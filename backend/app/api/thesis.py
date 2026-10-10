"""Thesis-loop endpoints: propose, test, and report -- never hide the denominator.

Thin over :mod:`app.thesis.loop`, :mod:`app.thesis.ledger`, :mod:`app.thesis.holdout` and
:mod:`app.thesis.author`, in the same shape :mod:`app.api.backtest` and :mod:`app.api.report` are
thin over their service layers. :mod:`app.thesis`'s docstring names the hazard -- a generator that
tries theses until one looks good is a p-hacking machine by default -- and the four guards that stop
it. This router adds nothing to those guards; it exists to expose them without weakening them.

**Collaborators are Protocol-typed with lazy ``_default_*()`` imports**, exactly as
:mod:`app.backtest.service` composes :class:`~app.backtest.service.Events`,
:class:`~app.backtest.service.Guards` and the rest. Two reasons, both sharper here than there. First,
this module must not import :mod:`app.thesis.strategycard` or :mod:`app.thesis.debate` -- they are
being written concurrently and may not exist yet, and a hard import at module load time would make
this router fail to mount before either lands. Second, and more importantly: the object under test at
this boundary is the *translation* from a :class:`~app.thesis.models.LoopResult` to an HTTP response,
not the loop's internal arithmetic. A fake :class:`LoopRunner` lets a test hand back a
:class:`~app.thesis.models.LoopResult` with an arbitrary :class:`~app.thesis.models.HoldoutState`
attached and assert on the status code that shape produces, without driving real bars through real
indicators through a real SQLite ledger to get there. Every Protocol method signature is built from
:mod:`app.thesis.models` shapes for the same reason the lazy imports are lazy: this file has no
compile-time opinion about how :mod:`app.thesis.loop` gets a :class:`LoopResult`, only about the shape
of the thing it gets back.

**The iteration budget is bounded here, hard.** :data:`~app.thesis.models.DEFAULT_ITERATION_BUDGET`
is a default a caller can override, and an unbounded override defeats guard 4 as completely as no
budget at all -- a caller who can ask for a budget of ten thousand has re-created "loop until it
works" one HTTP request away from the code that forbids it. Bounded to 1..24: twice the default is
generous headroom for a caller who wants to walk the whole catalogue and its handful of
leveraged-only entries twice, and it is still a number a person chose, not the absence of one.

**``HoldoutBurned`` and ``HoldoutUnavailable`` never reach this layer as exceptions.**
:func:`app.thesis.loop.run` already catches both internally -- at :func:`~app.thesis.holdout.establish`
and at :func:`~app.thesis.holdout.claim` respectively -- and folds them into an ordinary
:class:`~app.thesis.models.LoopResult` carrying
:attr:`~app.thesis.models.LoopOutcome.HOLDOUT_UNAVAILABLE` plus a warning. That is the right shape for
the loop itself: a run that could not get an out-of-sample read is real information about the ticker,
not a crash. It is the wrong shape for this endpoint to hand back as a bare 200, because the caller of
an HTTP API reads status codes before bodies, and "your holdout is now burned" is exactly the kind of
fact a 200 buries. So :func:`run_thesis_loop` re-derives which of the two happened from the returned
state -- :attr:`~app.thesis.models.HoldoutState.status` is
:attr:`~app.thesis.models.HoldoutStatus.BURNED` only when :func:`~app.thesis.holdout.claim` was the
cause, and the holdout is ``None`` only when :func:`~app.thesis.holdout.establish` never created one
-- and raises the two different HTTP errors the guard's own module docstring calls for: 409 for a
conflict with prior state the request cannot fix by retrying, 422 for a request that was fine but
whose ticker cannot yet support the guarantee.

**Nothing here filters, paginates, or trims to survivors.** ``GET /ledger`` and the body of
``POST /run`` always carry the full ``records``/``ledger`` pair. A "just show me what worked" view
would let a caller see a result without its denominator, which is precisely the invisible-trial-count
failure mode :mod:`app.thesis` exists to prevent -- adding it here would undo guard 2 one layer up
from where it is enforced.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Annotated, Protocol, cast

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.db.duck import Interval
from app.market.models import BarSeries, MarketWarning
from app.market.providers.base import ProviderError, ProviderUnavailable, SymbolNotFound
from app.market.registry import ProviderRegistry, default_registry
from app.thesis.models import (
    DEFAULT_ITERATION_BUDGET,
    Direction,
    HoldoutState,
    HoldoutStatus,
    LedgerStats,
    LoopOutcome,
    LoopResult,
    StrategyCard,
    ThesisRecord,
)
from app.thesis.promotion import DEFAULT_POSITION_PCT, PromotionError, PromotionResult
from app.tournament.models import StrategyCard as LibraryCard
from app.tournament.purposes import Purpose

router = APIRouter(prefix="/api/thesis", tags=["thesis"])

#: Same closed alphabet as `app.api.backtest.SymbolParam`: a symbol reaches the filesystem as a
#: Parquet partition directory name one layer down, so the pattern is a filesystem-safety bound as
#: much as an input-shape one.
SymbolParam = Annotated[str, Query(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")]

#: Hard ceiling on `POST /run`'s budget. See the module docstring -- an override without a ceiling
#: defeats guard 4 exactly as no budget at all does.
_MAX_BUDGET = 24


# ---------------------------------------------------------------------------
# Injectable collaborators
# ---------------------------------------------------------------------------
#
# Protocol + lazy-default shape, matching `app.backtest.service`. See the module docstring for why
# this router needs the seam even though `app.thesis.loop` already composes everything below it.


class LoopRunner(Protocol):
    def run(
        self,
        symbol: str,
        *,
        interval: Interval = Interval.DAY,
        budget: int = DEFAULT_ITERATION_BUDGET,
        settings: Settings | None = None,
        registry: ProviderRegistry | None = None,
    ) -> LoopResult: ...


class CardBuilder(Protocol):
    """What `POST /run` needs to turn one survivor into a `StrategyCard`.

    Deliberately not shaped after `app.thesis.strategycard.build_card` itself, whose signature takes
    `bars` and `evidence` the caller must already have in hand -- a router-level Protocol shaped that
    way would leak `app.thesis.strategycard`'s internal decomposition (baseline distribution, regime
    masks, tax replay) into this file's compile-time surface, exactly what the module docstring says
    this file must not do. Instead this Protocol asks for what *this* layer actually has: a symbol,
    an interval, and the one `ThesisRecord` that survived -- everything a card needs to be built from
    scratch, including re-reading bars, is the implementation's problem, not this file's.
    """

    def build_for_survivor(
        self,
        symbol: str,
        interval: Interval,
        survivor: ThesisRecord,
        *,
        ledger_stats: LedgerStats | None = None,
        holdout_state: HoldoutState | None = None,
        settings: Settings | None = None,
        registry: ProviderRegistry | None = None,
    ) -> StrategyCard: ...


class LedgerReader(Protocol):
    def stats_for(self, symbol: str, *, settings: Settings | None = None) -> LedgerStats: ...

    def records_for(
        self, symbol: str, *, settings: Settings | None = None
    ) -> list[ThesisRecord]: ...


class HoldoutReader(Protocol):
    def load(self, symbol: str, *, settings: Settings | None = None) -> HoldoutState | None: ...

    def describe(self, state: HoldoutState | None) -> str: ...


class TemplateLike(Protocol):
    """What `GET /catalogue` needs from one entry. Structural, not `app.thesis.author.Template`
    itself -- this router's compile-time dependency stops at `app.thesis.models` shapes, and a
    template's key/hypothesis/rules are not modelled there because the catalogue is the author's
    concern, not the loop's contract. Duck typing here is the same call `app.thesis.loop.Evaluator`
    makes for a different reason and reaches the same place: describe what is used, not where it
    lives.

    Declared as read-only properties rather than plain attributes: `Template` is a frozen dataclass,
    and a Protocol's plain `name: T` attribute demands a *settable* member, which a frozen field can
    never satisfy structurally under ``mypy --strict`` even though reading it is exactly what this
    router does.
    """

    @property
    def key(self) -> str: ...
    @property
    def hypothesis(self) -> str: ...
    @property
    def entry(self) -> str: ...
    @property
    def exit(self) -> str | None: ...
    @property
    def horizon(self) -> int: ...
    @property
    def direction(self) -> Direction: ...
    @property
    def falsifies_if(self) -> str: ...
    @property
    def rationale(self) -> str: ...
    @property
    def max_holding_bars(self) -> int | None: ...
    @property
    def stop_loss_pct(self) -> float | None: ...
    @property
    def leveraged_only(self) -> bool: ...


class AuthorCatalogue(Protocol):
    @property
    def CATALOGUE(self) -> tuple[TemplateLike, ...]: ...


def _default_loop_runner() -> LoopRunner:
    from app.thesis import loop

    return loop


def _bars_frame(series: BarSeries) -> pd.DataFrame:
    """Same construction `app.thesis.loop._bars_frame` uses. Duplicated rather than imported: that
    function is private to a module this router does not import at module load time (see the module
    docstring), and the handful of lines that matter are simple enough to state directly rather than
    reach into another module's private surface."""
    return pd.DataFrame(
        {
            "ts": pd.Series([b.ts for b in series.bars], dtype="datetime64[ns, UTC]"),
            **{
                column: pd.Series([getattr(b, column) for b in series.bars], dtype="float64")
                for column in ("open", "high", "low", "close", "adj_close", "volume")
            },
        }
    )


