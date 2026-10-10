"""Tests for `app.i18n.narrative.translate_texts` and `POST /api/i18n/translate`.

Fully offline, matching `tests/test_agents_reviewer.py`'s own convention: every scenario below
monkeypatches `app.i18n.narrative.call_structured` (the name imported into that module, which is what
actually needs patching for the monkeypatch to take effect -- patching `app.agents.client.
call_structured` itself would leave `narrative`'s own already-bound reference untouched) rather than
reaching the real `anthropic` SDK.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.models import AgentBudget, AgentCall
from app.api import i18n as i18n_router
from app.config import Settings, get_settings
from app.i18n import narrative as narrative_module

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def settings_off(tmp_path: Path) -> Settings:
    """The flag's default: translation disabled."""
    return Settings(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        store_dir=tmp_path / "store",
        cache_dir=tmp_path / "cache",
        translate_narratives=False,
    )


@pytest.fixture()
def settings_on(tmp_path: Path) -> Settings:
    """Translation opted in, with a small but non-trivial budget."""
    return Settings(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        store_dir=tmp_path / "store",
        cache_dir=tmp_path / "cache",
        translate_narratives=True,
        translate_budget_usd=Decimal("2.00"),
    )


def _make_call(**overrides: Any) -> AgentCall:
    defaults: dict[str, Any] = {
        "call_id": "call-test-0001",
        "role": "translator",
        "model": narrative_module.DEFAULT_MODEL,
        "created_at": dt.datetime.now(dt.UTC),
        "system": narrative_module._SYSTEM_PROMPT,
        "user": "usr",
        "raw_response": "{}",
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cost_usd": Decimal("0.01"),
        "request_id": None,
        "stop_reason": None,
    }
    defaults.update(overrides)
    return AgentCall(**defaults)


def _fake_call_structured_returning(korean: str) -> Any:
    """A `call_structured`-shaped callable that always answers `korean`, counting how many times it
    was invoked on the function object itself (`.calls`), the same lightweight counter shape
    `tests/test_agentdesk_core.py`'s own `_fake_call` helper uses."""

    def fake(**kwargs: Any) -> tuple[Any, AgentCall, AgentBudget]:
        fake.calls += 1  # type: ignore[attr-defined]
        budget: AgentBudget = kwargs["budget"]
        new_budget = AgentBudget(
            cap_usd=budget.cap_usd,
            spent_usd=budget.spent_usd + Decimal("0.01"),
            calls=budget.calls + 1,
        )
        return narrative_module._KoreanText(korean=korean), _make_call(), new_budget

    fake.calls = 0  # type: ignore[attr-defined]
    return fake


def _failing_call_structured(**kwargs: Any) -> Any:
    raise AssertionError("call_structured must not be called")


# ---------------------------------------------------------------------------
# translate_texts
# ---------------------------------------------------------------------------


class TestFlagOff:
    def test_flag_off_returns_all_none_without_calling_model(
        self, monkeypatch: pytest.MonkeyPatch, settings_off: Settings
    ) -> None:
        monkeypatch.setattr(narrative_module, "call_structured", _failing_call_structured)

        results = narrative_module.translate_texts(
            ["The S&P 500 rose 15.3% this year.", "Another sentence."],
            locale="ko",
            settings=settings_off,
        )

        assert results == [None, None]


class TestFlagOnCleanTranslation:
    def test_clean_translation_preserving_numbers_is_returned_and_cached(
        self, monkeypatch: pytest.MonkeyPatch, settings_on: Settings
    ) -> None:
        fake = _fake_call_structured_returning("올해 S&P 500 지수가 15.3% 상승했습니다.")
        monkeypatch.setattr(narrative_module, "call_structured", fake)

        results = narrative_module.translate_texts(
            ["The S&P 500 rose 15.3% this year."], locale="ko", settings=settings_on
        )

        assert results == ["올해 S&P 500 지수가 15.3% 상승했습니다."]
        assert fake.calls == 1

    def test_one_model_call_per_text(self, monkeypatch: pytest.MonkeyPatch, settings_on: Settings) -> None:
        fake = _fake_call_structured_returning("숫자 15.3이 포함된 번역입니다.")
        monkeypatch.setattr(narrative_module, "call_structured", fake)

        results = narrative_module.translate_texts(
            ["First 15.3 sentence.", "Second 15.3 sentence."], locale="ko", settings=settings_on
        )

        assert len(results) == 2
        assert all(r is not None for r in results)
        assert fake.calls == 2


class TestNumberPreservationGate:
    def test_translation_missing_a_source_number_is_rejected_and_not_cached(
        self, monkeypatch: pytest.MonkeyPatch, settings_on: Settings
    ) -> None:
        # The model drops the 15.3% figure entirely -- no digits anywhere in its response.
        fake = _fake_call_structured_returning("올해 S&P 500 지수가 상승했습니다.")
        monkeypatch.setattr(narrative_module, "call_structured", fake)

        results = narrative_module.translate_texts(
            ["The S&P 500 rose 15.3% this year."], locale="ko", settings=settings_on
        )

        assert results == [None]
        assert fake.calls == 1

        # Nothing was cached for the rejected translation -- a second call still hits the model.
        results_again = narrative_module.translate_texts(
            ["The S&P 500 rose 15.3% this year."], locale="ko", settings=settings_on
        )
        assert results_again == [None]
        assert fake.calls == 2


