"""Compute the live paper desk's state: three books, each a roster of seats started on a common
inception (:data:`INCEPTION`, unless :func:`effective_inception` says an operator moved it) with its
own purpose's seed (:data:`app.tournament.purposes.PURPOSE_SPECS` -- savings $100,000, trading
$60,000, roth $30,000; see :func:`_mandate` and :func:`opening_capital`) and traded forward on this
application's own stored daily bars.

**Three of the four seat shapes are strategy cards; the fourth is not.** A rules card
(:class:`~app.tournament.models.StrategyCard`), a drawdown ladder and an always-invested allocation
are all replayed from stored bars on every request, which is what makes them cacheable and auditable:
the same bars always produce the same book. The **autopilot** seat is the exception and the reason
:mod:`app.paperdesk.autopilot` exists -- it renders the Agent Workflow's own persisted order ledger,
whose entries are model judgements made on the day they were staged and cannot be re-derived from
price history at all. Read :func:`_book` for how the two paths diverge, and note that the roster
therefore holds ids that :func:`_load_card` cannot resolve, by design.

The card roster itself is configurable; see :data:`AGENT_IDS` and :func:`roster` for the default and
for why every seat on it is a hand-authored decision with its reasoning recorded beside it.

**This module reimplements nothing that already exists.** Every session's decision, fill, exit
precedence, bracket timing and position sizing comes from :func:`app.tournament.runner.run_card` --
read that module's docstring in full before reading this one, since every rule stated there (exit
precedence stop > target > time > rule; brackets checked against the *previous* close and filled at
the next open; sizing as a fixed fraction of *starting* equity, never re-levered; no pyramiding)
applies unchanged to a desk here. This module's own job is the smallest thing that is not already
one of those: locate the rostered cards, build the shared mandate, cache one :class:`AgentResult`
per card per trading window -- in memory, and on disk behind it, since a cold run costs seconds per
card -- and reshape that result into the wire types in
:mod:`app.paperdesk.models`.

**"Real-time" means "as of the most recent stored session," nothing more.** There is no live
intraday feed here -- only the daily bars ``/api/market/sync`` pulls in.
:data:`~app.paperdesk.models.PaperDeskState.as_of` and
:data:`~app.paperdesk.models.PaperDeskState.latest_bar` are therefore the same date: the trading
window's ``end`` is the newest stored session for the benchmark, full stop, matching
:data:`app.tournament.models.TRADE_END`'s own convention ("last stored session at the time this
package was built"). An earlier draft of this module stopped one session short of that, reasoning
that "a decision on the newest bar's close has no next-session open to fill against yet" -- true of
a session *dated after* the newest stored bar, which does not exist, but **not** true of the session
dated on the newest stored bar itself. A session is identified by its own fill date, not its decision
date: the session dated ``latest_bar`` is decided on the *prior* stored session's close (via
``Session.decided_on``, always strictly earlier -- see :mod:`app.paper.marketdata`) and filled at
``latest_bar``'s own open, and both of those bars already exist in the store by the time
``latest_bar`` is the newest one. Nothing about trading through it needs a bar that hasn't arrived
yet. Stopping one session early was therefore measuring a different, shorter window than the
tournament and every backtest this desk will be compared against -- not a caution, a bug. See
:func:`_trading_window` below for exactly how the boundary is found, so the window keeps extending
itself as new bars are synced in rather than being hardcoded to any one date.

``stale_days`` (``today - latest_bar``) is the honest "how far behind the calendar is this mark"
figure the page warns on: how far behind the real wall clock the stored data itself is, independent
of trading-window bookkeeping.

**The persona's 25% single-name cap is loosened to 100%, and that loosening is disclosed, not
silent.** ``app.tournament.__main__`` documents the same choice for the tournament proper: five
submitted cards specify a position size the persona's mandate would refuse outright
(``position_pct x max_positions`` alone is checked by ``StrategyCard``; the mandate's own
``max_single_name_weight`` is a separate, stricter rule ``StrategyCard`` never sees). Both
``B-momentum`` (15% x 6 = 90%) and ``C-trend`` (18% x 5 = 90%) fit under the persona's real cap
individually per-position, but the mandate's weight check is evaluated against the *book*, not the
card in isolation -- see ``app.paper.paperbroker.PaperBroker._check_buy``'s ``max_single_name_weight``
branch -- so raising it here keeps this desk's behaviour identical to the tournament's own reported
numbers rather than quietly running a different, stricter mandate the cards were never measured
against. See :func:`_mandate` below and :attr:`~app.paperdesk.models.PaperDeskState.notes`.

**"decisions" is reconstructed from fills, not a deliberation trace.** ``run_card`` does not record
a per-session "did I look at this and pass" log -- only orders that were actually submitted (and
either filled or rejected) exist anywhere in its output. :func:`_decisions` below turns each
:class:`~app.tournament.models.RealisedTrade` into one ``enter`` and (if closed) one ``exit`` row.
Inventing a denser log -- one row per session per symbol, most of them "no signal" -- would
misrepresent what this application actually recorded as having happened. :func:`_signals` is what
covers "what is the strategy thinking right now": every universe symbol's entry/exit rule truth
value against the newest stored close (``as_of``) -- the *next* decision, not the last one; a
trader reads the rules against today's close and the resulting order fills at the following
session's open, which has not happened yet. Evaluated fresh here (parsing with
``app.rules.grammar.parse`` and walking with ``app.rules.evaluate``, the same two calls
``run_card``'s own ``_rule_fires`` makes) rather than replayed from the trade log, since a symbol
that never fired an order still has a current rule state worth showing. The list comes back in
the engine's own entry order, ranked by the card's ``rank_by`` key where it sets one -- see
:func:`_signals`. This also means a held
symbol's :attr:`~app.paperdesk.models.Signal.last_close` always equals its
:attr:`~app.paperdesk.models.Holding.last_price` -- both are marked to the same date -- which is the
invariant an earlier version of this function got wrong by evaluating one session too early.

**Holdings are marked fresh, not read off ``RealisedTrade.pnl``.** An ``open_at_end`` trade's
``pnl``/``return_pct`` are net of the entry commission (see ``run_card._open_at_end_trade``), which
is correct for that field but does not, by construction, satisfy ``cost_basis + pnl == price *
quantity`` -- the commission is exactly the gap. Holding.market_value/unrealised_pnl are computed
here straight from a fresh close (the same date and the same store ``run_card`` used to mark
``AgentResult.ending_equity``), so ``equity == cash + positions_value`` holds to the cent and
``cash`` (which ``AgentResult`` does not expose directly, only the combined ``ending_equity``) is
recovered as the difference -- see :func:`_build_desk`.

**In-process result cache, keyed on ``(agent_id, start, end, latest_bar)``.** Twelve sessions runs
in well under a second, but a page load must not pay that cost on every request; see :func:`state`
and :func:`refresh`.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import re
import threading
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

from app.config import Settings, get_settings
from app.core.models import TaxTreatment
from app.evolution.models import PromotionRecord, roster_overlay_path
from app.evolution.promotion import load_promotions
from app.market import store
from app.market.live import LiveQuoteSource, build_source
from app.market.models import Interval
from app.paper.mandate import default_mandate
from app.paper.marketdata import AsOfMarket, SessionCalendar, UnpricedSymbol
from app.paper.paperbroker import Fill, Mandate, Order, PaperBroker, rejection_label
from app.paper.papertax import PaperTaxSummary, resolve_configured_rates, summarize_paper_tax
from app.paperdesk import autopilot as autopilot_mod
from app.paperdesk.benchmarks import REGISTRY as BLEND_REGISTRY
from app.paperdesk.benchmarks import InsufficientHistory, price_blend, price_equal_weight_basket
from app.paperdesk.models import (
    Benchmark,
    Book,
    Decision,
    Desk,
    DeskRejection,
    Funding,
    Holding,
    LadderDescription,
    LadderRungDescription,
    LiveFill,
    PaperDeskState,
    SeatProvenance,
    Signal,
    Trade,
)
from app.rules import evaluate as rule_evaluate
from app.rules import grammar
from app.rules.nodes import BoolExpr, NumExpr
from app.tournament.allocation import AllocationCard, AllocationResult, run_allocation
from app.tournament.ladder import LadderCard, LadderResult, run_ladder_card
from app.tournament.models import (
    DESIGN_THROUGH,
    AgentResult,
    RealisedTrade,
    RejectionRecord,
    StrategyCard,
)
from app.tournament.purposes import PURPOSE_SPECS, FundingShape, Purpose, PurposeSpec
from app.tournament.runner import (
    _build_rank_table,
    _entry_quantity,
    _ordered_entry_candidates,
    run_card,
)

__all__ = [
    "AGENT_IDS",
    "AUTOPILOT_AGENT_ID",
    "INCEPTION",
    "InceptionRejected",
    "clear_cache",
    "clear_disk_cache",
    "clear_inception",
    "effective_inception",
    "inception_override_path",
    "refresh",
    "roster",
    "rosters",
    "seats",
    "set_inception",
    "state",
    "universe_symbols",
    "warm",
]

logger = logging.getLogger(__name__)

#: Re-exported from :mod:`app.paperdesk.autopilot` so a caller that only imports this module can name
#: the autopilot seat without reaching past it -- the same courtesy `AGENT_IDS` already does for the
#: card roster. The definition stays in that module, next to the code that knows which arm and which
#: universe the seat reads, because that is the decision the id belongs to.
AUTOPILOT_AGENT_ID = autopilot_mod.AUTOPILOT_AGENT_ID

#: The strategies this desk trades *by default*, when `Settings.paperdesk_agent_ids` is unset.
#: Order here is the order they appear in the response's ``desks`` list.
#:
#: **Set by round 11** (`data/rounds/r11-2026-08/SELECTION.md`), which implements "fix 4" -- the
#: recommendation standing open since round 6 and repeated by every round since: **score the live
#: desk's own record and weight it above the backtests.** Round 10 is where its absence stopped being
#: a footnote. Gate S' dropped `A-rotation` on backtest rank dispersion while a 127-session live
#: record said the opposite, the owner overrode the rule to keep it, and that was the second override
#: in three rounds -- both times the rule ranked on backtests and the owner weighted the live record,
#: which no gate could see.
#:
#: * **Gates A and L (unchanged) are now explicitly floors.** Gate A: positive median annualized
#:   adjusted excess at round 5's 5y and 10y rungs against both SPY and QQQ. Gate L: traded in the
#:   out-of-sample window and either holding now or having traded within 60 sessions. Their job is
#:   "the long-horizon backtest does not call this card broken"; neither ranks anything any more.
#: * **Gate S' stops eliminating and becomes a tie-break.** Its dispersion number is still computed
#:   and reported for every card. Under fix 4 the live record is the senior evidence, so backtest
#:   stability decides between cards the live record cannot separate -- which, this round, is exactly
#:   what it did.
#: * **Gate C (new).** Positive `adjusted_excess` in at least 3 of the 6 live sub-periods, so
#:   promoting the live record cannot collapse into promoting one good month.
#: * **Ranking (new, primary): the live matrix.** Median `adjusted_excess` across six contiguous
#:   sub-periods of 2026-02-17 to 2026-08-18. Tie-breaks: live hit rate, then Gate S' range, then
#:   Gate A's 10y QQQ median.
#: * **Distinctness and the seat count are unchanged** from round 10 -- one card per discipline and
#:   per base family, seats an output capped at four with no floor.
#:
#: **Three seats.** `B3-concentrated` (live median +7.41%, 4/6 sub-periods positive),
#: `A-rotation` (+3.47%, 4/6) and `C-trend` (+1.81%, 3/6). `H-trend-diversified` is the one card
#: Gate C removes, at 1/6.
#:
#: **`B-momentum` leaves the desk, and it is worth knowing why.** It clears every gate and ranks
#: second on the live matrix (+4.82%, 3/6) -- but `B3-concentrated` is the same base family and
#: outranks it, so distinctness seats one. `B-momentum` was the card round 8's owner override seated
#: over `B3-concentrated`; **the live record reverses that override**, while seating `A-rotation` on
#: the rule and thereby vindicating round 10's. Fix 4 split the two rather than ratifying both, which
#: is the strongest available evidence that the rule is reading the record rather than the owner
#: (`SELECTION.md` section 5).
#:
#: **The first attempt at this matrix was invalid and was thrown away** -- `strategy-program/
#: DEFECTS.md` D5. Six *independent* sub-window runs reset the book at every boundary, so a card that
#: entered in March and held into August was forced to liquidate and re-enter six times; `B-momentum`
#: showed 0.0% exposure in two whole sub-windows while fully invested. The runs are now cumulative
#: from one fixed start and differenced, which preserves position continuity. No threshold, gate or
#: boundary moved, and the correction moved the result *away* from the convenient answer: the broken
#: matrix seated `A-rotation` alone.
#:
#: **Owner override, 2026-08-22: `B-momentum` is back, seated beside `B3-concentrated`**
#: (`data/rounds/r11-2026-08/SELECTION.md` section 8). Round 11's ranking is unchanged and
#: `B3-concentrated` still wins the momentum seat on it; this is a *fifth* seat added against the
#: distinctness rule, not a reversal of the rank.
#:
#: **This override is a different shape from the previous two, and the difference is the whole
#: argument for it.** Rounds 8 and 10 were overridden on *which card is better* -- a disagreement
#: about evidence. This one is not: nobody disputes that `B3-concentrated` outranks `B-momentum` on
#: the live record. What is being overridden is **distinctness**, the rule that at most one card per
#: base family may be seated, which exists so the desk does not show one idea twice.
#:
#: It shows one idea at two breadths, and the holdings say so exactly. As of 2026-08-18
#: `B3-concentrated` holds MRVL, TSM, AMD, MSFT and `B-momentum` holds those same four **plus AMZN
#: and NVDA** -- a strict subset, 4 of 6 names, not an overlap that happens to be large. So the
#: second panel is not a redundant copy: it is the same entry and exit rules run at six slots of 15%
#: instead of four of 22%, and what a reader sees by having both is precisely **which names survive
#: the tighter slot count**. For a desk whose purpose is "what is this thing buying", that is a legible
#: comparison rather than a duplicated signal.
#:
#: The cost is real and is not waved away: a reader skimming five panels will see two that agree
#: almost entirely, and the equal visual weight overstates how much independent evidence is on the
#: page. Four of the five panels are now momentum-or-semis-shaped.
#:
#: **What this evidence cannot do**, restated wherever the roster is read: six contiguous sub-periods
#: of one period are not six regime draws. They are one market environment cut into pieces. The three
#: backtest matrices -- a GFC, a COVID crash, two chop regimes, a decade of bull market, 27 horizon
#: windows -- are where regime coverage lived, and this rule weights six months of 2026 above all of
#: it. That is fix 4's whole content and it is a trade, not an upgrade.
#:
#: **Round 24 found this roster in breach of its own account, and the breach was resolved by moving
#: the mandate rather than the cards.** The tuple below is therefore unchanged from round 11 plus the
#: owner override -- but it was briefly not, and the reason it is back is worth reading before anyone
#: re-derives the same finding.
#:
#: **What was wrong.** `PurposeSpec.horizon_months_max` bounded the trading book at **six months**.
#: `StrategyCard.max_hold_days` is counted in **sessions** (`app.tournament.runner._decide_exit`:
#: `held = session.index - lot.entry_session_index`), so `B3-concentrated` and `B-momentum` at 180
#: sessions can hold roughly **8.6 calendar months** -- 2.6 months past that mandate. Not
#: hypothetical: at `as_of` 2026-08-28 both held MRVL entered 2026-03-11, **118 sessions, eight short
#: of the six-month line**, with 62 still to run before their own time stop would fire. Nothing in the
#: engine would have stopped it, because `horizon_months_max` is **declarative** -- no runner check,
#: no card validation, no gate reads it.
#:
#: **What the alternative would have cost, measured rather than argued** (round 24, cards frozen at
#: `9dcd283` before any run, `data/rounds/r24-2026-08/scorecard-r2.json`). Six-month variants were
#: built -- each its base with **one** field changed, `max_hold_days` 180 -> 126, `PROTOCOL.md`
#: section 7's one-decision rule -- and run over the r2 regime matrix. Median adjusted excess:
#: `B3-concentrated` +13.89% -> +8.82% (**-5.07pp**), `B-momentum` +12.16% -> +11.97% (**-0.19pp**).
#: Both **inside the 21.2pp ordering floor**. Five of six windows were byte-identical; the entire cost
#: sat in `chop-2015`, a directionless market where a position runs on without triggering a trend
#: break and only a clock gets it out.
#:
#: **Both variants were seated on 2026-08-30 (`a81fcb6`) and reverted the same day, by owner
#: decision: `horizon_months_max` moved 6 -> 9 instead.** Nine is the smallest whole month count that
#: admits a 180-session hold. The cards are unchanged and remain the forms every figure in rounds 1-23
#: was measured on. `B3-concentrated-cap126` and `B-momentum-cap126` stay in `library/variants/`
#: unseated -- they are real, pre-registered, measured variants and round 24's second arm is the
#: evidence for them; deleting them would erase that.
#:
#: **An earlier version of this note claimed the measurement refuted the card's own thesis. It does
#: not, and the claim is withdrawn** (`ROUND-24-PLAN.md` section 11, raised by review). The thesis's
#: two "capped variants" are a **take-profit** ("capping gains at 8-30%") and a **fast 20-day-EMA
#: exit**; its "roughly triple" figure compares those against an uncapped arm defined as "a stop, a
#: 200-day trend-break, **or a 180-day backstop**". The 180-session hold is therefore *part of the arm
#: the author prefers*, not one of the variants being criticised. Moving it 180 -> 126 shortened the
#: preferred arm and built neither variant the claim is about, so **the "roughly triple" claim remains
#: untested** and nothing here bears on it. The measurement itself -- -5.07pp and -0.19pp, inside the
#: floor, confined to `chop-2015` -- is unaffected, and was always the only thing this roster note
#: needed.
#:
#: **The live arm of that round was inert and is not evidence either way.** On the r11 live matrix
#: both variants reproduced their bases byte for byte with zero time-stop exits, because the cap binds
#: in September and that window ends 2026-08-18. `ROUND-24-PLAN.md` section 8 records the
#: pre-registration error that predicted otherwise.
#:
#: **What the wider bound does not change.** Gate A scores on round 5's five-year and ten-year rungs,
#: which a nine-month card cannot satisfy any more than a six-month one -- so section 9's **r21
#: amendment still stands on its own premise**: the `trading` purpose has no promotion rule, Gate L
#: and Gate C remain floors, and seats here are owner judgment. Nothing below was promoted.
AGENT_IDS: tuple[str, ...] = (
    "B3-concentrated",
    "A-rotation",
    "C-trend",
    "B-momentum",
    "I-13f-duquesne-2026q2",
    "r40-rsi-confirm-slots6",
)
"""**`I-13f-duquesne-2026q2` was seated on 2026-08-30 by owner decision, and it is the first card on
this desk that no gate has ever ranked.**

**`r40-rsi-confirm-slots6` was seated on 2026-09-09 by owner decision, also on no gate.** Round 40's
sole positive cell (arm-minus-control +4.82pp median adjusted excess), from the persona
confirmation-conjunct round -- a margin inside the 21.2pp noise floor, so round 40's own rule says the
conjunct does not pay for itself. It is here by direction, under observation, and it carries a
**-17.2pp worst window** (its higher-median 3-slot sibling's is -30.7pp, which is why the milder
6-slot variant was the one promoted). `PROTOCOL.md` section 9 and `data/rounds/r40-2026-09/REPORT.md`
record both the promotion to `candidates/` and this seat. §6's promotion rule does not apply to the
`trading` purpose (the r21 amendment makes trading seating owner judgment), so this seat rests on that
judgment plus the desk's liveness floors, exactly as `I-13f-duquesne-2026q2` does.

Recorded plainly, the way rounds 8, 10 and 11's overrides
are recorded below, because the difference between "seated on the rule" and "seated by decision" is
the only thing that keeps this roster readable.

It is the first `desk_only` card (`app.tournament.models.StrategyCard.desk_only`). Its
`designed_through` is 2026-08-14 -- the date Duquesne Family Office's quarter-ending-2026-06-30 13F
became public -- which is after the tournament's design cutoff and one day before
:data:`INCEPTION`. It therefore **cannot** be run in a round, ranked against Gate A, L, S' or C, or
compared on the live matrix with the four cards above, all of which carry three backtest matrices
behind them. `app.tournament.jobs._resolve_cards` refuses it by construction. What this desk shows
for it is one forward window and nothing else.

**Why seat something with no backtest at all.** The card's whole point is a property no backtested
card can have: a 13F basket whose trading window begins *after* the filing it was derived from.
`strategy-program/CONSTRAINTS.md` names that as the one information-timing rule enforced by
discipline rather than by code, and the three 13F cards in the prior tournament that broke it were
run over windows two years of which predated their own documents. This one satisfies it -- by an
accident of the calendar, inception falling one day after the filing date, not by any cleverness --
and satisfying it is only possible going forward, never retrospectively. A backtest of this card is
not a thing that can be built.

