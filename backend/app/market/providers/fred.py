"""FRED (Federal Reserve Economic Data) macro series provider.

FRED serves the same history through two structurally different endpoints, and this module talks to
both:

* **Keyed JSON** -- ``https://api.stlouisfed.org/fred/series/observations``. Needs ``api_key``, and
  answers with ``{"observations": [{"date": ..., "value": ...}, ...]}``.
* **Keyless CSV** -- ``https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series>``. Needs no key at
  all and still returns the *full* history (16,854 rows back to 1962 for ``DGS10``). This is not a
  degraded fallback for when a key is missing; it is the same data over a different wire format, and
  :meth:`FredProvider.fetch_series` uses it outright whenever no key is configured.

Which endpoint is used is decided once, at call time, by whether ``api_key`` was supplied at
construction -- never renegotiated mid-request. A provider is a thin, stateless translator (see
``app.market.providers.base``); deciding to retry a failed keyed request against the keyless endpoint
is a fallback decision, and those belong to whatever assembles the macro snapshot, not to this class.
A bad key must therefore come back as a loud, typed, retryable error (see below), not get quietly
absorbed here.

Three details are load-bearing rather than incidental:

* **The two endpoints spell a missing observation differently.** JSON marks a gap with the string
  ``"."``; CSV marks the same gap with an *empty field* (``1993-01-18,``). Both must become
  ``MacroPoint(value=None)``. ``tests/fixtures/macro/fred_json_dgs10.json`` and
  ``fred_missing_rows.csv`` capture the same real gap (1993-01-18, MLK Day) in each convention.
  Coercing either spelling to ``0.0`` draws the 10-year yield collapsing to zero on every market
  holiday -- 719 rows of it in ``DGS10`` alone.
* **The User-Agent must be honest, never a spoofed browser string.** FRED tarpits a Chrome-style UA:
  the request hangs until timeout and never returns, while an honest UA such as
  ``investing-dashboard/0.1`` gets the same data in under a second. Verified 3/3 vs 9/9 interleaved
  against the live endpoint. Do not "fix" this to look more like a browser.
* **A 400 from the JSON API can mean two very different things.** An unknown ``series_id`` and a
  rejected ``api_key`` both come back as HTTP 400 with a JSON error body -- only ``error_message``
  tells them apart (see ``fred_json_unknown_series.json`` and ``fred_json_bad_key.json``). The first
  is :class:`~app.market.providers.base.SymbolNotFound` (terminal: no series became real by trying
  again). The second is :class:`~app.market.providers.base.ProviderResponseError` (retryable
  elsewhere): a bad key must not look like a missing series, because a missing series is treated as
  permanent and a bad key is a config problem that a human can fix five minutes from now. The CSV
  endpoint answers an unknown series with a plain HTTP 404, which maps to the same
  :class:`SymbolNotFound`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

import httpx

from app.market.macro_models import MacroPoint, MacroSeries, MacroSource, MacroUnit
from app.market.models import MarketWarning
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
)

__all__ = ["FredProvider"]

_JSON_URL: Final[str] = "https://api.stlouisfed.org/fred/series/observations"
_CSV_URL: Final[str] = "https://fred.stlouisfed.org/graph/fredgraph.csv"

#: FRED tarpits requests that carry a browser-shaped User-Agent -- see the module docstring. Do not
#: replace this with anything that looks like Chrome/Firefox/Safari.
_USER_AGENT: Final[str] = "investing-dashboard/0.1"

#: How the JSON API spells a published gap in the series. The CSV endpoint spells the same gap as an
#: empty field instead -- see :meth:`FredProvider._parse_csv`.
_JSON_GAP: Final[str] = "."

#: Expected first column of the CSV header, e.g. ``observation_date,DGS10``. The second column name
#: (the series id) is not checked -- FRED's own casing of it does not always match the id used to
#: request it, and the first column is sufficient to recognise "this is not the CSV we expect".
_CSV_DATE_COLUMN: Final[str] = "observation_date"


class FredProvider:
    """Macro series from FRED, keyed JSON when an API key is configured, keyless CSV otherwise."""

    name = "fred"

    def __init__(self, client: httpx.Client, *, api_key: str | None = None) -> None:
        self._client = client
        self._api_key = api_key

    def fetch_series(
        self, series_id: str, *, start: dt.date | None = None, unit: MacroUnit = MacroUnit.PERCENT
    ) -> MacroSeries:
        points = (
            self._fetch_json(series_id, start=start)
            if self._api_key
            else self._fetch_csv(series_id, start=start)
        )

        # Both endpoints already return observations in ascending date order, but sorting here is
        # cheap insurance against a future response that doesn't, and the subsequent filter needs
        # ascending order to be meaningful anyway.
        points.sort(key=lambda point: point.date)
        if start is not None:
            points = [point for point in points if point.date >= start]

        warnings: list[MarketWarning] = []
        if not points:
            # A caller who gets an empty list with no explanation cannot tell "this series has not
            # started yet", "the requested window is entirely before its first observation", and "the
            # upstream silently returned nothing" apart. All three render identically as a blank
            # sparkline, so the distinction has to travel as a warning or it is lost.
            window = f" on or after {start.isoformat()}" if start is not None else ""
            warnings.append(
                MarketWarning(
                    kind="short_history",
                    message=f"fred returned no observations for {series_id}{window}",
                )
            )

        return MacroSeries(
            series_id=series_id,
            # FRED's observations endpoint does not carry the series' human title -- that lives on a
            # separate /fred/series endpoint this provider does not call, so the id doubles as the
            # title. Callers that want a friendlier label (e.g. MacroTile.label) supply their own.
            title=series_id,
            unit=unit,
            source=MacroSource.FRED,
            points=points,
            warnings=warnings,
            fetched_at=dt.datetime.now(dt.UTC),
        )

    # -- Keyed JSON endpoint --------------------------------------------------

    def _fetch_json(self, series_id: str, *, start: dt.date | None) -> list[MacroPoint]:
        params: dict[str, str] = {
            "api_key": self._api_key or "",
            "file_type": "json",
            "series_id": series_id,
        }
        if start is not None:
            params["observation_start"] = start.isoformat()

        response = self._get(_JSON_URL, params, series_id)

        if response.status_code == 400:
            self._raise_for_json_400(series_id, response)
        if response.status_code == 404:
            raise SymbolNotFound(f"fred has no series {series_id!r}", provider=self.name)
        self._raise_for_status(response, series_id)

        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"fred JSON response for {series_id} was not valid JSON", provider=self.name
            ) from exc

        observations = payload.get("observations")
        if not isinstance(observations, list):
            raise ProviderResponseError(
                f"fred JSON response for {series_id} had no 'observations' list", provider=self.name
            )
        return [self._json_point(series_id, obs) for obs in observations]

    def _raise_for_json_400(self, series_id: str, response: httpx.Response) -> None:
        """Tell an unknown series apart from a rejected api_key -- see the module docstring.

        Both are HTTP 400 with a JSON body shaped ``{"error_code": 400, "error_message": "..."}``,
        and the message is the only thing that differs (captured live in
        ``fred_json_unknown_series.json`` and ``fred_json_bad_key.json``).
        """
        try:
            body: Any = response.json()
        except ValueError:
            body = {}
        message = str(body.get("error_message", "")) if isinstance(body, dict) else ""
        lowered = message.lower()
        if "series_id" in lowered:
            raise SymbolNotFound(
                f"fred does not recognise the series {series_id!r}: {message}", provider=self.name
            )
        if "api_key" in lowered:
            raise ProviderResponseError(
                f"fred rejected the configured api_key while fetching {series_id}: {message}",
                provider=self.name,
            )
        raise ProviderResponseError(
            f"fred returned HTTP 400 for {series_id}: {message or body}", provider=self.name
        )

    def _json_point(self, series_id: str, obs: object) -> MacroPoint:
        if not isinstance(obs, dict):
            raise ProviderResponseError(
                f"fred observation for {series_id} was not an object: {obs!r}", provider=self.name
            )
        date_str = obs.get("date")
        if not isinstance(date_str, str):
            raise ProviderResponseError(
                f"fred observation for {series_id} is missing a date: {obs!r}", provider=self.name
            )
        try:
            date = dt.date.fromisoformat(date_str)
        except ValueError as exc:
            raise ProviderResponseError(
                f"fred observation date {date_str!r} for {series_id} is not ISO-8601",
                provider=self.name,
            ) from exc

        raw_value = obs.get("value")
        if raw_value == _JSON_GAP:
            return MacroPoint(date=date, value=None)

        # A wrong *type* and an unparseable *string* are the same class of malformed response, so
        # they share one message. The type check is separate from the `float()` because a missing
        # `"value"` key yields `None`, and `None` must stay loud rather than fall through: FRED
        # marks a real gap with `"."` here (and an empty field on the CSV endpoint), never by
        # omitting the key, so a missing key means the payload is not what we think it is. Treating
        # it as a gap would quietly turn a broken response into a chart full of holidays.
        malformed = (
            f"fred observation value {raw_value!r} for {series_id} on {date} is neither numeric "
            f"nor the gap marker {_JSON_GAP!r}"
        )
        if not isinstance(raw_value, (str, int, float)) or isinstance(raw_value, bool):
            raise ProviderResponseError(malformed, provider=self.name)
        try:
            value = float(raw_value)
        except ValueError as exc:
            raise ProviderResponseError(malformed, provider=self.name) from exc
        return MacroPoint(date=date, value=value)

    # -- Keyless CSV endpoint ---------------------------------------------

    def _fetch_csv(self, series_id: str, *, start: dt.date | None) -> list[MacroPoint]:
        # `start` is accepted for symmetry with the JSON path but is not sent as a query param here:
        # the CSV endpoint's date-window params are unconfirmed against the live API, whereas serving
        # the full history and filtering client-side (done uniformly in fetch_series) is guaranteed
        # correct regardless of what the server does with extra params.
        response = self._get(_CSV_URL, {"id": series_id}, series_id)

        if response.status_code == 404:
            raise SymbolNotFound(f"fred has no series {series_id!r}", provider=self.name)
        self._raise_for_status(response, series_id)

        return self._parse_csv(response.text, series_id)

    def _parse_csv(self, text: str, series_id: str) -> list[MacroPoint]:
        lines = text.splitlines()
        if not lines:
            raise ProviderResponseError(f"fred CSV for {series_id} was empty", provider=self.name)

        header = lines[0].split(",")
        if len(header) != 2 or header[0].strip().lower() != _CSV_DATE_COLUMN:
            raise ProviderResponseError(
                f"fred CSV for {series_id} has an unexpected header {lines[0]!r}; expected "
                f"'{_CSV_DATE_COLUMN},<SERIES_ID>'",
                provider=self.name,
            )

        points: list[MacroPoint] = []
        for line in lines[1:]:
            if not line.strip():
                continue
            fields = line.split(",")
            if len(fields) != 2:
                raise ProviderResponseError(
                    f"fred CSV row {line!r} for {series_id} does not have exactly 2 columns",
                    provider=self.name,
                )
            date_str, value_str = fields
            try:
                date = dt.date.fromisoformat(date_str.strip())
            except ValueError as exc:
                raise ProviderResponseError(
                    f"fred CSV date {date_str!r} for {series_id} is not ISO-8601", provider=self.name
                ) from exc

            value_str = value_str.strip()
            if value_str == "":
                # The CSV endpoint's gap marker -- an empty field, not the JSON API's "." (see the
                # module docstring). tests/fixtures/macro/fred_missing_rows.csv exercises this.
                points.append(MacroPoint(date=date, value=None))
                continue
            try:
                value = float(value_str)
            except ValueError as exc:
                raise ProviderResponseError(
                    f"fred CSV value {value_str!r} for {series_id} on {date} is neither numeric nor "
                    "an empty gap marker",
                    provider=self.name,
                ) from exc
            points.append(MacroPoint(date=date, value=value))
        return points

    # -- Shared HTTP + error mapping ---------------------------------------

    def _get(self, url: str, params: dict[str, str], series_id: str) -> httpx.Response:
        try:
            return self._client.get(url, params=params, headers={"User-Agent": _USER_AGENT})
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"fred timed out fetching {series_id}", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"fred transport error fetching {series_id}: {exc}", provider=self.name
            ) from exc

    def _raise_for_status(self, response: httpx.Response, series_id: str) -> None:
        """Map the status codes both endpoints share. 400 and 404 are handled by each caller first,
        since their meaning differs per endpoint (see :meth:`_fetch_json` and :meth:`_fetch_csv`)."""
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"fred rate-limited the request for {series_id}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"fred returned {response.status_code} for {series_id}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"fred returned unexpected status {response.status_code} for {series_id}",
                provider=self.name,
            )
