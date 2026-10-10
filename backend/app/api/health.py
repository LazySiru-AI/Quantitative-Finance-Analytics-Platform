"""Health and store-status endpoints.

``/api/health/stores`` reports what actually exists on disk rather than just returning ``{"ok": true}``.
On a system whose entire output depends on ingested data, "the server is up" is not the useful signal;
"the ledger has 1,000 transactions across 8 accounts and the derivation is current" is.

``/api/health/providers`` applies the same reasoning to the upstreams. The registry walks a
two-provider chain for bars and one of them has been unable to answer since Phase 4, so in practice
every price in this application comes from a single source. That is a fact worth knowing before an
outage, not one to infer from an error message during one.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.config import get_settings
from app.datasource import ledger_db_path
from app.db import duck, sqlite
from app.market.registry import default_registry

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
def health() -> dict[str, str]:
    """Liveness. Deliberately does no I/O."""
    return {"status": "ok"}


@router.get("/providers")
def providers() -> dict[str, Any]:
    """Which upstreams are registered, and how many of them can actually serve.

    Reports known status; it does not probe. A probe would add a network round trip per provider to
    an endpoint meant to be cheap, and would describe only this instant — while the useful fact here
    is structural and does not change between requests. Live failures are already reported by name
    on the request that hits them, because an exhausted walk raises with what every provider said.
    """
    registry = default_registry()
    statuses = registry.describe()
    bars = [s for s in statuses if s.role == "bars"]
    usable_bars = [s for s in bars if s.usable]

    return {
        "providers": [
            {
                "name": status.name,
                "role": status.role,
                "intervals": list(status.intervals),
                "usable": status.usable,
                "degraded_reason": status.degraded_reason,
            }
            for status in statuses
        ],
        "bars": {
            "registered": len(bars),
            "usable": len(usable_bars),
            # Named rather than left to be counted: "1 of 2" is the shape of a fallback chain that
            # has no fallback, and it should read as a finding rather than as a statistic.
            "single_point_of_failure": (
                usable_bars[0].name if len(usable_bars) == 1 else None
            ),
        },
    }


@router.get("/stores")
def stores() -> dict[str, Any]:
    """Report what is actually in each store.

    **There is no derived-state block, deliberately.** This used to report a ``derived`` status --
    ``never_built``, ``current`` or ``stale`` -- read from a ``derived_build`` table that recorded
    rebuilds of materialised lots, positions and gains. Those tables were never built: every derived
    figure here is recomputed from the ledger per request, which is why a stale one is not a state
    this application can be in. The status was therefore ``never_built`` forever, and the Portfolio
    page rendered it as a badge beside figures that were correct and current. See
    ``app.db.sqlite._migrate_drop_derived_build``.
    """
    settings = get_settings()
    ledger_file = ledger_db_path(settings)
    report: dict[str, Any] = {
        "source": settings.data_source,
        "ledger": {"path": str(ledger_file), "exists": ledger_file.exists()},
        "bars": {"path": str(settings.bars_dir), "exists": settings.bars_dir.exists()},
    }

    if ledger_file.exists():
        with sqlite.connect(ledger_file, read_only=True) as conn:
            _fingerprint, txn_count = sqlite.ledger_fingerprint(conn)
            counts = {
                name: int(conn.execute(f"SELECT COUNT(*) AS n FROM {name}").fetchone()["n"])
                for name in ("account", "instrument", "raw_import", "txn")
            }

        report["ledger"].update(counts)
        report["ledger"]["transactions"] = txn_count

    if settings.bars_dir.exists():
        report["bars"]["symbols"] = {
            interval.value: len(duck.stored_symbols(settings.bars_dir, interval))
            for interval in duck.Interval
        }

    return report
