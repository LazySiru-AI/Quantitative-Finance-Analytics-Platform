"""`app.paper.mandate.default_mandate` must never silently drift from the UAT persona it was copied
from.

This is not a runtime dependency check -- the served application no longer imports or reads
`uat/personas/pro-investor-01.setup.json` at all, `app.paper.mandate` is a plain code constant (see
that module's docstring for why). What this test protects is an **equality**, and the reason it
matters is `strategy-program/rounds/`: every result committed there was measured with the persona's
own cash, position limits, settlement, slippage and fee numbers. If `default_mandate` is ever
retuned -- deliberately or by accident -- without this test catching it, a newly-run round would be
measured under different rules than the ones already committed, and the two-consecutive-rounds
promotion criterion in `strategy-program/PROTOCOL.md` §6 would silently start comparing measurements
that are no longer comparable. This test makes that impossible to do by accident: change the
mandate's numbers, this test fails, you either revert or update the test, and either way the change
is visible in the diff instead of buried in a result nobody re-checked against the persona.

`persona_id`/`display_name`/`account_id`/`account_label` are deliberately excluded from the
comparison below. Those four fields name a fictional UAT persona ("Alex Reiner", `uat-taxable`) --
genuinely persona-specific labels that the application's own mandate has no business sharing, and
`default_mandate` gives them its own values (`desk-default` / "Paper desk default") instead. Only
the constraint and execution fields -- the actual trading behaviour -- are asserted equal.
"""

from __future__ import annotations

from decimal import Decimal

from app.config import REPO_ROOT
from app.paper.mandate import default_mandate
from app.paper.paperbroker import load_mandate

PERSONA_PATH = REPO_ROOT / "uat" / "personas" / "pro-investor-01.setup.json"

#: Every field that describes actual trading behaviour -- cash, limits, settlement, execution costs.
#: Deliberately excludes `persona_id`, `display_name`, `account_id`, `account_label`: see module
#: docstring.
_BEHAVIOUR_FIELDS = (
    "starting_cash",
    "allow_fractional_shares",
    "max_positions",
    "max_single_name_weight",
    "min_clip_notional",
    "min_cash",
    "settlement_days",
    "slippage_bps",
    "commission_per_trade",
    "sec_fee_rate",
    "taf_per_share",
    "taf_cap",
)


def test_default_mandate_matches_the_persona_on_every_behaviour_field() -> None:
    """`default_mandate()` (no override) must equal `load_mandate(PERSONA_PATH)` field-by-field on
    every constraint and execution value -- the numbers `strategy-program/rounds/` was measured
    against. See the module docstring for why this is an equality assertion, not a smoke test."""
    persona_mandate = load_mandate(PERSONA_PATH)
    app_mandate = default_mandate()

    for field in _BEHAVIOUR_FIELDS:
        assert getattr(app_mandate, field) == getattr(persona_mandate, field), (
            f"default_mandate() has drifted from the persona on {field!r}: "
            f"{getattr(app_mandate, field)!r} != {getattr(persona_mandate, field)!r}"
        )


def test_default_mandate_persona_labels_are_the_applications_own() -> None:
    """The four identity fields are genuinely persona-specific and are *not* asserted equal to the
    UAT persona's -- see module docstring. This test only records that the app's own labels are
    sensible and distinct from the fictional persona's, not that they match it."""
    persona_mandate = load_mandate(PERSONA_PATH)
    app_mandate = default_mandate()

    assert app_mandate.persona_id != persona_mandate.persona_id
    assert app_mandate.display_name != persona_mandate.display_name
    assert app_mandate.account_id != persona_mandate.account_id
    assert app_mandate.account_label != persona_mandate.account_label


def test_default_mandate_starting_cash_is_overridable() -> None:
    """`app.paperdesk.desk` runs its live desk at $100,000, while `app.tournament.jobs` runs at the
    persona's own $10,000 -- both build on the same `default_mandate`, differing only in this one
    override."""
    override = default_mandate(starting_cash=Decimal("100000.00"))
    assert override.starting_cash == Decimal("100000.00")

    default = default_mandate()
    assert default.starting_cash == Decimal("10000.00")


def test_default_mandate_keeps_the_personas_real_single_name_cap() -> None:
    """`default_mandate` must hold the persona's real 25% single-name cap, *not* the 100% some
    callers loosen it to -- that loosening is each caller's own explicit, disclosed
    `dataclasses.replace`, not something baked into the default. See `app.paper.mandate`'s docstring
    and the long comment in `backend/app/tournament/__main__.py`."""
    assert default_mandate().max_single_name_weight == Decimal("0.25")
