"""The strategy-programme's selection rule, as a product feature rather than a hand-run script.

**Why this module exists.** Running a competition round is already `app.tournament.jobs` /
`POST /api/competition/jobs` -- the engine trades every card through every window and writes an
`AgentResult` per (card, window). *Deciding which cards win a seat on the paper desk* was never that:
it lived in `strategy-program/tools/round10.py`, `round11.py` and `holdings_overlap.py`, three
one-off scripts read by a human who then hand-edited `backend/app/paperdesk/desk.py`'s `AGENT_IDS`
tuple. This module is the missing layer -- the same rule, callable as `select(round_id)`, so the
roster can be derived by the product instead of transcribed from a terminal.

**This is a port, not a redesign.** `strategy-program/ROUND-12-PLAN.md` section 3 is the authority;
where it and the scripts it describes disagree, the plan wins. Every gate, every tie-break and the
distinctness rule below are taken from that document and from `round10.py` / `round11.py` /
`holdings_overlap.py`, reproduced here rather than imported -- `strategy-program` is not a legal
Python package name (the hyphen makes `import strategy_program` illegal), so the only way to reuse
its logic from application code is to copy it and keep the copies in step by inspection, the same
trade-off `strategy-program/tools/score.py`'s own module docstring makes for its sibling files.

**The register.** Four stages, each a floor or a ranking criterion, never both:

* **Gate A** (`_gate_a`) -- a backtest floor. Positive median annualized adjusted excess at round 5's
  5-year and 10-year rungs, against both SPY (the engine's own `benchmark_return`) and QQQ
  (recomputed from the bar store). Ported from `round10.gate_a` / `round10.rung_excess_vs_qqq`.
* **Gate L** (`GATE_L_FAIL`) -- a liveness floor, carried forward from round 9 as data rather than
  recomputed, because the window and the field are both frozen and re-running it would reproduce the
  same verdict and report it as if two rounds had independently confirmed something they had not.
* **Gate C** (`_gate_c_outcomes`) -- live consistency. Positive `adjusted_excess` in at least 3 of the
  6 live sub-periods, differenced from round 11's cumulative live runs by `_live_cells` -- see that
  function's docstring for why differencing, not six independent runs, is the only correct way to
  recover those six numbers.
* **Ranking and distinctness** (`select`'s ranking key, and its seating walk) -- median live
  `adjusted_excess`, descending, with three tie-breaks; then a walk down the ranking seating each card
  whose *novel names* against the union of everything already seated is at least one whole position.
  This replaces the discipline/base-family rule rounds 6-11 used -- see
  `strategy-program/tools/holdings_overlap.py`'s module docstring and `ROUND-12-PLAN.md` section 3 for
  why a proxy for "what a card descends from" is the wrong question and "what does the reader learn
  from this panel" is the right one.

`ladder-qld-schd` is seated outside the competition (`seated_by="outside-competition"`): it is not a
`StrategyCard`, was never run through any of the four stages above, and is excluded from `gates` and
`ranking` entirely -- see `backend/app/paperdesk/desk.py`'s own docstring on `AGENT_IDS` for why that
seat is independently justified rather than a candidate that competed for one of the ranked ones.

**What this module does not do.** It does not write to `desk.py`, does not call
`app.tournament.runner`, and does not open a write connection to the bar store -- see
`strategy-program/DEFECTS.md` D3: the bar store is a single DuckDB file, and a concurrent write-mode
reader racing a round in progress corrupts results silently rather than raising. Every bar read here
goes through an in-memory connection (`duck.connect()`, no path), the same pattern
`app.tournament.roster` already uses for the identical reason: "a read path has no business creating
[the on-disk catalog]."

**Honesty is load-bearing, not decorative.** `SelectionResult.notes` always carries
`MANDATORY_NOTES` verbatim, and a candidate this rule cannot assess (no live record at Gate C, no
`live-6` trade log for distinctness) is reported as unassessable -- `passed=False` /
`seated=False` with a reason that says so explicitly -- rather than silently defaulted to a pass or a
fail that looks like an ordinary one.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Literal, NamedTuple

import duckdb

from app.config import Settings, get_settings
from app.db import duck
from app.tournament.models import TRADE_END, TRADE_START, AgentResult

# ---------------------------------------------------------------------------
# The public contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateOutcome:
    agent_id: str
    passed: bool
    reason: str
    detail: dict[str, str]


@dataclass(frozen=True)
class SelectionSeat:
    agent_id: str
    rank: int | None
    live_median: str | None
    live_hits: str | None
    novel_names: str | None
    seated: bool
    seated_by: Literal["rule", "outside-competition", "owner-override"]
    note: str


@dataclass(frozen=True)
class SelectionResult:
    round_id: str
    rule_version: str
    gates: dict[str, list[GateOutcome]]
    ranking: list[SelectionSeat]
    seats: list[SelectionSeat]
    notes: list[str]


RULE_VERSION = "r12-holdings-distinctness"

#: Caveats `ROUND-12-PLAN.md` and `round11.py`'s module docstring require next to any roster this
#: rule produces, carried verbatim regardless of what the roster turns out to be -- these are
#: properties of the *measurement*, not conclusions the rule reaches, so they do not belong behind a
#: conditional.
MANDATORY_NOTES: tuple[str, ...] = (
    "The live matrix is one market environment cut into six pieces, not six regime draws.",
    "The live window is 127 sessions against the ~250 the programme set as its own bar.",
    "The distinctness rule cannot assess a card with no live record.",
)

#: Seated independently of the competition -- see the module docstring and
#: `backend/app/paperdesk/desk.py`'s `AGENT_IDS` docstring. Not a `StrategyCard`, never gated, never
#: ranked.
OUTSIDE_COMPETITION_AGENT_ID = "ladder-qld-schd"

# ---------------------------------------------------------------------------
# The candidate field -- ported from `strategy-program/tools/round10.py::FIELD`
# ---------------------------------------------------------------------------

#: The fifteen `StrategyCard`s that compete for a seat, and each one's `discipline` -- unchanged from
#: rounds 6 through 11 (`round10.FIELD`). The discipline label itself is no longer consulted by
#: distinctness (round 12 replaces that clause; see the module docstring), but the field membership
#: it was recorded against is still the field this rule runs over, so the map is kept rather than
#: thinned to a bare tuple -- a reader checking this module against `round10.py` should find the same
#: fifteen names attached to the same labels, not a silently narrower list.
FIELD: dict[str, str] = {
    "B-momentum": "momentum",
    "B2-hold-90": "momentum",
    "B3-concentrated": "momentum",
    "B4-tight-stop": "momentum",
    "A-rotation": "pairs-rotation",
    "c20-rotation": "pairs-rotation",
    "C-trend": "trend",
    "H-trend-diversified": "trend",
    "c07-chop": "mean-reversion",
    "c18-meanrev": "mean-reversion",
    "c09-convex": "volatility",
    "c19-volatility": "volatility",
    "c14-riskmanaged-wide": "risk-managed",
    "c21-uncorrelated": "risk-managed",
    "c11-breakout": "breakout",
}

#: Gate L's verdicts, carried forward from `data/rounds/r9-2026-08/SELECTION.md` section 2 rather
#: than re-run -- `round10.GATE_L_FAIL`, reproduced here verbatim including its provenance comment.
#: The clause is unchanged, the fifteen cards are frozen, the window (2026-02-17 to 2026-08-18, 127
#: sessions) is bounded by a bar store that has not moved, and the desk's own `as_of` is still
#: 2026-08-18 -- so re-running it would reproduce it exactly and then be reported as if two rounds had
#: independently confirmed something. They would not have; it is one measurement counted twice.
GATE_L_FAIL: dict[str, str] = {
    "c07-chop": "all cash for 92 sessions; last trade closed 2026-04-07, past the 60-session line",
    "c14-riskmanaged-wide": "zero trades in the out-of-sample window",
}

#: Round 5's 5-year and 10-year rungs -- the horizons Gate A is computed on, unchanged from round 10.
RUNGS_5Y: tuple[str, ...] = ("h5y-1", "h5y-2", "h5y-3")
RUNGS_10Y: tuple[str, ...] = ("h10y-1", "h10y-2")

#: Gate C: positive `adjusted_excess` in at least this many of the six live sub-windows -- half the
#: matrix plus one, pre-registered in `ROUND-11-PLAN.md` section 3 before any sub-window ran and
#: unchanged by round 12 (`round11.MIN_LIVE_HITS`).
MIN_LIVE_HITS = 3

#: The six contiguous sub-windows of the live out-of-sample period, in calendar order
#: (`score.R11_LIVE_TAGS`). Not parameterised by `round_id`'s programme number because the *shape* of
#: the live matrix (six cumulative slices of one out-of-sample window) is a property of the rule, not
#: of any one round -- what changes between rounds is which round's `results/` directory holds them.
LIVE_TAGS: tuple[str, ...] = ("live-1", "live-2", "live-3", "live-4", "live-5", "live-6")

#: Distinctness: seat a card if its mean novel names against the union of everything already seated
#: is at least this many whole positions -- `ROUND-12-PLAN.md` section 3, chosen as a unit ("one whole
#: position a reader could not already see") rather than a fitted number. See `select`'s seating walk.
NOVELTY_THRESHOLD = 1.0

#: Seat count is an output, capped here, with no floor -- `ROUND-12-PLAN.md` section 3.
MAX_SEATS = 4


class _MatrixSpec(NamedTuple):
    """Gate S' -- kept as a tie-break only, exactly as round 11 demoted it (`round11.py`'s module
    docstring: "Gate S' stops eliminating anything and becomes a tie-break"). Mirrors
    `round10.MATRICES`: the three backtest matrices a card's rank can be checked against, each an
    independent (window-set, annualization) choice already made for round 10 and not revisited here.
    """

    name: str
    round_dir: str
    tags: tuple[str, ...]
    annualized: bool


#: Round 2's eight regime windows -- `strategy-program/tools/score.py::MAIN_WINDOW_TAGS`, duplicated
#: here for the same reason `score.py` duplicates it from `windows.py`: the two live in unrelated,
#: unimportable trees and eight short strings kept in sync by inspection are less fragile than a
#: cross-package import hack.
_R2_TAGS: tuple[str, ...] = (
    "q4-2018",
    "covid",
    "bear-2022",
    "chop-2015",
    "chop-2011",
    "bull-2024",
    "recent",
    "gfc",
)

#: Round 4's six regimes, deliberately disjoint from round 2's -- `score.py::R4_MAIN_WINDOW_TAGS`.
_R4_TAGS: tuple[str, ...] = (
    "recovery-2009",
    "taper-2013",
    "oil-2014",
    "volmageddon-2018",
    "inflation-2021",
    "banks-2023",
)

#: Round 5's ladder arm -- `score.py::R5_LADDER_TAGS`, ten-year rungs first through six-month last, in
#: the file's own order.
_R5_LADDER_TAGS: tuple[str, ...] = (
    "h10y-1",
    "h10y-2",
    "h5y-1",
    "h5y-2",
    "h5y-3",
    "h3y-1",
    "h3y-2",
    "h3y-3",
    "h3y-4",
    "h1y-1",
    "h1y-2",
    "h1y-3",
    "h1y-4",
    "h1y-5",
    "h1y-6",
    "h6m-1",
    "h6m-2",
    "h6m-3",
    "h6m-4",
    "h6m-5",
    "h6m-6",
)

MATRICES: tuple[_MatrixSpec, ...] = (
    _MatrixSpec("r2", "r2-2026-08", _R2_TAGS, False),
    _MatrixSpec("r4", "r4-2026-08", _R4_TAGS, False),
    _MatrixSpec("r5-ladder", "r5-2026-08", _R5_LADDER_TAGS, True),
)

#: The historical round Gate A is always measured against, regardless of which programme round
#: `select()` is deciding. This is a backtest over a frozen window -- re-running it under a different
#: `round_id` would recompute the same numbers, not sample anything new (`PROTOCOL.md` section 6(a)),
#: so unlike the live matrix it is not parameterised by `round_id`.
_R5_ROUND_DIR = "r5-2026-08"


# ---------------------------------------------------------------------------
# Metrics -- ported from `strategy-program/tools/score.py`. See `strategy-program/DEFECTS.md` D1/D2:
# never read `AgentResult.total_return` or `AgentResult.exposure` directly; both are defective
# proxies for the quantities their names suggest.
# ---------------------------------------------------------------------------


def _corrected_return(result: AgentResult) -> Decimal:
    """`ending_equity / starting_equity - 1`. **Not** `result.total_return` -- DEFECTS.md D1: that
    field is silently rebased to the first session's close rather than to starting equity."""
    return result.ending_equity / result.starting_equity - 1


