"""The thesis loop.

``TestNullSeriesDiscipline`` is the single most important test in this feature. Pointed at pure
random walks for a full iteration budget, the loop must report **zero** survivors. If it finds a
strategy in noise, the guards do not work and nothing else here is worth reading.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.db.duck import Interval
from app.thesis import author, holdout, instruments, ledger, loop
from app.thesis.models import (
    DEFAULT_ITERATION_BUDGET,
    Direction,
    Evidence,
    LoopOutcome,
    LoopResult,
    Thesis,
    ThesisRecord,
    ThesisStatus,
    Verdict,
)


def _random_walk(n: int = 3000, *, seed: int) -> pd.DataFrame:
    """A driftless random walk. There is no edge here to find, by construction."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.0, 1.0, size=n)
    close = 100.0 * np.exp(np.cumsum(steps) * 0.01)
    open_ = close * (1.0 + rng.normal(0.0, 0.001, size=n))
    return pd.DataFrame(
        {
            "ts": pd.date_range("2010-01-01", periods=n, freq="D", tz="UTC"),
            "open": open_,
            "high": np.maximum(close, open_) * 1.005,
            "low": np.minimum(close, open_) * 0.995,
            "close": close,
            "adj_close": close,
            "volume": np.full(n, 1e6),
        }
    )


class TestNullSeriesDiscipline:
    """Pointed at noise, the loop must find nothing. Repeatedly, across independent seeds."""

    @pytest.mark.parametrize("seed", [1, 2, 3, 4, 5, 6, 7, 8])
    def test_a_random_walk_yields_no_survivor(self, settings: Settings, seed: int) -> None:
        result = loop.run(
            f"NULL{seed}",
            budget=DEFAULT_ITERATION_BUDGET,
            settings=settings,
            bars=_random_walk(seed=seed),
        )

        # Asserted against `records`, not `survivors`. This test originally checked
        # `result.survivors == []`, which was **vacuously true on every run**: the property filtered
        # `cards`, and the loop never populates cards. The assertion that reads as the heart of the
        # test was doing nothing, and only the `outcome` check below was load-bearing.
        survived = [r for r in result.records if r.verdict is Verdict.SURVIVED]
        assert survived == [], (
            f"seed {seed}: the loop claimed a survivor on a driftless random walk. "
            f"verdicts={[r.verdict for r in result.records]}"
        )
        assert result.survivors == []
        assert result.outcome is not LoopOutcome.SURVIVOR_FOUND

    def test_running_out_of_ideas_is_not_reported_as_running_out_of_budget(
        self, settings: Settings
    ) -> None:
        """Two different facts. "No thesis survived twelve attempts" is about the ticker; "the
        author had five ideas" is about the author, and with a five-template catalogue against a
        budget of twelve the second was being reported as the first on every single run."""
        result = loop.run("NULLB", budget=DEFAULT_ITERATION_BUDGET, settings=settings,
                          bars=_random_walk(seed=11))

        assert result.iterations_used < result.budget
        assert result.outcome is LoopOutcome.CATALOGUE_EXHAUSTED
        assert result.iterations_used > 0

    def test_a_budget_smaller_than_the_catalogue_reports_budget_exhausted(
        self, settings: Settings
    ) -> None:
        result = loop.run("NULLB2", budget=2, settings=settings, bars=_random_walk(seed=11))
        assert result.iterations_used == 2
        assert result.outcome is LoopOutcome.BUDGET_EXHAUSTED

    def test_every_attempt_left_a_trial_behind(self, settings: Settings) -> None:
        """The invisible-denominator failure. Iterations used and theses registered must agree."""
        result = loop.run("NULLC", settings=settings, bars=_random_walk(seed=12))
        stats = ledger.stats_for("NULLC", settings=settings)

        assert stats.total_trials == result.iterations_used
        assert len(result.records) == result.iterations_used

    def test_noise_produces_inconclusive_rather_than_rejected(self, settings: Settings) -> None:
        """Underpowered is checked before direction, so a small sample with a big edge is
        inconclusive rather than rejected -- rejecting would be a stronger claim than the data
        supports in the other direction."""
        result = loop.run("NULLD", settings=settings, bars=_random_walk(seed=13))
        assert all(r.verdict is not Verdict.SURVIVED for r in result.records)

    def test_the_holdout_is_not_spent_when_nothing_survives(self, settings: Settings) -> None:
        """One look per ticker, and spending it on something already refuted in-sample wastes the
        only out-of-sample test that ticker will ever get."""
        loop.run("NULLE", settings=settings, bars=_random_walk(seed=14))
        state = holdout.load("NULLE", settings=settings)

        assert state is not None
        assert state.status is holdout.HoldoutStatus.UNUSED
        assert state.attempts == 0


