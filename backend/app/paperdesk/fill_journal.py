"""What the rule desks' positions did between two refreshes -- the only place a desk fill is recorded.

**The paper desk has no fills to read, and that is not an oversight.** Every rule desk on that page is
*replayed*, not traded: `app.paperdesk.desk.refresh` recomputes each card from stored bars back to
inception and reports the positions that replay ends holding. The replay is deterministic, so it never
"executes" anything at a moment in time -- run it twice and the same trades happen twice, from scratch.
That is exactly what makes the page trustworthy, and exactly what leaves nothing for a notification to
be *about*: there is no event, only a recomputed end state.

So this module manufactures the event by differencing two end states. It keeps a snapshot of the last
holdings map (`holdings_last.json`) beside an append-only journal of every change it has observed
(`fills.jsonl`), and `diff_and_record` turns "the state was A, now it is B" into a list of BUY/SELL
deltas. This is a strictly weaker claim than a broker fill, and the vocabulary keeps that honest: these
are `FillDelta`s -- what changed between two observations -- not `Fill`s. A desk that opened and closed
a position between two refreshes produces no delta at all, because from this module's vantage point
nothing changed. `app.paperdesk` is not the place to fix that; the replay's own `Trade` list already
records every round trip exactly, for anyone asking what happened rather than what is new.

**The first run records a baseline and reports nothing.** With no snapshot on disk, every position a
desk holds looks new, and announcing thirty "BUY"s the first time the feature runs would be thirty
false notifications about positions opened months ago. An absent snapshot therefore means "not yet
observed", never "empty portfolio" -- which is why the baseline write happens on the same call that
returns `[]`, and why deleting `holdings_last.json` re-baselines rather than re-announcing.

Quantities are compared as `Decimal`, read back from the JSON snapshot as strings, per this codebase's
money convention -- a share count that round-trips through a JSON *number* can come back as
`10.000000000000002` and manufacture a delta out of nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from app.config import Settings

if TYPE_CHECKING:  # pragma: no cover - import cycle: models imports nothing from here
    from app.paperdesk.models import PaperDeskState

__all__ = ["FillDelta", "diff_and_record", "holdings_map", "journal_path", "snapshot_path"]

logger = logging.getLogger(__name__)

Side = Literal["BUY", "SELL"]


@dataclass(frozen=True, slots=True)
class FillDelta:
    """One position change observed between two refreshes of one desk.

    `quantity` is always positive and `side` carries the direction, rather than a signed quantity:
    the two consumers are a headline ("SELL 4 NVDA") and a JSONL line a human reads, and neither is
    improved by having to notice a minus sign.
    """

    desk: str
    """`"<book purpose>/<agent id>"`. The agent id alone is not unique -- the same card trades in more
    than one book (`trading`, `savings`, `roth`), each with its own funding and its own positions, so
    keying on `agent_id` would silently merge two different desks' holdings into one series."""

    symbol: str
    side: Side
    quantity: Decimal
    """How much the position moved, not how much is now held -- `SELL 4` off a position of 10 leaves 6."""

    as_of: dt.date
    """`PaperDeskState.as_of`: the last *traded session*, which is what this change is a fact about.
    Deliberately not the wall clock -- a refresh pressed twice on a Sunday observes the same session
    both times, and dating the delta by the button press would make one change look like two."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "desk": self.desk,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": str(self.quantity),
            "as_of": self.as_of.isoformat(),
        }


def _dir(settings: Settings) -> Path:
    path = settings.data_dir / "paperdesk"
    path.mkdir(parents=True, exist_ok=True)
    return path


def snapshot_path(settings: Settings) -> Path:
    """`data/paperdesk/holdings_last.json` -- the last observed holdings map, overwritten each run."""
    return _dir(settings) / "holdings_last.json"


def journal_path(settings: Settings) -> Path:
    """`data/paperdesk/fills.jsonl` -- every delta ever observed, append-only."""
    return _dir(settings) / "fills.jsonl"


def holdings_map(state: PaperDeskState) -> dict[str, dict[str, str]]:
    """`{"<purpose>/<agent id>": {"<symbol>": "<quantity>"}}` for every desk in `state`.

    Quantities are stringified here rather than at write time so the in-memory comparison and the
    on-disk snapshot are the same values compared the same way -- there is no path where a delta is
    computed against a number that was never what got written.
    """
    out: dict[str, dict[str, str]] = {}
    for book in state.books:
        for desk in book.desks:
            key = f"{book.purpose}/{desk.agent_id}"
            out[key] = {holding.symbol: str(holding.quantity) for holding in desk.holdings}
    return out


def _read_snapshot(settings: Settings) -> dict[str, dict[str, str]] | None:
    """The last snapshot, or `None` when there is not one to compare against.

    An unreadable or malformed file answers `None` -- i.e. re-baseline -- rather than raising or being
    treated as an empty portfolio. Both alternatives are worse: raising breaks a refresh over a file
    nothing else needs, and reading corruption as "held nothing" would announce every open position as
    a fresh buy, which is the exact false-notification storm the baseline rule exists to prevent.
    """
    path = snapshot_path(settings)
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("paperdesk fill journal: unreadable snapshot %s; re-baselining", path.name)
        return None
    if not isinstance(loaded, dict):
        return None
    snapshot: dict[str, dict[str, str]] = {}
    for desk, positions in loaded.items():
        if isinstance(desk, str) and isinstance(positions, dict):
            snapshot[desk] = {
                str(symbol): str(quantity) for symbol, quantity in positions.items()
            }
    return snapshot


def _quantity(raw: str) -> Decimal:
    try:
        return Decimal(raw)
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _deltas(
    previous: dict[str, dict[str, str]],
    current: dict[str, dict[str, str]],
    *,
    as_of: dt.date,
) -> list[FillDelta]:
    """Every position change from `previous` to `current`, sorted for a stable read.

    **Only desks present in both maps are differenced.** A desk that appears for the first time (a
    newly seated card, or a book whose desks were filtered out of the previous run) is in the same
    position as the very first run overall: its whole portfolio would look like a burst of buys that
    did not happen today. A desk that *disappears* is likewise not liquidated -- it was unseated, and
    announcing a sell of everything it held would be a fabricated trade. Both cases are recorded into
    the new snapshot, so the run after this one differences them normally.
    """
    deltas: list[FillDelta] = []
    for desk in sorted(current.keys() & previous.keys()):
        before = previous[desk]
        after = current[desk]
        for symbol in sorted(before.keys() | after.keys()):
            was = _quantity(before.get(symbol, "0"))
            now = _quantity(after.get(symbol, "0"))
            if now == was:
                continue
            side: Side = "BUY" if now > was else "SELL"
            deltas.append(
                FillDelta(
                    desk=desk,
                    symbol=symbol,
                    side=side,
                    quantity=abs(now - was),
                    as_of=as_of,
                )
            )
    return deltas


def _append_journal(settings: Settings, deltas: list[FillDelta]) -> None:
    path = journal_path(settings)
    with path.open("a", encoding="utf-8") as handle:
        for delta in deltas:
            handle.write(json.dumps(delta.to_dict(), separators=(",", ":")) + "\n")


def diff_and_record(settings: Settings, state: PaperDeskState) -> list[FillDelta]:
    """Difference `state`'s holdings against the last snapshot, journal the deltas, re-snapshot.

    Returns the deltas, `[]` on the first ever call (see the module docstring on baselining). The
    snapshot is overwritten **whether or not** anything changed, and after the journal append rather
    than before: a crash between the two costs one duplicated journal line on the next run, which the
    `dedupe_id` at the notify layer absorbs, where the opposite order would cost a silently dropped
    change forever.
    """
    current = holdings_map(state)
    previous = _read_snapshot(settings)

    deltas: list[FillDelta] = []
    if previous is not None:
        deltas = _deltas(previous, current, as_of=state.as_of)
        if deltas:
            _append_journal(settings, deltas)

    snapshot_path(settings).write_text(json.dumps(current, indent=2), encoding="utf-8")
    return deltas
