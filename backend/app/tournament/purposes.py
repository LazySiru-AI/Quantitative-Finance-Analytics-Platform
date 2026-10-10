"""`Purpose`: which of three investment goals a strategy card serves, and the invariant that follows
from one of them.

`strategy-program/THREE-PURPOSES-PLAN.md` is this module's original specification, and
`ACCOUNT-DEPLOYMENT-PLAN.md` section 0 supersedes it on the funding figures, the horizons and the
benchmarks (see the note below the bullets). Three purposes exist today because three different
questions are being asked of the same programme, and nothing before this module distinguished them:

**All three are lump sums as of 2026-08-29**, and the figures below are that date's, not the plan
document's. The owner removed every ongoing contribution ("let's get rid of extra one thousand dollar
per month, anything like that") and reset the capital. `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md`
section 0 is the record of that instruction and of the four consequences it carries.

* **`savings`** -- $100,000 once, no additions, held 10-20 years, taxable. **The largest of the three
  books and the one with the safest mandate**: the owner's words are "keeping the wealth, without the
  big volatility," and they stated explicitly that they will accept the least return of the three for
  it. Was a $20,000 seed plus $1,000/month until 2026-08-29.
* **`trading`** -- $60,000 once, no additions, taxable, **bounded at six months** ("days up to three
  months or six months, six months maximum"). Trend and swing trading on rules. Both figures have
  moved repeatedly: the seed went $100,000 (the plan's table) -> $50,000 (2026-08-23) -> $100,000
  (2026-08-24) -> $60,000 (2026-08-29), and the horizon went "under 3 years" (the plan's table) ->
  unbounded (owner override, "doesn't really care") -> six months (2026-08-29). See
  `PurposeSpec.seed` and `PurposeSpec.horizon_months_max` for both histories, and note that
  `horizon_years_max` is `None` for this purpose **without meaning unbounded** any more.
* **`roth`** -- $30,000 once, no additions, a long horizon, `roth_ira` tax treatment, and -- uniquely
  among the three -- symbols that must never overlap either of the other two. The $7,500/year
  contribution (the IRS's own annual limit) was removed on 2026-08-29; that allowance is
  use-it-or-lose-it and the cost of giving it up is recorded at `PURPOSE_SPECS`' own entry rather
  than left for a reader to infer from a bare zero.

**The plan document's section 1 table is no longer this module's source of truth for the funding
figures**, though it remains so for everything else. Where the two disagree on an amount, a funding
shape or a horizon, this module and `ACCOUNT-DEPLOYMENT-PLAN.md` section 0 are current and the plan's
table is the historical record of what was originally planned.

`PurposeSpec` carries what each purpose *is*, as data a scorer or a report can read, rather than as a
comment beside the card that trades it. `find_disjointness_violations` enforces the one invariant that
follows from the third bullet above.

**What this module is not.** `backend/app/tax/washsale.py` is the *detective* side of this problem --
it reports, after the fact, exactly how much of a realised loss a replacement purchase disallowed or
destroyed, carefully keeping the ordinary-deferral and IRA-destruction outcomes separate (Rev. Rul.
2008-5; see that module's own docstring for the mechanics). This module is the *preventive* side:
`find_disjointness_violations` exists so a Roth-purpose card and a taxable-purpose card are never
allowed to name the same ticker in the first place, so `washsale.py`'s machinery never has anything to
detect between the two purposes it would be most damaging for it to detect (an IRA replacement destroys
the loss outright, with no basis adjustment anywhere -- see that module's docstring -- which is strictly
worse for the taxpayer than an ordinary wash sale).

**Ticker disjointness is a necessary condition that is cheap to check, not a sufficient one, and this
module does not claim otherwise.** IRC §1091 turns on securities being *substantially identical*, not on
their ticker symbols matching. Two different tickers can already be substantially identical (dual share
classes of the same fund, most plainly) -- and whether two different tickers can be substantially
identical *without* being economically interchangeable is exactly the part that is unsettled: QLD and
QQQ are obviously not the same security, but a 2x leveraged fund tracking the same index as an
unleveraged one is not obviously "not substantially identical" either, and the IRS has never ruled on
ETF pairs of that shape. Ticker equality is mechanical and cheap to check, and this module checks
exactly that; it does not follow that two cards which pass `find_disjointness_violations` carry no
wash-sale risk between them, and nothing here should be read to imply that a roster clearing this check
is safe under §1091 -- only that the one specific, checkable thing this function checks did not fire.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.core.models import Money, TaxTreatment

__all__ = [
    "PURPOSE_SPECS",
    "DisjointnessViolation",
    "FundingShape",
    "Purpose",
    "PurposeSpec",
    "find_disjointness_violations",
    "purpose_spec",
]


class Purpose(StrEnum):
    """Which of three investment goals a strategy card serves. Decides how the card is scored --
    `strategy-program/THREE-PURPOSES-PLAN.md` section 2 measures the gap directly: the same QLD
    strategy through 2006-2011 reports a money-weighted IRR of 10.70% against a time-weighted CAGR of
    2.29%, an 8.4-point spread produced entirely by *when the money arrived*. A card's `purpose` is
    what tells a future scorer which of those two numbers -- or lump-sum `adjusted_excess`, for
    `TRADING` -- is the right one to compute for it.

    Named `Purpose`, not `Mandate` -- `backend/app/paper/mandate.py` already defines `Mandate` as the
    paper desk's capital and risk constraint set (`starting_cash`, `max_positions`, slippage, fees),
    unrelated and load-bearing, and the plan document (section 4) is explicit that the two names must
    never collide.
    """

    SAVINGS = "savings"
    """One lump sum, 10-20 year horizon, taxable, and the safest mandate of the three -- lowest
    drawdown, least return accepted. The largest book since 2026-08-29. Was monthly-contribution
    funded until that date. See `PURPOSE_SPECS[Purpose.SAVINGS]`."""

    TRADING = "trading"
    """One lump sum, taxable, **bounded at nine months** (`PurposeSpec.horizon_months_max`, not
    `horizon_years_max`, which is `None` here without meaning unbounded). Six until 2026-08-30, when
    round 24 found two seated cards could not honour that and the owner widened the bound rather than
    capping them; that field's docstring carries the reasoning. The default every existing card
    already is -- see `PurposeSpec`'s own docstring and each card model's `purpose` field for why."""

    ROTH = "roth"
    """One lump sum, long horizon, tax-free, and the one purpose whose symbols must be disjoint from
    the other two -- see `find_disjointness_violations`. Was annual-contribution funded until
    2026-08-29."""


class FundingShape(StrEnum):
    """How money enters a purpose's book over the life of the account.

    Modelled explicitly, per this package's brief, rather than encoded as a bare `Decimal` next to an
    implicit assumption about cadence. A lump sum, a monthly contribution stream and an annual
    contribution stream are different *questions* for a scoring harness to ask, not three settings of
    one number: `strategy-program/THREE-PURPOSES-PLAN.md` section 2 states plainly that lump-sum
    `adjusted_excess` is the right basis for exactly one of the three purposes and the wrong one for
    the other two, because contribution funding inverts sequence risk relative to a lump sum. A single
    `amount: Money` field could not carry which of those two very different questions is being asked
    of it; this enum is what a caller switches on instead.
    """

    LUMP_SUM = "lump_sum"
    """Deposited once, at inception, and never topped up again -- `TRADING`'s $100,000."""

    MONTHLY_CONTRIBUTION = "monthly_contribution"
    """A `PurposeSpec.seed` at inception, then `PurposeSpec.contribution` added every month
    thereafter -- `SAVINGS`."""

    ANNUAL_CONTRIBUTION = "annual_contribution"
    """A `PurposeSpec.seed` at inception, then `PurposeSpec.contribution` added once a year on top of
    it -- `ROTH`, whose $30,000 paper seed models a starting IRA balance the annual contribution continues
    rather than replaces, at the amount the IRS sets as the annual contribution limit, not a figure
    this module chose."""


