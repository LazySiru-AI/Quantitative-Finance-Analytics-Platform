"""Adapter registry: pick the right parser for a file by looking at its header.

Detection is by header signature, never by filename. The user renames exports freely --
``Account A.csv`` and ``Account B.csv`` tell a parser nothing -- and a filename-based guess
that lands on the wrong adapter produces silently wrong numbers rather than an error.

Ambiguity is fatal. If two adapters claim a file, that is a bug in one of their ``matches``
implementations and must be fixed rather than resolved by declaration order.
"""

from __future__ import annotations

import threading

from app.ingest.adapters.base import BrokerAdapter
from app.ingest.provenance import RawFile

__all__ = [
    "AdapterNotFound",
    "AmbiguousAdapter",
    "available_adapters",
    "clear",
    "load_builtin_adapters",
    "register",
    "resolve",
]

_REGISTRY: list[BrokerAdapter] = []

#: Guards the read-then-mutate in :func:`load_builtin_adapters`. Module-level and non-reentrant:
#: nothing it protects calls back into it.
_REGISTRY_LOCK = threading.Lock()

#: Adapters shipped with the application, as ``module: attribute`` pairs. Imported lazily by
#: :func:`load_builtin_adapters` rather than at package import, so importing
#: :mod:`app.ingest.adapters` never has the side effect of mutating global state.
_BUILTIN: tuple[tuple[str, str], ...] = (
    ("app.ingest.adapters.robinhood", "ADAPTER"),
    ("app.ingest.adapters.webull", "ADAPTER"),
    ("app.ingest.adapters.sofi", "ADAPTER"),
)


class AdapterNotFound(LookupError):
    """No registered adapter recognised the file's header."""

    def __init__(self, raw: RawFile) -> None:
        super().__init__(
            f"no adapter matches {raw.path.name!r}\n"
            f"  header: {list(raw.header)}\n"
            f"  registered: {[a.name for a in _REGISTRY] or 'none'}\n"
            "Add an adapter, or use the generic adapter with an explicit column mapping."
        )
        self.raw = raw


class AmbiguousAdapter(LookupError):
    """More than one adapter claimed the file."""

    def __init__(self, raw: RawFile, matches: list[BrokerAdapter]) -> None:
        super().__init__(
            f"{len(matches)} adapters match {raw.path.name!r}: {[a.name for a in matches]}. "
            "Header signatures must be mutually exclusive; tighten one of the matches() rules."
        )
        self.raw = raw
        self.matches = matches


def register(adapter: BrokerAdapter) -> BrokerAdapter:
    """Register an adapter. Usable as a decorator on the class instantiation site."""
    if any(existing.name == adapter.name for existing in _REGISTRY):
        raise ValueError(f"adapter {adapter.name!r} is already registered")
    _REGISTRY.append(adapter)
    return adapter


def available_adapters() -> tuple[BrokerAdapter, ...]:
    return tuple(_REGISTRY)


def clear() -> None:
    """Empty the registry. For tests that need to assert detection in isolation."""
    _REGISTRY.clear()


def load_builtin_adapters() -> tuple[BrokerAdapter, ...]:
    """Register the adapters shipped with the application.

    Idempotent, **including under concurrency**: calling it twice is a no-op rather than a
    duplicate-name error, so application startup, an individual test and two simultaneous requests
    can all call it without coordinating.

    The lock is not defensive programming. This function reads ``_REGISTRY`` to decide what is
    missing and then mutates it — a check-then-act on process-global state — and FastAPI runs sync
    endpoints in a **thread pool**. Once ``GET /api/import`` started calling this on the request
    path, two concurrent previews could both observe ``robinhood`` as absent and both call
    :func:`register`, and the loser got ``ValueError: adapter 'robinhood' is already registered``
    rendered to the user as a bare 500. Found by a UAT persona on the first load of the Activity
    page, reported as transient and self-resolving on reload, which is the signature of exactly this
    race — React's development double-invoke is enough to fire the two requests.

    ``app.rules.service`` had already recorded this hazard in the abstract as its reason to refuse
    global mutable state; this is the same hazard, arrived at from the other direction.
    """
    from importlib import import_module

    with _REGISTRY_LOCK:
        registered = {adapter.name for adapter in _REGISTRY}
        for module_path, attribute in _BUILTIN:
            adapter: BrokerAdapter = getattr(import_module(module_path), attribute)
            if adapter.name not in registered:
                register(adapter)
                registered.add(adapter.name)
        return tuple(_REGISTRY)


def resolve(raw: RawFile) -> BrokerAdapter:
    """Find the single adapter that handles this file.

    Raises:
        AdapterNotFound: Nothing matched.
        AmbiguousAdapter: More than one matched.
    """
    matches = [adapter for adapter in _REGISTRY if adapter.matches(raw)]
    if not matches:
        raise AdapterNotFound(raw)
    if len(matches) > 1:
        raise AmbiguousAdapter(raw, matches)
    return matches[0]


