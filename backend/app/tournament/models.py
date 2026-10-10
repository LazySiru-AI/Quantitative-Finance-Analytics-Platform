"""The contract for a strategy tournament: what an analyst submits, and what a run returns.

Ten analysts each design a strategy, each strategy is traded through the same mock broker over the
same window, and the results are compared. Everything in this package exists to make that
comparison mean something, because the naive version of it does not.

**The naive version is a p-hacking machine.** Run ten strategies over six months, report the best
one, and you have found the maximum of ten noisy samples -- which is a large positive number
whether or not any strategy has an edge. Three structural choices answer that, and each is enforced
here rather than left to the analyst's discipline:

*Design and evaluation happen in different windows.* :data:`DESIGN_THROUGH` is the last day an
analyst may look at. :data:`TRADE_START` is the first day traded. They do not overlap, and
:class:`StrategyCard` refuses a submission claiming to have been designed past the cutoff. An
analyst who fits the trading window cannot do so accidentally; they have to lie about a date.

*The comparison is corrected for the number of strategies tried.* Ten hypotheses need ten-hypothesis
arithmetic. `app.backtest.scan.benjamini_hochberg` already exists for exactly this and is used
unchanged -- including its rule that a strategy with no computable p-value still occupies a slot in
the denominator, because dropping it would flatter every other entry.

*The mock broker is the one the UAT harness already uses.* `uat.harness.paperbroker.PaperBroker`
enforces cash, settlement, position caps and adverse slippage, and `uat.harness.marketdata`'s
``AsOfMarket`` makes lookahead structurally impossible rather than merely checked -- every read
derives its window from the instance's ``as_of``, which a caller cannot widen. Reusing it means a
tournament result and a persona result were produced by the same rules.

**None of this makes a profitable backtest evidence that a strategy works.** 127 sessions is one
regime, not a sample of regimes; survivorship, the specific universe, and the fact that these
tickers were chosen because the user already traded them are all live biases that no correction
here removes. The reports this package generates are required to say so.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.models import Money, Quantity
from app.tournament.purposes import Purpose

__all__ = [
    "DESIGN_THROUGH",
    "DESK_INCEPTION",
    "TRADE_END",
    "TRADE_START",
    "AgentResult",
    "Discipline",
    "RejectionRecord",
    "StrategyCard",
    "TournamentResult",
]

DESIGN_THROUGH: dt.date = dt.date(2026, 2, 13)
"""The last session an analyst is permitted to have looked at while designing.

The design window's final session and the trading window's first *decision* are the same day, which
is not an off-by-one: the trading window's first order is decided on this close and filled at the
next session's open, so an analyst who saw this day saw nothing the trader did not also see. One day
later would have been a leak.
"""

TRADE_START: dt.date = dt.date(2026, 2, 17)
"""First session traded. 127 sessions to :data:`TRADE_END`, roughly six months."""

TRADE_END: dt.date = dt.date(2026, 8, 18)
"""Last session traded -- the last stored session at the time this package was built."""

DESK_INCEPTION: dt.date = dt.date(2026, 8, 15)
"""First session of the **paper desk's** forward window -- the cutoff a ``desk_only`` card is held
to instead of :data:`DESIGN_THROUGH`.

**This is a mirror of `app.paperdesk.desk.INCEPTION`, and the duplication is deliberate.**
`app.paperdesk.desk` imports this module for `StrategyCard`, so this module cannot import it back to
read the real constant. The alternative -- a deferred import inside a model validator, run on every
card load -- makes a hot path depend on import order to enforce a date. Mirroring the literal and
asserting the two agree in a test is the same pattern `tests/test_paper_mandate.py` already uses to
keep the persona file and `default_mandate()` from drifting apart; `tests/test_tournament_models.py`
holds the assertion for this pair. **If you move `desk.INCEPTION`, move this too** -- the test will
say so, loudly, before anything else does.