def _capital_exposure(result: AgentResult) -> Decimal | None:
    """Capital-weighted exposure, preferring the engine's own `AgentResult.capital_exposure`.

    **Not** `result.exposure` -- DEFECTS.md D2: that field is the fraction of *sessions* the card
    held anything at all, regardless of size, and over-credits a thinly-filled book when multiplied
    against a benchmark return. Falls back to a trade-log reconstruction only for a run file that
    predates the engine field, matching `score.capital_exposure`'s fallback.
    """
    engine_figure = result.capital_exposure
    if engine_figure is not None:
        return Decimal(str(engine_figure))
    if not result.trades or result.sessions <= 0 or result.starting_equity <= 0:
        return None
    invested = sum(t.quantity * t.entry_price * t.bars_held for t in result.trades)
    return Decimal(invested) / (Decimal(result.sessions) * result.starting_equity)


def _adjusted_excess(result: AgentResult) -> Decimal | None:
    """`corrected_return - (capital_exposure * benchmark_return)` -- the primary ranking metric.
    `None` when the window's benchmark is unknown, never substituted with zero."""
    if result.benchmark_return is None:
        return None
    exposure = _capital_exposure(result)
    if exposure is None:
        if result.exposure is None:
            return None
        exposure = Decimal(str(result.exposure))
    return _corrected_return(result) - (exposure * result.benchmark_return)