class _StoreCardBuilder:
    """Default `CardBuilder`: re-reads the ticker's bars from the store and hands them, plus the
    survivor's own evidence, to `app.thesis.strategycard.build_card`.

    Re-reading bars here rather than widening `LoopResult` to carry them is deliberate.
    `app.market.store.ensure_series` is a cache read in the common case -- it only re-syncs when the
    store is empty, stale, or `refresh` is requested, see its own docstring -- so the run the loop
    just finished has already primed the cache this call reads from; this is not a second real
    fetch. The alternative, putting a `pandas.DataFrame` on `LoopResult` so this layer never has to
    ask again, would put pandas on the wire contract of every other consumer of `LoopResult` for the
    sake of the one caller that needs it.

    Takes `ensure_series` and `build_card` as constructor arguments rather than importing
    `app.market.store` and `app.thesis.strategycard` at class-body scope, so that the only place
    either import happens is inside `_default_card_builder`, at request time -- never at module load,
    for the same reason the rest of this file's collaborators are lazy.
    """

    def __init__(
        self,
        ensure_series: Callable[..., BarSeries],
        build_card: Callable[..., StrategyCard],
    ) -> None:
        self._ensure_series = ensure_series
        self._build_card = build_card

    def build_for_survivor(
        self,
        symbol: str,
        interval: Interval,
        survivor: ThesisRecord,
        *,
        ledger_stats: LedgerStats | None = None,
        holdout_state: HoldoutState | None = None,
        settings: Settings | None = None,
        registry: ProviderRegistry | None = None,
    ) -> StrategyCard:
        if survivor.in_sample is None:
            # Cannot happen for a record the loop actually screened -- `_screen` always attaches
            # `in_sample` before a verdict is set -- but the field is typed `Evidence | None` on
            # `ThesisRecord`, and a card built from evidence that was never measured would be
            # indistinguishable from one built honestly. Raising here (caught by the caller, see
            # `run_thesis_loop`) is louder than silently building a hollow card.
            raise ValueError(
                f"record {survivor.thesis_hash[:12]} has no in-sample evidence; a card cannot be "
                "built for a thesis the loop never screened"
            )

        cfg = settings or get_settings()
        series = self._ensure_series(symbol, interval, registry=registry, settings=cfg)
        bars = _bars_frame(series)
        return self._build_card(
            survivor.thesis,
            survivor,
            bars=bars,
            evidence=survivor.in_sample,
            holdout_evidence=survivor.holdout,
            ledger_stats=ledger_stats,
            holdout_state=holdout_state,
        )


