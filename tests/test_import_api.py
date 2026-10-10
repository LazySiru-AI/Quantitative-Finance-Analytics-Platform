"""The import endpoint -- the only route in this application that writes.

The orchestration itself is covered by `tests/test_ingest_service.py`. What matters here is the
boundary: that a preview stays a preview, that a caller cannot name a file outside the data
directory, and that the two ways an import legitimately does not happen -- no manifest, nothing to
import -- come back as answers a user can act on rather than a 500.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app

FIXTURES = Path(__file__).parent / "fixtures"
RH = FIXTURES / "robinhood" / "rh_activity.csv"
SOFI = FIXTURES / "sofi" / "activity_full.csv"


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _place(settings: Settings, source: Path, name: str) -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    target = settings.data_dir / name
    target.write_bytes(source.read_bytes())
    return target


def _manifest(settings: Settings, body: str) -> None:
    path = settings.data_dir / "accounts.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


ENTRY = """
[[account]]
file = "{file}"
account_id = "{account_id}"
tax_treatment = "taxable"
"""


class TestPreview:
    def test_empty_data_directory_is_not_an_error(self, client: TestClient) -> None:
        """A fresh checkout has nothing to import. That is a state to describe, not fail on."""
        body = client.get("/api/import").json()
        assert body["files"] == []
        assert body["importable"] == 0
        assert body["manifest"]["present"] is False

    def test_preview_works_without_a_manifest(
        self, client: TestClient, settings: Settings
    ) -> None:
        """This is exactly when a user needs to see what was found."""
        _place(settings, RH, "RH.csv")
        body = client.get("/api/import").json()

        assert body["manifest"]["present"] is False
        assert len(body["files"]) == 1
        assert body["files"][0]["status"] == "undeclared"
        assert body["files"][0]["adapter"] == "robinhood", "the broker is still detected"
        assert body["importable"] == 0

    def test_preview_shows_the_account_each_file_would_land_in(
        self, client: TestClient, settings: Settings
    ) -> None:
        """The one input nothing downstream can validate, shown before it is applied."""
        _place(settings, RH, "RH.csv")
        _manifest(settings, ENTRY.format(file="RH.csv", account_id="rh-taxable"))
        body = client.get("/api/import").json()

        assert body["files"][0]["account_id"] == "rh-taxable"
        assert body["files"][0]["tax_treatment"] == "taxable"
        assert body["importable"] == 1

    def test_preview_writes_nothing(self, client: TestClient, settings: Settings) -> None:
        _place(settings, RH, "RH.csv")
        _manifest(settings, ENTRY.format(file="RH.csv", account_id="rh-taxable"))
        client.get("/api/import")
        client.get("/api/import")

        with_ledger = client.get("/api/health/stores").json()
        assert with_ledger["ledger"]["transactions"] == 0

    def test_a_malformed_manifest_is_reported_not_hidden(
        self, client: TestClient, settings: Settings
    ) -> None:
        """Absent and broken are different problems with different fixes."""
        _place(settings, RH, "RH.csv")
        _manifest(settings, "this is not toml [[[")
        body = client.get("/api/import").json()

        assert body["manifest"]["present"] is True
        assert body["manifest"]["error"]
        assert body["manifest"]["entries"] == 0


class TestImport:
    def test_import_lands_rows_and_reports_them(
        self, client: TestClient, settings: Settings
    ) -> None:
        _place(settings, RH, "RH.csv")
        _manifest(settings, ENTRY.format(file="RH.csv", account_id="rh-taxable"))

        body = client.post("/api/import", json={}).json()
        assert body["ok"] is True
        assert body["inserted"] > 0
        assert body["files"][0]["status"] == "imported"
        assert body["txn_count"] == body["inserted"]

        stores = client.get("/api/health/stores").json()
        assert stores["ledger"]["transactions"] == body["inserted"]

    def test_reimport_is_a_no_op(self, client: TestClient, settings: Settings) -> None:
        _place(settings, RH, "RH.csv")
        _manifest(settings, ENTRY.format(file="RH.csv", account_id="rh-taxable"))

        first = client.post("/api/import", json={}).json()
        second = client.post("/api/import", json={}).json()

        assert second["inserted"] == 0
        assert second["files"][0]["status"] == "unchanged"
        assert second["ledger_fingerprint"] == first["ledger_fingerprint"]

    def test_a_subset_can_be_named(self, client: TestClient, settings: Settings) -> None:
        _place(settings, RH, "RH.csv")
        _place(settings, SOFI, "SOFI.csv")
        _manifest(
            settings,
            ENTRY.format(file="RH.csv", account_id="rh-taxable")
            + ENTRY.format(file="SOFI.csv", account_id="sofi-taxable"),
        )

        body = client.post("/api/import", json={"filenames": ["SOFI.csv"]}).json()
        assert [f["filename"] for f in body["files"]] == ["SOFI.csv"]
        assert body["files"][0]["account_id"] == "sofi-taxable"

    @pytest.mark.parametrize(
        "name",
        [
            "../../../etc/passwd",
            "/etc/passwd",
            "C:/Windows/win.ini",
            "..\\..\\secrets.csv",
            "store/ledger.sqlite",
        ],
    )
    def test_a_path_outside_the_data_directory_is_refused(
        self, client: TestClient, settings: Settings, name: str
    ) -> None:
        """Names are matched against the discovered set, never joined onto a path.

        There is no traversal to defend against as long as that stays true, and this asserts it
        stays true: every one of these must be a 404 naming what was not found, not a read.
        """
        _place(settings, RH, "RH.csv")
        _manifest(settings, ENTRY.format(file="RH.csv", account_id="rh-taxable"))

        response = client.post("/api/import", json={"filenames": [name]})
        assert response.status_code == 404
        assert "not found in the data directory" in response.json()["detail"]

    def test_missing_manifest_is_422_with_the_fix_in_the_message(
        self, client: TestClient, settings: Settings
    ) -> None:
        """The request is well-formed and the server is healthy; a declaration is missing."""
        _place(settings, RH, "RH.csv")
        response = client.post("/api/import", json={})

        assert response.status_code == 422
        assert "--init" in response.json()["detail"]

    def test_nothing_to_import_is_422_not_a_silent_success(
        self, client: TestClient, settings: Settings
    ) -> None:
        """An empty run returning ok=true would read as "your exports were imported"."""
        _manifest(settings, ENTRY.format(file="RH.csv", account_id="rh-taxable"))
        response = client.post("/api/import", json={})

        assert response.status_code == 422
        assert "no broker exports found" in response.json()["detail"]

    def test_undeclared_file_makes_the_run_unclean(
        self, client: TestClient, settings: Settings
    ) -> None:
        _place(settings, RH, "RH.csv")
        _place(settings, SOFI, "SOFI.csv")
        _manifest(settings, ENTRY.format(file="RH.csv", account_id="rh-taxable"))

        body = client.post("/api/import", json={}).json()
        statuses = {f["filename"]: f["status"] for f in body["files"]}

        assert statuses["SOFI.csv"] == "undeclared"
        assert body["ok"] is False
        assert body["inserted"] > 0, "the declared file still imported"

    def test_the_body_is_optional(self, client: TestClient, settings: Settings) -> None:
        _place(settings, RH, "RH.csv")
        _manifest(settings, ENTRY.format(file="RH.csv", account_id="rh-taxable"))
        assert client.post("/api/import").status_code == 200

    def test_an_unknown_field_is_rejected(self, client: TestClient, settings: Settings) -> None:
        """`extra="forbid"`: a client sending `files` instead of `filenames` must hear about it
        rather than have every export imported because the field was ignored."""
        _place(settings, RH, "RH.csv")
        _manifest(settings, ENTRY.format(file="RH.csv", account_id="rh-taxable"))
        assert client.post("/api/import", json={"files": ["RH.csv"]}).status_code == 422