_TRADING_DAYS_PER_YEAR = Decimal(252)


def _window_years(result: AgentResult) -> Decimal | None:
    if result.sessions < 1:
        return None
    return Decimal(result.sessions) / _TRADING_DAYS_PER_YEAR


def _annualized_return(result: AgentResult) -> Decimal | None:
    years = _window_years(result)
    if years is None:
        return None
    base = Decimal(1) + _corrected_return(result)
    if base <= 0:
        return None
    root = float(base) ** (1.0 / float(years))
    return Decimal(str(root)) - 1


def _annualized_benchmark(result: AgentResult) -> Decimal | None:
    if result.benchmark_return is None:
        return None
    years = _window_years(result)
    if years is None:
        return None
    base = Decimal(1) + result.benchmark_return
    if base <= 0:
        return None
    root = float(base) ** (1.0 / float(years))
    return Decimal(str(root)) - 1


def _annualized_adjusted_excess(result: AgentResult) -> Decimal | None:
    ann_return = _annualized_return(result)
    if ann_return is None:
        return None
    ann_bench = _annualized_benchmark(result)
    if ann_bench is None:
        return None
    exposure = _capital_exposure(result)
    if exposure is None:
        if result.exposure is None:
            return None
        exposure = Decimal(str(result.exposure))
    return ann_return - (exposure * ann_bench)


def _load_results(
    results_root: Path, round_tag: str, window_tags: Sequence[str]
) -> dict[str, dict[str, AgentResult]]:
    """``{window_tag: {agent_id: AgentResult}}`` for every run file actually on disk under
    ``results_root/<tag>/runs/<round_tag>-*.json`` -- `score.load_results`, ported. The file's own
    `card.agent_id` is the key, not the filename's, in case the two ever disagree."""
    out: dict[str, dict[str, AgentResult]] = {}
    for tag in window_tags:
        runs_dir = results_root / tag / "runs"
        agents: dict[str, AgentResult] = {}
        if runs_dir.is_dir():
            for path in sorted(runs_dir.glob(f"{round_tag}-*.json")):
                result = AgentResult.model_validate_json(path.read_text(encoding="utf-8"))
                agents[result.card.agent_id] = result
        out[tag] = agents
    return out


