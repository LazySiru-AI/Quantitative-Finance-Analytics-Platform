"""The wash-sale engine: IRC §1091, IRS Publication 550, and Rev. Rul. 2008-5.

A loss on the sale of stock or securities is disallowed if, within **30 calendar days before or
30 calendar days after** the sale, the taxpayer acquires substantially identical stock or
securities -- 61 days total, counted on the calendar, not on trading days. The boundary is
exclusive at day 31 on both sides.

Four consequences follow, and this module implements all four:

1. **The loss is disallowed in proportion to the shares replaced.** Selling 100 and replacing 40
   disallows 40% of the loss, not all of it (Pub 550, "Wash Sales").
2. **The disallowed amount is added to the replacement lot's basis.** The loss is not gone, it is
   deferred into the shares that caused the disallowance.
3. **The replacement lot's holding period tolls** -- it inherits the start of the shares that were
   sold. This is the half of the rule most commonly left out, and it can turn a would-be short-term
   position into a long-term one.
4. **The rule chains.** A replacement lot later sold at a loss inside another window triggers §1091
   again, against the basis this module already adjusted once.

"The taxpayer" in the statute is the person, not the account: a replacement purchase in *any*
account the user controls triggers the rule, including a different broker. Matching is on
``instrument_id`` (CUSIP), never on ticker, because the same CUSIP can be spelled differently across
brokers.

**Rev. Rul. 2008-5** covers the case where the replacement is bought inside a traditional or Roth
IRA: the loss is still disallowed, but there is **no basis adjustment anywhere**. It is not deferred
into the IRA lot the way an ordinary wash sale defers it into a taxable replacement lot -- it is
destroyed. This is strictly worse for the taxpayer than an ordinary wash sale and must never be
folded into the ordinary disallowed total.

"Substantially identical" is undefined by the statute. This module decides only the case the IRS
has effectively settled by construction -- an exact CUSIP match. Everything else that might
plausibly be substantially identical (a leveraged single-stock ETF and its underlying, two
issuers' funds on the same index, dual share classes) is either ruled out explicitly (a fund and
its inverse are obviously not identical) or surfaced as :class:`~app.tax.models.UnsettledPair`
with both interpretations priced, never auto-applied. Silently picking one interpretation would be
a defect, not a feature.

**This is a calculation, not tax advice**, and must be reconciled against the user's 1099-B forms
before it informs a filing.

----------------------------------------------------------------------------------------------------

**`apply_wash_sales` mutates its `ledger` argument in place.** This is surprising for a function
that also returns a value, so it is stated here as plainly as possible: after the call returns,
objects already sitting in ``ledger.lots`` and ``ledger.disposals`` have been changed, not
replaced. Concretely this function writes:

* ``Disposal.disallowed_loss`` (positive) and ``Disposal.permanently_disallowed`` on every disposal
  that triggers the rule.
* ``Lot.wash_sale_adjustment`` on every ordinary (non-IRA) replacement lot, and the identical amount
  added onto ``Lot.cost_basis`` -- never onto an IRA lot, per Rev. Rul. 2008-5.
* ``Lot.holding_period_start`` on a replacement lot whose holding period tolls.

Callers that already hold references to lots or disposals from before the call see the changes,
because they are the same Python objects. Callers that need the pre-adjustment figures must copy
them out before calling this function.
"""

from __future__ import annotations

import datetime as dt
from bisect import bisect_left, bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.core.ids import stable_id
from app.core.lots import Disposal, LotLedger
from app.core.models import Account, Lot
from app.core.money import quantize_money
from app.tax.models import (
    EquivalenceDecision,
    EquivalenceRule,
    UnsettledPair,
    WashSaleEvent,
)

__all__ = ["DEFAULT_EQUIVALENCE", "WashSaleResult", "apply_wash_sales"]

#: IRC §1091: 30 days before the sale, the sale date itself, 30 days after -- 61 calendar days.
#: Boundary is exclusive at day 31 on both sides (Pub 550, "Wash Sales").
_WINDOW_DAYS = 30


