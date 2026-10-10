"""Guard 3: one ticker, one holdout, one look.

An out-of-sample test is only out-of-sample the first time. Look twice and the second look is
in-sample: whatever was adjusted between them -- a threshold, a horizon, the decision to keep going --
was chosen with knowledge of the holdout, and the numbers it returns no longer mean what they appear
to mean. This is not a rule about honesty. It is arithmetic about what the sample contains.

So a holdout is **stateful and per ticker**, not a slice recomputed on demand. It is recorded the
first time it is used, and the second attempt is refused.

**A burned holdout is recorded, not silently refused.** The obvious implementation raises on the
second attempt and leaves the state alone, which produces a system where a user who does not know the
holdout is compromised keeps reading its stored numbers as if it were clean.
:attr:`~app.thesis.models.HoldoutStatus.BURNED` is a state the UI can display, and
:attr:`~app.thesis.models.HoldoutState.attempts` is the count that proves it happened.

**The split is by date, chosen without looking at outcomes.** A fixed trailing fraction of the
sessions, taken from the end. Not "the last bear market", not "since 2020" -- any split chosen for
what it contains is a split chosen on the data, and it would make the holdout an extension of the
in-sample period wearing a different name.

**A holdout too short to test is refused up front**, rather than returning a result computed over
eleven bars. :data:`MIN_HOLDOUT_BARS` is the floor, and falling below it is a
:attr:`~app.thesis.models.LoopOutcome.HOLDOUT_UNAVAILABLE` outcome -- a reportable one, not an error.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

import pandas as pd

from app.config import Settings
from app.thesis.ledger import _connect as _ledger_connect
from app.thesis.models import HoldoutState, HoldoutStatus

__all__ = [
    "HOLDOUT_FRACTION",
    "MIN_HOLDOUT_BARS",
    "HoldoutBurned",
    "HoldoutUnavailable",
    "claim",
    "load",
    "split",
    "split_frame",
]

#: Fraction of sessions reserved, taken from the end of the sample.
#:
#: A quarter is enough to be a real test on the histories this project stores -- roughly seven years
#: of QQQ, four of SOXL -- while leaving the in-sample period long enough to contain more than one
#: regime. The number is fixed rather than tunable on purpose: a caller who can choose the split can
#: choose it after seeing which choice helps.
HOLDOUT_FRACTION: Final[float] = 0.25

#: Below this, a holdout cannot support a verdict and the loop declines to produce one.
#:
#: 250 sessions is about a year. A 20-bar forward study over a shorter window yields a handful of
#: independent events, and a "holdout result" computed from five of them is a number that reads like
#: confirmation and carries none.
MIN_HOLDOUT_BARS: Final[int] = 250

_SCHEMA = """
CREATE TABLE IF NOT EXISTS thesis_holdout (
    symbol                TEXT PRIMARY KEY,
    split_date            TEXT NOT NULL,
    status                TEXT NOT NULL,
    evaluated_at          TEXT,
    evaluated_thesis_hash TEXT,
    attempts              INTEGER NOT NULL DEFAULT 0
);
"""


class HoldoutUnavailable(RuntimeError):
    """The holdout cannot support an evaluation -- too few bars, or no bars at all."""


class HoldoutBurned(RuntimeError):
    """A second evaluation was attempted. The state has been updated to record it."""


@contextmanager
def _connect(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    """The same database file the trial ledger uses -- one research store, not two.

    Sharing the connection helper rather than the *table*: holdout state and trial records answer
    different questions and neither reads the other's rows.
    """
    with _ledger_connect(settings) as conn:
        conn.executescript(_SCHEMA)
        yield conn


def split(bars: pd.DataFrame) -> dt.date:
    """The last in-sample session. Everything after it is holdout.

    Purely positional -- a fixed fraction from the end -- so the boundary cannot be influenced by
    what the data does around it.
    """
    if bars.empty:
        raise HoldoutUnavailable("no bars: nothing to split")
    n = len(bars)
    cut = int(n * (1.0 - HOLDOUT_FRACTION))
    if cut < 1 or n - cut < MIN_HOLDOUT_BARS:
        raise HoldoutUnavailable(
            f"{n} sessions leaves {max(0, n - cut)} in the holdout, under the {MIN_HOLDOUT_BARS} "
            "needed to support a verdict; this ticker cannot be evaluated out-of-sample yet"
        )
    ts = bars["ts"]
    date = ts.iloc[cut - 1].date()
    return date if isinstance(date, dt.date) else dt.date.fromisoformat(str(date))


def split_frame(bars: pd.DataFrame, split_date: dt.date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``(in_sample, holdout)`` around a boundary date, inclusive on the in-sample side.

    Returned as copies with reset indices: the Phase 7 engines validate that a signal's index matches
    its bars exactly, and a sliced frame carrying its parent's index would fail that check in a way
    whose message points at the wrong thing.
    """
    boundary = pd.Timestamp(split_date, tz="UTC")
    in_sample = bars[bars["ts"] <= boundary].reset_index(drop=True)
    holdout = bars[bars["ts"] > boundary].reset_index(drop=True)
    return in_sample, holdout


def load(symbol: str, *, settings: Settings | None = None) -> HoldoutState | None:
    """This ticker's holdout state, or ``None`` if it has never been established."""
    with _connect(settings) as conn:
        row = conn.execute(
            "SELECT * FROM thesis_holdout WHERE symbol = ?", (symbol.upper(),)
        ).fetchone()
    if row is None:
        return None
    return HoldoutState(
        symbol=row["symbol"],
        split_date=dt.date.fromisoformat(row["split_date"]),
        status=HoldoutStatus(row["status"]),
        evaluated_at=(
            dt.datetime.fromisoformat(row["evaluated_at"]) if row["evaluated_at"] else None
        ),
        evaluated_thesis_hash=row["evaluated_thesis_hash"],
        attempts=int(row["attempts"]),
    )