**What that costs the reader, stated rather than assumed away.** Five panels now, of which four are
momentum-or-semis-shaped and the fifth is a mega-cap-tech basket, so the desk is *more* concentrated
in one theme than the paragraph below already warns it is. And a card with one forward window beside
four cards with a decade of matrices behind them will render at equal visual weight while carrying
far less evidence. Neither is a reason not to seat it; both are reasons to read the panel as a live
experiment rather than as a result.

**`ladder-qld-schd` was unseated on 2026-08-30: its measured horizon is up to 62.5 months on a
book bounded at 9.** It had held the fifth seat since round 6 as an independent reference signal --
not a `StrategyCard`, never run through Gate A, L, S' or C, selected by direct analysis
(`strategy-program/DRAWDOWN-LADDER.md`) rather than by the competition above. None of that changed.
What changed is that the horizon question finally got asked of it.

**Why it was never caught before.** A `LadderCard` has **no `max_hold_days` field** -- it never goes
to cash, it re-weights sleeves -- so there is nothing in the type system for a horizon check to read,
and `horizon_months_max` is declarative anyway (no runner check, no validation, no gate). The card was
not violating a rule the engine enforces; it was outside a mandate nothing had measured it against.
`strategy-program/tools/ladder_horizon.py` is that measurement, and it derives every figure from
`RealisedTrade.entry_date`/`.exit_date` in the real engine's own trade log rather than replicating the
arming state machine, because a hand-rolled copy would measure the copy.

**What it measured** (`data/rounds/r24-2026-08/ladder-horizon.json`, 2006-07 .. 2026-08, the longest
window `QLD`'s first bar 2006-06-20 allows). Twelve armed cycles. Nine sit inside nine months, at 3.2
to 6.7. The two that matter do not: **2022-07-22 -> 2024-04-17 is 20.9 months, and 2008-03-25 ->
2013-06-11 is 62.5** -- the ladder bought leverage into the GFC and stayed committed for five years.
That is the strategy working exactly as designed, and it is not a days-to-nine-months instrument.

**There is no other book it can legally sit on, which is the part worth recording.** Its natural home
is a long-horizon book, and both are closed:

* **`ROTH`** -- blocked by the disjointness invariant (`purposes.find_disjointness_violations`).
  `SCHD` is a sleeve of the seated *savings* card, which is taxable. This is exactly why
  `ladder-sso-vig-bnd` exists as a substitute, at a measured cost of -1.72pp CAGR
  (`strategy-program/ROTH-DISJOINT-LADDER.md`).
* **`SAVINGS`** -- blocked by that book's mandate. `qld-schd-sgov` was dropped from it on 2026-08-29
  on a measurement (-34.9% max drawdown against the seated card's -16.8%) for holding `QLD`. Seating
  a different `QLD` ladder there would reverse that decision.

**The control that makes this a horizon finding rather than a ladder finding:** `ladder-sso-vig-bnd`
runs the identical state machine and posts an identical **62.6-month** longest stretch -- and stays
seated, because `ROTH`'s `horizon_months_max` is `None` and a long book is where this shape belongs.
Same instrument, legal in one book and not the other, purely on horizon.

**Unseated, not retired.** The card stays in `library/ladder/`, unedited, and every figure it has ever
produced stands. If a long-horizon book can legally take it -- a Roth whose taxable sibling drops
`SCHD`, say -- it goes straight back with no re-derivation needed.

**What this costs the page, stated because it is a real loss.** The trading book drops to four panels,
all rules cards, all momentum-or-semiconductor shaped. It loses its only low-drawdown reference
(-3.91% live, against -20% to -30% for the rules cards) and its only panel that is not a
concentrated equity book -- on a page whose stated job is showing what each strategy would buy."""

#: The savings book's roster: allocation cards, which are always-invested sleeve portfolios
#: rebalanced on drift bands rather than rules that go to cash. Empty is a legal value -- a purpose
#: can be funded and defined before a card exists for it, and the page renders that as an empty book
#: rather than hiding the purpose.
#: `qld-schd-sgov` was removed on 2026-08-29, when the savings purpose became the owner's safest book
#: -- $100,000, lowest drawdown, explicitly willing to accept the least return of the three. A 2x
#: leveraged Nasdaq sleeve does not serve that mandate, and the removal is backed by a measurement
#: rather than by the argument from leverage alone, because the card had **never** been run on the
#: lump-sum basis: `ALLOCATION-FAMILY.md` excludes leveraged funds from that family by design, so no
#: CAGR/maxDD/MAR figure for it existed anywhere.
#:
#: Measured over the only window its real sleeves reach (2020-06-01 .. 2026-08-21; SGOV's first bar is
#: 2020-05-31, which is *after* the COVID crash, so neither that nor the GFC is reachable natively):
#: in the 2022 bear its max drawdown was **-34.9% against the seated card's -16.8%** -- essentially
#: naked QQQ buy-and-hold's -34.6%, despite the card nominally holding only 35-43% QLD. On a
#: SPY-for-SCHD/BIL-for-SGOV proxy reaching 2007-2026 the gap widens: GFC **-61.6% vs -32.6%**, COVID
#: **-33.5% vs -20.2%**. MAR 0.49 against the seated card's 0.57 over the common window.
#:
#: **Its own tilt made it worse than a static blend of its own three sleeves** (-34.9% vs -32.0% in
#: 2022): the buy-low/trim-high rule re-bought QLD into a sustained downtrend, which is the exact
#: regime the card's own thesis names as its falsification condition.
#:
#: The card's CAGR is the higher one (17.4% vs 9.7% over 2020-2026) and that is not a counter-argument
#: under a mandate that deprioritises return -- but the sharper point is that **the known biases cannot
#: rescue it**. "Cash earns nothing" understates this card more than the seated one (SGOV is 25% of the
#: book against BIL's 10%, and T-bills paid 4.5-5.3% post-2022), so its true return gap is *smaller*
#: than measured -- and both that bias and "no dividends" touch only the return side. Drawdown and
#: volatility come straight off price paths that already embed QLD's real daily-reset decay, so no
#: bias here narrows the drawdown gap, which is the axis the mandate actually turns on.
SAVINGS_AGENT_IDS: tuple[str, ...] = ("spy-schd-agg-gld-bil-atr-tilt",)

#: The Roth book's roster. Every card here must stay ticker-disjoint from both taxable books --
#: `app.tournament.purposes.find_disjointness_violations` is what enforces that, and
#: `tests/test_purposes.py` is where it fires. `ladder-sso-vig-bnd` exists precisely as the
#: Roth-safe expression of the same drawdown ladder the trading book runs on QLD/SCHD/IEF; see
#: `strategy-program/ROTH-DISJOINT-LADDER.md`.
#:
#: **`r34-ma-crossover-on` was seated on 2026-09-09 by owner decision, on no gate.** Recorded the way
#: `I-13f-duquesne-2026q2`'s seat is recorded on `AGENT_IDS` above, because "seated on the rule" and
#: "seated by decision" must stay distinguishable. It is the best cell of the disjoint sector family
#: (`strategy-program/DISJOINT-SECTOR-FAMILY.md`, rounds 34-36, all three null): a 10/30 EMA crossover
#: inside a 200-day filter on eight industry ETFs (`XME XRT XHB XSD XOP XBI ITA VNQ`), median adjusted
#: excess +1.24pp across the eight-window matrix, hit rate 5 of 8, worst window -9.95pp -- a margin
#: inside the 21.2pp floor by a factor of seventeen, from a round whose own plan said nothing would be
#: promoted. `PROTOCOL.md` section 9 records the directed promotion to `candidates/`; this line
#: records the directed seat. It is the first rules card on this book (the ladder is an
#: `AllocationCard`-shaped `LadderCard`), so the Roth book now runs both card shapes.
ROTH_AGENT_IDS: tuple[str, ...] = ("ladder-sso-vig-bnd", "r34-ma-crossover-on")

#: What each book is called on the page. The owner's own words for these accounts, not the enum
#: values: a reader recognises "Roth IRA", not `roth`. Held here rather than on `PurposeSpec` because
#: it is presentation -- `app.tournament.purposes` is read by scorers that have no page to render.
_BOOK_LABELS: dict[Purpose, str] = {
    Purpose.SAVINGS: "Savings",
    Purpose.TRADING: "Trading",
    Purpose.ROTH: "Roth IRA",
}

#: The library subdirectory holding `AllocationCard` JSON, searched by content the way
#: :data:`_LADDER_TIER` is. Named here rather than inlined so the two tiers read alike.
_ALLOCATION_TIER = "allocation"

INCEPTION: dt.date = dt.date(2026, 8, 15)
"""The desk's own **default** inception -- unrelated to ``app.tournament.models.TRADE_START``, which
is a different (earlier, longer) window built for the tournament comparison. This package trades its
own forward window starting here, unless an operator has set a runtime override (see
:func:`effective_inception`, :func:`set_inception`) -- this constant stays the fallback and the named
value every override is relative to, so the record below of why it moved, and what moving it cost,
keeps meaning what it always meant.

**Moved from 2026-01-01 to 2026-08-15 by owner decision, restarting the forward record.** The desk
is being restructured onto three real funding purposes with real amounts
(`strategy-program/THREE-PURPOSES-PLAN.md`), and a return produced under the old arrangement -- one
flat $100,000 per card from January -- answers a question nobody is asking any more. Restarting is
the honest option; carrying the old curve forward under new rules would produce a number whose
meaning changed halfway along it.

**The cost, stated here because it is easy to miss and impossible to undo:** 2026-08-15 is a
Saturday, so the first session is 2026-08-17, and against a latest stored bar of 2026-08-21 that is
**five sessions**. A return over five sessions is noise. **The desk is not evidence about anything
for months**, and any figure read off it before roughly the turn of the year says more about one
week's tape than about any strategy.

**What this does not touch is the competition.** Rounds 11 and 12 measure the out-of-sample window
2026-02-17 to 2026-08-18, written as literal dates derived from the design cutoff, not from this
constant. Every gate, ranking, novelty and selection figure in those rounds is unaffected by moving
inception, and no round document needs revisiting.

The previous arrangement, kept for the record: inception was 2026-01-01, which straddled the
``designed_through = 2026-02-13`` design cutoff -- the first ~30 sessions were in-sample and only
2026-02-16 onward was a genuine forward test. `data/rounds/r7-2026-08/SELECTION.md` and the
published report split the two, because a headline return that silently blends fitted and unfitted
periods is exactly the kind of number this programme exists to catch. **The new inception is
entirely after the cutoff**, so that particular hazard is gone -- replaced by the much simpler one
of having almost no data."""


def roster(settings: Settings) -> tuple[str, ...]:
    """The agent ids this desk trades, in the order they appear in the response.

    ``settings.paperdesk_agent_ids`` wins when set; ``AGENT_IDS`` above is the fallback -- see that
    constant's own docstring for why the default lives there rather than being copied into
    ``Settings`` as a second literal. Every call site that used to read ``AGENT_IDS`` directly reads
    this function instead, so the roster is a runtime configuration value everywhere in this module
    except in the one place (this function) that knows what to fall back to.

    Validated here, not left to surface as a downstream ``KeyError`` or an empty page: a roster of
    zero cards would render a desk with nothing on it and no indication anything is wrong, and a
    repeated agent id would render as the same card twice with no indication *that* is wrong either.
    Both are rejected up front. What is deliberately **not** checked here is whether each id actually
    resolves to a card in the library -- that check already exists, in :func:`_find_card`, and
    happens naturally the first time this roster is walked in :func:`_compute`. Duplicating it here
    would mean two places doing the same filesystem lookup and, worse, two slightly different error
    messages for the same failure.
    """
    ids = settings.paperdesk_agent_ids if settings.paperdesk_agent_ids is not None else AGENT_IDS
    if not ids:
        raise ValueError(
            "paperdesk roster is empty -- app.paperdesk.desk needs at least one agent id to trade. "
            "This should already have been rejected by Settings.paperdesk_agent_ids's own validator; "
            "seeing it here means AGENT_IDS itself was edited down to nothing."
        )
    seen: set[str] = set()
    for agent_id in ids:
        if agent_id in seen:
            raise ValueError(
                f"paperdesk roster names {agent_id!r} more than once ({ids!r}) -- each agent id "
                "must appear at most once, or the response would carry the same card's numbers "
                "twice under one agent id with nothing on the page to say so."
            )
        seen.add(agent_id)
    return ids


def _overlay_agent_ids(
    settings: Settings, purpose: Purpose, *, already: tuple[str, ...]
) -> tuple[str, ...]:
    """Agent ids the auto-promotion loop has added to `purpose`'s roster, on top of `already` (the
    hand-authored ids `rosters` is about to combine this with) -- read from
    `app.evolution.models.roster_overlay_path`, the file `app.evolution.promotion.seat_on_desk` writes.

    **Additive and best-effort, by design, because this feeds a page render.** A missing overlay file
    is the normal state (nothing has been auto-promoted yet) and returns `()` with no log line at all.
    A present-but-malformed file, or one whose ``seats`` entry for `purpose` is not a list of strings,
    is logged and treated as `()` for this purpose only -- never raised. An id that duplicates one
    already in `already`, or that names no card `_find_card` can resolve, is skipped individually with
    its own log line rather than failing the whole overlay. The paper desk page rendering three real
    books is more important than one auto-promoted card appearing on schedule; a single bad line in a
    file this loop writes must never 500 the page (see this module's own docstring on the recorded
    incident where one bad value took down a page and three funds with it -- this is the same class of
    mistake, guarded against here instead).
    """
    path = roster_overlay_path(settings)
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("paperdesk: roster overlay at %s is unreadable, ignoring it: %s", path, exc)
        return ()
    seats = payload.get("seats") if isinstance(payload, dict) else None
    if not isinstance(seats, dict):
        logger.warning("paperdesk: roster overlay at %s has no 'seats' object, ignoring it", path)
        return ()
    raw_ids = seats.get(purpose.value, [])
    if not isinstance(raw_ids, list) or not all(isinstance(x, str) for x in raw_ids):
        logger.warning(
            "paperdesk: roster overlay at %s has a malformed %r entry, ignoring it",
            path,
            purpose.value,
        )
        return ()

    seen = set(already)
    resolved: list[str] = []
    for agent_id in raw_ids:
        if agent_id in seen:
            continue  # already on this book, hand-authored or an earlier overlay entry
        try:
            _find_card(settings, agent_id)
        except FileNotFoundError:
            logger.warning(
                "paperdesk: roster overlay names %r for %s but no card resolves to that id, "
                "skipping it",
                agent_id,
                purpose.value,
            )
            continue
        resolved.append(agent_id)
        seen.add(agent_id)
    return tuple(resolved)


def rosters(settings: Settings) -> dict[Purpose, tuple[str, ...]]:
    """Every book's roster, keyed by purpose, in `savings`, `trading`, `roth` order.

    `Purpose.TRADING` delegates to :func:`roster` so the existing settings override
    (`INVDASH_PAPERDESK_AGENT_IDS`) keeps meaning exactly what it meant before this desk had three
    books -- the trading roster -- rather than silently becoming "all three books" or "whichever
    book is listed first".

    The savings and Roth rosters are module constants with no settings override yet. That asymmetry
    is deliberate rather than an oversight: the trading override exists because a real operator has
    re-selected that roster eleven times across the competition's rounds, and neither of the other
    two has been selected even once. Adding two settings keys nobody sets would be inventing
    configuration surface to look symmetrical.

    A purpose whose roster is empty is returned as an empty tuple, not omitted -- see
    :attr:`app.paperdesk.models.PaperDeskState.books` for why an empty book is rendered rather than
    hidden.

    **The auto-promotion loop's roster overlay is appended here, additively.** Each hand-authored
    tuple below (`SAVINGS_AGENT_IDS`, `roster(settings)`, `ROTH_AGENT_IDS`) is always returned first
    and is never filtered, reordered or removed by the overlay -- deleting the overlay file restores
    exactly today's desk, with no other code path affected. See :func:`_overlay_agent_ids` for what
    happens when the overlay is missing, malformed, or names a card that does not exist: none of those
    cases ever raises out of this function.
    """
    hand_authored: dict[Purpose, tuple[str, ...]] = {
        Purpose.SAVINGS: SAVINGS_AGENT_IDS,
        Purpose.TRADING: roster(settings),
        Purpose.ROTH: ROTH_AGENT_IDS,
    }
    return {
        purpose: ids + _overlay_agent_ids(settings, purpose, already=ids)
        for purpose, ids in hand_authored.items()
    }


def seats(settings: Settings) -> dict[Purpose, tuple[str, ...]]:
    """Every id each book actually **renders**: :func:`rosters` plus the autopilot seat on trading.

    **Separate from `rosters` on purpose, and the split is load-bearing.** `rosters` means *cards* --
    hand-authored ids plus whatever the evolution loop's overlay promoted -- and its callers rely on
    that: `app.evolution.promotion`'s own tests assert its exact contents and ordering, and every
    consumer feeds each id straight to :func:`_load_card`. The autopilot seat is not a card and
    `_load_card` cannot resolve it, so folding it into `rosters` would have silently redefined that
    function for every existing caller. It was written that way first, and seven overlay tests said
    so immediately: an auto-promoted card that used to be fourth on the trading book was suddenly
    fifth, behind a seat that is not a card at all.

    So `rosters` keeps answering "which cards", and this answers "what does the page show" -- which is
    the question `_compute` and :func:`universe_symbols` are actually asking. The seat sorts **after**
    the overlay, last on the book, so the card ordering both halves of the competition machinery care
    about is contiguous and untouched.

    Seated by default, and turned off through `Settings.paperdesk_autopilot_seat` rather than by
    deleting a line here. That is a departure from `AGENT_IDS`, and a deliberate one: a hand-authored
    *card* seat is a strategy decision whose reasoning belongs in code beside it, but whether to show
    the workflow's own paper book -- which fills no order and spends nothing -- is a per-deployment
    viewing choice, the same kind of knob `paperdesk_agent_ids` already is for the card roster. When
    the flag is off the id is simply never appended, so `_book` never looks for the seat and no other
    code path changes.
    """
    resolved = rosters(settings)
    if not settings.paperdesk_autopilot_seat:
        return resolved
    return {
        purpose: (
            (*ids, autopilot_mod.AUTOPILOT_AGENT_ID) if purpose is Purpose.TRADING else ids
        )
        for purpose, ids in resolved.items()
    }


_BENCHMARK = "SPY"

#: Every index the desk is reported against, in display order, as ``(symbol, label)``. `_BENCHMARK`
#: above stays the *primary* -- it is what `app.tournament.runner` scores against and what every
#: committed round result used, so it must keep leading. `QQQ` is here because round 5 section 3
#: measured that it compounds at +18.56% a year over the decade against SPY's +12.14%, and that
#: scoring these books against it roughly halves every edge: `A-rotation`'s ten-year figure falls
#: from +5.28% to +0.63%. A page showing only the first number shows the flattering half.
_BENCHMARKS: tuple[tuple[str, str], ...] = (
    (_BENCHMARK, "broad market"),
    ("QQQ", "Nasdaq-100"),
)


def _card_symbols(card: StrategyCard | LadderCard | AllocationCard) -> set[str]:
    """Every symbol one card needs a price for, whatever shape of card it is.

    The three card shapes name their symbols in three unrelated ways and share no base class (see
    ``app.tournament.allocation``'s own docstring on why ``AllocationCard`` is not a ``StrategyCard``
    with extra fields), so this is an explicit per-shape read rather than a ``getattr(card,
    "universe", ())`` that would silently return an empty set for the two shapes that do not have
    one. A ladder that quietly contributed no symbols would look exactly like a ladder whose symbols
    were all already fresh, which is the failure mode a fetch summary exists to make impossible.

    A ladder's ``signal_symbol`` counts: ``SPY`` is not held by the ladder, but its drawdown is what
    arms every rung, so a stale ``SPY`` bar moves the card's decisions just as surely as a stale
    ``QLD`` one moves its mark. Likewise an allocation card's ``rules``: a ``TiltRule``'s
    ``on_symbol`` is validated to be some sleeve on the same card, but ``from_symbol``/``to_symbol``
    are read here anyway rather than trusted to be covered by ``sleeves`` -- that validation is
    ``app.tournament.allocation``'s contract to keep, not this function's to depend on.
    """
    if isinstance(card, LadderCard):
        return {
            card.signal_symbol,
            card.defensive_symbol,
            card.bond_symbol,
            card.leveraged_symbol,
        }
    if isinstance(card, AllocationCard):
        symbols = {sleeve.symbol for sleeve in card.sleeves}
        for rule in card.rules:
            symbols.update({rule.on_symbol, rule.from_symbol, rule.to_symbol})
        return symbols
    return set(card.universe)


def universe_symbols(settings: Settings | None = None) -> tuple[str, ...]:
    """Every daily-bar symbol this desk prices -- all three books' rosters plus every benchmark --
    de-duplicated and sorted.

    This is the desk's answer to "what data would have to be fresh for this page to be current",
    and :mod:`app.paperdesk.fetch` is the only caller that acts on it. It is deliberately built
    from :func:`rosters` and the cards themselves rather than from a hand-maintained list: a card
    re-rostered by a competition round, or a card whose universe an analyst edited, changes what
    this desk needs priced, and a second list that had to be edited alongside would be wrong the
    first time somebody forgot.

    :data:`_BENCHMARKS` is included because the page reports every book against those indices and
    -- more load-bearing -- because :func:`_trading_window` derives the desk's entire trading window
    (``as_of``, ``latest_bar``, ``earliest_inception``, ``latest_inception``) from the primary
    benchmark's own stored bars. A fetch that refreshed every card's universe but not ``SPY`` would
    leave the desk marked to the old session no matter how much new data it had just pulled.

    **A card that cannot be read is skipped, not raised on.** Same reasoning as
    :func:`_overlay_agent_ids`: an overlay naming a card that no longer exists, or a half-written
    file caught mid-save, must not take down a fetch of the thirty-odd symbols that are perfectly
    readable. Such a card's symbols are simply not fetched this pass; the desk's own recompute is
    where a missing card becomes visible, and it already handles that.
    """
    cfg = settings or get_settings()
    symbols: set[str] = {symbol for symbol, _label in _BENCHMARKS}
    for agent_ids in seats(cfg).values():
        for agent_id in agent_ids:
            # The autopilot seat has no card to read a universe off. Its symbols are whatever its
            # persisted book actually ordered, which changes every session the screened selector
            # runs -- so it answers for itself. Falling through to `_load_card` here would raise
            # `FileNotFoundError`, get swallowed by the `except (OSError, ...)` below, and quietly
            # leave every symbol the autopilot holds out of the fetch: its holdings would then be
            # marked to whatever stale bar happened to be in the store, on a page whose entire
            # discipline is about saying how stale a mark is.
            if agent_id == autopilot_mod.AUTOPILOT_AGENT_ID:
                symbols.update(autopilot_mod.universe_symbols(cfg))
                continue
            try:
                card = _load_card(cfg, agent_id)
            except (OSError, ValueError):
                logger.warning("paperdesk fetch: skipping unreadable card %r", agent_id)
                continue
            symbols.update(_card_symbols(card))
    return tuple(sorted(symbols))

_EXIT_REASON_TEXT: dict[str, str] = {
    "stop": "stop loss hit",
    "target": "take-profit hit",
    "time": "hold cap reached",
    "rule": "exit rule fired",
}

_CENTS = Decimal("0.01")


def _money(value: Decimal) -> Decimal:
    """Round to cents, half-up -- the same convention every other module in this application
    applies to a cash figure at the point it becomes one (see ``app.tournament.runner._money``,
    ``app.paper.paperbroker._money``)."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Card + mandate setup
# ---------------------------------------------------------------------------


#: The library tier a ladder card lives under. Not searched by filename == agent_id the way every
#: ``base``/``candidates`` card is: ``qld-schd-ief.json`` is named after the strategy, not the agent
#: id it declares (``ladder-qld-schd``), so :func:`_find_card` reads each file's own ``agent_id`` key
#: instead of assuming the filename convention every rules card happens to follow. That convention was
#: never a contract this package's own tooling enforced -- it just happened to hold for every card
#: written before this one -- so a second card type is exactly where relying on it silently would have
#: broken.
_LADDER_TIER = "ladder"


def _find_card(
    settings: Settings, agent_id: str
) -> tuple[Path, Literal["rules", "ladder", "allocation"]]:
    """Locate the strategy card named ``agent_id``, wherever it lives, and say which of the two card
    *shapes* it is -- needed by :func:`_load_card` to know which pydantic model to validate the file
    against, since a ``StrategyCard`` and a ``LadderCard`` do not share a schema at all.

    Not hardcoded to ``base`` or ``candidates``: the manager is moving ``C-trend.json`` from
    ``library/candidates/`` to ``library/base/`` concurrently with this package being built, so this
    globs every tier and resolves deterministically (``base`` preferred when a card somehow exists
    in more than one tier at once, which should never happen but would otherwise be an ambiguous
    pick) rather than failing if the file is not where an earlier draft of this module expected it.

    ``library/ladder/`` is searched by *content*, not by filename == agent_id: see :data:`_LADDER_TIER`
    for why. A malformed or unreadable file in that directory is skipped rather than raised on --
    exactly one file in that directory is expected to exist at all, so a corrupt neighbour must not
    take down every other card's lookup.
    """
    library = settings.library_dir
    for tier in ("base", "candidates"):
        candidate = library / tier / f"{agent_id}.json"
        if candidate.is_file():
            return candidate, "rules"

    ladder_dir = library / _LADDER_TIER
    if ladder_dir.is_dir():
        for candidate in sorted(ladder_dir.glob("*.json")):
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("agent_id") == agent_id:
                return candidate, "ladder"

    # `library/allocation/` is searched the same way `library/ladder/` is, and for the same reason
    # (see `_LADDER_TIER`): a card there is identified by the `agent_id` *inside* the file, not by
    # its filename, so renaming a file cannot silently orphan a rostered card. Until this desk grew a
    # savings book, nothing in the application read this directory at all -- the cards committed
    # there were unreachable, which `strategy-program/THREE-PURPOSES-PLAN.md` section 7 records as
    # "`library/allocation/` is orphaned".
    allocation_dir = library / _ALLOCATION_TIER
    if allocation_dir.is_dir():
        for candidate in sorted(allocation_dir.glob("*.json")):
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if payload.get("agent_id") == agent_id:
                return candidate, "allocation"

    matches = sorted(library.glob(f"*/{agent_id}.json"))
    if matches:
        return matches[0], "rules"
    raise FileNotFoundError(
        f"no strategy card named {agent_id!r} under {library} (checked every tier directory)"
    )


def _load_card(settings: Settings, agent_id: str) -> StrategyCard | LadderCard | AllocationCard:
    path, kind = _find_card(settings, agent_id)
    if kind == "ladder":
        return LadderCard.model_validate_json(path.read_text(encoding="utf-8"))
    if kind == "allocation":
        return AllocationCard.model_validate_json(path.read_text(encoding="utf-8"))
    return StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))


