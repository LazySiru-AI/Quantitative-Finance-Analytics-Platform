"""Pin the bar store a round actually ran against, and compare a later store to that pin.

This is the fix for **DEFECTS.md D6**, deferred at the time it was found because implementing it
mid-integration is the kind of instrument change ``PROTOCOL.md`` refuses. It is implemented now, at
a generation boundary, with the autonomous loop stopped.

**The defect, restated.** Rounds 11 and 12 both open by asserting the evidence base is frozen. Round
11's §0 says the bar store is *"unchanged since round 9 ran -- verified, not assumed: SPY holds
8,445 rows ending 2026-08-18"*. That was true when written. By the end of the same working day the
store held SPY 8,448 rows ending 2026-08-21, because ``data/store/`` is gitignored mutable state and
``app.market.store.ensure_series`` syncs fresh bars whenever a page asks for them. **Verifying the
dashboard advanced the data the competition is scored on.** No figure changed -- every computation is
explicitly bounded -- but the *claim* broke, and the same reassuring sentence still sits at the top
of two round documents.

**Why a row count quoted in prose cannot be the reference.** The comparison round 11 made was
against a number transcribed from round 9's write-up. That has an expiry date nobody stated, and
nothing detects when it passes: the sentence goes on reading as a verification long after it stopped
being one. The fix is not a better sentence. It is to make the round record its own evidence base as
*data*, at run time, so a later round compares against a measurement rather than against prose.

**What is pinned, and what is deliberately not.** Row count and last bar date per symbol -- the two
numbers that move when a sync appends. Not the bytes, not a hash of the Parquet: a store that
rewrote a partition identically is not a changed evidence base, and a hash would report it as one.
Not ``fetched_at`` either, which changes on every sync *including the ones that appended nothing*.

**Drift is reported, never judged.** :func:`compare` says which symbols moved and by how much; it has
no opinion about whether a round is invalidated. That is a reading of the round's own bounds -- round
11's ladder windows all close on or before 2026-02-13, so appended bars provably cannot reach them --
and it belongs in the round document, written by a person, not in a tool's exit code.

Loaded by file path in tests (``strategy-program`` is not a legal package name); see
``tests/test_storestate.py``.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings, get_settings
from app.db import duck
from app.market.models import Interval

__all__ = [
    "STORE_STATE_KEY",
    "SYMBOL_DRIFT_KINDS",
    "StoreDrift",
    "StoreState",
    "SymbolDrift",
    "SymbolState",
    "capture",
    "compare",
    "describe_drift",
    "state_from_json",
    "state_to_json",
]

#: The scorecard's top-level key. Named here rather than spelled inline in ``score.py`` so the writer
#: and any later reader cannot drift apart on it.
STORE_STATE_KEY = "store_state"

#: How a symbol's store row can differ between a pin and a later capture. ``appended`` is the
#: expected one -- ordinary use of the application syncing fresh bars. ``shrank`` and ``rewritten``
#: are not expected and are worth a look: a store that lost rows, or kept its count while moving its
#: last bar, is not the same evidence base in a way "3 rows were added" does not cover.
SYMBOL_DRIFT_KINDS = ("appended", "shrank", "rewritten", "added", "removed")


@dataclass(frozen=True, slots=True)
class SymbolState:
    """What the store holds for one symbol at one interval."""

    symbol: str
    rows: int
    last_bar: dt.date | None
    """``None`` only when the partition exists but holds no rows -- distinct from the symbol being
    absent entirely, which is represented by having no :class:`SymbolState` at all."""


@dataclass(frozen=True, slots=True)
class StoreState:
    """A whole store's pin: every symbol it held, when the pin was taken, and at which interval."""

    captured_at: dt.datetime
    """Timezone-aware UTC. This is when the pin was *taken*, and it is the one thing here that is
    about the pin rather than about the store."""
    interval: str
    symbols: tuple[SymbolState, ...]
    """Ordered by symbol, so two pins serialise comparably and a diff of the JSON is readable."""

    def by_symbol(self) -> dict[str, SymbolState]:
        return {state.symbol: state for state in self.symbols}

    @property
    def total_rows(self) -> int:
        return sum(state.rows for state in self.symbols)


