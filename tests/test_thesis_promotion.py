"""Promoting a Thesis survivor onto the library shelf -- `app.thesis.promotion` and `POST /promote`.

Three concerns, kept apart:

* **The translation** (`TestBuildCard`) -- a survivor `ThesisRecord` to a `reference_only`
  `app.tournament.models.StrategyCard`, pure and disk-free. This is where the field-by-field contract
  is pinned, including the two refusals (`NotASurvivor`, `NotPromotable`).
* **The write** (`TestPromoteToDisk`) -- idempotent, one JSON per survivor, into a *temporary*
  library so the real shelf under `backend/app/paper/library/` is never touched.
* **The invariant that makes it honest** (`TestReferenceOnlyIsNeverScored`) -- a `reference_only`
  card is exempt from the design cutoff only because nothing scores it, so the model refuses the
  contradiction with `desk_only`, and `app.tournament.jobs` refuses it from a round.
* **The endpoint** (`TestPromoteEndpoint`) -- status-code mapping, driven through
  `app.api.thesis`'s own `_default_*` seams, the same way `tests/test_thesis_api.py` tests `/run`.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import thesis as thesis_api
from app.config import Settings
from app.db.duck import Interval
from app.main import app
from app.thesis import author, preregister, promotion
from app.thesis.models import Direction, Thesis, ThesisRecord, ThesisStatus, Verdict
from app.tournament.models import Discipline, StrategyCard
from app.tournament.purposes import Purpose

# ---------------------------------------------------------------------------------------------
# Helpers -- a survivor record, built the way tests/test_thesis_card.py builds one.
# ---------------------------------------------------------------------------------------------


def _thesis(**overrides: object) -> Thesis:
    base: dict[str, object] = {
        "symbol": "QQQ",
        "interval": Interval.DAY,
        "hypothesis": "A fixed rule fires and forward returns beat baseline.",
        "entry": "close < sma(20)",
        "exit": "close > sma(20)",
        "horizon": 5,
        "direction": Direction.UP,
        "falsifies_if": "the hit rate after the rule does not exceed the unconditional rate",
    }
    base.update(overrides)
    return Thesis(**base)  # type: ignore[arg-type]


def _survivor(thesis: Thesis | None = None, *, verdict: Verdict = Verdict.SURVIVED) -> ThesisRecord:
    """A registered record with a verdict attached. `model_copy` sidesteps the survivor-needs-holdout
    validator exactly as `tests/test_thesis_card.py::_record` does -- promotion reads the verdict, the
    thesis and the registration date, none of which need holdout evidence present."""
    registered = preregister.register(thesis if thesis is not None else _thesis())
    return registered.model_copy(update={"status": ThesisStatus.HOLDOUT_TESTED, "verdict": verdict})


def _from_template(key: str) -> ThesisRecord:
    """A survivor whose thesis is the catalogue template `key` verbatim -- what `author.propose`
    actually mints, so `discipline_for` can match it back."""
    template = author.template_for(key)
    assert template is not None, key
    thesis = _thesis(
        hypothesis=template.hypothesis,
        entry=template.entry,
        exit=template.exit,
        horizon=template.horizon,
        direction=template.direction,
        falsifies_if=template.falsifies_if,
        max_holding_bars=template.max_holding_bars,
        stop_loss_pct=template.stop_loss_pct,
    )
    return _survivor(thesis)


# ---------------------------------------------------------------------------------------------
# The translation
# ---------------------------------------------------------------------------------------------


class TestBuildCard:
    def test_survivor_becomes_a_reference_only_single_name_card(self) -> None:
        record = _survivor(_thesis(symbol="qqq", stop_loss_pct=0.08, max_holding_bars=40))
        card = promotion.build_card(record, catalogue=author.CATALOGUE)

        assert isinstance(card, StrategyCard)
        assert card.reference_only is True
        assert card.desk_only is False
        assert card.universe == ("QQQ",)
        assert card.max_positions == 1
        # Every executable field is the ledger's thesis, not anything invented here.
        assert card.entry == record.thesis.entry
        assert card.exit == record.thesis.exit
        assert card.falsification == record.thesis.falsifies_if
        # Provenance links back to the exact survivor; the id is a pure function of it.
        assert card.source_thesis_hash == record.thesis_hash
        assert card.agent_id == f"T-QQQ-{record.thesis_hash[:8]}"

    def test_designed_through_is_the_registration_date(self) -> None:
        record = _survivor()
        card = promotion.build_card(record, catalogue=author.CATALOGUE)
        assert card.designed_through == record.registered_at.date()

    def test_position_pct_and_purpose_pass_through(self) -> None:
        from decimal import Decimal

        record = _survivor()
        card = promotion.build_card(
            record, position_pct=Decimal("0.05"), purpose=Purpose.ROTH, catalogue=author.CATALOGUE
        )
        assert card.position_pct == Decimal("0.05")
        assert card.purpose is Purpose.ROTH

    def test_a_non_survivor_is_refused(self) -> None:
        for verdict in (Verdict.REJECTED, Verdict.INCONCLUSIVE):
            record = _survivor(verdict=verdict)
            with pytest.raises(promotion.NotASurvivor):
                promotion.build_card(record, catalogue=author.CATALOGUE)

    def test_a_non_daily_survivor_is_refused(self) -> None:
        record = _survivor(_thesis(interval=Interval.HOUR))
        with pytest.raises(promotion.NotPromotable, match="daily"):
            promotion.build_card(record, catalogue=author.CATALOGUE)

    def test_an_exit_less_thesis_becomes_an_empty_exit_with_a_time_stop(self) -> None:
        # volatility_contraction is the catalogue template with exit=None + max_holding_bars set.
        record = _from_template("volatility_contraction")
        assert record.thesis.exit is None
        card = promotion.build_card(record, catalogue=author.CATALOGUE)
        # The sanctioned "no discretionary exit" representation: an empty exit the runner skips,
        # closed instead by the time stop.
        assert card.exit == ""
        assert card.max_hold_days == record.thesis.max_holding_bars

    def test_a_thesis_that_could_hold_forever_is_refused(self) -> None:
        record = _survivor(_thesis(exit=None, max_holding_bars=None, stop_loss_pct=0.1))
        # A stop-loss alone does not satisfy the exit requirement -- it closes losers, never winners.
        with pytest.raises(promotion.NotPromotable, match="close a position"):
            promotion.build_card(record, catalogue=author.CATALOGUE)

    def test_out_of_range_time_stop_is_refused(self) -> None:
        record = _survivor(_thesis(max_holding_bars=400))
        with pytest.raises(promotion.NotPromotable, match="time-stop"):
            promotion.build_card(record, catalogue=author.CATALOGUE)

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("band_reversion", Discipline.MEAN_REVERSION),
            ("trend_following", Discipline.TREND),
            ("momentum_persistence", Discipline.MOMENTUM),
            ("volatility_contraction", Discipline.VOLATILITY),
            ("decay_avoidance", Discipline.RISK_MANAGED),
        ],
    )
    def test_discipline_is_derived_from_the_source_template(
        self, key: str, expected: Discipline
    ) -> None:
        record = _from_template(key)
        discipline, matched = promotion.discipline_for(record.thesis, author.CATALOGUE)
        assert discipline is expected
        assert matched == key

    def test_a_thesis_matching_no_template_falls_back_to_risk_managed(self) -> None:
        record = _survivor(_thesis(hypothesis="bespoke, matches no template", entry="close > sma(3)"))
        discipline, matched = promotion.discipline_for(record.thesis, author.CATALOGUE)
        assert discipline is Discipline.RISK_MANAGED
        assert matched is None


# ---------------------------------------------------------------------------------------------
# The write -- into a temporary library, never the real shelf
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def tmp_settings(settings: Settings, tmp_path: Path) -> Settings:
    """`settings` with `library_dir` redirected into `tmp_path`. `library_dir` is a fixed source-tree
    path by default (`config.py`), so a promote() that wrote through the real settings would land a
    card in `backend/app/paper/library/candidates/` -- this keeps every write in the temp dir."""
    return settings.model_copy(update={"library_dir": tmp_path / "library"})


class TestPromoteToDisk:
    def test_writes_one_valid_card_into_candidates(self, tmp_settings: Settings) -> None:
        record = _survivor(_thesis(max_holding_bars=40))
        result = promotion.promote(record, settings=tmp_settings, catalogue=author.CATALOGUE)

        assert result.created is True
        assert result.path == tmp_settings.library_dir / "candidates" / f"{result.card.agent_id}.json"
        assert result.path.is_file()
        # Round-trips through the library model -- it is a real, valid card, not just bytes.
        reloaded = StrategyCard.model_validate_json(result.path.read_text(encoding="utf-8"))
        assert reloaded == result.card
        assert reloaded.reference_only is True

    def test_re_promoting_the_same_survivor_is_idempotent(self, tmp_settings: Settings) -> None:
        record = _survivor(_thesis(max_holding_bars=40))
        first = promotion.promote(record, settings=tmp_settings, catalogue=author.CATALOGUE)
        second = promotion.promote(record, settings=tmp_settings, catalogue=author.CATALOGUE)

        assert first.created is True
        assert second.created is False
        assert second.card == first.card
        # Exactly one file, never a duplicate or an overwrite.
        candidates = list((tmp_settings.library_dir / "candidates").glob("*.json"))
        assert candidates == [first.path]


# ---------------------------------------------------------------------------------------------
# The invariant: a reference_only card is scored on no window
# ---------------------------------------------------------------------------------------------


class TestReferenceOnlyIsNeverScored:
    def test_reference_only_is_exempt_from_the_design_cutoff(self) -> None:
        # A designed_through of *today* -- long after every scored window opens -- is fine, because
        # nothing scores a reference card. A tournament card with the same date would be rejected.
        card = promotion.build_card(_survivor(), catalogue=author.CATALOGUE)
        assert card.designed_through >= dt.date(2026, 8, 15)  # past DESK_INCEPTION, still valid

    def test_a_card_cannot_be_both_reference_only_and_desk_only(self) -> None:
        payload = promotion.build_card(
            _survivor(_thesis(max_holding_bars=40)), catalogue=author.CATALOGUE
        ).model_dump()
        payload["desk_only"] = True  # already reference_only=True -- the contradiction
        with pytest.raises(ValueError, match=r"reference_only.*desk_only|desk_only.*reference_only"):
            StrategyCard.model_validate(payload)

    def test_a_round_refuses_a_reference_only_card(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.tournament import jobs

        reference = promotion.build_card(_survivor(_thesis(max_holding_bars=40)), catalogue=author.CATALOGUE)
        normal = StrategyCard(
            agent_id="N-normal",
            display_name="normal",
            discipline=Discipline.TREND,
            thesis="t",
            universe=("SPY",),
            entry="close > sma(50)",
            exit="close < sma(50)",
            max_positions=1,
            position_pct=__import__("decimal").Decimal("0.2"),
            designed_through=dt.date(2026, 2, 1),
        )
        index = {
            reference.agent_id: ("candidates", reference),
            normal.agent_id: ("candidates", normal),
        }
        monkeypatch.setattr(jobs, "_load_library_index", lambda: index)

        # Defaulted tier: the reference card is excluded, the normal one runs.
        field = jobs._resolve_cards([], "candidates")
        assert [c.agent_id for c in field] == ["N-normal"]

        # Named explicitly: refused, with a reason, not silently dropped.
        with pytest.raises(jobs.ReferenceOnlyCard):
            jobs._resolve_cards([reference.agent_id], "candidates")


# ---------------------------------------------------------------------------------------------
# The endpoint -- translation only, through the _default_* seams
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def client(settings: Settings) -> TestClient:
    # Depends on `settings` so the suite-wide auth-disable (INVDASH_AUTH_ENABLED=0, set by that
    # fixture) is in effect -- without it every request 401s at the gate before reaching the route.
    return TestClient(app)


class _FakeLedger:
    def __init__(self, records: list[ThesisRecord]) -> None:
        self._records = records

    def records_for(self, symbol: str, *, settings: object = None) -> list[ThesisRecord]:
        return list(self._records)


class _FakePromoter:
    def __init__(self, *, result: promotion.PromotionResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    def promote(self, record: ThesisRecord, *, position_pct: object, purpose: object, settings: object = None) -> promotion.PromotionResult:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def _install(monkeypatch: pytest.MonkeyPatch, *, ledger: _FakeLedger, promoter: _FakePromoter | None = None) -> None:
    monkeypatch.setattr(thesis_api, "_default_ledger", lambda: ledger)
    if promoter is not None:
        monkeypatch.setattr(thesis_api, "_default_promoter", lambda: promoter)


class TestPromoteEndpoint:
    def test_no_matching_survivor_is_404(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        _install(monkeypatch, ledger=_FakeLedger([]))
        resp = client.post("/api/thesis/promote", json={"symbol": "QQQ", "thesis_hash": "deadbeefcafe"})
        assert resp.status_code == 404

    def test_success_is_201_and_returns_the_card(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        record = _survivor(_thesis(max_holding_bars=40))
        card = promotion.build_card(record, catalogue=author.CATALOGUE)
        _install(
            monkeypatch,
            ledger=_FakeLedger([record]),
            promoter=_FakePromoter(result=promotion.PromotionResult(card=card, path=Path("x"), created=True)),
        )
        resp = client.post("/api/thesis/promote", json={"symbol": "QQQ", "thesis_hash": record.thesis_hash})
        assert resp.status_code == 201
        body = resp.json()
        assert body["agent_id"] == card.agent_id
        assert body["reference_only"] is True
        assert body["source_thesis_hash"] == record.thesis_hash

    def test_already_promoted_is_409(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        record = _survivor(_thesis(max_holding_bars=40))
        card = promotion.build_card(record, catalogue=author.CATALOGUE)
        _install(
            monkeypatch,
            ledger=_FakeLedger([record]),
            promoter=_FakePromoter(result=promotion.PromotionResult(card=card, path=Path("x"), created=False)),
        )
        resp = client.post("/api/thesis/promote", json={"symbol": "QQQ", "thesis_hash": record.thesis_hash})
        assert resp.status_code == 409

    def test_a_non_survivor_is_422(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        record = _survivor(verdict=Verdict.REJECTED)
        _install(
            monkeypatch,
            ledger=_FakeLedger([record]),
            promoter=_FakePromoter(error=promotion.NotASurvivor("not a survivor")),
        )
        resp = client.post("/api/thesis/promote", json={"symbol": "QQQ", "thesis_hash": record.thesis_hash})
        assert resp.status_code == 422

    def test_the_request_carries_no_rule_fields(self) -> None:
        # The safety contract: a caller identifies a survivor, it never describes one. No executable
        # DSL can enter through the request body.
        fields = set(thesis_api.PromoteRequest.model_fields)
        assert not (fields & {"entry", "exit", "universe", "stop_loss_pct", "rank_by"})
        assert fields == {"symbol", "thesis_hash", "position_pct", "purpose"}