class _Frozen(BaseModel):
    """Deliberately a separate definition from `app.tournament.models._Frozen`,
    `app.tournament.allocation._Frozen` and `app.tournament.ladder._Frozen` -- not an import of any of
    them. Importing a private, underscore-prefixed name from one of those modules would tie this
    module's own basic validation behaviour to an implementation detail of a package this module does
    not own and this change is explicitly scoped not to modify (`allocation.py`'s own module docstring
    gives the identical reasoning for why it duplicates rather than imports `models.py`'s `_Frozen`,
    and `ladder.py`'s duplicates it a third time for the same reason). Two lines duplicated on purpose
    cost nothing; a coupling to another package's private name would cost a future reader the ability
    to reason about this file on its own.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class PurposeSpec(_Frozen):
    """Everything a `Purpose` *is*, as data rather than as a comment beside the card that trades it.

    A card's `purpose` field says *which* purpose it serves; `PURPOSE_SPECS` is the lookup that says
    what that purpose actually means -- how it is funded, how long it is meant to run, what tax
    treatment its book lives under, and whether its symbols are load-bearing enough to keep disjoint
    from every other purpose's universe. `strategy-program/THREE-PURPOSES-PLAN.md` section 1's table
    is this class's source of truth; every field below traces to one cell of it.

    Every money field is `app.core.models.Money` (`Decimal`, with `float` rejected at construction --
    see that module's own docstring on why: a `0.1` silently coerced to a binary-float-shaped `Decimal`
    is exactly the class of error that has already compounded into a wrong figure elsewhere in this
    codebase), never a bare `Decimal` and never a `float`, so a purpose's funding numbers are held to
    the identical boundary every other monetary figure in this repository already is.
    """

    purpose: Purpose

    funding_shape: FundingShape
    """How money enters this purpose's book -- see `FundingShape`'s own docstring for why this has to
    be an enum rather than a bare amount next to an implicit cadence assumption."""

    seed: Money
    """The lump sum deposited at inception. Since 2026-08-29 it is also the *entire* funding of every
    purpose, because none of the three receives a recurring `contribution` any more: $100,000 for
    `SAVINGS`, $60,000 for `TRADING`, $30,000 for `ROTH` (a modelled starting IRA balance).

    **This figure has a history, and the history is the reason it is documented rather than just
    stated.** `TRADING` has moved four times -- $100,000 (the plan document's table) -> $50,000
    (2026-08-23) -> $100,000 (2026-08-24) -> $60,000 (2026-08-29). `SAVINGS` moved once and further:
    $20,000 -> $100,000 (2026-08-29). Every one of those is an owner instruction, not a correction of
    another's error.

    **The 2026-08-29 pair changed the ordering, which no earlier change did.** Savings was the
    smallest book and is now the largest; trading was the largest and is now the middle one. Anything
    that assumed "trading is where the money is" -- a default, a docstring, a reader's memory -- is
    wrong from that date. `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 3 is why: the capital
    had been sitting inversely to both the evidence and the tax efficiency, with the largest balance
    in the taxable book that 18 rounds had found no edge for.

    Changing this figure obliges a `_DISK_CACHE_VERSION` bump in `app.paperdesk.desk` -- starting cash
    is in none of that module's cache-key components, and three of its seven versions exist for
    exactly this reason. See that constant's own note."""

    contribution: Money
    """The recurring amount added after `seed`, at the cadence `funding_shape` names.

    **`Decimal(0)` for all three purposes since 2026-08-29**, when the owner removed every ongoing
    contribution. It was $1,000/month for `SAVINGS` and $7,500/year for `ROTH` (the IRS's own annual
    limit) until that date.

    For `ROTH` the zero is a decision with a recurring cost rather than the absence of one: the
    $7,500 annual allowance is use-it-or-lose-it -- a skipped year destroys that year's room instead
    of deferring it -- and `ROTH` is the only one of the three whose gains are never taxed, so it is
    the most valuable contribution room in the system. Flagged to the owner and the instruction
    stood."""

    contribution_variants: tuple[Money, ...] = ()
    """Other contribution amounts this purpose must also be expressible at, alongside `contribution`
    rather than instead of it.

    **Empty for every purpose since 2026-08-29**, because no purpose has a contribution left for a
    variant of. It held `SAVINGS`'s $500/month alternative until then, and
    `strategy-program/THREE-PURPOSES-PLAN.md` section 9 is worth keeping in view in case contributions
    return: "Monthly $1,000 against $500 is a real fork... At a 10-year horizon the contribution
    stream dominates the terminal balance, so a strategy ranked at one rate may not rank at the
    other." `SAVINGS-FAMILY.md` later measured that fork and found it real -- the DIVERSIFIED-PRIMARY
    ranking genuinely flips between the two rates (variant 2's MAR 0.3837 vs SPY's 0.3862 at $1,000;
    0.3922 vs 0.3865 at $500). The field stays for the same reason its enum members do: the owner has
    used contribution funding once and may return to it."""

    horizon_years_min: int | None
    """Shortest horizon this purpose is meant to be judged over, or `None` when no lower bound is
    stated at all. `10` for `SAVINGS`. `None` for `TRADING` -- see `horizon_years_max`'s docstring; the
    owner's correction applies to both ends of the range, not just the upper one. `None` for `ROTH`
    too, for the same "don't invent a number the source document never stated" reasoning
    `horizon_years_max` gives for that purpose -- `0` would be technically true of any horizon and
    would misleadingly suggest a minimum was actually considered."""

    horizon_years_max: int | None
    """Longest horizon, or `None` for a deliberately unbounded one. `SAVINGS` is bounded at `20`.
    `ROTH` is `None`, because the plan's own words for its horizon are "long, and never taxed on the
    way out," with no year count anywhere in the source document -- inventing one here would be a
    number the plan never actually committed to, not a faithful restatement of it.

    **`TRADING` is also `None`, and this is a correction, not the original spec.** Both this document
    and `strategy-program/THREE-PURPOSES-PLAN.md` originally described `trading` as "under 3 years."
    The owner corrected that mid-implementation: "horizon is <> 3yrs doesn't really care." `TRADING`'s
    horizon is therefore modelled here as genuinely absent -- `None` on both ends -- rather than as a
    large number standing in for "no real constraint," because a caller reading `horizon_years_max` and
    finding, say, `99` would reasonably infer a bound the owner explicitly declined to set. `None` here
    means "the owner does not care how long a trading-purpose card runs," not "nobody got around to
    deciding." The plan document itself has not been updated to reflect this correction as of this
    change; that is flagged in this change's own report.

    **Reversed again on 2026-08-29, and `TRADING`'s bound now lives in `horizon_months_max`.** The
    owner bounded the trading horizon at "days up to three months or six months, six months maximum"
    -- see `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 0. `horizon_years_max` stays `None`
    for `TRADING` because six months cannot be expressed in whole years without lying in one of two
    directions: `0` reads as "no horizon," the opposite of a tight bound, and `1` reads as double the
    actual mandate. The bound is carried by `horizon_months_max` instead, and a caller that reads only
    this field must not conclude `TRADING` is unbounded -- read both."""

    horizon_months_max: int | None = None
    """Longest horizon in *months*, for a purpose whose bound is too short to state in whole years.
    `9` for `TRADING`; `None` for `SAVINGS` and `ROTH`, whose horizons are years and are carried by
    `horizon_years_max`.

    A second field rather than a re-typed `horizon_years_max`, because every figure this module
    publishes has a recorded history and rewriting the years field's units would silently
    reinterpret every value already stored against it. The two are not both set on any purpose today;
    a purpose bounded in months has `horizon_years_max=None` and vice versa.

    **6 -> 9 on 2026-08-30, by owner decision, and this is the third position this bound has held.**
    The sequence, because it matters for reading any figure dated against it: originally unbounded
    ("horizon is <> 3yrs doesn't really care"), then `6` on 2026-08-29
    (`strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 0), now `9`.

    **What moved it.** Round 24 (`strategy-program/ROUND-24-PLAN.md`) found that two seated trading
    cards could not honour `6`. `StrategyCard.max_hold_days` counts **sessions**
    (`app.tournament.runner._decide_exit`), so `B3-concentrated` and `B-momentum` at 180 sessions can
    hold roughly **8.6 calendar months**; both were live-holding MRVL from 2026-03-11, eight sessions
    short of the six-month line with 62 still to run. The conflict was real and had two honest fixes:
    cap the cards, or move the bound. Both were put to the owner with the measured cost of the first
    (round 24: **-5.07pp** median adjusted excess on `B3-concentrated`, **-0.19pp** on `B-momentum`,
    both inside the 21.2pp ordering floor). **The owner moved the bound**, and the desk reverted to
    the uncapped cards.

    **`9` rather than `None`, deliberately.** `None` would restore the original unbounded position and
    is what the owner said in the first round of this question -- but it would also erase the horizon
    distinction that is `TRADING`'s whole identity against `SAVINGS` and `ROTH`, both of which are
    long. `9` is the smallest whole month count that admits a 180-session hold, so it resolves the
    contradiction without pretending the book has no horizon at all.

    **This bound has a consequence the scoring layer does not yet honour, and widening it to 9 does
    not fix that.** The trading book's Gate A scores on round 5's five-year and ten-year rungs
    (`app.tournament.selection.RUNGS_5Y`, `RUNGS_10Y`), which a card capped at *nine* months cannot
    satisfy any more than one capped at six -- the failure shape `strategy-program/DEFECTS.md` D5
    describes. Nothing raises when that happens. So `PROTOCOL.md` section 9's **r21 amendment still
    stands on its own premise**: the `trading` purpose has no promotion rule, Gate L and Gate C remain
    floors, and seats there are owner judgment. Only an unbounded horizon would have reopened that,
    which is part of why `9` was chosen over `None`. See
    `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 7 item 3."""

    tax_treatment: TaxTreatment
    """`app.core.models.TaxTreatment` -- `TAXABLE` for `SAVINGS` and `TRADING`, `ROTH_IRA` for `ROTH`.
    Never `TRADITIONAL_IRA`; none of the three purposes `strategy-program/THREE-PURPOSES-PLAN.md`
    section 1 defines uses it."""

    symbols_must_be_disjoint: bool
    """`True` only for `ROTH`. This flag is what `find_disjointness_violations` actually reads to
    decide which cards belong on which side of the check -- it is not merely documentation of the
    invariant, it is the data the invariant is computed from."""

    benchmark: str
    """A key into `app.paperdesk.benchmarks.REGISTRY` -- what this purpose's book is measured against.

    A blend name rather than a symbol, and *always* a blend even when the blend has one leg, so that
    "this book's benchmark" is one type at every use site instead of "a symbol, or else a basket"
    with a branch wherever it is read. `TRADING` names `"spy"`, a single-leg blend that prices to SPY
    exactly.

    **Both non-trading benchmarks changed on 2026-08-29, and for opposite reasons.** Until then
    `SAVINGS` and `ROTH` both named `"60-40-spy-agg"`, chosen when both were contribution-funded
    long-horizon books that wanted something "less aggressive than 100% equity". The owner's reset
    made all three lump sums and pulled the two purposes apart, so one blend can no longer serve both.

    `SAVINGS` now names `"30-70-spy-agg"`. 60/40 was already the *growth* compromise; a book whose
    mandate is the lowest drawdown of the three, explicitly accepting the least return, needs a more
    bond-heavy yardstick or every point of return it deliberately gives up reads as a miss.

    `ROTH` now names `"spy"`, and the reasoning is the part worth keeping. The previous justification
    here -- that the Roth seats a ladder whose base state is a defensive/bond mix, so 100% equity
    would punish it for a risk posture it never takes -- **had the relationship backwards.** A
    benchmark represents the *passive alternative to the mandate*, not a mirror of the strategy's own
    resting allocation; matching the two makes any active strategy look close to its yardstick by
    construction, which is the one thing a yardstick must not do. `ROTH` is the longest-horizon,
    never-taxed, growth-oriented book, so the passive alternative it must beat is the equity market.
    SPY is also the ladder's own `signal_symbol` and its leveraged sleeve (SSO) is a 2x SPY fund, so
    this is an unforced choice rather than an imposed one.

    Both are judgements made here, neither is backtested, and the owner may overrule either --
    `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 7c records them as open decisions.

    A benchmark is priced, never traded, so a blend leg may name a symbol some card also holds --
    including a `ROTH` card's. `symbols_must_be_disjoint` constrains card universes, not the yardstick
    they are measured with."""


PURPOSE_SPECS: Mapping[Purpose, PurposeSpec] = MappingProxyType(
    {
        Purpose.SAVINGS: PurposeSpec(
            purpose=Purpose.SAVINGS,
            # Lump sum since 2026-08-29: the owner removed every ongoing contribution from all three
            # purposes ("let's get rid of extra one thousand dollar per month, anything like that").
            # `FundingShape.MONTHLY_CONTRIBUTION` is retained in the enum -- it is correct, tested,
            # and describes a funding this account used until today -- but no purpose selects it now.
            funding_shape=FundingShape.LUMP_SUM,
            # $100,000 since 2026-08-29, up from $20,000. Savings is now the *largest* of the three
            # books, and the owner's mandate for it is the safest: "keeping the wealth, without the
            # big volatility," explicitly willing to accept the least return of the three. See
            # `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 0.
            seed=Decimal("100000"),
            contribution=Decimal("0"),
            contribution_variants=(),
            horizon_years_min=10,
            horizon_years_max=20,
            tax_treatment=TaxTreatment.TAXABLE,
            symbols_must_be_disjoint=False,
            benchmark="30-70-spy-agg",
        ),
        Purpose.TRADING: PurposeSpec(
            purpose=Purpose.TRADING,
            funding_shape=FundingShape.LUMP_SUM,
            # $60,000 since 2026-08-29. The full history, because this figure has moved four times:
            # $100,000 in the plan document's table, $50,000 on 2026-08-23, back to $100,000 on
            # 2026-08-24, and $60,000 on 2026-08-29 -- all owner instructions. The last move is the
            # only one that changed the *ordering* of the three books: trading is no longer the
            # largest. See `PurposeSpec.seed`'s docstring and
            # `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 0.
            seed=Decimal("60000"),
            contribution=Decimal("0"),
            contribution_variants=(),
            # Bounded in months, carried by `horizon_months_max` below because it cannot be stated
            # in whole years. `horizon_years_max=None` here does NOT mean unbounded -- read both
            # fields. Six months from 2026-08-29; **nine since 2026-08-30**, see that field's
            # docstring for what moved it and what the extra three months do not buy.
            horizon_years_min=None,
            horizon_years_max=None,
            horizon_months_max=9,
            tax_treatment=TaxTreatment.TAXABLE,
            symbols_must_be_disjoint=False,
            benchmark="spy",
        ),
        Purpose.ROTH: PurposeSpec(
            purpose=Purpose.ROTH,
            # Lump sum since 2026-08-29, per the same owner instruction that removed savings'
            # monthly contribution. `FundingShape.ANNUAL_CONTRIBUTION` is retained in the enum but
            # no purpose selects it now.
            funding_shape=FundingShape.LUMP_SUM,
            # $30,000 -- a modelled starting IRA balance for the paper book.
            seed=Decimal("30000"),
            # $0 since 2026-08-29, down from $7,500/year.
            #
            # **This zero is a decision with a recurring cost, not an absence of one, and it must not
            # be read as "there is nothing here."** $7,500 is the IRS annual contribution limit, and
            # it is use-it-or-lose-it: a year skipped does not defer the allowance into a later year,
            # it destroys it. This is also the only one of the three accounts whose gains are never
            # taxed, so the allowance being given up is the most valuable dollar of contribution room
            # in the system. Flagged to the owner on 2026-08-29 and the instruction stood; recorded
            # here so a later reader does not mistake it for an oversight.
            # See `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 0(c).
            contribution=Decimal("0"),
            contribution_variants=(),
            # Both ends `None` -- the plan's own words are "long," with no year count anywhere in the
            # source document (see `PurposeSpec.horizon_years_max`'s own docstring); `0` as a minimum
            # would be technically true of any horizon and would misleadingly suggest a minimum was
            # actually considered.
            horizon_years_min=None,
            horizon_years_max=None,
            tax_treatment=TaxTreatment.ROTH_IRA,
            symbols_must_be_disjoint=True,
            benchmark="spy",
        ),
    }
)
"""Every `Purpose`'s `PurposeSpec`, keyed by the purpose itself. A `MappingProxyType` -- read-only, the
same immutability `_Frozen`'s pydantic models already give each individual `PurposeSpec`, extended to
the collection itself so a caller cannot repoint `PURPOSE_SPECS[Purpose.TRADING]` at a different spec
at runtime and have every other reader silently see the change."""


