"""Integration tests for the rule HTTP API (`app.api.rules`) and, through it, `app.rules.service`.

`app.main` does not wire this router yet -- that is the orchestrator's job once every phase-6 module
lands -- so the `app` fixture below builds its own minimal `FastAPI` app around `rules_api.router`,
the same way `tests/test_macro_api.py` exercises `app.api.macro` before `app.main` grows an
`app.include_router(rules_api.router)` line. Once that line exists, these tests keep working
unchanged: they only depend on the router object and the modules it calls into.

`app.rules.grammar` and `app.rules.evidence` may not exist yet while this phase is still being built
in parallel by other agents. Every test here fakes all three collaborators
(`app.rules.service._default_grammar` / `_default_evaluator` / `_default_evidence`, and
`app.api.rules._grammar` / `_evaluator` for `/validate`) rather than importing the real modules, so
this file collects and passes regardless of their state -- and keeps passing once they land, since
nothing here depends on their internals, only on the fixed signatures documented in
`app.rules.service`.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import rules as rules_api
from app.config import Settings
from app.db.duck import BAR_COLUMNS, Interval
from app.market.providers.base import SymbolNotFound
from app.market.registry import ProviderRegistry
from app.rules import catalog as catalog_module
from app.rules import service
from app.rules.evaluate import IndicatorCache
from app.rules.models import HORIZONS, Evidence, RuleState, TriState

TODAY = dt.date.today()


# ---------------------------------------------------------------------------
# Fakes -- no test in this file touches the network or requires grammar.py/evidence.py to exist
# ---------------------------------------------------------------------------


class FakeGrammar:
    """Stands in for `app.rules.grammar`. The "node" it produces is just the expression string
    itself -- these tests never inspect tree internals, only that the same object flows from
    `parse` through `render` and into `evaluate`/`required_specs`.

    Rejects a blank expression (matching a real parser's behaviour on `""`) and anything containing
    the `@@BAD@@` marker or listed in `fail_on`, so individual tests can target one specific
    catalog rule's expression without the fake needing real grammar semantics.
    """

    def __init__(self, fail_on: frozenset[str] = frozenset()) -> None:
        self._fail_on = fail_on

    def parse(self, expression: str) -> str:
        if not expression.strip():
            raise ValueError("empty expression")
        if "@@BAD@@" in expression or expression in self._fail_on:
            raise ValueError(f"could not parse {expression!r} at position 0")
        return expression

    def render(self, node: str) -> str:
        return node


class FakeEvaluator:
    """Stands in for `app.rules.evaluate`. Produces a deterministic alternating signal so
    `FakeEvidence` has something non-trivial to summarise, and raises for any node listed in
    `fail_on` -- a test targets one catalog rule's expression the same way `FakeGrammar` does."""

    def __init__(self, fail_on: frozenset[str] = frozenset()) -> None:
        self._fail_on = fail_on
        self.calls: list[str] = []

    def evaluate(
        self,
        node: str,
        bars: pd.DataFrame,
        *,
        interval: Interval,
        indicator_cache: IndicatorCache | None = None,
    ) -> pd.Series:
        self.calls.append(node)
        if node in self._fail_on:
            raise ValueError(f"could not evaluate {node!r}")
        values = [i % 2 == 0 for i in range(len(bars))]
        return pd.Series(values, index=bars.index, dtype="boolean")

    def required_specs(self, node: str) -> list[str]:
        """A *real* spec string, not a synthetic one.

        `/validate` now checks each returned spec against the indicator registry -- parsing is not
        validity, and `rsi(14, 5)` used to come back VALID. A stub that returns `f"spec:{node}"`
        makes that check fail on every call for a reason that has nothing to do with the endpoint,
        so the fake has to speak the registry's language.
        """
        return ["rsi:14"]


class FakeEvidence:
    """Stands in for `app.rules.evidence`. Just enough to populate a valid `RuleState`/`Evidence`
    shape -- the statistics themselves are not this file's concern, `app.rules.service`'s tests are
    (via this same file, since that module has no dedicated HTTP-free test file of its own -- see
    the delivery brief's file list)."""

    def rule_state(self, signal: pd.Series, bars: pd.DataFrame) -> RuleState:
        last = bool(signal.iloc[-1]) if len(signal) else None
        state = TriState.UNKNOWN if last is None else (TriState.TRUE if last else TriState.FALSE)
        return RuleState(state=state, triggers_in_history=int(signal.fillna(False).sum()))

    def compute_evidence(self, signal: pd.Series, bars: pd.DataFrame) -> list[Evidence]:
        return [Evidence(horizon=h, sample_size=0) for h in HORIZONS]


class FakeBarProvider:
    """Serves a fixed frame per symbol; raises `SymbolNotFound` for anything not registered."""

    name = "yahoo"
    supported_intervals = frozenset({Interval.FIVE_MIN, Interval.HOUR, Interval.DAY})

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self._frames = frames

    def fetch_bars(
        self,
        symbol: str,
        interval: Interval,
        *,
        start: dt.date | None = None,
        end: dt.date | None = None,
    ) -> pd.DataFrame:
        if symbol not in self._frames:
            raise SymbolNotFound(f"yahoo has no fixture for {symbol!r}", provider="yahoo")
        return self._frames[symbol].copy()


def _daily_frame(n: int, *, end: dt.date) -> pd.DataFrame:
    """`n` ascending daily bars ending on `end`, shaped like a real fetch."""
    stamps = [
        dt.datetime.combine(end, dt.time.min, tzinfo=dt.UTC) - dt.timedelta(days=(n - 1 - i))
        for i in range(n)
    ]
    closes = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "ts": pd.Series(stamps, dtype="datetime64[us, UTC]"),
            "open": [c - 0.5 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000 + i for i in range(n)],
        }
    )


