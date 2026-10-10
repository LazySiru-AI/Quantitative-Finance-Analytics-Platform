"""Render a run's fills as a broker export and load it through the application's real ingest path.

The harness could write transactions straight into the ledger. It deliberately does not. The whole
value of running a persona against this application is that the persona's data traverses the same
code a real export traverses -- header detection, the Robinhood adapter, provenance hashing,
idempotent insertion, lot construction, wash-sale adjustment -- so that a defect anywhere along that
chain shows up in the persona's own portfolio numbers rather than in a test fixture. Writing to the
ledger directly would skip the four stages most likely to be wrong.

**Format fidelity.** The CSV written here is shaped to Robinhood's activity-report header, which is
what ``app.ingest.adapters.robinhood`` detects on. Two deliberate departures, both recorded because
a reader comparing this against a real export will notice them:

* **No CUSIPs.** Real Robinhood rows carry ``CUSIP: 037833100`` inside ``Description``. Minting
  plausible-looking CUSIPs for a synthetic run would put fabricated security identifiers into a
  ledger whose entire design premise is that every figure traces back to something real. The adapter
  resolves instruments by symbol when no CUSIP is present -- the path its own ``SLIP``/``CDIV`` rows
  take -- so omitting them costs nothing here and keeps invented identifiers out of the data.
* **Fees as their own rows.** Regulatory fees are emitted as separate ``FEE`` rows rather than
  netted into the sell amount. This is a modelling choice, not a claim about what Robinhood does:
  separate rows keep the trade row's ``Amount`` equal to ``quantity * price`` (so a reconciliation
  failure points at one thing rather than two) and they exercise the ledger's ``FEE`` code path,
  which this data would otherwise never touch.

The sandbox is the point of :func:`sandbox_settings`: the UAT ledger lives under ``uat/sandbox`` and
the real ledger under ``data/store`` is never opened for writing by anything in this package.
"""

from __future__ import annotations

import csv
import datetime as dt
import os
import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from app.config import Settings
from app.core.models import (
    Account,
    AccountType,
    Broker,
    ImportRecord,
    TaxTreatment,
)
from app.db import sqlite
from app.ingest import registry
from app.ingest.provenance import build_import_record, read_rows
from uat.harness.paperbroker import Fill, Mandate

__all__ = [
    "IngestOutcome",
    "ingest_fills",
    "provision_sandbox",
    "sandbox_settings",
    "write_activity_csv",
]

#: Robinhood's activity-report header, in order. Must match
#: ``app.ingest.adapters.robinhood.HEADER_SIGNATURE`` or the registry will refuse the file -- which
#: is the intended failure mode if Robinhood's format ever changes underneath us.
HEADER: Final = (
    "Activity Date",
    "Process Date",
    "Settle Date",
    "Instrument",
    "Description",
    "Trans Code",
    "Quantity",
    "Price",
    "Amount",
)

_DATE_FORMAT: Final = "%m/%d/%Y"


def sandbox_settings(repo_root: Path, name: str = "sandbox") -> Settings:
    """Settings pointing every writable path at ``uat/sandbox`` (or one of its named children).

    Constructed rather than read from the environment so that importing this module can never, by
    any ordering accident, hand a caller a ``Settings`` whose ``ledger_path`` is the user's real
    one. ``data_dir`` is redirected too: nothing in a UAT run has any business reading the real
    broker exports.

    ``name`` defaults to ``"sandbox"``, which resolves to ``uat/sandbox`` exactly as before this
    parameter existed -- runs 1 and 2 stay reproducible against the same path. Any other name
    resolves to ``uat/sandbox/<name>/`` with its own ``data/``, ``store/`` and ``cache/``, so that
    two runs replaying different calendar windows never share a ledger. That isolation is not
    cosmetic: run 3 replays July 2026 against a sandbox that, before this parameter existed, still
    held August trades from runs 1 and 2 in the one shared ledger. A July persona browsing the
    dashboard would have seen August positions -- future data reaching the decision-maker through
    the UI, which is exactly the property :class:`uat.harness.marketdata.AsOfMarket` exists to make
    impossible at the price boundary. Per-name isolation closes the same hole at the ledger/dashboard
    boundary, and as a side effect lets independent runs execute in parallel instead of queueing
    behind one SQLite file.

    ``name`` must be a plain directory-name component -- no path separators, ``.`` or ``..`` -- so a
    caller cannot use it to walk this settings object outside ``uat/sandbox``.
    """
    if name != "sandbox" and (Path(name).name != name or name in ("", ".", "..")):
        raise ValueError(f"invalid sandbox name {name!r}: must be a plain directory name")
    root = repo_root / "uat" / "sandbox"
    sandbox = root if name == "sandbox" else root / name
    return Settings(
        repo_root=repo_root,
        data_dir=sandbox / "data",
        store_dir=sandbox / "store",
        cache_dir=sandbox / "cache",
    )


