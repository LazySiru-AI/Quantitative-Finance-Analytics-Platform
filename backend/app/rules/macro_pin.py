"""Freeze the macro series a round reads, so the round can be re-run and get the same answer.

**Why a bar store is not enough.** ``PROTOCOL.md`` section 8 requires runs to be deterministic: the
same cards, persona, window and store give byte-identical results. Bars satisfy that because the
store is a file on disk that only grows. **A macro series does not.** FRED serves the *currently
revised* value against a reference date, so refetching ``CPILFESL`` next month can return a different
number for the same July observation -- and ``app.rules.macro_binding`` resolves that to the same
*eligibility date*, which means the join is stable while the value underneath it is not. A round that
fetched live at run time would be reproducible in its dates and irreproducible in its answers, which
is the worse of the two failure modes because it looks fine.

So a round pins: every series it will read is fetched once, written to a file, and read from that file
thereafter. ``strategy-program/ROUND-21-PLAN.md`` section 2c requires this before the round runs and
says plainly that a round discovered to be unpinned after the fact is invalidated rather than quietly
re-scored.

**A pin is immutable, and that is enforced rather than documented.** :func:`write_pin` refuses to
overwrite an existing file. A mutable pin is not a pin: the whole guarantee is that the bytes a round
was scored against are still on disk, and an overwrite silently replaces the evidence for every result
already published from it.

**What a pin does not fix.** It freezes *which* revision of the data the round used; it does not make
that revision point-in-time. The values are still today's view of history, not what was on the wire on
each historical date -- closing that needs FRED's ALFRED vintage archive, which the provider does not
speak. See :mod:`app.rules.macro_binding`'s own note on the revision leak; pinning and release-date
binding close two different holes and neither closes the other.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.market.macro_models import MacroSeries, MacroUnit
from app.rules.nodes import MacroField

__all__ = [
    "MACRO_PIN_ENV",
    "MACRO_UNITS",
    "MissingPinError",
    "PinExistsError",
    "PinIntegrityError",
    "active_pin",
    "clear_pin_cache",
    "fetch_series_for_pin",
    "pin_digest",
    "read_pin",
    "write_pin",
]

#: Environment variable naming the pin the run path should read.
#:
#: An environment variable rather than a `Settings` field, deliberately and for one round only: a pin
#: belongs to a *round*, not to an installation, and `INVDASH_`-prefixed settings are process-wide
#: configuration. Adding a settings field would also mean editing `app.config` while it is being
#: changed elsewhere. If macro rounds become routine this should move onto the round's own manifest
#: rather than staying here.
MACRO_PIN_ENV = "INVDASH_MACRO_PIN"

#: What each series physically is, needed because `MacroSeries.unit` decides formatting and change
#: arithmetic downstream.
#:
#: **Held here rather than read from `app.market.macro._SERIES_CATALOG`**, which covers only `DGS10`,
#: `T10Y2Y`, `DCOILWTICO` and `DCOILBRENTEU` -- four of this table's seven fields are absent from it,
#: so `load_series` raises `SeriesNotFound` for `T10YIE`, `PCEPI`, `PCEPILFE` and `CPILFESL`. Reusing
#: that catalog would also drag in its `as_of` truncation, which selects on the *reference* date and
#: is exactly the join `app.rules.macro_binding` exists to avoid.
#:
#: The three price indices are `INDEX`, not `PERCENT`: they are index levels (2026-07 core CPI prints
#: 336.789), not rates. Mirrored against `MacroField` by a test.
MACRO_UNITS: Mapping[MacroField, MacroUnit] = MappingProxyType(
    {
        MacroField.DGS10: MacroUnit.PERCENT,
        MacroField.T10Y2Y: MacroUnit.PERCENT_SPREAD,
        MacroField.T10YIE: MacroUnit.PERCENT,
        MacroField.DCOILWTICO: MacroUnit.USD,
        MacroField.PCEPI: MacroUnit.INDEX,
        MacroField.PCEPILFE: MacroUnit.INDEX,
        MacroField.CPILFESL: MacroUnit.INDEX,
    }
)

#: Bumped when the on-disk shape changes. A pin written by an older build is refused rather than
#: guessed at -- the same principle `app.paperdesk.desk._DISK_CACHE_VERSION` states: a stale payload
#: that still parses is worse than one that fails loudly.
PIN_FORMAT_VERSION = 1


class PinExistsError(FileExistsError):
    """A pin already exists at that path.

    Raised rather than overwritten, because an overwrite destroys the evidence for every result
    already scored against the old bytes. Re-pinning is a deliberate act: delete the file, and accept
    that every figure produced from it is now unreproducible.
    """


class PinIntegrityError(ValueError):
    """A pin's recorded digest does not match the series it contains.

    Means the file was edited after it was written, which is the one thing a pin exists to make
    impossible. The round it belongs to cannot be trusted to have used the data it claims.
    """


def pin_digest(series: Mapping[MacroField, MacroSeries]) -> str:
    """A stable hash over every observation in the pin.

    Covers series id, and each ``(date, value)`` pair. **Excludes ``fetched_at``**, deliberately: two
    pins of identical data taken a minute apart should compare equal, because what a round depends on
    is the observations, not the clock reading when they were downloaded. Including the timestamp
    would make every pin unique and the digest useless as an equality test.
    """
    hasher = hashlib.sha256()
    for field in sorted(series, key=lambda f: f.value):
        macro = series[field]
        hasher.update(f"{field.value}:{macro.series_id}:".encode())
        for point in macro.points:
            hasher.update(f"{point.date.isoformat()}={point.value!r};".encode())
    return hasher.hexdigest()


def fetch_series_for_pin(
    fields: Sequence[MacroField], *, provider: Any
) -> dict[MacroField, MacroSeries]:
    """Fetch each field's full history from ``provider``, ready to be written to a pin.

    ``provider`` is an :class:`~app.market.providers.fred.FredProvider` (typed loosely so this module
    does not import the provider package just for an annotation). Called once, at pin time; nothing
    in the run path ever calls it, which is the point.
    """
    out: dict[MacroField, MacroSeries] = {}
    for field in dict.fromkeys(fields):
        unit = MACRO_UNITS.get(field)
        if unit is None:
            raise KeyError(
                f"macro field {field.value!r} has no MACRO_UNITS entry; add it rather than defaulting, "
                f"because the unit decides how every downstream change figure is computed"
            )
        out[field] = provider.fetch_series(field.value, unit=unit)
    return out


def write_pin(
    path: Path,
    series: Mapping[MacroField, MacroSeries],
    *,
    created_at: dt.datetime,
    note: str = "",
) -> str:
    """Write the pin and return its digest. Refuses to overwrite an existing file.

    ``created_at`` is passed in rather than read from the clock here, so a caller that needs a
    reproducible file (a test, a replay) can supply one. It is recorded for the reader's benefit and
    is deliberately not part of the digest -- see :func:`pin_digest`.
    """
    if path.exists():
        raise PinExistsError(
            f"a macro pin already exists at {path}; refusing to overwrite it. Every result scored "
            f"against the existing pin depends on these exact bytes, so re-pinning means deleting "
            f"the file deliberately and accepting that those figures become unreproducible."
        )
    digest = pin_digest(series)
    payload: dict[str, Any] = {
        "format_version": PIN_FORMAT_VERSION,
        "created_at": created_at.isoformat(),
        "digest": digest,
        "note": note,
        "series": {
            field.value: json.loads(macro.model_dump_json()) for field, macro in series.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return digest


def read_pin(path: Path) -> dict[MacroField, MacroSeries]:
    """Load a pin. **Never touches the network**, and verifies the digest before returning.

    A digest mismatch raises rather than warns: a pin that has been edited cannot support the claim
    its round makes about what data was used, and continuing would let a hand-edited series through
    under the authority of a recorded hash.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    version = payload.get("format_version")
    if version != PIN_FORMAT_VERSION:
        raise PinIntegrityError(
            f"macro pin at {path} is format version {version!r}, this build reads "
            f"{PIN_FORMAT_VERSION!r}; refusing to guess at an older shape"
        )
    series: dict[MacroField, MacroSeries] = {}
    for name, raw in payload["series"].items():
        try:
            field = MacroField(name)
        except ValueError as exc:
            raise PinIntegrityError(
                f"macro pin at {path} contains series {name!r}, which is not a MacroField"
            ) from exc
        series[field] = MacroSeries.model_validate(raw)

    recorded = payload.get("digest")
    actual = pin_digest(series)
    if recorded != actual:
        raise PinIntegrityError(
            f"macro pin at {path} records digest {recorded!r} but its series hash to {actual!r}; "
            f"the file has been modified since it was written, so no result scored against it can "
            f"be trusted to have used the data it claims"
        )
    return series