@dataclass(frozen=True, slots=True)
class SymbolDrift:
    """One symbol's difference between a pin and a later capture."""

    symbol: str
    kind: str
    """One of :data:`SYMBOL_DRIFT_KINDS`."""
    recorded_rows: int | None
    current_rows: int | None
    recorded_last_bar: dt.date | None
    current_last_bar: dt.date | None

    @property
    def row_delta(self) -> int:
        """Signed change in row count. ``0`` for a symbol that appeared or vanished, where a delta is
        not the interesting number -- read :attr:`kind` for those."""
        if self.recorded_rows is None or self.current_rows is None:
            return 0
        return self.current_rows - self.recorded_rows


@dataclass(frozen=True, slots=True)
class StoreDrift:
    """The comparison of a later store against a round's pin."""

    recorded_at: dt.datetime
    compared_at: dt.datetime
    interval: str
    drifted: tuple[SymbolDrift, ...]
    unchanged: int
    """How many symbols matched exactly. Reported because "12 symbols moved" means something
    different against 20 symbols than against 688."""

    @property
    def changed(self) -> bool:
        return bool(self.drifted)

    @property
    def rows_added(self) -> int:
        return sum(d.row_delta for d in self.drifted if d.row_delta > 0)


def capture(
    *,
    symbols: Sequence[str] | None = None,
    interval: Interval = Interval.DAY,
    settings: Settings | None = None,
) -> StoreState:
    """Pin what the store holds right now.

    ``symbols=None`` pins every symbol at ``interval`` -- the right default, because D6's broken claim
    was about the store as a whole ("the bar store is unchanged"), not about one round's universe. A
    caller wanting a narrower pin can pass one.

    **One grouped query, not one query per symbol.** The store holds 688 daily symbols at the time of
    writing; calling :func:`app.market.store.coverage` per symbol would open 688 Parquet files to
    compute two aggregates each. DuckDB reads the hive partition in a single pass instead, which is
    what makes pinning cheap enough to do on every round rather than only when someone remembers.
    """
    cfg = settings or get_settings()
    bars_dir = Path(cfg.bars_dir)
    wanted = (
        [s.upper() for s in symbols]
        if symbols is not None
        else duck.stored_symbols(bars_dir, interval)
    )
    captured_at = dt.datetime.now(dt.UTC)

    if not wanted:
        return StoreState(captured_at=captured_at, interval=interval.value, symbols=())

    rows_by_symbol: dict[str, tuple[int, dt.date | None]] = {}
    root = bars_dir / f"interval={interval.value}"
    if root.exists():
        pattern = str(root / "symbol=*" / "bars.parquet").replace("\\", "/")
        # Not `read_only=True`: `duck.connect()` with no path opens an in-memory database, and
        # DuckDB refuses to launch one read-only. The query below is a read regardless -- it only
        # ever scans Parquet through `read_parquet`.
        #
        # This deliberately does not go through `app.market.store.coverage` per symbol, and the
        # per-partition lock that would have taken is not the protection it looks like: `_WRITE_LOCKS`
        # is an in-process dict, so a scorer running as its own process is unsynchronised with a live
        # backend either way. The choice is therefore only about speed, and one grouped scan over the
        # hive partition beats 688 file opens by enough to make pinning routine rather than optional.
        #
        # A failure here **raises**. An empty pin would serialise as a real measurement saying the
        # store held nothing, which is the exact "empty result that reads like nothing happened"
        # failure this defect is about; the caller omits the key instead. See `score.py`.
        # **Grouped by filename, not by `hive_partitioning = true`.** The obvious spelling is the hive
        # one, and it fails on this store: it holds `BZ=F` (Brent futures), whose partition directory
        # is `symbol=BZ=F`, and DuckDB cannot split that into one key and one value --
        # `Binder Error: Hive partition mismatch ... key "symbol" not found`, which takes down the
        # scan for all 688 symbols, not just that one. Parsing the directory name here instead is
        # exactly what `duck.stored_symbols` already does, so the two agree by construction on every
        # symbol the hive parser would choke on.
        with duck.connect() as conn:
            result = conn.execute(
                "SELECT filename, COUNT(*) AS n_rows, MAX(ts) AS last_ts "
                "FROM read_parquet(?, filename = true) "
                "GROUP BY filename",
                [pattern],
            ).fetchall()
        for filename, count, last_ts in result:
            symbol = Path(str(filename)).parent.name.removeprefix("symbol=").upper()
            last_date: dt.date | None = None
            if last_ts is not None:
                last_date = last_ts.date() if hasattr(last_ts, "date") else last_ts
            rows_by_symbol[symbol] = (int(count), last_date)

    states = tuple(
        SymbolState(
            symbol=symbol,
            rows=rows_by_symbol.get(symbol, (0, None))[0],
            last_bar=rows_by_symbol.get(symbol, (0, None))[1],
        )
        for symbol in sorted(set(wanted))
        if symbol in rows_by_symbol
    )
    return StoreState(captured_at=captured_at, interval=interval.value, symbols=states)


