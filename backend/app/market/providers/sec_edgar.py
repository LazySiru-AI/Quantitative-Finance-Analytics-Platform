"""SEC EDGAR fundamentals provider.

Two SEC-specific requirements sit ahead of the actual data:

* **A descriptive ``User-Agent`` is mandatory.** SEC's fair-access policy rejects generic or
  default HTTP client user agents with a 403; the default here follows their documented format
  (app name plus a contact address) and is overridable for a different deployment identity.
* **Symbols are resolved to a zero-padded 10-digit CIK before anything else.** The company-facts
  endpoint is keyed by CIK, not ticker, so every call first consults the ticker map at
  ``https://www.sec.gov/files/company_tickers.json`` -- about 10k rows, changes rarely, so it is
  parsed once and cached on the instance rather than refetched per symbol.

**A symbol absent from the ticker map is the common case, not an edge case.** This portfolio is
mostly ETFs, and ETFs file nothing on this endpoint -- they are registered investment companies,
not the operating companies the SEC's XBRL financial-statement pipeline covers. It is reported as
:class:`~app.market.providers.base.SymbolNotFound`, typed the same way every other provider spells
"there is nothing here," with a message that says plainly why.

**A 404 on the ticker map itself is not a symbol-not-found.** ``_TICKERS_URL`` is one shared,
symbol-agnostic resource fetched once and cached on the instance -- it has no concept of "AAPL" or
"QQQ" to not find. A 404 there means the endpoint moved or is down, and :meth:`_get_json` reports it
as :class:`~app.market.providers.base.ProviderResponseError` (retryable elsewhere), never
:class:`SymbolNotFound` (terminal). Conflating the two used to make *every* symbol -- including real
filers like AAPL -- fail as "does not exist" the moment the ticker map 404s.
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from app.config import get_settings
from app.market.fundamentals import Fundamentals, build_fundamentals
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
    SymbolNotFound,
)

__all__ = ["SecEdgarProvider"]

_TICKERS_URL: Final[str] = "https://www.sec.gov/files/company_tickers.json"
_FACTS_URL: Final[str] = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"


def _default_user_agent() -> str:
    """SEC's mandatory contact-address User-Agent, read from settings at call time.

    Not a module-level `Final` constant -- this used to be a literal containing a real address.
    Reading `get_settings().contact_email` here, inside a function called from `__init__` rather
    than baked into the constructor's default-argument value, means each new provider picks up
    whatever `.env`/`INVDASH_CONTACT_EMAIL` says *at construction time* instead of freezing
    whatever was set (or unset) the moment this module was first imported.
    """
    return get_settings().contact_email


class SecEdgarProvider:
    """Reported financials from SEC EDGAR's XBRL company-facts API."""

    name = "sec_edgar"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 15.0,
        user_agent: str | None = None,
    ) -> None:
        self._client = client or httpx.Client(timeout=timeout)
        self._user_agent = user_agent if user_agent is not None else _default_user_agent()
        # symbol (upper) -> zero-padded 10-digit CIK. None until the first lookup; ~10k rows and
        # changes rarely enough that refetching per call would be pure waste.
        self._ticker_map: dict[str, str] | None = None

    def _get_json(self, url: str, *, symbol_not_found_message: str | None = None) -> Any:
        """Fetch and parse one JSON endpoint, mapping transport and status failures.

        `symbol_not_found_message` is what turns a 404 into :class:`SymbolNotFound` rather than a
        retryable failure -- pass it only when *this specific request* is a per-symbol lookup, i.e.
        only for the facts endpoint (see :meth:`fetch_fundamentals`). Leaving it unset, as
        :meth:`_load_ticker_map` does, is deliberate: a 404 on the ticker map means the shared,
        symbol-agnostic infrastructure endpoint is unreachable or has moved, not that any particular
        ticker does not exist. Collapsing both cases into one blanket "404 means SymbolNotFound" used
        to make `fetch_fundamentals("AAPL")` -- a real, filing company -- raise `SymbolNotFound` the
        moment the ticker map itself 404s, and `SymbolNotFound` is documented in
        `app.market.registry` as **terminal**: the registry does not retry it and the caller is told
        the ticker does not exist. An infrastructure outage is the opposite of that.
        """
        try:
            response = self._client.get(url, headers={"User-Agent": self._user_agent})
        except httpx.TimeoutException as exc:
            raise ProviderUnavailable(
                f"sec_edgar timed out fetching {url}", provider=self.name
            ) from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailable(
                f"sec_edgar transport error fetching {url}: {exc}", provider=self.name
            ) from exc

        if response.status_code == 404:
            if symbol_not_found_message is not None:
                raise SymbolNotFound(symbol_not_found_message, provider=self.name)
            raise ProviderResponseError(
                f"sec_edgar returned 404 for {url} -- this is shared, symbol-agnostic "
                "infrastructure (the ticker map), not a per-company lookup, so a 404 here means the "
                "endpoint itself is unreachable or has moved, not that any ticker does not exist",
                provider=self.name,
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            raise RateLimited(
                f"sec_edgar rate-limited {url}",
                provider=self.name,
                retry_after=float(retry_after) if retry_after else None,
            )
        if response.status_code >= 500:
            raise ProviderUnavailable(
                f"sec_edgar returned {response.status_code} for {url}", provider=self.name
            )
        if response.status_code >= 400:
            raise ProviderResponseError(
                f"sec_edgar returned unexpected status {response.status_code} for {url}",
                provider=self.name,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderResponseError(
                f"sec_edgar response from {url} was not valid JSON", provider=self.name
            ) from exc

    def _load_ticker_map(self) -> dict[str, str]:
        if self._ticker_map is None:
            payload = self._get_json(_TICKERS_URL)
            mapping: dict[str, str] = {}
            for row in payload.values():
                ticker = row.get("ticker")
                cik = row.get("cik_str")
                if ticker and cik is not None:
                    mapping[str(ticker).upper()] = f"{int(cik):010d}"
            self._ticker_map = mapping
        return self._ticker_map

    def fetch_fundamentals(self, symbol: str) -> Fundamentals:
        cik10 = self._load_ticker_map().get(symbol.upper())
        if cik10 is None:
            raise SymbolNotFound(
                f"{symbol} is not in the SEC ticker map. This is the expected result for most of "
                "this portfolio, which is ETFs: they do not file the XBRL financial statements "
                "this endpoint covers.",
                provider=self.name,
            )
        payload = self._get_json(
            _FACTS_URL.format(cik10=cik10),
            symbol_not_found_message=(
                f"sec_edgar has no XBRL company facts for {symbol} (CIK {cik10}) -- the filer has a "
                "CIK in SEC's ticker map but nothing on the company-facts endpoint, which happens for "
                "a newly registered filer or one that does not file XBRL financial statements"
            ),
        )
        return build_fundamentals(payload, symbol)