DEFAULT_EQUIVALENCE: tuple[EquivalenceRule, ...] = (
    # --- Settled in the negative: a leveraged fund and its inverse are opposite bets, never the
    # same security under any reading of "substantially identical". -----------------------------
    EquivalenceRule(
        left="SOXL",
        right="SOXS",
        decision=EquivalenceDecision.NOT_IDENTICAL,
        rationale=(
            "SOXL (3x bull semiconductors) and SOXS (3x bear semiconductors) are opposite "
            "economic exposures. A fund and its inverse are never substantially identical."
        ),
    ),
    EquivalenceRule(
        left="TQQQ",
        right="SQQQ",
        decision=EquivalenceDecision.NOT_IDENTICAL,
        rationale=(
            "TQQQ (3x bull Nasdaq-100) and SQQQ (3x bear Nasdaq-100) are opposite economic "
            "exposures. A fund and its inverse are never substantially identical."
        ),
    ),
    # --- Genuinely unsettled: no IRS ruling addresses these relationships. Flagged for the
    # user, never auto-applied. -----------------------------------------------------------
    EquivalenceRule(
        left="NVDA",
        right="NVDL",
        decision=EquivalenceDecision.UNSETTLED,
        rationale=(
            "NVDL is a 2x single-stock leveraged ETF on NVDA common stock, not the same security. "
            "The IRS has not ruled on whether a leveraged single-stock ETF is substantially "
            "identical to its underlying; the user must decide."
        ),
    ),
    EquivalenceRule(
        left="MU",
        right="MUU",
        decision=EquivalenceDecision.UNSETTLED,
        rationale="MUU is a leveraged single-stock ETF on MU common stock; no IRS ruling exists.",
    ),
    EquivalenceRule(
        left="MU",
        right="MULL",
        decision=EquivalenceDecision.UNSETTLED,
        rationale="MULL is a leveraged single-stock ETF on MU common stock; no IRS ruling exists.",
    ),
    EquivalenceRule(
        left="TSLA",
        right="TSLL",
        decision=EquivalenceDecision.UNSETTLED,
        rationale=(
            "TSLL is a leveraged single-stock ETF on TSLA common stock; no IRS ruling exists."
        ),
    ),
    EquivalenceRule(
        left="SNDK",
        right="SNXX",
        decision=EquivalenceDecision.UNSETTLED,
        rationale=(
            "SNXX is a leveraged single-stock ETF on SNDK common stock; no IRS ruling exists."
        ),
    ),
    EquivalenceRule(
        left="SOXL",
        right="SOXX",
        decision=EquivalenceDecision.UNSETTLED,
        rationale=(
            "SOXL and SOXX track the same semiconductor index from two different issuers at "
            "different leverage (3x vs 1x unleveraged). Same benchmark, different structure; no "
            "IRS ruling addresses whether that makes them substantially identical."
        ),
    ),
    EquivalenceRule(
        left="GOOG",
        right="GOOGL",
        decision=EquivalenceDecision.UNSETTLED,
        rationale=(
            "GOOG and GOOGL are Alphabet's two share classes, differing only in voting rights. No "
            "IRS ruling addresses whether different share classes of the same issuer are "
            "substantially identical."
        ),
    ),
    EquivalenceRule(
        left="CRDO",
        right="CRDU",
        decision=EquivalenceDecision.UNSETTLED,
        rationale=(
            "CRDU is a leveraged single-stock ETF on CRDO common stock; no IRS ruling exists."
        ),
    ),
    EquivalenceRule(
        left="IREN",
        right="IREX",
        decision=EquivalenceDecision.UNSETTLED,
        rationale=(
            "IREX is a leveraged single-stock ETF on IREN common stock; no IRS ruling exists."
        ),
    ),
    EquivalenceRule(
        left="GDX",
        right="GDXU",
        decision=EquivalenceDecision.UNSETTLED,
        rationale=(
            "GDXU is a leveraged ETF tracking the same gold-miners index as GDX; no IRS ruling "
            "addresses leveraged-vs-unleveraged funds on the same benchmark."
        ),
    ),
    EquivalenceRule(
        left="GDX",
        right="NUGT",
        decision=EquivalenceDecision.UNSETTLED,
        rationale=(
            "GDX and NUGT track the same gold-miners index from two different issuers at "
            "different leverage. Same benchmark family, different structure; no IRS ruling exists."
        ),
    ),
)


