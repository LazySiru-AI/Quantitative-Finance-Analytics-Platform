"""Score a *combined book* of several strategy cards, not just each card alone.

Three rounds have scored every card in isolation. The strongest result available so far turned out
to be about a *pair*, not a card: `B-momentum`, `C-trend` and `c14-riskmanaged-wide`, held in equal
thirds, roughly halve the worst window a person could have hit -- `C-trend` alone posts -22.9% in
its worst window; the trio posts -11.1% -- because `C-trend` and `c14` are effectively uncorrelated
(rho ~= +0.04) while `B` and `C` are two versions of the same trade (rho ~= +0.57). See
`strategy-program/ROUND-4-PLAN.md` Sec 1, where that table was built by hand. This module makes it a
tool.

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe \\
        strategy-program/tools/portfolio.py \\
        --results data/rounds/r3-2026-08/results \\
        --cards B-momentum --cards C-trend --cards c14-riskmanaged-wide \\
        [--json out.json]

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen), so it can only be invoked by file path, with `backend` and the repo root already on
``PYTHONPATH`` for the `app.*` imports this module makes.

**The per-result metrics are duplicated from `strategy-program/tools/score.py`, not imported.**
`score.py`'s own module docstring explains why: the two files are siblings under a hyphenated
directory, which is not a legal Python package name, so an import between them needs either a
``sys.path`` hack or an ``importlib.util.spec_from_file_location`` dance -- more fragile than keeping
a few short functions in sync by inspection. If either file's formula changes, both need updating
either way; a shared import would only save noticing it in one place instead of two. See
`strategy-program/DEFECTS.md` D1 and D2 for why `corrected_return` and `capital_exposure` exist at
all rather than reading `AgentResult.total_return`/`AgentResult.exposure` directly.

**Combining.** For a named set of cards and a set of windows, each window is scored **equal-weight**:
every card gets ``1/n`` of the book. A card that has no run file for a window -- `B-momentum` and
`C-trend` are structurally ineligible for `gfc` and `chop-2011`, having never traded a name whose
history reaches that far back -- holds **cash** for that window and contributes ``0.0`` to the
combined return on its share, rather than being excluded or treated as `NaN`. Excluding it would
silently rescale the other members' weights and report a different, easier book than the one a
person could actually have held; a card missing three of eight windows is not "the book, minus the
windows it couldn't run" -- it is a book that was two-thirds in cash for those three.

The book's combined `capital_exposure` is reported the same way: the mean of the members' own
`capital_exposure` for that window, with an absent member contributing ``0.0``. `adjusted_excess` is
then computed from *that* combined exposure, not from any member's own. Skipping this is the D2
artifact all over again at the book level: a book that is two-thirds cash in `gfc` "beating" a -56%
benchmark by 55 points is a statement about non-participation, not skill, and burying the combined
exposure would hide exactly the number that says so.

**The correlation matrix** is the pairwise Pearson correlation of two members' *per-window*
`corrected_return` values, computed only over the windows **both** members actually ran -- never
imputing a return for a window one of them could not trade, which would fabricate the very
comovement the matrix exists to measure. Each pair is reported with its sample count `n` alongside
rho. With a main-window matrix of eight tags, most pairs have `n` in the 4-8 range: these are small
samples, and a bare correlation coefficient with no `n` beside it invites more confidence than eight
points (or fewer, for two members with disjoint eligibility) can support. Read a `rho` next to a
small `n` as suggestive, not as a settled property of the strategies.
"""

from __future__ import annotations

import argparse
import itertools
import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.tournament.models import AgentResult

__all__ = [
    "MAIN_WINDOW_TAGS",
    "PairCorrelation",
    "PortfolioScore",
    "PortfolioWindow",
    "WindowMember",
    "adjusted_excess",
    "capital_exposure",
    "combine_window",
    "corrected_return",
    "correlation_matrix",
    "excess",
    "load_results",
    "render_markdown",
    "score_portfolio",
]

