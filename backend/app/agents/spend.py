"""Process-wide aggregate spend ledger for the translate and persona model-spending HTTP routes.

**Why this exists.** Every model-spending HTTP route already enforces its own per-call
`app.agents.models.AgentBudget` -- a fresh one minted per request (`app.i18n.narrative.translate_texts`)
or per job (`app.personas.service`'s `ask`/`critique`/`consolidate`/`strategy_card`/`start_ingest`).
That bounds what *one* call or job can spend, but nothing bounds how many times an authenticated user
can call one of those routes -- so an authenticated user could spend without bound simply by calling
repeatedly. This module adds a second, aggregate ceiling on top of the per-call ones: a rolling
24-hour total across every call `app.agents.client` records, checked *before* a translate or persona
call is made. See `app.config.Settings.model_spend_daily_cap_usd` for the cap itself.

**In-memory, single-process, best-effort -- the same weight as `app.auth.throttle.LoginThrottle`
(read that module's docstring; this one mirrors it).** State lives in a module-level list of
`(timestamp, cost)` entries and is lost on restart. That is the right weight for one uvicorn process
serving a handful of known users: it costs nothing, needs no store, and a restart clearing the running
total is not an exposure worth a database for. It is *not* a defense for a horizontally scaled or
multi-worker deployment -- there is exactly one worker here (see `backend/Dockerfile`'s `uvicorn`
command, no `--workers`).

**What counts toward the total, versus what is actually gated.** `app.agents.client.call_structured` is
the single choke point for every Anthropic call in this codebase, and it records every call's actual
cost here unconditionally (see its own docstring) -- so in practice the evolution loop's and
agent-desk's calls (roles `designer`/`scout`/`reviewer`, the `app.tradingagents` analyst/researcher/
trader roles, `swarm_worker`) add to this running total too, since they share that same call path with
`translator` and the persona features (also `swarm_worker`). What *is* scoped to translate + personas
is enforcement: only `app.i18n.narrative.translate_texts` and the persona routes named above call
`check()` against the cap before spending. The evolution loop and agent-desk runs never call `check()`
-- they are owner-launched, long-running jobs with their own single-slot registries and their own
per-run `AgentBudget` caps, and this module is not a second ceiling on top of those.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from decimal import Decimal

__all__ = ["LEDGER", "WINDOW_SECONDS", "SpendCapExceeded", "SpendLedger"]

#: Rolling window the aggregate cap is measured over, in seconds.
WINDOW_SECONDS = 24 * 60 * 60


class SpendCapExceeded(Exception):
    """Raised by `SpendLedger.check` when the rolling-window total is already at or past the cap.

    Carries everything the HTTP layer needs to answer without re-deriving it: the spend and cap that
    were compared (`spent_usd`, `cap_usd`) and an estimate of how long until the oldest entry in the
    window ages out and the total drops (`retry_after_seconds`) -- an estimate, not a guarantee, since
    spend recorded after this is raised can push that moment back out.
    """

    def __init__(self, spent_usd: Decimal, cap_usd: Decimal, *, retry_after_seconds: int) -> None:
        super().__init__(
            f"model spend cap exceeded: spent {spent_usd} of {cap_usd} in the trailing 24h"
        )
        self.spent_usd = spent_usd
        self.cap_usd = cap_usd
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class _Entry:
    at: float
    cost_usd: Decimal


class SpendLedger:
    """Tracks model spend in a rolling window (24h by default). Thread-safe; one instance is shared
    process-wide below (`LEDGER`)."""

    def __init__(self, *, window_seconds: int = WINDOW_SECONDS) -> None:
        self._window = window_seconds
        self._entries: list[_Entry] = []
        self._lock = threading.Lock()

    def _prune_locked(self, now: float) -> None:
        """Drop entries older than the window. Caller must hold `self._lock`."""
        cutoff = now - self._window
        self._entries = [e for e in self._entries if e.at > cutoff]

    def _retry_after_seconds_locked(self, now: float) -> int:
        """Caller must hold `self._lock`."""
        if not self._entries:
            return 0
        oldest = min(e.at for e in self._entries)
        return max(0, int(oldest + self._window - now) + 1)

    def record(self, cost_usd: Decimal, *, now: float | None = None) -> None:
        """Record one call's actual cost. Called unconditionally from `app.agents.client` for every
        model call the SDK or CLI transport completes -- see the module docstring for what that does
        and does not mean for enforcement."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune_locked(now)
            self._entries.append(_Entry(at=now, cost_usd=cost_usd))

    def spent_last_24h(self, *, now: float | None = None) -> Decimal:
        """Total cost recorded in the trailing window as of `now`."""
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune_locked(now)
            return sum((e.cost_usd for e in self._entries), Decimal(0))

    def check(self, cap_usd: Decimal, *, now: float | None = None) -> None:
        """Raise `SpendCapExceeded` if the rolling-window total is already at or past `cap_usd`.

        `cap_usd <= 0` means unlimited and this never raises. Call this *before* making the model
        call it is meant to gate, not after -- it looks only at spend already recorded, never at the
        cost of the call about to happen (which is not known yet)."""
        if cap_usd <= 0:
            return
        now = time.monotonic() if now is None else now
        with self._lock:
            self._prune_locked(now)
            spent = sum((e.cost_usd for e in self._entries), Decimal(0))
            if spent >= cap_usd:
                raise SpendCapExceeded(
                    spent, cap_usd, retry_after_seconds=self._retry_after_seconds_locked(now)
                )

    def reset(self) -> None:
        """Drop all state. For tests."""
        with self._lock:
            self._entries.clear()


#: The process-wide ledger every model-spending route checks against and every model call records into.
LEDGER = SpendLedger()