def _empty_frame() -> pd.DataFrame:
    """A zero-row frame with the right columns -- "this symbol has no bars", not "unknown symbol"."""
    columns: dict[str, pd.Series[Any]] = {"ts": pd.Series(dtype="datetime64[us, UTC]")}
    columns.update({c: pd.Series(dtype="float64") for c in BAR_COLUMNS if c != "ts"})
    return pd.DataFrame(columns)


def _working_registry() -> ProviderRegistry:
    frames = {"SOXL": _daily_frame(90, end=TODAY), "NODATA": _empty_frame()}
    return ProviderRegistry(bar_providers=[FakeBarProvider(frames)])


def _strict_json_loads(text: str) -> Any:
    """Parses `text`, raising on a bare `NaN`/`Infinity`/`-Infinity` token -- the invalid-JSON shape
    `json.dumps` produces for a float that should have been routed through `jsonable_float` first."""
    return json.loads(text, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))


# ---------------------------------------------------------------------------
# App + fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the rules router -- see the module docstring."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(rules_api.router)
    return fastapi_app


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> TestClient:
    """A client whose grammar, evaluator, evidence builder and bar registry are all working fakes.

    Individual tests override one of these again via `monkeypatch` to exercise a degraded rule or
    upstream, matching the layered-fixture style `tests/test_market_api.py` and
    `tests/test_macro_api.py` use for their own clients.
    """
    monkeypatch.setattr(service, "_default_grammar", lambda: FakeGrammar())
    monkeypatch.setattr(service, "_default_evaluator", lambda: FakeEvaluator())
    monkeypatch.setattr(service, "_default_evidence", lambda: FakeEvidence())
    monkeypatch.setattr(rules_api, "_grammar", lambda: FakeGrammar())
    monkeypatch.setattr(rules_api, "_evaluator", lambda: FakeEvaluator())
    monkeypatch.setattr(rules_api, "_registry", lambda: _working_registry())
    return TestClient(app)


# ---------------------------------------------------------------------------
# /api/rules/catalog
# ---------------------------------------------------------------------------


class TestCatalogEndpoint:
    def test_returns_the_full_catalog(self, client: TestClient) -> None:
        response = client.get("/api/rules/catalog")
        assert response.status_code == 200
        body = response.json()
        assert {r["rule_id"] for r in body} == {r.rule_id for r in catalog_module.catalog()}

    def test_response_matches_the_rule_shape(self, client: TestClient) -> None:
        """Field-for-field spot check against `frontend/src/api/rules.ts`'s `Rule`."""
        body = client.get("/api/rules/catalog").json()
        assert set(body[0]) == {"rule_id", "name", "expression", "description", "intervals"}

    def test_no_nan_or_infinity_token_reaches_the_wire(self, client: TestClient) -> None:
        raw = client.get("/api/rules/catalog").text
        assert "NaN" not in raw and "Infinity" not in raw
        _strict_json_loads(raw)