class WashSaleResult(BaseModel):
    """One pass of :func:`apply_wash_sales`: real disallowances plus anything left for the user.

    ``events`` are disallowances the engine actually applied. ``unsettled`` are pairs the engine
    refused to decide -- neither number in an :class:`~app.tax.models.UnsettledPair` has been
    applied to any lot or disposal; they are priced so the user can rule on them.
    """

    model_config = ConfigDict(extra="forbid")

    events: tuple[WashSaleEvent, ...] = ()
    unsettled: tuple[UnsettledPair, ...] = ()


# A replacement lot matched against a loss disposal, with the quantity of that lot consumed by the
# match. A single disposal can be satisfied by more than one replacement lot.
_Match = tuple[Lot, Decimal]


# ---------------------------------------------------------------------------
# Candidate lookup
#
# Every loss disposal needs the lots acquired inside its own 61-day window. Scanning the whole
# ledger once per disposal is quadratic, and on a real book (over a thousand lots and disposals) it was
# nearly the entire cost of a Portfolio or Tax page load, up from a small fraction of that
# when the ledger was half the size. The two structures below make each disposal's lookup
# proportional to the candidates it actually has rather than to the size of the ledger, which takes
# the same pass to ~35 ms and, more importantly, makes it grow linearly with the next import instead
# of with its square.
#
# **Nothing here changes which lots are found or the order they are found in** -- see
# `_WindowIndex`'s note on ordering. This is a lookup change, not a matching-rule change.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _WindowIndex:
    """Lots grouped by a key, each group sorted so a date window is one contiguous slice.

    Groups are sorted by ``(acquired_date, replay position)`` -- exactly the key the per-disposal
    sort used to apply, so a slice out of this index is already in the order Treas. Reg. §1.1091-1
    matching requires: earliest acquisition first, same-date ties broken by the order the lots were
    replayed rather than by ``lot_id``, which is a hash (see the note in :func:`apply_wash_sales`).
    Building the order once instead of re-sorting per disposal is safe because the wash-sale pass
    mutates ``cost_basis``, ``wash_sale_adjustment`` and ``holding_period_start`` but never
    ``acquired_date`` -- if that ever changes, this index becomes stale mid-pass.
    """

    groups: dict[str, tuple[list[dt.date], list[Lot]]]

    def in_window(self, key: str, start: dt.date, end: dt.date) -> list[Lot]:
        """Lots under ``key`` acquired in ``[start, end]``, inclusive at both ends."""
        group = self.groups.get(key)
        if group is None:
            return []
        dates, lots = group
        return lots[bisect_left(dates, start) : bisect_right(dates, end)]


def _index_lots(lots: Sequence[Lot], key_of: Mapping[str, str] | None) -> _WindowIndex:
    """Group ``lots`` for :class:`_WindowIndex`.

    ``key_of`` maps ``instrument_id`` to the grouping key; ``None`` groups by ``instrument_id``
    itself. A lot whose instrument has no entry in ``key_of`` is left out of the index entirely,
    which is what the scan this replaces did when it could not resolve a candidate's symbol.
    """
    grouped: dict[str, list[Lot]] = {}
    # `lots` is in replay order, so appending preserves it; the sort below is stable, which is what
    # makes replay position the same-date tie-break without carrying an explicit rank.
    for lot in lots:
        key = lot.instrument_id if key_of is None else key_of.get(lot.instrument_id, "")
        if not key:
            continue
        grouped.setdefault(key, []).append(lot)
    return _WindowIndex(
        groups={
            key: ([lot.acquired_date for lot in group], group)
            for key, group in (
                (key, sorted(group, key=lambda lot: lot.acquired_date))
                for key, group in grouped.items()
            )
        }
    )