#: The eight round-2/round-3 regime tags. Duplicated from `strategy-program/tools/windows.MAIN_WINDOWS`
#: (and from `score.py`'s own copy of the same list) rather than imported -- see the module docstring.
MAIN_WINDOW_TAGS: tuple[str, ...] = (
    "q4-2018",
    "covid",
    "bear-2022",
    "chop-2015",
    "chop-2011",
    "bull-2024",
    "recent",
    "gfc",
)


# ---------------------------------------------------------------------------
# Per-result metrics -- duplicated from score.py; see the module docstring
# ---------------------------------------------------------------------------


def corrected_return(result: AgentResult) -> Decimal:
    """The card's actual return: ``ending_equity / starting_equity - 1``.

    **Not** `result.total_return` -- see `strategy-program/DEFECTS.md` D1. Under the pre-fix engine
    that field was silently rebased to the first session's close rather than to starting equity;
    this quantity is correct under every engine version, which is why it -- and not the model field
    -- is what both this module and `score.py` compute from.
    """
    return result.ending_equity / result.starting_equity - 1


def capital_exposure(result: AgentResult) -> Decimal | None:
    """Time-weighted fraction of starting capital actually at risk, from the engine's own figure
    where present, else reconstructed from the trade log.

    **Not** `result.exposure` -- see `strategy-program/DEFECTS.md` D2. That field is the fraction of
    *sessions* on which the card held anything at all, regardless of how much; a four-slot card
    holding one slot every session reports ``1.0`` there with a quarter of its capital deployed.
    Multiplying a benchmark return by that figure -- rather than by this one -- is exactly the
    mistake D2 documents.

    `None` only for a card that took no trades, or where `sessions` is zero -- an unmeasurable
    exposure, not a zero one.
    """
    engine_figure = getattr(result, "capital_exposure", None)
    if engine_figure is not None:
        return Decimal(str(engine_figure))
    if not result.trades or result.sessions <= 0 or result.starting_equity <= 0:
        return None
    invested = sum(t.quantity * t.entry_price * t.bars_held for t in result.trades)
    return Decimal(invested) / (Decimal(result.sessions) * result.starting_equity)


def excess(result: AgentResult) -> Decimal | None:
    """``corrected_return - benchmark_return``. `None` when the window's own benchmark return is
    unknown -- never substituted with zero, which would silently claim the strategy tied the
    benchmark."""
    if result.benchmark_return is None:
        return None
    return corrected_return(result) - result.benchmark_return


def adjusted_excess(result: AgentResult) -> Decimal | None:
    """``corrected_return - (capital_exposure * benchmark_return)`` -- the metric that survives
    scrutiny once exposure is accounted for; see `strategy-program/DEFECTS.md` D2 and `score.py`'s
    module docstring for why raw `excess` over-credits simply being invested.

    Falls back to the session-presence `result.exposure` only when the card took no trades at all,
    where the two coincide at zero anyway. `None` when the benchmark is unknown.
    """
    if result.benchmark_return is None:
        return None
    exposure = capital_exposure(result)
    if exposure is None:
        if result.exposure is None:
            return None
        exposure = Decimal(str(result.exposure))
    return corrected_return(result) - (exposure * result.benchmark_return)


#: Trading days per year, matching `strategy-program/tools/windows.py`'s `_TRADING_DAYS_PER_YEAR`
#: and `score.py`'s constant of the same purpose. Duplicated here for the reason the module
#: docstring gives for duplicating the metric functions themselves.
_TRADING_DAYS_PER_YEAR = 252


def window_years(result: AgentResult) -> Decimal | None:
    """The window's length in years, derived from ``result.sessions``.

    Derived from the session count rather than from the window's calendar dates because **an
    `AgentResult` does not carry its window's dates**. They exist only on the sibling per-window
    `tournament.json`, which neither this module nor `score.py` reads -- both load `runs/` only.
    Checked against `data/rounds/r5-2026-08/windows.json`'s real session counts, `sessions / 252`
    lands within about a percent of every round-5 horizon's nominal length (125-127 sessions to
    ~0.5y, 2515-2517 to ~10.0y), which is far inside the tolerance a fractional root needs.

    `None` for a zero-session window, which is degenerate rather than instantaneous.
    """
    if result.sessions <= 0:
        return None
    return Decimal(result.sessions) / Decimal(_TRADING_DAYS_PER_YEAR)