def opening_capital(spec: PurposeSpec) -> Decimal:
    """What a book actually opens with, which is not always `spec.seed`.

    A `LUMP_SUM` purpose deposits its seed and nothing else, so the seed *is* the opening capital.
    **Since 2026-08-29 all three purposes are `LUMP_SUM`** -- `SAVINGS` $100,000, `TRADING` $60,000,
    `ROTH` $30,000 -- so this function returns `spec.seed` for every purpose that actually exists
    today, and the branching below is retained for a funding shape none of them currently uses. A
    `MONTHLY_CONTRIBUTION` or `ANNUAL_CONTRIBUTION` purpose would open with its seed and add to it
    from then on.

    So the rule is: the seed when there is one, otherwise the first contribution -- a fallback for the
    case where an `ANNUAL_CONTRIBUTION` purpose has **no seed at all** (as `ROTH` itself did before
    2026-08-24, when `PurposeSpec.seed` was `Decimal("0")` and this fallback is what kept that book
    from opening with nothing, which would have rendered as a desk that mysteriously did nothing
    rather than as the funding model it actually was). Quantized to cents because every monetary
    figure this desk puts on the wire is a 2dp string.

    **This fallback branch is currently unreached, not dead.** As of 2026-08-24 every `PurposeSpec` in
    `PURPOSE_SPECS` has `seed > 0`, so no purpose this function is actually called with today takes the
    `else`. It stays rather than being deleted because nothing about `PurposeSpec` or the
    `ANNUAL_CONTRIBUTION` shape *requires* a positive seed -- `ROTH`'s own seed has already moved from
    `0` to `30000` once, and a future purpose (or a test constructing a `PurposeSpec` directly) can
    reintroduce a zero seed at any time. Removing the guard now would just mean re-deriving it the next
    time that happens.

    **What this deliberately does not do is model the contributions themselves.** The desk runs a
    static book from `inception` to `as_of` and never adds money mid-window; `run_card`,
    `run_ladder_card` and `run_allocation` all take one `starting_cash` and no contribution stream.
    Over the desk's current handful of sessions no monthly or annual deposit is even due, so nothing
    is currently misreported -- but this stops being true the moment the window passes a month, and
    it matters more here than anywhere: `strategy-program/THREE-PURPOSES-PLAN.md` section 2 exists
    because contribution funding inverts sequence risk, measuring an 8.4-point IRR-vs-CAGR gap on one
    strategy in one window. A contribution-funded book shown without its contributions is being asked
    the lump-sum question again. :func:`_funding_note` says so on the book itself rather than leaving
    a reader to infer it.
    """
    # `spec.seed > 0` is the guard described above -- see the docstring's "currently unreached, not
    # dead" section for why this stays even though no entry in `PURPOSE_SPECS` takes the `else` today.
    seed = spec.seed if spec.seed > 0 else spec.contribution
    return Decimal(seed).quantize(Decimal("0.01"))


def _mandate(purpose: Purpose) -> Mandate:
    """The same persona mandate ``app.tournament.__main__`` builds, seeded with **this purpose's own**
    opening capital and the single-name weight cap loosened to 1.0 -- see this module's docstring for
    why the cap moves, and :func:`opening_capital` for why the seed is not always ``spec.seed``.

    **Per purpose, not per desk.** Each book trades its own money: as of 2026-08-29, $100,000 for
    `SAVINGS`, $60,000 for `TRADING`, $30,000 for `ROTH` (see :func:`opening_capital`). One desk-wide
    mandate would have meant either three books sharing a figure that is right for at most one of
    them, or a fourth number belonging to none.

    **`SAVINGS` is now the largest book and `TRADING` is not**, which reverses the ordering every
    earlier version of this docstring described -- and it is the point of the change rather than an
    incidental renumbering: the owner moved the majority of the capital into the book with the safest
    mandate. See `strategy-program/ACCOUNT-DEPLOYMENT-PLAN.md` section 0.

    **The amount is read from :data:`app.tournament.purposes.PURPOSE_SPECS`, not written here.** How
    much money a purpose has is already stated as data in exactly one place. A literal here would be a
    second copy of a figure the owner has already changed twice -- $100,000 to $50,000 to $100,000 for
    `TRADING` alone -- and the failure mode of two copies is not a crash, it is a desk quietly
    reporting returns on capital the programme no longer thinks it has."""
    mandate = default_mandate(starting_cash=opening_capital(PURPOSE_SPECS[purpose]))
    return dataclasses.replace(mandate, max_single_name_weight=Decimal(1))


# ---------------------------------------------------------------------------
# Inception override -- settable at runtime, persisted to disk
# ---------------------------------------------------------------------------
#
# :data:`INCEPTION` above is the desk's *default* inception, not its only one any more.
# :func:`effective_inception` reads `data/paperdesk/inception.json` when present and falls back to
# `INCEPTION` otherwise -- the same "small persisted JSON override, read at request time" shape
# `app.evolution.models.roster_overlay_path` already uses for the roster overlay (see
# :func:`_overlay_agent_ids` above), for the same reason: a running server must not need to rewrite
# already-imported Python to change behaviour, and deleting the file must restore exactly the
# hand-authored default.
#
# **Changing inception does not need to bust `_RUN_CACHE`/the disk cache tier, and this module
# deliberately does not add any code to do so.** Every cache key already includes `window.inception`
# (see :func:`_cached_run`, :func:`_cached_allocation_run`, :func:`_cached_ladder_run` and
# :func:`_disk_cache_path`'s own filename), so a changed inception already produces a different key
# and the next :func:`state` call recomputes every book from the new window on its own -- and
# switching back to an inception this desk has already traded from serves the earlier run straight
# back out of the cache instead of paying to recompute it. Clearing the cache here would only discard
# correct, already-paid-for work.


def inception_override_path(settings: Settings) -> Path:
    """`data/paperdesk/inception.json` -- the file :func:`set_inception` writes and
    :func:`effective_inception` reads back, one level under `settings.data_dir` the same way
    `app.evolution.models.roster_overlay_path` sits under it for the roster overlay."""
    return settings.data_dir / "paperdesk" / "inception.json"


def _read_inception_override(settings: Settings) -> dt.date | None:
    """The override file's parsed value, or `None` when there is nothing usable to read.

    **A missing file is the normal case** -- most servers never call :func:`set_inception` -- and
    returns `None` silently, with no log line at all. **A present-but-malformed file logs and
    returns `None` too, and never raises**: this module has a recorded incident (see
    :func:`_overlay_agent_ids` above, guarding the same class of file) where trusting a small
    persisted override enough to raise on it took a page and every book on it down over one bad
    value, and inception is a worse place for that to happen than a roster -- it gates the trading
    window for *every* book, not one card's roster. `None` here means "behave exactly as if this file
    did not exist," which is the same fallback :func:`effective_inception` gives a missing file.
    """
    path = inception_override_path(settings)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = payload.get("inception") if isinstance(payload, dict) else None
        if not isinstance(raw, str):
            raise ValueError(f"no string 'inception' key in {payload!r}")
        return dt.date.fromisoformat(raw)
    except (OSError, ValueError) as exc:
        logger.warning(
            "paperdesk: inception override at %s is unreadable, falling back to the default "
            "%s: %s",
            path,
            INCEPTION.isoformat(),
            exc,
        )
        return None


def effective_inception(settings: Settings) -> dt.date:
    """The inception this desk actually trades from right now: the override file's value when one
    parses, otherwise :data:`INCEPTION`. See :func:`_read_inception_override` for exactly what counts
    as "parses" and what happens when it does not."""
    return _read_inception_override(settings) or INCEPTION


def _benchmark_dates(settings: Settings) -> list[dt.date]:
    """Every stored session date for the primary benchmark, ascending -- one store read, shared by
    :func:`_trading_window` (which needs only the latest) and :func:`_validate_inception` (which
    needs both ends)."""
    frame = store.read_frame(_BENCHMARK, Interval.DAY, settings=settings)
    return sorted({ts.date() for ts in frame["ts"]})


class InceptionRejected(ValueError):
    """:func:`set_inception` refused `value` -- :attr:`reason` is the specific, user-facing
    explanation :mod:`app.api.paperdesk` maps to a `422` body, rather than letting a rejected date
    reach the client as a bare `500` or, worse, silently clamping it to something tradeable. See
    :func:`_validate_inception` for the three ways a date earns this."""

    def __init__(self, value: dt.date, reason: str) -> None:
        super().__init__(reason)
        self.value = value
        self.reason = reason


def _validate_inception(value: dt.date, *, settings: Settings) -> None:
    """Refuse `value` outright when it cannot actually be traded from, rather than clamping it to the
    nearest legal date -- a desk quietly trading a different window than the one asked for is worse
    than an error that says so.

    Three distinct refusals, each its own :class:`InceptionRejected`:

    * `value` is after the benchmark's latest stored bar -- there would be no sessions at all.
    * `value` is before the benchmark's earliest stored bar -- there is no history to trade from.
    * `value` falls inside the stored range but `SessionCalendar` itself yields zero sessions --
      which can still happen even inside the range, because a session also needs a *prior* stored
      bar to decide on (`SessionCalendar.__init__`'s own "no prior stored session to decide on"
      check): the very first stored bar is inside the range and yet untradeable as an inception.
    """
    dates = _benchmark_dates(settings)
    if not dates:
        raise InceptionRejected(
            value,
            f"no {_BENCHMARK} bars are stored at all -- there is nothing to validate any inception "
            "against",
        )
    earliest, latest = dates[0], dates[-1]
    if value > latest:
        raise InceptionRejected(
            value,
            f"{value.isoformat()} is after the latest stored {_BENCHMARK} bar "
            f"({latest.isoformat()}); there would be no sessions to trade at all",
        )
    if value < earliest:
        raise InceptionRejected(
            value,
            f"{value.isoformat()} is before the earliest stored {_BENCHMARK} bar "
            f"({earliest.isoformat()})",
        )
    try:
        calendar = SessionCalendar(start=value, end=latest, settings=settings, benchmark=_BENCHMARK)
    except (UnpricedSymbol, ValueError) as exc:
        raise InceptionRejected(
            value,
            f"{value.isoformat()} yields zero trading sessions through {latest.isoformat()}: {exc}",
        ) from exc
    if len(calendar) == 0:
        raise InceptionRejected(
            value,
            f"{value.isoformat()} yields zero trading sessions through {latest.isoformat()}",
        )


def set_inception(value: dt.date, *, settings: Settings) -> None:
    """Persist `value` as the desk's inception override, after :func:`_validate_inception` refuses it
    outright if it cannot be traded from at all.

    Written atomically: a temp file in the same directory, then `Path.replace` -- the identical
    device :func:`_compute_and_store` already uses for its disk cache tier, for the identical reason.
    A request reading :func:`effective_inception` mid-write must never observe a half-written file; a
    desk request landing between the temp file's creation and the rename simply reads whatever the
    override file already said, old or new, never a torn one.

    **Does not touch either run-cache tier, on purpose -- see this section's own module-level comment
    above.** The cache key already covers `window.inception`, so a changed inception is already a
    different key; clearing the cache here would only discard correct, already-paid-for work for
    every inception this desk has ever traded from.
    """
    _validate_inception(value, settings=settings)
    path = inception_override_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"inception": value.isoformat()}), encoding="utf-8")
    tmp.replace(path)


def clear_inception(*, settings: Settings) -> None:
    """Delete the override file, restoring :data:`INCEPTION` as the effective inception.

    A missing file is not an error: clearing an already-default desk is a no-op, matching
    `Path.unlink(missing_ok=True)`'s own contract, not a failure a caller has to guard against."""
    inception_override_path(settings).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# The trading window -- derived from the store, never hardcoded
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class _Window:
    inception: dt.date
    first_session: dt.date
    as_of: dt.date
    """The last traded session's own date -- also the ``end`` passed to ``run_card``. Equal to
    ``latest_bar``: the newest stored session is itself tradeable (see this module's docstring)."""
    decided_on: dt.date
    """``as_of``'s own ``decided_on`` -- the close the desk's *last actual* decision was made
    against, one session before ``as_of``. Kept for reference; ``signals`` are evaluated at
    ``as_of`` itself, not here -- see :func:`_signals`."""
    sessions: int
    latest_bar: dt.date
    session_dates: tuple[dt.date, ...] = ()
    """Every session's own date, ascending -- used to count
    :attr:`~app.paperdesk.models.PaperDeskState.in_sample_sessions` precisely (each date compared
    against `app.tournament.models.DESIGN_THROUGH` directly) rather than by calendar-day arithmetic,
    which cannot see weekends or holidays. Defaults to `()` only so the hand-built `_WINDOW` fixture
    in `tests/test_paperdesk.py`, which predates this field and does not exercise in-sample counting,
    keeps constructing unchanged; :func:`_trading_window` always populates it for real."""
    earliest_bar: dt.date | None = None
    """The benchmark's very first stored session -- independent of ``inception``, since a window can
    (and, once :func:`set_inception` exists, routinely will) start well after the store's own history
    begins. `None` only for the same reason `session_dates` defaults to `()` above; a test double is
    the only caller that ever leaves it unset. :func:`_compute` falls back to ``inception`` itself
    when this is `None`, which only ever happens in that test double."""


def _trading_window(settings: Settings) -> _Window:
    """Find the window this desk trades, from the benchmark's own stored history.

    ``inception`` comes from :func:`effective_inception`, not the module constant directly -- see
    that function and :data:`INCEPTION`'s own docstring for why a runtime override can move it.
    ``latest_bar`` is the newest stored day for the benchmark, and the trading window's own ``end``
    is that same day, matching ``app.tournament.models.TRADE_END``'s own convention ("last stored
    session at the time this package was built"). The session dated ``latest_bar`` is decided on the
    *prior* stored session's close and filled at ``latest_bar``'s own open -- both bars already
    exist, so nothing about trading through it needs a bar the store doesn't have yet (see the
    module docstring's "Real-time" section for why an earlier, more conservative version of this
    function stopped one session short, and why that was wrong rather than merely cautious).
    ``SessionCalendar`` is reused, not reimplemented, to turn ``(inception, end)`` into the actual
    session list -- the same class ``run_card`` builds internally with the same two dates, so this
    module's ``first_session``/``as_of``/``sessions`` are guaranteed to agree with whatever
    ``run_card`` itself just traded.
    """
    inception = effective_inception(settings)
    dates = _benchmark_dates(settings)
    if not dates:
        raise UnpricedSymbol(_BENCHMARK, inception)

    earliest_bar = dates[0]
    latest_bar = dates[-1]
    end = latest_bar

    calendar = SessionCalendar(start=inception, end=end, settings=settings, benchmark=_BENCHMARK)
    sessions = list(calendar)
    last_session = sessions[-1]
    return _Window(
        inception=inception,
        first_session=sessions[0].date,
        as_of=last_session.date,
        decided_on=last_session.decided_on,
        sessions=len(sessions),
        session_dates=tuple(s.date for s in sessions),
        latest_bar=latest_bar,
        earliest_bar=earliest_bar,
    )