def _unsettled_partners(
    equivalence: Sequence[EquivalenceRule],
) -> dict[str, dict[str, str]]:
    """Sold symbol -> ``{replacement symbol: rationale}`` for every **unsettled** pair, upper-cased.

    Replaces a linear scan of the whole table per candidate lot -- 13 rules x every lot in the
    ledger x every loss disposal, each comparison building two sets, which is where the pass spent
    most of its time.

    The first rule relating a pair wins, exactly as that scan's first match did. That includes the
    case where the first rule *settles* the pair in the negative: a later ``UNSETTLED`` rule for the
    same pair must not resurrect it, so pairs are marked seen before their decision is consulted.
    """
    seen: set[frozenset[str]] = set()
    partners: dict[str, dict[str, str]] = {}
    for rule in equivalence:
        left, right = rule.left.upper(), rule.right.upper()
        pair = frozenset((left, right))
        if pair in seen:
            continue
        seen.add(pair)
        if rule.decision is not EquivalenceDecision.UNSETTLED:
            continue
        partners.setdefault(left, {})[right] = rule.rationale
        partners.setdefault(right, {})[left] = rule.rationale
    return partners


def apply_wash_sales(
    ledger: LotLedger,
    *,
    accounts: Mapping[str, Account],
    equivalence: Sequence[EquivalenceRule] = DEFAULT_EQUIVALENCE,
) -> WashSaleResult:
    """Apply IRC §1091 to every loss disposal in ``ledger``, across every account at once.

    **Mutates ``ledger`` in place** -- see the module docstring for exactly which fields. The
    return value is a report of what changed, not the only place the changes are visible.

    Processing is a single chronological pass over every disposal, sorted by ``disposed_date`` then
    ``disposal_id``. That order is what makes chaining (case 7 in the standing test suite) correct:
    when a replacement lot's own later sale is reached, its ``cost_basis`` and
    ``holding_period_start`` have already been adjusted by whichever earlier disposal matched it,
    so both the loss on the second sale and the holding period it tolls to are computed against the
    adjusted state, not the state a lot-replay pass captured before any wash sale ran. This function
    never trusts ``Disposal.cost_basis`` or ``Disposal.holding_start`` for that determination -- it
    recomputes the disposal's share of the lot's *current* basis, and reads the lot's *current*
    ``effective_holding_start``, on every iteration. Trusting a field set once at lot-replay time is
    exactly what would make a chain of wash sales silently stop at the first link.

    Args:
        ledger: The full cross-account replay. Every account must be present -- a per-account call
            would miss every cross-broker wash sale, which is most of them in a portfolio that holds
            the same CUSIP at more than one broker.
        accounts: ``account_id`` -> :class:`~app.core.models.Account`, for tax treatment. A KeyError
            here means a lot or disposal references an account this call was not told about, which
            is a caller bug, not data to paper over.
        equivalence: The "substantially identical" table. Defaults to
            :data:`DEFAULT_EQUIVALENCE`. Anything not an exact CUSIP match and not explicitly listed
            here is treated as not substantially identical -- the engine never guesses.

    Returns:
        A :class:`WashSaleResult` holding every disallowance applied and every pair left unsettled.
    """
    lots_by_id = ledger.lots_by_id()
    # How much of each candidate lot's total quantity has already been claimed as a replacement by
    # an earlier-processed disposal in this same pass. Shares purchased once cannot be counted as
    # the replacement for two different sales beyond what was actually bought.
    consumed: dict[str, Decimal] = {}

    events: list[WashSaleEvent] = []
    unsettled: list[UnsettledPair] = []

    # Tie-broken on **replay position**, not on `disposal_id`.
    #
    # `ledger.disposals` is appended during the chronological walk in `build_lots`, so its own order
    # is the order the trades were replayed in -- which `fetch_transactions` now makes deterministic
    # and hash-free. `disposal_id` is a hash, and processing order decides real money here: two
    # same-day sales compete for one limited pool of replacement shares (`consumed` below), so
    # whichever is processed first takes them.
    #
    # Measured on a real ledger, comparing two databases with byte-identical transaction content
    # differing only in id scheme: realised short-term gain and the split between
    # deferred and permanently disallowed losses moved by hundreds of dollars. Same-day attribution is genuinely
    # underdetermined by the data, but it must not depend on a hash that changes when an unrelated
    # part of the system changes.
    replay_order = {d.disposal_id: index for index, d in enumerate(ledger.disposals)}
    ordered_disposals = sorted(
        ledger.disposals, key=lambda d: (d.disposed_date, replay_order[d.disposal_id])
    )

    # Built once, read by every disposal below -- see the note above `_WindowIndex`. `by_symbol` is
    # keyed on the upper-cased display symbol because that is what the equivalence table matches on;
    # `by_instrument` is keyed on `instrument_id`, which is the only thing an exact
    # substantially-identical match is ever allowed to turn on.
    by_instrument = _index_lots(ledger.lots, None)
    symbol_keys = {
        instrument_id: symbol.upper() for instrument_id, symbol in ledger.symbols.items()
    }
    by_symbol = _index_lots(ledger.lots, symbol_keys)
    partners = _unsettled_partners(equivalence)

    for disposal in ordered_disposals:
        account = accounts[disposal.account_id]
        if account.is_tax_advantaged:
            # No taxable loss is ever recognised inside an IRA, so there is nothing for §1091 to
            # disallow on the sale side. The account is still scanned below as a source of
            # *replacement* purchases for other accounts' sales -- that is the Rev. Rul. 2008-5
            # case -- it is just never the sale side of the rule.
            continue

        lot = lots_by_id.get(disposal.lot_id)
        if lot is not None and lot.quantity != 0:
            effective_basis = lot.basis_per_share * disposal.quantity
            # Like cost_basis, `Disposal.holding_start` is a snapshot taken when the lot replay
            # created this disposal -- before any wash-sale toll this same pass might apply to the
            # lot being sold. Re-reading the lot's *current* effective start (its own docstring:
            # "re-read by the wash-sale pass, which may move it earlier") is what makes a chain of
            # wash sales toll all the way back through every link, not just the first one.
            sold_holding_start = lot.effective_holding_start
        else:  # pragma: no cover - defensive; a disposal always has a lot in a well-formed ledger
            effective_basis = disposal.cost_basis
            sold_holding_start = disposal.holding_start
        gain_loss = disposal.proceeds - disposal.fees - effective_basis
        if gain_loss >= 0:
            continue  # Pub 550: the rule applies to losses only.
        loss_amount = -gain_loss

        window_start = disposal.disposed_date - dt.timedelta(days=_WINDOW_DAYS)
        window_end = disposal.disposed_date + dt.timedelta(days=_WINDOW_DAYS)

        # Exact-CUSIP replacements, already in Treas. Reg. §1.1091-1 order: earliest acquisition
        # first, same-date ties in replay order rather than by `lot_id`, for the reason given above
        # -- which lot absorbs a disallowed loss changes its basis, and that should not turn on a
        # hash. `_WindowIndex` holds that order so it does not have to be rebuilt per disposal.
        identical_candidates = [
            candidate
            for candidate in by_instrument.in_window(
                disposal.instrument_id, window_start, window_end
            )
            if candidate.lot_id != disposal.lot_id
        ]

        # Everything else that *might* be substantially identical. Only symbols the equivalence
        # table relates to this one are looked at -- a disposal in a symbol the table says nothing
        # about does no work here at all, which is almost all of them.
        unsettled_by_symbol: dict[str, list[Lot]] = {}
        unsettled_rationale: dict[str, str] = {}
        for partner_symbol, rationale in partners.get(disposal.symbol.upper(), {}).items():
            for candidate in by_symbol.in_window(partner_symbol, window_start, window_end):
                if candidate.lot_id == disposal.lot_id:
                    continue
                if candidate.instrument_id == disposal.instrument_id:
                    # The same security, spelled by a symbol the table happens to relate to itself.
                    # It is an exact match, already handled above, and never an unsettled one.
                    continue
                candidate_symbol = ledger.symbols.get(candidate.instrument_id, "")
                if not candidate_symbol:  # pragma: no cover - excluded from the index by `_index_lots`
                    continue
                unsettled_by_symbol.setdefault(candidate_symbol, []).append(candidate)
                unsettled_rationale[candidate_symbol] = rationale

        matched: list[_Match] = []
        remaining_need = disposal.quantity
        for candidate in identical_candidates:
            if remaining_need <= 0:
                break
            already_used = consumed.get(candidate.lot_id, Decimal(0))
            available = candidate.quantity - already_used
            if available <= 0:
                continue
            use = available if available < remaining_need else remaining_need
            matched.append((candidate, use))
            consumed[candidate.lot_id] = already_used + use
            remaining_need -= use

        quantity_replaced_total = disposal.quantity - remaining_need

        if quantity_replaced_total > 0:
            events.extend(
                _build_events(
                    disposal=disposal,
                    sold_holding_start=sold_holding_start,
                    matched=matched,
                    loss_amount=loss_amount,
                    quantity_sold=disposal.quantity,
                    quantity_replaced_total=quantity_replaced_total,
                    accounts=accounts,
                    lot=lot,
                )
            )

        remaining_after_identical = disposal.quantity - quantity_replaced_total
        if remaining_after_identical > 0 and unsettled_by_symbol:
            unsettled.extend(
                _build_unsettled(
                    disposal=disposal,
                    loss_amount=loss_amount,
                    remaining_after_identical=remaining_after_identical,
                    unsettled_by_symbol=unsettled_by_symbol,
                    unsettled_rationale=unsettled_rationale,
                )
            )

    events.sort(key=lambda event: (event.sale_date, event.disposal_id, event.event_id))
    unsettled.sort(
        key=lambda pair: (pair.sale_date, pair.sale_disposal_id, pair.replacement_symbol)
    )
    return WashSaleResult(events=tuple(events), unsettled=tuple(unsettled))