def _annualize(total: Decimal, years: Decimal | None) -> Decimal | None:
    """``(1 + total) ** (1 / years) - 1``, or `None` where that is undefined.

    A return at or below -100% cannot be annualized -- the base of the root is zero or negative and
    there is no real answer -- and this returns `None` rather than clamping, because a clamped value
    would render as an ordinary number in a table and be read as one.

    The root is taken in `float` and converted back. Every other metric in this module is exact
    `Decimal` arithmetic and a test asserts on exact values; that exactness is preserved for the
    non-annualized path, and is not available here at all, since `Decimal` has no fractional power.
    """
    if years is None or years <= 0:
        return None
    base = float(total) + 1.0
    if base <= 0.0:
        return None
    return Decimal(str(base ** (1.0 / float(years)) - 1.0))


def annualized_return(result: AgentResult) -> Decimal | None:
    """`corrected_return` expressed as a compound annual rate. See `_annualize`."""
    return _annualize(corrected_return(result), window_years(result))


def annualized_benchmark(result: AgentResult) -> Decimal | None:
    """The window's benchmark return as a compound annual rate. `None` when it is unknown."""
    if result.benchmark_return is None:
        return None
    return _annualize(result.benchmark_return, window_years(result))


def annualized_adjusted_excess(result: AgentResult) -> Decimal | None:
    """``annualized_return - capital_exposure * annualized_benchmark``.

    The exposure correction is applied to the *annualized* benchmark rather than annualizing the
    already-corrected figure, and the two are not the same. Annualizing `adjusted_excess` directly
    would take a root of a quantity that is a difference of two returns, which is not a growth rate
    and has no compound annual equivalent -- for a card that trailed its benchmark the quantity is
    negative and the root is undefined outright. Correcting after annualizing keeps both terms
    growth rates throughout, which is the only reading under which the subtraction means anything.
    """
    ann = annualized_return(result)
    bench = annualized_benchmark(result)
    if ann is None or bench is None:
        return None
    exposure = capital_exposure(result)
    if exposure is None:
        if result.exposure is None:
            return None
        exposure = Decimal(str(result.exposure))
    return ann - (exposure * bench)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _discover_window_tags(results_root: Path) -> list[str]:
    """Every subdirectory of ``results_root`` that looks like a window's output (has a ``runs/``
    folder), main windows first in their canonical order, then anything else alphabetically --
    duplicated from `score.py`'s function of the same name; see the module docstring."""
    if not results_root.is_dir():
        return []
    found = {p.name for p in results_root.iterdir() if p.is_dir() and (p / "runs").is_dir()}
    ordered = [tag for tag in MAIN_WINDOW_TAGS if tag in found]
    ordered += sorted(found - set(MAIN_WINDOW_TAGS))
    return ordered


def _discover_round_tag(results_root: Path, window_tags: Sequence[str]) -> str | None:
    """Infer the round prefix from the run filenames on disk -- duplicated from `score.py`'s function
    of the same name; see that function's docstring for the reasoning and `_discover_window_tags`
    above for why it is duplicated rather than imported."""
    prefixes: set[str] = set()
    for tag in window_tags:
        runs_dir = results_root / tag / "runs"
        if not runs_dir.is_dir():
            continue
        for path in runs_dir.glob("*.json"):
            prefixes.add(path.stem.split("-", 1)[0])
    return prefixes.pop() if len(prefixes) == 1 else None


def load_results(
    results_root: Path, round_tag: str, window_tags: Sequence[str]
) -> dict[str, dict[str, AgentResult]]:
    """Every `AgentResult` actually on disk, as ``{window_tag: {agent_id: AgentResult}}``.

    Duplicated from `score.py`'s function of the same name (see the module docstring). Only files
    that exist are in the returned mapping -- a (window, agent) pair with no file simply has no
    entry, which is what lets `combine_window` tell "this card was cash here" from "this card lost
    money here". The filename's own agent-id segment is not trusted as the key; `card.agent_id` from
    the parsed file is, in case the two ever disagree.
    """
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