def _median_of(values: dict[str, Decimal], tags: tuple[str, ...]) -> Decimal | None:
    present = [values[t] for t in tags if t in values]
    return median(present) if present else None


def _pct(value: Decimal | float | None) -> str:
    return "n/a" if value is None else f"{value * 100:+.2f}%"


# ---------------------------------------------------------------------------
# Gate A -- backtest floor. Ported from `round10.rung_excess_vs_qqq` / `round10.gate_a`.
# ---------------------------------------------------------------------------


def _qqq_annualized(
    conn: duckdb.DuckDBPyConnection, settings: Settings, start: dt.date, end: dt.date
) -> Decimal:
    """QQQ's annualized close-to-close return over one window's calendar dates, from the bar store.

    Deliberately *not* the engine's `benchmark_return`: that is SPY, measured over the sessions a
    particular run actually traded. This is a second, independent anchor over the window's stated
    calendar period -- `round10._qqq_annualized`, ported verbatim.
    """
    bars = duck.read_bars(conn, settings.bars_dir, "QQQ", duck.Interval.DAY, start=start, end=end)
    closes = [Decimal(str(c)) for c in bars["close"].tolist()]
    if len(closes) < 2:
        raise ValueError(f"QQQ has {len(closes)} bars over {start}..{end} -- cannot price the window")
    total = closes[-1] / closes[0] - 1
    years = Decimal(len(closes)) / _TRADING_DAYS_PER_YEAR
    return (1 + total) ** (1 / years) - 1 if years > 0 else Decimal(0)


def _rung_excess_vs_qqq(settings: Settings) -> dict[str, dict[str, Decimal]]:
    """``{agent_id: {rung_tag: annualized adjusted excess vs QQQ}}`` over the 5y and 10y rungs --
    `round10.rung_excess_vs_qqq`, ported. Window dates come from round 5's own `windows.json`, never
    from a tag-name convention, so a tag that does not follow the naming pattern cannot misparse."""
    windows_path = settings.rounds_dir / _R5_ROUND_DIR / "windows.json"
    windows = json.loads(windows_path.read_text(encoding="utf-8"))
    dates = {
        w["tag"]: (dt.date.fromisoformat(w["start"]), dt.date.fromisoformat(w["end"]))
        for arm in windows["arms"].values()
        for w in arm
    }
    rungs = RUNGS_5Y + RUNGS_10Y
    with duck.connect() as conn:
        qqq = {tag: _qqq_annualized(conn, settings, *dates[tag]) for tag in rungs}
    r5_results = settings.rounds_dir / _R5_ROUND_DIR / "results"
    by_window = _load_results(r5_results, "r1", list(rungs))
    out: dict[str, dict[str, Decimal]] = {}
    for tag in rungs:
        for agent_id, result in by_window[tag].items():
            if agent_id not in FIELD:
                continue
            ann = _annualized_return(result)
            cap = _capital_exposure(result)
            if ann is None or cap is None:
                continue
            out.setdefault(agent_id, {})[tag] = ann - cap * qqq[tag]
    return out


def _gate_a(settings: Settings) -> dict[str, dict[str, Decimal | bool | None]]:
    """Positive median annualized adjusted excess at *both* the 5y and 10y rungs against *both*
    benchmarks -- `round10.gate_a`, ported unchanged."""
    qqq_by_rung = _rung_excess_vs_qqq(settings)
    r5_results = settings.rounds_dir / _R5_ROUND_DIR / "results"
    by_window = _load_results(r5_results, "r1", list(RUNGS_5Y + RUNGS_10Y))
    spy: dict[str, dict[str, Decimal]] = {}
    for tag in RUNGS_5Y + RUNGS_10Y:
        for agent_id, result in by_window[tag].items():
            if agent_id in FIELD:
                value = _annualized_adjusted_excess(result)
                if value is not None:
                    spy.setdefault(agent_id, {})[tag] = value

    out: dict[str, dict[str, Decimal | bool | None]] = {}
    for agent_id in FIELD:
        s, q = spy.get(agent_id, {}), qqq_by_rung.get(agent_id, {})
        cells: dict[str, Decimal | bool | None] = {
            "spy_5y": _median_of(s, RUNGS_5Y),
            "spy_10y": _median_of(s, RUNGS_10Y),
            "qqq_5y": _median_of(q, RUNGS_5Y),
            "qqq_10y": _median_of(q, RUNGS_10Y),
        }
        values = list(cells.values())
        cells["pass"] = all(v is not None and v > 0 for v in values)
        out[agent_id] = cells
    return out


_GATE_A_KEYS: tuple[str, ...] = ("spy_5y", "qqq_5y", "spy_10y", "qqq_10y")


def _gate_a_outcomes(cells: dict[str, dict[str, Decimal | bool | None]]) -> list[GateOutcome]:
    out: list[GateOutcome] = []
    for agent_id in FIELD:
        c = cells[agent_id]
        detail = {k: _pct(c[k]) for k in _GATE_A_KEYS}
        passed = bool(c["pass"])
        if passed:
            reason = (
                "Positive median annualized adjusted excess at both the 5y and 10y rungs, "
                "against both SPY and QQQ."
            )
        else:
            failing = [k for k in _GATE_A_KEYS if not (c[k] is not None and c[k] > 0)]  # type: ignore[operator]
            reason = "Fails the backtest floor at: " + ", ".join(f"{k} {detail[k]}" for k in failing)
        out.append(GateOutcome(agent_id=agent_id, passed=passed, reason=reason, detail=detail))
    return out


