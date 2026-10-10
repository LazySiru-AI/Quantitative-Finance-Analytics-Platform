"""Trading costs for a selector, charged on the turnover its own decisions create.

**Why the exam needs this at all.** `strategy-program/DISCOVERY.md` §5 listed "no costs" as a known
limitation, which understated it: the exam's headline was a *median excess of +3.22%*, and a sector
rotation that replaces most of its book once a year is not obviously cheaper than that. A limitation
worth listing is a limitation worth pricing, because the sign of the result may depend on it.

**Turnover is measured between consecutive decisions, not per trial.** Each trial in
:mod:`app.discovery.exam` is scored independently -- buy at ``t``, measure at ``t + horizon`` -- which
would suggest charging every trial a full round trip. That is wrong for a rule someone would actually
run: annual decisions that re-pick the same fund do not trade it, and `mom12_1` re-picks heavily (SMH
and SOXX appear in consecutive years repeatedly). Charging a round trip per trial would invent
turnover the strategy never had and make any rule look worse the more stable it is, which is backwards.

**The benchmark is charged nothing, and that is deliberate.** An equal-weight basket of every
candidate also rebalances and also costs something. Leaving it free biases the comparison *against*
the selector, which is the direction an honest test should err in: a selector that still shows excess
after paying costs its benchmark did not pay has cleared a bar higher than the real one.

**One-way basis points, applied to the weight actually traded.** :data:`DEFAULT_COST_BPS` is charged
against ``sum |Δw|`` across the book, so a rebalance that swaps one of three equal-weight positions
trades ``2/3`` of the book and pays two thirds of the rate.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

__all__ = [
    "DEFAULT_COST_BPS",
    "CostedSeries",
    "apply_costs",
    "turnover",
]

#: One-way cost in basis points of the notional traded, covering commission and half-spread.
#:
#: 10bp on a large sector ETF is deliberately pessimistic for a retail account in 2026 -- commission
#: is typically zero and SPDR sector spreads run about a cent on a $80-200 share, so a fill nearer
#: 1-3bp is realistic. The pessimistic default is the point: if a result survives 10bp it survives the
#: honest number, and a reader who wants the optimistic case can pass one rather than having to trust
#: that a flattering default was not chosen to make the result work.
DEFAULT_COST_BPS = Decimal("10")


def turnover(previous: Sequence[str], current: Sequence[str]) -> Decimal:
    """``sum |Δw|`` moving from one equal-weight book to the next.

    Both books are equal-weighted over their own members, so a name held in both still trades whenever
    the position counts differ (three names to four means every position is resized). Moving from an
    empty book charges a full 1.0 -- the initial purchase is a real trade and the first decision date
    should not be free.
    """
    if not current:
        return Decimal(0) if not previous else Decimal(1)
    old_w = {s: Decimal(1) / Decimal(len(previous)) for s in previous} if previous else {}
    new_w = {s: Decimal(1) / Decimal(len(current)) for s in current}
    return sum(
        (abs(new_w.get(s, Decimal(0)) - old_w.get(s, Decimal(0))) for s in set(old_w) | set(new_w)),
        Decimal(0),
    )


@dataclass(frozen=True, slots=True)
class CostedSeries:
    """Per-decision turnover and cost, aligned index-for-index with the trials they came from."""

    turnovers: tuple[Decimal, ...]
    costs: tuple[Decimal, ...]
    """Cost as a fraction of book value, to be subtracted from that trial's return."""

    @property
    def total_cost(self) -> Decimal:
        return sum(self.costs, Decimal(0))

    @property
    def mean_turnover(self) -> Decimal:
        return (
            Decimal(0)
            if not self.turnovers
            else sum(self.turnovers, Decimal(0)) / Decimal(len(self.turnovers))
        )


def apply_costs(
    pick_sets: Sequence[Sequence[str]], *, cost_bps: Decimal = DEFAULT_COST_BPS
) -> CostedSeries:
    """Turnover and cost for a chronological sequence of pick sets.

    `pick_sets` must be in decision order; the cost charged to element *i* is the cost of moving into
    it from element *i-1*, with the first charged a full entry.
    """
    rate = cost_bps / Decimal(10_000)
    turnovers: list[Decimal] = []
    costs: list[Decimal] = []
    previous: Sequence[str] = ()
    for picks in pick_sets:
        moved = turnover(previous, picks)
        turnovers.append(moved)
        costs.append(moved * rate)
        previous = picks
    return CostedSeries(turnovers=tuple(turnovers), costs=tuple(costs))