Note this mirrors the desk's *default* inception, not `desk.effective_inception()`, which an operator
can override at runtime through `data/paperdesk/inception.json`. A validator cannot read that file --
it has no `Settings` -- so an operator who moves inception *earlier* than a seated `desk_only` card's
`designed_through` has re-opened the leak this check closes, and nothing here will catch it. That is a
real gap, stated rather than papered over: the override is an operator action on a desk whose whole
record restarts when it is used, and the honest place to notice is that restart, not a card validator.
"""


class Discipline(StrEnum):
    """The school an analyst is working in.

    Recorded so the tournament can say whether the strategies were genuinely different approaches
    or ten variations on one idea. Ten momentum strategies that all buy the same breakout are one
    hypothesis tested ten times, and the correction arithmetic cannot tell that from ten
    independent ideas -- only this label, and a reader, can.
    """

    TREND = "trend"
    MEAN_REVERSION = "mean-reversion"
    MOMENTUM = "momentum"
    BREAKOUT = "breakout"
    VOLATILITY = "volatility"
    PAIRS_ROTATION = "pairs-rotation"
    RISK_MANAGED = "risk-managed"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class StrategyCard(_Frozen):
    """One analyst's submission: the strategy, and the claim about how it was arrived at."""

    agent_id: str
    """Short slug, unique within the tournament. Becomes the report filename."""

    display_name: str
    discipline: Discipline

    purpose: Purpose = Purpose.TRADING
    """Which of the three investment goals (`app.tournament.purposes.Purpose`) this card serves --
    `savings`, `trading` or `roth`. Decides how the card is scored (lump-sum `adjusted_excess` for
    `trading`; the contribution harness, reporting both money-weighted IRR and time-weighted CAGR, for
    the other two -- see `app.tournament.purposes`'s module docstring) and, for `roth`, that this
    card's `universe` must stay disjoint from every `savings`- or `trading`-purpose card's
    (`app.tournament.purposes.find_disjointness_violations`).

    Defaults to `Purpose.TRADING` because every card that already exists on disk genuinely is a
    trading card: committed before `Purpose` existed, funded as a single lump sum, run through this
    package's lump-sum-scored tournament -- not a placeholder guess, but what those roughly 35
    committed card JSONs across `backend/app/paper/library/{base,variants,candidates,retired}` and
    `data/rounds/*/cards/` already are. No existing card JSON needs an edit, and no existing test needs
    a `purpose` key added to it, to keep validating against this model."""

    desk_only: bool = False
    """This card is scored on the paper desk's forward window only, never in the tournament.

    **What it buys, and why the default is `False`.** The tournament's design cutoff
    (:data:`DESIGN_THROUGH`, 2026-02-13) exists so no card is scored on a window its author could
    already see. That cutoff is correct for the tournament, whose window opens at
    :data:`TRADE_START`. It is the wrong date for the paper desk, which trades its own forward window
    from :data:`DESK_INCEPTION` (2026-08-15) -- six months later. Before this field existed, a
    strategy built on a signal that only became public in August could not be expressed at all: the
    validator below rejected it for having looked at data *after February*, while the desk it was
    headed for would not start trading it until *after August*. The invariant was never "February";
    it is **"designed_through must precede the first session of the window this card is scored on."**
    This field says which window that is, and the validator applies the matching cutoff.

    `False` is the default because every card already on disk genuinely is a tournament card -- all
    sixty in `backend/app/paper/library/` carry `designed_through = 2026-02-13`, and every frozen
    card under `data/rounds/*/cards/` was committed and measured under the tournament cutoff. No
    existing card JSON needs an edit and no existing round needs revisiting for this field to exist.

    **What it costs.** A `desk_only` card has no tournament result and cannot acquire one: it is
    refused by `app.tournament.jobs._resolve_cards`, so it can never enter a round's field, be ranked
    against a gate, or appear on a scorecard. Its entire evidentiary record is the forward desk. That
    is a weaker position than any seated card holds, and a reader comparing a `desk_only` card's
    return against `B3-concentrated`'s is comparing one live window to a live window plus three
    backtest matrices. This flag is what makes such a strategy expressible, not what makes it
    evidence.
    """

    thesis: str
    """Why this should work, in the analyst's own words, written **before** the trading window ran.

    Kept because a strategy's rationale is the only thing that distinguishes a hypothesis from a
    curve fit after the fact. A card whose thesis is a description of its own rules ("buys when RSI
    is low") has not stated one.
    """

    falsification: str | None = None
    """What measurement would make this card's `thesis` wrong -- named by the author, in advance.

    **Why this exists.** `docs/research/programme/thesis-audit.md` read all six cards seated to a book
    and found that **eleven of thirteen quantitative thesis claims had never been measured outside the
    window they were fitted on**, and that the split ran cleanly along card type: the two
    allocation-family cards each stated in prose what would falsify them, named the document that
    would hold the number, and the number existed. None of the four trading cards stated a
    falsification condition at all. A thesis is what a reader takes a card to have established, and
    until this field nothing in the apparatus asked the author to say how it could fail.

    **Optional on the model, expected on a seated card.** Roughly 35 committed card JSONs plus the
    evolution loop's whole genome population validate against this model, and none of them carries
    one, so a required field here would be a migration rather than a check. The expectation is
    enforced where it means something -- `tests/test_thesis_falsification.py` asserts it over
    `app.paperdesk.desk`'s seated rosters, which is the set a reader sees beside live money.

    **A restatement of the rules is not a falsification condition**, for the same reason it is not a
    thesis: "wrong if the moving averages stop crossing" describes the mechanism. What belongs here
    is the observation that would settle it -- an out-of-sample comparison, a control arm, a null --
    stated so that someone other than the author could run it and so that the answer is not already
    known when it is written.
    """

    universe: tuple[str, ...] = Field(min_length=1, max_length=12)
    """Tickers to trade, drawn from the ones the user has actually traded."""

    entry: str
    """Rule-DSL expression. Grammar in `app.rules.grammar`; must pass `app.backtest.guards.check`."""

    exit: str
    """Rule-DSL expression for a discretionary exit. Stops and targets are separate fields, because
    a stop that lives inside the exit expression cannot be reported on independently."""

    stop_loss_pct: Decimal | None = None
    """Hard stop as a fraction of one below entry -- ``Decimal("0.08")`` is 8%."""

    take_profit_pct: Decimal | None = None
    """Target as a fraction of one above entry."""

    max_hold_days: int | None = Field(default=None, ge=1, le=252)
    """Time stop. A strategy with no exit rule, no target and no time stop can hold forever, which
    is a position, not a strategy."""

    max_positions: int = Field(ge=1, le=8)
    position_pct: Decimal
    """Fraction of starting equity committed per position."""

    rank_by: str | None = None
    """Ranking-key expression deciding **which** qualifying names take the scarce slots.

    The one place this engine compares symbols to each other rather than to their own bars. When
    more names satisfy `entry` on a session than `max_positions` leaves room for, somebody has to
    choose; with this unset -- the default, and what every card frozen before this field existed
    gets -- that choice is the order `universe` happens to be written in. That is an arbitrary
    tiebreak, and a measured one: re-running a single identical card under twelve orderings moved
    its three-year return across a **53.9-point spread, sigma = 21.2 points**
    (`strategy-program/PROTOCOL.md` §7). A card that leaves this `None` is still exposed to all of
    it, and its margins must still be read against that floor.

    Set, it is rule-DSL text parsed by `app.rules.grammar.parse_ranking` -- the same grammar,
    indicators and precedence `entry`/`exit` use, but yielding a number instead of a condition:
    `close / sma(200)` for distance above trend, `rsi(14)` for momentum magnitude,
    `(close - sma(50)) / atr(14)` for the same thing in volatility units. It is evaluated per
    symbol against that symbol's own bars at the decision session, exactly as the entry rule is,
    and the resulting scalars are then sorted against each other. **Highest first**: the key names
    the quantity you want the most of, and negation inverts it (`0 - rsi(14)` takes the weakest),
    so there is exactly one way to express any order and no second direction field to disagree
    with the expression.

    This does not make the engine cross-sectional in general. It cannot express a spread, a pair,
    or an entry condition contingent on another symbol -- `entry` is still evaluated per symbol in
    isolation, and a name that fails it is never ranked at all. What it removes is the arbitrary
    part of a choice the engine was already making silently.
    """

    designed_through: dt.date
    """The last session the analyst looked at. Must not exceed :data:`DESIGN_THROUGH` -- unless
    `reference_only`, which is scored on no window and so is exempt (see that field)."""

    reference_only: bool = False
    """This card is a **reference specification** -- it is entered into no scored window, not the
    tournament and not the paper desk.

    **Why it exists.** A `Thesis` survivor (`app.thesis`) is a rule that was pre-registered and then
    validated on a *holdout* running up to its registration date -- so it is genuinely "designed
    through ~now". Every scored window here opens earlier than that (the tournament at
    :data:`TRADE_START`, the desk at :data:`DESK_INCEPTION`), so there is no honest window to score it
    on and no honest `designed_through` that clears the cutoff below. Pinning it to
    :data:`DESIGN_THROUGH` the way an evolution genome legitimately does would be a *false* date --
    the thesis demonstrably evaluated its rule past February -- and would defeat the exact lookahead
    guard the cutoff is. `POST /api/thesis/promote` (`app.thesis.promotion`) instead writes the
    survivor as a reference card: a first-class, readable entry on the library shelf whose evidence
    lives in the thesis ledger, scored by nothing here.

    **What makes the cutoff exemption safe.** Because it is scored on no window, there is nothing its
    author could have seen too early, so `_cannot_claim_to_have_seen_the_trading_window` skips the
    check for it. That exemption is only honest if the card really is scored nowhere, and two call
    sites enforce that: `app.tournament.jobs._resolve_field` refuses it from a round (raises if named,
    excludes it from a defaulted tier, exactly as it treats `desk_only`), and `app.paperdesk.desk`
    skips it when seating. Mutually exclusive with `desk_only`, which means the opposite -- *scored on
    the desk*; a card cannot be both scored-on-the-desk and scored-nowhere."""

    source_thesis_hash: str | None = None
    """Set only on a card promoted from a `Thesis` survivor (`POST /api/thesis/promote`). Links the
    card back to its `ThesisRecord` in the thesis ledger for audit and for promotion idempotency.
    `None` for every hand-authored or evolution-bred card -- added optional, no migration, exactly as
    `falsification` was."""

    source_persona: str | None = None
    """Set only on a card promoted from a persona strategy-card draft
    (`POST /api/personas/{slug}/strategy-cards/{version}/promote`). Carries `"{slug}@v{version}"` so
    the shelved card is traceable to the exact persona draft it came from, and so re-promoting the
    same draft is idempotent. Unlike a promoted thesis survivor this card is *not* `reference_only`: a
    persona draft is built through `card_for`, which stamps the real `DESIGN_THROUGH`, so it is
    honestly designed before every scored window and competes as an ordinary candidate. `None` for
    every non-persona card."""

    @property
    def reward_risk(self) -> Decimal | None:
        """Target divided by stop -- the planned RRR, when both are declared.

        Planned, not realised: a strategy exits on its rule or its time stop far more often than on
        either bracket, so this is what the analyst intended, and `AgentResult` reports what
        actually happened beside it.
        """
        if self.take_profit_pct is None or self.stop_loss_pct in (None, Decimal(0)):
            return None
        assert self.stop_loss_pct is not None
        return self.take_profit_pct / self.stop_loss_pct

    @model_validator(mode="after")
    def _cannot_claim_to_have_seen_the_trading_window(self) -> Self:
        """`designed_through` must precede the first session of the window this card is scored on.

        Which window that is depends on `desk_only` -- see that field. This stays one rule, not two:
        an author may not have looked at the data their card is about to be measured on.

        A `reference_only` card is the one card scored on *no* window (see that field), so the rule
        has nothing to bite on and is skipped -- but only after refusing the contradiction of a card
        that claims to be both scored-nowhere (`reference_only`) and scored-on-the-desk (`desk_only`).
        """
        if self.reference_only:
            if self.desk_only:
                raise ValueError(
                    "a card cannot be both reference_only (scored on no window) and desk_only "
                    "(scored on the paper desk's forward window) -- these are opposite claims. A "
                    "promoted Thesis survivor is reference_only; leave desk_only false."
                )
            return self
        if self.desk_only:
            if self.designed_through >= DESK_INCEPTION:
                raise ValueError(
                    f"designed_through={self.designed_through.isoformat()} is not before the paper "
                    f"desk's inception {DESK_INCEPTION.isoformat()}. A desk_only card is scored on "
                    "the desk's forward window, so its author must not have seen that window's "
                    "first session -- the same rule the tournament applies at its own cutoff, "
                    "measured against the window this card is actually scored on."
                )
            return self
        if self.designed_through > DESIGN_THROUGH:
            raise ValueError(
                f"designed_through={self.designed_through.isoformat()} is after the design cutoff "
                f"{DESIGN_THROUGH.isoformat()}. The trading window starts "
                f"{TRADE_START.isoformat()}; a strategy designed with sight of it is fitted to the "
                "data it is about to be scored on, and its result would measure nothing. If this "
                "card is for the paper desk rather than the tournament, set desk_only=true -- that "
                "is a different window with a different, later cutoff, not a way around this one."
            )
        return self

    @model_validator(mode="after")
    def _position_sizing_is_a_fraction_of_one(self) -> Self:
        if not (Decimal(0) < self.position_pct <= Decimal(1)):
            raise ValueError(
                f"position_pct must be a fraction of one, not a percentage -- got "
                f"{self.position_pct}. Use Decimal('0.20') for 20%."
            )
        if self.position_pct * self.max_positions > Decimal("1.001"):
            raise ValueError(
                f"position_pct {self.position_pct} x max_positions {self.max_positions} commits "
                "more than the whole book. The broker would reject the overflow as insufficient "
                "cash, so the strategy would silently run smaller than written."
            )
        return self

    @model_validator(mode="after")
    def _ranking_key_is_a_number_this_grammar_can_compute(self) -> Self:
        """Reject an unparseable `rank_by` at load, not on the session it first has to break a tie.

        A card is frozen and then run across a whole matrix of windows; a key that does not parse
        would otherwise surface as a mid-run failure on whichever window first put four qualifying
        names in front of three slots -- and, because the runner walks past a failed card by design
        (`PROTOCOL.md` §8), as a silently short round rather than a loud one.

        Only the parse is checked here. Indicator resolution and the causality check need bars and
        an interval, which this model has neither of; `app.tournament.runner._guard_card` runs both
        against every universe symbol before the card trades, the same way it already does for
        `entry` and `exit`.
        """
        if self.rank_by is None:
            return self
        if not self.rank_by.strip():
            raise ValueError(
                "rank_by is an empty string. Leave it unset (null) to keep universe-order fills; "
                "an empty expression is not a ranking key."
            )
        from app.rules.grammar import RuleSyntaxError, parse_ranking

        try:
            parse_ranking(self.rank_by)
        except RuleSyntaxError as exc:
            raise ValueError(
                f"rank_by={self.rank_by!r} is not a ranking key: {exc}. A ranking key is a number "
                "per symbol -- 'close / sma(200)', 'rsi(14)' -- not a condition; the entry rule "
                "already decides who qualifies, and this decides which of them gets a slot."
            ) from exc
        return self

    @model_validator(mode="after")
    def _something_closes_the_position(self) -> Self:
        if not self.exit.strip() and self.max_hold_days is None and self.take_profit_pct is None:
            raise ValueError(
                "a card needs an exit rule, a take-profit, or a max_hold_days -- with none of "
                "them, a stop is the only way out and the strategy is only ever sold at a loss."
            )
        return self