# ---------------------------------------------------------------------------
# Gate L -- liveness floor, carried forward as data. See `GATE_L_FAIL`.
# ---------------------------------------------------------------------------


def _gate_l_outcomes() -> list[GateOutcome]:
    out: list[GateOutcome] = []
    for agent_id in FIELD:
        fail_reason = GATE_L_FAIL.get(agent_id)
        if fail_reason is None:
            out.append(
                GateOutcome(
                    agent_id=agent_id,
                    passed=True,
                    reason=(
                        "Traded in the out-of-sample window and currently holds a position or "
                        "traded within the last 60 sessions (round 9's verdict, carried forward "
                        "unchanged -- the window and the field are both frozen)."
                    ),
                    detail={},
                )
            )
        else:
            out.append(
                GateOutcome(
                    agent_id=agent_id,
                    passed=False,
                    reason=f"Fails the liveness floor (round 9's verdict, carried forward): {fail_reason}",
                    detail={"reason": fail_reason},
                )
            )
    return out


# ---------------------------------------------------------------------------
# The live matrix -- differenced from cumulative runs. See the module docstring and
# `strategy-program/DEFECTS.md` D5 for why this, and not six independent tournaments, is the only
# correct way to recover six sub-period numbers.
# ---------------------------------------------------------------------------


def _live_cells(results_root: Path) -> dict[str, dict[str, Decimal]]:
    """``{agent_id: {live_tag: adjusted_excess}}`` per sub-period, by differencing cumulative runs.

    **Each run under ``results_root/live-*`` starts at `TRADE_START` and ends at its tag's
    boundary** -- they are cumulative, not independent (`strategy-program/tools/run_live_matrix.sh`).
    Six separate sub-window runs would each start with a flat book, forcing a card that entered in
    March and held into August to liquidate and re-enter at every boundary, inside a window too short
    for many entry rules to re-fire from a standing start. That version of this matrix put
    `B-momentum` at 0.0% exposure and zero trades in two entire sub-windows while it was in fact fully
    invested, and it biased the whole field toward high-turnover cards. See
    `strategy-program/DEFECTS.md` D5. Ported from `round11.live_cells` exactly -- this is the one
    piece of arithmetic in the whole rule where getting it wrong produces a plausible, biased table
    rather than an obvious error.

    Differencing recovers each sub-period **exactly**, because every quantity involved is either a
    level or a per-session sum over a `starting_equity` common to all six runs:

    * **return** -- ``ending_equity_k / ending_equity_{k-1} - 1``.
    * **benchmark** -- ``(1 + bench_k) / (1 + bench_{k-1}) - 1``. Chain-linked, not subtracted: two
      cumulative returns do not difference arithmetically.
    * **capital exposure** -- `AgentResult.capital_exposure` is
      ``sum(session_entry_notional) / (sessions * starting_equity)``, so multiplying back recovers
      the notional total and differencing gives the sub-period's, then dividing by
      ``delta_sessions * ending_equity_{k-1}`` -- the equity the sub-period actually began with, the
      same base its return is measured against.

    A card missing any of the six windows is skipped entirely (not given a partial row) -- an
    incomplete live record is a lost card for Gate C's purposes, not a coverage rule to score around.
    """
    by_window = _load_results(results_root, "r1", list(LIVE_TAGS))
    out: dict[str, dict[str, Decimal]] = {}
    for agent_id in FIELD:
        # Filtered rather than tested with `any(... is None)`: the comprehension is what narrows the
        # element type from `AgentResult | None` to `AgentResult` for everything below. The length
        # comparison preserves the original rule exactly -- one run per live tag or the card is
        # skipped -- because the filter can only ever shorten the list.
        maybe_runs = [by_window[tag].get(agent_id) for tag in LIVE_TAGS]
        runs = [r for r in maybe_runs if r is not None]
        if len(runs) != len(LIVE_TAGS):
            continue
        prev_equity = runs[0].starting_equity
        prev_bench = Decimal(0)
        prev_notional = Decimal(0)
        prev_sessions = 0
        for tag, r in zip(LIVE_TAGS, runs, strict=True):
            # `benchmark_return` and `capital_exposure` are both Optional on `AgentResult`, and this
            # arithmetic has no way to express a missing one: `1 + None` raises `TypeError` and
            # `Decimal(str(None))` raises `InvalidOperation`. Neither is a zero. A run carrying
            # neither figure is an incomplete record, which is what the surrounding `break` on a
            # non-advancing session count already treats as the end of this card's usable series.
            bench_total, exposure_frac = r.benchmark_return, r.capital_exposure
            if bench_total is None or exposure_frac is None:
                break
            d_sessions = r.sessions - prev_sessions
            if d_sessions <= 0 or prev_equity <= 0:
                break
            ret = r.ending_equity / prev_equity - 1
            bench = (1 + bench_total) / (1 + prev_bench) - 1
            notional = Decimal(str(exposure_frac)) * Decimal(r.sessions) * runs[0].starting_equity
            exposure = (notional - prev_notional) / (Decimal(d_sessions) * prev_equity)
            out.setdefault(agent_id, {})[tag] = ret - exposure * bench
            prev_equity, prev_bench = r.ending_equity, bench_total
            prev_notional, prev_sessions = notional, r.sessions

    # Self-check, ported from `round11.py`'s `main`: for the first sub-period there is nothing to
    # difference against, so the differenced cell must reduce exactly to plain `_adjusted_excess` of
    # that run. If the arithmetic above is wrong anywhere, it is wrong here too, and this is the one
    # cell where an independent implementation already exists to check it against.
    first = by_window.get(LIVE_TAGS[0], {})
    for agent_id, result in first.items():
        want = _adjusted_excess(result)
        got = out.get(agent_id, {}).get(LIVE_TAGS[0])
        if want is not None and got is not None and abs(want - got) > Decimal("1e-12"):
            raise AssertionError(
                f"live-cell differencing disagrees with plain adjusted_excess on the first "
                f"sub-period for {agent_id}: {want} vs {got} -- the differencing arithmetic in "
                f"_live_cells is wrong, and every cell it produces is suspect"
            )
    return out