def _default_card_builder() -> CardBuilder:
    from app.market.store import ensure_series
    from app.thesis.strategycard import build_card

    return _StoreCardBuilder(ensure_series=ensure_series, build_card=build_card)


def _default_ledger() -> LedgerReader:
    from app.thesis import ledger

    return ledger


def _default_holdout() -> HoldoutReader:
    from app.thesis import holdout

    # `describe` is a real, public function on this module (see its docstring: "One line a UI can
    # show..."), but it is not listed in the module's `__all__`, which `mypy --strict` treats as the
    # module's declared public surface when matching it against a Protocol. The cast reflects what is
    # actually true at runtime rather than what an unrelated export list happens to say -- and this
    # router may not add `describe` to that list itself, since `app/thesis/holdout.py` is out of
    # scope for this change.
    return cast(HoldoutReader, holdout)


def _default_author() -> AuthorCatalogue:
    from app.thesis import author

    return author


class Promoter(Protocol):
    """The one call `POST /promote` makes into `app.thesis.promotion`. Protocol-typed like every
    other collaborator here so a test can hand back a `PromotionResult` (or raise a `PromotionError`)
    without a real ledger record, a real catalogue and a real library directory to write into."""

    def promote(
        self,
        record: ThesisRecord,
        *,
        position_pct: Decimal,
        purpose: Purpose,
        settings: Settings | None = ...,
    ) -> PromotionResult: ...


