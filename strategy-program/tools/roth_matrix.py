"""Run the two Roth strategy families over the tournament's own R5 window calendar.

**Why this script exists.** `strategy-program/tools/contributions.py` simulates a *contribution-funded*
Roth IRA -- $7,500 deposited once a year -- and the two candidate families it hosts
(`roth_momentum.py`, `roth_voltarget.py`) are each tested on their own bespoke, hand-picked windows
(`full-2006`, `gfc-2006-2011`, `schd-era-2011-2026` for momentum; `CRISIS`/`PRIMARY`/`FULL` for
voltarget). `app.tournament`'s `StrategyCard` competition, by contrast, always tests a *lump-sum*
card against the same shared calendar: `strategy-program/tools/windows.py`'s round-5 horizon ladder
(`R5_LADDER_WINDOW_TAGS`, 21 windows from 6 months to 10 years) plus its six bear-supplement windows
(`R5_BEAR_WINDOW_TAGS`). Round 11 closed by naming this gap as the binding constraint on the
programme: the two Roth families hold the only genuinely new ideas since round 5, and neither has ever
been run on the windows a future round would actually gate against. This script is that run -- not a
new strategy, not a new backtest engine, just the existing `WeightFn` factories from both modules,
replayed through the existing `contributions.simulate` harness, on the tournament's own dates.

**What this can and cannot make comparable.** Running the same calendar closes exactly one gap: "did
this variant exist for the regime a card would have been gated on." It does **not** make a Roth
variant's number the same *kind* of number as a `StrategyCard`'s `adjusted_excess` from
`strategy-program/tools/score.py` -- one is a money-weighted IRR on an account that receives new cash
every January, the other is a lump-sum excess-over-benchmark on an account funded once at inception.
Putting the two in one ranked column would be exactly the mistake `strategy-program/tools/
contributions.py`'s own docstring warns about: sequence risk *inverts* between the two account shapes,
so a number that looks good funded one way can look mediocre funded the other. This script reports a
same-shape benchmark instead (buy-and-hold SPY and QQQ, contributed on the identical annual schedule),
so a variant's number here is read as an excess over a contribution-funded passive alternative, never
against a tournament card's lump-sum figure.

**A second, load-bearing limitation, discovered by running this rather than assumed in advance.** Two
of `roth_momentum.py`'s four strategies -- absolute momentum and the confirmed-regime blend -- gate
their first real position on a 200- or 252-*session* lookback computed from **only the bars inside the
window being tested**, because `WeightFn` warmup guards on the session index `i` and this script feeds
each window its own bars from the window's own start (matching how `app.tournament` bounds a card's
own data, and how `strategy-program/tools/windows.py`'s eligibility check treats "history before the
window" as a symbol-coverage question rather than something this script re-derives for a rule's
internal lookback). For any window shorter than that lookback -- every one of round 5's 6-month and
1-year ladder slots -- the strategy never leaves its initial defensive weight and the row is
indistinguishable from the static baseline it is meant to beat. This is flagged per-row below (a `*`
after the strategy name) rather than hidden or worked around: the fix (priming state from bars before
the window starts, without letting that lead-in also collect a phantom contribution) is real work for
whoever wires this into the tournament proper, not a two-line patch this script should improvise.

**Symbols and coverage.** Every variant below uses only QLD, SCHD, IEF, SPY and QQQ, and every round-5
ladder/bear window starts in 2013 or later -- after SCHD's own first bar (2011-10-20), so no window in
this run is skipped for data coverage. That is a property of *this* symbol selection, not a guarantee
this script provides in general: `eligible_for` below still checks first-bar coverage per variant per
window and marks a cell `SKIPPED` rather than fabricating a result, exactly as `score.py` treats a
missing cell, for whichever future variant or window combination does not clear it.

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/roth_matrix.py

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen), so it is invoked by file path with `backend` and the repo root already on ``PYTHONPATH``, the
same convention every other script in this directory uses.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import statistics
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from app.config import get_settings
from app.db import duck

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLS_DIR = _REPO_ROOT / "strategy-program" / "tools"
_OUT_DIR = _REPO_ROOT / "data" / "rounds" / "r12-2026-08"


def _load_sibling(name: str, filename: str) -> ModuleType:
    """Load a `strategy-program/tools/*.py` sibling by file path.

    `strategy-program` is not a legal Python package name (the hyphen), so none of these files can be
    reached with an ordinary `import`. Every sibling module in this directory that needs another one
    (`roth_momentum.py` and `roth_voltarget.py` both load `contributions.py` this way already) uses
    `importlib.util.spec_from_file_location` for exactly this reason; this helper is the same pattern,
    generalised to also load `roth_momentum.py`, `roth_voltarget.py` and `windows.py` themselves so
    this script can call their real functions instead of re-typing any strategy rule or window date.
    """
    path = _TOOLS_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {filename} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# Load once at import time. `roth_momentum` and `roth_voltarget` each load their own private copy of
# `contributions.py` into `sys.modules["contributions"]` under a name the other overwrites -- harmless,
# because each module keeps its own reference (`roth_momentum.contrib`, `roth_voltarget.contrib`) and
# neither ever looks the name back up through `sys.modules` after exec'ing it. Either module's `contrib`
# attribute is the same code (`contributions.py` verbatim), so `roth_momentum.contrib` is used
# throughout below as the one copy this script calls.
roth_momentum = _load_sibling("roth_momentum", "roth_momentum.py")
roth_voltarget = _load_sibling("roth_voltarget", "roth_voltarget.py")
windows_mod = _load_sibling("rm_windows", "windows.py")
contrib = roth_momentum.contrib

WeightFn = Callable[[int, Mapping[str, Sequence[float]]], dict[str, float]]

#: Every symbol any variant or benchmark below touches. Loaded once, in full, so eligibility can be
#: decided from real first-bar dates rather than the coverage dates quoted in the brief -- those are a
#: starting point for a human, not something this script should trust without checking the store it is
#: about to read from anyway.
ALL_SYMBOLS: tuple[str, ...] = ("QLD", "SCHD", "IEF", "SPY", "QQQ")

#: The two benchmark names, used to look results back up out of a window's result dict when computing
#: excess figures. Kept as constants rather than re-typed at each call site so a typo cannot silently
#: produce a `None` benchmark instead of a `KeyError`.
SPY_BENCH = "SPY buy & hold"
QQQ_BENCH = "QQQ buy & hold"


@dataclass(frozen=True)
class Variant:
    """One strategy or benchmark this script runs, as a thin wrapper around the real `WeightFn`
    factory in `roth_momentum.py` / `roth_voltarget.py` -- this dataclass adds nothing to the
    strategy itself, only the bookkeeping (which family, which symbols, how much lookback it needs
    before it can possibly deviate from its own initial defensive weight) needed to run it across many
    windows and report the result honestly.
    """

    family: str
    name: str
    symbols: tuple[str, ...]
    build: Callable[[list[dt.date]], WeightFn]
    #: The best candidate named in the variant's own source document (`ROTH-MOMENTUM.md` /
    #: `ROTH-VOLTARGET.md`), reported so the table can mark it without a reader cross-referencing.
    is_candidate: bool = False
    #: Session count before the strategy's own state can first differ from its initial all-defensive
    #: (or, for the vol-scaled family, near-immediately-reactive) weight -- see the module docstring's
    #: warmup-vs-window-length caveat. `0` for anything with no such warmup (baselines, buy-and-hold).
    warmup_bars: int = 0


MOMENTUM_VARIANTS: list[Variant] = [
    Variant(
        family="ROTH-MOMENTUM",
        name="abs momentum (QLD/SCHD)",
        symbols=("QLD", "SCHD"),
        build=lambda dates: roth_momentum.make_abs_momentum(dates, "QLD", "SCHD"),
        warmup_bars=roth_momentum.LOOKBACK_12M,
    ),
    Variant(
        family="ROTH-MOMENTUM",
        name="MA regime (QLD vs 50/50 SCHD/IEF, sig SPY200)",
        symbols=("QLD", "SCHD", "IEF", "SPY"),
        build=lambda dates: roth_momentum.make_ma_regime(
            dates, "QLD", {"SCHD": 0.5, "IEF": 0.5}, "SPY"
        ),
        is_candidate=True,  # ROTH-MOMENTUM.md's "single best candidate"
        warmup_bars=roth_momentum.MA_WINDOW,
    ),
    Variant(
        family="ROTH-MOMENTUM",
        name="confirmed regime (QLD vs 50/50 SCHD/IEF)",
        symbols=("QLD", "SCHD", "IEF", "SPY"),
        build=lambda dates: roth_momentum.make_confirmed_regime(
            dates, "QLD", {"SCHD": 0.5, "IEF": 0.5}, "SPY"
        ),
        # The confirmed-regime blend can leave its all-defensive state as soon as *either* leg fires --
        # the trend leg (200-session) is the faster of the two -- so its warmup is the shorter of the
        # pair, not the momentum leg's 252 alone.
        warmup_bars=min(roth_momentum.MA_WINDOW, roth_momentum.LOOKBACK_12M),
    ),
    Variant(
        family="ROTH-MOMENTUM",
        name="static 40/30/30 QLD/SCHD/IEF",
        symbols=("QLD", "SCHD", "IEF"),
        build=lambda dates: roth_momentum.make_static({"QLD": 0.40, "SCHD": 0.30, "IEF": 0.30}),
    ),
]

VOLTARGET_VARIANTS: list[Variant] = [
    Variant(
        family="ROTH-VOLTARGET",
        name="voltarget 12% QLD/IEF (lb20)",
        symbols=("QLD", "IEF"),
        build=lambda dates: roth_voltarget.make_vol_target("QLD", "IEF", 0.12, 20),
        is_candidate=True,  # ROTH-VOLTARGET.md's "best candidate"
        warmup_bars=20,
    ),
    Variant(
        family="ROTH-VOLTARGET",
        name="risk-budgeted core (lb20)",
        symbols=("QLD", "SCHD", "IEF"),
        build=lambda dates: roth_voltarget.make_risk_budgeted_core("QLD", "SCHD", "IEF", 0.12, 20),
        warmup_bars=20,  # ROTH-VOLTARGET.md's "credible second choice"
    ),
    Variant(
        family="ROTH-VOLTARGET",
        name="circuit-breaker (lb20)",
        symbols=("QLD", "SCHD", "IEF"),
        build=lambda dates: roth_voltarget.make_circuit_breaker(
            {"QLD": 0.40, "SCHD": 0.30, "IEF": 0.30}, "QLD", "QLD", 20, 0.45, 0.30
        ),
        warmup_bars=20,  # ROTH-VOLTARGET.md: "flag rather than either keep or discard outright"
    ),
]

BENCHMARKS: list[Variant] = [
    Variant(
        family="benchmark", name=SPY_BENCH, symbols=("SPY",),
        build=lambda dates: roth_voltarget.make_buy_hold("SPY"),
    ),
    Variant(
        family="benchmark", name=QQQ_BENCH, symbols=("QQQ",),
        build=lambda dates: roth_voltarget.make_buy_hold("QQQ"),
    ),
]

ALL_VARIANTS: list[Variant] = MOMENTUM_VARIANTS + VOLTARGET_VARIANTS + BENCHMARKS


def load_all_closes(
    symbols: Sequence[str],
) -> tuple[dict[str, dict[dt.date, float]], dict[str, dt.date]]:
    """Every stored daily close for `symbols`, as `{symbol: {date: close}}`, plus each symbol's first
    stored session date -- read once, in full, via `duck.read_bars` exactly as `strategy-program/
    tools/windows.py`'s own `symbol_first_bar` does, rather than trusting the coverage dates quoted in
    a brief. A read-only connection, per that module's own warning: the default connection takes a
    write lock that turns a concurrent reader elsewhere in the store into an `IOException`
    indistinguishable from a missing ticker.
    """
    settings = get_settings()
    closes: dict[str, dict[dt.date, float]] = {}
    first_bar: dict[str, dt.date] = {}
    with duck.connect(settings.analytics_path, read_only=True) as conn:
        for symbol in symbols:
            frame = duck.read_bars(conn, settings.bars_dir, symbol, duck.Interval.DAY)
            if frame.empty:
                closes[symbol] = {}
                continue
            by_date = {
                ts.date(): float(c)
                for ts, c in zip(frame["ts"], frame["close"], strict=True)
            }
            closes[symbol] = by_date
            first_bar[symbol] = min(by_date)
    return closes, first_bar


def eligibility_reason(
    symbols: Sequence[str], first_bar: Mapping[str, dt.date], window_start: dt.date
) -> str | None:
    """Why `symbols` cannot run in a window starting `window_start`, or `None` if they can.

    Two checks, in the same order `strategy-program/tools/windows.py`'s `eligible_windows` uses:
    missing history entirely (a symbol never stored) is reported by name; a symbol whose first bar
    postdates the window start is reported with both dates, naming the binding (latest-starting)
    symbol so a reader does not have to check every symbol in the set by hand.
    """
    missing = sorted(s for s in symbols if s not in first_bar)
    if missing:
        reason = f"{missing[0]} has no stored bars"
        if len(missing) > 1:
            reason += f" (also missing: {', '.join(missing[1:])})"
        return reason
    late = [s for s in symbols if first_bar[s] > window_start]
    if late:
        binding = max(late, key=lambda s: first_bar[s])
        return (
            f"{binding} first bar {first_bar[binding].isoformat()}, "
            f"window starts {window_start.isoformat()}"
        )
    return None


@dataclass
class Cell:
    """One (variant, window) outcome -- a run result or the reason it was skipped, never both, and
    never a fabricated number standing in for a skip. Mirrors `score.py`'s `WindowCell` in spirit:
    a missing result is a fact about that cell, not a zero.
    """

    status: str  # "run" | "skipped"
    reason: str | None = None
    result: contrib.ContributionResult | None = None
    signal_activated: bool = True
    excess_irr_spy: float | None = None
    excess_twr_spy: float | None = None
    excess_irr_qqq: float | None = None
    excess_twr_qqq: float | None = None


def _excess(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def run_window(
    tag: str,
    start: dt.date,
    end: dt.date,
    closes: Mapping[str, Mapping[dt.date, float]],
    first_bar: Mapping[str, dt.date],
) -> tuple[list[dt.date], dict[str, Cell]]:
    """Run every variant and both benchmarks over one tournament window, on a single shared date grid.

    The date grid is the intersection of *every* symbol any variant or benchmark below touches
    (`ALL_SYMBOLS`), not just the symbols the one variant being run needs -- so every row in a window's
    table is quoting the same contribution schedule (`contributions.contribution_dates` keys off the
    date list's own year boundaries) as every other row, which is what makes the excess-over-benchmark
    columns a fair same-shape comparison rather than two runs that happened to start on different days.
    """
    common = sorted(set.intersection(*(set(closes[s]) for s in ALL_SYMBOLS)))
    dates = [d for d in common if start <= d <= end]

    cells: dict[str, Cell] = {}
    for variant in ALL_VARIANTS:
        reason = eligibility_reason(variant.symbols, first_bar, start)
        if reason is None and len(dates) < 2:
            reason = f"only {len(dates)} overlapping session(s) in window"
        if reason is not None:
            cells[variant.name] = Cell(status="skipped", reason=reason)
            continue
        variant_closes = {s: [closes[s][d] for d in dates] for s in variant.symbols}
        weight_fn = variant.build(dates)
        result = contrib.simulate(dates, variant_closes, weight_fn)
        cells[variant.name] = Cell(
            status="run", result=result, signal_activated=len(dates) > variant.warmup_bars
        )

    spy_r = cells[SPY_BENCH].result if cells[SPY_BENCH].status == "run" else None
    qqq_r = cells[QQQ_BENCH].result if cells[QQQ_BENCH].status == "run" else None
    for cell in cells.values():
        if cell.status != "run":
            continue
        r = cell.result
        assert r is not None
        cell.excess_irr_spy = _excess(r.irr, spy_r.irr if spy_r else None) if spy_r else None
        cell.excess_twr_spy = (
            r.time_weighted_cagr - spy_r.time_weighted_cagr if spy_r is not None else None
        )
        cell.excess_irr_qqq = _excess(r.irr, qqq_r.irr if qqq_r else None) if qqq_r else None
        cell.excess_twr_qqq = (
            r.time_weighted_cagr - qqq_r.time_weighted_cagr if qqq_r is not None else None
        )

    return dates, cells


def _fmt_pct(x: float | None) -> str:
    return "   n/a" if x is None else f"{x * 100:5.1f}%"


EXTRA_HEADER = f"  {'exIRR~SPY':>9}  {'exTWR~SPY':>9}  {'exIRR~QQQ':>9}  {'exTWR~QQQ':>9}"


def render_row(name: str, cell: Cell) -> str:
    r = cell.result
    assert r is not None
    label = name if cell.signal_activated else f"{name} *"
    base = contrib.summarise(label, r)
    return (
        f"{base}  {_fmt_pct(cell.excess_irr_spy):>9}  {_fmt_pct(cell.excess_twr_spy):>9}  "
        f"{_fmt_pct(cell.excess_irr_qqq):>9}  {_fmt_pct(cell.excess_twr_qqq):>9}"
    )


@dataclass
class Aggregate:
    """One variant's roll-up over the windows it actually ran, within one arm (ladder or bear) -- the
    same shape `score.py`'s `CardScore` reports for a tournament card, so a future round gating these
    variants beside `StrategyCard`s has a head start on what the aggregate should look like, without
    this script pretending the two are the same unit (see the module docstring).
    """

    n_windows_total: int
    n_run: int
    n_skipped: int
    n_no_signal: int
    median_excess_irr_spy: float | None
    worst_excess_irr_spy: float | None
    hit_rate_spy: float | None


def aggregate(tags: Sequence[str], per_window: Mapping[str, dict[str, Cell]], name: str) -> Aggregate:
    """Roll one variant's cells up over `tags` (a list of window tags within one arm)."""
    run_cells = [per_window[t][name] for t in tags if per_window[t][name].status == "run"]
    skipped = [per_window[t][name] for t in tags if per_window[t][name].status == "skipped"]
    no_signal = [c for c in run_cells if not c.signal_activated]
    values = [c.excess_irr_spy for c in run_cells if c.excess_irr_spy is not None]
    return Aggregate(
        n_windows_total=len(tags),
        n_run=len(run_cells),
        n_skipped=len(skipped),
        n_no_signal=len(no_signal),
        median_excess_irr_spy=statistics.median(values) if values else None,
        worst_excess_irr_spy=min(values) if values else None,
        hit_rate_spy=(sum(1 for v in values if v > 0) / len(values)) if values else None,
    )


def common_support(
    tags: Sequence[str], per_window: Mapping[str, dict[str, Cell]], names: Sequence[str]
) -> list[str]:
    """The window tags on which **every** named variant actually had its signal live.

    The only subset on which a cross-variant ranking means anything. A variant whose rule needs a
    200-252 session lookback cannot activate inside a 6-month window -- the book holds its fallback
    sleeve start to finish -- so a median that mixes those cells with live ones is comparing one
    strategy against another strategy's fallback. Restricting to common support costs windows (11 of
    21 on the ladder arm) and buys the ability to say "A beat B" without that meaning "A beat B's
    cash position".

    Deliberately computed across the *whole* variant list rather than pairwise: a pairwise subset
    would give every comparison its own window set, and two such comparisons could then disagree
    transitively while both looked sound.
    """
    return [
        tag
        for tag in tags
        if all(
            per_window[tag][name].status == "run" and per_window[tag][name].signal_activated
            for name in names
        )
    ]


def _cell_to_json(cell: Cell) -> dict:
    if cell.status == "skipped":
        return {"status": "skipped", "reason": cell.reason}
    r = cell.result
    assert r is not None
    return {
        "status": "run",
        "signal_activated": cell.signal_activated,
        "final_balance": r.final_balance,
        "total_contributed": r.total_contributed,
        "multiple": r.multiple,
        "irr": r.irr,
        "time_weighted_cagr": r.time_weighted_cagr,
        "max_drawdown": r.max_drawdown,
        "mar": r.mar,
        "rebalances": r.rebalances,
        "excess_irr_spy": cell.excess_irr_spy,
        "excess_twr_spy": cell.excess_twr_spy,
        "excess_irr_qqq": cell.excess_irr_qqq,
        "excess_twr_qqq": cell.excess_twr_qqq,
    }


def main() -> int:
    out_lines: list[str] = []

    def emit(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    emit(
        f"Roth strategy matrix -- the two Roth candidate families run through "
        f"contributions.py (${contrib.ANNUAL_CONTRIBUTION:,.0f}/year) over app.tournament's own "
        f"round-5 window calendar (strategy-program/tools/windows.py: R5_LADDER_WINDOW_TAGS + "
        f"R5_BEAR_WINDOW_TAGS)."
    )
    emit(
        "This is NOT a StrategyCard run and these numbers are NOT comparable to a card's "
        "adjusted_excess in score.py -- contribution-funded IRR/TWR here, lump-sum excess there. "
        "See this script's module docstring."
    )
    emit(
        "A row marked '*' never left its own initial defensive weight within this window -- its "
        "lookback exceeds the window's own session count. See the module docstring."
    )

    closes, first_bar = load_all_closes(ALL_SYMBOLS)
    emit()
    emit("Symbol coverage (first stored session):")
    for symbol in ALL_SYMBOLS:
        if symbol in first_bar:
            emit(f"  {symbol:6} {first_bar[symbol].isoformat()}")
        else:
            emit(f"  {symbol:6} NO STORED BARS")

    ladder_tags = list(windows_mod.R5_LADDER_WINDOW_TAGS)
    bear_tags = list(windows_mod.R5_BEAR_WINDOW_TAGS)
    all_tags = ladder_tags + bear_tags

    per_window: dict[str, dict[str, Cell]] = {}
    for tag in all_tags:
        start, end, regime = windows_mod.WINDOWS[tag]
        horizon = windows_mod.R5_HORIZON.get(tag, "?")
        arm = "ladder" if tag in ladder_tags else "bear"
        dates, cells = run_window(tag, start, end, closes, first_bar)
        per_window[tag] = cells

        emit()
        emit(
            f"=== {tag} ({arm}, {horizon}): {start} .. {end} -- {regime} "
            f"({len(dates)} shared sessions) ==="
        )
        emit(contrib.HEADER + EXTRA_HEADER)
        skip_notes: list[str] = []
        for variant in ALL_VARIANTS:
            cell = cells[variant.name]
            if cell.status == "skipped":
                skip_notes.append(f"  SKIPPED {variant.name}: {cell.reason}")
                continue
            emit(render_row(variant.name, cell))
        if skip_notes:
            emit("  --")
            for line in skip_notes:
                emit(line)

    emit()
    emit("=" * 100)
    emit("Aggregate over the round-5 ladder (21 windows, 6mo-10y) and bear-supplement (6 windows) arms")
    emit("=" * 100)
    emit(
        f"{'variant':46} {'ladder n':>9} {'skip':>5} {'no-sig':>7} {'med exIRR~SPY':>14} "
        f"{'worst exIRR~SPY':>16} {'hit%':>6}   {'bear n':>7} {'med exIRR~SPY':>14}"
    )
    for variant in MOMENTUM_VARIANTS + VOLTARGET_VARIANTS:
        lad = aggregate(ladder_tags, per_window, variant.name)
        bear = aggregate(bear_tags, per_window, variant.name)
        tag = " *" if variant.is_candidate else ""
        hit_str = "  n/a" if lad.hit_rate_spy is None else f"{lad.hit_rate_spy * 100:5.1f}"
        emit(
            f"{variant.name + tag:46} "
            f"{lad.n_run:>5}/{lad.n_windows_total:<3} {lad.n_skipped:>5} {lad.n_no_signal:>7} "
            f"{_fmt_pct(lad.median_excess_irr_spy):>14} {_fmt_pct(lad.worst_excess_irr_spy):>16} "
            f"{hit_str:>6}   "
            f"{bear.n_run:>4}/{bear.n_windows_total:<3} {_fmt_pct(bear.median_excess_irr_spy):>14}"
        )
    emit("(* = the best candidate named in that family's own document)")
    emit()
    emit(
        "  ^ 'no-sig' counts windows too short for that variant's own lookback to activate. Those"
    )
    emit(
        "    cells are the fallback sleeve held start to finish, NOT the strategy, and they are in"
    )
    emit("    the medians above. Do not rank variants off that table -- use the next one.")

    # The comparable view. See `common_support` for why the medians above cannot be ranked against
    # each other and this one can.
    all_names = [v.name for v in MOMENTUM_VARIANTS + VOLTARGET_VARIANTS]
    emit()
    emit("=" * 100)
    emit("COMMON SUPPORT -- only windows where every variant's signal is live")
    emit("=" * 100)
    for arm_name, arm_tags in (("ladder", ladder_tags), ("bear", bear_tags)):
        common = common_support(arm_tags, per_window, all_names)
        emit(
            f"{arm_name}: {len(common)} of {len(arm_tags)} windows qualify "
            f"({', '.join(common) if common else 'none'})"
        )
        rows = []
        for variant in MOMENTUM_VARIANTS + VOLTARGET_VARIANTS:
            vals = [
                per_window[tag][variant.name].excess_irr_spy
                for tag in common
                if per_window[tag][variant.name].excess_irr_spy is not None
            ]
            if vals:
                rows.append((statistics.median(vals), variant.name, len(vals)))
        for med, name, n in sorted(rows, reverse=True):
            emit(f"   {name:46} {_fmt_pct(med):>10}  n={n}")
        emit()
    emit(
        "The ordering here differs from the table above, and this one is the comparable one. On the"
    )
    emit(
        "ladder arm the starved cells drag the momentum family below the static baseline; with them"
    )
    emit("excluded the ordering reverses. Neither table is wrong -- they answer different questions.")

    emit()
    emit("Per-horizon breakdown, ladder arm only (bear windows carry a deliberate downward regime")
    emit("bias -- see windows.py's own module docstring -- and are kept out of this breakdown so a")
    emit("horizon's number is not silently part-ordinary-market, part-crash):")
    for variant in MOMENTUM_VARIANTS + VOLTARGET_VARIANTS:
        emit(f"  {variant.name}")
        by_horizon: dict[str, list[str]] = {}
        for t in ladder_tags:
            by_horizon.setdefault(windows_mod.R5_HORIZON[t], []).append(t)
        for horizon in ("6m", "1y", "3y", "5y", "10y"):
            tags_h = by_horizon.get(horizon, [])
            if not tags_h:
                continue
            agg = aggregate(tags_h, per_window, variant.name)
            emit(
                f"    {horizon:>4}: {agg.n_run}/{agg.n_windows_total} run, "
                f"{agg.n_no_signal} no-signal, median exIRR~SPY {_fmt_pct(agg.median_excess_irr_spy)}"
            )

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    (_OUT_DIR / "roth-matrix.txt").write_text("\n".join(out_lines) + "\n", encoding="utf-8")

    payload = {
        "generated_for": "round 12 candidate evaluation",
        "annual_contribution": contrib.ANNUAL_CONTRIBUTION,
        "symbols": {s: (first_bar[s].isoformat() if s in first_bar else None) for s in ALL_SYMBOLS},
        "windows": {
            tag: {
                "start": windows_mod.WINDOWS[tag][0].isoformat(),
                "end": windows_mod.WINDOWS[tag][1].isoformat(),
                "regime": windows_mod.WINDOWS[tag][2],
                "horizon": windows_mod.R5_HORIZON.get(tag),
                "arm": "ladder" if tag in ladder_tags else "bear",
                "cells": {name: _cell_to_json(cell) for name, cell in per_window[tag].items()},
            }
            for tag in all_tags
        },
        "common_support": {
            arm_name: {
                "windows": common_support(
                    arm_tags, per_window, [v.name for v in MOMENTUM_VARIANTS + VOLTARGET_VARIANTS]
                ),
                "median_excess_irr_spy": {
                    variant.name: (
                        statistics.median(vals)
                        if (
                            vals := [
                                per_window[tag][variant.name].excess_irr_spy
                                for tag in common_support(
                                    arm_tags,
                                    per_window,
                                    [v.name for v in MOMENTUM_VARIANTS + VOLTARGET_VARIANTS],
                                )
                                if per_window[tag][variant.name].excess_irr_spy is not None
                            ]
                        )
                        else None
                    )
                    for variant in MOMENTUM_VARIANTS + VOLTARGET_VARIANTS
                },
            }
            for arm_name, arm_tags in (("ladder", ladder_tags), ("bear", bear_tags))
        },
        "aggregate": {
            variant.name: {
                "is_candidate": variant.is_candidate,
                "ladder": aggregate(ladder_tags, per_window, variant.name).__dict__,
                "bear": aggregate(bear_tags, per_window, variant.name).__dict__,
            }
            for variant in MOMENTUM_VARIANTS + VOLTARGET_VARIANTS
        },
    }
    (_OUT_DIR / "roth-matrix.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nwrote {_OUT_DIR / 'roth-matrix.txt'}")
    print(f"wrote {_OUT_DIR / 'roth-matrix.json'}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