def provision_sandbox(repo_root: Path, name: str = "sandbox") -> Settings:
    """Create a sandbox's directories and give it read access to the shared daily-bar store.

    Every sandbox needs ``store/bars`` populated to price anything -- ``_universe`` in
    ``uat.harness.run`` and every :class:`uat.harness.marketdata.AsOfMarket` read walk it. Copying
    the full bar store into each of ``run3``/``run4``/``run5`` would triple roughly 19MB of parquet
    (86 symbols across three intervals) for data none of them ever writes to, so this links instead:
    the canonical copy already provisioned at ``uat/sandbox/store/bars`` (the default sandbox, name
    ``"sandbox"``) is shared read-only by every other sandbox via :func:`_link_bars`. The default
    sandbox itself owns a plain directory, since it *is* the canonical copy.

    Nothing under ``store/bars`` is ever written to by this package -- ``app.market.store.read_frame``,
    the only reader ``uat.harness`` uses, never fetches or persists new bars (see
    ``uat.harness.marketdata``) -- so a link is safe to share even though the underlying filesystem
    object is not itself read-only.

    Idempotent: safe to call again for a sandbox that already has directories and a populated (or
    linked) ``bars/``.
    """
    settings = sandbox_settings(repo_root, name=name)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.store_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)

    canonical_bars = sandbox_settings(repo_root).bars_dir
    bars = settings.bars_dir
    if bars == canonical_bars:
        # This *is* the canonical sandbox; it owns its bars outright rather than linking to itself.
        bars.mkdir(parents=True, exist_ok=True)
    elif not bars.exists() and canonical_bars.exists():
        _link_bars(canonical_bars, bars)
    # Else, either bars is already provisioned (idempotent re-`init`) or the canonical sandbox has
    # no bars yet either (a fresh clone before any run has populated it). In the latter case there is
    # nothing to link -- the new sandbox's universe will report empty until it does, which is a
    # clear, visible failure rather than a silent one.

    return settings


def _link_bars(source: Path, target: Path) -> str:
    """Point ``target`` at ``source`` without copying it. Returns which mechanism worked.

    Tries three mechanisms, most preferred first:

    1. A Windows directory junction (``mklink /J``), which needs neither Developer Mode nor an
       elevated shell -- the property that matters here, since sandboxes are provisioned from an
       ordinary ``init`` invocation, not a privileged setup step.
    2. ``os.symlink``, which on Windows requires Developer Mode or an administrator shell (kept as
       a fallback for machines that have one enabled) and is the primary mechanism on other
       platforms.
    3. A full copy, so a sandbox is never left without prices merely because neither link
       mechanism was available on this machine -- correctness of the run over disk footprint.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(target), str(source)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and target.exists():
            return "junction"
    try:
        os.symlink(source, target, target_is_directory=True)
        return "symlink"
    except OSError:
        pass
    shutil.copytree(source, target)
    return "copy"


# ---------------------------------------------------------------------------
# CSV rendering
# ---------------------------------------------------------------------------


def _date(value: dt.date) -> str:
    return value.strftime(_DATE_FORMAT)


def _amount(value: Decimal) -> str:
    """Robinhood's money rendering: ``$1,234.50``, negatives parenthesised as ``($1,234.50)``."""
    magnitude = f"${abs(value):,.2f}"
    return f"({magnitude})" if value < 0 else magnitude


def _price(value: Decimal) -> str:
    return f"${value:,.2f}"