def _default_promoter() -> Promoter:
    from app.thesis import promotion

    return cast(Promoter, promotion)


def _registry() -> ProviderRegistry:
    """One registry per request -- see `app.api.backtest._registry`."""
    return default_registry()


def _handle(exc: ProviderError) -> HTTPException:
    """The same status mapping every other market-facing router uses."""
    if isinstance(exc, SymbolNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ProviderUnavailable):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _warning_message(result: LoopResult, kind: str) -> str | None:
    """The message of the first warning of this kind, if `run` left one.

    `app.thesis.loop.run` attaches `kind="holdout_burned"` or `kind="holdout_unavailable"` at the
    exact point it swallows the corresponding exception -- see the module docstring. Reading the
    message back out here means the 409/422 this endpoint raises carries the same text the guard
    itself produced, not a paraphrase that could drift from it.
    """
    return next((w.message for w in result.warnings if w.kind == kind), None)


# ---------------------------------------------------------------------------
# Response shapes specific to this router
# ---------------------------------------------------------------------------
#
# None of these belong in `app.thesis.models`: they are HTTP-response envelopes around that module's
# shapes, not new domain concepts, and adding them there would blur a boundary the rest of this
# package is careful about.


class LedgerResponse(BaseModel):
    """`GET /ledger`'s body: the denominator and the trials that make it up, together.

    Always both. A view offering the stats without the records -- or the records without the stats --
    would let a caller reconstruct only part of the trial history, and the whole point of guard 2 is
    that the family is inspectable, not summarised away.
    """

    stats: LedgerStats
    records: list[ThesisRecord]


class HoldoutResponse(BaseModel):
    """`GET /holdout`'s body. `state` is `None` for a ticker whose holdout has never been
    established -- not an error, just a fact this ticker has not yet had a thesis screened far enough
    to reserve one."""

    state: HoldoutState | None
    description: str


class CatalogueEntry(BaseModel):
    """One standard hypothesis from `app.thesis.author.CATALOGUE`, as the author wrote it -- before
    any ticker was chosen and before any bar was read. Exposed so a user can see what the loop is
    capable of proposing before spending a trial on it."""

    key: str
    hypothesis: str
    entry: str
    exit: str | None
    horizon: int
    direction: Direction
    falsifies_if: str
    rationale: str
    max_holding_bars: int | None
    stop_loss_pct: float | None
    leveraged_only: bool


class RunRequest(BaseModel):
    """`POST /run`'s body. `budget` is bounded 1..24 -- see the module docstring for why an
    unbounded override is the exact hazard this feature exists to prevent."""

    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")
    interval: Interval = Interval.DAY
    budget: int = Field(default=DEFAULT_ITERATION_BUDGET, ge=1, le=_MAX_BUDGET)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/run", response_model=LoopResult)
