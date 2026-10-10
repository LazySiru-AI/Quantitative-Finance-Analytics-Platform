"""An in-process failed-login limiter.

Keyed by both username and client IP: five failures against either key within a fifteen-minute
window locks *that key* for fifteen minutes. Two keys rather than one so that neither a single
mistyped account nor a single noisy IP can be brute-forced, while a legitimate user on a shared
egress IP is not locked out by someone else's failures against a different account.

**In-memory, single-process, best-effort.** State lives in a module-level dict and is lost on
restart. That is the right weight for one uvicorn process serving ten known users: it costs nothing,
needs no store, and a restart clearing the counters is not an exposure worth a database for. It is
*not* a defense for a horizontally scaled or multi-worker deployment -- there is exactly one worker
here (see ``backend/Dockerfile``'s ``uvicorn`` command, no ``--workers``). A successful login clears
that user's counter; the IP counter ages out on its own.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

#: Failures allowed within the window before a key locks.
MAX_FAILURES = 5
#: Sliding window / lockout duration, in seconds.
WINDOW_SECONDS = 15 * 60


@dataclass
class _Bucket:
    failures: list[float] = field(default_factory=list)


class LoginThrottle:
    """Tracks failed logins per key. Thread-safe; one instance is shared process-wide below."""

    def __init__(self, *, max_failures: int = MAX_FAILURES, window_seconds: int = WINDOW_SECONDS):
        self._max = max_failures
        self._window = window_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def _prune(self, bucket: _Bucket, now: float) -> None:
        cutoff = now - self._window
        bucket.failures = [t for t in bucket.failures if t > cutoff]

    def retry_after(self, keys: list[str], *, now: float | None = None) -> int:
        """Seconds until the *most* locked of ``keys`` frees up, or 0 if none is locked."""
        now = time.monotonic() if now is None else now
        worst = 0
        with self._lock:
            for key in keys:
                bucket = self._buckets.get(key)
                if bucket is None:
                    continue
                self._prune(bucket, now)
                if len(bucket.failures) >= self._max:
                    oldest = min(bucket.failures)
                    worst = max(worst, int(oldest + self._window - now) + 1)
        return worst

    def is_locked(self, keys: list[str], *, now: float | None = None) -> bool:
        return self.retry_after(keys, now=now) > 0

    def record_failure(self, keys: list[str], *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            for key in keys:
                bucket = self._buckets.setdefault(key, _Bucket())
                self._prune(bucket, now)
                bucket.failures.append(now)

    def clear(self, keys: list[str]) -> None:
        """Reset the given keys -- called for the username on a successful login."""
        with self._lock:
            for key in keys:
                self._buckets.pop(key, None)

    def reset(self) -> None:
        """Drop all state. For tests."""
        with self._lock:
            self._buckets.clear()


#: The process-wide throttle the login route uses.
THROTTLE = LoginThrottle()
