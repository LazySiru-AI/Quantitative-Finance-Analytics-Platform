"""Adapter registry: loading, detection and mutual exclusivity."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.models import Broker
from app.ingest import registry
from app.ingest.adapters.base import ExportOrder
from app.ingest.provenance import read_rows


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    """Each test starts from an empty registry and loads what it needs."""
    registry.clear()


class TestLoading:
    def test_loads_three_adapters(self) -> None:
        adapters = registry.load_builtin_adapters()
        assert {a.name for a in adapters} == {"robinhood", "webull", "sofi"}

    def test_every_adapter_declares_its_export_order(self) -> None:
        """`export_order` is required on `BrokerAdapter` with no default, precisely because the
        system's old behaviour was to assume oldest-first without ever being told -- which was
        wrong for all three of these. Loop-based so a fourth adapter cannot ship without declaring
        it either."""
        for adapter in registry.load_builtin_adapters():
            assert isinstance(adapter.export_order, ExportOrder)

    def test_loading_twice_is_idempotent(self) -> None:
        """Startup and an individual test must both be able to call this without coordinating."""
        first = registry.load_builtin_adapters()
        second = registry.load_builtin_adapters()
        assert len(first) == len(second) == 3

    def test_loading_concurrently_is_idempotent(self) -> None:
        """The sequential test above passed throughout, and the function still raced.

        `load_builtin_adapters` reads `_REGISTRY` to decide what is missing and then mutates it.
        FastAPI runs sync endpoints in a thread pool, so once `GET /api/import` began calling this
        on the request path, two concurrent previews could both see `robinhood` as absent and both
        register it — and the loser returned a bare 500. A UAT persona hit it on the first load of
        the Activity page and reported it as transient, self-resolving on reload, which is what a
        race looks like from the outside.

        Reproduced here with a barrier so every thread reaches the check before any of them acts,
        which is the interleaving that fails. Without the lock this raises
        `ValueError: adapter 'robinhood' is already registered` essentially every run.
        """
        import threading

        registry.clear()
        threads = 8
        barrier = threading.Barrier(threads)
        errors: list[BaseException] = []

        def load() -> None:
            try:
                barrier.wait(timeout=5)
                registry.load_builtin_adapters()
            except BaseException as exc:
                # Deliberately broad: the assertion is that nothing at all escapes, and an
                # exception swallowed by a narrower clause would make this test pass for the wrong
                # reason. A thread's exception is otherwise printed and lost.
                errors.append(exc)

        workers = [threading.Thread(target=load) for _ in range(threads)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)

        assert errors == [], f"concurrent load raised: {errors!r}"
        assert {a.name for a in registry.available_adapters()} == {"robinhood", "webull", "sofi"}

    def test_duplicate_registration_is_rejected(self) -> None:
        registry.load_builtin_adapters()
        existing = registry.available_adapters()[0]
        with pytest.raises(ValueError, match="already registered"):
            registry.register(existing)

    def test_every_adapter_declares_a_version(self) -> None:
        """Version is stored on the import record, so a ledger row traces to the parsing logic."""
        for adapter in registry.load_builtin_adapters():
            assert adapter.version
            assert adapter.broker in set(Broker)


class TestDetection:
    """Header signatures must be mutually exclusive: ambiguity is a bug, not a tie to break."""

    def test_unknown_header_raises_with_a_useful_message(self, tmp_path: Path) -> None:
        registry.load_builtin_adapters()
        path = tmp_path / "mystery.csv"
        path.write_text("Alpha,Beta,Gamma\n1,2,3\n", encoding="utf-8")
        with pytest.raises(registry.AdapterNotFound, match="no adapter matches"):
            registry.resolve(read_rows(path))

    def test_empty_registry_finds_nothing(self, tmp_path: Path) -> None:
        path = tmp_path / "x.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        with pytest.raises(registry.AdapterNotFound):
            registry.resolve(read_rows(path))