def run_thesis_loop(request: RunRequest) -> LoopResult:
    """Run the loop for one ticker, end to end: propose, screen in-sample, correct against the whole
    ledger, spend the holdout at most once, then build a `StrategyCard` for the survivor, if any.

    Returns the full `LoopResult` -- `records` and `ledger` included, whatever the outcome -- because
    a caller who only sees survivors has seen a different, more flattering result than the one that
    actually happened. See the module docstring for why a burned or unavailable holdout becomes a
    4xx here rather than a 200 the caller has to inspect to notice.

    `result.cards` carries the survivor's card and only the survivor's -- see
    `LoopResult.cards`'s own docstring for why building one for every rejected and inconclusive
    record too would not be free. A run can only ever produce zero or one survivor (`app.thesis.loop`
    returns as soon as one's holdout confirms), so this never needs to build more than one. If the
    card build itself fails, that failure does not become this endpoint's failure: the loop's result
    is the valuable part of the response, a `kind="card_failed"` warning is appended so the caller can
    see what did not render, and `cards` stays empty rather than the whole request turning into a
    500 over a rendering step, not a research one.
    """
    runner = _default_loop_runner()
    cfg = get_settings()
    try:
        result = runner.run(
            request.symbol.upper(),
            interval=request.interval,
            budget=request.budget,
            settings=cfg,
            registry=_registry(),
        )
    except ProviderError as exc:
        raise _handle(exc) from exc

    if result.outcome is LoopOutcome.HOLDOUT_UNAVAILABLE:
        if result.holdout is not None and result.holdout.status is HoldoutStatus.BURNED:
            # A second evaluation was attempted this run: `holdout.claim` recorded the burn before
            # raising, so the state on the result already reflects it. Not 400 -- the request was
            # well-formed and the *state* is the conflict.
            detail = _warning_message(result, "holdout_burned") or _default_holdout().describe(
                result.holdout
            )
            raise HTTPException(status_code=409, detail=detail)

        # No holdout was ever established for this ticker -- too little history to reserve one.
        # Well-formed request, unprocessable ticker.
        detail = _warning_message(result, "holdout_unavailable") or (
            f"{result.symbol}: this ticker's history cannot support a holdout evaluation yet"
        )
        raise HTTPException(status_code=422, detail=detail)

    if result.outcome is LoopOutcome.SURVIVOR_FOUND:
        # `LoopResult`'s own validators (see `app.thesis.models`) now guarantee `survivors` is
        # non-empty exactly when `outcome` is `SURVIVOR_FOUND`, and `app.thesis.loop.run`'s module
        # docstring establishes that at most one record can legitimately reach `SURVIVED` in a single
        # run -- so `survivors[0]` is the survivor, not a guess at it. `result` reached this branch
        # already validated (`LoopRunner.run` returns a `LoopResult`, which cannot be constructed with
        # this outcome and no survivor), so indexing here relies on an invariant the type system and
        # the validator both enforce, not on this endpoint re-deriving it with a defensive scan.
        survivor = result.survivors[0]
        try:
            card = _default_card_builder().build_for_survivor(
                result.symbol,
                result.interval,
                survivor,
                ledger_stats=result.ledger,
                holdout_state=result.holdout,
                settings=cfg,
                registry=_registry(),
            )
        except Exception as exc:
            # Broad on purpose -- see the docstring: a card failure must not turn a completed
            # run into a 500. Matches the identical broad-except-and-warn choice
            # `app.thesis.loop.run` makes around `evaluate_thesis` for the same reason:
            # everything from a store read failure to a bad regime computation lands here, and
            # none of it should cost the caller the loop's own result.
            result = result.model_copy(
                update={
                    "warnings": [
                        *result.warnings,
                        MarketWarning(
                            kind="card_failed",
                            message=(
                                f"{survivor.thesis.hypothesis[:60]}...: strategy card could not "
                                f"be built ({exc})"
                            ),
                        ),
                    ]
                }
            )
        else:
            result = result.model_copy(update={"cards": [card]})

    return result