# ---------------------------------------------------------------------------
# Combining
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WindowMember:
    """One card's contribution to one window of the combined book."""

    agent_id: str
    present: bool
    """`False` when this card has no run file for this window -- it held cash on its ``1/n`` share,
    contributing `0.0` to both `corrected_return` and `capital_exposure` below rather than being
    dropped from the average. See the module docstring."""

    corrected_return: Decimal | None
    """This card's own `corrected_return` for the window, or `None` when `present` is `False`."""

    capital_exposure: Decimal | None
    """This card's own `capital_exposure` for the window, or `None` when `present` is `False`.
    Note this can also be `None` while `present` is `True`, for a card that ran the window but took
    no trades in it -- see `capital_exposure`'s own docstring."""


@dataclass(frozen=True, slots=True)
class PortfolioWindow:
    """The combined book's result in one window."""

    window_tag: str
    members: tuple[WindowMember, ...]

    benchmark_return: Decimal | None
    """The window's benchmark return, read off whichever present member(s) carry it. `None` if no
    member ran this window with a known benchmark."""

    combined_return: Decimal
    """The equal-weight mean of every member's `corrected_return`, absent members contributing
    ``0.0``. Always computable -- it needs no benchmark."""

    combined_capital_exposure: Decimal
    """The equal-weight mean of every member's `capital_exposure`, absent members and zero-trade
    members alike contributing ``0.0``. Always computable, for the same reason."""

    excess: Decimal | None
    """``combined_return - benchmark_return``. `None` when `benchmark_return` is `None`."""

    adjusted_excess: Decimal | None
    """``combined_return - (combined_capital_exposure * benchmark_return)`` -- computed from the
    *book's* combined exposure, not any one member's. `None` when `benchmark_return` is `None`."""

    benchmark_disagreement: tuple[Decimal, ...] = ()
    """Non-empty only if two present members' own `benchmark_return` values for this window
    disagree -- which should not happen (all cards trade the same window against the same
    benchmark) but is worth surfacing rather than silently picking one, if it ever does."""


def combine_window(
    window_tag: str,
    cards: Sequence[str],
    by_window: Mapping[str, Mapping[str, AgentResult]],
) -> PortfolioWindow:
    """Equal-weight combine ``cards`` for one window. An absent card holds cash -- see the module
    docstring's "Combining" section. ``cards`` must be non-empty."""
    if not cards:
        raise ValueError("combine_window requires at least one card")

    agents_here = by_window.get(window_tag, {})
    n = Decimal(len(cards))

    members: list[WindowMember] = []
    returns: list[Decimal] = []
    exposures: list[Decimal] = []
    benchmarks_seen: dict[Decimal, None] = {}  # ordered set

    for agent_id in cards:
        result = agents_here.get(agent_id)
        if result is None:
            members.append(
                WindowMember(
                    agent_id=agent_id, present=False, corrected_return=None, capital_exposure=None
                )
            )
            returns.append(Decimal(0))
            exposures.append(Decimal(0))
            continue

        cr = corrected_return(result)
        ce = capital_exposure(result)
        members.append(
            WindowMember(agent_id=agent_id, present=True, corrected_return=cr, capital_exposure=ce)
        )
        returns.append(cr)
        exposures.append(ce if ce is not None else Decimal(0))
        if result.benchmark_return is not None:
            benchmarks_seen[result.benchmark_return] = None

    combined_return = sum(returns, Decimal(0)) / n
    combined_capital_exposure = sum(exposures, Decimal(0)) / n

    benchmark = next(iter(benchmarks_seen), None)
    exc = combined_return - benchmark if benchmark is not None else None
    adj = (
        combined_return - (combined_capital_exposure * benchmark) if benchmark is not None else None
    )

    return PortfolioWindow(
        window_tag=window_tag,
        members=tuple(members),
        benchmark_return=benchmark,
        combined_return=combined_return,
        combined_capital_exposure=combined_capital_exposure,
        excess=exc,
        adjusted_excess=adj,
        benchmark_disagreement=tuple(benchmarks_seen) if len(benchmarks_seen) > 1 else (),
    )