def purpose_spec(purpose: Purpose) -> PurposeSpec:
    """`PURPOSE_SPECS[purpose]`, as a function -- a call site reads `purpose_spec(card.purpose)` rather
    than reaching into the module-level mapping directly, which is the same indirection this codebase
    already prefers elsewhere for a lookup that might one day need to become more than a dict access
    (a per-owner override, a feature flag) without every caller's syntax changing."""
    return PURPOSE_SPECS[purpose]


# ---------------------------------------------------------------------------
# The disjointness invariant
# ---------------------------------------------------------------------------


@runtime_checkable
class _PurposedCard(Protocol):
    """The three things `find_disjointness_violations` needs from a card, structurally.

    Not an import of `StrategyCard` / `AllocationCard` / `LadderCard` -- this module is imported *by*
    all three of those (each adds a `purpose: Purpose` field sourced from here), so importing any of
    them back would be circular. A `Protocol` says exactly as much as this function actually needs
    (`agent_id`, `purpose`, `universe`) without depending on which concrete model supplies it, and
    `runtime_checkable` is not exercised by this function -- callers pass real card instances, typed
    structurally by a type checker, not `isinstance`-gated at runtime -- but is left on so a caller *can*
    reach for it if a future check ever wants to filter a mixed list defensively.
    """

    @property
    def agent_id(self) -> str: ...

    @property
    def purpose(self) -> Purpose: ...

    @property
    def universe(self) -> tuple[str, ...]: ...