def state_to_json(state: StoreState) -> dict[str, Any]:
    """The pin, as it sits inside ``scorecard.json``.

    Symbols are a mapping rather than a list so a human diffing two scorecards sees one changed line
    per changed symbol, instead of a re-indexed array.
    """
    return {
        "captured_at": state.captured_at.isoformat(),
        "interval": state.interval,
        "symbol_count": len(state.symbols),
        "total_rows": state.total_rows,
        "symbols": {
            s.symbol: {
                "rows": s.rows,
                "last_bar": s.last_bar.isoformat() if s.last_bar else None,
            }
            for s in state.symbols
        },
    }


def state_from_json(payload: Mapping[str, Any]) -> StoreState:
    """Read a pin back out of a scorecard. The inverse of :func:`state_to_json`."""
    # `.get("symbols", {})`, never `.get("symbols") or {}`. The two differ on exactly the case that
    # matters: `or` is falsy-triggered, so an empty *list* would coerce to `{}` and sail through the
    # type check below as a pin that legitimately measured nothing -- this module's own headline
    # failure, an empty result reading as a measurement, reintroduced in its parser. The default
    # form fires only when the key is absent, so present-but-wrong still reaches the raise.
    raw_symbols = payload.get("symbols", {})
    if not isinstance(raw_symbols, Mapping):
        raise ValueError(
            f"store_state.symbols must be a mapping of symbol -> {{rows, last_bar}}, "
            f"got {type(raw_symbols).__name__}"
        )

    symbols = []
    for symbol, entry in sorted(raw_symbols.items()):
        if not isinstance(entry, Mapping):
            raise ValueError(f"store_state.symbols[{symbol!r}] must be a mapping")
        last_bar_raw = entry.get("last_bar")
        symbols.append(
            SymbolState(
                symbol=str(symbol).upper(),
                rows=int(entry.get("rows", 0)),
                last_bar=dt.date.fromisoformat(last_bar_raw) if last_bar_raw else None,
            )
        )

    captured_raw = payload.get("captured_at")
    if not isinstance(captured_raw, str):
        raise ValueError("store_state.captured_at must be an ISO-8601 string")

    return StoreState(
        captured_at=dt.datetime.fromisoformat(captured_raw),
        interval=str(payload.get("interval", Interval.DAY.value)),
        symbols=tuple(symbols),
    )


def _classify(recorded: SymbolState, current: SymbolState) -> str | None:
    if recorded.rows == current.rows and recorded.last_bar == current.last_bar:
        return None
    if current.rows > recorded.rows:
        return "appended"
    if current.rows < recorded.rows:
        return "shrank"
    # Same count, different last bar: the partition was rewritten rather than extended. Worth its own
    # name because "0 rows added" would otherwise read as "unchanged".
    return "rewritten"