@dataclass(frozen=True, slots=True)
class PortfolioScore:
    """The combined book's result across every window at least one member ran, plus the roll-up
    summary it is judged on."""

    agent_ids: tuple[str, ...]
    windows: tuple[PortfolioWindow, ...]
    n_windows: int

    median_excess: Decimal | None
    worst_excess: Decimal | None
    hit_rate_excess: float | None

    median_adjusted_excess: Decimal | None
    worst_adjusted_excess: Decimal | None
    hit_rate_adjusted_excess: float | None


def score_portfolio(
    by_window: Mapping[str, Mapping[str, AgentResult]],
    cards: Sequence[str],
    window_tags: Sequence[str],
) -> PortfolioScore:
    """Combine ``cards`` over every window in ``window_tags`` that at least one of them actually
    ran, then roll the per-window `excess`/`adjusted_excess` up into median, worst-window and hit
    rate for both metrics.

    A window where *none* of ``cards`` has a run file is dropped entirely rather than reported as an
    all-cash ``0.0`` row -- with no member present there is no benchmark figure to read either, so
    the row would carry no information beyond "the book was not eligible here", which the omission
    already says. A window where *some but not all* members are present is kept, with the absent
    ones' ``1/n`` share held as cash (see `combine_window`).
    """
    relevant_tags = [tag for tag in window_tags if any(a in by_window.get(tag, {}) for a in cards)]
    windows = [combine_window(tag, cards, by_window) for tag in relevant_tags]

    excess_values = [w.excess for w in windows if w.excess is not None]
    adjusted_values = [w.adjusted_excess for w in windows if w.adjusted_excess is not None]

    def _median(values: list[Decimal]) -> Decimal | None:
        return statistics.median(values) if values else None

    def _worst(values: list[Decimal]) -> Decimal | None:
        return min(values) if values else None

    def _hit_rate(values: list[Decimal]) -> float | None:
        return sum(1 for v in values if v > 0) / len(values) if values else None

    return PortfolioScore(
        agent_ids=tuple(cards),
        windows=tuple(windows),
        n_windows=len(windows),
        median_excess=_median(excess_values),
        worst_excess=_worst(excess_values),
        hit_rate_excess=_hit_rate(excess_values),
        median_adjusted_excess=_median(adjusted_values),
        worst_adjusted_excess=_worst(adjusted_values),
        hit_rate_adjusted_excess=_hit_rate(adjusted_values),
    )


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairCorrelation:
    """Pearson correlation of two members' per-window `corrected_return`, over the windows both
    actually ran -- see the module docstring's "correlation matrix" section for why `n` is reported
    beside `rho` rather than left implicit."""

    a: str
    b: str
    n: int
    rho: float | None
    """`None` when `n < 2` (no correlation is computable from fewer than two shared points) or when
    one member's shared-window returns are constant (zero variance, making Pearson's rho undefined)."""


