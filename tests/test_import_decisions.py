"""Choosing where an export goes: attach to an existing account, or open a new one.

This is the decision the Import panel exists to put in front of the user, and the only input in the
whole pipeline that no validation can check for them. The endpoint's job is to show what the ledger
actually contains and let them choose. It must never attach a file on its own, and it must never let
a file restate an account's tax treatment.
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

ENTRY = """
[[account]]
file = "{file}"
account_id = "{account_id}"
tax_treatment = "{treatment}"
"""


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


def _entry(file: str, account_id: str, treatment: str = "taxable") -> str:
    return ENTRY.format(file=file, account_id=account_id, treatment=treatment)


def _seed(client: TestClient, settings: Settings, account_id: str = "rh-taxable",
          treatment: str = "taxable") -> None:
    """One imported Robinhood file, so there is an account to match against."""
    _place(settings, RH, "RH.csv")
    _manifest(settings, _entry("RH.csv", account_id, treatment))
    client.post("/api/import", json={})


class TestMatchEvidence:
    def test_a_re_export_of_a_stored_account_is_suggested(
        self, client: TestClient, settings: Settings
    ) -> None:
        """The same file again is the simplest re-export: it contains the account whole."""
        _seed(client, settings)
        _place(settings, RH, "RH-fresh.csv")

        body = client.get("/api/import").json()
        fresh = next(f for f in body["files"] if f["filename"] == "RH-fresh.csv")

        assert fresh["status"] == "undeclared", "a match is evidence, not an assignment"
        assert fresh["suggested_account_id"] == "rh-taxable"
        assert fresh["match_is_ambiguous"] is False

        best = fresh["matches"][0]
        assert best["account_id"] == "rh-taxable"
        assert best["account_coverage"] == 1.0
        assert best["overlapping"] == best["incoming_total"]
        assert best["new_rows"] == 0

    def test_an_unrelated_broker_offers_no_candidates(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A SoFi export cannot be a Robinhood account; offering it would be noise."""
        _seed(client, settings)
        _place(settings, SOFI, "SOFI.csv")

        body = client.get("/api/import").json()
        sofi = next(f for f in body["files"] if f["filename"] == "SOFI.csv")

        assert sofi["suggested_account_id"] is None
        assert sofi["matches"] == []

    def test_preview_writes_nothing_while_matching(
        self, client: TestClient, settings: Settings
    ) -> None:
        """Matching parses every file to recompute ids. None of that may reach the ledger."""
        _seed(client, settings)
        before = client.get("/api/health/stores").json()["ledger"]["transactions"]
        _place(settings, RH, "RH-fresh.csv")

        client.get("/api/import")
        client.get("/api/import")

        assert client.get("/api/health/stores").json()["ledger"]["transactions"] == before