# ---------------------------------------------------------------------------
# /api/rules/decisions
# ---------------------------------------------------------------------------


class TestDecisionsEndpoint:
    def test_happy_path_returns_one_row_per_catalog_rule(self, client: TestClient) -> None:
        response = client.get("/api/rules/decisions?symbol=SOXL")
        assert response.status_code == 200
        body = response.json()
        assert body["symbol"] == "SOXL"
        assert body["interval"] == "1d"
        assert body["bars_evaluated"] == 90
        assert body["first_bar"] is not None and body["last_bar"] is not None
        assert len(body["rows"]) == len(catalog_module.catalog())

        row = next(r for r in body["rows"] if r["rule"]["rule_id"] == "rsi_oversold")
        assert row["state"]["state"] in {"true", "false"}
        assert row["warnings"] == []
        assert len(row["evidence"]) == len(HORIZONS)

    def test_response_matches_the_decision_table_shape(self, client: TestClient) -> None:
        """Field-for-field spot check against `frontend/src/api/rules.ts`'s `DecisionTable`."""
        body = client.get("/api/rules/decisions?symbol=SOXL").json()
        assert set(body) == {
            "symbol", "interval", "generated_at", "bars_evaluated", "first_bar", "last_bar",
            "rows", "criteria", "warnings",
        }
        row = body["rows"][0]
        assert set(row) == {"rule", "state", "evidence", "warnings"}

        # `criteria` carries the thresholds the Significance column is graded by, so the legend a
        # user reads is the rule the code applied rather than a paragraph in a component that would
        # drift the first time a constant moved.
        assert set(body["criteria"]) == {
            "weak_min_independent", "weak_min_edge",
            "suggestive_min_independent", "suggestive_min_edge",
        }
        assert body["criteria"]["suggestive_min_independent"] > body["criteria"]["weak_min_independent"]

    def test_symbol_is_upper_cased(self, client: TestClient) -> None:
        body = client.get("/api/rules/decisions?symbol=soxl").json()
        assert body["symbol"] == "SOXL"

    def test_a_rule_not_defined_on_this_interval_still_appears_as_a_degraded_row(
        self, client: TestClient
    ) -> None:
        """`vwap_reclaim` is intraday-only; requested on the default `1d` interval it must still be
        a row -- degraded, not missing. See `app.rules.service.build_decision_table`."""
        response = client.get("/api/rules/decisions?symbol=SOXL")
        body = response.json()
        row = next(r for r in body["rows"] if r["rule"]["rule_id"] == "vwap_reclaim")
        assert row["state"]["state"] == "unknown"
        assert row["warnings"]
        assert row["warnings"][0]["kind"] == "unsupported_interval"
        # every rule that *is* defined on this interval must be unaffected by the bad one
        assert len(body["rows"]) == len(catalog_module.catalog())

    def test_a_rule_that_fails_to_parse_still_appears_as_a_degraded_row(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad = catalog_module.get("rsi_oversold")
        assert bad is not None
        monkeypatch.setattr(
            service, "_default_grammar", lambda: FakeGrammar(fail_on=frozenset({bad.expression}))
        )

        response = client.get("/api/rules/decisions?symbol=SOXL")

        assert response.status_code == 200
        body = response.json()
        assert len(body["rows"]) == len(catalog_module.catalog())  # the table was not emptied
        row = next(r for r in body["rows"] if r["rule"]["rule_id"] == "rsi_oversold")
        assert row["state"]["state"] == "unknown"
        assert row["warnings"][0]["kind"] == "parse_error"
        # an unrelated rule is unaffected
        other = next(r for r in body["rows"] if r["rule"]["rule_id"] == "rsi_overbought")
        assert other["warnings"] == []

    def test_a_rule_that_fails_to_evaluate_still_appears_as_a_degraded_row(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        bad = catalog_module.get("rsi_overbought")
        assert bad is not None
        monkeypatch.setattr(
            service, "_default_evaluator", lambda: FakeEvaluator(fail_on=frozenset({bad.expression}))
        )

        response = client.get("/api/rules/decisions?symbol=SOXL")

        assert response.status_code == 200
        body = response.json()
        assert len(body["rows"]) == len(catalog_module.catalog())
        row = next(r for r in body["rows"] if r["rule"]["rule_id"] == "rsi_overbought")
        assert row["state"]["state"] == "unknown"
        assert row["warnings"][0]["kind"] == "evaluate_error"
        other = next(r for r in body["rows"] if r["rule"]["rule_id"] == "rsi_oversold")
        assert other["warnings"] == []

    def test_symbol_with_no_stored_bars_is_an_empty_table_not_a_500(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/rules/decisions?symbol=NODATA")
        assert response.status_code == 200
        body = response.json()
        assert body["rows"] == []
        assert body["bars_evaluated"] == 0
        assert body["first_bar"] is None and body["last_bar"] is None
        assert any(w["kind"] == "short_history" for w in body["warnings"])

    def test_unknown_symbol_is_404_not_500(self, client: TestClient) -> None:
        response = client.get("/api/rules/decisions?symbol=NOPE")
        assert response.status_code == 404

    def test_malformed_interval_is_a_4xx_not_a_500(self, client: TestClient) -> None:
        response = client.get("/api/rules/decisions?symbol=SOXL&interval=3d")
        assert 400 <= response.status_code < 500

    def test_no_nan_or_infinity_token_reaches_the_wire(self, client: TestClient) -> None:
        raw = client.get("/api/rules/decisions?symbol=SOXL").text
        assert "NaN" not in raw and "Infinity" not in raw
        _strict_json_loads(raw)


# ---------------------------------------------------------------------------
# /api/rules/validate
# ---------------------------------------------------------------------------


class TestValidateEndpoint:
    def test_valid_expression_is_200_with_valid_true(self, client: TestClient) -> None:
        response = client.post("/api/rules/validate", json={"expression": "rsi(14) < 30"})
        assert response.status_code == 200
        body = response.json()
        assert body == {
            "valid": True,
            "error": None,
            "normalized": "rsi(14) < 30",
            "indicators": ["rsi:14"],
        }

    def test_malformed_expression_is_200_with_valid_false_not_a_4xx(
        self, client: TestClient
    ) -> None:
        response = client.post("/api/rules/validate", json={"expression": "@@BAD@@ nonsense"})
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["error"]
        assert body["normalized"] is None
        assert body["indicators"] == []

    def test_an_expression_the_engine_would_refuse_is_not_valid(self) -> None:
        """Parsing is not validity.

        `rsi(14, 5)` and `sma(9999)` both parse -- the grammar accepts any argument list -- and both
        are refused by `parse_spec` the moment the rule runs, for arity and for range. They were
        reported VALID until a UAT persona checked what the registry actually does with them. A
        green checkmark on an expression the engine will reject is worse than no checkmark, because
        the user builds on it.

        Uses the real grammar and evaluator rather than this module's fakes: the whole point is what
        the registry says, so stubbing it out would test nothing.
        """
        from fastapi.testclient import TestClient as _TestClient

        from app.main import app as _app

        real = _TestClient(_app)
        for expression, expected in (
            ("rsi(14) < 30", True),
            ("close > sma(200)", True),
            ("rsi(14, 5) < 30", False),
            ("close > sma(9999)", False),
        ):
            body = real.post("/api/rules/validate", json={"expression": expression}).json()
            assert body["valid"] is expected, (expression, body)
            if not expected:
                assert body["error"], expression

    def test_empty_string_is_200_with_valid_false(self, client: TestClient) -> None:
        response = client.post("/api/rules/validate", json={"expression": ""})
        assert response.status_code == 200
        body = response.json()
        assert body["valid"] is False
        assert body["error"]

    def test_missing_expression_field_is_a_4xx(self, client: TestClient) -> None:
        response = client.post("/api/rules/validate", json={})
        assert response.status_code == 422

    def test_overlength_expression_is_a_4xx(self, client: TestClient) -> None:
        response = client.post(
            "/api/rules/validate", json={"expression": "rsi(14) < 30 and " * 200}
        )
        assert response.status_code == 422

    def test_no_nan_or_infinity_token_reaches_the_wire(self, client: TestClient) -> None:
        raw = client.post("/api/rules/validate", json={"expression": "rsi(14) < 30"}).text
        assert "NaN" not in raw and "Infinity" not in raw
        _strict_json_loads(raw)