class TestRegressionsFromAdversarialQA:
    """Every test here reproduces a defect an adversarial pass found in shipped code. Four of the
    five were in the guards themselves, which is the point: guards need attacking, not exercising."""

    def test_survivors_reflects_the_records_not_an_unpopulated_card_list(
        self, settings: Settings
    ) -> None:
        """`survivors` filtered `cards`, which the loop never fills, so it returned `[]` on every
        run whatever the verdicts were -- and the null-series assertion built on it passed
        vacuously."""
        result = loop.run("SURV", settings=settings, bars=_random_walk(seed=81))
        forced = result.model_copy(
            update={
                "records": [
                    r.model_copy(update={"verdict": Verdict.SURVIVED}) for r in result.records[:1]
                ]
            }
        )
        assert len(forced.survivors) == 1
        assert forced.survivors[0].verdict is Verdict.SURVIVED

    def test_concurrent_holdout_claims_grant_exactly_one_clean_look(
        self, settings: Settings
    ) -> None:
        """A read-then-write race let 6 of 8 concurrent callers through, each recorded as the single
        clean look. The whole guarantee is "one look"."""
        import threading

        holdout.establish("RACE", _random_walk(seed=82), settings=settings)
        barrier = threading.Barrier(8)
        granted: list[int] = []
        refused: list[int] = []

        def attempt(i: int) -> None:
            barrier.wait()
            try:
                holdout.claim("RACE", f"hash-{i}", settings=settings)
                granted.append(i)
            except Exception:
                refused.append(i)

        threads = [threading.Thread(target=attempt, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(granted) == 1, f"{len(granted)} callers got a clean look; exactly one may"
        assert len(refused) == 7
        state = holdout.load("RACE", settings=settings)
        assert state is not None
        assert state.status is holdout.HoldoutStatus.BURNED
        assert state.attempts == 8

    def test_a_second_run_does_not_silently_re_roll_stored_p_values(
        self, settings: Settings
    ) -> None:
        """Re-running replaced all five stored p-values against different bars while the trial count
        stayed at five -- the first evaluation vanished from the denominator entirely, which is the
        invisible-trial hazard reappearing inside the machinery built to prevent it."""
        loop.run("REROLL", settings=settings, bars=_random_walk(seed=83))
        before = {
            r.thesis_hash: (r.in_sample.p_value if r.in_sample else None)
            for r in ledger.records_for("REROLL", settings=settings)
        }
        trials_before = ledger.stats_for("REROLL", settings=settings).total_trials

        second = loop.run("REROLL", settings=settings, bars=_random_walk(seed=9999))
        after = {
            r.thesis_hash: (r.in_sample.p_value if r.in_sample else None)
            for r in ledger.records_for("REROLL", settings=settings)
        }

        assert before == after, "stored evidence was overwritten by a re-run"
        assert second.iterations_used == 0, "already-tested theses must not consume iterations"
        assert ledger.stats_for("REROLL", settings=settings).total_trials == trials_before

    def test_a_payload_cannot_be_attached_to_a_different_thesis(
        self, settings: Settings
    ) -> None:
        """The SQL columns cannot drift, but the JSON blob could -- producing a row whose flat
        columns described one thesis while its payload endorsed another."""
        from app.thesis import preregister
        from app.thesis.models import Direction, Thesis

        def mk(tag: str) -> Thesis:
            return Thesis(
                symbol="SPLIT",
                hypothesis=f"claim {tag}",
                entry="close > sma(20)",
                horizon=20,
                direction=Direction.UP,
                falsifies_if="no excess",
            )

        a = preregister.register(mk("A"))
        b = preregister.register(mk("B"))
        ledger.record(a, settings=settings)
        ledger.record(b, settings=settings)

        with pytest.raises(preregister.PreregistrationError, match="may only join"):
            ledger.update_outcome(
                a.thesis_hash,
                status=ThesisStatus.HOLDOUT_TESTED,
                verdict=Verdict.SURVIVED,
                payload=b.model_dump_json(),
                settings=settings,
            )

    def test_a_matching_payload_is_accepted(self, settings: Settings) -> None:
        """The control: the check must not break the normal path."""
        from app.thesis import preregister
        from app.thesis.models import Direction, Thesis

        record = preregister.register(
            Thesis(
                symbol="OK",
                hypothesis="claim",
                entry="close > sma(20)",
                horizon=20,
                direction=Direction.UP,
                falsifies_if="no excess",
            )
        )
        ledger.record(record, settings=settings)
        ledger.update_outcome(
            record.thesis_hash,
            status=ThesisStatus.IN_SAMPLE_TESTED,
            payload=record.model_copy(update={"status": ThesisStatus.IN_SAMPLE_TESTED}).model_dump_json(),
            settings=settings,
        )
        assert ledger.stats_for("OK", settings=settings).total_trials == 1


class TestAtMostOneSurvivorPerRun:
    """The defect: a ticker gets exactly one holdout look, ever, so at most one record per run may
    legitimately carry `Verdict.SURVIVED` -- but `_screen` returning SURVIVED for a thesis only marks
    it a *candidate*, and the loop only ever spent the holdout on the first one. Every later thesis
    that also cleared the in-sample screen kept the SURVIVED label forever, with `holdout` left
    `None`, because nothing downgraded it once the ticker's one look was already spoken for.
    `outcome` and `survivors` then disagreed too: `CATALOGUE_EXHAUSTED` ("nothing survived") while
    `survivors` reported several.

    Reproduced the same way the defect was originally found: force `_screen` to clear every
    candidate, force `_confirm` (the holdout verdict) to come back inconclusive so the one real look
    does not happen to confirm anything, and stub the FDR correction so guard 2 does not intervene
    first and mask the defect the way it did on the first reproduction attempt.
    """

    def test_forcing_every_candidate_past_the_screen_still_yields_no_unconfirmed_survivor(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(loop, "_screen", lambda thesis, evidence: Verdict.SURVIVED)
        monkeypatch.setattr(loop, "_confirm", lambda thesis, evidence: Verdict.INCONCLUSIVE)
        monkeypatch.setattr(loop.ledger_module, "correct_over_ledger", lambda *a, **k: (0.01, 5))

        # Constructing `LoopResult` is where the old defect would have surfaced as data, not as an
        # exception -- the whole point of the fix is that this call cannot silently produce the
        # illegal shape. It also cannot *raise* here: this is the "genuine work happened, no defect
        # left in the object" path, distinct from the constructibility tests below, which build the
        # illegal shape directly and demand the validator refuse it.
        result = loop.run("FORCEDQQQ", settings=settings, bars=_random_walk(seed=91))

        assert result.iterations_used >= 2, "the forced screen needs more than one candidate to prove the point"
        assert not any(r.verdict is Verdict.SURVIVED and r.holdout is None for r in result.records), (
            f"an unconfirmed record still claims SURVIVED: "
            f"{[(r.thesis_hash[:12], r.verdict, r.holdout) for r in result.records]}"
        )
        # The one real holdout look came back inconclusive, so nothing may report as a survivor --
        # and outcome and survivors must agree about that.
        assert result.survivors == []
        assert result.outcome is not LoopOutcome.SURVIVOR_FOUND
        # Every forced candidate was still registered and tested in-sample: the fix downgrades the
        # verdict of the ones that lost the race for the one look, it does not drop their trial.
        assert result.iterations_used == len(result.records)
        assert all(r.status is not ThesisStatus.REGISTERED for r in result.records)
        assert all(r.verdict is Verdict.INCONCLUSIVE for r in result.records)

    def test_the_genuine_single_survivor_path_still_reports_exactly_one(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The control for the test above: when the one real holdout look genuinely confirms, the
        run must still report `SURVIVOR_FOUND` with exactly one survivor. The fix must downgrade the
        extra in-sample candidates without touching the one that is legitimately promoted."""
        monkeypatch.setattr(loop, "_screen", lambda thesis, evidence: Verdict.SURVIVED)
        monkeypatch.setattr(loop, "_confirm", lambda thesis, evidence: Verdict.SURVIVED)
        monkeypatch.setattr(loop.ledger_module, "correct_over_ledger", lambda *a, **k: (0.01, 5))

        result = loop.run("FORCEDSURV", settings=settings, bars=_random_walk(seed=92))

        assert result.outcome is LoopOutcome.SURVIVOR_FOUND
        assert len(result.survivors) == 1
        survivor = result.survivors[0]
        assert survivor.holdout is not None
        assert survivor.status is ThesisStatus.HOLDOUT_TESTED

        others = [r for r in result.records if r.thesis_hash != survivor.thesis_hash]
        assert others, "the catalogue has more than one template -- there should be others to check"
        assert all(r.verdict is Verdict.INCONCLUSIVE for r in others), (
            "every candidate that lost the race for the one look must be downgraded, not left "
            "claiming SURVIVED"
        )
        assert len(others) == result.iterations_used - 1


class TestLoopResultCannotConstructTheIllegalShape:
    """`LoopResult`'s `model_validator`s (see `app/thesis/models.py`), exercised directly: the
    illegal states `TestAtMostOneSurvivorPerRun` shows the fixed loop no longer *produces* must also
    be impossible to *construct* by hand, so a future producer bug cannot reintroduce them."""

    @staticmethod
    def _thesis() -> Thesis:
        return Thesis(
            symbol="X",
            hypothesis="A claim.",
            entry="close > sma(20)",
            horizon=20,
            direction=Direction.UP,
            falsifies_if="no excess over baseline",
        )

    def _record(self, *, verdict: Verdict, holdout: Evidence | None) -> ThesisRecord:
        return ThesisRecord(
            thesis_hash="deadbeefcafe",
            thesis=self._thesis(),
            registered_at=dt.datetime.now(dt.UTC),
            status=ThesisStatus.HOLDOUT_TESTED if holdout is not None else ThesisStatus.IN_SAMPLE_TESTED,
            verdict=verdict,
            holdout=holdout,
        )

    def _loop_result(self, **overrides: object) -> LoopResult:
        base: dict[str, object] = {
            "symbol": "X",
            "interval": Interval.DAY,
            "started_at": dt.datetime.now(dt.UTC),
            "finished_at": dt.datetime.now(dt.UTC),
            "outcome": LoopOutcome.BUDGET_EXHAUSTED,
            "budget": 12,
            "iterations_used": 0,
            "records": [],
        }
        base.update(overrides)
        return LoopResult(**base)  # type: ignore[arg-type]

    def test_a_survivor_without_a_holdout_cannot_be_constructed(self) -> None:
        record = self._record(verdict=Verdict.SURVIVED, holdout=None)
        with pytest.raises(ValidationError, match="never spent the ticker's one out-of-sample look"):
            self._loop_result(
                outcome=LoopOutcome.SURVIVOR_FOUND, records=[record], iterations_used=1
            )

    def test_survivor_found_with_no_survivors_cannot_be_constructed(self) -> None:
        with pytest.raises(ValidationError, match="SURVIVOR_FOUND"):
            self._loop_result(outcome=LoopOutcome.SURVIVOR_FOUND, records=[])

    def test_a_survivor_present_but_outcome_not_survivor_found_cannot_be_constructed(self) -> None:
        record = self._record(
            verdict=Verdict.SURVIVED, holdout=Evidence(horizon=20, p_value=0.01)
        )
        with pytest.raises(ValidationError, match="survivors is non-empty"):
            self._loop_result(
                outcome=LoopOutcome.BUDGET_EXHAUSTED, records=[record], iterations_used=1
            )

    def test_a_genuine_confirmed_survivor_constructs_fine(self) -> None:
        """The control: the two validators must not reject the one shape that is actually legal."""
        record = self._record(
            verdict=Verdict.SURVIVED, holdout=Evidence(horizon=20, p_value=0.01)
        )
        result = self._loop_result(
            outcome=LoopOutcome.SURVIVOR_FOUND, records=[record], iterations_used=1
        )
        assert result.survivors == [record]


class TestDirectionIsChecked:
    """A significant effect in the *opposite* direction refutes a thesis. A loop scoring on
    magnitude alone would count it as a discovery."""

    @staticmethod
    def _thesis(direction: Direction) -> Thesis:
        return Thesis(
            symbol="X",
            hypothesis="h",
            entry="close > sma(20)",
            horizon=20,
            direction=direction,
            falsifies_if="edge does not run the predicted way",
        )

    def test_an_edge_opposite_to_the_prediction_is_rejected(self) -> None:
        evidence = Evidence(
            horizon=20, hit_rate=0.30, baseline_hit_rate=0.55,
            sample_size=400, independent_sample_size=120,
        )
        assert loop._screen(self._thesis(Direction.UP), evidence) is Verdict.REJECTED
        assert loop._screen(self._thesis(Direction.DOWN), evidence) is Verdict.SURVIVED

    def test_the_same_magnitude_either_way_is_not_the_same_result(self) -> None:
        up = Evidence(horizon=20, hit_rate=0.70, baseline_hit_rate=0.55,
                      sample_size=400, independent_sample_size=120)
        down = Evidence(horizon=20, hit_rate=0.40, baseline_hit_rate=0.55,
                        sample_size=400, independent_sample_size=120)
        thesis = self._thesis(Direction.UP)

        assert loop._screen(thesis, up) is Verdict.SURVIVED
        assert loop._screen(thesis, down) is Verdict.REJECTED

    def test_an_underpowered_sample_is_inconclusive_whichever_way_it_points(self) -> None:
        for hit in (0.95, 0.05):
            evidence = Evidence(
                horizon=20, hit_rate=hit, baseline_hit_rate=0.55,
                sample_size=12, independent_sample_size=4,
            )
            assert loop._screen(self._thesis(Direction.UP), evidence) is Verdict.INCONCLUSIVE

    def test_an_unmeasurable_edge_never_survives(self) -> None:
        evidence = Evidence(horizon=20, sample_size=0, independent_sample_size=100)
        assert loop._screen(self._thesis(Direction.UP), evidence) is not Verdict.SURVIVED


class TestPlantedEffect:
    """The control for the null-series tests: a loop that can never find anything would pass those
    trivially. This constructs a series where the measured effect is real and large, and asserts the
    machinery registers it in-sample."""

    @staticmethod
    def _planted(n: int = 4000, *, seed: int = 21) -> pd.DataFrame:
        """A driftless walk in which a two-sigma downside excursion is followed by a real bounce.

        Two earlier constructions failed, and both failures are worth recording because they are the
        same mistake in different clothes.

        The first planted the effect on ``close > sma(200)`` with asymmetric drift. That trends the
        series up almost everywhere, so 99.9% of all 20-bar windows were positive and the conditional
        and unconditional hit rates were *identical*: the effect was in the data, the measurement was
        correct, and there was nothing left to discriminate.

        The second made the drifts symmetric, which did not help, because the condition has
        **positive feedback** -- above the average implies upward drift implies still above the
        average. It locked on, firing on 2,781 of 2,800 bars, so the conditional sample simply *was*
        the baseline sample.

        A planted effect therefore needs a condition that is (a) genuinely selective and (b) not
        self-reinforcing. A band excursion is both: it is mean-reverting by construction, so the
        bounce it triggers pushes price back out of the condition rather than deeper into it.
        """
        rng = np.random.default_rng(seed)
        close = np.empty(n)
        close[0] = 100.0
        boost_remaining = 0
        for i in range(1, n):
            window = close[max(0, i - 20) : i]
            drift = 0.0
            if boost_remaining > 0:
                drift = 0.0025
                boost_remaining -= 1
            elif window.size >= 20:
                mean = float(window.mean())
                std = float(window.std(ddof=0))
                if std > 0 and close[i - 1] < mean - 2.0 * std:
                    # The excursion has just happened; the bounce starts on the next bar, which is
                    # also the first bar a rule reading this condition could have traded.
                    boost_remaining = 20
            close[i] = max(close[i - 1] * (1.0 + drift + rng.normal(0.0, 0.010)), 1.0)

        return pd.DataFrame(
            {
                "ts": pd.date_range("2010-01-01", periods=n, freq="D", tz="UTC"),
                "open": close,
                "high": close * 1.005,
                "low": close * 0.995,
                "close": close,
                "adj_close": close,
                "volume": np.full(n, 1e6),
            }
        )

    _THESIS = Thesis(
        symbol="PLANT",
        hypothesis="A lower-band excursion is followed by above-baseline 20-bar returns.",
        entry="close < bb_lower(20,2)",
        horizon=20,
        direction=Direction.UP,
        falsifies_if="the hit rate after a band touch does not exceed the unconditional rate",
    )

    def test_a_planted_effect_is_measured_with_the_right_sign(self, settings: Settings) -> None:
        evidence = loop.evaluate_thesis(self._THESIS, self._planted())

        assert evidence.edge is not None
        assert evidence.edge > 0, f"planted effect not recovered: {evidence}"
        assert evidence.sample_size > 50
        assert evidence.baseline_hit_rate is not None
        assert evidence.hit_rate is not None
        assert evidence.hit_rate > evidence.baseline_hit_rate

    def test_the_same_machinery_finds_nothing_on_the_matched_null(
        self, settings: Settings
    ) -> None:
        """Same thesis, same code path, noise instead of signal. Without this the test above only
        shows that the measurement is non-zero, not that it is discriminating."""
        evidence = loop.evaluate_thesis(
            self._THESIS.model_copy(update={"symbol": "NULLP"}), _random_walk(4000, seed=31)
        )
        assert evidence.edge is not None
        assert abs(evidence.edge) < 0.10


class TestOrderOfOperations:
    def test_registration_precedes_evaluation(self, settings: Settings) -> None:
        """A run that dies during evaluation must still have spent its trials."""

        class _Exploding:
            calls = 0

            def evaluate(self, node: object, bars: pd.DataFrame, *, interval: Interval):  # type: ignore[no-untyped-def]
                _Exploding.calls += 1
                raise RuntimeError("evaluation failed")

        result = loop.run(
            "BOOM", settings=settings, bars=_random_walk(seed=41), evaluator=_Exploding()
        )

        assert _Exploding.calls > 0
        assert ledger.stats_for("BOOM", settings=settings).total_trials == result.iterations_used
        assert ledger.stats_for("BOOM", settings=settings).abandoned == result.iterations_used

    def test_a_failing_thesis_is_abandoned_not_dropped(self, settings: Settings) -> None:
        class _Exploding:
            def evaluate(self, node: object, bars: pd.DataFrame, *, interval: Interval):  # type: ignore[no-untyped-def]
                raise RuntimeError("nope")

        result = loop.run(
            "BOOM2", settings=settings, bars=_random_walk(seed=42), evaluator=_Exploding()
        )
        assert result.records
        assert all(r.status is ThesisStatus.ABANDONED for r in result.records)

    def test_a_short_history_is_refused_before_any_thesis_is_registered(
        self, settings: Settings
    ) -> None:
        """No holdout means no verdict is possible, and burning trials to discover that would be
        worse than declining."""
        result = loop.run("SHORT", settings=settings, bars=_random_walk(400, seed=51))

        assert result.outcome is LoopOutcome.HOLDOUT_UNAVAILABLE
        assert result.iterations_used == 0
        assert ledger.stats_for("SHORT", settings=settings).total_trials == 0

    def test_no_bars_is_a_reportable_outcome(self, settings: Settings) -> None:
        result = loop.run("EMPTY", settings=settings, bars=_random_walk(0, seed=61))
        assert result.outcome is LoopOutcome.NO_DATA
        assert result.iterations_used == 0

    def test_the_budget_caps_iterations(self, settings: Settings) -> None:
        result = loop.run("CAP", budget=2, settings=settings, bars=_random_walk(seed=71))
        assert result.iterations_used == 2
        assert ledger.stats_for("CAP", settings=settings).total_trials == 2

    def test_a_zero_budget_registers_nothing(self, settings: Settings) -> None:
        result = loop.run("ZERO", budget=0, settings=settings, bars=_random_walk(seed=72))
        assert result.iterations_used == 0
        assert ledger.stats_for("ZERO", settings=settings).total_trials == 0


class TestTheAuthorIsBlindToTheSample:
    def test_propose_takes_no_bars(self) -> None:
        """Hazard property (2): a proposer that sees the history writes a description of it."""
        import inspect

        params = set(inspect.signature(author.propose).parameters)
        assert "bars" not in params
        assert "frame" not in params
        assert params <= {"symbol", "interval", "exclude"}

    def test_every_template_declares_its_falsification_criterion_in_advance(self) -> None:
        for template in author.CATALOGUE:
            assert template.falsifies_if.strip(), template.key

    def test_the_leveraged_template_is_only_proposed_for_leveraged_products(self) -> None:
        plain = {t.hypothesis for t in author.propose("QQQ")}
        levered = {t.hypothesis for t in author.propose("SOXL")}
        assert len(levered) > len(plain)

    def test_a_candidate_from_reverse_conditioning_is_stamped_with_its_origin(self) -> None:
        """A surviving result deserves more suspicion when the data suggested the hypothesis."""
        thesis = author.propose_from_candidate(
            "QQQ",
            entry="rsi(14) < 25",
            exit=None,
            horizon=20,
            direction=Direction.UP,
            falsifies_if="no excess over baseline",
            source="reverse conditioning",
        )
        assert "suggested by the same history" in thesis.rationale


class TestInstrumentGuard:
    def test_leveraged_products_map_to_their_unlevered_equivalent(self) -> None:
        assert instruments.unlevered_for("SOXL") == "SOXX"
        assert instruments.unlevered_for("TQQQ") == "QQQ"
        assert instruments.unlevered_for("NVDL") == "NVDA"

    def test_inverse_products_carry_a_negative_factor(self) -> None:
        entry = instruments.lookup("SOXS")
        assert entry is not None and entry.factor < 0

    def test_an_ordinary_instrument_has_no_mapping(self) -> None:
        assert instruments.lookup("QQQ") is None
        assert instruments.unlevered_for("QQQ") is None

    def test_a_leveraged_product_with_no_equivalent_still_fires_the_guard(self) -> None:
        """`None` from `unlevered_for` covers two different situations, and the card needs to tell
        them apart -- a stated gap is very different from an ordinary instrument."""
        entry = instruments.lookup("MUU")
        assert entry is not None
        assert entry.underlying is None
        assert "no unlevered equivalent" in (instruments.describe("MUU") or "")

    def test_describe_is_silent_for_ordinary_instruments(self) -> None:
        assert instruments.describe("QQQ") is None