class RealisedTrade(_Frozen):
    """One completed round trip, as the mock broker actually filled it."""

    symbol: str
    entry_date: dt.date | dt.datetime
    """The bar the position opened on. A calendar date for a daily run -- which is every run the
    tournament and the live desk perform -- and a full timestamp for an intraday one, because a date
    cannot name which of a session's 78 five-minute bars a fill happened on. Declared
    `date | datetime` rather than widened to `datetime` so daily results serialise byte-identically
    to every round already on disk; `datetime` is a subclass of `date`, and pydantic would otherwise
    coerce a date to midnight and rewrite them."""
    entry_price: Money
    exit_date: dt.date | dt.datetime | None
    exit_price: Money | None
    quantity: Quantity
    exit_reason: str
    """``rule`` / ``stop`` / ``target`` / ``time`` / ``open_at_end``."""

    pnl: Money
    return_pct: Decimal
    bars_held: int


class RejectionRecord(_Frozen):
    """One refused order, structured -- the report-facing counterpart to
    `app.paper.paperbroker.Rejection`, carrying only what a report groups on (not `order_id`,
    `session` or `side`/`quantity`, which stay internal to the broker's own run record)."""

    rule: str
    """The stable mandate-rule slug, e.g. ``"insufficient_cash"`` -- see
    `app.paper.paperbroker.REJECTION_LABELS` for the full set."""
    symbol: str
    reason: str
    """The broker's full sentence, e.g. ``"$1,200 exceeds $900 of settled cash ..."`` -- the detail
    `rejections` below discards by keeping only the bare rule slug."""