def _build_events(
    *,
    disposal: Disposal,
    sold_holding_start: dt.date,
    matched: list[_Match],
    loss_amount: Decimal,
    quantity_sold: Decimal,
    quantity_replaced_total: Decimal,
    accounts: Mapping[str, Account],
    lot: Lot | None,
) -> list[WashSaleEvent]:
    """Turn a set of matched replacement lots into one or two events, and mutate the ledger.

    Two events when the matches span both ordinary (taxable) and IRA accounts: the two cases have
    incompatible outcomes -- one gets a basis add-back, the other permanently loses the loss -- and
    :class:`~app.tax.models.WashSaleEvent` carries a single ``permanently_disallowed`` flag, so they
    cannot be reported as one event without erasing that distinction.
    """
    ordinary = [
        (m_lot, qty) for m_lot, qty in matched if not accounts[m_lot.account_id].is_tax_advantaged
    ]
    permanent = [
        (m_lot, qty) for m_lot, qty in matched if accounts[m_lot.account_id].is_tax_advantaged
    ]

    total_disallowed_exact = loss_amount * quantity_replaced_total / quantity_sold
    total_disallowed = quantize_money(total_disallowed_exact)

    groups: list[tuple[bool, list[_Match], Decimal]] = []
    if ordinary:
        groups.append((False, ordinary, sum((qty for _, qty in ordinary), Decimal(0))))
    if permanent:
        groups.append((True, permanent, sum((qty for _, qty in permanent), Decimal(0))))

    is_chained = lot is not None and lot.wash_sale_adjustment != 0

    result: list[WashSaleEvent] = []
    allocated = Decimal(0)
    permanent_amount = Decimal(0)
    for index, (is_ira, group_matched, group_qty) in enumerate(groups):
        if index == len(groups) - 1:
            # Remainder, not a fresh division: guarantees the per-group amounts sum exactly to
            # `total_disallowed` even when the split does not divide evenly in cents.
            group_disallowed = total_disallowed - allocated
        else:
            group_disallowed = quantize_money(
                total_disallowed_exact * group_qty / quantity_replaced_total
            )
            allocated += group_disallowed

        replacement_lot_ids = tuple(dict.fromkeys(m_lot.lot_id for m_lot, _ in group_matched))
        replacement_txn_ids = tuple(
            dict.fromkeys(m_lot.acquired_txn_id for m_lot, _ in group_matched)
        )
        replacement_account_ids = tuple(
            dict.fromkeys(m_lot.account_id for m_lot, _ in group_matched)
        )

        if is_ira:
            permanent_amount += group_disallowed

        basis_added_to_lot_id: str | None = None
        holding_period_tolled_to: dt.date | None = None
        if not is_ira:
            basis_added_to_lot_id, holding_period_tolled_to = _apply_ordinary_adjustment(
                sold_holding_start=sold_holding_start,
                group_matched=group_matched,
                group_qty=group_qty,
                group_disallowed=group_disallowed,
            )
        # is_ira branch: Rev. Rul. 2008-5 -- no basis anywhere, no holding-period benefit either,
        # since a holding period inside a tax-advantaged account has no capital-gains consequence
        # to toll in the first place.

        result.append(
            WashSaleEvent(
                event_id=stable_id(
                    "wash_sale",
                    disposal.disposal_id,
                    "ira" if is_ira else "ordinary",
                    *replacement_lot_ids,
                ),
                disposal_id=disposal.disposal_id,
                instrument_id=disposal.instrument_id,
                symbol=disposal.symbol,
                sale_date=disposal.disposed_date,
                sale_account_id=disposal.account_id,
                quantity_sold=quantity_sold,
                loss_amount=quantize_money(loss_amount),
                quantity_replaced=group_qty,
                disallowed_loss=group_disallowed,
                replacement_txn_ids=replacement_txn_ids,
                replacement_lot_ids=replacement_lot_ids,
                replacement_account_ids=replacement_account_ids,
                permanently_disallowed=is_ira,
                basis_added_to_lot_id=basis_added_to_lot_id,
                holding_period_tolled_to=holding_period_tolled_to,
                is_chained=is_chained,
            )
        )

    disposal.disallowed_loss = total_disallowed
    # Only the IRA-replaced portion is permanent. Where one sale is replaced in both a taxable
    # account and an IRA, flagging the whole disallowance as permanent would report a deferred loss
    # as destroyed -- real data does this on some disposals.
    disposal.permanently_disallowed_loss = permanent_amount
    return result


