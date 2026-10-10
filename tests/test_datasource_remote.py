"""``app.datasource`` in remote mode, against an in-memory fake of the data service's wire contract."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import datasource
from app.config import Settings
from app.core.models import Account, AccountType, Broker, TaxTreatment
from app.datasource import DataServiceError, demo, remote
from app.db import sqlite as ledger_db
from app.ingest.manifest import load_manifest_text
from app.ingest.service import import_paths
from tests.fakes.ledger_service_fake import TABLES, LedgerServiceFake
from tests.fixtures.synthetic_ledger import build_synthetic_ledger

TOKEN = "unit-test-token"
FIXTURE_CSV = Path(__file__).parent / "fixtures" / "sofi" / "activity_full.csv"


class _Client:
    """Wraps a TestClient so ``with _client(settings) as client`` works repeatedly without closing it."""

    def __init__(self, inner: httpx.Client) -> None:
        self.inner = inner

    def __enter__(self) -> httpx.Client:
        return self.inner

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.fixture
def fake(tmp_path: Path) -> LedgerServiceFake:
    service = LedgerServiceFake(tmp_path / "service" / "ledger.sqlite", token=TOKEN)
    seed = tmp_path / "seed.sqlite"
    build_synthetic_ledger(seed)
    service.seed_from(seed)
    return service


@pytest.fixture
def cfg(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "data_source": "remote",
            "db_service_url": "http://fake",
            "db_service_token": SecretStr(TOKEN),
            "db_service_poll_s": 0.0,
        }
    )


@pytest.fixture(autouse=True)
def _reset_remote_state() -> Iterator[None]:
    remote._last_check.clear()
    yield
    remote._last_check.clear()


def _use(monkeypatch: pytest.MonkeyPatch, fake: LedgerServiceFake, token: str = TOKEN) -> None:
    client = TestClient(fake.app, base_url="http://fake", headers={"Authorization": f"Bearer {token}"})
    monkeypatch.setattr(remote, "_client", lambda settings: _Client(client))


def _replica_rows(path: Path, table: str) -> tuple[list[str], list[list[Any]]]:
    import sqlite3

    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        cols = [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")]
        order = ", ".join(TABLES[table])
        return cols, [list(r) for r in conn.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY {order}")]
    finally:
        conn.close()


# -- reads ------------------------------------------------------------------------------------------


def test_snapshot_pull_materialises_an_identical_replica(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    path = datasource.ledger_db_path(cfg)
    assert path.name == f"r{fake.revision}.sqlite"
    assert path.parent == remote.replica_dir(cfg)
    for table in TABLES:
        assert _replica_rows(path, table) == fake.table_rows(table), table
    assert fake.count("txn") > 0


def test_second_call_inside_the_poll_window_makes_no_requests(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    patient = cfg.model_copy(update={"db_service_poll_s": 3600.0})
    first = datasource.ledger_db_path(patient)
    fake.requests.clear()
    assert datasource.ledger_db_path(patient) == first
    assert fake.requests == []


def test_unchanged_revision_checks_but_does_not_re_pull(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    datasource.ledger_db_path(cfg)
    fake.requests.clear()
    datasource.ledger_db_path(cfg)
    assert fake.requests == ["GET /v1/ledger"]


def test_revision_bump_pulls_a_new_replica_file_and_prunes_the_old(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    first = datasource.ledger_db_path(cfg)
    fake.bump_revision()
    second = datasource.ledger_db_path(cfg)
    assert second != first
    assert second.name == f"r{fake.revision}.sqlite"
    assert second.exists() and not first.exists()
    assert "GET /v1/ledger/snapshot" in fake.requests


# -- writes -----------------------------------------------------------------------------------------


def _extra_account_rows(ledger: Path) -> None:
    with ledger_db.connect(ledger) as conn:
        ledger_db.upsert_account(
            conn,
            Account(
                account_id="extra-acct",
                broker=Broker.SOFI,
                label="Extra",
                tax_treatment=TaxTreatment.TAXABLE,
                account_type=AccountType.CASH,
            ),
        )


def test_ledger_writer_posts_a_changeset_and_refreshes_the_replica(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    before_rev, before_accounts = fake.revision, fake.count("account")
    with datasource.ledger_writer(cfg) as path:
        _extra_account_rows(path)
    assert fake.revision == before_rev + 1
    assert fake.count("account") == before_accounts + 1
    replica = datasource.ledger_db_path(cfg)
    assert replica.name == f"r{fake.revision}.sqlite"
    assert _replica_rows(replica, "account") == fake.table_rows("account")
    assert not list(remote.replica_dir(cfg).glob(".write-*"))  # private working copy cleaned up


def test_import_pipeline_round_trips_through_the_service(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    manifest = load_manifest_text(
        '[[account]]\nfile = "activity_full.csv"\naccount_id = "sofi-new"\nlabel = "SoFi New"\n'
        'tax_treatment = "taxable"\naccount_type = "cash"\nbroker = "sofi"\n',
        FIXTURE_CSV.parent / "accounts.toml",
    )
    txns_before, rev_before = fake.count("txn"), fake.revision
    run = import_paths([FIXTURE_CSV], manifest=manifest, settings=cfg)
    assert run is not None
    assert fake.count("txn") > txns_before
    assert fake.revision == rev_before + 1
    replica = datasource.ledger_db_path(cfg)
    for table in TABLES:
        assert _replica_rows(replica, table) == fake.table_rows(table), table


def test_concurrent_change_is_refused_and_leaves_the_service_untouched(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    snapshot = {t: fake.table_rows(t) for t in TABLES}
    revision = fake.revision
    with pytest.raises(DataServiceError, match="changed on the data service"), datasource.ledger_writer(cfg) as path:
        _extra_account_rows(path)
        fake.bump_revision()  # another writer lands between session start and exit
    assert fake.revision == revision + 1  # only the other writer's bump
    assert {t: fake.table_rows(t) for t in TABLES} == snapshot


def test_exception_inside_the_block_posts_nothing(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    datasource.ledger_db_path(cfg)
    fake.requests.clear()
    with pytest.raises(RuntimeError, match="boom"), datasource.ledger_writer(cfg) as path:
        _extra_account_rows(path)
        raise RuntimeError("boom")
    assert "POST /v1/ledger/changesets" not in fake.requests
    assert "extra-acct" not in {row[0] for row in fake.table_rows("account")[1]}


def test_writer_with_no_changes_posts_nothing(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    revision = fake.revision
    with datasource.ledger_writer(cfg):
        pass
    assert "POST /v1/ledger/changesets" not in fake.requests
    assert fake.revision == revision


def test_writer_into_an_empty_service_uses_base_revision_zero(
    cfg: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = LedgerServiceFake(tmp_path / "empty" / "ledger.sqlite", token=TOKEN)
    _use(monkeypatch, empty)
    with datasource.ledger_writer(cfg) as path:
        _extra_account_rows(path)
    assert empty.count("account") == 1
    assert empty.revision == 1


# -- failures ---------------------------------------------------------------------------------------


class _Down:
    def __enter__(self) -> _Down:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def request(self, *args: Any, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError("connection refused")


def test_service_down_without_a_replica_raises(cfg: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remote, "_client", lambda settings: _Down())
    with pytest.raises(DataServiceError, match="unreachable"):
        datasource.ledger_db_path(cfg)


def test_service_down_with_a_replica_serves_it_stale(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    replica = datasource.ledger_db_path(cfg)
    monkeypatch.setattr(remote, "_client", lambda settings: _Down())
    assert datasource.ledger_db_path(cfg) == replica


def test_wrong_token_is_a_data_service_error(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake, token="not-the-token")
    with pytest.raises(DataServiceError, match="rejected the token"):
        datasource.ledger_db_path(cfg)


def test_schema_version_mismatch_is_a_data_service_error(
    cfg: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    behind = LedgerServiceFake(tmp_path / "old" / "ledger.sqlite", token=TOKEN, schema_version=ledger_db.SCHEMA_VERSION - 1)
    _use(monkeypatch, behind)
    with pytest.raises(DataServiceError, match="schema version"):
        datasource.ledger_db_path(cfg)
    assert not list(remote.replica_dir(cfg).glob("r*.sqlite"))


# -- documents --------------------------------------------------------------------------------------


def test_document_round_trip_and_none_on_404(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake)
    assert datasource.read_document("accounts-manifest", cfg) is None
    datasource.write_document("accounts-manifest", "[[account]]\n", cfg)
    assert datasource.read_document("accounts-manifest", cfg) == "[[account]]\n"
    datasource.write_document("accounts-manifest", "# v2\n", cfg)
    assert datasource.read_document("accounts-manifest", cfg) == "# v2\n"
    assert fake.documents["accounts-manifest"]["version"] == 2
    assert datasource.read_document("planner-board", cfg) is None


def test_document_calls_with_a_bad_token_raise(
    cfg: Settings, fake: LedgerServiceFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, fake, token="nope")
    with pytest.raises(DataServiceError):
        datasource.read_document("sectors", cfg)


# -- configuration ----------------------------------------------------------------------------------


def test_validate_settings_rejects_remote_without_a_token(cfg: Settings) -> None:
    with pytest.raises(DataServiceError, match="DB_SERVICE_TOKEN"):
        datasource.validate_settings(cfg.model_copy(update={"db_service_token": None}))
    with pytest.raises(DataServiceError, match="DB_SERVICE_TOKEN"):
        datasource.validate_settings(cfg.model_copy(update={"db_service_token": SecretStr("")}))


def test_validate_settings_rejects_a_non_http_url(cfg: Settings) -> None:
    with pytest.raises(DataServiceError, match="http"):
        datasource.validate_settings(cfg.model_copy(update={"db_service_url": "ftp://x"}))


def test_validate_settings_accepts_valid_remote_and_ignores_other_modes(cfg: Settings, settings: Settings) -> None:
    datasource.validate_settings(cfg)
    datasource.validate_settings(settings)  # local mode needs no token
    datasource.validate_settings(settings.model_copy(update={"data_source": "demo"}))


def test_client_requires_a_token(cfg: Settings) -> None:
    with pytest.raises(DataServiceError, match="TOKEN"):
        remote._client(cfg.model_copy(update={"db_service_token": None}))


# -- diff_ledgers -----------------------------------------------------------------------------------


def test_diff_ledgers_emits_only_new_or_changed_rows(tmp_path: Path) -> None:
    base, work = tmp_path / "base.sqlite", tmp_path / "work.sqlite"
    demo.build_demo_ledger(base)
    work.write_bytes(base.read_bytes())
    assert remote.diff_ledgers(base, work) == {}

    with ledger_db.connect(work) as conn:
        conn.execute("UPDATE account SET label = 'Renamed' WHERE account_id = 'demo-roth'")
    with ledger_db.connect(work) as conn:
        ledger_db.upsert_account(
            conn,
            Account(
                account_id="brand-new",
                broker=Broker.SOFI,
                label="New",
                tax_treatment=TaxTreatment.TAXABLE,
                account_type=AccountType.CASH,
            ),
        )
    diff = remote.diff_ledgers(base, work)
    assert set(diff) == {"account"}
    ids = {row[diff["account"]["columns"].index("account_id")] for row in diff["account"]["rows"]}
    assert ids == {"demo-roth", "brand-new"}


def test_diff_ledgers_against_no_base_emits_everything(tmp_path: Path) -> None:
    work = tmp_path / "work.sqlite"
    demo.build_demo_ledger(work)
    diff = remote.diff_ledgers(None, work)
    assert {"account", "instrument", "raw_import", "txn"} <= set(diff)
    assert len(diff["txn"]["rows"]) > 50