class DisjointnessViolation(_Frozen):
    """One symbol a `roth`-purpose card shares with a `savings`- or `trading`-purpose card's universe.

    Named, not boolean -- a caller (a test, a pre-commit gate, a report) can act on this directly:
    which two cards, which symbol, which purposes. A bare `True`/`False` would leave the reader to grep
    the whole roster for the actual offending pair, which is exactly the information this type exists
    to not discard.
    """

    symbol: str
    roth_agent_id: str
    """`agent_id` of the `roth`-purpose card that trades `symbol`."""
    other_agent_id: str
    """`agent_id` of the `savings`- or `trading`-purpose card that also trades `symbol`."""
    other_purpose: Purpose
    """Always `Purpose.SAVINGS` or `Purpose.TRADING` -- never `Purpose.ROTH` itself, since the check
    only ever compares a roth card against a non-roth one (see `find_disjointness_violations`)."""

    @property
    def message(self) -> str:
        """A single sentence naming the collision, for a log line or a test's own failure message --
        e.g. ``"SPY is traded by roth card 'ladder-1' and trading card 'B-momentum'"``."""
        return (
            f"{self.symbol!r} is traded by roth card {self.roth_agent_id!r} and "
            f"{self.other_purpose.value} card {self.other_agent_id!r}"
        )