class TestDecisions:
    def test_a_new_account_is_created_and_persisted(
        self, client: TestClient, settings: Settings
    ) -> None:
        """The choice is written into the manifest, so the CLI sees the same answer next time."""
        _seed(client, settings)
        _place(settings, SOFI, "SOFI.csv")

        body = client.post(
            "/api/import",
            json={
                "filenames": ["SOFI.csv"],
                "decisions": [
                    {
                        "filename": "SOFI.csv",
                        "new_account": {
                            "account_id": "sofi-taxable",
                            "label": "SoFi taxable",
                            "tax_treatment": "taxable",
                        },
                    }
                ],
            },
        ).json()

        assert body["ok"] is True
        assert body["files"][0]["account_id"] == "sofi-taxable"

        manifest = (settings.data_dir / "accounts.toml").read_text(encoding="utf-8")
        assert 'file = "SOFI.csv"' in manifest
        assert 'account_id = "sofi-taxable"' in manifest

    def test_attaching_inherits_the_accounts_declared_tax_treatment(
        self, client: TestClient, settings: Settings
    ) -> None:
        """A file cannot restate an account's tax treatment.

        Treatment belongs to the account, not to a file. If a request could set it, importing one
        export could silently reclassify a Roth as taxable -- and every gain in it with it.
        """
        _seed(client, settings, account_id="rh-roth", treatment="roth_ira")
        _place(settings, RH, "RH-more.csv")

        client.post(
            "/api/import",
            json={
                "filenames": ["RH-more.csv"],
                "decisions": [{"filename": "RH-more.csv", "account_id": "rh-roth"}],
            },
        )

        manifest = (settings.data_dir / "accounts.toml").read_text(encoding="utf-8")
        assert manifest.count('tax_treatment = "roth_ira"') == 2, "inherited, not re-declared"

    def test_attaching_actually_imports_into_that_account(
        self, client: TestClient, settings: Settings
    ) -> None:
        _seed(client, settings)
        _place(settings, SOFI, "SOFI.csv")
        client.post(
            "/api/import",
            json={
                "filenames": ["SOFI.csv"],
                "decisions": [
                    {
                        "filename": "SOFI.csv",
                        "new_account": {
                            "account_id": "sofi-taxable",
                            "label": "SoFi",
                            "tax_treatment": "taxable",
                        },
                    }
                ],
            },
        )

        rows = client.get("/api/portfolio/transactions?account_id=sofi-taxable").json()
        assert rows["total"] > 0

    @pytest.mark.parametrize(
        ("payload", "why"),
        [
            (
                {
                    "filename": "RH.csv",
                    "account_id": "rh-taxable",
                    "new_account": {
                        "account_id": "rh-new",
                        "label": "New",
                        "tax_treatment": "taxable",
                    },
                },
                "both targets",
            ),
            ({"filename": "RH.csv"}, "neither target"),
        ],
    )
    def test_a_decision_must_name_exactly_one_target(
        self, client: TestClient, settings: Settings, payload: dict[str, object], why: str
    ) -> None:
        """"Attach" and "create" are opposite instructions; choosing between them is not the
        server's call."""
        _place(settings, RH, "RH.csv")
        response = client.post("/api/import", json={"decisions": [payload]})
        assert response.status_code == 422, why

    def test_creating_an_account_that_already_exists_is_refused(
        self, client: TestClient, settings: Settings
    ) -> None:
        """Proceeding would merge two books, and nothing downstream would show it happened."""
        _seed(client, settings)
        _place(settings, RH, "RH-more.csv")

        response = client.post(
            "/api/import",
            json={
                "filenames": ["RH-more.csv"],
                "decisions": [
                    {
                        "filename": "RH-more.csv",
                        "new_account": {
                            "account_id": "rh-taxable",
                            "label": "Duplicate",
                            "tax_treatment": "taxable",
                        },
                    }
                ],
            },
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_attaching_to_an_unknown_account_is_refused(
        self, client: TestClient, settings: Settings
    ) -> None:
        _place(settings, RH, "RH.csv")
        response = client.post(
            "/api/import",
            json={"decisions": [{"filename": "RH.csv", "account_id": "does-not-exist"}]},
        )
        assert response.status_code == 404

    def test_re_deciding_a_declared_file_is_refused(
        self, client: TestClient, settings: Settings
    ) -> None:
        """Rows already imported do not follow a manifest edit.

        Silently re-assigning would leave the same trades under two accounts with nothing on screen
        saying so, so the edit is left to the user's own hand.
        """
        _seed(client, settings)

        response = client.post(
            "/api/import",
            json={
                "filenames": ["RH.csv"],
                "decisions": [
                    {
                        "filename": "RH.csv",
                        "new_account": {
                            "account_id": "rh-elsewhere",
                            "label": "Elsewhere",
                            "tax_treatment": "taxable",
                        },
                    }
                ],
            },
        )
        assert response.status_code == 409
        assert "already declared" in response.json()["detail"]

    def test_a_decision_for_a_file_outside_the_data_directory_is_refused(
        self, client: TestClient, settings: Settings
    ) -> None:
        """Names are matched against the discovered set, never joined onto a path."""
        _place(settings, RH, "RH.csv")
        response = client.post(
            "/api/import",
            json={
                "decisions": [
                    {
                        "filename": "../secrets.csv",
                        "new_account": {
                            "account_id": "x",
                            "label": "X",
                            "tax_treatment": "taxable",
                        },
                    }
                ]
            },
        )
        assert response.status_code == 404

    def test_an_invalid_account_id_is_rejected_before_anything_is_written(
        self, client: TestClient, settings: Settings
    ) -> None:
        """The id is written into a TOML file and used as a key, so its shape is constrained."""
        _place(settings, RH, "RH.csv")
        response = client.post(
            "/api/import",
            json={
                "decisions": [
                    {
                        "filename": "RH.csv",
                        "new_account": {
                            "account_id": "Not A Slug",
                            "label": "X",
                            "tax_treatment": "taxable",
                        },
                    }
                ]
            },
        )
        assert response.status_code == 422
        assert not (settings.data_dir / "accounts.toml").exists()