def _apply_ordinary_adjustment(
    *,
    sold_holding_start: dt.date,
    group_matched: list[_Match],
    group_qty: Decimal,
    group_disallowed: Decimal,
) -> tuple[str, dt.date | None]:
    """Add basis to and toll the holding period of every non-IRA replacement lot in a group.

    Returns the id of the lot that absorbed the most of this group's disallowance (for
    ``WashSaleEvent.basis_added_to_lot_id``, which is singular even though a match can span more
    than one lot) and the holding-period date it was tolled to, if any.
    """
    allocated = Decimal(0)
    primary_lot, primary_qty = group_matched[0][0], Decimal(-1)
    tolled_to: dt.date | None = None

    for index, (rep_lot, used_qty) in enumerate(group_matched):
        if index == len(group_matched) - 1:
            share = group_disallowed - allocated  # remainder: exact sum, see _build_events
        else:
            share = quantize_money(group_disallowed * used_qty / group_qty)
            allocated += share

        rep_lot.wash_sale_adjustment += share
        rep_lot.cost_basis += share

        # Tolling: the replacement lot inherits the holding period of the shares it replaced. Only
        # move it earlier -- never later -- and only if it is not already earlier from some other
        # match in this same run.
        if sold_holding_start < rep_lot.effective_holding_start:
            rep_lot.holding_period_start = sold_holding_start

        if used_qty > primary_qty:
            primary_qty = used_qty
            primary_lot = rep_lot
            tolled_to = rep_lot.holding_period_start

    return primary_lot.lot_id, tolled_to


