"""The thesis-loop endpoints: `POST /run`, `GET /ledger`, `GET /holdout`, `GET /catalogue`.

Tested against fakes injected through `app.api.thesis`'s own `_default_*()` seams, not through a real
run of `app.thesis.loop` -- the point of this file is the *translation* from a `LoopResult` to an HTTP
response (status codes, which shape survives the wire, what a burned holdout looks like to a caller),
not the loop's internal statistics, which `tests/test_thesis_loop.py` already covers end to end. The
one exception is `GET /ledger`, `GET /holdout` and `GET /catalogue`, which are thin enough over the
real `app.thesis.ledger` / `app.thesis.holdout` / `app.thesis.author` modules that exercising the real
thing (against the temporary store the `settings` fixture provides) is both simpler and more honest
than faking it.
"""

from __future__ import annotations

import contextlib
import datetime as dt

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.api import thesis as thesis_api
from app.config import Settings
from app.db.duck import Interval
from app.main import app
from app.market.models import MarketWarning
from app.market.providers.base import ProviderUnavailable, SymbolNotFound
from app.thesis import author, holdout, ledger, preregister
from app.thesis.models import (
    Direction,
    Evidence,
    HoldoutState,
    HoldoutStatus,
    LedgerStats,
    LoopOutcome,
    LoopResult,
    StrategyCard,
    Thesis,
    ThesisRecord,
    ThesisStatus,
    Verdict,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# Fakes -- injected through app.api.thesis's own Protocol seams
# ---------------------------------------------------------------------------


def _flat_bars(n: int = 1200) -> pd.DataFrame:
    """Enough sessions to clear `holdout.MIN_HOLDOUT_BARS` at the fixed 0.25 split fraction --
    1200 * 0.25 = 300, comfortably over the 250 floor."""
    return pd.DataFrame(
        {
            "ts": pd.date_range("2015-01-01", periods=n, freq="D", tz="UTC"),
            "open": np.full(n, 100.0),
            "high": np.full(n, 101.0),
            "low": np.full(n, 99.0),
            "close": np.full(n, 100.0),
            "adj_close": np.full(n, 100.0),
            "volume": np.full(n, 1e6),
        }
    )


def _thesis(symbol: str = "TEST") -> Thesis:
    return Thesis(
        symbol=symbol,
        hypothesis="A close below the lower band precedes higher-than-baseline returns.",
        entry="close < bb_lower(20,2)",
        horizon=20,
        direction=Direction.UP,
        falsifies_if="the hit rate does not exceed the unconditional rate",
    )


def _record(
    hash_: str,
    *,
    verdict: Verdict | None = None,
    status: ThesisStatus = ThesisStatus.REGISTERED,
    holdout: Evidence | None = None,
) -> ThesisRecord:
    """``holdout`` defaults to ``None``, which is correct for every status except
    ``HOLDOUT_TESTED`` with ``verdict=Verdict.SURVIVED`` -- `LoopResult`'s validator now refuses to
    construct a run whose survivor was never holdout-tested (see `app/thesis/models.py`), so a caller
    building a *genuine* survivor fixture must pass evidence here, not leave the field to default."""
    return ThesisRecord(
        thesis_hash=hash_,
        thesis=_thesis(),
        registered_at=dt.datetime.now(dt.UTC),
        status=status,
        verdict=verdict,
        holdout=holdout,
    )


def _loop_result(
    *,
    symbol: str = "TEST",
    outcome: LoopOutcome = LoopOutcome.BUDGET_EXHAUSTED,
    records: list[ThesisRecord] | None = None,
    ledger_stats: LedgerStats | None = None,
    holdout_state: HoldoutState | None = None,
    warnings: list[MarketWarning] | None = None,
    budget: int = 12,
) -> LoopResult:
    recs = records if records is not None else []
    return LoopResult(
        symbol=symbol,
        interval=Interval.DAY,
        started_at=dt.datetime.now(dt.UTC),
        finished_at=dt.datetime.now(dt.UTC),
        outcome=outcome,
        budget=budget,
        iterations_used=len(recs),
        records=recs,
        cards=[],
        ledger=ledger_stats,
        holdout=holdout_state,
        warnings=warnings or [],
    )


class _FakeLoopRunner:
    """Hands back a fixed `LoopResult`, or raises a fixed exception -- the router must not care
    which collaborator produced either, only translate what it gets."""

    def __init__(self, outcome: LoopResult | Exception) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        symbol: str,
        *,
        interval: Interval = Interval.DAY,
        budget: int = 12,
        settings: Settings | None = None,
        registry: object | None = None,
    ) -> LoopResult:
        self.calls.append({"symbol": symbol, "interval": interval, "budget": budget})
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _install_runner(monkeypatch: pytest.MonkeyPatch, outcome: LoopResult | Exception) -> _FakeLoopRunner:
    fake = _FakeLoopRunner(outcome)
    monkeypatch.setattr(thesis_api, "_default_loop_runner", lambda: fake)
    return fake