def _gate_c_outcomes(
    survivors_al: list[str], cells: dict[str, dict[str, Decimal]]
) -> tuple[list[GateOutcome], list[str], dict[str, dict[str, object]]]:
    """Positive `adjusted_excess` in at least `MIN_LIVE_HITS` of the six live sub-periods.

    A candidate with zero live cells (no live record at all in this round's matrix) is reported as
    **unassessable** -- `passed=False` with a reason that says so, not a silent pass or a fail that
    reads like an ordinary consistency failure. See the module docstring's honesty paragraph.
    """
    out: list[GateOutcome] = []
    survivors_c: list[str] = []
    live_summary: dict[str, dict[str, object]] = {}
    for agent_id in survivors_al:
        row = cells.get(agent_id, {})
        vals = [row[t] for t in LIVE_TAGS if t in row]
        n = len(vals)
        if n == 0:
            live_summary[agent_id] = {"median": None, "hits": 0, "n": 0}
            out.append(
                GateOutcome(
                    agent_id=agent_id,
                    passed=False,
                    reason=(
                        "No live record in this round's matrix -- Gate C cannot be assessed, and "
                        "is reported as unassessable rather than defaulted to a pass or a fail."
                    ),
                    detail={"hits": "n/a", "median": "n/a"},
                )
            )
            continue
        hits = sum(1 for v in vals if v > 0)
        med = median(vals)
        live_summary[agent_id] = {"median": med, "hits": hits, "n": n}
        ok = hits >= MIN_LIVE_HITS
        detail = {"hits": f"{hits}/{n}", "median": _pct(med)}
        reason = (
            f"Positive adjusted excess in {hits} of {n} live sub-periods (>= {MIN_LIVE_HITS} required)."
            if ok
            else f"Positive adjusted excess in only {hits} of {n} live sub-periods (need >= {MIN_LIVE_HITS})."
        )
        out.append(GateOutcome(agent_id=agent_id, passed=ok, reason=reason, detail=detail))
        if ok:
            survivors_c.append(agent_id)
    return out, survivors_c, live_summary


# ---------------------------------------------------------------------------
# Gate S' tie-break -- backtest rank range across the three matrices in `MATRICES`.
# ---------------------------------------------------------------------------


def _medians_for_matrix(spec: _MatrixSpec, settings: Settings) -> dict[str, Decimal]:
    """Each field card's median adjusted excess on one matrix, over the windows it actually ran --
    `round10._medians`, ported."""
    results_root = settings.rounds_dir / spec.round_dir / "results"
    by_window = _load_results(results_root, "r1", list(spec.tags))
    per_card: dict[str, list[Decimal]] = {}
    for agents in by_window.values():
        for agent_id, result in agents.items():
            if agent_id not in FIELD:
                continue
            value = _annualized_adjusted_excess(result) if spec.annualized else _adjusted_excess(result)
            if value is not None:
                per_card.setdefault(agent_id, []).append(value)
    return {agent_id: median(values) for agent_id, values in per_card.items() if values}


def _ranks(values: dict[str, Decimal]) -> dict[str, int]:
    """1-indexed rank, descending, rank 1 best -- `round10._ranks`, ported."""
    order = sorted(values, key=lambda a: values[a], reverse=True)
    return {agent_id: i + 1 for i, agent_id in enumerate(order)}


def _backtest_rank_spread(settings: Settings) -> dict[str, int | None]:
    """Each card's rank range across `MATRICES` -- the highest rank minus the lowest, among matrices
    it appears in at all. `None` when the card appears in fewer than two matrices, matching
    `round11.py`'s `spread` computation: a rank range needs at least two ranks to have a range."""
    rank_table = {spec.name: _ranks(_medians_for_matrix(spec, settings)) for spec in MATRICES}
    spread: dict[str, int | None] = {}
    for agent_id in FIELD:
        seen = [r for r in (rank_table[m.name].get(agent_id) for m in MATRICES) if r]
        spread[agent_id] = max(seen) - min(seen) if len(seen) >= 2 else None
    return spread


# ---------------------------------------------------------------------------
# Distinctness -- novelty of holdings against the union of everything already seated. Ported from
# `strategy-program/tools/holdings_overlap.py`. See that module's docstring for the full argument;
# summarised in this module's own docstring.
# ---------------------------------------------------------------------------


