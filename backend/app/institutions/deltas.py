"""Quarter-over-quarter delta engine for institutional and fund holdings.

Two rules make this module what it is, and both exist because the obvious implementation is wrong
in a way that is invisible until you check it against real filings. See
:mod:`app.institutions.models` for the wire types this operates on.

**Positions are matched on CUSIP, never on issuer name.** Berkshire reported CUSIP ``060505104`` as
``BANK AMERICA CORP`` in the quarter ending 2026-03-31 and as ``BANK OF AMER CORP`` in the quarter
ending 2026-06-30. A name-keyed diff sees two different strings and reports a continuing position as
a simultaneous exit of the whole ``BANK AMERICA CORP`` stake and a new buy of ``BANK OF AMER CORP``
-- a fabricated $25bn sale and $27.5bn purchase that never happened. Every lookup in this module goes
through :attr:`~app.institutions.models.Snapshot.by_cusip`, which is keyed the same way, so there is
no code path that can key on the display name instead.

**Action is classified from the share count alone, never from the value.** A position's disclosed
value moves for two reasons -- the manager traded it, and the market repriced it -- and only the
first is a decision. Between Berkshire's quarter ending 2026-03-31 and its quarter ending
2026-06-30, Chevron's disclosed value fell from $17,457,364,606 to $13,986,141,890, a $3.47bn move,
while the share count stayed at exactly 84,375,856 shares in both filings. A classifier that looks at
value calls that a large sale. It was not a sale at all -- Berkshire did not trade a single share --
and the entire point of this feature is to tell a reader which of those two things happened. Making
that distinction structurally impossible to get wrong means :func:`diff` never reads ``.value`` when
deciding :class:`~app.institutions.models.Action`; see :func:`_classify`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from app.institutions.models import Action, Holding, HoldingChange, PortfolioDelta, Snapshot

__all__ = ["diff", "latest_pair"]

_ZERO = Decimal(0)


def _classify(before: Holding | None, after: Holding | None) -> Action:
    """The one place share counts turn into an :class:`Action`. Never given ``.value``.

    The signature itself is the guardrail: a :class:`Holding` carries both ``shares`` and ``value``,
    but this function only ever receives whole holdings so that a future edit cannot quietly start
    reading the value field and reintroduce the Chevron bug -- the caller passes the holdings, not
    pre-extracted numbers, and every branch below only ever touches ``.shares``.
    """
    if before is None and after is not None:
        return Action.NEW
    if before is not None and after is None:
        return Action.EXIT
    assert before is not None and after is not None  # narrowed by the two branches above
    if after.shares > before.shares:
        return Action.ADD
    if after.shares < before.shares:
        return Action.TRIM
    return Action.HOLD


def _change_for(cusip: str, before: Holding | None, after: Holding | None) -> HoldingChange:
    """Build one row of the diff for a single CUSIP present in either period (or both)."""
    action = _classify(before, after)

    # Display fields prefer the later period's disclosure -- the more recent name and ticker are
    # the more useful ones to show -- and fall back to the earlier period for an EXIT, where there
    # is no later disclosure to prefer.
    source = after if after is not None else before
    assert source is not None  # at least one of before/after is always present
    issuer = source.issuer
    ticker = source.ticker

    shares_before = before.shares if before is not None else _ZERO
    shares_after = after.shares if after is not None else _ZERO
    shares_delta = shares_after - shares_before

    # Guarded rather than derived from `action == Action.NEW`: a filing that discloses a holding
    # with zero shares in the earlier period (data oddity, not a real case we have seen, but the
    # contract promises no DivisionByZero) would hit the same zero denominator on a TRIM or HOLD
    # classification, and the guard has to hold there too.
    shares_pct_change = shares_delta / shares_before if shares_before != _ZERO else None

    value_before = before.value if before is not None else _ZERO
    value_after = after.value if after is not None else _ZERO
    value_delta = value_after - value_before

    weight_before = before.weight if before is not None else _ZERO
    weight_after = after.weight if after is not None else _ZERO
    weight_delta = weight_after - weight_before

    return HoldingChange(
        cusip=cusip,
        issuer=issuer,
        ticker=ticker,
        action=action,
        shares_before=shares_before,
        shares_after=shares_after,
        shares_delta=shares_delta,
        shares_pct_change=shares_pct_change,
        value_before=value_before,
        value_after=value_after,
        value_delta=value_delta,
        weight_before=weight_before,
        weight_after=weight_after,
        weight_delta=weight_delta,
    )


def diff(before: Snapshot, after: Snapshot) -> PortfolioDelta:
    """Compute what changed between two snapshots of the same filer.

    Matching is on CUSIP only (see the module docstring), via
    :attr:`~app.institutions.models.Snapshot.by_cusip`. A CUSIP present in only one snapshot yields a
    ``NEW`` or ``EXIT`` row with the absent side's shares, value and weight all zero -- never
    ``None`` -- so a reader (or the UI summing a column) does not have to special-case a missing
    holding as distinct from a zero one.

    ``changes`` is sorted by absolute value delta descending, then by CUSIP ascending as a
    deterministic tie-break. The point of a delta view is "what moved the most", so the biggest
    dollar swings lead regardless of whether they were trades or repricings -- a reader scanning the
    top of the list sees Chevron's $3.47bn value move sitting right beside its ``HOLD`` label, which
    is exactly the juxtaposition this feature exists to surface.
    """
    if before.fund.key.lower() != after.fund.key.lower():
        raise ValueError(
            f"diff() requires two snapshots of the same filer, got "
            f"{before.fund.key!r} and {after.fund.key!r}"
        )

    before_map = before.by_cusip
    after_map = after.by_cusip
    all_cusips = set(before_map) | set(after_map)

    changes = [
        _change_for(cusip, before_map.get(cusip), after_map.get(cusip)) for cusip in all_cusips
    ]
    changes.sort(key=lambda c: (-abs(c.value_delta), c.cusip))

    return PortfolioDelta(
        fund=after.fund,
        from_period=before.period,
        to_period=after.period,
        from_accession=before.accession,
        to_accession=after.accession,
        total_value_before=before.total_value,
        total_value_after=after.total_value,
        changes=tuple(changes),
    )


def latest_pair(snapshots: Sequence[Snapshot]) -> tuple[Snapshot, Snapshot] | None:
    """The two most recent snapshots, ordered by :attr:`~app.institutions.models.Snapshot.period`.

    **Never by ``filed``.** A real iShares NPORT-P filed 2026-07-13 reports the period ending
    2025-09-30 -- months older than one iShares filed 2026-05-28 reporting the period ending
    2026-03-31. Sorting on filing date would pick the 2026-07-13 filing as "more recent" because it
    landed on EDGAR later, and hand :func:`diff` a pair that runs backwards: a stale re-filing of an
    old quarter reported as the *later* snapshot, so real trades in the intervening quarters show up
    as reversed the wrong way.

    Returns ``None`` when there are fewer than two distinct periods -- including when ``snapshots``
    is empty, or every snapshot in it shares one period.

    When two snapshots share a period (an amended filing restating the same quarter), the one with
    the later ``filed`` date wins for that period, on the theory that a restatement supersedes the
    filing it amends and is the one a reader wants reflected in the diff.
    """
    if not snapshots:
        return None

    best_by_period: dict[dt.date, Snapshot] = {}
    for snap in snapshots:
        current = best_by_period.get(snap.period)
        if current is None or snap.filed > current.filed:
            best_by_period[snap.period] = snap

    periods = sorted(best_by_period)
    if len(periods) < 2:
        return None

    before_period, after_period = periods[-2], periods[-1]
    return best_by_period[before_period], best_by_period[after_period]