# ---------------------------------------------------------------------------
# Signals -- current rule truth per universe symbol, evaluated fresh
# ---------------------------------------------------------------------------


def _rule_fires(tree: BoolExpr, symbol: str, *, market: AsOfMarket) -> bool:
    """Truth of `tree` on `symbol`'s last available bar at `market.as_of`.

    The same construction as ``app.tournament.runner._rule_fires``: an unknown truth value
    (warmup, a gap, no stored bar at all) becomes ``False``, never raises.
    """
    # Full history, for the same reason `runner._rule_fires` does it -- see DEFECTS.md D4. The
    # desk's signals must agree with what the engine would decide, so they must be computed the
    # same way.
    bars = market.history(symbol, lookback_days=None)
    if bars.empty:
        return False
    signal = rule_evaluate.evaluate(tree, bars, interval=Interval.DAY)
    return bool(signal.fillna(False).iloc[-1])


def _signals(
    card: StrategyCard,
    result: AgentResult,
    *,
    settings: Settings,
    window: _Window,
    holdings: list[Holding],
    cash: Decimal,
) -> list[Signal]:
    """Every universe symbol's current standing, evaluated once at ``window.as_of`` -- the newest
    stored close, the same one every :class:`Holding` is marked to. This is deliberately the *next*
    decision, not the last one: a trader reads the rules against today's close and the resulting
    order fills at the following session's open, which has not happened yet -- no lookahead, since
    ``as_of``'s own close is already in the store. Evaluating one session earlier (at
    ``window.decided_on``, the market the desk's *last* actual decision was made against) would
    reproduce a decision already acted on, and would report a different close than
    :class:`Holding.last_price` for the same symbol on the same page -- see the module docstring.

    **The order of the returned list is the order the engine would attempt entries in.** For a card
    that sets ``rank_by`` that is the ranked order -- strongest key first, unknown keys last -- and
    for one that does not it is ``card.universe`` unchanged, which is what the engine walks in that
    case too (`app.tournament.runner._ordered_entry_candidates`). This matters because the list was
    previously always in ``universe`` order while the engine's own fill order was not, so a reader
    with three names firing into two free slots could see them in one order and have the desk buy
    them in another. :attr:`~app.paperdesk.models.Signal.entry_rank` names the same order as a
    number for the contenders, and :attr:`~app.paperdesk.models.Signal.rank_value` shows the key it
    was sorted on -- an ordering with no visible reason is not much better than an arbitrary one."""
    market = AsOfMarket(as_of=window.as_of, settings=settings)
    entry_tree = grammar.parse(card.entry)
    exit_tree = grammar.parse(card.exit) if card.exit.strip() else None
    rank_tree: NumExpr | None = (
        grammar.parse_ranking(card.rank_by) if card.rank_by is not None else None
    )

    # The ranking is the engine's, called here rather than reproduced -- `_build_rank_table` and
    # `_ordered_entry_candidates` are the same two functions `run_card` itself uses to decide which
    # qualifying name takes a scarce slot, handed this desk's own as-of date instead of a historical
    # session's. Reimplementing the sort would be a second answer to a question that already has
    # one, and this panel's whole claim is that it shows what the engine would actually do next.
    # `card.rank_by is None` makes both calls degenerate -- an empty table, and `universe` returned
    # unchanged -- so an unranked card's panel is exactly what it was before this existed.
    ranks = _build_rank_table(rank_tree, card.universe, settings=settings, through=window.as_of)
    order = _ordered_entry_candidates(card.universe, ranks, on=window.as_of)

    held_symbols = {h.symbol for h in holdings}
    position_notional = card.position_pct * result.starting_equity
    open_positions = len(holdings)

    # Counted as the ranked walk passes each contender, which is what makes `entry_rank` a queue
    # position rather than a row number: it advances only on a name actually competing for a slot.
    contenders = 0

    signals: list[Signal] = []
    for symbol in order:
        rank_value = ranks.value(symbol, window.as_of)
        held = symbol in held_symbols
        try:
            last_close = market.close(symbol)
        except UnpricedSymbol:
            signals.append(
                Signal(
                    symbol=symbol,
                    held=held,
                    entry_fires=False,
                    exit_fires=False,
                    last_close=None,
                    blocked="no price",
                    rank_value=rank_value,
                )
            )
            continue

        entry_fires = _rule_fires(entry_tree, symbol, market=market)
        exit_fires = (
            held and exit_tree is not None and _rule_fires(exit_tree, symbol, market=market)
        )

        blocked: str | None = None
        entry_rank: int | None = None
        if entry_fires and not held:
            if rank_tree is not None:
                contenders += 1
                entry_rank = contenders
            if open_positions >= card.max_positions:
                blocked = "book full"
            elif cash < position_notional:
                blocked = "insufficient cash"

        signals.append(
            Signal(
                symbol=symbol,
                held=held,
                entry_fires=entry_fires,
                exit_fires=exit_fires,
                last_close=last_close,
                blocked=blocked,
                rank_value=rank_value,
                entry_rank=entry_rank,
            )
        )
    return signals


# ---------------------------------------------------------------------------
# Trades, decisions, holdings
# ---------------------------------------------------------------------------


def _closed_trades(trades: tuple[RealisedTrade, ...]) -> list[Trade]:
    closed = [t for t in trades if t.exit_reason != "open_at_end"]
    closed.sort(key=lambda t: t.exit_date or dt.date.min, reverse=True)
    return [
        Trade(
            symbol=t.symbol,
            entry_date=t.entry_date,
            entry_price=t.entry_price,
            exit_date=t.exit_date,  # type: ignore[arg-type]  # closed => not None
            exit_price=t.exit_price,  # type: ignore[arg-type]
            quantity=t.quantity,
            exit_reason=t.exit_reason,
            pnl=t.pnl,
            return_pct=t.return_pct,
            bars_held=t.bars_held,
        )
        for t in closed
    ]


def _decisions(trades: tuple[RealisedTrade, ...]) -> list[Decision]:
    """Reconstructed from the trade log -- see the module docstring's "decisions" section."""
    rows: list[Decision] = []
    for t in trades:
        rows.append(
            Decision(
                date=t.entry_date,
                symbol=t.symbol,
                action="enter",
                reason="entry rule fired",
                price=t.entry_price,
                quantity=t.quantity,
                notional=_money(t.entry_price * t.quantity),
            )
        )
        if t.exit_date is not None and t.exit_price is not None:
            rows.append(
                Decision(
                    date=t.exit_date,
                    symbol=t.symbol,
                    action="exit",
                    reason=_EXIT_REASON_TEXT.get(t.exit_reason, t.exit_reason),
                    price=t.exit_price,
                    quantity=t.quantity,
                    notional=_money(t.exit_price * t.quantity),
                )
            )
    rows.sort(key=lambda d: d.date, reverse=True)
    return rows


_MAX_REJECTION_DETAIL = 20
"""Cap on `DeskRejection.detail` -- a card that failed hundreds of orders under one rule (a mandate
misconfiguration, say) should not ship hundreds of near-identical sentences to the page."""


def _group_rejections(
    records: Iterable[RejectionRecord] | None, *, bare_rules: Iterable[str] = ()
) -> tuple[list[DeskRejection], int]:
    """Collapse a run's per-order refusals into one :class:`DeskRejection` per rule.

    Exactly one of the two arguments carries real per-order data. `records` is
    `AgentResult.rejection_details` -- a rules card's broker run, with the full `rule`/`symbol`/
    `reason` for every refusal. `LadderResult`/`AllocationResult` (a ladder or allocation card's run)
    only ever recorded the bare rule slug (`rejections: tuple[str, ...]`, from
    `app.tournament.ladder`/`app.tournament.allocation`, both outside this package), so `bare_rules`
    is the fallback path for those two card shapes: `symbols` is left empty (never observed) and
    `detail` falls back to the rule's own label, repeated, rather than inventing a reason sentence
    that was never recorded.

    Groups are sorted by `count` descending, then `rule` ascending, matching
    `app.paperdesk.models.Desk.rejections`'s own contract. Returns the groups alongside the total
    order count across every group, i.e. `Desk.rejection_count`.
    """
    # (rule, symbol_or_none, reason_or_none), oldest first -- reversed per group below to get
    # "newest first" for `detail` without sorting the whole run by anything but insertion order.
    rows: list[tuple[str, str | None, str | None]] = (
        [(r.rule, r.symbol, r.reason) for r in records]
        if records is not None
        else [(rule, None, None) for rule in bare_rules]
    )

    groups: dict[str, dict[str, Any]] = {}
    for rule, symbol, reason in rows:
        group = groups.setdefault(rule, {"count": 0, "symbols": set(), "detail": []})
        group["count"] += 1
        if symbol:
            group["symbols"].add(symbol)
        group["detail"].append(reason if reason is not None else rejection_label(rule))

    desk_rejections = [
        DeskRejection(
            rule=rule,
            label=rejection_label(rule),
            count=group["count"],
            symbols=sorted(group["symbols"]),
            detail=list(reversed(group["detail"]))[:_MAX_REJECTION_DETAIL],
        )
        for rule, group in groups.items()
    ]
    desk_rejections.sort(key=lambda d: (-d.count, d.rule))
    total = sum(d.count for d in desk_rejections)
    return desk_rejections, total