def _sessions(settings: Settings) -> list[dt.date]:
    """SPY's own trading sessions across the live window -- the calendar every card's dates land on.
    `holdings_overlap.sessions`, ported."""
    with duck.connect() as conn:
        bars = duck.read_bars(
            conn, settings.bars_dir, "SPY", duck.Interval.DAY, start=TRADE_START, end=TRADE_END
        )
    return [ts.date() for ts in bars["ts"].tolist()]


def _held_by_session(
    results_root: Path, agent_id: str, days: Sequence[dt.date]
) -> list[frozenset[str]] | None:
    """The set of symbols a card held at each session's close, from its `live-6` trade log -- the
    only run that spans the whole live window in one piece, so it is the only complete record of what
    each card held on every session. `holdings_overlap.held_by_session`, ported.

    A closed trade is held over ``[entry_date, exit_date)`` -- inclusive of entry, exclusive of exit.
    A trade still open at the window's end carries ``exit_date is None``, not a date equal to the
    window end, so it is held from entry through every remaining session.

    `None` when no `live-6` run file exists for this card at all -- an unassessable candidate for
    distinctness, not one implicitly holding nothing.
    """
    path = results_root / "live-6" / "runs" / f"r1-{agent_id}.json"
    if not path.is_file():
        return None
    result = AgentResult.model_validate_json(path.read_text(encoding="utf-8"))
    out: list[frozenset[str]] = []
    for day in days:
        names = {
            trade.symbol
            for trade in result.trades
            if trade.entry_date <= day and (trade.exit_date is None or day < trade.exit_date)
        }
        out.append(frozenset(names))
    return out


def _seat(
    ranked_ids: Sequence[str], held: dict[str, list[frozenset[str]] | None]
) -> dict[str, tuple[str | None, bool, str]]:
    """Walk ``ranked_ids`` in order, seating the first card unconditionally and every later card
    whose novel-names count against the union of everything already seated clears
    `NOVELTY_THRESHOLD`, up to `MAX_SEATS`.

    Returns ``{agent_id: (novel_names_formatted, seated, note)}`` for every id in ``ranked_ids`` --
    including the ones that did not get a seat, so a caller can show *why* alongside the ones that
    did. ``held[agent_id] is None`` (no `live-6` trade log for that card at all) is reported as
    **unassessable** -- `seated=False` with a note that says so explicitly, never silently treated as
    either "holds nothing" or "seat it anyway". `novelty` returning ``(None, None, 0)`` (the card
    never held a position in the live window) gets the same explicit non-default treatment.

    Only cards that actually got seated feed the union later candidates are compared against --
    a skipped card (cap, below threshold, unassessable) never joins it, matching
    `strategy-program/tools/holdings_overlap.py`'s own walk.
    """
    seats_ids: list[str] = []
    seat_status: dict[str, tuple[str | None, bool, str]] = {}
    for agent_id in ranked_ids:
        if not seats_ids:
            seats_ids.append(agent_id)
            seat_status[agent_id] = (
                None,
                True,
                "First in the ranking -- nothing is seated yet for it to be redundant with.",
            )
            continue

        held_i = held.get(agent_id)
        if held_i is None:
            seat_status[agent_id] = (
                None,
                False,
                "No `live-6` trade log on disk -- distinctness cannot be assessed, not defaulted "
                "to a seat.",
            )
            continue

        # Walrus-bound: mypy narrows a *name*, not a repeated subscript, so `held[s]` stayed
        # `... | None` for the element type no matter what the filter tested.
        count, _frac, _n = _novelty(held_i, [h for s in seats_ids if (h := held[s]) is not None])
        if count is None:
            seat_status[agent_id] = (
                None,
                False,
                "Never held a position in the live window -- novelty is undefined, not zero.",
            )
            continue

        novel_str = f"{count:.2f}"
        if len(seats_ids) >= MAX_SEATS:
            seat_status[agent_id] = (
                novel_str,
                False,
                f"{novel_str} novel names against the seated union -- four seats already filled (cap).",
            )
            continue
        if count >= NOVELTY_THRESHOLD:
            seats_ids.append(agent_id)
            seat_status[agent_id] = (
                novel_str,
                True,
                f"{novel_str} novel names against the seated union (>= {NOVELTY_THRESHOLD:.2f} threshold).",
            )
        else:
            seat_status[agent_id] = (
                novel_str,
                False,
                f"{novel_str} novel names against the seated union -- below the "
                f"{NOVELTY_THRESHOLD:.2f} threshold.",
            )
    return seat_status


def _novelty(
    candidate: Sequence[frozenset[str]], seated: Sequence[Sequence[frozenset[str]]]
) -> tuple[float | None, float | None, int]:
    """``(mean novel names, mean novel fraction, invested sessions)`` for one candidate against the
    union of ``seated``. `holdings_overlap.novelty`, ported -- see that function's docstring for why
    the rule counts whole names rather than a fraction, and why sessions where the candidate holds
    nothing are skipped rather than scored.

    Asymmetric and measured against the **union** of everything already seated, per session, across
    every session in ``candidate`` -- not pairwise, and not a snapshot. ``(None, None, 0)`` when the
    candidate never held anything -- undefined, not zero.
    """
    counts: list[int] = []
    fractions: list[float] = []
    for i, held in enumerate(candidate):
        if not held:
            continue
        already: set[str] = set()
        for other in seated:
            already |= other[i]
        new = held - already
        counts.append(len(new))
        fractions.append(len(new) / len(held))
    if not counts:
        return None, None, 0
    return sum(counts) / len(counts), sum(fractions) / len(fractions), len(counts)