def _settle(trade_date: dt.date, days: int = 1) -> dt.date:
    current = trade_date
    remaining = days
    while remaining > 0:
        current += dt.timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def write_activity_csv(
    path: Path,
    *,
    fills: Sequence[Fill],
    mandate: Mandate,
    funded_on: dt.date | None = None,
) -> Path:
    """Write fills as a Robinhood-shaped activity report.

    Rows are emitted newest-first, which is the order Robinhood exports in. The adapter assigns
    ``sequence`` from file position to break same-day ties, so the order is not cosmetic -- it is
    what the lot engine will replay against if two same-day trades touch one symbol.

    ``funded_on`` adds the opening deposit row and belongs only on the first export of a run.

    **One file per session, not one growing file.** The run ingests after every session so the
    persona can see its own book in the dashboard the next morning, and a single file that gained
    rows each session would change content hash -- and therefore ``import_id`` -- every time. The
    transactions already in the ledger would then differ from the re-parsed ones by exactly that
    field, and ``insert_transactions`` would correctly report every one of them as a *conflict*
    rather than a duplicate. Per-session files each import once and never contend.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, str]] = []

    for fill in fills:
        rows.append(
            {
                "Activity Date": _date(fill.trade_date),
                "Process Date": _date(fill.trade_date),
                "Settle Date": _date(_settle(fill.trade_date, mandate.settlement_days)),
                "Instrument": fill.symbol,
                "Description": f"{fill.symbol} paper fill, UAT persona {mandate.persona_id}",
                "Trans Code": "Buy" if fill.side == "buy" else "Sell",
                "Quantity": format(fill.quantity, "f"),
                "Price": _price(fill.price),
                "Amount": _amount(-fill.gross if fill.side == "buy" else fill.gross),
            }
        )
        if fill.fees > 0:
            rows.append(
                {
                    "Activity Date": _date(fill.trade_date),
                    "Process Date": _date(fill.trade_date),
                    "Settle Date": _date(_settle(fill.trade_date, mandate.settlement_days)),
                    "Instrument": "",
                    "Description": f"Regulatory fees on {fill.symbol} sale ({fill.order_id})",
                    "Trans Code": "FEE",
                    "Quantity": "",
                    "Price": "",
                    "Amount": _amount(-fill.fees),
                }
            )

    if funded_on is not None:
        rows.append(
            {
                "Activity Date": _date(funded_on),
                "Process Date": _date(funded_on),
                "Settle Date": _date(funded_on),
                "Instrument": "",
                "Description": f"UAT opening deposit for persona {mandate.persona_id}",
                "Trans Code": "ACH",
                "Quantity": "",
                "Price": "",
                "Amount": _amount(mandate.starting_cash),
            }
        )

    rows.sort(key=lambda row: dt.datetime.strptime(row["Activity Date"], _DATE_FORMAT), reverse=True)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(HEADER))
        writer.writeheader()
        writer.writerows(rows)

    return path


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """What the load did, in the terms the ledger reports them."""

    import_id: str
    adapter: str
    row_count: int
    usable_row_count: int
    inserted: int
    duplicates: int
    conflicts: list[str]
    instruments: int
    skipped: dict[str, int]
    fingerprint: str
    txn_count: int

    @property
    def is_clean(self) -> bool:
        return not self.conflicts

    def to_json(self) -> dict[str, Any]:
        return {
            "import_id": self.import_id,
            "adapter": self.adapter,
            "row_count": self.row_count,
            "usable_row_count": self.usable_row_count,
            "inserted": self.inserted,
            "duplicates": self.duplicates,
            "conflicts": self.conflicts,
            "instruments": self.instruments,
            "skipped": self.skipped,
            "ledger_fingerprint": self.fingerprint,
            "ledger_txn_count": self.txn_count,
        }


def ingest_fills(
    csv_path: Path,
    *,
    mandate: Mandate,
    settings: Settings,
    imported_at: dt.datetime | None = None,
) -> IngestOutcome:
    """Load a rendered activity CSV into the sandbox ledger through the real pipeline.

    Re-running this on the same file is safe and is worth doing at least once per run: the ledger's
    idempotency guarantee (``app.db.sqlite.insert_transactions``) is one of the properties a UAT run
    should actually confirm rather than assume, and a second call that reports anything other than
    all-duplicates is a genuine finding.
    """
    when = imported_at or dt.datetime.now(dt.UTC)

    registry.load_builtin_adapters()
    raw = read_rows(csv_path, settings=settings)
    adapter = registry.resolve(raw)

    account = Account(
        account_id=mandate.account_id,
        broker=Broker.ROBINHOOD,
        label=mandate.account_label,
        tax_treatment=TaxTreatment.TAXABLE,
        account_type=AccountType.CASH,
    )

    # `build_import_record` derives `import_id` from the content hash, the account and `imported_at`
    # -- none of which depend on parsing -- but it also wants `usable_row_count`, which does. Rather
    # than reimplement the id derivation here, it is called twice with the same `imported_at`, so
    # both calls produce the same id and only the row count differs. Deterministic, and it keeps the
    # id formula in one place.
    provisional = build_import_record(
        raw,
        broker=Broker.ROBINHOOD,
        account_id=mandate.account_id,
        adapter=adapter.name,
        adapter_version=adapter.version,
        usable_row_count=0,
        imported_at=when,
    )
    result = adapter.parse(raw, account=account, import_id=provisional.import_id)
    record: ImportRecord = build_import_record(
        raw,
        broker=Broker.ROBINHOOD,
        account_id=mandate.account_id,
        adapter=adapter.name,
        adapter_version=adapter.version,
        usable_row_count=result.usable_row_count,
        imported_at=when,
    )
    assert record.import_id == provisional.import_id, (
        "import id is not stable across two calls with the same imported_at; "
        "build_import_record's derivation changed and this function needs revisiting"
    )

    settings.ensure_dirs()
    with sqlite.connect(settings.ledger_path) as conn:
        sqlite.migrate(conn)
        sqlite.upsert_account(conn, account)
        # The import row is a foreign key target for every transaction, so it is written first --
        # the same ordering `tests/test_e2e.py` relies on.
        try:
            sqlite.record_import(conn, record)
        except Exception:
            # A re-ingest of an identical file at the same `imported_at` collides on the primary
            # key. That is the idempotent case, not an error: the transactions below will report as
            # duplicates and the ledger is unchanged.
            conn.rollback()
        for instrument in result.instruments.values():
            sqlite.upsert_instrument(conn, instrument)
        report = sqlite.insert_transactions(conn, result.transactions)
        fingerprint, txn_count = sqlite.ledger_fingerprint(conn)

    return IngestOutcome(
        import_id=record.import_id,
        adapter=adapter.name,
        row_count=raw.row_count,
        usable_row_count=result.usable_row_count,
        inserted=report.inserted,
        duplicates=report.duplicates,
        conflicts=[str(c) for c in report.conflicts],
        instruments=len(result.instruments),
        skipped=result.skip_counts(),
        fingerprint=fingerprint,
        txn_count=txn_count,
    )
