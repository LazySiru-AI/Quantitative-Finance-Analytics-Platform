"""Identity must survive a *longer* export of the same account.

The store exists for one reason, stated in `docs/PLAN.md`: *"the payoff isn't query speed -- it's
idempotent re-import. Next month's export will overlap heavily with this one, and naive appending
silently duplicates lots, which corrupts every downstream tax number."*

That guarantee did not hold. `sequence` was the row's absolute position in the source file and is
part of `txn_id`, so a re-export covering more history moved every row and changed every id --
which is precisely "next month's export", the case the design was written for. It went unnoticed
because every test re-parsed the *same* file, where positions do not move.

Seen on real data when fresh exports were added: a Robinhood export of an account already holding
transactions shared nearly all of them by content and **zero** by id. Importing it would have added
every row again and double-counted months of trades.

These tests parse a file, then parse a superset of it, and assert the shared rows keep their
identity. The tests in the per-adapter modules cover re-parsing the identical file; that is a weaker
property and it passed throughout.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import Account, AccountType, Broker, TaxTreatment
from app.ingest import registry
from app.ingest.adapters.base import AdapterResult
from app.ingest.provenance import read_rows

FIXTURES = Path(__file__).parent / "fixtures"

ROBINHOOD_HEADER = (
    "Activity Date,Process Date,Settle Date,Instrument,Description,"
    "Trans Code,Quantity,Price,Amount"
)
WEBULL_HEADER = (
    "Name,Symbol,Side,Status,Filled,Total Qty,Price,Avg Price,"
    "Time-in-Force,Placed Time,Filled Time"
)
SOFI_HEADER = "Date,Ticker/Type,Description,Shares,Price,Notes,Amount"

#: Three older Robinhood trades, then two newer ones. A later export of the same account carries the
#: newer rows *above* the older ones, which is what moves every position.
RH_OLD = [
    '"3/2/2026","3/2/2026","3/3/2026","AAAA","Buy","Buy","10","$10.00","($100.00)"',
    '"3/3/2026","3/3/2026","3/4/2026","BBBB","Buy","Buy","5","$20.00","($100.00)"',
    '"3/4/2026","3/4/2026","3/5/2026","CCCC","Sell","Sell","2","$50.00","$100.00"',
]
RH_NEW = [
    '"4/1/2026","4/1/2026","4/2/2026","DDDD","Buy","Buy","1","$70.00","($70.00)"',
    '"4/2/2026","4/2/2026","4/3/2026","EEEE","Buy","Buy","3","$30.00","($90.00)"',
]


def _account(broker: Broker, account_id: str) -> Account:
    return Account(
        account_id=account_id,
        broker=broker,
        label=account_id,
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )


def _parse(path: Path, account: Account) -> AdapterResult:
    registry.load_builtin_adapters()
    raw = read_rows(path)
    adapter = registry.resolve(raw)
    return adapter.parse(raw, account=account, import_id="imp")


def _write(path: Path, header: str, rows: list[str]) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


class TestSupersetExportKeepsIdentity:
    def test_robinhood_rows_keep_their_ids_when_the_export_grows(self, tmp_path: Path) -> None:
        """The case that was broken, at its smallest.

        The later export leads with two newer trades, so every older row sits two positions further
        down. Under the old positional `sequence` all three changed id and would have been inserted
        a second time.
        """
        account = _account(Broker.ROBINHOOD, "rh-taxable")
        first = _parse(_write(tmp_path / "a.csv", ROBINHOOD_HEADER, RH_OLD), account)
        second = _parse(_write(tmp_path / "b.csv", ROBINHOOD_HEADER, RH_NEW + RH_OLD), account)

        old_ids = {t.txn_id for t in first.transactions}
        new_ids = {t.txn_id for t in second.transactions}

        assert len(old_ids) == 3
        assert old_ids <= new_ids, "every previously stored trade must be recognised, not re-added"
        assert len(new_ids - old_ids) == 2, "and exactly the two genuinely new trades are new"

    def test_source_row_still_moves_because_provenance_should(self, tmp_path: Path) -> None:
        """`source_row` is the coordinate into *that* file. It is meant to differ between exports.

        Keeping it positional is what lets a figure be walked back to a line in the CSV it came
        from; identity is a separate question and the two were conflated.
        """
        account = _account(Broker.ROBINHOOD, "rh-taxable")
        first = _parse(_write(tmp_path / "a.csv", ROBINHOOD_HEADER, RH_OLD), account)
        second = _parse(_write(tmp_path / "b.csv", ROBINHOOD_HEADER, RH_NEW + RH_OLD), account)

        by_id_first = {t.txn_id: t for t in first.transactions}
        moved = [
            t for t in second.transactions
            if t.txn_id in by_id_first and t.source_row != by_id_first[t.txn_id].source_row
        ]
        assert moved, "the rows did move in the file; that is the whole premise"
        for txn in moved:
            assert txn.txn_id == by_id_first[txn.txn_id].txn_id

    def test_webull_rows_keep_their_ids_when_the_export_grows(self, tmp_path: Path) -> None:
        account = _account(Broker.WEBULL, "wb-cash")
        old = [
            "Fund,AAAA,Buy,Filled,10,10,@10.0000000000,10.0000000000,DAY,"
            "03/02/2026 10:00:00 EST,03/02/2026 10:00:01 EST",
            "Fund,BBBB,Sell,Filled,5,5,@20.0000000000,20.0000000000,DAY,"
            "03/03/2026 10:00:00 EST,03/03/2026 10:00:01 EST",
        ]
        new = [
            "Fund,CCCC,Buy,Filled,7,7,@30.0000000000,30.0000000000,DAY,"
            "04/01/2026 10:00:00 EDT,04/01/2026 10:00:01 EDT",
        ]
        first = _parse(_write(tmp_path / "w1.csv", WEBULL_HEADER, old), account)
        second = _parse(_write(tmp_path / "w2.csv", WEBULL_HEADER, new + old), account)

        assert {t.txn_id for t in first.transactions} <= {t.txn_id for t in second.transactions}

    def test_sofi_rows_keep_their_ids_when_the_export_grows(self, tmp_path: Path) -> None:
        account = _account(Broker.SOFI, "sofi-taxable")
        old = [
            "2026-03-02,AAAA,Market buy,1.0,10.0,,-10.0",
            "2026-03-03,BBBB,Market sell,2.0,20.0,,40.0",
        ]
        new = ["2026-04-01,CCCC,Market buy,3.0,30.0,,-90.0"]
        first = _parse(_write(tmp_path / "s1.csv", SOFI_HEADER, old), account)
        second = _parse(_write(tmp_path / "s2.csv", SOFI_HEADER, new + old), account)

        assert {t.txn_id for t in first.transactions} <= {t.txn_id for t in second.transactions}


class TestDuplicatesStayDistinct:
    """The property `sequence` was introduced for, which the fix must not trade away."""

    def test_two_identical_same_day_trades_remain_two_transactions(self, tmp_path: Path) -> None:
        account = _account(Broker.ROBINHOOD, "rh-taxable")
        dupes = [
            '"3/2/2026","3/2/2026","3/3/2026","AAAA","Buy","Buy","10","$10.00","($100.00)"',
            '"3/2/2026","3/2/2026","3/3/2026","AAAA","Buy","Buy","10","$10.00","($100.00)"',
        ]
        result = _parse(_write(tmp_path / "d.csv", ROBINHOOD_HEADER, dupes), account)

        assert len({t.txn_id for t in result.transactions}) == 2
        assert sorted(t.sequence for t in result.transactions) == [0, 1]

    def test_a_duplicated_pair_keeps_its_ids_when_the_export_grows(self, tmp_path: Path) -> None:
        """The hard case: duplicates *and* a growing file at once.

        The ordinal counts only a row's own twins, so the pair stays `{0, 1}` however far down the
        file it moves -- which is what makes both halves of the guarantee hold together.
        """
        account = _account(Broker.ROBINHOOD, "rh-taxable")
        dupes = [
            '"3/2/2026","3/2/2026","3/3/2026","AAAA","Buy","Buy","10","$10.00","($100.00)"',
            '"3/2/2026","3/2/2026","3/3/2026","AAAA","Buy","Buy","10","$10.00","($100.00)"',
        ]
        first = _parse(_write(tmp_path / "a.csv", ROBINHOOD_HEADER, dupes), account)
        second = _parse(_write(tmp_path / "b.csv", ROBINHOOD_HEADER, RH_NEW + dupes), account)

        assert {t.txn_id for t in first.transactions} <= {t.txn_id for t in second.transactions}
        assert len({t.txn_id for t in first.transactions}) == 2


@pytest.mark.parametrize("broker", [Broker.ROBINHOOD, Broker.WEBULL, Broker.SOFI])
def test_identity_still_separates_accounts(broker: Broker, tmp_path: Path) -> None:
    """The same trade in two accounts is two transactions, and must stay so.

    `account_id` is part of the hash; this pins that the sequencer did not accidentally key on
    anything narrower.
    """
    header, rows = {
        Broker.ROBINHOOD: (ROBINHOOD_HEADER, RH_OLD),
        Broker.WEBULL: (
            WEBULL_HEADER,
            [
                "Fund,AAAA,Buy,Filled,10,10,@10.0000000000,10.0000000000,DAY,"
                "03/02/2026 10:00:00 EST,03/02/2026 10:00:01 EST"
            ],
        ),
        Broker.SOFI: (SOFI_HEADER, ["2026-03-02,AAAA,Market buy,1.0,10.0,,-10.0"]),
    }[broker]

    path = _write(tmp_path / "x.csv", header, rows)
    one = _parse(path, _account(broker, "acct-one"))
    two = _parse(path, _account(broker, "acct-two"))

    assert {t.txn_id for t in one.transactions}.isdisjoint({t.txn_id for t in two.transactions})