def correlation_matrix(
    by_window: Mapping[str, Mapping[str, AgentResult]],
    cards: Sequence[str],
    window_tags: Sequence[str],
    *,
    annualized: bool = False,
) -> list[PairCorrelation]:
    """Every pairwise correlation among ``cards``, each computed only over the windows where both
    members of that specific pair have a run file -- never imputing a value for a window one of them
    could not trade. See the module docstring.

    ``annualized=True`` correlates compound annual rates instead of raw window returns. **Use it
    whenever the window set mixes lengths**, which from round 5 onwards it does: the horizon ladder
    runs from 125 to 2517 sessions, so a raw-return series has one point that is a decade's growth
    and another that is half a year's. The resulting correlation is then driven mostly by which
    windows happened to be long, which is a fact about the matrix and not about either card.

    It is off by default because annualizing is not a monotone transform across windows of differing
    length, so turning it on moves the figures rounds 1-4 published and argued from -- including
    `ROUND-4-PLAN.md` section 1's table, which `tests/test_portfolio_tool.py` reproduces against the
    committed round-3 tree. Those rounds' windows were all within a factor of six of each other,
    where the distinction barely bites; round 5's span a factor of twenty, where it dominates.

    A card whose annualized return is undefined in a window (a total loss, or a zero-session window
    -- see `_annualize`) is dropped from that window for this pair, exactly as a missing run file is,
    rather than being imputed."""
    pairs: list[PairCorrelation] = []
    for a, b in itertools.combinations(cards, 2):
        xs: list[float] = []
        ys: list[float] = []
        for tag in window_tags:
            agents = by_window.get(tag, {})
            ra = agents.get(a)
            rb = agents.get(b)
            if ra is None or rb is None:
                continue
            if annualized:
                va, vb = annualized_return(ra), annualized_return(rb)
                if va is None or vb is None:
                    continue
                xs.append(float(va))
                ys.append(float(vb))
            else:
                xs.append(float(corrected_return(ra)))
                ys.append(float(corrected_return(rb)))
        n = len(xs)
        rho: float | None
        if n < 2:
            rho = None
        else:
            try:
                rho = statistics.correlation(xs, ys)
            except statistics.StatisticsError:
                # Zero variance in one leg (every shared-window return identical) -- Pearson's rho
                # is undefined, not zero; reported as unknown rather than as "uncorrelated".
                rho = None
        pairs.append(PairCorrelation(a=a, b=b, n=n, rho=rho))
    return pairs


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _pct(value: Decimal | float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:+.2f}%"


def render_markdown(score: PortfolioScore, pairs: list[PairCorrelation]) -> str:
    """The stdout report: one row per window (each member's return, the benchmark, the combined
    return, excess and adjusted excess), the summary line, and the correlation matrix."""
    lines: list[str] = []
    cards = score.agent_ids

    lines.append(f"## Combined book: {', '.join(cards)} (equal weight, 1/{len(cards)} each)")
    lines.append("")

    headers = ["window", *cards, "benchmark", "combined", "excess", "adj_excess"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    for w in score.windows:
        member_cells = [
            _pct(m.corrected_return) if m.present else "cash" for m in w.members
        ]
        row = [
            w.window_tag,
            *member_cells,
            _pct(w.benchmark_return),
            _pct(w.combined_return),
            _pct(w.excess),
            _pct(w.adjusted_excess),
        ]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append(f"## Summary ({score.n_windows} window(s))")
    lines.append("")
    lines.append(
        f"- excess: median {_pct(score.median_excess)}, worst {_pct(score.worst_excess)}, "
        f"hit rate {'n/a' if score.hit_rate_excess is None else f'{score.hit_rate_excess * 100:.0f}%'}"
    )
    lines.append(
        f"- adjusted_excess: median {_pct(score.median_adjusted_excess)}, "
        f"worst {_pct(score.worst_adjusted_excess)}, "
        f"hit rate {'n/a' if score.hit_rate_adjusted_excess is None else f'{score.hit_rate_adjusted_excess * 100:.0f}%'}"
    )
    lines.append("")

    lines.append("## Pairwise correlation of per-window returns (shared windows only)")
    lines.append("")
    lines.append(
        "Small samples -- read `n` beside every `rho` before trusting it; see the module docstring."
    )
    lines.append("")
    lines.append("| a | b | n | rho |")
    lines.append("|---|---|---|---|")
    for p in pairs:
        rho_text = "n/a" if p.rho is None else f"{p.rho:+.3f}"
        lines.append(f"| {p.a} | {p.b} | {p.n} | {rho_text} |")

    return "\n".join(lines) + "\n"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, WindowMember):
        return {
            "agent_id": value.agent_id,
            "present": value.present,
            "corrected_return": _jsonable(value.corrected_return),
            "capital_exposure": _jsonable(value.capital_exposure),
        }
    if isinstance(value, PortfolioWindow):
        return {
            "window_tag": value.window_tag,
            "members": [_jsonable(m) for m in value.members],
            "benchmark_return": _jsonable(value.benchmark_return),
            "combined_return": _jsonable(value.combined_return),
            "combined_capital_exposure": _jsonable(value.combined_capital_exposure),
            "excess": _jsonable(value.excess),
            "adjusted_excess": _jsonable(value.adjusted_excess),
            "benchmark_disagreement": [_jsonable(v) for v in value.benchmark_disagreement],
        }
    if isinstance(value, PairCorrelation):
        return {"a": value.a, "b": value.b, "n": value.n, "rho": value.rho}
    return value