class TestCache:
    def test_cache_hit_does_not_call_model_again(
        self, monkeypatch: pytest.MonkeyPatch, settings_on: Settings
    ) -> None:
        fake = _fake_call_structured_returning("15.3% 상승했습니다.")
        monkeypatch.setattr(narrative_module, "call_structured", fake)

        first = narrative_module.translate_texts(["Up 15.3% today."], locale="ko", settings=settings_on)
        assert first == ["15.3% 상승했습니다."]
        assert fake.calls == 1

        second = narrative_module.translate_texts(["Up 15.3% today."], locale="ko", settings=settings_on)
        assert second == ["15.3% 상승했습니다."]
        assert fake.calls == 1  # unchanged -- served from cache


class TestEmptyAndWhitespace:
    def test_empty_and_whitespace_texts_return_none_without_calling_model(
        self, monkeypatch: pytest.MonkeyPatch, settings_on: Settings
    ) -> None:
        monkeypatch.setattr(narrative_module, "call_structured", _failing_call_structured)

        results = narrative_module.translate_texts(["", "   ", "\t\n"], locale="ko", settings=settings_on)

        assert results == [None, None, None]


class TestBudgetExhaustion:
    def test_exhausted_budget_stops_further_model_calls(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        settings = Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            store_dir=tmp_path / "store",
            cache_dir=tmp_path / "cache",
            translate_narratives=True,
            # A cap smaller than one call's cost (0.01 spent per call in the fake above): the very
            # first call exhausts it, so the second text must not reach the model at all.
            translate_budget_usd=Decimal("0.005"),
        )
        fake = _fake_call_structured_returning("15.3% 상승했습니다.")
        monkeypatch.setattr(narrative_module, "call_structured", fake)

        results = narrative_module.translate_texts(
            ["First 15.3 sentence.", "Second 22.1 sentence."], locale="ko", settings=settings
        )

        # The budget starts at 0 spent against a 0.005 cap, so `exhausted` (spent >= cap) is False
        # until the first call reports 0.01 spent -- the first call is allowed, the second is not.
        assert fake.calls == 1
        assert results[1] is None


# ---------------------------------------------------------------------------
# The router
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(settings_on: Settings) -> FastAPI:
    fastapi_app = FastAPI()
    fastapi_app.include_router(i18n_router.router)
    fastapi_app.dependency_overrides[get_settings] = lambda: settings_on
    return fastapi_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


class TestRouter:
    def test_results_match_request_length_and_order(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_translate_texts(texts: Any, *, locale: str, settings: Settings) -> list[str | None]:
            assert locale == "ko"
            return ["번역1" if t.strip() else None for t in texts]

        monkeypatch.setattr(i18n_router, "translate_texts", fake_translate_texts)

        response = client.post(
            "/api/i18n/translate",
            json={"locale": "ko", "texts": ["Hello world", "", "Another one"]},
        )

        assert response.status_code == 200
        body = response.json()
        assert body == {"results": ["번역1", None, "번역1"]}

    def test_empty_texts_list_returns_empty_results(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(i18n_router, "translate_texts", lambda texts, *, locale, settings: [])

        response = client.post("/api/i18n/translate", json={"locale": "ko", "texts": []})

        assert response.status_code == 200
        assert response.json() == {"results": []}

    def test_unsupported_locale_is_rejected(self, client: TestClient) -> None:
        response = client.post("/api/i18n/translate", json={"locale": "fr", "texts": ["Hello"]})

        assert response.status_code == 422

    def test_too_many_texts_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/i18n/translate", json={"locale": "ko", "texts": ["x"] * (i18n_router._MAX_TEXTS + 1)}
        )

        assert response.status_code == 422

    def test_max_texts_is_accepted(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            i18n_router,
            "translate_texts",
            lambda texts, *, locale, settings: [None] * len(texts),
        )

        response = client.post(
            "/api/i18n/translate", json={"locale": "ko", "texts": ["x"] * i18n_router._MAX_TEXTS}
        )

        assert response.status_code == 200
        assert len(response.json()["results"]) == i18n_router._MAX_TEXTS

    def test_real_translate_texts_end_to_end_flag_off(self, settings_off: Settings) -> None:
        """No monkeypatching at all: the flag-off path through the real router and the real
        `translate_texts`, proving the two are actually wired together."""
        fastapi_app = FastAPI()
        fastapi_app.include_router(i18n_router.router)
        fastapi_app.dependency_overrides[get_settings] = lambda: settings_off
        with TestClient(fastapi_app) as off_client:
            response = off_client.post(
                "/api/i18n/translate", json={"locale": "ko", "texts": ["Hello", "World"]}
            )

        assert response.status_code == 200
        assert response.json() == {"results": [None, None]}