class PromoteRequest(BaseModel):
    """Identify a survivor and set its two risk knobs. Deliberately carries **no** rule/DSL field:
    the server rebuilds the card from the ledger record, so a caller can point at a survivor but never
    describe one -- a library card's `entry`/`exit` are executed, and accepting them from a request
    would be an injection path. See `app.thesis.promotion`'s module docstring."""

    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")
    thesis_hash: str = Field(min_length=8, max_length=128)
    position_pct: Decimal = Field(default=DEFAULT_POSITION_PCT, gt=0, le=1)
    """Fraction of the book this single-name card commits. Owner policy, a validated numeric."""
    purpose: Purpose = Purpose.TRADING


@router.post("/promote", response_model=LibraryCard, status_code=201)
def promote_thesis_survivor(request: PromoteRequest) -> LibraryCard:
    """Promote a Thesis **survivor** onto the library shelf as a `reference_only` card.

    The survivor is resolved from the thesis ledger by `(symbol, thesis_hash)` and its `verdict` is
    re-read there -- never trusted from the request -- so a non-survivor is refused (422) whatever the
    caller claims. The written card is scored on no window (`reference_only`): a fresh survivor is
    designed through ~now, past every scored window's opening, so there is no honest window to score
    it on. Its evidence stays in the ledger; this puts a readable, hash-pinned spec on the shelf.

    - **201** with the new card on success.
    - **404** if no such survivor is registered for the symbol.
    - **409** (idempotent) if it was already promoted -- a survivor's rules are hash-pinned, so a
      re-promote is a no-op, not a duplicate.
    - **422** if the record did not survive, or survived but cannot be a card (non-daily interval,
      out-of-range time stop, or no way to close a position).
    """
    cfg = get_settings()
    records = _default_ledger().records_for(request.symbol, settings=cfg)
    record = next((r for r in records if r.thesis_hash == request.thesis_hash), None)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no thesis {request.thesis_hash[:12]!r} is registered for "
                f"{request.symbol.upper()}; nothing to promote"
            ),
        )
    try:
        result = _default_promoter().promote(
            record,
            position_pct=request.position_pct,
            purpose=request.purpose,
            settings=cfg,
        )
    except PromotionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not result.created:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    f"{result.card.agent_id} is already on the library shelf. A survivor's rules "
                    "are hash-pinned, so promoting it again changes nothing."
                ),
                "agent_id": result.card.agent_id,
            },
        )
    return result.card


@router.get("/ledger", response_model=LedgerResponse)
def thesis_ledger(symbol: SymbolParam) -> LedgerResponse:
    """The trial ledger for one ticker -- readable without running anything.

    A ticker with no history returns zeros and an empty record list, not a 404: "no trials yet" is a
    fact about the denominator, the same contract `app.thesis.ledger.stats_for` documents.
    """
    reader = _default_ledger()
    cfg = get_settings()
    upper = symbol.upper()
    return LedgerResponse(
        stats=reader.stats_for(upper, settings=cfg),
        records=reader.records_for(upper, settings=cfg),
    )


@router.get("/holdout", response_model=HoldoutResponse)
def thesis_holdout(symbol: SymbolParam) -> HoldoutResponse:
    """One ticker's holdout state, plus a human sentence describing it.

    Read-only: this never establishes a holdout, only reports whether one exists. Establishing one is
    a side effect reserved for `POST /run`, which has bars to split.
    """
    reader = _default_holdout()
    cfg = get_settings()
    state = reader.load(symbol.upper(), settings=cfg)
    return HoldoutResponse(state=state, description=reader.describe(state))


@router.get("/catalogue", response_model=list[CatalogueEntry])
def thesis_catalogue() -> list[CatalogueEntry]:
    """Every standard hypothesis the default author can propose, so a user can see what will be
    tried before a single trial is spent on it."""
    reader = _default_author()
    return [
        CatalogueEntry(
            key=template.key,
            hypothesis=template.hypothesis,
            entry=template.entry,
            exit=template.exit,
            horizon=template.horizon,
            direction=template.direction,
            falsifies_if=template.falsifies_if,
            rationale=template.rationale,
            max_holding_bars=template.max_holding_bars,
            stop_loss_pct=template.stop_loss_pct,
            leveraged_only=template.leveraged_only,
        )
        for template in reader.CATALOGUE
    ]