def _evidence(**overrides: object) -> Evidence:
    base: dict[str, object] = {
        "horizon": 20,
        "hit_rate": 0.6,
        "baseline_hit_rate": 0.5,
        "sample_size": 50,
        "independent_sample_size": 40,
        "p_value": 0.01,
    }
    base.update(overrides)
    return Evidence(**base)  # type: ignore[arg-type]


def _card(thesis_hash: str, *, verdict: Verdict = Verdict.SURVIVED) -> StrategyCard:
    return StrategyCard(
        symbol="TEST",
        interval=Interval.DAY,
        generated_at=dt.datetime.now(dt.UTC),
        thesis=_thesis(),
        thesis_hash=thesis_hash,
        verdict=verdict,
        entry_rule="close < bb_lower(20,2)",
    )


class _FakeCardBuilder:
    """Hands back a fixed `StrategyCard`, or raises a fixed exception -- the router must translate
    either without caring which collaborator produced it, exactly the discipline `_FakeLoopRunner`
    exists to enforce for `LoopRunner`."""

    def __init__(self, outcome: StrategyCard | Exception) -> None:
        self._outcome = outcome
        self.calls: list[dict[str, object]] = []

    def build_for_survivor(
        self,
        symbol: str,
        interval: Interval,
        survivor: ThesisRecord,
        *,
        ledger_stats: LedgerStats | None = None,
        holdout_state: HoldoutState | None = None,
        settings: Settings | None = None,
        registry: object | None = None,
    ) -> StrategyCard:
        self.calls.append(
            {"symbol": symbol, "interval": interval, "survivor": survivor.thesis_hash}
        )
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def _install_card_builder(
    monkeypatch: pytest.MonkeyPatch, outcome: StrategyCard | Exception
) -> _FakeCardBuilder:
    fake = _FakeCardBuilder(outcome)
    monkeypatch.setattr(thesis_api, "_default_card_builder", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# POST /run -- shape and success paths
# ---------------------------------------------------------------------------


class TestRunEndpointShape:
    def test_a_normal_run_returns_the_full_loop_result(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = [_record("h1", verdict=Verdict.REJECTED, status=ThesisStatus.IN_SAMPLE_TESTED)]
        stats = LedgerStats(symbol="TEST", total_trials=1, rejected=1)
        result = _loop_result(outcome=LoopOutcome.BUDGET_EXHAUSTED, records=records, ledger_stats=stats)
        _install_runner(monkeypatch, result)

        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "budget_exhausted"
        assert body["symbol"] == "TEST"

    def test_records_and_ledger_are_always_on_the_wire(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The response must never hide the trial count -- `records` and `ledger` travel with every
        outcome, and `iterations_used` must equal the number of records this run produced."""
        records = [_record("h1"), _record("h2"), _record("h3")]
        stats = LedgerStats(symbol="TEST", total_trials=3)
        result = _loop_result(records=records, ledger_stats=stats)
        _install_runner(monkeypatch, result)

        response = client.post("/api/thesis/run", json={"symbol": "TEST", "budget": 5})
        assert response.status_code == 200
        body = response.json()
        assert "records" in body
        assert "ledger" in body
        assert len(body["records"]) == 3
        assert body["iterations_used"] == len(body["records"])
        assert body["ledger"]["total_trials"] == 3

    def test_budget_exhausted_is_a_normal_200_not_an_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`budget_exhausted` is a reportable outcome, not an error state."""
        _install_runner(monkeypatch, _loop_result(outcome=LoopOutcome.BUDGET_EXHAUSTED))
        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 200
        assert response.json()["outcome"] == "budget_exhausted"

    def test_no_data_is_a_normal_200(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_runner(monkeypatch, _loop_result(outcome=LoopOutcome.NO_DATA))
        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 200
        assert response.json()["outcome"] == "no_data"

    def test_survivor_found_is_a_normal_200(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        records = [
            _record(
                "h1",
                verdict=Verdict.SURVIVED,
                status=ThesisStatus.HOLDOUT_TESTED,
                holdout=_evidence(),
            )
        ]
        holdout_state = HoldoutState(
            symbol="TEST", split_date=dt.date(2024, 1, 1), status=HoldoutStatus.SPENT, attempts=1
        )
        result = _loop_result(
            outcome=LoopOutcome.SURVIVOR_FOUND, records=records, holdout_state=holdout_state
        )
        _install_runner(monkeypatch, result)
        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 200
        assert response.json()["outcome"] == "survivor_found"

    def test_the_runner_receives_the_requested_budget_and_symbol(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake = _install_runner(monkeypatch, _loop_result(symbol="ABC"))
        response = client.post("/api/thesis/run", json={"symbol": "abc", "budget": 7})
        assert response.status_code == 200
        assert fake.calls == [{"symbol": "ABC", "interval": Interval.DAY, "budget": 7}]


# ---------------------------------------------------------------------------
# POST /run -- catalogue_exhausted, the outcome that was missing from the frontend union
# ---------------------------------------------------------------------------


class TestCatalogueExhaustedOutcome:
    def test_catalogue_exhausted_is_a_normal_200_and_round_trips(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`CATALOGUE_EXHAUSTED` is a real `LoopOutcome` member (`app/thesis/models.py`) reachable
        from `app/thesis/loop.py`, but the frontend's `LoopOutcome` union only ever listed four
        values -- this proves the fifth travels over the wire unmangled, which is the backend half
        of that fix; `frontend/src/api/thesis.ts`'s union is the other half."""
        _install_runner(monkeypatch, _loop_result(outcome=LoopOutcome.CATALOGUE_EXHAUSTED))
        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 200
        assert response.json()["outcome"] == "catalogue_exhausted"


# ---------------------------------------------------------------------------
# POST /run -- survivor cards, wired through the `CardBuilder` seam
#
# This is the regression class for the original defect: nothing anywhere populated
# `LoopResult.cards`, so `result.cards` was `[]` on every run regardless of outcome, and
# `strategycard.py`/`debate.py`/`ThesisCard.tsx` were unreachable. `test_a_survivor_found_run_gets_a_card`
# below is the test that would have caught it -- it asserts the card a fake `CardBuilder` returns
# actually reaches the response body, not merely that the endpoint returns 200.
# ---------------------------------------------------------------------------


class TestSurvivorCardWiring:
    def test_a_survivor_found_run_gets_a_card_wired_through_the_router(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        survivor = _record(
            "h1",
            verdict=Verdict.SURVIVED,
            status=ThesisStatus.HOLDOUT_TESTED,
            holdout=_evidence(),
        ).model_copy(update={"in_sample": _evidence()})
        holdout_state = HoldoutState(
            symbol="TEST", split_date=dt.date(2024, 1, 1), status=HoldoutStatus.SPENT, attempts=1
        )
        result = _loop_result(
            outcome=LoopOutcome.SURVIVOR_FOUND, records=[survivor], holdout_state=holdout_state
        )
        _install_runner(monkeypatch, result)
        fake_builder = _install_card_builder(monkeypatch, _card(survivor.thesis_hash))

        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 200
        body = response.json()
        assert len(body["cards"]) == 1
        assert body["cards"][0]["thesis_hash"] == survivor.thesis_hash
        assert body["cards"][0]["verdict"] == "survived"
        assert fake_builder.calls == [
            {"symbol": "TEST", "interval": Interval.DAY, "survivor": survivor.thesis_hash}
        ]

    def test_a_card_builder_that_raises_does_not_fail_the_whole_request(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A card build failing is a rendering failure, not a research one -- the loop's own result
        (records, ledger, outcome) is still the valuable, correct part of the response, so this must
        stay a 200 with the failure surfaced as a warning, not turn into a 500."""
        survivor = _record(
            "h1",
            verdict=Verdict.SURVIVED,
            status=ThesisStatus.HOLDOUT_TESTED,
            holdout=_evidence(),
        ).model_copy(update={"in_sample": _evidence()})
        result = _loop_result(outcome=LoopOutcome.SURVIVOR_FOUND, records=[survivor])
        _install_runner(monkeypatch, result)
        _install_card_builder(monkeypatch, ValueError("no bars available for TEST"))

        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "survivor_found"
        assert body["cards"] == []
        assert len(body["records"]) == 1  # the loop's own result is untouched
        warning_kinds = [w["kind"] for w in body["warnings"]]
        assert "card_failed" in warning_kinds
        message = next(w["message"] for w in body["warnings"] if w["kind"] == "card_failed")
        assert "no bars available for TEST" in message

    def test_a_non_survivor_outcome_never_calls_the_card_builder(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Building a card is not free -- see `LoopResult.cards`'s docstring -- so it must only be
        attempted when there is a survivor to build one for."""
        _install_runner(monkeypatch, _loop_result(outcome=LoopOutcome.BUDGET_EXHAUSTED))
        fake_builder = _install_card_builder(monkeypatch, _card("unused"))

        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 200
        assert response.json()["cards"] == []
        assert fake_builder.calls == []


# ---------------------------------------------------------------------------
# POST /run -- the holdout guard, surfaced as HTTP status
# ---------------------------------------------------------------------------


class TestHoldoutErrorMapping:
    def test_a_second_holdout_evaluation_is_409_and_explains_the_burn(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        burned_state = HoldoutState(
            symbol="TEST",
            split_date=dt.date(2024, 1, 1),
            status=HoldoutStatus.BURNED,
            attempts=2,
        )
        warning = MarketWarning(
            kind="holdout_burned",
            message=(
                "TEST: the holdout was already evaluated on 2024-06-01 against thesis abc123456789. "
                "This is attempt 2. A second look is not an out-of-sample test -- the holdout is now "
                "recorded as burned for this ticker."
            ),
        )
        result = _loop_result(
            outcome=LoopOutcome.HOLDOUT_UNAVAILABLE,
            holdout_state=burned_state,
            warnings=[warning],
        )
        _install_runner(monkeypatch, result)

        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "burned" in detail.lower()
        assert "second look" in detail.lower()

    def test_holdout_unavailable_is_422_with_the_reason(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        warning = MarketWarning(
            kind="holdout_unavailable",
            message="TEST: 100 sessions leaves 0 in the holdout, under the 250 needed",
        )
        result = _loop_result(
            outcome=LoopOutcome.HOLDOUT_UNAVAILABLE,
            holdout_state=None,
            warnings=[warning],
        )
        _install_runner(monkeypatch, result)

        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 422
        assert "250" in response.json()["detail"]

    def test_burned_takes_priority_over_generic_unavailable_when_both_signals_present(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A run that burns the holdout always has a state attached (`claim` records before it
        raises) -- the 409 path must fire whenever that state says BURNED, regardless of what else is
        in `warnings`."""
        burned_state = HoldoutState(
            symbol="TEST", split_date=dt.date(2024, 1, 1), status=HoldoutStatus.BURNED, attempts=2
        )
        result = _loop_result(outcome=LoopOutcome.HOLDOUT_UNAVAILABLE, holdout_state=burned_state)
        _install_runner(monkeypatch, result)
        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 409


# ---------------------------------------------------------------------------
# POST /run -- provider errors
# ---------------------------------------------------------------------------


class TestProviderErrorMapping:
    def test_an_unknown_symbol_is_404(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_runner(monkeypatch, SymbolNotFound("NOPE: no such symbol", provider="test"))
        response = client.post("/api/thesis/run", json={"symbol": "NOPE"})
        assert response.status_code == 404

    def test_every_provider_down_is_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_runner(monkeypatch, ProviderUnavailable("all providers down", provider="test"))
        response = client.post("/api/thesis/run", json={"symbol": "TEST"})
        assert response.status_code == 503


# ---------------------------------------------------------------------------
# POST /run -- input bounds
# ---------------------------------------------------------------------------


class TestRunInputBounds:
    """The budget is bounded 1..24 hard -- this endpoint is expensive and unbounded iteration is
    the exact hazard the feature exists to prevent."""

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"symbol": "TEST", "budget": 0}, id="budget zero"),
            pytest.param({"symbol": "TEST", "budget": 25}, id="budget too high"),
            pytest.param({"symbol": "TEST", "budget": -1}, id="negative budget"),
            pytest.param({"symbol": "TEST", "interval": "3y"}, id="malformed interval"),
            pytest.param({"symbol": "../etc/passwd"}, id="path traversal symbol"),
            pytest.param({"symbol": ""}, id="empty symbol"),
            pytest.param({"symbol": "x" * 17}, id="symbol too long"),
            pytest.param({}, id="missing symbol"),
        ],
    )
    def test_rejected_before_the_runner_is_ever_called(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, body: dict[str, object]
    ) -> None:
        fake = _install_runner(monkeypatch, _loop_result())
        response = client.post("/api/thesis/run", json=body)
        assert response.status_code == 422
        assert fake.calls == []


# ---------------------------------------------------------------------------
# GET /ledger
# ---------------------------------------------------------------------------


class TestLedgerEndpoint:
    def test_a_ticker_with_no_history_returns_zeros_not_404(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.get("/api/thesis/ledger?symbol=NEVERSEEN")
        assert response.status_code == 200
        body = response.json()
        assert body["stats"]["total_trials"] == 0
        assert body["records"] == []

    def test_registered_trials_appear_with_the_stats(
        self, client: TestClient, settings: Settings
    ) -> None:
        # `ledger.record` verifies the hash against the thesis's own content, so the record has to
        # come from `preregister.register` rather than a hand-built `ThesisRecord` -- a fabricated
        # hash is exactly what the tamper check exists to catch.
        registered = preregister.register(_thesis())
        finished = registered.model_copy(
            update={"status": ThesisStatus.IN_SAMPLE_TESTED, "verdict": Verdict.REJECTED}
        )
        ledger.record(finished, settings=settings)

        response = client.get("/api/thesis/ledger?symbol=TEST")
        assert response.status_code == 200
        body = response.json()
        assert body["stats"]["total_trials"] == 1
        assert body["stats"]["rejected"] == 1
        assert [r["thesis_hash"] for r in body["records"]] == [finished.thesis_hash]

    def test_path_traversal_symbol_is_422(self, client: TestClient) -> None:
        response = client.get("/api/thesis/ledger?symbol=../etc")
        assert response.status_code == 422

    def test_missing_symbol_is_422(self, client: TestClient) -> None:
        response = client.get("/api/thesis/ledger")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# GET /holdout
# ---------------------------------------------------------------------------


class TestHoldoutEndpoint:
    def test_an_unestablished_holdout_is_a_200_with_a_null_state(
        self, client: TestClient, settings: Settings
    ) -> None:
        response = client.get("/api/thesis/holdout?symbol=NEVERSEEN")
        assert response.status_code == 200
        body = response.json()
        assert body["state"] is None
        assert isinstance(body["description"], str) and body["description"] != ""

    def test_an_established_holdout_reports_its_state_and_a_description(
        self, client: TestClient, settings: Settings
    ) -> None:
        holdout.establish("TEST", _flat_bars(), settings=settings)

        response = client.get("/api/thesis/holdout?symbol=TEST")
        assert response.status_code == 200
        body = response.json()
        assert body["state"] is not None
        assert body["state"]["status"] == "unused"
        assert "one evaluation is available" in body["description"].lower()

    def test_a_burned_holdout_is_visibly_described_as_burned(
        self, client: TestClient, settings: Settings
    ) -> None:
        holdout.establish("TEST", _flat_bars(), settings=settings)
        holdout.claim("TEST", "hash-a", settings=settings)
        with contextlib.suppress(holdout.HoldoutBurned):
            holdout.claim("TEST", "hash-b", settings=settings)

        response = client.get("/api/thesis/holdout?symbol=TEST")
        assert response.status_code == 200
        body = response.json()
        assert body["state"]["status"] == "burned"
        assert "no longer an out-of-sample test" in body["description"].lower()


# ---------------------------------------------------------------------------
# GET /catalogue
# ---------------------------------------------------------------------------


class TestCatalogueEndpoint:
    def test_every_template_is_listed_with_a_non_empty_falsifies_if(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/thesis/catalogue")
        assert response.status_code == 200
        body = response.json()
        assert len(body) == len(author.CATALOGUE)
        keys = {entry["key"] for entry in body}
        assert keys == {t.key for t in author.CATALOGUE}
        for entry in body:
            assert entry["falsifies_if"].strip() != ""
            assert entry["hypothesis"].strip() != ""


# ---------------------------------------------------------------------------
# Router mounting
# ---------------------------------------------------------------------------


class TestRouterIsMounted:
    def test_the_openapi_schema_lists_every_endpoint(self, client: TestClient) -> None:
        paths = set(client.get("/openapi.json").json()["paths"])
        assert {
            "/api/thesis/run",
            "/api/thesis/ledger",
            "/api/thesis/holdout",
            "/api/thesis/catalogue",
        } <= paths