def find_disjointness_violations(
    cards: Sequence[_PurposedCard],
) -> tuple[DisjointnessViolation, ...]:
    """Every symbol a `roth`-purpose card shares with a `savings`- or `trading`-purpose card's universe.

    Enforces `strategy-program/THREE-PURPOSES-PLAN.md` section 6's invariant, quoted here in full
    because it is the whole contract this function exists to check: "No symbol traded by a `roth`-
    purpose card may appear in the universe of any `savings`- or `trading`-purpose card." Every roth
    card is compared against every non-roth card in `cards` -- not merely adjacent entries -- because
    the roster this runs over has no ordering with respect to purpose; a savings card submitted before
    a roth one is exactly as much a risk as one submitted after it.

    **Why `.universe`, and why that means a ladder card's `signal_symbol` is never checked here.** All
    three card shapes (`StrategyCard`, `AllocationCard`, `LadderCard`) expose `.universe` as "the
    symbols this card can actually own a position in": a firing `Rung` moves real dollars, a `Sleeve`
    is bought and sold on rebalance, a `StrategyCard.entry`/`.exit` opens and closes a lot -- but
    reading a price to *compute* a signal creates no lot, no cost basis, and critically, no *purchase*
    for Rev. Rul. 2008-5 to destroy the loss on. `backend/app/tax/washsale.py`'s own module docstring
    is explicit that both outcomes it models -- ordinary deferral and IRA-destructive disallowance --
    are triggered by *acquiring* substantially identical securities; neither is triggered by an account
    merely being aware of a symbol's price. A roth-purpose ladder card that reads SPY's drawdown as its
    `signal_symbol` while a taxable card holds SPY outright creates no wash-sale exposure in either
    direction: nothing is ever bought inside the Roth against that ticker, so there is no replacement
    lot for the rule to act on. This is not an oversight in this function -- it is the conservative-in-
    the-right-direction reading of "what could actually cause a disallowed loss," and it is not even a
    decision this function makes on its own: `LadderCard.universe`'s own docstring already excludes
    `signal_symbol` for the identical reason ("read for a signal, never traded"), so checking
    `.universe` uniformly across all three card shapes inherits that boundary rather than redrawing it
    here.

    Returns violations in a stable order: roth cards in `cards`' own order, then -- for each -- the
    other cards sharing a symbol with it in `cards`' own order, then that pair's shared symbols sorted.
    Deterministic output, not because a caller is expected to depend on the exact order, but so a test
    asserting against this function's result does not have to sort it first to make a stable
    comparison.
    """
    roth_cards = [card for card in cards if card.purpose is Purpose.ROTH]
    other_cards = [
        card for card in cards if card.purpose in (Purpose.SAVINGS, Purpose.TRADING)
    ]

    violations: list[DisjointnessViolation] = []
    for roth_card in roth_cards:
        roth_symbols = set(roth_card.universe)
        for other_card in other_cards:
            shared = roth_symbols & set(other_card.universe)
            for symbol in sorted(shared):
                violations.append(
                    DisjointnessViolation(
                        symbol=symbol,
                        roth_agent_id=roth_card.agent_id,
                        other_agent_id=other_card.agent_id,
                        other_purpose=other_card.purpose,
                    )
                )
    return tuple(violations)
