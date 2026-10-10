"""Tests for `app.tournament.purposes`: the `Purpose` model, its lookup table, and the roth/taxable
symbol-disjointness invariant.

No broker, no market data, no `settings` fixture -- every test here is a plain pydantic model
construction, following `tests/test_allocation_card.py` and `tests/test_ladder_card.py`'s own house
style of hand-checked, minimal fixtures rather than asserting against whatever the code under test
happens to produce.

* `TestPurposeSpecs` -- `PURPOSE_SPECS` matches `strategy-program/THREE-PURPOSES-PLAN.md` section 1's
  table plus later corrections (trading's lump sum, as revised in the plan document; trading's
  horizon bound; and roth's seed, which the plan document's table did not name -- see `purposes.py`'s own
  docstrings on `PurposeSpec.seed` and `.horizon_years_max` for the detail on each).
* `TestPurposeFieldDefaults` -- `StrategyCard`, `AllocationCard` and `LadderCard` each default
  `purpose` to `Purpose.TRADING` when omitted, and accept an explicit value.
* `TestExistingCardStillLoads` -- a real card JSON already committed to
  `backend/app/paper/library/base/` validates unchanged against `StrategyCard`, with `purpose`
  defaulting to `Purpose.TRADING` even though the file on disk has no `purpose` key at all.
* `TestDisjointnessInvariant` -- a roth card and a trading card sharing a ticker produce exactly one
  named violation; two cards with no overlap produce none; a ladder card's `signal_symbol` alone
  (never in `.universe`) does not trigger a violation even when it collides with a taxable card's
  traded symbol.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.models import TaxTreatment
from app.tournament.allocation import AllocationCard, Sleeve
from app.tournament.ladder import LadderCard, Rung
from app.tournament.models import DESIGN_THROUGH, Discipline, StrategyCard
from app.tournament.purposes import (
    PURPOSE_SPECS,
    DisjointnessViolation,
    FundingShape,
    Purpose,
    PurposeSpec,
    find_disjointness_violations,
    purpose_spec,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Fixtures -- minimal, valid cards of each shape, purpose left as a keyword so a test can override it.
# ---------------------------------------------------------------------------


def _strategy_card(*, agent_id: str, universe: tuple[str, ...], purpose: Purpose | None = None) -> StrategyCard:
    kwargs: dict = dict(
        agent_id=agent_id,
        display_name=agent_id,
        discipline=Discipline.TREND,
        thesis="A minimal thesis, long enough to be a sentence.",
        universe=universe,
        entry="close > 0",
        exit="close < 0",
        max_positions=1,
        position_pct=Decimal("1"),
        designed_through=DESIGN_THROUGH,
    )
    if purpose is not None:
        kwargs["purpose"] = purpose
    return StrategyCard(**kwargs)


def _allocation_card(
    *, agent_id: str, symbols: tuple[str, str], purpose: Purpose | None = None
) -> AllocationCard:
    kwargs: dict = dict(
        agent_id=agent_id,
        display_name=agent_id,
        thesis="A minimal thesis, long enough to be a sentence, and its falsification condition.",
        sleeves=(
            Sleeve(symbol=symbols[0], target_weight=Decimal("0.5")),
            Sleeve(symbol=symbols[1], target_weight=Decimal("0.5")),
        ),
        band_pct=Decimal("0.05"),
        designed_through=DESIGN_THROUGH,
    )
    if purpose is not None:
        kwargs["purpose"] = purpose
    return AllocationCard(**kwargs)


def _ladder_card(
    *,
    agent_id: str,
    signal_symbol: str = "SPY",
    defensive_symbol: str = "SCHD",
    bond_symbol: str = "IEF",
    leveraged_symbol: str = "QLD",
    purpose: Purpose | None = None,
) -> LadderCard:
    kwargs: dict = dict(
        agent_id=agent_id,
        display_name=agent_id,
        thesis="A minimal thesis, long enough to be a sentence.",
        signal_symbol=signal_symbol,
        defensive_symbol=defensive_symbol,
        bond_symbol=bond_symbol,
        leveraged_symbol=leveraged_symbol,
        base_defensive_weight=Decimal("0.6"),
        base_bond_weight=Decimal("0.4"),
        rungs=(Rung(drawdown=Decimal("-0.10"), leveraged_weight=Decimal("0.2")),),
        confirm_ma=3,
        ath_haircut=Decimal("0.5"),
        recovery_gain=Decimal("0.1"),
        recovery_sessions=5,
        designed_through=DESIGN_THROUGH,
    )
    if purpose is not None:
        kwargs["purpose"] = purpose
    return LadderCard(**kwargs)


# ---------------------------------------------------------------------------


class TestPurposeSpecs:
    def test_savings_is_the_largest_book_and_no_longer_contribution_funded(self) -> None:
        """Two changes on 2026-08-29, in one spec. The monthly contribution is gone -- every ongoing
        contribution was removed from all three purposes -- and the seed was raised, which makes
        savings the *largest* of the three books rather than the smallest.

        The pairing is the point: this is now the biggest balance in the system and it carries the
        safest mandate (keeping the wealth, without the big volatility, explicitly willing
        to accept the least return). A spec that showed a small monthly-funded book would describe
        the opposite of both facts. See `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 0."""
        spec = purpose_spec(Purpose.SAVINGS)
        assert spec.funding_shape is FundingShape.LUMP_SUM
        assert spec.seed == Decimal("100000")
        assert spec.contribution == Decimal("0")
        assert spec.contribution_variants == ()
        assert spec.horizon_years_min == 10
        assert spec.horizon_years_max == 20
        assert spec.tax_treatment is TaxTreatment.TAXABLE
        assert spec.symbols_must_be_disjoint is False

    def test_trading_is_bounded_in_months_and_years_max_alone_would_mislead(self) -> None:
        """`seed` has now moved four times. Only the last change altered the *ordering* of the
        books: trading is no longer the largest.

        The horizon is the part worth a test of its own. It was previously unbounded, was bounded at
        six months on 2026-08-29, then widened to nine on 2026-08-30 when round 24 found two seated
        cards holding ~8.6 months and the bound was moved rather than capping them. A month bound is not expressible in whole
        years without lying -- `0` reads as "no horizon" and `1` as too loose -- so `horizon_years_max`
        stays `None` and `horizon_months_max` carries it. **This test asserts both**, because a
        caller reading only the years field would conclude trading is unbounded, which is now the
        opposite of true."""
        spec = purpose_spec(Purpose.TRADING)
        assert spec.funding_shape is FundingShape.LUMP_SUM
        assert spec.seed == Decimal("60000")
        assert spec.contribution == Decimal("0")
        assert spec.contribution_variants == ()
        assert spec.horizon_years_min is None
        assert spec.horizon_years_max is None
        assert spec.horizon_months_max == 9
        assert spec.tax_treatment is TaxTreatment.TAXABLE
        assert spec.symbols_must_be_disjoint is False

    def test_roth_keeps_its_seed_and_gave_up_its_annual_contribution(self) -> None:
        """The seed is an existing IRA balance and is unchanged. The annual contribution
        was removed on 2026-08-29 along with every other ongoing contribution.

        **The zero is asserted deliberately, not incidentally.** The annual contribution is capped at
        the IRS limit and is use-it-or-lose-it: a skipped year destroys that year's allowance rather
        than deferring it, and this is the only account whose gains are never taxed. The cost was
        flagged and the instruction stood. A future reader who finds this zero should find a test that knows
        it is a decision, not an oversight."""
        spec = purpose_spec(Purpose.ROTH)
        assert spec.funding_shape is FundingShape.LUMP_SUM
        assert spec.seed == Decimal("30000")
        assert spec.contribution == Decimal("0")
        assert spec.contribution_variants == ()
        assert spec.horizon_years_min is None
        assert spec.horizon_years_max is None
        assert spec.tax_treatment is TaxTreatment.ROTH_IRA
        assert spec.symbols_must_be_disjoint is True

    def test_each_purpose_names_its_own_benchmark_and_no_two_now_share_one(self) -> None:
        """Which blend a book is measured against decides what "beat the market" means for every card
        in it, so a silent change here silently rescores the whole book. Nothing pinned these until
        2026-08-29: the only assertion that touched a benchmark read it *from the spec*
        (`test_competition_api.py`'s `got["benchmark"] == spec.benchmark`), which passes whatever the
        spec happens to say. This test states the three choices instead.

        `SAVINGS` and `ROTH` shared `"60-40-spy-agg"` until 2026-08-29, chosen when both were
        contribution-funded long-horizon books. The owner's reset pulled them apart in opposite
        directions -- savings toward preservation (`"30-70-spy-agg"`, since 60/40 was already the
        *growth* compromise) and roth toward growth (`"spy"`, because a benchmark is the passive
        alternative to the mandate, not a mirror of the strategy's own resting allocation).

        **Both are judgement calls, not backtested optima**, and the owner may overrule either -- see
        `PurposeSpec.benchmark`'s docstring and `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section
        7c. If one is overruled, this test is the thing that should fail."""
        assert purpose_spec(Purpose.SAVINGS).benchmark == "30-70-spy-agg"
        assert purpose_spec(Purpose.TRADING).benchmark == "spy"
        assert purpose_spec(Purpose.ROTH).benchmark == "spy"

        # Every name must resolve, or a book renders against a benchmark that does not exist.
        from app.paperdesk.benchmarks import REGISTRY

        for spec in PURPOSE_SPECS.values():
            assert spec.benchmark in REGISTRY, f"{spec.purpose} names an unregistered benchmark"

    def test_every_purpose_has_a_spec(self) -> None:
        assert set(PURPOSE_SPECS) == {Purpose.SAVINGS, Purpose.TRADING, Purpose.ROTH}
        for purpose, spec in PURPOSE_SPECS.items():
            assert spec.purpose is purpose

    def test_no_float_leaks_into_a_money_field(self) -> None:
        """`app.core.models.Money` rejects `float` at construction -- confirm `PurposeSpec` actually
        uses that annotation rather than a bare `Decimal` that would silently accept one."""
        with pytest.raises(ValidationError):
            PurposeSpec(
                purpose=Purpose.TRADING,
                funding_shape=FundingShape.LUMP_SUM,
                seed=50000.0,  # float, not Decimal -- must be rejected
                contribution=Decimal("0"),
                horizon_years_min=None,
                horizon_years_max=None,
                tax_treatment=TaxTreatment.TAXABLE,
                symbols_must_be_disjoint=False,
            )


class TestPurposeFieldDefaults:
    def test_strategy_card_defaults_to_trading(self) -> None:
        card = _strategy_card(agent_id="a", universe=("SPY",))
        assert card.purpose is Purpose.TRADING

    def test_strategy_card_accepts_an_explicit_purpose(self) -> None:
        card = _strategy_card(agent_id="a", universe=("SPY",), purpose=Purpose.SAVINGS)
        assert card.purpose is Purpose.SAVINGS

    def test_allocation_card_defaults_to_trading(self) -> None:
        card = _allocation_card(agent_id="a", symbols=("SPY", "IEF"))
        assert card.purpose is Purpose.TRADING

    def test_allocation_card_accepts_an_explicit_purpose(self) -> None:
        card = _allocation_card(agent_id="a", symbols=("SPY", "IEF"), purpose=Purpose.ROTH)
        assert card.purpose is Purpose.ROTH

    def test_ladder_card_defaults_to_trading(self) -> None:
        card = _ladder_card(agent_id="a")
        assert card.purpose is Purpose.TRADING

    def test_ladder_card_accepts_an_explicit_purpose(self) -> None:
        card = _ladder_card(agent_id="a", purpose=Purpose.ROTH)
        assert card.purpose is Purpose.ROTH


class TestExistingCardStillLoads:
    def test_b_momentum_json_validates_unchanged(self) -> None:
        """`backend/app/paper/library/base/B-momentum.json` predates `Purpose` entirely and has no
        `purpose` key. It must still validate against `StrategyCard`, defaulting to `Purpose.TRADING`
        -- the backward-compatibility guarantee this whole change depends on."""
        path = REPO_ROOT / "backend" / "app" / "paper" / "library" / "base" / "B-momentum.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert "purpose" not in raw, "fixture assumption broke: this file now has a purpose key"
        card = StrategyCard.model_validate(raw)
        assert card.purpose is Purpose.TRADING
        assert card.agent_id == "B-momentum"


class TestDisjointnessInvariant:
    def test_no_violations_when_universes_do_not_overlap(self) -> None:
        roth = _strategy_card(agent_id="roth-1", universe=("VTI",), purpose=Purpose.ROTH)
        trading = _strategy_card(agent_id="trading-1", universe=("NVDA",), purpose=Purpose.TRADING)
        assert find_disjointness_violations([roth, trading]) == ()

    def test_catches_a_real_overlap_with_trading(self) -> None:
        roth = _strategy_card(agent_id="roth-1", universe=("SPY", "QLD"), purpose=Purpose.ROTH)
        trading = _strategy_card(agent_id="trading-1", universe=("QLD",), purpose=Purpose.TRADING)
        violations = find_disjointness_violations([roth, trading])
        assert len(violations) == 1
        violation = violations[0]
        assert isinstance(violation, DisjointnessViolation)
        assert violation.symbol == "QLD"
        assert violation.roth_agent_id == "roth-1"
        assert violation.other_agent_id == "trading-1"
        assert violation.other_purpose is Purpose.TRADING
        assert "QLD" in violation.message
        assert "roth-1" in violation.message
        assert "trading-1" in violation.message

    def test_catches_a_real_overlap_with_savings(self) -> None:
        roth = _strategy_card(agent_id="roth-1", universe=("SCHD",), purpose=Purpose.ROTH)
        savings = _strategy_card(agent_id="savings-1", universe=("SCHD",), purpose=Purpose.SAVINGS)
        violations = find_disjointness_violations([roth, savings])
        assert len(violations) == 1
        assert violations[0].other_purpose is Purpose.SAVINGS

    def test_two_taxable_purposes_sharing_a_symbol_is_not_a_violation(self) -> None:
        """Savings and trading are both `taxable` and are allowed to share symbols by design (the
        plan's own section 1 table: "shared pool" for both) -- only roth-vs-taxable is checked."""
        savings = _strategy_card(agent_id="savings-1", universe=("SCHD",), purpose=Purpose.SAVINGS)
        trading = _strategy_card(agent_id="trading-1", universe=("SCHD",), purpose=Purpose.TRADING)
        assert find_disjointness_violations([savings, trading]) == ()

    def test_multiple_roth_cards_and_multiple_symbols_all_named(self) -> None:
        roth = _strategy_card(agent_id="roth-1", universe=("SPY", "QLD", "IEF"), purpose=Purpose.ROTH)
        trading = _strategy_card(agent_id="trading-1", universe=("SPY", "IEF"), purpose=Purpose.TRADING)
        violations = find_disjointness_violations([roth, trading])
        symbols = {v.symbol for v in violations}
        assert symbols == {"SPY", "IEF"}
        assert all(v.roth_agent_id == "roth-1" and v.other_agent_id == "trading-1" for v in violations)

    def test_allocation_and_ladder_cards_are_checked_too(self) -> None:
        """`AllocationCard.universe` and `LadderCard.universe` are computed properties, not a plain
        field -- confirm the check works against both, not only `StrategyCard`'s field."""
        roth_alloc = _allocation_card(agent_id="roth-alloc", symbols=("SCHD", "IEF"), purpose=Purpose.ROTH)
        trading_ladder = _ladder_card(
            agent_id="trading-ladder",
            defensive_symbol="SCHD",
            bond_symbol="TLT",
            leveraged_symbol="QLD",
            purpose=Purpose.TRADING,
        )
        violations = find_disjointness_violations([roth_alloc, trading_ladder])
        assert len(violations) == 1
        assert violations[0].symbol == "SCHD"
        assert violations[0].roth_agent_id == "roth-alloc"
        assert violations[0].other_agent_id == "trading-ladder"

    def test_ladder_signal_symbol_alone_does_not_trigger_a_violation(self) -> None:
        """`LadderCard.universe` deliberately excludes `signal_symbol` (see that property's own
        docstring: "read for a signal, never traded"). A roth ladder reading SPY as its signal while a
        taxable card holds SPY outright must not be flagged -- nothing is ever bought against that
        ticker inside the Roth, so there is no replacement lot for Rev. Rul. 2008-5 to act on (see
        `find_disjointness_violations`'s own docstring for the full argument)."""
        roth_ladder = _ladder_card(
            agent_id="roth-ladder",
            signal_symbol="SPY",
            defensive_symbol="SCHD",
            bond_symbol="IEF",
            leveraged_symbol="QLD",
            purpose=Purpose.ROTH,
        )
        assert "SPY" not in roth_ladder.universe  # fixture assumption this test depends on

        trading_card = _strategy_card(agent_id="trading-spy", universe=("SPY",), purpose=Purpose.TRADING)
        assert find_disjointness_violations([roth_ladder, trading_card]) == ()

    def test_empty_roster_has_no_violations(self) -> None:
        assert find_disjointness_violations([]) == ()

    def test_roth_only_roster_has_no_violations(self) -> None:
        roth_a = _strategy_card(agent_id="roth-a", universe=("QLD",), purpose=Purpose.ROTH)
        roth_b = _strategy_card(agent_id="roth-b", universe=("QLD",), purpose=Purpose.ROTH)
        assert find_disjointness_violations([roth_a, roth_b]) == ()
