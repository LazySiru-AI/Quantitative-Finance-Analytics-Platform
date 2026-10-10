"""The application's own standing trading mandate -- a code constant, not a UAT persona file.

`app.paperdesk` and `app.tournament.jobs` both need a `Mandate` (cash, position limits, settlement,
slippage, fees) to trade against, and both used to build it by calling
`app.paper.paperbroker.load_mandate` on `uat/personas/pro-investor-01.setup.json` -- a fixture that
belongs to the UAT harness, not to the served application. Reading it here made a production code
path depend on a test persona's file, purely because the two happened to want the same numbers.
`default_mandate` below reproduces those numbers as a Python constant instead, for three reasons:

1. **The persona file's shape does not fit an application default.** `persona_id`, `display_name`
   and `account` name a fictional trader ("Alex Reiner", `uat-taxable`) invented for UAT roleplay --
   meaningless labels for a constraint set the application itself owns and applies unconditionally.
   `default_mandate` gives those fields values that describe what they now are (`desk-default`,
   "Paper desk default"), not who they used to belong to.

2. **A code constant cannot go missing the way a data file can.** `load_mandate` opens a path at
   request time; if that path is wrong, deleted, or simply not shipped with the install (as
   `uat/` never was, once `backend/` became the unit that gets deployed), the failure shows up as a
   `FileNotFoundError` from inside a request handler instead of at import time, or not at all until
   someone happens to hit the code path. A literal `Mandate(...)` in this module either imports
   successfully or the application does not start; there is no third state where it silently reads
   nothing.

3. **The `Decimal("...")` literals below are exact for the same reason `load_mandate`'s string
   parsing is.** See `load_mandate`'s own docstring in `app.paper.paperbroker`: JSON has only binary
   floats, so a bare `10000.00` read out of a data file would arrive as a float and reintroduce
   exactly the imprecision `app.core.models._reject_float` exists to reject downstream, in the
   ledger these fills eventually post to. Writing `Decimal("10000.00")` directly in Python is the
   same discipline applied one layer earlier, with no JSON round-trip in between to undo it.

**This is not a re-tuning of the mandate -- the numbers are the persona's own, verbatim**, read out
of `uat/personas/pro-investor-01.setup.json` at the time this module was written. Every result
committed under `strategy-program/rounds/` was measured against those numbers, so
`tests/test_paper_mandate.py` asserts this module's default equals that file's contents on every
constraint and execution field. If the two are ever meant to diverge -- a deliberate re-tuning of
the desk's own mandate, independent of the UAT persona -- that test will fail, and updating it is
the place that change becomes visible in a diff, rather than a silent drift nobody notices until a
round stops being comparable to the ones before it.

**`max_single_name_weight` here is the persona's real 25% cap, not the loosened 100% the tournament
and the paper desk actually trade under.** Raising it is a *per-caller* decision, made explicitly and
disclosed at the call site via `dataclasses.replace` -- see the long comment in
`backend/app/tournament/__main__.py` on why that loosening happens and why it is disclosed rather
than baked in silently. `default_mandate` states the real constraint; `app.tournament.__main__`,
`app.tournament.jobs` and `app.paperdesk.desk` each loosen it themselves, visibly.
"""

from __future__ import annotations

from decimal import Decimal

from app.paper.paperbroker import Mandate

__all__ = ["default_mandate"]

#: Verbatim from `uat/personas/pro-investor-01.setup.json`'s `capital.starting_cash`.
_STARTING_CASH = Decimal("10000.00")


def default_mandate(*, starting_cash: Decimal | None = None) -> Mandate:
    """The desk's standing constraints: cash, position limits, settlement, slippage, and fees.

    Every constraint and execution field below is copied verbatim from
    `uat/personas/pro-investor-01.setup.json` -- see this module's docstring for why that copy is a
    Python literal rather than a read of the file itself, and `tests/test_paper_mandate.py` for the
    equality assertion that keeps the two from drifting apart unnoticed.

    `starting_cash` is overridable because the two callers of this function do not agree on it:
    `app.paperdesk.desk` runs its live desk on the trading purpose's seed ($50,000, read from
    `app.tournament.purposes.PURPOSE_SPECS` rather than written there), while `app.tournament.jobs` and
    `app.tournament.__main__` run at the persona's own $10,000. Every other field is fixed --
    nothing else here varies by caller.

    `persona_id`/`display_name`/`account_id`/`account_label` are this application's own labels, not
    the UAT persona's ("Alex Reiner", `uat-taxable`) -- see this module's docstring, point 1.
    """
    return Mandate(
        persona_id="desk-default",
        display_name="Paper desk default",
        account_id="paper-desk",
        account_label="Paper desk default",
        starting_cash=starting_cash if starting_cash is not None else _STARTING_CASH,
        allow_fractional_shares=False,
        max_positions=8,
        max_single_name_weight=Decimal("0.25"),
        min_clip_notional=Decimal("500.00"),
        min_cash=Decimal("0.00"),
        settlement_days=1,
        slippage_bps=Decimal("5"),
        commission_per_trade=Decimal("0.00"),
        sec_fee_rate=Decimal("0.0000278"),
        taf_per_share=Decimal("0.000166"),
        taf_cap=Decimal("8.30"),
    )
