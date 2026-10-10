"""``ExportOrder.replay_order_for``: the row-index -> chronological-rank mapping every adapter now
relies on for same-day ordering when the broker publishes no execution timestamp.

The bug this whole mechanism exists to pin closed is one fact: all three real broker exports write
newest-first, and until ``ExportOrder`` existed the system had no explicit model of that at all --
``fetch_transactions`` broke same-date ties on the row's raw file position, on the undocumented
assumption that oldest-first was the only possibility. See ``app/ingest/adapters/base.py``'s module
docstring for what reading the file backwards cost on a real ledger.
"""

from __future__ import annotations

import pytest

from app.ingest.adapters.base import ExportOrder


class TestOldestFirst:
    def test_replay_order_is_the_row_index_unchanged(self) -> None:
        assert [ExportOrder.OLDEST_FIRST.replay_order_for(i, 5) for i in range(5)] == [
            0,
            1,
            2,
            3,
            4,
        ]

    def test_single_row_file(self) -> None:
        assert ExportOrder.OLDEST_FIRST.replay_order_for(0, 1) == 0


class TestNewestFirst:
    def test_replay_order_reverses_the_file(self) -> None:
        # 5 rows, newest first: row 0 (most recent) must rank last; row 4 (oldest) first.
        assert [ExportOrder.NEWEST_FIRST.replay_order_for(i, 5) for i in range(5)] == [
            4,
            3,
            2,
            1,
            0,
        ]

    def test_first_row_gets_the_highest_rank(self) -> None:
        """Row 0 is what the broker wrote first, which is what happened *last*. Getting this
        backwards is exactly the bug: it is what made a same-day sell replay before its buy."""
        total = 12
        assert ExportOrder.NEWEST_FIRST.replay_order_for(0, total) == total - 1

    def test_last_row_gets_rank_zero(self) -> None:
        total = 12
        assert ExportOrder.NEWEST_FIRST.replay_order_for(total - 1, total) == 0

    def test_single_row_file(self) -> None:
        assert ExportOrder.NEWEST_FIRST.replay_order_for(0, 1) == 0


@pytest.mark.parametrize("order", [ExportOrder.OLDEST_FIRST, ExportOrder.NEWEST_FIRST])
def test_both_directions_are_strictly_monotonic_in_row_index(order: ExportOrder) -> None:
    """Whichever direction a broker writes in, a later row index must never rank chronologically
    earlier than the row before it -- `fetch_transactions` trusts `replay_order` as a total,
    ascending-is-earlier ordering within one file, and ties within a file would make that ordering
    arbitrary exactly where it is supposed to be decisive.
    """
    total = 20
    ranks = [order.replay_order_for(i, total) for i in range(total)]
    if order is ExportOrder.OLDEST_FIRST:
        assert ranks == sorted(ranks)
    else:
        assert ranks == sorted(ranks, reverse=True)
    assert len(set(ranks)) == len(ranks), "no two rows in one file may tie on replay_order"


def test_oldest_and_newest_first_agree_only_when_the_file_has_one_row() -> None:
    """A one-row file is the only case where direction cannot matter -- there is nothing to
    order relative to. Any longer file must disagree, which is the parametrized test above's
    real content; this just states the boundary explicitly."""
    assert (
        ExportOrder.OLDEST_FIRST.replay_order_for(0, 1)
        == ExportOrder.NEWEST_FIRST.replay_order_for(0, 1)
        == 0
    )
    assert ExportOrder.OLDEST_FIRST.replay_order_for(0, 2) != ExportOrder.NEWEST_FIRST.replay_order_for(
        0, 2
    )