# ---------------------------------------------------------------------------
# select() -- the entry point
# ---------------------------------------------------------------------------


def select(round_id: str, *, settings: Settings | None = None) -> SelectionResult:
    """Derive the paper desk's roster for ``round_id``, applying Gates A/L/C, the live-median
    ranking with its tie-breaks, and the holdings-distinctness seating walk -- see the module
    docstring for the full register and `strategy-program/ROUND-12-PLAN.md` section 3 for the
    authority this is a port of.

    ``round_id`` (e.g. ``"r11-2026-08"``) selects which round's ``results/live-{1..6}`` directory the
    live matrix and the distinctness walk are read from. Gate A and the Gate S' tie-break are always
    measured against round 5's backtests regardless of ``round_id`` -- those are frozen historical
    windows, not something a later round re-runs (`PROTOCOL.md` section 6(a)).

    Never runs a backtest and never opens a write connection to the bar store -- every read goes
    through `duck.connect()` (in-memory) or a `read_only`-safe file read, matching
    `strategy-program/DEFECTS.md` D3's guidance that a concurrent write-mode reader can corrupt a
    round in progress.
    """
    settings = settings or get_settings()
    results_root = settings.rounds_dir / round_id / "results"

    # Gate A.
    a_cells = _gate_a(settings)
    gate_a_outcomes = _gate_a_outcomes(a_cells)
    survivors_a = {o.agent_id for o in gate_a_outcomes if o.passed}

    # Gate L.
    gate_l_outcomes = _gate_l_outcomes()
    survivors_l = {o.agent_id for o in gate_l_outcomes if o.passed}
    survivors_al = [agent_id for agent_id in FIELD if agent_id in survivors_a and agent_id in survivors_l]

    # Gate C, over the differenced live matrix.
    cells = _live_cells(results_root)
    gate_c_outcomes, survivors_c, live_summary = _gate_c_outcomes(survivors_al, cells)

    # Ranking: live median descending, then live hit rate, then backtest rank range (lower better),
    # then Gate A's 10y QQQ median -- `ROUND-12-PLAN.md` section 3 / `round11.py`'s `key`.
    spread = _backtest_rank_spread(settings)

    def _rank_key(agent_id: str) -> tuple[Decimal, int, int, Decimal]:
        summary = live_summary[agent_id]
        med = summary["median"]
        hits = summary["hits"]
        s = spread.get(agent_id)
        qqq10 = a_cells[agent_id]["qqq_10y"]
        # `live_summary` and `a_cells` are heterogeneous dicts, so these arrive as `object` and
        # `Decimal | bool | None` respectively and neither negation was checked by anything. At
        # runtime "median" and "qqq_10y" hold a `Decimal` or `None` (set at `_gate_c_outcomes`'s two
        # assignments and `_gate_a`'s `_median_of`), so each `isinstance` below is precisely the
        # `is not None` test this code already made -- it additionally rules out the types the
        # negation would have raised on, which is what the two suppressed errors were reporting.
        return (
            -(med if isinstance(med, Decimal) else Decimal(-99)),
            -(hits if isinstance(hits, int) else 0),
            s if s is not None else 99,
            -(qqq10 if isinstance(qqq10, Decimal) else Decimal(-99)),
        )

    ranked_ids = sorted(survivors_c, key=_rank_key)

    # Distinctness: walk the ranking, seating the first card unconditionally and every later card
    # whose novel-names count against the union of what is already seated clears the threshold, up to
    # the seat cap.
    days = _sessions(settings)
    held: dict[str, list[frozenset[str]] | None] = {
        agent_id: _held_by_session(results_root, agent_id, days) for agent_id in ranked_ids
    }

    seat_status = _seat(ranked_ids, held)

    ranking: list[SelectionSeat] = []
    for i, agent_id in enumerate(ranked_ids, start=1):
        novel_str, seated, note = seat_status[agent_id]
        summary = live_summary[agent_id]
        n = summary["n"]
        ranking.append(
            SelectionSeat(
                agent_id=agent_id,
                rank=i,
                live_median=_pct(summary["median"]),  # type: ignore[arg-type]
                live_hits=f"{summary['hits']}/{n}" if n else None,
                novel_names=novel_str,
                seated=seated,
                seated_by="rule",
                note=note,
            )
        )

    outside = SelectionSeat(
        agent_id=OUTSIDE_COMPETITION_AGENT_ID,
        rank=None,
        live_median=None,
        live_hits=None,
        novel_names=None,
        seated=True,
        seated_by="outside-competition",
        note=(
            "Seated outside the competition -- not a StrategyCard, never gated, never ranked "
            "(selected by direct analysis; see backend/app/paperdesk/desk.py's AGENT_IDS docstring)."
        ),
    )

    seats = [s for s in ranking if s.seated] + [outside]

    notes = list(MANDATORY_NOTES)
    unassessed = sorted(agent_id for agent_id in survivors_al if not cells.get(agent_id))
    if unassessed:
        notes.append(
            "No live record at all in this round's matrix for: "
            + ", ".join(unassessed)
            + " -- Gate C reports them as unassessable rather than passed or failed."
        )

    return SelectionResult(
        round_id=round_id,
        rule_version=RULE_VERSION,
        gates={"A": gate_a_outcomes, "L": gate_l_outcomes, "C": gate_c_outcomes},
        ranking=ranking,
        seats=seats,
        notes=notes,
    )
