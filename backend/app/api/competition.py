"""Strategy-competition endpoints: the card library, the round list, a round's leaderboard against
SPY, and the per-trade drill-down behind one agent's number in one round.

Thin on purpose, same as `app.api.macro`: every real computation -- `total_return` recomputed from
equity, `excess`/`adjusted_excess`, the eligibility gate, the per-trade attribution -- lives in
`app.tournament.results`, which is the online counterpart to the offline
`strategy-program/tools/score.py` and `strategy-program/tools/attribution.py` (see that module's
docstring for the exact correspondence and the one place this API's contract deliberately diverges
from `score.py`'s own ranking key).

**Money crosses the wire as a string, never a JSON number.** `frontend/src/api/client.ts` documents
this convention (`export type DecimalString = string`), the same one `app.api.market`/`app.api.macro`
already follow for prices. Every `Decimal`-typed field below is serialised via :func:`_money`.
`capital_exposure`, `hit_rate`, `win_rate`, `sharpe`-style figures stay plain floats -- they are
observations, not currency, and rounding them in transit costs nothing a reader would notice.

**404, never a 500, for an unknown identifier.** An unknown `round_id` or `agent_id` is this router's
only genuine error condition -- `app.tournament.results.RoundNotFoundError` /
`AgentNotFoundError` map to it below, the same "typo or stale build reads as not found, not crash"
contract `app.api.macro`'s module docstring describes for its own 404. An unrecognised `rank_by` is
different in kind: it is a malformed request, not a missing resource, so it is a 422
(`ValueError` from `app.tournament.results.build_leaderboard`), matching how `/api/macro/fear-greed`
turns its own request-shaped rejection into a 422 rather than a 404 or a 200.

**`/windows` sources its catalogue from `app.tournament.jobs`, not from this module's own copy of
anything.** `app.tournament.results` already duplicates the window matrix's *tags* (`MAIN_WINDOWS`,
`PROVENANCE_WINDOW`) for the leaderboard's aggregation rules, but the dates and one-line regime
labels a run-form needs live only in `app.tournament.jobs.WINDOWS` -- the constant
`POST /api/competition/jobs` (the round runner, a different router in this program) actually
validates a launch request's `windows` field against. Importing it here, rather than adding a third
copy of the same table, is the point: the set this endpoint offers is *by construction* the exact
set a launch request will accept, so the two can never drift apart the way `strategy-program/
tools/windows.py`'s table and `score.py`'s duplicate of it are only kept in step by inspection.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from app.tournament import jobs, results
from app.tournament.models import StrategyCard
from app.tournament.purposes import PURPOSE_SPECS

router = APIRouter(prefix="/api/competition", tags=["competition"])

#: Same constraint `app.api.competition_selection.RoundIdPath` applies (and `app.tournament.jobs`
#: enforces on the write side), copied verbatim for the same reason that module gives. Until the
#: 2026-09-07 security audit the two read routes below took a bare `str`, and `round_id` is joined
#: straight onto the rounds root in `app.tournament.results` (`root / round_id / "results"`) -- so a
#: `..`-bearing segment could point them at a directory outside `data/rounds/`.
RoundIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")]


def _money(value: Decimal | None) -> str | None:
    """`Decimal` -> its exact string representation, never a `float` round-trip. `None` passes
    through unchanged -- an unknown figure (e.g. `excess` with no benchmark) is `null` on the wire,
    not the string `"None"` or a fabricated `"0"`."""
    return None if value is None else str(value)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CardSummary(BaseModel):
    """One `StrategyCard`, as the library and agent-detail endpoints both render it.

    Every `Decimal` field (`stop_loss_pct`, `take_profit_pct`, `position_pct`) is a string on the
    wire -- see the module docstring. `universe` and `entry`/`exit` are exposed verbatim; the DSL
    text is meant to be read by a person looking at the card, not re-parsed by the frontend.
    """

    agent_id: str
    display_name: str
    discipline: str
    universe: list[str]
    entry: str
    exit: str
    stop_loss_pct: str | None
    take_profit_pct: str | None
    max_hold_days: int | None
    max_positions: int
    position_pct: str
    designed_through: str
    thesis: str


def _card_summary(card: StrategyCard) -> CardSummary:
    return CardSummary(
        agent_id=card.agent_id,
        display_name=card.display_name,
        discipline=str(card.discipline),
        universe=list(card.universe),
        entry=card.entry,
        exit=card.exit,
        stop_loss_pct=_money(card.stop_loss_pct),
        take_profit_pct=_money(card.take_profit_pct),
        max_hold_days=card.max_hold_days,
        max_positions=card.max_positions,
        position_pct=_money(card.position_pct) or "0",
        designed_through=card.designed_through.isoformat(),
        thesis=card.thesis,
    )


class LibraryTier(BaseModel):
    tier: str
    label: str
    cards: list[CardSummary]


class LibraryResponse(BaseModel):
    """`/api/competition/library`'s body: all four tiers, always in this order, even when a tier
    (e.g. `variants`) holds no cards."""

    tiers: list[LibraryTier]


class RoundSummary(BaseModel):
    """One row of `/api/competition/rounds`, newest-first by `sequence` descending (see
    `app.tournament.results.round_sequence` -- sorting the round *id* as a plain string is a known
    defect, since `"r9-2026-08" > "r13-2026-08"` lexicographically).

    `has_results=False` means `/rounds/{round_id}/leaderboard` will 404 for this round by design:
    `app.tournament.results.load_round_results` raises `RoundNotFoundError` whenever the round has no
    `results/` directory, or one with no windows in it, and this field exists so a caller (the
    frontend seeds its selected round from the first entry in this list) can avoid defaulting a
    picker onto a round that cannot render, rather than opening straight onto a 404.

    `has_selection` is true only once the round's live out-of-sample matrix has started
    (`results/live-1` exists) -- see `app.api.competition_selection`'s `_LIVE_MATRIX_MARKER`, which
    this mirrors independently rather than importing (that name is private to its module).
    """

    round_id: str
    label: str
    windows: list[str]
    agents: int
    has_report: bool
    has_brief: bool
    has_results: bool
    has_selection: bool
    sequence: int


class RoundsResponse(BaseModel):
    rounds: list[RoundSummary]


class WindowCatalogEntry(BaseModel):
    """One entry in the run-form's window checklist -- everything a caller needs to offer a regime
    without having to already know its dates or which round-runner windows dict it came from.

    `main=False` marks `"13f-legal"` only, and is computed from
    `jobs.PROVENANCE_CONSTRAINED_WINDOWS` rather than from membership of any round's matrix. Those
    are different properties and they were briefly conflated: `main` was derived as "in
    `jobs.MAIN_WINDOWS`", which was true while `MAIN_WINDOWS` happened to be every window but one,
    and became wrong the moment round 4 added six regimes that belong to a *different* matrix. The
    run form then dimmed all six and captioned them as not-comparable, which is false -- they are
    ordinary regime windows, they simply are not round 2's.

    `matrix` says which round's set a window belongs to, for a caller that wants to group them.

    That window exists solely for cards whose universe was
    assembled from a 13F filing -- see `app.tournament.jobs.WINDOWS`'s and
    `strategy-program/tools/windows.py`'s module docstrings -- and it is excluded from the round
    runner's eligibility gate (`MIN_ELIGIBLE_MAIN_WINDOWS` counts only `main=True` windows) for the
    same reason `/rounds/{round_id}/leaderboard` marks its own `"13f-legal"` cell
    `provenance_constrained`: a basket only knowable from a filing that postdates most of these
    regimes cannot be legally traded through them, so a result there is not comparable with the
    other eight and should be offered to a user picking regimes with that caveat visible, not
    silently mixed in as a ninth ordinary choice.

    Round 5 added two more matrices, both `main=True` -- `jobs.R5_LADDER_WINDOWS`'s 21 windows and
    `jobs.R5_BEAR_WINDOWS`'s 6 -- because both are ordinary, comparable windows in exactly the sense
    `oil-2014` or `banks-2023` are: nothing about a card's universe or provenance makes them
    ineligible for it. What is different about round 5 is that its windows are not named regimes at
    all, they are a *horizon ladder* (see `jobs.WINDOWS`'s round-5 comment) -- `horizon` below is
    where that distinction actually lives, not `matrix`.
    """

    window: str
    start: str
    end: str
    label: str
    main: bool
    matrix: str
    """Which matrix this window belongs to: `"r2"` (rounds 2-3), `"r4"`, `"r5-ladder"`, `"r5-bear"`,
    or `"special"`."""
    horizon: str | None
    """The window's *designed* run length -- `"6m"`, `"1y"`, `"3y"`, `"5y"` or `"10y"` -- from
    `jobs.R5_HORIZON.get(tag)`. `None` for every window outside round 5's matrix, deliberately: a
    named regime window like `covid` or `oil-2014` has a length (its `start`/`end` already say so),
    but that length was not the point of choosing it the way it is the entire point of `h10y-1` --
    round 5 is the only round whose window set was constructed *as* a ladder of horizons, so it is
    the only one `horizon` describes anything meaningful about. A regime window's incidental length
    is still readable from `start`/`end` by anyone who wants it; `horizon` is reserved for "this
    window's length was the variable under test," which is a different, narrower claim."""


class WindowsResponse(BaseModel):
    """`/api/competition/windows`'s body: every window the round runner
    (`POST /api/competition/jobs`) will accept, main windows first (chronological by `start`), then
    the non-main (`"13f-legal"`) window(s) -- see `WindowCatalogEntry` for what `main` means.
    """

    windows: list[WindowCatalogEntry]


class WindowInfo(BaseModel):
    """What every card in a window shares: the session count and SPY's buy-and-hold return over it.

    `provenance_constrained=True` marks `"13f-legal"` -- see `app.tournament.results`'s module
    docstring: that window's universe was only knowable from a filing that postdates it, so its
    numbers are real but not comparable to the other eight and are excluded from every ranking
    aggregate.
    """

    window: str
    sessions: int
    benchmark_return: str
    provenance_constrained: bool


class LeaderboardWindowCell(BaseModel):
    """One agent's result in one window, as a leaderboard cell -- a slimmer view than the
    agent-detail endpoint's `AgentWindowDetail` (no per-trade breakdown; see
    `/rounds/{round_id}/agents/{agent_id}` for that)."""

    total_return: str
    benchmark_return: str | None
    excess: str | None
    adjusted_excess: str | None
    capital_exposure: float | None
    capital_exposure_reconstructed: bool
    max_drawdown: str
    trades: int
    sessions: int


class LeaderboardRow(BaseModel):
    """One card's aggregate across the round's non-`"13f-legal"` windows, plus every window's cell
    (including `"13f-legal"`'s, for display) -- see `app.tournament.results.build_leaderboard`'s
    docstring for exactly which fields exclude that window and why."""

    rank: int
    agent_id: str
    display_name: str
    discipline: str
    windows_run: int
    eligible: bool
    median_excess: str | None
    worst_excess: str | None
    hit_rate: float | None
    mean_capital_exposure: float | None
    total_trades: int
    per_window: dict[str, LeaderboardWindowCell]


class PurposeInfo(BaseModel):
    """One purpose, as the competition sees it: how it is funded and what ranks it.

    Served so a client does not hardcode the three purposes, their funding or -- most importantly --
    which quantity each is ranked on. See `app.tournament.purposes.PurposeSpec`, which is the source
    every field here is read from rather than restated.
    """

    purpose: str
    funding_shape: str
    seed: str
    contribution: str
    horizon_years_min: int | None
    horizon_years_max: int | None
    """`None` for `trading`, and that is a decision rather than a missing value: a purpose whose
    horizon is unstated is not the same as one whose horizon is short. Render "unbounded"."""
    tax_treatment: str
    symbols_must_be_disjoint: bool
    benchmark: str
    scoring_basis: str


class PurposesResponse(BaseModel):
    purposes: list[PurposeInfo]


class LeaderboardResponse(BaseModel):
    round_id: str
    rank_by: str
    purpose: str
    scoring_basis: str
    """The quantity `rows` is ranked on. Travels with the rows because it differs by purpose, and a
    column heading that silently changes meaning is how an IRR ends up compared to an excess."""
    unscored_reason: str | None = None
    """Why `rows` is empty, when it is. `None` whenever there are rows."""
    windows: list[WindowInfo]
    rows: list[LeaderboardRow]


class TradeOut(BaseModel):
    """One realised trade, with its exact share of the card's return in this window.

    `contribution = pnl / starting_equity`, and every trade's `contribution` in a window sums to
    that window's `total_return` exactly -- see `app.tournament.results`'s module docstring and
    `strategy-program/tools/attribution.py`, which this reproduces.
    """

    symbol: str
    entry_date: str
    exit_date: str | None
    entry_price: str
    exit_price: str | None
    quantity: str
    bars_held: int
    exit_reason: str
    return_pct: str
    pnl: str
    contribution: str
    unrealised: bool


def _trade_out(contribution: results.TradeContribution) -> TradeOut:
    trade = contribution.trade
    return TradeOut(
        symbol=trade.symbol,
        entry_date=trade.entry_date.isoformat(),
        exit_date=trade.exit_date.isoformat() if trade.exit_date else None,
        entry_price=_money(trade.entry_price) or "0",
        exit_price=_money(trade.exit_price),
        quantity=_money(trade.quantity) or "0",
        bars_held=trade.bars_held,
        exit_reason=trade.exit_reason,
        return_pct=_money(trade.return_pct) or "0",
        pnl=_money(trade.pnl) or "0",
        contribution=_money(contribution.contribution) or "0",
        unrealised=contribution.unrealised,
    )


class AgentWindowDetail(BaseModel):
    window: str
    sessions: int
    starting_equity: str
    ending_equity: str
    total_return: str
    benchmark_return: str | None
    excess: str | None
    adjusted_excess: str | None
    capital_exposure: float | None
    max_drawdown: str
    win_rate: float | None
    profit_factor: str | None
    unrealised_share: str
    top3_share_of_gross_wins: float | None
    return_without_top3_winners: str
    rejections: list[str]
    trades: list[TradeOut]


class AgentDetailResponse(BaseModel):
    round_id: str
    agent_id: str
    display_name: str
    card: CardSummary
    windows: list[AgentWindowDetail]


# ---------------------------------------------------------------------------
# Converters -- `app.tournament.results` dataclasses -> the response models above
# ---------------------------------------------------------------------------


def _window_info(facts: results.WindowFacts) -> WindowInfo:
    return WindowInfo(
        window=facts.window,
        sessions=facts.sessions,
        benchmark_return=_money(facts.benchmark_return) or "0",
        provenance_constrained=facts.provenance_constrained,
    )


def _leaderboard_cell(metrics: results.LeaderboardCellData) -> LeaderboardWindowCell:
    return LeaderboardWindowCell(
        total_return=_money(metrics.total_return) or "0",
        benchmark_return=_money(metrics.benchmark_return),
        excess=_money(metrics.excess),
        adjusted_excess=_money(metrics.adjusted_excess),
        capital_exposure=metrics.capital_exposure,
        capital_exposure_reconstructed=metrics.capital_exposure_reconstructed,
        max_drawdown=_money(metrics.max_drawdown) or "0",
        trades=metrics.trades,
        sessions=metrics.sessions,
    )


def _leaderboard_row(row: results.LeaderboardRowData) -> LeaderboardRow:
    return LeaderboardRow(
        rank=row.rank,
        agent_id=row.agent_id,
        display_name=row.display_name,
        discipline=row.discipline,
        windows_run=row.windows_run,
        eligible=row.eligible,
        median_excess=_money(row.median_excess),
        worst_excess=_money(row.worst_excess),
        hit_rate=row.hit_rate,
        mean_capital_exposure=row.mean_capital_exposure,
        total_trades=row.total_trades,
        per_window={tag: _leaderboard_cell(cell) for tag, cell in row.per_window.items()},
    )


def _agent_window_detail(metrics: results.WindowMetrics) -> AgentWindowDetail:
    return AgentWindowDetail(
        window=metrics.window,
        sessions=metrics.sessions,
        starting_equity=_money(metrics.starting_equity) or "0",
        ending_equity=_money(metrics.ending_equity) or "0",
        total_return=_money(metrics.total_return) or "0",
        benchmark_return=_money(metrics.benchmark_return),
        excess=_money(metrics.excess),
        adjusted_excess=_money(metrics.adjusted_excess),
        capital_exposure=metrics.capital_exposure,
        max_drawdown=_money(metrics.max_drawdown) or "0",
        win_rate=metrics.win_rate,
        profit_factor=_money(metrics.profit_factor),
        unrealised_share=_money(metrics.unrealised_share) or "0",
        top3_share_of_gross_wins=metrics.top3_share_of_gross_wins,
        return_without_top3_winners=_money(metrics.return_without_top3_winners) or "0",
        rejections=list(metrics.rejections),
        trades=[_trade_out(c) for c in metrics.contributions],
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/library", response_model=LibraryResponse)
def library() -> LibraryResponse:
    """Every `StrategyCard` on disk, grouped into the four tiers `strategy-program/library/` holds
    (`base`, `variants`, `candidates`, `retired`).

    Always returns all four tiers, in that fixed order, even when one is empty -- `variants` has
    never held a card in this program's history, and the frontend renders four columns regardless.
    Globbed fresh on every request rather than cached: the library is edited concurrently by other
    work in this program (cards move between tiers, new ones are added), so a stale in-memory list
    would silently drift from what is actually on disk. A `provenance.json` sidecar, when present in
    a tier directory, is never treated as a card -- see `app.tournament.results.load_library`.
    """
    by_tier = results.load_library()
    return LibraryResponse(
        tiers=[
            LibraryTier(
                tier=tier,
                label=label,
                cards=[_card_summary(card) for card in by_tier.get(tier, [])],
            )
            for tier, label in results.TIERS
        ]
    )


@router.get("/rounds", response_model=RoundsResponse)
def rounds() -> RoundsResponse:
    """Every completed competition round, newest-first by round *number* (see
    `app.tournament.results.round_sequence`), with its window set and agent count.

    `agents` counts distinct `agent_id` values across every run file the round holds, in any window
    -- a card that only cleared eligibility for one window still counts once, not zero.

    Unlike `/library` directly above, this route does not re-read every file on every request: the
    per-run-file parse behind `agents` is memoised on each file's own `(mtime_ns, size)` in
    `app.tournament.results._AGENT_ID_CACHE`. The response is nonetheless the same response a full
    re-read would produce -- a run file added, changed or removed since the last request is picked up
    on this one -- which matters because `app.tournament.jobs` is writing run files into the round
    being listed while this route is polled. See that cache's own comment for the argument and
    `tests/test_competition_round_listing_cache.py` for the tests that hold it to it. Everything else
    on the row (windows, label, `has_report`/`has_brief`/`has_results`/`has_selection`) is still
    stat-ed fresh per request.
    """
    return RoundsResponse(
        rounds=[
            RoundSummary(
                round_id=r.round_id,
                label=r.label,
                windows=list(r.windows),
                agents=r.agents,
                has_report=r.has_report,
                has_brief=r.has_brief,
                has_results=r.has_results,
                has_selection=r.has_selection,
                sequence=r.sequence,
            )
            for r in results.list_rounds()
        ]
    )


@router.get("/windows", response_model=WindowsResponse)
def windows() -> WindowsResponse:
    """The full window catalogue a round-launch form should offer -- exactly the set
    `POST /api/competition/jobs` will accept, since both read `app.tournament.jobs.WINDOWS` /
    `MAIN_WINDOWS` rather than either one keeping its own copy.

    Ordered main windows first (the eight regimes the eligibility gate counts), then the non-main
    windows (`"13f-legal"`); within each group, chronologically by `start` -- a person picking
    regimes for a launch reads a timeline more easily than an alphabetised list. Never empty and
    never round-dependent: unlike `/rounds`, which can return `[]` on a fresh install with no
    completed rounds yet, this endpoint answers from the round runner's own static window matrix, so
    a run form has something to offer before a single round has ever been launched.
    """
    def _matrix(tag: str) -> str:
        if tag in jobs.PROVENANCE_CONSTRAINED_WINDOWS:
            return "special"
        if tag in jobs.R5_LADDER_WINDOWS:
            return "r5-ladder"
        if tag in jobs.R5_BEAR_WINDOWS:
            return "r5-bear"
        if tag in jobs.R4_MAIN_WINDOWS:
            return "r4"
        return "r2"

    # A plain lexical sort on the matrix string would put `"r5-bear"` before `"r5-ladder"` (string
    # comparison, not round-construction order), which is exactly backwards -- the ladder is round
    # 5's primary matrix and the bear arm supplements it, so a reader should see the ladder's 21
    # windows before the bear arm's 6. This explicit map is what fixes that; it also keeps the
    # ordering stable against a future matrix name that happens to sort earlier or later than these
    # five by accident of spelling.
    _MATRIX_ORDER = {"r2": 0, "r4": 1, "r5-ladder": 2, "r5-bear": 3, "special": 4}

    def _sort_key(item: tuple[str, tuple[dt.date, dt.date, str]]) -> tuple[bool, int, dt.date]:
        tag, (start, _end, _label) = item
        # Comparable regimes first, then the provenance-constrained one; within that, grouped by
        # matrix (via `_MATRIX_ORDER`, not the matrix string itself) and ordered chronologically, so
        # a person picking regimes reads a coherent list.
        return (tag in jobs.PROVENANCE_CONSTRAINED_WINDOWS, _MATRIX_ORDER[_matrix(tag)], start)

    ordered = sorted(jobs.WINDOWS.items(), key=_sort_key)
    return WindowsResponse(
        windows=[
            WindowCatalogEntry(
                window=tag,
                start=start.isoformat(),
                end=end.isoformat(),
                label=label,
                main=tag not in jobs.PROVENANCE_CONSTRAINED_WINDOWS,
                matrix=_matrix(tag),
                horizon=jobs.R5_HORIZON.get(tag),
            )
            for tag, (start, end, label) in ordered
        ]
    )


@router.get("/purposes", response_model=PurposesResponse)
def purposes() -> PurposesResponse:
    """The three purposes, their funding, and the basis each is ranked on.

    A catalogue read, like `/windows`: served so a client renders three books from data rather than
    from three hardcoded assumptions about what they are and how they are scored. Every field is read
    from `app.tournament.purposes.PURPOSE_SPECS`, never restated here, so this endpoint cannot drift
    out of agreement with the scorer or the paper desk about what a purpose is funded with.
    """
    return PurposesResponse(
        purposes=[
            PurposeInfo(
                purpose=purpose.value,
                funding_shape=spec.funding_shape.value,
                # `str(...)`, not `_money(...)`: both fields are `app.core.models.Money`, a
                # non-optional `Decimal`, while `_money` returns `str | None` for the fields
                # that genuinely can be absent. Same output, and `PurposeInfo` requires `str`.
                seed=str(spec.seed),
                contribution=str(spec.contribution),
                horizon_years_min=spec.horizon_years_min,
                horizon_years_max=spec.horizon_years_max,
                tax_treatment=spec.tax_treatment.value,
                symbols_must_be_disjoint=spec.symbols_must_be_disjoint,
                benchmark=spec.benchmark,
                scoring_basis=results.SCORING_BASIS[purpose.value],
            )
            for purpose, spec in PURPOSE_SPECS.items()
        ]
    )


@router.get("/rounds/{round_id}/leaderboard", response_model=LeaderboardResponse)
def leaderboard(
    round_id: RoundIdPath,
    rank_by: Annotated[
        str, Query(description="One of: " + ", ".join(results.RANK_BY_CHOICES))
    ] = "median",
    purpose: Annotated[
        str, Query(description="One of: " + ", ".join(sorted(results.SCORING_BASIS)))
    ] = "trading",
) -> LeaderboardResponse:
    """The round's cards for one purpose, ranked against that purpose's benchmark.

    `purpose` defaults to `trading`, which is what every card in every committed round actually is,
    so the default response is byte-identical to what this endpoint returned before purposes existed.

    **The filter is applied before ranking, not after.** A rank is a position within a field; ranking
    the whole field and then hiding rows would leave the survivors holding ranks that count
    competitors the caller cannot see.

    **`scoring_basis` is on the response because the three purposes are not ranked on the same
    quantity.** `trading` is scored on lump-sum `adjusted_excess` over regime windows; the two
    contribution-funded purposes are scored on money-weighted IRR *and* time-weighted CAGR.
    `data/rounds/r12-2026-08/ROTH-CANDIDATES.md` is explicit that ranking an IRR against an
    `adjusted_excess` is a category error rather than a rounding one, so the basis travels with the
    rows rather than being assumed by whatever renders them.

    An empty board for a non-trading purpose carries `unscored_reason` naming the cause: no round has
    run those cards. That is an absence of measurement, not a poor result, and the two must not
    render the same way.

    `rank_by` selects which criterion orders the table -- `median` (default), `worst`, `hit-rate` or
    `excess-per-exposure` (see `app.tournament.results.RANK_BY_CHOICES`); an unrecognised value is a
    422, not a silent fallback to the default, since a caller who mistyped it should see that rather
    than an unexplained ranking.

    Every row's aggregate figures (`median_excess`, `worst_excess`, `hit_rate`,
    `mean_capital_exposure`, `total_trades`) are computed over the round's eight main windows only --
    `"13f-legal"` is excluded from all of them, per `app.tournament.results.PROVENANCE_WINDOW`'s
    docstring, because that window's universe was only knowable from a filing postdating it and is
    not comparable to the rest. Its `per_window` cell is still present for every card that ran it,
    so a caller can render it (greyed) rather than lose it.

    A card that ran fewer than 5 of the 8 main windows is `eligible=False` and sorts after every
    eligible row, `rank` continuing the same sequence rather than restarting -- it is still reported
    with its real numbers, never hidden.
    """
    try:
        data = results.build_leaderboard(round_id, rank_by=rank_by, purpose=purpose)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except results.RoundNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return LeaderboardResponse(
        round_id=data.round_id,
        rank_by=data.rank_by,
        purpose=data.purpose,
        scoring_basis=data.scoring_basis,
        unscored_reason=data.unscored_reason,
        windows=[_window_info(w) for w in data.windows],
        rows=[_leaderboard_row(r) for r in data.rows],
    )


@router.get("/rounds/{round_id}/agents/{agent_id}", response_model=AgentDetailResponse)
def agent_detail(round_id: RoundIdPath, agent_id: str) -> AgentDetailResponse:
    """One agent's full result in one round: its card as it actually ran, and every window it ran
    in, each with the trades that produced that window's number.

    `card` is the run file's own embedded `StrategyCard`, not the library's current copy of it -- a
    round's report must reflect the card as it actually traded, even after the library entry for the
    same `agent_id` has since been edited. Every window's `trades` are sorted by
    `abs(contribution)` descending, and every trade's `contribution` for a window sums to that
    window's `total_return` exactly (`app.tournament.results`'s module docstring).

    404 when `round_id` does not exist, or when `agent_id` has no run file in any window of it.

    422 when the agent ran but its card is an allocation or ladder shape this view cannot render.
    Deliberately not a 404: "did not run" and "ran, and I cannot show it to you" are different facts,
    and round 15 exists precisely to have measured those shapes for the first time -- reporting it as
    absent would deny the measurement happened. Before this was handled, it was not even a 404: one
    ladder run file raised out of the loader and the endpoint returned a bare `500` for *every* card
    in the round, including the two that read perfectly well.
    """
    try:
        data = results.build_agent_detail(round_id, agent_id)
    except results.RoundNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except results.AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except results.AgentShapeUnsupportedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return AgentDetailResponse(
        round_id=data.round_id,
        agent_id=data.agent_id,
        display_name=data.display_name,
        card=_card_summary(data.card),
        windows=[_agent_window_detail(w) for w in data.windows],
    )