def establish(
    symbol: str, bars: pd.DataFrame, *, settings: Settings | None = None
) -> HoldoutState:
    """Fix this ticker's split, or return the one already fixed.

    **The split date never moves once set.** Recomputing it as history grows would slide the boundary
    forward, quietly feeding previously-held-out sessions into the in-sample period -- so a thesis
    tuned today would be tuned on data that was the holdout last month, and the holdout's guarantee
    would decay without anyone touching it.
    """
    upper = symbol.upper()
    existing = load(upper, settings=settings)
    if existing is not None:
        return existing

    split_date = split(bars)
    with _connect(settings) as conn:
        conn.execute(
            """
            INSERT INTO thesis_holdout (symbol, split_date, status, attempts)
            VALUES (?, ?, ?, 0)
            ON CONFLICT(symbol) DO NOTHING
            """,
            (upper, split_date.isoformat(), HoldoutStatus.UNUSED.value),
        )
    state = load(upper, settings=settings)
    if state is None:  # pragma: no cover - the insert above guarantees a row
        raise HoldoutUnavailable(f"{upper}: holdout state could not be established")
    return state


def claim(
    symbol: str,
    thesis_hash: str,
    *,
    at: dt.datetime | None = None,
    settings: Settings | None = None,
) -> HoldoutState:
    """Spend this ticker's one holdout evaluation.

    Raises :class:`HoldoutBurned` on a second attempt -- **after** recording it. The recording is the
    part that matters: a refusal that leaves no trace produces a system where the stored holdout
    result still looks clean to anyone who did not witness the refusal.

    The attempt counter increments on every call including refused ones, so the state itself is the
    evidence of how many times someone reached for it.
    """
    upper = symbol.upper()
    state = load(upper, settings=settings)
    if state is None:
        raise HoldoutUnavailable(
            f"{upper}: no holdout has been established; call establish() with the bars first"
        )

    now = at or dt.datetime.now(dt.UTC)

    # One statement decides and writes. The obvious implementation -- SELECT, branch in Python,
    # UPDATE -- has a read-then-write race, and it is not theoretical: eight threads calling this
    # concurrently produced *six* "clean" looks and left the row reading `spent`, i.e. six
    # evaluations recorded as one. The whole guarantee is "one look", so the decision has to be made
    # by the database against the row it is updating, not by the caller against a row it read
    # earlier. `BEGIN IMMEDIATE` takes the write lock before the read inside the same transaction,
    # so concurrent callers serialise and each sees the state the previous one left.
    with _connect(settings) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT status FROM thesis_holdout WHERE symbol = ?", (upper,)
            ).fetchone()
            was_unused = row is not None and row["status"] == HoldoutStatus.UNUSED.value
            if was_unused:
                conn.execute(
                    """
                    UPDATE thesis_holdout
                       SET status = ?, evaluated_at = ?, evaluated_thesis_hash = ?,
                           attempts = attempts + 1
                     WHERE symbol = ? AND status = ?
                    """,
                    (
                        HoldoutStatus.SPENT.value,
                        now.isoformat(),
                        thesis_hash,
                        upper,
                        HoldoutStatus.UNUSED.value,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE thesis_holdout SET status = ?, attempts = attempts + 1 WHERE symbol = ?",
                    (HoldoutStatus.BURNED.value, upper),
                )
            conn.execute("COMMIT")
        except Exception:  # pragma: no cover - only on a driver-level failure
            conn.execute("ROLLBACK")
            raise

    updated = load(upper, settings=settings)
    if updated is None:  # pragma: no cover
        raise HoldoutUnavailable(f"{upper}: holdout state vanished mid-claim")

    if not was_unused:
        # Read from the post-transaction row, not from `state`, which was loaded before the lock was
        # taken and under a race can claim UNUSED for a holdout another caller has already spent.
        when = f"{updated.evaluated_at:%Y-%m-%d}" if updated.evaluated_at else "an earlier run"
        raise HoldoutBurned(
            f"{upper}: the holdout was already evaluated on {when} against thesis "
            f"{(updated.evaluated_thesis_hash or '')[:12]}. This is attempt {updated.attempts}. "
            "A second look is not an out-of-sample test -- anything adjusted since was adjusted "
            "knowing what the holdout contains -- so the holdout is now recorded as burned for "
            "this ticker."
        )
    return updated


def describe(state: HoldoutState | None) -> str:
    """One line a UI can show without re-deriving the meaning of each status."""
    if state is None:
        return "No holdout established for this ticker yet."
    match state.status:
        case HoldoutStatus.UNUSED:
            return (
                f"Holdout reserved from {state.split_date:%Y-%m-%d} onward, never evaluated. "
                "One evaluation is available."
            )
        case HoldoutStatus.SPENT:
            when = f"{state.evaluated_at:%Y-%m-%d}" if state.evaluated_at else "an earlier run"
            return (
                f"Holdout from {state.split_date:%Y-%m-%d} was evaluated once on {when}. "
                "That result stands; no further out-of-sample test is available for this ticker."
            )
        case HoldoutStatus.BURNED:
            return (
                f"Holdout from {state.split_date:%Y-%m-%d} has been evaluated {state.attempts} "
                "times. It is no longer an out-of-sample test: anything tuned after the first look "
                "was tuned knowing what it contains. Treat its numbers as in-sample."
            )


def _state_json(state: HoldoutState) -> str:  # pragma: no cover - convenience for run cards
    return json.dumps(state.model_dump(mode="json"), sort_keys=True)