class MissingPinError(RuntimeError):
    """A rule needs macro data and no pin is configured.

    Raised rather than falling back to a live fetch, which is the whole point: a live fetch would
    make the run reproducible in its dates and irreproducible in its values, and would do so
    silently. See this module's docstring.
    """


#: Pins keyed by ``(resolved path, mtime_ns, size)``. A pin is immutable by construction
#: (:func:`write_pin` refuses to overwrite), so caching by path alone would be *almost* safe -- the
#: mtime and size are in the key anyway, because "almost safe" and "safe" differ exactly when
#: somebody deletes a pin and writes a new one at the same path, which is the supported way to
#: re-pin.
_PIN_CACHE: dict[tuple[str, int, int], dict[MacroField, MacroSeries]] = {}


def clear_pin_cache() -> None:
    """Drop the in-process pin cache. For tests, and for a long-lived process told to re-read."""
    _PIN_CACHE.clear()


def active_pin(path: Path | str | None = None) -> dict[MacroField, MacroSeries]:
    """The pin this run should read, from ``path`` or from :data:`MACRO_PIN_ENV`.

    Reads and verifies once per distinct file, then serves from memory: a round evaluates many cards
    against one pin and re-parsing a four-megabyte JSON per card would dominate its runtime.

    Raises :class:`MissingPinError` when nothing is configured, rather than returning an empty
    mapping. An empty mapping would reach :func:`app.rules.macro_binding.bind_macro` and raise there
    with a message about a missing series, which describes the symptom rather than the cause.
    """
    raw = str(path) if path is not None else os.environ.get(MACRO_PIN_ENV, "")
    if not raw:
        raise MissingPinError(
            f"this rule reads a macro series, but no macro pin is configured. Set "
            f"{MACRO_PIN_ENV} to a pin written by app.rules.macro_pin.write_pin. A live fetch is "
            f"deliberately not attempted: FRED serves revised values against the same reference "
            f"dates, so an unpinned run is reproducible in its dates and not in its answers."
        )
    resolved = Path(raw)
    if not resolved.is_file():
        raise MissingPinError(f"{MACRO_PIN_ENV} points at {resolved}, which is not a file")
    stat = resolved.stat()
    key = (str(resolved.resolve()), stat.st_mtime_ns, stat.st_size)
    cached = _PIN_CACHE.get(key)
    if cached is None:
        cached = read_pin(resolved)
        _PIN_CACHE[key] = cached
    return cached