def _holdings(
    trades: tuple[RealisedTrade, ...],
    *,
    settings: Settings,
    as_of: dt.date,
    stop_loss_pct: Decimal | None,
    take_profit_pct: Decimal | None,
    max_hold_days: int | None,
) -> list[Holding]:
    """Every ``open_at_end`` trade, marked fresh at ``as_of`` -- the same date ``run_card``/
    ``run_ladder_card`` used to compute their result's own ``ending_equity`` -- so the sum of every
    holding's ``market_value`` agrees with the equity figure to the cent. See the module docstring's
    "Holdings are marked fresh" section for why this does not reuse ``RealisedTrade.pnl``.

    Takes the three bracket-shaped figures directly rather than a whole ``StrategyCard``, so this one
    function serves both card shapes this package now builds a desk from: a ``LadderCard`` has none
    of `stop_loss_pct`/`take_profit_pct`/`max_hold_days` (a portfolio-weight rotation has no
    per-position bracket at all), and :func:`_build_ladder_desk` calls this the same way
    :func:`_build_desk` does, passing ``None`` for all three -- which already renders correctly, since
    every branch below already treats ``None`` as "this card declines the bracket entirely", not as a
    missing value to guess at.
    """
    open_trades = [t for t in trades if t.exit_reason == "open_at_end"]
    if not open_trades:
        return []

    market = AsOfMarket(as_of=as_of, settings=settings)
    rows: list[Holding] = []
    for t in open_trades:
        history = market.history(t.symbol, lookback_days=10)
        if history.empty:
            # Marked flat against the entry price -- no data to price it at all, which mirrors
            # `run_card._open_at_end_trade`'s own fallback for the identical situation.
            last_price = t.entry_price
            last_price_date = as_of
        else:
            last_price = market.close(t.symbol)
            last_price_date = history["ts"].iloc[-1].date()

        cost_basis = _money(t.entry_price * t.quantity)
        market_value = _money(last_price * t.quantity)
        unrealised_pnl = market_value - cost_basis
        return_pct = (unrealised_pnl / cost_basis) if cost_basis != 0 else Decimal(0)

        stop_price = (
            _money(t.entry_price * (Decimal(1) - stop_loss_pct)) if stop_loss_pct is not None else None
        )
        target_price = (
            _money(t.entry_price * (Decimal(1) + take_profit_pct))
            if take_profit_pct is not None
            else None
        )
        sessions_to_time_stop = (
            max_hold_days - t.bars_held if max_hold_days is not None else None
        )

        rows.append(
            Holding(
                symbol=t.symbol,
                quantity=t.quantity,
                entry_date=t.entry_date,
                entry_price=t.entry_price,
                cost_basis=cost_basis,
                last_price=last_price,
                last_price_date=last_price_date,
                market_value=market_value,
                unrealised_pnl=unrealised_pnl,
                return_pct=return_pct,
                bars_held=t.bars_held,
                weight=0.0,  # filled in by `_build_desk`, once `equity` is known
                stop_price=stop_price,
                target_price=target_price,
                sessions_to_time_stop=sessions_to_time_stop,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Per-card result cache -- in memory, and on disk behind it
# ---------------------------------------------------------------------------
#
# **Why a disk tier exists at all.** Running the roster cold costs about six seconds per card --
# eighteen for three -- and a profile puts effectively all of it in `runner._rule_fires`, which
# recomputes every indicator across the symbol's *entire* stored history once per session per symbol
# (1,378 times for a 55-session window) to extract a single trailing boolean each time. That is a
# real inefficiency in the engine and the right place to fix it is there, by evaluating each
# indicator once per symbol and indexing per session. It is deliberately *not* fixed here: that is
# the audited hot path every committed round was measured through, and three rounds of
# cross-comparability currently rest on it reproducing bit-for-bit.
#
# So the cost is paid once instead of made cheaper. The desk's result is a pure function of its
# inputs -- the same card, mandate, window and bars give byte-identical output, which round 3
# verified directly by reproducing both incumbents' round-2 numbers to the last decimal -- so it is
# safe to memoise across process restarts as long as the key covers everything that can change it.
#
# **What the key covers.** Agent id, the window (inception / as_of / latest_bar), and a digest of the
# card itself. The card digest is the part that is easy to forget and expensive to get wrong: edit a
# card's stop or universe without it and the desk would serve the old book's numbers under the new
# book's name, indefinitely and silently. `StrategyCard` is frozen and fully serialisable, so its
# JSON is a complete description of everything `run_card` reads from it.
#
# The mandate is deliberately *not* in the key, and that is a live limitation rather than an
# oversight: `app.paper.mandate.default_mandate()` is code, so changing slippage or commission would
# not invalidate these entries. `tests/test_paper_mandate.py` pins those numbers against the UAT
# persona precisely so they do not move quietly, and `clear_disk_cache()` is the escape hatch if they
# ever do.
#
# **`Settings.paperdesk_live_fills` is the one input that breaks "pure function of card, mandate,
# window and bars" outright**, because it can let a fill price off a live quote -- a number that
# changes from one call to the next with nothing in `key` moving to say so. `_cached_run` bypasses
# both tiers entirely while it is on, rather than widen the key; see its own comment for why.

_RUN_CACHE: dict[tuple[str, dt.date, dt.date, dt.date, str], AgentResult] = {}

#: One lock per cache key, so two callers wanting the same uncomputed desk queue instead of both
#: computing it. Without this, a request landing while the startup `warm` is still running does the
#: entire run a second time in parallel -- measured at 9.3s of duplicated work on a three-card
#: roster -- and, worse, puts two bar-loading backtests on the box at once. This repository has a
#: documented history of exactly that combination exhausting a 16 GB host
#: (`strategy-program/DEFECTS.md` D3 and the round-2 post-mortem): concurrent runs are a resource
#: hazard here, not merely wasteful.
#:
#: `_LOCKS` itself is guarded by `_LOCKS_GUARD`, because two threads racing to create the *lock* for
#: the same key would otherwise each get their own and neither would exclude the other.
_LOCKS: dict[tuple[str, dt.date, dt.date, dt.date, str], threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _key_lock(key: tuple[str, dt.date, dt.date, dt.date, str]) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())

#: Bumped when anything changes that would alter a cached `AgentResult` but is invisible to the
#: cache key -- the shape of the payload, or the behaviour of the engine that produced it. Entries
#: written by an older build are ignored rather than trusted, because a stale payload that still
#: parses is worse than one that fails loudly.
#:
#: v2: `strategy-program/DEFECTS.md` D4. Rule evaluation moved from a 400-day trailing window to full
#: history, which changes recursive indicators (`ema`, Wilder `rsi`) by enough to move a crossover.
#: The key covers the card, the window and the bars -- none of which changed -- so every v1 entry
#: would otherwise have been served indefinitely as a pre-fix result under a post-fix build. This is
#: exactly the "a corrected engine" case `clear_disk_cache`'s docstring names, and the reason a
#: version lives in the filename rather than only in the payload.
#:
#: v3: a second card *type* (`LadderCard` / `LadderResult`, see `app.tournament.ladder`) can now
#: produce a disk cache entry, and a cached entry's meaning has changed even though nothing about
#: `AgentResult`'s own payload shape moved: before this version, "this cache directory holds
#: `AgentResult` JSON keyed on `(agent_id, window, card digest)`" was true of every file in it. From
#: v3 on it is not -- a ladder entry is keyed the same way but validates against `LadderResult`
#: instead (see :func:`_ladder_disk_cache_path`'s distinct filename prefix, which is what lets
#: `_compute_and_store`/`_compute_and_store_ladder` each read back the shape they wrote without first
#: having to sniff the JSON). A v2-built directory is not wrong in a way that would crash a v3 reader
#: -- no v2 entry could ever have been a ladder result, since this module could not produce one yet --
#: but the version is bumped anyway, on the same principle `clear_disk_cache`'s docstring states for
#: v2 itself: a stale payload that still parses is worse than one a version bump makes this build
#: simply never look at.
#:
#: v4: the desk's starting cash moved from a flat $100,000 to the trading purpose's $50,000 seed
#: (:func:`_mandate`). Starting cash is in none of the five key components -- and `_card_digest`
#: hashes the *card*, which did not change, not the mandate -- so without this bump every v3 entry
#: would be served indefinitely as a $100,000 book under a $50,000 build. Position sizing is a
#: fraction of starting equity and shares are whole, so the halved seed changes fills, share counts
#: and therefore returns; a stale entry here would not look broken, it would look like a desk that
#: had simply performed differently.
#:
#: v5: two more starting-cash changes on 2026-08-24, same blind spot as v4 -- starting cash is still in
#: none of the five key components. `TRADING`'s seed reverted from $50,000 back to $100,000
#: (`PURPOSE_SPECS[Purpose.TRADING].seed`), and `ROTH`'s opening capital moved from $7,500 (the
#: `opening_capital` fallback onto `contribution`, when `seed` was `Decimal(0)`) to a $30,000 seed
#: taken directly. Without this bump, every v4 entry -- a $50,000 `TRADING` book and a $7,500 `ROTH`
#: book -- would be served indefinitely under a build that now thinks those books open at $100,000 and
#: $30,000 respectively.
#:
#: v6: `rosters` now appends the auto-promotion loop's roster overlay
#: (`app.evolution.models.roster_overlay_path`) on top of the hand-authored tuples -- see
#: `_overlay_agent_ids`. The overlay is not part of any of the five key components below: it is a
#: separate file, read at request time, outside the card/mandate/window inputs this cache key was ever
#: built from. Without this bump, a card promoted onto a book after that book's first request would be
#: served from a cached payload computed before the overlay named it, and a card later removed from the
#: overlay would keep appearing indefinitely. Same blunt fix v4 and v5 both took for the same shape of
#: blind spot: the cache key cannot see everything that can change the response, so a change in that
#: gap has to invalidate everything rather than nothing.
#:
#: v7: two more starting-cash changes on 2026-08-29 -- the *third* time this exact blind spot has
#: forced a bump (v4, v5, now v7). `SAVINGS`'s seed moved $20,000 -> $100,000 and `TRADING`'s
#: $100,000 -> $60,000 (`PURPOSE_SPECS`), so savings is now the largest book and trading is not.
#: `ROTH`'s $30,000 is unchanged, but its `contribution` went $7,500 -> $0, which does not move
#: `opening_capital` while `seed > 0` -- noted so a reader does not go looking for a third moved
#: figure here. Without this bump every v6 entry -- a $20,000 savings book and a $100,000 trading
#: book -- would be served under a build that thinks those books open at $100,000 and $60,000. As in
#: v4: position sizing is a fraction of starting equity and shares are whole, so a stale entry does
#: not look broken, it looks like a desk that performed differently.
#:
#: **v8: the recurring blind spot (v4, v5, v7 -- three of the six bumps above, all the same omission)
#: is now fixed structurally, not by hand.** `mandate.starting_cash` is folded into the cache key via
#: `_run_cache_digest` below, the way `window.inception` already was, which is why an inception change
#: never needed a bump at all (see the "Inception override" section above). The key's *shape* --
#: `(agent_id, inception, as_of, latest_bar, digest)`, a 5-tuple -- is unchanged: `_card_digest` itself
#: stays a pure function of the card alone (`tests/test_paper_live_fill.py` calls it directly to
#: reconstruct a key's expected shape, and widening what it returns would break that reconstruction for
#: reasons unrelated to capital). `_run_cache_digest` is the one new seam every real caller
#: (`_cached_run`, `_cached_allocation_run`, `_cached_ladder_run`) goes through instead, combining
#: `_card_digest(card)` with `mandate.starting_cash` into the digest actually stored in the key. A
#: mandate whose capital changes now produces a different digest -- and therefore a different key and a
#: different cache file -- automatically, scoped to the book that actually moved, with nothing left for
#: a human to notice in `purposes.py` and remember to bump here. This version is still bumped to v8
#: anyway (rather than silently changing what a "v7" digest means) so that no old v7 entry, keyed on the
#: pre-fix pure-card digest, is ever mistaken for a v8 one on the same starting cash -- the two digest
#: functions cannot collide by construction (see `_run_cache_digest`'s own docstring), but a distinct
#: version keeps that guarantee visible in the filename rather than resting on it silently.
_DISK_CACHE_VERSION = "v8"


def _card_digest(card: StrategyCard | LadderCard | AllocationCard) -> str:
    """A short, stable digest of everything `run_card` reads from a card.

    Deliberately still a pure function of `card` alone -- see the `_DISK_CACHE_VERSION` v8 note above
    for why `starting_cash` is folded in at `_run_cache_digest` instead of here.
    """
    return hashlib.sha256(card.model_dump_json().encode("utf-8")).hexdigest()[:16]


def _run_cache_digest(
    card: StrategyCard | LadderCard | AllocationCard, *, starting_cash: Decimal
) -> str:
    """The digest actually stored in a `_cached_run`/`_cached_allocation_run`/`_cached_ladder_run`
    cache key: `_card_digest(card)` folded together with the mandate's `starting_cash`.

    This is the fix the `_DISK_CACHE_VERSION` v8 note describes: `starting_cash` decides fills, share
    counts and therefore every return this desk reports (`AgentResult`/`LadderResult`/
    `AllocationResult` alike), and it was in none of the five key components before this change --
    three of the six version bumps this constant has ever needed (v4, v5, v7) existed only to paper
    over that gap by hand, each invalidating every cached entry across every book to correct one book's
    capital. Combining it into the digest here, rather than widening the key tuple's own arity, keeps
    every key a 5-tuple of the same shape `_disk_cache_path`/`_allocation_disk_cache_path`/
    `_ladder_disk_cache_path` already destructure -- `_card_digest` itself is left untouched (see its
    own docstring) precisely so that shape does not have to change.

    Delimited with `"|"`, a character `str(Decimal)` never produces, so `(card_digest="ab", cash=12)`
    and `(card_digest="ab1", cash=2)` cannot collide by having their concatenated strings coincide --
    the same reasoning `_disk_cache_path`'s own filename-joining relies on implicitly via fixed-width
    date formatting, made explicit here because `starting_cash` has no fixed width.
    """
    return hashlib.sha256(f"{_card_digest(card)}|{starting_cash}".encode()).hexdigest()[:16]


def _disk_cache_dir(settings: Settings) -> Path:
    return settings.cache_dir / "paperdesk"


def _disk_cache_path(settings: Settings, key: tuple[str, dt.date, dt.date, dt.date, str]) -> Path:
    agent_id, inception, as_of, latest_bar, digest = key
    # `agent_id` reaches the filesystem, so it is reduced to a conservative charset rather than
    # trusted: a card id is analyst-supplied and a `../` in one would otherwise escape the cache dir.
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in agent_id)
    name = f"{_DISK_CACHE_VERSION}-{safe}-{inception:%Y%m%d}-{as_of:%Y%m%d}-{latest_bar:%Y%m%d}-{digest}.json"
    return _disk_cache_dir(settings) / name


def clear_cache() -> None:
    """Drop every in-memory cached run. Called by :func:`refresh` and by tests that must not let one
    test's cached result leak into the next.

    Drops the per-key locks with it, so a test that clears the cache does not leave a lock behind
    keyed on a window it will never ask for again. Only the in-memory tier; :func:`refresh` clears
    the disk tier too -- see its docstring for why
    an explicit user action has to reach further than an internal one."""
    _RUN_CACHE.clear()
    with _LOCKS_GUARD:
        _LOCKS.clear()
    _LADDER_RUN_CACHE.clear()
    with _LADDER_LOCKS_GUARD:
        _LADDER_LOCKS.clear()
    _ALLOCATION_RUN_CACHE.clear()
    with _ALLOCATION_LOCKS_GUARD:
        _ALLOCATION_LOCKS.clear()


#: Matches this module's own cache filenames, of any past or future `_DISK_CACHE_VERSION` -- the shape
#: every one of `_disk_cache_path`/`_allocation_disk_cache_path`/`_ladder_disk_cache_path` writes:
#: `v<digits>-[allocation-|ladder-]<safe-agent-id>-<8 digits>-<8 digits>-<8 digits>-<16 hex>.json`.
#: :func:`clear_disk_cache` uses this to decide what it may delete -- see that function's own docstring
#: for why matching only this module's own shape matters, not just globbing every `.json` in the
#: directory.
_CACHE_FILENAME_RE = re.compile(
    r"^v\d+-(?:allocation-|ladder-)?[A-Za-z0-9_-]+-\d{8}-\d{8}-\d{8}-[0-9a-f]{16}\.json$"
)


def clear_disk_cache(settings: Settings | None = None) -> int:
    """Delete every persisted run, of every cache version this module has ever written, and return how
    many files were removed.

    **Version-agnostic on purpose.** This glob used to be scoped to `f"{_DISK_CACHE_VERSION}-*.json"`
    -- only the *current* build's version -- which meant every earlier version bump orphaned its own
    files here instead of clearing them: an operator pressing "clear cache" got a directory that looked
    cleared (`removed` reported honestly) while `v1` through `v6` entries sat untouched forever, because
    this function could never see filenames that did not start with whatever `_DISK_CACHE_VERSION` was
    at call time. `data/cache/paperdesk` had accumulated roughly a hundred files this way, some of them
    `v1`/`v2` entries from builds long since replaced. This is the case the docstring below already
    named this function for -- "a changed mandate, a corrected engine" -- an operator asking for a
    clean slate should get one regardless of which prior versions ever wrote into this directory, not a
    slate that is clean only of the newest layer.

    Matching :data:`_CACHE_FILENAME_RE` rather than a bare `*.json` glob keeps this safe: only files
    shaped exactly like this module's own cache entries are removed, so a stray or future `.json` file
    that some other tool ever drops into this same directory is left alone rather than swept up by an
    unqualified wildcard.

    For the case the cache key cannot see -- a changed mandate, a corrected engine -- and for tests.
    """
    root = _disk_cache_dir(settings or get_settings())
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.glob("*.json"):
        if not _CACHE_FILENAME_RE.match(path.name):
            continue
        path.unlink()
        removed += 1
    return removed


def _cached_run(
    card: StrategyCard, *, settings: Settings, mandate: Mandate, window: _Window
) -> AgentResult:
    key = (
        card.agent_id,
        window.inception,
        window.as_of,
        window.latest_bar,
        _run_cache_digest(card, starting_cash=mandate.starting_cash),
    )

    if settings.paperdesk_live_fills:
        # **The live-fills trap.** This cache's whole premise is that `(agent_id, window, card
        # digest)` is a complete description of a run's inputs -- see this module's docstring on "the
        # desk's result is a pure function of its inputs". `Settings.paperdesk_live_fills` breaks that
        # premise: it lets `PaperBroker.submit` (via a live-quote seam not wired into `run_card` by
        # this key's own inputs) price a fill off whatever the market is doing at the moment the
        # request is served, which is not a function of the card, the window or the stored bars at
        # all -- it changes from one call to the next with nothing in `key` moving to say so. Serving
        # such a run from either cache tier would freeze that one live price and hand it back
        # indefinitely, which is exactly the "desk shows a 'live' fill that silently never updates"
        # failure this flag's own rollout must not walk into.
        #
        # The fix is exclusion, not a wider key: a quote timestamp folded into `key` would still write
        # *something* to the disk tier under a key no later request will ever ask for again, growing
        # that directory without bound for a result that is by design never looked at twice. Bypassing
        # both tiers entirely -- neither read nor written -- costs a fresh `run_card` call per request
        # while this flag is on, which is the correct price for a run that cannot be memoised at all.
        #
        # With the flag at its default `False` this branch is never taken and every call below is
        # unchanged from before this flag existed -- see `tests/test_paper_live_fill.py` for the test
        # proving both halves of that claim.
        return _compute_and_store(
            card, settings=settings, mandate=mandate, window=window, key=key, cache=False
        )

    cached = _RUN_CACHE.get(key)
    if cached is not None:
        return cached

    with _key_lock(key):
        # Re-check inside the lock: whoever held it before us has just populated both tiers, and the
        # whole point is that the loser of the race reads a result rather than computing a second.
        cached = _RUN_CACHE.get(key)
        if cached is not None:
            return cached
        return _compute_and_store(card, settings=settings, mandate=mandate, window=window, key=key)


def _compute_and_store(
    card: StrategyCard,
    *,
    settings: Settings,
    mandate: Mandate,
    window: _Window,
    key: tuple[str, dt.date, dt.date, dt.date, str],
    cache: bool = True,
) -> AgentResult:
    """Read the disk tier, or run the card and persist it. Called only under `key`'s lock -- except
    the `cache=False` call from `_cached_run`'s live-fills branch above, which takes no lock at all,
    because nothing it does touches either cache tier for another caller to race against.

    `cache=False` (see that branch) skips the disk read, the in-memory write and the disk write in
    their entirety: `run_card` is called and its result handed straight back, every time, for exactly
    the reason stated there.
    """
    path = _disk_cache_path(settings, key)
    if cache and path.is_file():
        try:
            result = AgentResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A truncated or stale-shaped entry must never take the desk down: fall through and
            # recompute, and let the write below replace it.
            pass
        else:
            _RUN_CACHE[key] = result
            return result

    result = run_card(card, settings=settings, mandate=mandate, start=window.inception, end=window.as_of)
    if not cache:
        return result
    _RUN_CACHE[key] = result
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file in the same directory and replace, so a reader never observes a
        # half-written entry -- two workers warming the same desk at once is the ordinary case, not
        # an exotic one.
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(result.model_dump_json(), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        # A read-only or full cache directory is a degraded cache, not a failed request.
        pass
    return result


# ---------------------------------------------------------------------------
# The ladder's own cache tier -- a parallel, not a shared, structure.
#
# `_RUN_CACHE`/`_disk_cache_path`/`_compute_and_store` above are typed to `AgentResult`, and a
# `LadderCard` run produces a `LadderResult` instead -- a differently-shaped payload that a plain
# `AgentResult.model_validate_json(...)` would either reject outright or, worse, half-parse into
# nonsense (a ladder result's `card` object has none of `StrategyCard`'s required fields). Rather than
# widen `_RUN_CACHE`'s value type to a union and have every reader of it re-discover which branch it
# got, this module keeps a second, identically-shaped cache tier for ladder results specifically --
# same in-memory dict + per-key lock + disk-tier-behind-it structure as the rules-card tier above, the
# same reasoning (a cold run costs real seconds; a second concurrent run of the same card is a
# resource hazard, not merely wasteful -- see `_LOCKS`'s own docstring), duplicated rather than
# parameterised because a generic "cache of T" here would need its caller to pass in both the runner
# function and the model class to validate against, which is exactly as much code as the sixty lines
# below and considerably harder to read at the call site in :func:`_compute`.
_LADDER_RUN_CACHE: dict[tuple[str, dt.date, dt.date, dt.date, str], LadderResult] = {}
_LADDER_LOCKS: dict[tuple[str, dt.date, dt.date, dt.date, str], threading.Lock] = {}
_LADDER_LOCKS_GUARD = threading.Lock()


#: The allocation tier's own caches, parallel to the ladder tier's, for the same reason: an
#: `AllocationResult` is a different pydantic model from an `AgentResult`, and a single dict typed to
#: hold either would defeat the point of validating what comes back off disk.
_ALLOCATION_RUN_CACHE: dict[tuple[str, dt.date, dt.date, dt.date, str], AllocationResult] = {}
_ALLOCATION_LOCKS: dict[tuple[str, dt.date, dt.date, dt.date, str], threading.Lock] = {}
_ALLOCATION_LOCKS_GUARD = threading.Lock()


def _allocation_key_lock(key: tuple[str, dt.date, dt.date, dt.date, str]) -> threading.Lock:
    with _ALLOCATION_LOCKS_GUARD:
        return _ALLOCATION_LOCKS.setdefault(key, threading.Lock())


def _allocation_disk_cache_path(
    settings: Settings, key: tuple[str, dt.date, dt.date, dt.date, str]
) -> Path:
    """Same directory as :func:`_disk_cache_path`, with an `allocation-` filename infix -- the same
    device :func:`_ladder_disk_cache_path` uses, so three tiers' files never collide on disk and
    :func:`_compute_and_store_allocation` never has to guess which model a file validates against."""
    agent_id, inception, as_of, latest_bar, digest = key
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in agent_id)
    name = (
        f"{_DISK_CACHE_VERSION}-allocation-{safe}-{inception:%Y%m%d}-{as_of:%Y%m%d}-"
        f"{latest_bar:%Y%m%d}-{digest}.json"
    )
    return _disk_cache_dir(settings) / name


def _cached_allocation_run(
    card: AllocationCard, *, settings: Settings, mandate: Mandate, window: _Window
) -> AllocationResult:
    """The allocation-card counterpart to :func:`_cached_run` -- identical structure, a third tier."""
    key = (
        card.agent_id,
        window.inception,
        window.as_of,
        window.latest_bar,
        _run_cache_digest(card, starting_cash=mandate.starting_cash),
    )
    cached = _ALLOCATION_RUN_CACHE.get(key)
    if cached is not None:
        return cached

    with _allocation_key_lock(key):
        cached = _ALLOCATION_RUN_CACHE.get(key)
        if cached is not None:
            return cached
        return _compute_and_store_allocation(
            card, settings=settings, mandate=mandate, window=window, key=key
        )


def _compute_and_store_allocation(
    card: AllocationCard,
    *,
    settings: Settings,
    mandate: Mandate,
    window: _Window,
    key: tuple[str, dt.date, dt.date, dt.date, str],
) -> AllocationResult:
    """The allocation counterpart to :func:`_compute_and_store`. Called only under `key`'s lock."""
    path = _allocation_disk_cache_path(settings, key)
    if path.is_file():
        try:
            result = AllocationResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            _ALLOCATION_RUN_CACHE[key] = result
            return result

    result = run_allocation(
        card, settings=settings, mandate=mandate, start=window.inception, end=window.as_of
    )
    _ALLOCATION_RUN_CACHE[key] = result
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(result.model_dump_json(), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return result


def _ladder_key_lock(key: tuple[str, dt.date, dt.date, dt.date, str]) -> threading.Lock:
    with _LADDER_LOCKS_GUARD:
        return _LADDER_LOCKS.setdefault(key, threading.Lock())


def _ladder_disk_cache_path(
    settings: Settings, key: tuple[str, dt.date, dt.date, dt.date, str]
) -> Path:
    """Same directory as :func:`_disk_cache_path`, but a `ladder-` filename infix -- so a ladder
    entry and a rules entry sharing an otherwise-identical key (same agent id would not happen in
    practice, since agent ids are unique across the whole roster, but the infix also means the two
    tiers' files are trivially distinguishable by eye in the cache directory) never collide on disk,
    and so :func:`_compute_and_store_ladder` never has to guess which pydantic model a given file on
    disk should validate against."""
    agent_id, inception, as_of, latest_bar, digest = key
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in agent_id)
    name = (
        f"{_DISK_CACHE_VERSION}-ladder-{safe}-{inception:%Y%m%d}-{as_of:%Y%m%d}-"
        f"{latest_bar:%Y%m%d}-{digest}.json"
    )
    return _disk_cache_dir(settings) / name


def _cached_ladder_run(
    card: LadderCard, *, settings: Settings, mandate: Mandate, window: _Window
) -> LadderResult:
    """The ladder-card counterpart to :func:`_cached_run` -- identical structure, a separate tier."""
    key = (
        card.agent_id,
        window.inception,
        window.as_of,
        window.latest_bar,
        _run_cache_digest(card, starting_cash=mandate.starting_cash),
    )
    cached = _LADDER_RUN_CACHE.get(key)
    if cached is not None:
        return cached

    with _ladder_key_lock(key):
        cached = _LADDER_RUN_CACHE.get(key)
        if cached is not None:
            return cached
        return _compute_and_store_ladder(card, settings=settings, mandate=mandate, window=window, key=key)


def _compute_and_store_ladder(
    card: LadderCard,
    *,
    settings: Settings,
    mandate: Mandate,
    window: _Window,
    key: tuple[str, dt.date, dt.date, dt.date, str],
) -> LadderResult:
    """The ladder-card counterpart to :func:`_compute_and_store`. Called only under `key`'s lock."""
    path = _ladder_disk_cache_path(settings, key)
    if path.is_file():
        try:
            result = LadderResult.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            _LADDER_RUN_CACHE[key] = result
            return result

    result = run_ladder_card(
        card, settings=settings, mandate=mandate, start=window.inception, end=window.as_of
    )
    _LADDER_RUN_CACHE[key] = result
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(result.model_dump_json(), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return result


def warm(settings: Settings | None = None) -> None:
    """Compute and persist the desk in the background, so no user pays the cold cost.

    Called from the application's lifespan on a daemon thread. Swallows everything: a warm that
    fails must not stop the server from starting, and the next request simply computes as it always
    did.
    """

    def _run() -> None:
        # Suppressing everything is the point: this thread has no caller to raise to, and a warm
        # that fails must leave the server started and the next request computing as it always did.
        with contextlib.suppress(Exception):
            state(settings)

    threading.Thread(target=_run, name="paperdesk-warm", daemon=True).start()


# ---------------------------------------------------------------------------
# Live session -- today's already-computed signals, executed against a live quote
# ---------------------------------------------------------------------------
#
# This is the piece `run_card` structurally cannot produce (see this module's own docstring's
# "Real-time" section and `tests/test_paper_live_fill.py`'s module docstring): the session dated
# *after* `window.as_of` -- decided on the newest stored close, meant to fill today -- never exists
# in `run_card`'s own `SessionCalendar`, because a session only exists for a date the benchmark has a
# stored bar for. `run_card` is off-limits for this change, so this lives here instead, on top of its
# already-replayed result rather than inside its loop.
#
# **A recomputed projection, never a persisted execution.** The paper desk keeps no trade ledger of
# its own -- every call to `_build_desk` replays the same stored bars into the same `AgentResult` --
# and this is no different in kind: a fresh `PaperBroker` is built, seeded from that replay's own
# ending cash and positions, asked to fill today's already-fired signals, and thrown away. Nothing
# here is written to disk, and nothing here is cached (see `Settings.paperdesk_live_fills`'s own
# docstring on why the surrounding `AgentResult` cache is bypassed entirely while this flag is on).

_LIVE_QUOTE_SOURCE: LiveQuoteSource | None = None
_LIVE_QUOTE_SOURCE_LOCK = threading.Lock()


def _live_quote_source(settings: Settings) -> LiveQuoteSource:
    """The process-wide `app.market.live.LiveQuoteSource` behind the desk's live session -- built
    lazily and shared across requests, the same shape `app.api.paperlive._source` uses for the same
    reason: `PollingQuoteSource` starts a background poll thread on first use, so a fresh instance per
    request would mean a fresh thread per request, leaked on every call. Only ever reached while
    `Settings.paperdesk_live_fills` is on. Tests replace this whole accessor
    (`monkeypatch.setattr(desk, "_live_quote_source", lambda settings: stub)`) rather than the module
    singleton it guards -- the same pattern `tests/test_api_paperlive.py` already uses for
    `app.api.paperlive._source`, and never a real network call."""
    global _LIVE_QUOTE_SOURCE
    with _LIVE_QUOTE_SOURCE_LOCK:
        if _LIVE_QUOTE_SOURCE is None:
            _LIVE_QUOTE_SOURCE = build_source(settings)
        return _LIVE_QUOTE_SOURCE


def _live_session(
    card: StrategyCard,
    result: AgentResult,
    *,
    settings: Settings,
    window: _Window,
    mandate: Mandate,
    signals: list[Signal],
    holdings: list[Holding],
    cash: Decimal,
    today: dt.date,
) -> tuple[list[LiveFill], list[DeskRejection], str | None]:
    """Submit today's already-computed `signals` against a live quote, on top of a fresh
    `PaperBroker` seeded from this desk's own replayed end-state -- never against `result` or
    `holdings` themselves, which stay exactly as `run_card` produced them (see this section's own
    comment, and `Desk.live_fills`'s docstring, for why the two must never mix).

    **Approximation, stated once here:** the broker seeded below carries `cash`/`holdings` forward
    but starts with empty `fills`/`rejections` history and no unsettled-proceeds ledger -- a live sell
    this session therefore reads as fully settled cash for a live buy later in the *same* session,
    which is never true of a same-day round trip in the real historical replay. This mirrors exactly
    the one thing a persisted broker state would track and a stateless recompute cannot; it is the
    correct trade for "no persistence layer" (see this module's own scope) and affects only the rare
    session where a live sell and a live buy fire together.

    Returns `([], [], None)` whenever nothing in `signals` actually fires (the ordinary case on most
    days) or the live source itself fails outright -- a live-quote provider outage must degrade this
    request's live session to empty, not take the whole page down; the historical figures above have
    already been fully computed by the time this runs.
    """
    symbols_needed = sorted(
        {s.symbol for s in signals if (s.held and s.exit_fires) or (s.entry_fires and not s.held)}
    )
    if not symbols_needed:
        return [], [], None

    source = _live_quote_source(settings)
    try:
        batch = source.snapshot(symbols_needed)
    except Exception:
        logger.warning("paperdesk: live quote snapshot failed for %s, skipping the live session", card.agent_id)
        return [], [], None
    quote_ts_by_symbol = {q.symbol.upper(): q.ts for q in batch.quotes}

    broker = PaperBroker(mandate)
    broker.cash = cash
    broker.positions = {h.symbol: h.quantity for h in holdings if h.quantity > 0}
    decision_market = AsOfMarket(as_of=window.as_of, settings=settings)

    order_seq = 0

    def _order_id(symbol: str, side: str) -> str:
        nonlocal order_seq
        order_seq += 1
        return f"{card.agent_id}-live-{today.isoformat()}-{order_seq}-{side}-{symbol}"

    fills: list[Fill] = []

    # Exits before any new entry is even considered -- the same precedence `run_card`'s own session
    # loop gives a historical session (see that function's own comment at its exits block).
    for signal in signals:
        if not (signal.held and signal.exit_fires):
            continue
        quantity = broker.positions.get(signal.symbol, Decimal(0))
        if quantity <= 0:
            continue
        order = Order(
            order_id=_order_id(signal.symbol, "sell"),
            session=result.sessions + 1,
            decided_on=window.as_of,
            symbol=signal.symbol,
            side="sell",
            quantity=quantity,
            thesis=f"exit rule fired for {signal.symbol} ({card.agent_id}) -- live session",
            invalidation="n/a -- this order closes a position, it does not open one",
        )
        outcome = broker.submit(
            order, market=decision_market, fill_date=today, live_quote_source=source, today=today
        )
        if isinstance(outcome, Fill):
            fills.append(outcome)

    # Entries, up to the card's own slot count -- mirroring `run_card`'s own loop, sized off the
    # decision-session close (`signal.last_close`) exactly as `_signals`'s own `blocked` heuristic and
    # `run_card`'s real sizing both are, never off the live price a symbol happens to fill at.
    position_notional = card.position_pct * result.starting_equity
    for signal in signals:
        if len(broker.positions) >= card.max_positions:
            break
        if not (signal.entry_fires and not signal.held):
            continue
        if signal.last_close is None:
            continue
        quantity = _entry_quantity(mandate, position_notional, signal.last_close)
        if quantity <= 0:
            continue
        order = Order(
            order_id=_order_id(signal.symbol, "buy"),
            session=result.sessions + 1,
            decided_on=window.as_of,
            symbol=signal.symbol,
            side="buy",
            quantity=quantity,
            thesis=f"entry rule fired for {signal.symbol} ({card.agent_id}): {card.entry} -- live session",
            invalidation=(
                f"stop_loss_pct={card.stop_loss_pct}, take_profit_pct={card.take_profit_pct}, "
                f"max_hold_days={card.max_hold_days}, exit={card.exit!r}"
            ),
        )
        outcome = broker.submit(
            order, market=decision_market, fill_date=today, live_quote_source=source, today=today
        )
        if isinstance(outcome, Fill):
            fills.append(outcome)

    live_fills = [
        LiveFill(
            symbol=fill.symbol,
            side=fill.side,
            quantity=format(fill.quantity, "f"),
            price=format(fill.price, "f"),
            quote_price=format(fill.reference_open, "f"),
            quote_ts=(
                quote_ts_by_symbol[fill.symbol.upper()].isoformat()
                if fill.symbol.upper() in quote_ts_by_symbol
                else batch.as_of.isoformat()
            ),
            notional=format(fill.gross, "f"),
        )
        for fill in fills
    ]
    # `PaperBroker.rejections` holds `Rejection`, not `RejectionRecord` -- structurally alike
    # (`rule`/`symbol`/`reason`, the only three fields `_group_rejections` reads) but a
    # different type. Converted the same way `app.tournament.allocation` already does when it
    # fills `AgentResult.rejection_details`, rather than relying on the resemblance holding.
    live_rejections, _ = _group_rejections(
        RejectionRecord(rule=r.rule, symbol=r.symbol, reason=r.reason) for r in broker.rejections
    )
    return live_fills, live_rejections, batch.as_of.isoformat()


# ---------------------------------------------------------------------------
# Assembling one desk, and the whole response
# ---------------------------------------------------------------------------


def _as_calendar_date(value: dt.date | dt.datetime) -> dt.date:
    """`value.date()` when `value` is a `datetime` (checked first: `datetime` is itself a `date`
    subclass, so the naive `isinstance(value, dt.date)` order would misclassify it), otherwise
    `value` unchanged. `RealisedTrade.entry_date`/`.exit_date` are a calendar `date` for every daily
    run this application performs and a full `datetime` only for an intraday one -- see that field's
    own docstring -- and `app.paper.papertax` keys everything on calendar dates, so this is the one
    normalisation :func:`_fills_from_trades` needs before handing dates to it."""
    if isinstance(value, dt.datetime):
        return value.date()
    return value


def _fills_from_trades(result: AgentResult) -> list[Fill]:
    """Synthesise the :class:`~app.paper.paperbroker.Fill` sequence `app.paper.papertax.
    summarize_paper_tax` needs, out of `result.trades` -- because the tournament runner records only
    the closed round trip (:class:`~app.tournament.models.RealisedTrade`), not the underlying fills
    that produced it, and the tax engine's cost-basis / wash-sale math is built on fills.

    One `"buy"` fill at `(entry_date, entry_price, quantity)` per trade, and -- **only** when
    `exit_date is not None`, i.e. the trade actually closed -- one `"sell"` fill at
    `(exit_date, exit_price, quantity)`. A trade still open at the trading window's end
    (`exit_reason == "open_at_end"`, `exit_date is None`) contributes its buy alone: correctly no
    realised gain, since nothing has been sold yet.

    **Dates are normalised to calendar dates** (`dt.datetime` -> `.date()`, see
    :func:`_as_calendar_date`) because the tax engine keys everything on calendar dates, never a
    timestamp. **`Money`/`Quantity` fields are coerced to plain `Decimal`** before being placed on a
    `Fill`, since `Money`/`Quantity` are themselves `Decimal`-based annotated types rather than the
    bare type `Fill`'s own dataclass fields declare.

    `gross` is `quantity * price` rounded to the cent (:func:`_money`, half-up -- this module's one
    rounding convention, applied everywhere else a cash figure becomes one). `reference_open` is set
    equal to `price`: a synthesised fill has no separate unslipped-open figure to report, and `price`
    is the only number this bridge actually has. `cash_delta` is `-gross` for the buy leg and `+gross`
    for the sell leg, matching `Fill.cash_delta`'s own sign convention.

    **Fees are set to zero, and this is the one lossy part of this bridge -- deliberately, not by
    oversight.** `RealisedTrade` nets its entry and exit commissions straight into `pnl`
    (`app.tournament.runner`) and exposes no way to recover either leg's fee in isolation, so there is
    no real fee figure this function could put on either synthesised fill without inventing one. The
    holding-period split and wash-sale detection :func:`summarize_paper_tax` computes from these fills
    are exact regardless -- both depend only on dates and prices, never fees -- but the resulting
    after-tax figure omits the paper broker's own per-leg regulatory fees (SEC Section 31 / FINRA TAF,
    a few cents per sell). See :data:`_TAX_FEE_NOTE`, which states this same caveat on the desk's own
    book-level `notes` rather than leaving it only in this docstring.

    **`order_id` is synthetic but stable, and `session` is a monotonic index over a deterministic
    sort.** `result.trades` is sorted here by `(entry_date, symbol)` before fills are built, so calling
    this twice on the same `result` produces byte-identical output regardless of what order
    `result.trades` happened to arrive in -- the same purity guarantee `app.paper.papertax.
    fills_to_transactions`'s own internal `(trade_date, session, order_id)` re-sort depends on to be
    stable. `session` counts fills (not trades) in that order, two per closed trade and one per open
    one, so it stays monotonic across the whole sequence.
    """
    ordered = sorted(result.trades, key=lambda t: (_as_calendar_date(t.entry_date), t.symbol))

    fills: list[Fill] = []
    session = 0
    for index, trade in enumerate(ordered):
        quantity = Decimal(trade.quantity)
        entry_price = Decimal(trade.entry_price)
        entry_date = _as_calendar_date(trade.entry_date)
        entry_gross = _money(quantity * entry_price)
        fills.append(
            Fill(
                order_id=f"paperdesk-synthetic-{index}-{trade.symbol}-entry",
                session=session,
                trade_date=entry_date,
                symbol=trade.symbol,
                side="buy",
                quantity=quantity,
                price=entry_price,
                reference_open=entry_price,
                gross=entry_gross,
                fees=Decimal("0"),
                cash_delta=-entry_gross,
            )
        )
        session += 1

        if trade.exit_date is not None:
            # `exit_price` is never `None` when `exit_date` isn't -- `RealisedTrade` sets both
            # together for every closed trade (see that class's own docstring) -- but the type is
            # `Money | None`, so this satisfies the type checker without asserting.
            exit_price = Decimal(trade.exit_price) if trade.exit_price is not None else entry_price
            exit_date = _as_calendar_date(trade.exit_date)
            exit_gross = _money(quantity * exit_price)
            fills.append(
                Fill(
                    order_id=f"paperdesk-synthetic-{index}-{trade.symbol}-exit",
                    session=session,
                    trade_date=exit_date,
                    symbol=trade.symbol,
                    side="sell",
                    quantity=quantity,
                    price=exit_price,
                    reference_open=exit_price,
                    gross=exit_gross,
                    fees=Decimal("0"),
                    cash_delta=exit_gross,
                )
            )
            session += 1

    return fills


#: The fee-omission caveat :func:`_fills_from_trades`'s docstring describes, restated on the wire via
#: a book's own `notes` -- appended in :func:`_book` whenever any of that book's desks actually carries
#: a `tax` summary. Named as a constant, not inlined, so the one sentence a reader needs to not
#: over-trust the after-tax figure exists in exactly one place.
_TAX_FEE_NOTE = (
    "After-tax figures on this book's rules desks (see each desk's 'tax' block) are computed by the "
    "real cost-basis / wash-sale tax engine over fills synthesised from each closed trade's entry and "
    "exit. Holding-period splits and wash-sale detection are exact -- both depend only on dates and "
    "prices -- but the synthesised fills carry zero fees, so the after-tax figure omits the paper "
    "broker's own per-leg regulatory fees (a few cents per sell)."
)


def _build_desk(
    card: StrategyCard,
    result: AgentResult,
    *,
    settings: Settings,
    window: _Window,
    mandate: Mandate | None = None,
    today: dt.date | None = None,
    taxable: bool = False,
) -> Desk:
    """`mandate`/`today` are only consulted for the live session (see `_live_session`) and both
    default rather than being required, so every pre-existing call site -- `_book` below, and every
    test that built a `Desk` before this feature existed -- keeps working unchanged. `mandate`
    defaults to `_mandate(card.purpose)`, the identical mandate `_book` itself would have passed;
    `today` defaults to `dt.date.today()`, injectable here (and by extension from `_book`/`_compute`/
    `state`/`refresh`, which all thread it through unchanged) precisely so a test never depends on the
    real wall clock -- the same reason `PaperBroker.submit`'s own `today` parameter exists.

    `taxable` defaults to `False` for the identical backward-compatibility reason: every test that
    called this function before `Desk.tax` existed passes no such argument and must keep getting
    `tax=None` back unchanged. `_book` is the one real caller and passes `True` exactly when this
    desk's book is a taxable one (`PurposeSpec.tax_treatment == TaxTreatment.TAXABLE`, i.e. `SAVINGS`
    or `TRADING`) -- see `Desk.tax`'s own docstring for the full populated-iff condition.

    **A tax-summary failure degrades to `tax=None` with a logged warning and never propagates.** This
    application has a recorded incident (see this module's own docstring, and `_overlay_agent_ids`'s)
    where trusting one panel's computation enough to let it raise took the whole page down over a
    single bad value; a wash-sale summary is exactly one more such panel, not a reason to relearn that
    lesson a second time.
    """
    holdings = _holdings(
        result.trades,
        settings=settings,
        as_of=window.as_of,
        stop_loss_pct=card.stop_loss_pct,
        take_profit_pct=card.take_profit_pct,
        max_hold_days=card.max_hold_days,
    )

    equity = result.ending_equity
    positions_value = _money(sum((h.market_value for h in holdings), Decimal(0)))
    cash = equity - positions_value

    # `weight` needs `equity`, which is only known once every holding above is summed -- filled in
    # as a second pass rather than threading `equity` through `_holdings` for one field.
    holdings = [
        h.model_copy(update={"weight": float(h.market_value / equity) if equity > 0 else 0.0})
        for h in holdings
    ]

    total_return = (equity / result.starting_equity) - Decimal(1)
    excess_return = (
        total_return - result.benchmark_return if result.benchmark_return is not None else None
    )

    realised_pnl = _money(
        sum((t.pnl for t in result.trades if t.exit_reason != "open_at_end"), Decimal(0))
    )
    unrealised_pnl = _money(sum((h.unrealised_pnl for h in holdings), Decimal(0)))

    signals = _signals(
        card, result, settings=settings, window=window, holdings=holdings, cash=cash
    )

    rejections, rejection_count = _group_rejections(result.rejection_details)

    tax: PaperTaxSummary | None = None
    if taxable:
        try:
            short_rate, long_rate, _rate_basis = resolve_configured_rates(settings)
            tax = summarize_paper_tax(
                _fills_from_trades(result),
                start=window.inception,
                end=window.as_of,
                short_term_rate=short_rate,
                long_term_rate=long_rate,
            )
        except Exception:
            logger.warning(
                "paperdesk: tax summary failed for %r over %s..%s, leaving tax=None",
                card.agent_id,
                window.inception.isoformat(),
                window.as_of.isoformat(),
                exc_info=True,
            )
            tax = None

    live_fills: list[LiveFill] = []
    live_rejections: list[DeskRejection] = []
    live_as_of: str | None = None
    if settings.paperdesk_live_fills:
        resolved_mandate = mandate if mandate is not None else _mandate(card.purpose)
        resolved_today = today if today is not None else dt.date.today()
        live_fills, live_rejections, live_as_of = _live_session(
            card,
            result,
            settings=settings,
            window=window,
            mandate=resolved_mandate,
            signals=signals,
            holdings=holdings,
            cash=cash,
            today=resolved_today,
        )

    return Desk(
        agent_id=card.agent_id,
        display_name=card.display_name,
        discipline=card.discipline.value,
        thesis=card.thesis,
        kind="rules",
        universe=list(card.universe),
        entry=card.entry,
        exit=card.exit,
        stop_loss_pct=card.stop_loss_pct,
        take_profit_pct=card.take_profit_pct,
        max_hold_days=card.max_hold_days,
        max_positions=card.max_positions,
        position_pct=card.position_pct,
        rank_by=card.rank_by,
        starting_equity=result.starting_equity,
        cash=cash,
        positions_value=positions_value,
        equity=equity,
        total_return=total_return,
        excess_return=excess_return,
        max_drawdown=result.max_drawdown,
        capital_exposure=result.capital_exposure,
        realised_pnl=realised_pnl,
        unrealised_pnl=unrealised_pnl,
        open_positions=len(holdings),
        slots_free=card.max_positions - len(holdings),
        holdings=holdings,
        trades=_closed_trades(result.trades),
        decisions=_decisions(result.trades),
        signals=signals,
        rejections=rejections,
        rejection_count=rejection_count,
        live_fills=live_fills,
        live_rejections=live_rejections,
        live_as_of=live_as_of,
        tax=tax,
    )


def _ladder_signals(
    card: LadderCard, *, settings: Settings, window: _Window, holdings: list[Holding]
) -> list[Signal]:
    """Every sleeve's current standing for a ladder desk -- `held`/`last_close` are read the same way
    :func:`_signals` reads them for a rules card, but `entry_fires`/`exit_fires` are always `False`
    here, deliberately, rather than an invented approximation.

    A rules card's signal is a single boolean re-evaluated fresh off `card.entry`/`.exit` at
    `window.as_of` (see `_signals`'s own docstring). There is no equivalent boolean for a ladder card
    to re-evaluate: its "next decision" is not a per-symbol rule at all, it is the state machine's own
    *carried state* -- which rung is armed, whether a recovery clock is running, how far the signal
    sits above or below its own confirmation average -- evaluated one session further forward. That
    state lives inside `run_ladder_card`'s own session loop and is not part of `LadderResult` today, so
    reproducing a genuine "would a rung fire, or the recovery clock close out, at the next close" flag
    here would mean either replaying the entire multi-year backtest a second time to recover four
    numbers, or threading a new field through `LadderResult` -- both legitimate future changes, neither
    justified by what this one needs: this desk's own trading window (from `INCEPTION`) has not yet
    seen a SPY drawdown deep enough to test either code path (see this package's own report for what
    the desk actually shows), so both would render identically to what is here regardless. Reporting
    `False` plainly is the honest choice until a caller actually needs the real computation -- a
    fabricated `True` on a signal this function cannot stand behind would be worse than an admittedly
    incomplete `False`.
    """
    held_symbols = {h.symbol for h in holdings}
    market = AsOfMarket(as_of=window.as_of, settings=settings)
    signals: list[Signal] = []
    for symbol in card.universe:
        held = symbol in held_symbols
        try:
            last_close = market.close(symbol)
        except UnpricedSymbol:
            signals.append(
                Signal(
                    symbol=symbol,
                    held=held,
                    entry_fires=False,
                    exit_fires=False,
                    last_close=None,
                    blocked="no price",
                )
            )
            continue
        signals.append(
            Signal(
                symbol=symbol,
                held=held,
                entry_fires=False,
                exit_fires=False,
                last_close=last_close,
                blocked=None,
            )
        )
    return signals


def _build_ladder_desk(
    card: LadderCard, result: LadderResult, *, settings: Settings, window: _Window
) -> Desk:
    """The `kind == "ladder"` counterpart to :func:`_build_desk`. Every figure that means the same
    thing regardless of card shape (equity, cash, P&L, holdings, trades, decisions) is computed the
    identical way; the only real branch is what replaces `entry`/`exit`/`max_positions`/`position_pct`
    (the :attr:`~app.paperdesk.models.Desk.ladder` block, see :class:`LadderDescription`) and what
    replaces a rules card's boolean signal (see :func:`_ladder_signals`)."""
    holdings = _holdings(
        result.trades,
        settings=settings,
        as_of=window.as_of,
        stop_loss_pct=None,
        take_profit_pct=None,
        max_hold_days=None,
    )

    equity = result.ending_equity
    positions_value = _money(sum((h.market_value for h in holdings), Decimal(0)))
    cash = equity - positions_value

    holdings = [
        h.model_copy(update={"weight": float(h.market_value / equity) if equity > 0 else 0.0})
        for h in holdings
    ]

    total_return = (equity / result.starting_equity) - Decimal(1)
    excess_return = (
        total_return - result.benchmark_return if result.benchmark_return is not None else None
    )

    realised_pnl = _money(
        sum((t.pnl for t in result.trades if t.exit_reason != "open_at_end"), Decimal(0))
    )
    unrealised_pnl = _money(sum((h.unrealised_pnl for h in holdings), Decimal(0)))

    signals = _ladder_signals(card, settings=settings, window=window, holdings=holdings)

    ladder_description = LadderDescription(
        signal_symbol=card.signal_symbol,
        defensive_symbol=card.defensive_symbol,
        bond_symbol=card.bond_symbol,
        leveraged_symbol=card.leveraged_symbol,
        base_defensive_weight_pct=card.base_defensive_weight,
        base_bond_weight_pct=card.base_bond_weight,
        rungs=[
            LadderRungDescription(drawdown_pct=r.drawdown, leveraged_weight_pct=r.leveraged_weight)
            for r in card.rungs
        ],
        confirm_ma_sessions=card.confirm_ma,
        ath_haircut_pct=card.ath_haircut,
        recovery_gain_pct=card.recovery_gain,
        recovery_sessions=card.recovery_sessions,
    )

    rejections, rejection_count = _group_rejections(result.rejection_details)

    return Desk(
        agent_id=card.agent_id,
        display_name=card.display_name,
        discipline="drawdown-ladder",
        thesis=card.thesis,
        kind="ladder",
        universe=list(card.universe),
        entry=None,
        exit=None,
        stop_loss_pct=None,
        take_profit_pct=None,
        max_hold_days=None,
        max_positions=None,
        position_pct=None,
        ladder=ladder_description,
        starting_equity=result.starting_equity,
        cash=cash,
        positions_value=positions_value,
        equity=equity,
        total_return=total_return,
        excess_return=excess_return,
        max_drawdown=result.max_drawdown,
        capital_exposure=result.capital_exposure,
        realised_pnl=realised_pnl,
        unrealised_pnl=unrealised_pnl,
        open_positions=len(holdings),
        # No `max_positions` for a ladder card (see `Desk.max_positions`'s own docstring) -- "slots
        # free" is read instead as "how many of the three sleeves are not currently held at all",
        # which stays a meaningful, non-misleading number: the base state holds two of three (SCHD,
        # IEF) with QLD at a zero weight, i.e. one slot free, and a fully-leveraged cycle holds all
        # three at once (zero free).
        slots_free=len(card.universe) - len(holdings),
        holdings=holdings,
        trades=_closed_trades(result.trades),
        decisions=_decisions(result.trades),
        signals=signals,
        rejections=rejections,
        rejection_count=rejection_count,
        # A ladder desk never attempts a live session -- see `Desk.live_fills`'s own docstring and
        # this module's scope fence. Populated with their well-formed empty/`None` defaults rather
        # than left to `Desk`'s own field defaults, so a reader of this constructor sees explicitly
        # that the omission is deliberate, not an oversight shared with the rules-card path above.
        live_fills=[],
        live_rejections=[],
        live_as_of=None,
    )


#: Notes that hold regardless of which cards are actually rostered -- none of these name a specific
#: agent id or a specific count of desks, so they need no per-roster computation. See
#: :func:`_single_name_cap_note` and :func:`_candidate_notes` for the two that used to live in this
#: tuple as static prose but, on inspection, named specific cards and specific counts ("two of the
#: three books," "c14-riskmanaged-wide is a library candidate") that only happen to be true for
#: today's default roster -- a roster switch would have kept shipping them verbatim regardless of
#: which cards were actually running, which is exactly the kind of silently-wrong-after-a-config-
#: change bug the audit for this change was looking for.
_EVERGREEN_NOTES: tuple[str, ...] = (
    "'as_of' equals 'latest_bar': the newest stored session is decided on the prior session's close "
    "and filled at its own open, both already in the store, so it is fully tradeable. This desk "
    "shows the most recent stored session, never a live intraday price -- 'stale_days' is how far "
    "behind the calendar that stored session itself is.",
    "'decisions' is reconstructed from filled trades -- run_card records only orders that were "
    "actually submitted, not a per-session deliberation trace. 'signals' covers what each strategy "
    "is currently seeing on every universe symbol, fired or not, held or not.",
    "'signals' are read against the most recent stored close ('as_of') and describe the next "
    "decision, not the last one: an 'entry_fires: true' symbol is one that would be bought at the "
    "following session's open, once that session exists, not one already bought.",
)

_SINGLE_NAME_CAP = Decimal("0.25")
"""The persona's own `max_single_name_weight`, before this desk loosens it -- see `_mandate` and
`_single_name_cap_note` below. Named here, once, rather than repeated as a bare `Decimal("0.25")`
literal at each of this note's two use sites."""


def _build_allocation_desk(
    card: AllocationCard, result: AllocationResult, *, settings: Settings, window: _Window
) -> Desk:
    """An allocation card's desk row.

    Shorter than :func:`_build_desk` because an allocation card declares none of the things that
    function reads off a `StrategyCard`: no `entry`/`exit` expression, no stop, no target, no hold
    cap, no `position_pct`, no `max_positions`. It holds continuous target weights across sleeves
    that are always invested and rebalances a sleeve only when *that sleeve's* own drift exceeds
    `band_pct`. Those fields are therefore `None` here rather than filled with stand-ins -- a `0`
    `max_positions` would read as "this card may hold nothing", which is the opposite of true.

    **No `signals` either, and that is a real gap rather than an oversight.** :func:`_signals`
    answers "would the entry rule fire on this symbol at the newest close", which presumes a per
    symbol boolean rule; an allocation card has no such rule to evaluate. The honest equivalent --
    each sleeve's current weight against its target and how close it sits to its band -- is a
    different computation that does not exist yet, and inventing an empty `signals` list that reads
    as "nothing is firing" would be worse than an empty one that reads as "not applicable to this
    card shape". `kind == "allocation"` is what tells a renderer which of those it is looking at.
    """
    holdings = _holdings(
        result.trades,
        settings=settings,
        as_of=window.as_of,
        stop_loss_pct=None,
        take_profit_pct=None,
        max_hold_days=None,
    )

    equity = result.ending_equity
    positions_value = _money(sum((h.market_value for h in holdings), Decimal(0)))
    cash = equity - positions_value
    holdings = [
        h.model_copy(update={"weight": float(h.market_value / equity) if equity > 0 else 0.0})
        for h in holdings
    ]

    total_return = (equity / result.starting_equity) - Decimal(1)
    excess_return = (
        total_return - result.benchmark_return if result.benchmark_return is not None else None
    )
    realised_pnl = _money(
        sum((t.pnl for t in result.trades if t.exit_reason != "open_at_end"), Decimal(0))
    )
    unrealised_pnl = _money(sum((h.unrealised_pnl for h in holdings), Decimal(0)))

    rejections, rejection_count = _group_rejections(result.rejection_details)

    return Desk(
        agent_id=card.agent_id,
        display_name=card.display_name,
        # An `AllocationCard` has no `discipline` field -- the concept belongs to `StrategyCard`'s
        # taxonomy of rule-based ideas. Naming the shape is more honest than borrowing a label from a
        # classification this card was never placed in.
        discipline="allocation",
        thesis=card.thesis,
        kind="allocation",
        universe=sorted(card.universe),
        starting_equity=result.starting_equity,
        cash=cash,
        positions_value=positions_value,
        equity=equity,
        total_return=total_return,
        excess_return=excess_return,
        max_drawdown=result.max_drawdown,
        capital_exposure=result.capital_exposure,
        realised_pnl=realised_pnl,
        unrealised_pnl=unrealised_pnl,
        open_positions=len(holdings),
        # Read as "how many sleeves are not currently held at all", the same reading
        # `_build_ladder_desk` gives it: an allocation card has no `max_positions` to subtract from.
        slots_free=len(card.universe) - len(holdings),
        holdings=holdings,
        trades=_closed_trades(result.trades),
        decisions=_decisions(result.trades),
        signals=[],
        rejections=rejections,
        rejection_count=rejection_count,
        # An allocation desk never attempts a live session either -- see the identical comment on
        # `_build_ladder_desk`'s own `Desk(...)` call above.
        live_fills=[],
        live_rejections=[],
        live_as_of=None,
    )


def _book_benchmarks(settings: Settings, spec: PurposeSpec, window: _Window) -> list[Benchmark]:
    """The benchmarks one book is measured against, its own primary first.

    The primary comes from :attr:`app.tournament.purposes.PurposeSpec.benchmark` and is priced by
    :func:`app.paperdesk.benchmarks.price_blend`, which composes a fixed-weight basket into one
    return -- so `trading` prices a single-leg SPY blend and the two contribution-funded books price
    a 60/40 SPY/AGG blend. Every entry after the primary is one of the desk-wide reference indices
    (:data:`_BENCHMARKS`), priced the same way they always were.

    A leg that cannot be priced across the whole window is reported as an unpriced benchmark
    (`return_pct=None`) rather than taking the page down: `Benchmark.return_pct` is already
    documented as `None`-when-unpriceable rather than a fabricated zero, and one book unable to price
    its yardstick must not deny a reader the other two books' figures.

    Two distinct failures are caught, because a leg can fall short in two ways and neither is this
    module's to resolve: `InsufficientHistory` when the leg's stored range does not span the window
    (`price_blend` refuses to price a shorter or substituted basket -- see that module's Decision 3),
    and `UnpricedSymbol` when the leg has no stored bar at a boundary at all. Neither is caught to
    paper over a data gap; both surface as a visibly missing number, which is what a stale or
    un-synced symbol should look like.
    """
    blend = BLEND_REGISTRY[spec.benchmark]
    try:
        primary_return: Decimal | None = price_blend(
            blend, start=window.first_session, end=window.as_of, settings=settings
        )
    except (InsufficientHistory, UnpricedSymbol):
        primary_return = None
    primary = Benchmark(symbol=blend.name, return_pct=primary_return, label=blend.label)

    others = [
        Benchmark(symbol=symbol, return_pct=_buy_and_hold(settings, symbol, window), label=label)
        for symbol, label in _BENCHMARKS
        # A single-leg blend *is* its symbol, so listing SPY again under its own name beneath a
        # primary that already prices to SPY would render the same number twice under two labels.
        if not (len(blend.legs) == 1 and blend.legs[0].symbol == symbol)
    ]
    return [primary, *others]


def _card_universe(card: StrategyCard | LadderCard | AllocationCard) -> tuple[str, ...]:
    """The symbols one card can actually end up *holding* -- narrower than :func:`_card_symbols`'s
    "everything this card needs a price for", which deliberately also counts symbols a card only
    watches, never buys: a ladder's `signal_symbol` arms its rungs but is never itself a position, and
    an allocation card's `TiltRule.from_symbol`/`to_symbol` are read there defensively even though
    `app.tournament.allocation` already validates them to be covered by `sleeves`.

    This function answers a different question -- "what basket would an equal-weight buy-and-hold of
    this card's own picks have been" (see :func:`_own_universe_benchmark`) -- which must not include a
    symbol the card was never actually allowed to hold, or the benchmark would be equal-weighting
    something the card itself could never have bought.
    """
    if isinstance(card, LadderCard):
        return (card.defensive_symbol, card.bond_symbol, card.leveraged_symbol)
    if isinstance(card, AllocationCard):
        return tuple(sleeve.symbol for sleeve in card.sleeves)
    return tuple(card.universe)


def _own_universe_benchmark(
    settings: Settings, card: StrategyCard | LadderCard | AllocationCard, window: _Window
) -> Benchmark:
    """One card measured against an equal-weight, buy-once-and-hold, never-rebalanced basket of its
    *own* tradable universe (:func:`_card_universe`) over the same window every other benchmark in
    :func:`_book_benchmarks` is priced over -- `window.first_session` to `window.as_of`.

    **Why this exists.** SPY and QQQ (:data:`_BENCHMARKS`) answer "did this card beat the market";
    neither answers "did this card beat what it was allowed to buy". An audit of this desk's own
    stored bars found the two questions have very different answers for at least one seated card: see
    this function's caller in :func:`_book` for the exact figures. A page reporting only market indices
    cannot show that a card's rules subtracted value relative to its own opportunity set -- this
    benchmark is what makes that visible, per card, without waiting for a full backtest.

    **Unpriced legs are excluded, not fatal** (see `price_equal_weight_basket`'s own docstring) -- a
    card whose universe includes one recently-listed or thinly-covered symbol still gets a benchmark
    computed from the rest, with the exclusion disclosed in `label` rather than silently dropped: the
    `Benchmark` model (`app.paperdesk.models`) has no separate field for "symbols excluded", so this is
    the one place that fact can travel to the page without widening that model.
    """
    universe = _card_universe(card)
    basket = price_equal_weight_basket(
        universe, start=window.first_session, end=window.as_of, settings=settings
    )
    label = f"{card.agent_id}'s own universe, equal-weight buy & hold"
    if basket.excluded:
        label += f" (excluding {', '.join(basket.excluded)}: no stored bars over this window)"
    return Benchmark(
        symbol=f"own_universe_ew:{card.agent_id}",
        return_pct=basket.return_pct,
        label=label,
    )


def _funding_note(spec: PurposeSpec) -> list[str]:
    """Disclose, on the book itself, that contributions are not modelled -- when that is true.

    Empty for a `LUMP_SUM` book, where there is nothing to disclose: the seed goes in at inception and
    that is the whole funding model, faithfully represented. For the other two shapes the desk shows a
    static book while the purpose is defined by a stream of deposits, which is precisely the
    lump-sum-versus-contribution confusion `strategy-program/THREE-PURPOSES-PLAN.md` section 2 exists
    to prevent. See :func:`opening_capital` for the full reasoning.
    """
    if spec.funding_shape is FundingShape.LUMP_SUM:
        return []
    every = "month" if spec.funding_shape is FundingShape.MONTHLY_CONTRIBUTION else "year"
    return [
        f"This book is funded by contributions ({spec.contribution:,.0f} every {every}) and the desk "
        f"does not model them: it trades a static {opening_capital(spec):,.0f} from inception. Over "
        "the desk's current window no contribution is yet due, so no figure here is wrong today -- "
        "but a contribution-funded book measured as a lump sum is being asked the wrong question, "
        "and this note stops applying only when the desk grows a contribution stream."
    ]


def _single_name_cap_note(desks: list[Desk]) -> str:
    """Disclose the persona's 25% single-name cap being loosened to 100% for this desk, and name
    which of the *actually rostered* cards that loosening binds on.

    Computed from the assembled ``desks`` rather than written as prose naming specific agent ids:
    an earlier version of this note hardcoded "B-momentum," "C-trend" and "c14-riskmanaged-wide" by
    name, which was accurate only because those three happened to be the whole roster at the time it
    was written. Once the roster is a configuration value (see :func:`roster`), a note that still
    named those three specific cards after a different four were switched in would misrepresent
    whose risk control was actually loosened -- disclosure that silently goes stale is not
    disclosure. `position_pct * max_positions` is the same product `StrategyCard` itself validates
    (see `app.tournament.models.StrategyCard`'s own `<= 1.001` check); it clears the persona's 25%
    cap on its own only when concentrated in few enough slots.

    **Only ever computed over `kind == "rules"` desks.** `position_pct` and `max_positions` are
    `None` for a ladder desk (see `Desk.position_pct`'s own docstring) -- there is no "fixed notional
    per position" concept to check against the persona's per-position cap at all, because a ladder
    card sizes every sleeve as a weight of the whole book, not a fixed fraction committed per
    position. A ladder desk's own leverage ceiling (how much of the book QLD can reach) is disclosed
    on its own terms in its `ladder` block instead of being forced through a cap this note computes
    for a different sizing model.
    """
    rules_desks = [d for d in desks if d.kind == "rules"]
    ladder_desks = [d for d in desks if d.kind == "ladder"]

    binding = [
        d
        for d in rules_desks
        if d.position_pct is not None
        and d.max_positions is not None
        and d.position_pct * d.max_positions > _SINGLE_NAME_CAP
    ]
    clearing = [d for d in rules_desks if d not in binding]

    if binding:
        sizing = "; ".join(
            f"{d.agent_id} sizes {d.position_pct:.0%} x {d.max_positions} slots = "
            f"{(d.position_pct * d.max_positions):.0%} of the book"  # type: ignore[operator]
            for d in binding
        )
        binds_clause = (
            f"It binds on {len(binding)} of {len(rules_desks)} rules-card book"
            f"{'s' if len(rules_desks) != 1 else ''} here: {sizing}, none of which clears a 25% "
            "single-name cap once concentrated in a handful of names."
        )
    else:
        binds_clause = (
            "It does not currently bind on any rostered rules-card book: every card here already "
            "clears a 25% single-name cap on its own sizing."
        )

    if clearing:
        cleared = ", ".join(
            f"{d.agent_id} ({d.position_pct:.0%} x {d.max_positions})" for d in clearing
        )
        clears_clause = f" {cleared} would have cleared it untouched."
    else:
        clears_clause = ""

    ladder_clause = (
        f" This per-position cap does not apply the same way to "
        f"{', '.join(d.agent_id for d in ladder_desks)} ({'it sizes' if len(ladder_desks) == 1 else 'they size'} "
        "sleeves as weights of the whole book, not a fixed notional per position); its own leverage "
        "ceiling is disclosed in its own rules block instead."
        if ladder_desks
        else ""
    )

    return (
        "The persona's own 25% max_single_name_weight cap is raised to 100% for this desk, matching "
        "app.tournament.__main__'s own default run. "
        f"{binds_clause}{clears_clause}{ladder_clause} The loosening is disclosed rather than silent "
        "because it is a real risk control being removed. Every other mandate rule (cash, "
        "settlement, minimum clip, whole shares, slippage, fees) is untouched."
    )


#: Rostered agent ids that are library *candidates* -- promoted onto this desk on less evidence than
#: `PROTOCOL.md` section 6's two-round bar for a base strategy -- so :func:`_candidate_notes` knows
#: to disclose them if and only if they are actually on the desk. Not derived from `_find_card`'s
#: own tier lookup (``base``/``candidates``): that would mean re-deriving a card's path a second time
#: purely to read which directory it came from, for a fact that changes only when a human promotes or
#: retires a card, not on every request. Whoever promotes ``c14-riskmanaged-wide`` to `library/base/`
#: should remove it from here in the same change -- see `_candidate_notes` for what happens if this
#: set and the library's own layout are allowed to disagree.
_CANDIDATE_AGENT_IDS: frozenset[str] = frozenset(
    {"c14-riskmanaged-wide", "r34-ma-crossover-on", "r40-rsi-confirm-slots6"}
)

#: Why each candidate is on a book at all -- the one clause that differs per card. Keyed separately
#: from :data:`_CANDIDATE_AGENT_IDS` so the membership test above stays a plain set lookup and the
#: prose beside it can say something true about each card rather than one sentence stretched over two.
_CANDIDATE_REASONS: dict[str, str] = {
    "c14-riskmanaged-wide": (
        "It earned a place here on one round's evidence -- round 3's best worst-window and hit "
        "rate -- not on the two rounds PROTOCOL.md section 6 requires for promotion."
    ),
    "r34-ma-crossover-on": (
        "It is here by owner decision, not by any gate: round 34's best cell at +1.24pp median "
        "adjusted excess, a margin inside the programme's 21.2pp noise floor, from a round that "
        "pre-registered that nothing would be promoted (PROTOCOL.md section 9, 2026-09-09)."
    ),
    "r40-rsi-confirm-slots6": (
        "It is here by owner decision, not by any gate: round 40's sole positive cell at +4.82pp "
        "arm-minus-control, inside the 21.2pp noise floor, from a round that concluded the "
        "confirmation conjunct does not pay for itself. Carries a -17.2pp worst window "
        "(PROTOCOL.md section 9, 2026-09-09)."
    ),
}


def _candidate_notes(desks: list[Desk]) -> list[str]:
    """One disclosure note per rostered desk named in :data:`_CANDIDATE_AGENT_IDS`, written to name
    whichever candidate cards are actually on the desk rather than assuming any one by name
    unconditionally, for the same reason :func:`_single_name_cap_note` stopped doing so: a roster swap
    that dropped a candidate must not keep disclosing one that is no longer running.

    If :data:`_CANDIDATE_AGENT_IDS` and the library's own ``base``/``candidates`` layout ever
    disagree -- a card promoted to ``base`` without being removed from this set, or vice versa --
    this function is wrong in the direction of over-disclosing or under-disclosing a tier, not in the
    direction of trading the wrong book; `_find_card` alone decides what actually gets run.
    """
    return [
        f"{d.agent_id} is a library *candidate*, not a base strategy. "
        f"{_CANDIDATE_REASONS.get(d.agent_id, 'It has not met the two-round bar PROTOCOL.md section 6 requires for promotion.')} "
        "Read it as under observation."
        for d in desks
        if d.agent_id in _CANDIDATE_AGENT_IDS
    ]


def _autopilot_notes(desks: list[Desk], spec: PurposeSpec) -> list[str]:
    """Book-level disclosures the autopilot seat forces, or `[]` when no such seat is on this book.

    **Two facts about this seat contradict what the book's own header says, and a reader who is not
    told will read its return against the wrong denominator and the wrong window.**

    The first is capital. Every other desk on a book opens with that book's own
    :func:`opening_capital` -- that is the whole point of `PurposeSpec`, and the header states it
    once for the book. The autopilot seat does not: it reads a ledger `app.workflow` seeded at its
    own `STARTING_CASH`, which is $100,000 against the trading book's $60,000. Nothing here rebases
    it, because rebasing would mean restating fills that actually happened at sizes they did not
    happen at. So the seat is disclosed instead, and its percentage return stays comparable to the
    others' even though its dollars are not.

    The second is inception. The desk's window is one fact on :class:`PaperDeskState` and every card
    is replayed from it -- including through the inception picker, which re-runs every card from a
    date the reader chooses. The autopilot seat cannot be re-run at all: its orders are judgements
    made on their own dates and are not a function of price history (see `app.workflow.book_models`'
    own docstring). It therefore starts when its book started and ignores the picker entirely.

    Both notes are emitted only when the seat is actually present, so a book that never carries one
    -- or one whose seat degraded off the page -- says nothing about it.
    """
    seats = [d for d in desks if d.kind == "autopilot"]
    if not seats:
        return []
    book_capital = opening_capital(spec)
    notes: list[str] = []
    for seat in seats:
        if seat.starting_equity != book_capital:
            notes.append(
                f"{seat.display_name} opens with {seat.starting_equity:,.2f}, not this book's "
                f"{book_capital:,.2f}. It trades a ledger the Agent Workflow seeded with its own "
                "starting cash, and rebasing it here would mean restating fills at sizes they never "
                "happened at. Its percentage return is comparable to the desks beside it; its dollar "
                "figures are not."
            )
        if seat.autopilot is not None:
            notes.append(
                f"{seat.display_name} runs from {seat.autopilot.card_adopted_date.isoformat()}, its "
                "own book's start, and the inception picker above does not move it. Its orders were "
                "decided on the days they were staged and cannot be re-run from another date -- "
                "unlike every other desk here, which is replayed from stored bars on demand."
            )
    return notes


def _buy_and_hold(settings: Settings, symbol: str, window: _Window) -> Decimal | None:
    """Buy-and-hold return for one symbol across the desk's own sessions.

    ``None`` rather than a zero when the symbol has no bar at either end of the window -- a benchmark
    that could not be priced is unknown, and this package never renders an unknown as a number (see
    :class:`app.paperdesk.models.Benchmark`). The first and last *stored* bars inside the window are
    used, which is the same convention `app.tournament.runner._benchmark_return` applies to the
    primary, so the two are computed alike.
    """
    frame = store.read_frame(symbol, Interval.DAY, settings=settings)
    if frame is None or frame.empty:
        return None
    inside = frame[
        (frame["ts"].dt.date >= window.first_session) & (frame["ts"].dt.date <= window.as_of)
    ]
    if len(inside) < 2:
        return None
    first, last = Decimal(str(inside["close"].iloc[0])), Decimal(str(inside["close"].iloc[-1]))
    if first <= 0:
        return None
    return last / first - 1


def _seat_provenance(
    promotions_by_agent: dict[str, PromotionRecord], agent_id: str
) -> SeatProvenance:
    """Where the seat `agent_id` came from. `"promoted"` with the latest generation the genome cleared
    when a `PromotionRecord` names it; `"owner"` otherwise -- a seat the evolution loop's promotion
    record does not name is here by an owner decision, not a gate. See `SeatProvenance`."""
    record = promotions_by_agent.get(agent_id)
    if record is not None and record.generations:
        return SeatProvenance(source="promoted", generation=max(record.generations))
    return SeatProvenance(source="owner")


def _book(
    settings: Settings,
    purpose: Purpose,
    agent_ids: tuple[str, ...],
    window: _Window,
    *,
    today: dt.date | None = None,
) -> Book:
    """Assemble one purpose's book: its own mandate, its own cards, its own benchmark.

    `today` is passed straight through to `_build_desk` for every rules-card desk (see that
    function's own docstring) -- `None` here means "let `_build_desk` resolve its own default", the
    same deferred-default shape `_build_desk` itself gives the parameter.

    The card-shape branch is the same `isinstance` on what the library actually handed back that
    `_compute` used before this desk had books -- extended to a third shape rather than replaced. Each
    shape keeps its own cache tier and its own builder because the three produce differently-typed
    results (`AgentResult`, `LadderResult`, `AllocationResult`) that no one builder accepts.

    **The autopilot seat is handled before any of that, by id rather than by shape**, because it is
    not a card and there is nothing for `_load_card` to return an `isinstance` of. It is also the one
    desk here that is not cached by this module at all: its inputs are a JSON ledger and the stored
    bars, so `load_book` re-reads the ledger every request. That is deliberate -- the file is written
    by a scheduled task in another process, and a desk cached against a window key that cannot see a
    mid-window write would keep serving yesterday's orders after today's landed.

    A card whose declared `purpose` disagrees with the book it is rostered into is a configuration
    error worth failing on rather than trading through: the purpose decides the capital the card is
    given and the basis it is scored on, so running a `trading` card inside the Roth book would fund
    it with the Roth's money and measure it against the Roth's benchmark while the card's own
    declaration says otherwise. `strategy-program/THREE-PURPOSES-PLAN.md` section 9 already warns that
    a card's purpose is declared rather than derived and that no test can catch a *mis-declared* card;
    this at least catches a mis-*rostered* one.
    """
    spec = PURPOSE_SPECS[purpose]
    mandate = _mandate(purpose)

    desks: list[Desk] = []
    # Parallel to `desks` -- one entry per card actually seated (a `desk_only` card skipped below via
    # `continue` gets neither) -- so :func:`_own_universe_benchmark` can be computed per card after the
    # loop without re-walking `agent_ids` and re-deriving which ones were skipped.
    seated_cards: list[StrategyCard | LadderCard | AllocationCard] = []
    #: Notes this book has to carry that only become knowable while building its desks -- today, only
    #: the autopilot seat's degrade message. Collected here and merged into `notes` below rather than
    #: appended to a note list that does not exist yet at this point in the function.
    extra_notes: list[str] = []
    for agent_id in agent_ids:
        # **The autopilot seat, handled before the card loader ever sees it.** It has no
        # `StrategyCard` -- its positions are staged orders written down by `app.workflow`, not a
        # rule replayed from bars -- so `_load_card` would raise `FileNotFoundError` on it. See
        # `rosters` for why it is a roster entry at all, and `app.paperdesk.autopilot` for what it
        # reads.
        #
        # **A failure here degrades to a note on the book, never an exception.** Every other desk on
        # this page is a deterministic replay of stored bars; this one reads a JSON ledger another
        # process writes on a schedule, which is a strictly larger set of ways to fail (a half-written
        # file, a schema bump, an unreadable directory). This module's own docstring records what it
        # cost the last time one panel's computation was trusted enough to raise -- a single bad value
        # took a page and three funds down with it -- and `_overlay_agent_ids` and `_build_desk`'s tax
        # block already guard the same way. A seat that cannot be built is a missing panel with a
        # stated reason; it is not a reason for the reader to lose the four cards beside it.
        if agent_id == autopilot_mod.AUTOPILOT_AGENT_ID:
            try:
                desks.append(
                    autopilot_mod.build_desk(
                        settings,
                        as_of=window.as_of,
                        # The seat derives its own session list from its own book's start rather
                        # than reusing `window.session_dates`. Those sessions begin at the *desk's*
                        # inception, which an operator can move and today sits weeks after the
                        # autopilot book's own first order -- handing them over would truncate the
                        # seat's equity curve to a window shorter than the panel says it has been
                        # running, and understate its drawdown accordingly. It needs the benchmark
                        # to build that calendar; the rest it reads from the book.
                        benchmark=_BENCHMARK,
                        mandate=mandate,
                        taxable=spec.tax_treatment == TaxTreatment.TAXABLE,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "paperdesk: the autopilot seat could not be built for the %s book, "
                    "leaving it off the page: %s",
                    purpose.value,
                    exc,
                    exc_info=True,
                )
                extra_notes.append(
                    "The Autopilot seat is not shown: its staged-order ledger could not be read "
                    f"({type(exc).__name__}). Every other desk on this book is unaffected -- they "
                    "are replayed from stored bars and do not depend on it."
                )
            continue
        card = _load_card(settings, agent_id)
        # **A `reference_only` card is scored on no window and must never trade.** It is a promoted
        # Thesis survivor kept as a reference specification (see
        # `app.tournament.models.StrategyCard.reference_only`); its cutoff exemption is only honest
        # while nothing scores it, and a live desk is a scored window. Promotion never seats one, so
        # reaching here means it was rostered by hand or by a later wiring -- skipped with a warning
        # rather than raised, so one mis-rostered reference card cannot take the other books on this
        # page down with it, the same page-preserving choice the desk_only waiting case makes below.
        if isinstance(card, StrategyCard) and card.reference_only:
            logger.warning(
                "paperdesk: skipping reference_only card %r -- it is a reference specification "
                "(a promoted Thesis survivor), scored on no window, and must not trade on a live "
                "desk. Its evidence lives in the thesis ledger; unseat it from the roster.",
                agent_id,
            )
            continue
        if card.purpose is not purpose:
            raise ValueError(
                f"card {agent_id!r} declares purpose {card.purpose.value!r} but is rostered in the "
                f"{purpose.value!r} book -- it would be funded with "
                f"{purpose.value}'s capital and scored against {purpose.value}'s benchmark while its "
                "own card says otherwise. Fix the roster or the card, not this check."
            )
        # **A `desk_only` card must not trade a window that opens before its author's design date.**
        # `StrategyCard`'s own validator checks `designed_through` against
        # `app.tournament.models.DESK_INCEPTION`, which mirrors this module's `INCEPTION` *default*.
        # It cannot see `effective_inception`, which an operator can move through
        # `data/paperdesk/inception.json` -- so the guarantee `desk_only` makes is only real if it is
        # re-checked here, against the window this desk is actually about to trade. Without this, an
        # override moving inception earlier silently re-opens exactly the lookahead the flag exists to
        # close: a 13F-derived card would be scored over months that predate the filing its universe
        # came from, which is the defect `strategy-program/CONSTRAINTS.md` records as having
        # invalidated three cards in the prior tournament.
        #
        # Skipped with a warning rather than raised, which is a deliberate departure from the
        # mis-rostered-purpose check below. That one is a card that would trade *wrong* -- a genuine
        # configuration error, and failing the page is the right answer. This is a card that must not
        # trade *yet*: a correct card, correctly refusing an inception that has not caught up to it.
        # A waiting state should not take four other books down with it.
        if (
            isinstance(card, StrategyCard)
            and card.desk_only
            and card.designed_through >= window.inception
        ):
            logger.warning(
                "paperdesk: skipping desk_only card %r -- its designed_through (%s) is not before "
                "this desk's effective inception (%s), so trading it here would score it on data "
                "its author already had sight of. Move inception to %s or later (it is %s by "
                "default; an override at data/paperdesk/inception.json can move it) to seat it.",
                agent_id,
                card.designed_through.isoformat(),
                window.inception.isoformat(),
                (card.designed_through + dt.timedelta(days=1)).isoformat(),
                INCEPTION.isoformat(),
            )
            continue
        if isinstance(card, LadderCard):
            ladder_result = _cached_ladder_run(card, settings=settings, mandate=mandate, window=window)
            desks.append(_build_ladder_desk(card, ladder_result, settings=settings, window=window))
        elif isinstance(card, AllocationCard):
            allocation_result = _cached_allocation_run(
                card, settings=settings, mandate=mandate, window=window
            )
            desks.append(
                _build_allocation_desk(card, allocation_result, settings=settings, window=window)
            )
        else:
            result = _cached_run(card, settings=settings, mandate=mandate, window=window)
            desks.append(
                _build_desk(
                    card,
                    result,
                    settings=settings,
                    window=window,
                    mandate=mandate,
                    today=today,
                    # Only a taxable book's rules desks get a `tax` summary -- see `Desk.tax`'s own
                    # docstring for the full condition. `SAVINGS`'s and `TRADING`'s `PurposeSpec`s are
                    # both `TaxTreatment.TAXABLE`; `ROTH`'s is `TaxTreatment.ROTH_IRA`, which realises
                    # no taxable event at all.
                    taxable=spec.tax_treatment == TaxTreatment.TAXABLE,
                )
            )
        seated_cards.append(card)

    # Provenance for each seat: where it came from, joined cheaply by agent_id. `promotions.jsonl` is
    # a small file read once here (not per seat), and a seat with no record is owner-seated by
    # definition -- which is every seat on the current hand-authored roster. Attached after the fact
    # via `model_copy` so none of the four desk builders has to learn about promotions or rounds.
    # See `app.paperdesk.models.SeatProvenance`.
    promotions_by_agent = {rec.agent_id: rec for rec in load_promotions(settings)}
    desks = [
        desk.model_copy(update={"provenance": _seat_provenance(promotions_by_agent, desk.agent_id)})
        for desk in desks
    ]

    benchmarks = [
        *_book_benchmarks(settings, spec, window),
        # **Each seated card against its own tradable universe, not only SPY/QQQ.** An audit computed
        # from this application's own stored bars that `A-rotation`'s reported outperformance was
        # universe selection, not rule skill: over 2026-01-01 to 08-28 the card returned +56.9% against
        # SPY's +11.9%, but SOXX alone -- a name *inside* `A-rotation`'s own universe -- returned +59.9%
        # buy-and-hold over the same window, and an equal-weight buy-and-hold of the whole 9-name
        # universe would have beaten the card's own rules by a wide margin. SPY and QQQ answer "did
        # this beat the market"; neither answers "did this beat what it was allowed to buy", which is
        # the question a page showing only market indices cannot raise. One entry per seated card,
        # keyed `own_universe_ew:{agent_id}` (see :class:`app.paperdesk.models.Benchmark`, which has no
        # per-card slot to add without widening that model -- the symbol field is the identifier a
        # reader matches back to `Desk.agent_id` above). See :func:`_own_universe_benchmark`.
        *(_own_universe_benchmark(settings, card, window) for card in seated_cards),
    ]

    # **Re-express every desk's excess against the book's own primary benchmark.** Each builder above
    # sets `excess_return` from `result.benchmark_return`, which is the *engine's* SPY figure --
    # measured over the session calendar the card actually traded, and hardcoded to SPY in
    # `app.tournament.runner._BENCHMARK`. Both halves of that are wrong for a page that renders the
    # excess next to a benchmark it did not come from:
    #
    #   * **Wrong index, for two of the three books.** A savings or Roth book is measured against a
    #     60/40 blend (`PurposeSpec.benchmark`); leaving the engine's number would have shown an
    #     excess-over-SPY sitting directly beneath a 60/40 benchmark, silently answering a different
    #     question than the row it is printed under. This is the exact failure
    #     `strategy-program/THREE-PURPOSES-PLAN.md` section 7 names -- "a savings book measured
    #     against SPY is measured against the wrong thing".
    #   * **Wrong clock, for all three, and this part was already broken before books existed.** The
    #     engine measures over its own traded sessions while the displayed benchmark is priced over
    #     the window's stored bars; the two differ by a session at the edges. `_compute` already
    #     documented that discrepancy for the benchmark *list* and made every entry there internally
    #     comparable -- but `excess_return` kept coming from the other clock, so `total_return` minus
    #     the displayed benchmark did not equal the displayed excess on any desk. A reader checking
    #     the subtraction by hand would have found it off and had nothing on the page to explain it.
    #
    # Computed here rather than inside the three builders because this is the first point that knows
    # which book a desk belongs to, and therefore which benchmark it is answerable to.
    primary = benchmarks[0].return_pct
    desks = [
        d.model_copy(
            update={"excess_return": None if primary is None else d.total_return - primary}
        )
        for d in desks
    ]

    notes = [*_funding_note(spec), *_candidate_notes(desks), *_autopilot_notes(desks, spec)]
    notes.extend(extra_notes)
    cap_note = _single_name_cap_note(desks)
    if cap_note:
        notes.insert(0, cap_note)
    if any(d.tax is not None for d in desks):
        notes.append(_TAX_FEE_NOTE)

    return Book(
        purpose=purpose.value,
        label=_BOOK_LABELS[purpose],
        funding=Funding(
            purpose=purpose.value,
            shape=spec.funding_shape.value,
            seed=spec.seed,
            contribution=spec.contribution,
            horizon_years_min=spec.horizon_years_min,
            horizon_years_max=spec.horizon_years_max,
            tax_treatment=spec.tax_treatment.value,
        ),
        starting_cash=mandate.starting_cash,
        benchmark=benchmarks[0],
        benchmarks=benchmarks,
        notes=notes,
        desks=desks,
    )


def _in_sample_note(in_sample_sessions: int, total_sessions: int) -> str:
    """Text for `PaperDeskState.notes` when the trading window's inception precedes
    `app.tournament.models.DESIGN_THROUGH` -- an honesty flag, not decoration, and never a refusal:
    the owner may legitimately want to look at an in-sample window, but a reader must be told so.

    Read `INCEPTION`'s own docstring: the desk's *previous* inception (2026-01-01) straddled this same
    cutoff, the first ~30 sessions were in-sample, and the split report existed "because a headline
    return that silently blends fitted and unfitted periods is exactly the kind of number this
    programme exists to catch." Making inception user-settable (:func:`set_inception`) reopens that
    exact hazard on any window an operator chooses -- this note is what keeps it disclosed rather than
    silent, the same way :func:`_single_name_cap_note` discloses the loosened single-name cap instead
    of leaving a reader to infer it.
    """
    return (
        f"{in_sample_sessions} of this window's {total_sessions} sessions fall at or before the "
        f"design cutoff ({DESIGN_THROUGH.isoformat()}) that every tournament round's own "
        "designed_through must not exceed. Returns over those sessions are fitted, not forward -- a "
        "headline figure that blends them with the genuinely out-of-sample sessions is exactly the "
        "kind of number this programme exists to catch (see INCEPTION's own docstring, which "
        "documents this desk living through the identical hazard once already, at its previous "
        "2026-01-01 inception)."
    )


def _compute(settings: Settings, *, today: dt.date | None = None) -> PaperDeskState:
    """`today` is threaded straight through to `_book`/`_build_desk` for the live session (see
    `_build_desk`'s own docstring) -- `None` (the default, and what every caller before this feature
    existed passes implicitly) defers to `_build_desk`'s own `dt.date.today()` fallback. Left
    unresolved here rather than pinned once at this level, so a caller of `_build_desk` directly (as
    `tests/test_paperdesk_live_session.py` does) is exercising the same default path a real request
    through `state()` would."""
    window = _trading_window(settings)
    books = [
        _book(settings, purpose, agent_ids, window, today=today)
        for purpose, agent_ids in seats(settings).items()
    ]

    in_sample_sessions = sum(1 for d in window.session_dates if d <= DESIGN_THROUGH)
    # Only notes true of the desk as a whole. The single-name-cap and candidate-tier notes are
    # computed per book instead, because both name specific rostered cards and a card sits in exactly
    # one book -- leaving them here would have attached one book's cards to all three.
    notes = list(_EVERGREEN_NOTES)
    if in_sample_sessions > 0:
        notes.append(_in_sample_note(in_sample_sessions, window.sessions))

    return PaperDeskState(
        inception=window.inception,
        as_of=window.as_of,
        latest_bar=window.latest_bar,
        stale_days=(dt.date.today() - window.latest_bar).days,
        first_session=window.first_session,
        sessions=window.sessions,
        inception_default=INCEPTION,
        inception_is_custom=_read_inception_override(settings) is not None,
        design_cutoff=DESIGN_THROUGH,
        in_sample_sessions=in_sample_sessions,
        # `earliest_bar` is `None` only for a test double that never sets it (see `_Window`'s own
        # docstring) -- `window.inception` is a harmless stand-in there, never reached for real.
        earliest_inception=window.earliest_bar or window.inception,
        latest_inception=window.latest_bar,
        notes=notes,
        books=books,
    )


def state(settings: Settings | None = None, *, today: dt.date | None = None) -> PaperDeskState:
    """The current paper desk state, served from cache when nothing has changed. See this module's
    docstring for the cache key.

    `today` is for the live session only (see `_build_desk`) and every real caller -- `app.api.
    paperdesk` included -- omits it, deferring to `dt.date.today()`."""
    return _compute(settings or get_settings(), today=today)


def refresh(settings: Settings | None = None, *, today: dt.date | None = None) -> PaperDeskState:
    """Bust **both** cache tiers and recompute. Same shape as :func:`state`.

    Clearing the disk tier as well is the point of this endpoint rather than an afterthought. If it
    only dropped the in-memory tier, a refresh against an unchanged window would reload the very
    bytes it just discarded and recompute nothing -- harmless while the cache key is complete, and
    exactly wrong when it is not. The key cannot see the mandate (`app.paper.mandate` is code, not
    data), so a change to slippage, commission or the single-name cap would otherwise be invisible
    to the desk until new bars happened to arrive. This is the escape hatch for that, and it is the
    one a reader of the page can actually reach.

    The cost is paying the cold run again -- seconds per card -- which is the right trade for a
    button a person pressed on purpose.
    """
    resolved = settings or get_settings()
    clear_cache()
    clear_disk_cache(resolved)
    state = _compute(resolved, today=today)
    _record_and_notify_fills(resolved, state)
    return state


def _record_and_notify_fills(settings: Settings, state: PaperDeskState) -> None:
    """Journal what the desks' positions did since the last refresh, and announce each change.

    **On `refresh` and never on `state`.** `state` is served from two cache tiers and is called on
    every page load, so hanging a position diff off it would compare a fresh recompute against a
    snapshot written by a cached read -- and, worse, would make "how many times did somebody open the
    page" part of what the journal records. `refresh` is a deliberate recompute, which is the only
    call that has actually looked at the market again.

    A `FillDelta` is an *observation*, not a broker fill (see `app.paperdesk.fill_journal`), and the
    headline says the desk and the change without claiming an execution price -- there is no such
    price to claim. Wrapped whole: the desk state is already computed and returned to the caller, and
    neither the diff nor the notification may cost them the page.
    """
    try:
        from app.notify import emit
        from app.paperdesk import fill_journal

        for delta in fill_journal.diff_and_record(settings, state):
            emit(
                settings,
                kind="paper.fill",
                severity="notable",
                headline=f"{delta.desk}: {delta.side} {delta.quantity} {delta.symbol}",
                detail=f"observed on the {delta.as_of.isoformat()} session",
                refs=(f"symbol:{delta.symbol}", f"desk:{delta.desk}"),
                source="paperdesk.refresh",
                dedupe_id=(
                    f"paper.fill:desk:{delta.desk}:{delta.symbol}:{delta.side}:"
                    f"{delta.as_of.isoformat()}"
                ),
            )
    except Exception:
        logger.exception("paperdesk: fill journal/notify hook failed; the desk state is unaffected")
