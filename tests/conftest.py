"""Shared fixtures.

Every fixture points storage at a temporary directory. No test may touch the user's real ledger or
their raw exports in ``data/``.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import REPO_ROOT, Settings, get_settings
from app.core.models import (
    Account,
    AccountType,
    Broker,
    TaxTreatment,
    Transaction,
    TxnAction,
)
from app.db import sqlite as ledger

DATA_DIR = REPO_ROOT / "data"

#: Real broker exports are gitignored, so tests that read them skip on a fresh clone rather than fail.
requires_real_data = pytest.mark.skipif(
    not (DATA_DIR / "RH taxable.csv").exists(),
    reason="real broker exports not present (data/ is gitignored)",
)

#: The same rule for the DuckDB/Parquet bar store, which is likewise gitignored (`data/store/`).
#:
#: Without this, a test that prices a historical window against the real store does not fail with
#: "no market data here"; it fails several layers down with whatever the pricing code raises when a
#: symbol comes back empty -- `ValueError: QQQ has 0 bars over 2013-09-03..2018-08-31` out of
#: `app.tournament.selection`, or an `IndexError` off the end of an empty date list. Fourteen tests
#: across four modules failed exactly that way on a fresh checkout on 2026-08-26 while passing on a
#: developer machine, which reads as fourteen broken features rather than one absent directory, and
#: costs whoever sees it the time to prove otherwise. The count grew from nine to fourteen while
#: this was being written, as `TestBarAvailability` landed carrying the same assumption -- the
#: pattern reappears whenever a test reaches for the real store, so reach for this marker with it.
#:
#: `tests/test_benchmarks.py` and `tests/test_marketdata_cache.py` each define their own local copy
#: of this predicate; this is the shared one for new callers, and either of those could import it
#: instead the next time they are touched.
requires_real_store = pytest.mark.skipif(
    not (DATA_DIR / "store" / "bars").exists(),
    reason="real bar store not present (data/store is gitignored; not on a fresh clone)",
)


@pytest.fixture(autouse=True, scope="session")
def _detach_dotenv() -> Iterator[None]:
    """Cut every ``Settings`` construction in the suite off from the repository's ``.env``.

    ``Settings.model_config["env_file"]`` is an **absolute path to the real repository root**, so
    ``pydantic-settings`` reads the developer's gitignored ``.env`` when building *any* Settings
    object a test produces -- including a ``tmp_path``-rooted one. A test that asserts a field's
    default is then asserting a property of that checkout rather than of the application, and it
    passes or fails according to a file that is deliberately untracked.

    That is not hypothetical. Adding ``INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED=1`` to ``.env`` --
    exactly what starting the Phase D-social clock requires, and the documented way to turn the
    scheduler on -- made ``tests/test_social_history.py``'s lifespan test fail on that machine while
    passing everywhere else. The flag was the instance; ``.env`` reaching test settings at all is
    the defect.

    Detaching ``env_file`` here rather than pinning one more ``INVDASH_*`` in ``settings`` below is
    what closes the class instead of the instance. The ``settings`` fixture can only pin variables
    for Settings objects built through ``get_settings()``; roughly four dozen tests across the suite
    call ``Settings(...)`` directly (``tests/test_stores.py``, ``tests/test_evolution_*.py`` and
    ``tests/test_social_history.py``'s own ``_scheduler_settings``, among others) and no fixture
    touches those at all -- every one of them was reading ``.env``. Mutating the class's own
    ``model_config`` reaches them, because ``pydantic-settings`` resolves ``env_file`` at
    instantiation time, not at class definition.

    What this deliberately does **not** do is scrub ``os.environ``. A real ``INVDASH_*`` exported in
    the shell still wins, because that is a person overriding one run on purpose. The two variables
    the suite must never inherit by either route are pinned explicitly in ``settings`` below.
    """
    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    get_settings.cache_clear()
    try:
        yield
    finally:
        Settings.model_config["env_file"] = original
        get_settings.cache_clear()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """Settings rooted in a temporary directory.

    Redirection goes through the ``INVDASH_*`` environment variables rather than by constructing a
    Settings object and patching it in. That matters because modules bind ``get_settings`` into their
    own namespace at import time, so patching the attribute on one module leaves the others -- the
    lifespan hook in particular -- still writing to the real store. Driving the real configuration
    path means every caller agrees, and it exercises the same override mechanism a user would.
    """
    for name, value in {
        "INVDASH_REPO_ROOT": tmp_path,
        "INVDASH_DATA_DIR": tmp_path / "data",
        "INVDASH_STORE_DIR": tmp_path / "store",
        "INVDASH_CACHE_DIR": tmp_path / "cache",
        # The persona feature writes its markdown vault under `vault_dir`, which defaults to the real
        # repo's `data/vault`. Redirected into `tmp_path` here, like the stores above, so a test that
        # ingests never touches (or reads) the developer's real vault.
        "INVDASH_VAULT_DIR": tmp_path / "vault",
        # The startup refresh sweep makes real HTTP requests to Yahoo, FRED and CNN, and it is
        # started from `lifespan` -- so every test using `with TestClient(app)` would fire it. It is
        # disabled *here*, in the fixture, rather than by shipping a `False` production default:
        # the owner asked for the data to refresh when the server starts, so the deployed default
        # has to be on, and "the test suite must not touch the network" is the test suite's
        # constraint to enforce, not something to pay for in production behaviour.
        "INVDASH_REFRESH_ON_STARTUP": "0",
        # Same reasoning, same hazard, different sweep: the social-snapshot scheduler
        # (`app.market.social_history.start_scheduler`) is a daemon thread making live StockTwits and
        # Reddit calls every few hours, started from `lifespan`, so any test using
        # `with TestClient(app)` would spawn one.
        #
        # Pinned rather than left to the model default for the same reason `REFRESH_ON_STARTUP` is
        # above: `_detach_dotenv` takes `.env` out of the picture, but it deliberately leaves
        # `os.environ` alone, so a developer who exported this variable in their shell to run the
        # real clock would otherwise spawn that daemon thread inside every `with TestClient(app)` in
        # the suite. These two flags are the ones whose cost is live network traffic, so they are
        # pinned against both routes rather than one.
        "INVDASH_SOCIAL_SNAPSHOT_SCHEDULER_ENABLED": "0",
        # Auth defaults ON in production (see `Settings.auth_enabled`), which would 401 every
        # endpoint the several dozen `TestClient(app)`-based test files hit. Those tests exercise the
        # endpoints, not the gate, so auth is disabled here for the whole suite. The auth tests
        # (`tests/test_auth_*.py`) re-enable it explicitly via their own monkeypatch, so turning it
        # off by default here does not weaken them.
        "INVDASH_AUTH_ENABLED": "0",
    }.items():
        monkeypatch.setenv(name, str(value))

    get_settings.cache_clear()
    cfg = get_settings()
    cfg.ensure_dirs()
    yield cfg
    get_settings.cache_clear()


@pytest.fixture
def conn(settings: Settings) -> Iterator[sqlite3.Connection]:
    """A migrated, empty ledger with one account registered."""
    with ledger.connect(settings.ledger_path) as connection:
        ledger.migrate(connection)
        ledger.upsert_account(connection, sample_account())
        yield connection


def sample_account(
    account_id: str = "rh-taxable",
    tax_treatment: TaxTreatment = TaxTreatment.TAXABLE,
) -> Account:
    return Account(
        account_id=account_id,
        broker=Broker.ROBINHOOD,
        label="RH taxable",
        tax_treatment=tax_treatment,
        account_type=AccountType.CASH,
    )


def make_txn(
    *,
    txn_id: str = "t1",
    action: TxnAction = TxnAction.BUY,
    symbol: str | None = "SOXL",
    quantity: str | None = "50",
    price: str | None = "24.10",
    amount: str | None = "-1205.00",
    trade_date: dt.date = dt.date(2026, 3, 2),
    settle_date: dt.date | None = None,
    account_id: str = "rh-taxable",
    source_row: int = 0,
    replay_order: int = 0,
    sequence: int = 0,
    import_id: str = "imp1",
    broker: Broker = Broker.ROBINHOOD,
) -> Transaction:
    """Build a Transaction with sensible defaults, overriding only what a test cares about.

    ``settle_date`` defaults to ``None`` -- the same "broker did not say" case most fixtures want.
    It matters to :mod:`app.core.cash`, which treats a row with no settle date as settled, so tests
    that care about unsettled proceeds must set it explicitly.

    ``replay_order`` defaults to ``0``, same as the model -- most tests only ever supply one
    transaction per (trade_date, account) or do not care which of several ties fetch_transactions
    resolves first, so leaving it unset is the common case. Tests exercising the newest-first
    replay fix set it explicitly; see tests/test_replay_order_integration.py.
    """
    return Transaction(
        txn_id=txn_id,
        import_id=import_id,
        source_row=source_row,
        replay_order=replay_order,
        account_id=account_id,
        broker=broker,
        action=action,
        trade_date=trade_date,
        settle_date=settle_date,
        sequence=sequence,
        symbol=symbol,
        quantity=Decimal(quantity) if quantity is not None else None,
        price=Decimal(price) if price is not None else None,
        amount=Decimal(amount) if amount is not None else None,
    )