def _build_json(score: PortfolioScore, pairs: list[PairCorrelation]) -> dict[str, Any]:
    return {
        "agent_ids": list(score.agent_ids),
        "n_windows": score.n_windows,
        "windows": [_jsonable(w) for w in score.windows],
        "median_excess": _jsonable(score.median_excess),
        "worst_excess": _jsonable(score.worst_excess),
        "hit_rate_excess": score.hit_rate_excess,
        "median_adjusted_excess": _jsonable(score.median_adjusted_excess),
        "worst_adjusted_excess": _jsonable(score.worst_adjusted_excess),
        "hit_rate_adjusted_excess": score.hit_rate_adjusted_excess,
        "correlation": [_jsonable(p) for p in pairs],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--results",
        dest="results_root",
        type=Path,
        required=True,
        help="directory containing <window-tag>/runs/<round>-<agent_id>.json",
    )
    parser.add_argument(
        "--cards",
        dest="cards",
        action="append",
        required=True,
        help="agent_id of a card to include in the book, at equal weight. Repeat for each member, "
        "e.g. --cards B-momentum --cards C-trend --cards c14-riskmanaged-wide",
    )
    parser.add_argument(
        "--round",
        dest="round_tag",
        default=None,
        help="round prefix on each run filename, e.g. 'r1' for 'r1-<agent_id>.json'. Optional -- "
        "auto-detected from the run filenames on disk when omitted, and reported as an error rather "
        "than guessed if that is ambiguous or nothing has been written yet.",
    )
    parser.add_argument(
        "--windows",
        default=None,
        help="comma-separated window tags to restrict the book and the correlation matrix to. "
        "Required in practice for round 5: a book scored across the whole horizon ladder averages "
        "a decade's return with a half-year's, which is arithmetic on two different units. Score "
        "one horizon at a time, or one arm at a time, and compare the results rather than pooling "
        "the windows.",
    )
    parser.add_argument(
        "--annualized",
        action="store_true",
        help="correlate compound annual rates rather than raw window returns. Use whenever the "
        "window set mixes lengths -- see correlation_matrix's docstring. Off by default so rounds "
        "1-4's published figures keep reproducing exactly.",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="optional path to write the machine-readable result",
    )
    args = parser.parse_args(argv)

    cards: list[str] = []
    for agent_id in args.cards:
        if agent_id not in cards:
            cards.append(agent_id)
        else:
            print(f"WARNING: --cards '{agent_id}' repeated; using it once")

    window_tags = _discover_window_tags(args.results_root)
    if args.windows is not None:
        requested = [tag.strip() for tag in args.windows.split(",") if tag.strip()]
        missing = [tag for tag in requested if tag not in window_tags]
        if missing:
            print(
                f"--windows names {', '.join(missing)}, which has no runs/ directory under "
                f"{args.results_root}; found {', '.join(window_tags)}"
            )
            return 1
        window_tags = requested
    if not window_tags:
        print(f"no window directories with a runs/ folder found under {args.results_root}")
        return 1

    round_tag = args.round_tag
    if round_tag is None:
        round_tag = _discover_round_tag(args.results_root, window_tags)
        if round_tag is None:
            print(
                f"could not auto-detect a single round tag from run filenames under "
                f"{args.results_root} (found none, or more than one prefix) -- pass --round explicitly"
            )
            return 1

    by_window = load_results(args.results_root, round_tag, window_tags)

    score = score_portfolio(by_window, cards, window_tags)
    if score.n_windows == 0:
        print(f"none of {', '.join(cards)} has a run file in any window under {args.results_root}")
        return 1
    pairs = correlation_matrix(by_window, cards, window_tags, annualized=args.annualized)

    print(render_markdown(score, pairs))

    if args.json is not None:
        report = _build_json(score, pairs)
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"wrote {args.json}")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
