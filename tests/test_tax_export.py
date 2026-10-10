"""``GET /api/tax/export/disposals.csv`` and ``.../washsales.csv`` -- the CPA reconciliation pack.

Written against a real SQLite ledger, like ``tests/test_tax_api.py``, and reusing that module's
fixture ledger rather than building a second one: these two exports are supposed to mirror the
tables the JSON routes already serve, so proving them against the *same* three scenarios
(``SOXL`` deferred, ``SPLIT`` one disposal replaced half taxable and half Roth, ``OPENX`` an open
window with no event) is what makes "mirror" checkable rather than asserted.

What these tests pin:

* both routes answer 200 with a header row that matches the module's declared column order, so a
  column silently added, dropped or reordered fails here rather than in a spreadsheet;
* a year with no rows returns the header **alone** -- an empty year is a real answer and must not
  arrive as a zero-byte file indistinguishable from a failed download;
* the body is UTF-8 with a BOM, because that is the one thing standing between an account label
  and Excel's ANSI codepage;
* the split disposal reaches the wash-sale export as two lines with different treatments, never
  one line summing a deferred loss and a destroyed one.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import sqlite as ledger
from app.main import app
from app.tax.export import DISPOSALS_CSV_HEADER, WASH_SALES_CSV_HEADER

# The scenario ledger is imported from `tests/test_tax_api.py` rather than re-derived -- see this
# module's docstring for why these exports are proven against the same three scenarios the JSON
# routes are. The two `@pytest.fixture`s below are redeclared instead of imported: importing a
# fixture by name shadows it at module scope and every test signature then reads as a redefinition
# (F811), which is noise, not a finding.
from tests.test_tax_api import (
    ACCOUNT,
    ROTH,
    _open_window_transactions,
    _record_import,
    _split_transactions,
    _wash_sale_transactions,
)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def seeded(settings: Settings, client: TestClient) -> Settings:
    with ledger.connect(settings.ledger_path) as conn:
        ledger.migrate(conn)
        ledger.upsert_account(conn, ACCOUNT)
        ledger.upsert_account(conn, ROTH)
        _record_import(conn)
        ledger.insert_transactions(
            conn,
            [
                *_wash_sale_transactions(),
                *_split_transactions(),
                *_open_window_transactions(),
            ],
        )
    return settings

#: The year `SPLIT`'s disposal falls in: one sale replaced half in a taxable account and half in a
#: Roth, i.e. one disposal that must reach the wash-sale export as two differently-treated lines.
SPLIT_YEAR = 2023

#: A year the fixture ledger has no activity in at all, for the empty-year cases. Well inside the
#: endpoint's own 1990..2100 bounds, so an empty answer here is "nothing happened", never a 422.
EMPTY_YEAR = 1999

BOM = "﻿"


def _rows(body: bytes) -> list[list[str]]:
    """Decode a CSV response body the way a spreadsheet would and return its rows.

    ``utf-8-sig`` rather than ``utf-8``: it strips the BOM if one is present and is a no-op if not,
    so this helper does not itself decide whether the BOM is there. That is asserted separately,
    on the raw bytes, in `TestCsvEncoding`.
    """
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


class TestDisposalsExport:
    def test_answers_200_with_the_declared_header(
        self, client: TestClient, seeded: Settings
    ) -> None:
        response = client.get(f"/api/tax/export/disposals.csv?year={SPLIT_YEAR}")
        assert response.status_code == 200
        assert _rows(response.content)[0] == list(DISPOSALS_CSV_HEADER)

    def test_is_served_as_a_named_csv_attachment(
        self, client: TestClient, seeded: Settings
    ) -> None:
        response = client.get(f"/api/tax/export/disposals.csv?year={SPLIT_YEAR}")
        assert response.headers["content-type"].startswith("text/csv")
        assert f'filename="disposals-{SPLIT_YEAR}.csv"' in response.headers["content-disposition"]

    def test_carries_the_years_disposals(self, client: TestClient, seeded: Settings) -> None:
        """`SPLIT` was sold in 2023, so its disposal is the row this year's export must carry."""
        rows = _rows(client.get(f"/api/tax/export/disposals.csv?year={SPLIT_YEAR}").content)
        symbols = {row[DISPOSALS_CSV_HEADER.index("Symbol")] for row in rows[1:]}
        assert "SPLIT" in symbols

    def test_dates_are_iso_and_money_is_a_plain_decimal(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """No locale, no currency symbol, no thousands separator -- a spreadsheet has to sum it."""
        rows = _rows(client.get(f"/api/tax/export/disposals.csv?year={SPLIT_YEAR}").content)
        assert len(rows) > 1
        row = rows[1]
        sold = row[DISPOSALS_CSV_HEADER.index("Date Sold")]
        proceeds = row[DISPOSALS_CSV_HEADER.index("Proceeds")]
        assert len(sold) == 10 and sold[4] == "-" and sold[7] == "-"
        assert proceeds.replace("-", "").replace(".", "").isdigit()
        assert "," not in proceeds and "$" not in proceeds

    def test_a_year_with_no_rows_returns_just_the_header(
        self, client: TestClient, seeded: Settings
    ) -> None:
        response = client.get(f"/api/tax/export/disposals.csv?year={EMPTY_YEAR}")
        assert response.status_code == 200
        assert _rows(response.content) == [list(DISPOSALS_CSV_HEADER)]

    def test_a_missing_ledger_is_a_404_not_an_empty_file(
        self, client: TestClient, settings: Settings
    ) -> None:
        """The same distinction `/report` makes: "no ledger" is not "no disposals this year", and
        an empty CSV would say the second while meaning the first."""
        settings.ledger_path.unlink()
        assert client.get("/api/tax/export/disposals.csv?year=2023").status_code == 404


class TestWashSalesExport:
    def test_answers_200_with_the_declared_header(
        self, client: TestClient, seeded: Settings
    ) -> None:
        response = client.get(f"/api/tax/export/washsales.csv?year={SPLIT_YEAR}")
        assert response.status_code == 200
        assert _rows(response.content)[0] == list(WASH_SALES_CSV_HEADER)

    def test_is_served_as_a_named_csv_attachment(
        self, client: TestClient, seeded: Settings
    ) -> None:
        response = client.get(f"/api/tax/export/washsales.csv?year={SPLIT_YEAR}")
        assert response.headers["content-type"].startswith("text/csv")
        assert f'filename="washsales-{SPLIT_YEAR}.csv"' in response.headers["content-disposition"]

    def test_one_split_disposal_exports_as_two_differently_treated_lines(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """The deferred half and the Rev. Rul. 2008-5 half are not commensurable, so they must
        never arrive collapsed into one line with one summed "Disallowed" figure."""
        rows = _rows(client.get(f"/api/tax/export/washsales.csv?year={SPLIT_YEAR}").content)
        symbol_col = WASH_SALES_CSV_HEADER.index("Symbol")
        treatment_col = WASH_SALES_CSV_HEADER.index("Treatment")
        disposal_col = WASH_SALES_CSV_HEADER.index("Disposal ID")

        split_rows = [row for row in rows[1:] if row[symbol_col] == "SPLIT"]
        assert len(split_rows) == 2
        assert len({row[disposal_col] for row in split_rows}) == 1
        assert {row[treatment_col] for row in split_rows} == {"Deferred", "Permanently disallowed"}

    def test_accounts_column_leads_with_the_selling_account(
        self, client: TestClient, seeded: Settings
    ) -> None:
        rows = _rows(client.get(f"/api/tax/export/washsales.csv?year={SPLIT_YEAR}").content)
        accounts_col = WASH_SALES_CSV_HEADER.index("Accounts")
        sale_account_col = WASH_SALES_CSV_HEADER.index("Sale Account ID")
        assert len(rows) > 1
        for row in rows[1:]:
            assert row[accounts_col].split(", ")[0] == row[sale_account_col]

    def test_a_year_with_no_rows_returns_just_the_header(
        self, client: TestClient, seeded: Settings
    ) -> None:
        response = client.get(f"/api/tax/export/washsales.csv?year={EMPTY_YEAR}")
        assert response.status_code == 200
        assert _rows(response.content) == [list(WASH_SALES_CSV_HEADER)]

    def test_a_missing_ledger_is_a_404_not_an_empty_file(
        self, client: TestClient, settings: Settings
    ) -> None:
        settings.ledger_path.unlink()
        assert client.get("/api/tax/export/washsales.csv?year=2023").status_code == 404


class TestCsvEncoding:
    """Both files are opened in Excel by a person, not parsed by a program -- hence the BOM."""

    def test_both_exports_are_utf8_with_a_bom(self, client: TestClient, seeded: Settings) -> None:
        for path in ("disposals", "washsales"):
            body = client.get(f"/api/tax/export/{path}.csv?year={SPLIT_YEAR}").content
            assert body.startswith(b"\xef\xbb\xbf"), path
            assert body.decode("utf-8").startswith(BOM), path

    def test_the_bom_does_not_leak_into_the_first_column_name(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """A BOM read as content rather than encoding turns "Date Sold" into "﻿Date Sold",
        which a CPA's spreadsheet template then fails to match on. Decoding as `utf-8-sig` is what
        every real consumer does; this pins that the byte is a BOM and not part of the header."""
        rows = _rows(client.get(f"/api/tax/export/disposals.csv?year={SPLIT_YEAR}").content)
        assert rows[0][0] == "Date Sold"

    def test_exports_are_byte_identical_across_repeated_requests(
        self, client: TestClient, seeded: Settings
    ) -> None:
        """Fixed line terminator and fixed column order, so a diff of two exports means something."""
        url = f"/api/tax/export/disposals.csv?year={SPLIT_YEAR}"
        assert client.get(url).content == client.get(url).content