class AgentResult(_Frozen):
    """What one analyst's strategy did over the trading window."""

    card: StrategyCard
    sessions: int
    starting_equity: Money
    ending_equity: Money

    total_return: Decimal
    max_drawdown: Decimal
    """From `app.backtest.metrics.compute` -- never recomputed here. The repo has already shipped a
    defect from having two drawdown implementations that disagreed."""

    sharpe: float | None = None
    sortino: float | None = None
    volatility: float | None = None
    exposure: float | None = None
    """Fraction of *sessions* on which the card held at least one position, however small --
    session presence, not capital at risk. From `app.backtest.metrics.compute`, unchanged: a
    four-slot card holding one slot every session reports `1.0` here. See `capital_exposure` for
    the capital-weighted figure this field's name invites you to assume it already is (DEFECTS.md
    D2) -- the two answer different questions and are both real measurements, so neither is
    deprecated in favour of the other."""

    capital_exposure: float | None = None
    """Capital-weighted exposure: the fraction of *starting equity* actually deployed, averaged
    across sessions -- in contrast to `exposure` above, which only asks whether *any* position was
    open and ignores how much of the book it was. Computed by the runner from the per-session
    entry notional (`quantity * entry_price`, summed over every lot open at that session's close)
    over `starting_equity`, averaged over `sessions`. Entry notional, not a mark-to-market value,
    because `position_pct` sizes off starting equity at entry time (see
    `app.tournament.runner`'s module docstring), so entry notional over starting equity is the
    fraction of the book that position actually committed.

    `strategy-program/tools/score.py` independently reconstructs the same quantity from the trade
    log, as `Σ(quantity * entry_price * bars_held) / (sessions * starting_equity)` -- the two are
    the same sum taken two ways (per-session here, per-trade there) and should agree closely; a
    divergence between them means one of the two implementations is wrong, not that they measure
    different things.

    `None` only when there is no `sessions` denominator to average over, which cannot happen for a
    completed run (`SessionCalendar` never yields zero sessions); `0.0`, not `None`, for a card
    that never opened a position, matching `exposure`'s own zero-trade behaviour."""
    win_rate: float | None = None

    profit_factor: Decimal | None = None
    """Gross wins over gross losses. ``None`` when there were no losing trades -- which is not an
    infinite profit factor, it is too small a sample to have met one."""

    realised_reward_risk: Decimal | None = None
    """Mean winning return over mean losing return, as it actually happened. Reported beside
    `StrategyCard.reward_risk` so a plan and its outcome can be compared rather than conflated."""

    trades: tuple[RealisedTrade, ...] = ()
    rejections: tuple[str, ...] = ()
    """Orders the broker refused, by rule. A strategy whose orders were mostly rejected did not run
    as written, and a report that omits this presents a different strategy's results.

    Kept as a bare-slug tuple, unchanged, because readers already exist against this exact shape
    (`app.tournament.results.WindowMetrics.rejections`, `app.tournament.report_pdf`'s rejections
    section, `app.api.competition.AgentWindowDetail.rejections`) and widening the element type here
    would silently break every one of them -- a plain `str.join` and a pydantic `list[str]` response
    field both fail hard on a non-string element. See `rejection_details` below for the structured
    form; it is additive, not a replacement."""

    rejection_details: tuple[RejectionRecord, ...] = ()
    """The same refusals as `rejections` above, structured: `rule`, `symbol` and the broker's full
    `reason` sentence for each, in the order the broker recorded them. This is what
    `app.paperdesk.desk` groups into `app.paperdesk.models.DeskRejection` instead of discarding the
    reason text and repeating the bare slug once per refused order."""

    benchmark_return: Decimal | None = None
    """Buy-and-hold on the benchmark over the same sessions."""

    p_value: float | None = None
    """Two-sided binomial p-value on the win/loss record, via `app.backtest.scan.binomial_p_value`.
    ``None`` when there are too few closed trades to compute one."""

    q_value: float | None = None
    """:attr:`p_value` after Benjamini-Hochberg across the whole tournament. Filled in by the
    tournament, not by the run -- a single strategy has no multiple-comparison problem; ten do."""

    notes: tuple[str, ...] = ()


class TournamentResult(_Frozen):
    """Every agent's run, and the comparison across them."""

    generated_at: dt.datetime
    trade_start: dt.date
    trade_end: dt.date
    sessions: int
    agents: tuple[AgentResult, ...]
    alpha: float = 0.10
    discoveries: int = 0
    """How many agents survive Benjamini-Hochberg at :attr:`alpha`. Frequently zero, and zero is
    the honest and expected outcome of ten strategies over one six-month regime."""

    benchmark: str = "SPY"
    benchmark_return: Decimal | None = None