def compare(recorded: StoreState, current: StoreState) -> StoreDrift:
    """How ``current`` differs from the pin in ``recorded``.

    Reports, never judges -- see the module docstring. A round reading this decides for itself
    whether the drift can reach its own bounded windows; usually it provably cannot.
    """
    recorded_map = recorded.by_symbol()
    current_map = current.by_symbol()

    drifted: list[SymbolDrift] = []
    unchanged = 0

    for symbol in sorted(set(recorded_map) | set(current_map)):
        before = recorded_map.get(symbol)
        after = current_map.get(symbol)

        if before is None and after is not None:
            drifted.append(
                SymbolDrift(
                    symbol=symbol,
                    kind="added",
                    recorded_rows=None,
                    current_rows=after.rows,
                    recorded_last_bar=None,
                    current_last_bar=after.last_bar,
                )
            )
            continue
        if before is not None and after is None:
            drifted.append(
                SymbolDrift(
                    symbol=symbol,
                    kind="removed",
                    recorded_rows=before.rows,
                    current_rows=None,
                    recorded_last_bar=before.last_bar,
                    current_last_bar=None,
                )
            )
            continue

        assert before is not None and after is not None
        kind = _classify(before, after)
        if kind is None:
            unchanged += 1
            continue
        drifted.append(
            SymbolDrift(
                symbol=symbol,
                kind=kind,
                recorded_rows=before.rows,
                current_rows=after.rows,
                recorded_last_bar=before.last_bar,
                current_last_bar=after.last_bar,
            )
        )

    return StoreDrift(
        recorded_at=recorded.captured_at,
        compared_at=current.captured_at,
        interval=recorded.interval,
        drifted=tuple(drifted),
        unchanged=unchanged,
    )


def describe_drift(drift: StoreDrift, *, limit: int = 12) -> str:
    """The drift as prose a round document can paste, naming symbols and deltas.

    This is the sentence D6 wanted in place of "the store is unchanged" -- one that cannot quietly
    become false, because it is generated from a comparison rather than transcribed from an earlier
    document.
    """
    if not drift.changed:
        return (
            f"bar store unchanged against the pin taken {drift.recorded_at.date()}: "
            f"{drift.unchanged} symbol(s) match on row count and last bar"
        )

    shown = drift.drifted[:limit]
    parts = []
    for d in shown:
        if d.kind == "added":
            parts.append(f"{d.symbol} added ({d.current_rows} rows)")
        elif d.kind == "removed":
            parts.append(f"{d.symbol} removed (was {d.recorded_rows} rows)")
        elif d.kind == "rewritten":
            parts.append(
                f"{d.symbol} rewritten ({d.recorded_rows} rows, last bar "
                f"{d.recorded_last_bar} -> {d.current_last_bar})"
            )
        else:
            parts.append(
                f"{d.symbol} {d.recorded_rows}->{d.current_rows} rows "
                f"(last bar {d.recorded_last_bar} -> {d.current_last_bar})"
            )
    more = len(drift.drifted) - len(shown)
    tail = f", and {more} more" if more > 0 else ""
    return (
        f"bar store DIFFERS from the pin taken {drift.recorded_at.date()}: "
        f"{len(drift.drifted)} symbol(s) moved, {drift.unchanged} unchanged -- "
        + "; ".join(parts)
        + tail
    )


def load_pin(scorecard_path: Path) -> StoreState | None:
    """The pin inside a scorecard, or ``None`` if that scorecard predates pinning.

    ``None`` is the honest answer for every round scored before this landed, and a caller comparing
    against it must say "round N recorded no pin" rather than "the store is unchanged".
    """
    payload = json.loads(Path(scorecard_path).read_text(encoding="utf-8"))
    raw = payload.get(STORE_STATE_KEY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"{scorecard_path}: {STORE_STATE_KEY} is not an object")
    return state_from_json(raw)


def _iter_symbol_args(values: Iterable[str] | None) -> list[str] | None:
    if values is None:
        return None
    out: list[str] = []
    for value in values:
        out.extend(part.strip().upper() for part in value.split(",") if part.strip())
    return out or None