def _build_unsettled(
    *,
    disposal: Disposal,
    loss_amount: Decimal,
    remaining_after_identical: Decimal,
    unsettled_by_symbol: dict[str, list[Lot]],
    unsettled_rationale: dict[str, str],
) -> list[UnsettledPair]:
    """Price both interpretations of every unsettled candidate symbol against this disposal.

    Each symbol is priced independently against whatever quantity the *certain* (exact-CUSIP)
    matches did not already account for. Nothing here is applied to any lot -- this is the flag,
    not the disallowance.
    """
    pairs: list[UnsettledPair] = []
    for symbol, candidates in unsettled_by_symbol.items():
        available_qty = sum((c.quantity for c in candidates), Decimal(0))
        if available_qty <= 0:
            continue
        cap = remaining_after_identical
        matched_qty = available_qty if available_qty < cap else cap
        if matched_qty <= 0:
            continue
        impact_if_identical = quantize_money(loss_amount * matched_qty / disposal.quantity)
        pairs.append(
            UnsettledPair(
                sale_disposal_id=disposal.disposal_id,
                sold_symbol=disposal.symbol,
                replacement_symbol=symbol,
                sale_date=disposal.disposed_date,
                loss_amount=quantize_money(loss_amount),
                impact_if_identical=impact_if_identical,
                impact_if_distinct=Decimal("0"),
                rationale=unsettled_rationale[symbol],
            )
        )
    return pairs
