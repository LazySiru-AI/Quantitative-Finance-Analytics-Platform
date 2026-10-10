"""The four guards, tested by trying to get around them.

Every test here constructs the manipulation the guard exists to prevent and demands it fail. A guard
that has only been shown well-behaved input has not been tested.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.config import Settings
from app.db.duck import Interval
from app.thesis import holdout, ledger, preregister
from app.thesis.models import (
    Direction,
    Evidence,
    HoldoutStatus,
    Thesis,
    ThesisStatus,
    Verdict,
)


def _thesis(**overrides: object) -> Thesis:
    base: dict[str, object] = {
        "symbol": "QQQ",
        "interval": Interval.DAY,
        "hypothesis": "A lower-band touch precedes a bounce.",
        "entry": "close < bb_lower(20,2)",
        "exit": "close > sma(20)",
        "horizon": 20,
        "direction": Direction.UP,
        "falsifies_if": "hit rate does not exceed the unconditional baseline by 5 points",
        "rationale": "Mean reversion in a range-bound index.",
    }
    base.update(overrides)
    return Thesis(**base)  # type: ignore[arg-type]


def _bars(n: int = 2000, *, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + rng.normal(0.0, 1.0, size=n).cumsum()
    close = np.maximum(close, 5.0)
    return pd.DataFrame(
        {
            "ts": pd.date_range("2015-01-01", periods=n, freq="D", tz="UTC"),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "adj_close": close,
            "volume": np.full(n, 1e6),
        }
    )


# ---------------------------------------------------------------------------
# Guard 1: pre-registration
# ---------------------------------------------------------------------------


class TestPreregistration:
    def test_the_same_claim_hashes_the_same_every_time(self) -> None:
        assert preregister.content_hash(_thesis()) == preregister.content_hash(_thesis())

    @pytest.mark.parametrize(
        "field,value",
        [
            ("hypothesis", "A lower-band touch precedes a decline."),
            ("entry", "close < bb_lower(20,3)"),
            ("exit", "close > sma(50)"),
            ("horizon", 5),
            ("direction", Direction.DOWN),
            ("falsifies_if", "hit rate does not exceed baseline by 10 points"),
            ("max_holding_bars", 30),
            ("stop_loss_pct", 0.1),
            ("symbol", "SPY"),
        ],
    )
    def test_changing_any_part_of_the_claim_is_a_different_thesis(
        self, field: str, value: object
    ) -> None:
        """This is the whole mechanism. Move the horizon after seeing the numbers and you have a new
        hash, a new record, and another trial -- there is no edit path."""
        assert preregister.content_hash(_thesis()) != preregister.content_hash(
            _thesis(**{field: value})
        )

    def test_rewording_the_rationale_is_not_a_new_thesis(self) -> None:
        """The one field that is commentary rather than claim. Hashing it would charge a trial for a
        cosmetic edit, which teaches people to leave it blank."""
        assert preregister.content_hash(_thesis()) == preregister.content_hash(
            _thesis(rationale="Completely different explanation of the same claim.")
        )

    def test_whitespace_in_a_hypothesis_is_not_a_new_thesis(self) -> None:
        """A trailing newline is a typo, not a claim. Charging a trial for pressing return would be
        the guard behaving as an obstacle rather than a control."""
        assert preregister.content_hash(_thesis(hypothesis="A  touch\n precedes a bounce.")) == (
            preregister.content_hash(_thesis(hypothesis="A touch precedes a bounce."))
        )

    def test_a_thesis_without_a_falsification_criterion_cannot_be_constructed(self) -> None:
        """A hypothesis that cannot say what would refute it is not one, and asking after the numbers
        arrive gets a criterion tuned to pass."""
        for blank in ("", "   ", "\n\t"):
            with pytest.raises(ValueError, match="falsifies_if"):
                _thesis(falsifies_if=blank)

    def test_a_registered_record_starts_with_no_results(self) -> None:
        """Registration precedes testing. A record that could arrive with evidence attached would
        make the ordering a convention rather than a mechanism."""
        record = preregister.register(_thesis())
        assert record.status is ThesisStatus.REGISTERED
        assert record.in_sample is None
        assert record.holdout is None
        assert record.verdict is None

    def test_tampering_with_a_registered_thesis_is_detected(self) -> None:
        """Constructed by hand, because `Thesis` is frozen and the normal path cannot produce it --
        which is exactly why the check belongs at the boundary where results get attached."""
        record = preregister.register(_thesis())
        tampered = record.model_copy(update={"thesis": _thesis(horizon=5)})

        with pytest.raises(preregister.PreregistrationError, match="new thesis"):
            preregister.verify_unmodified(tampered)

    def test_an_untampered_record_verifies(self) -> None:
        preregister.verify_unmodified(preregister.register(_thesis()))

    def test_the_hashed_field_list_covers_every_claim_field(self) -> None:
        """A field added to `Thesis` must be a deliberate decision about whether it is part of the
        claim. This fails when someone adds one without making that decision."""
        claim_fields = set(Thesis.model_fields) - {"rationale"}
        assert claim_fields == set(preregister.HASHED_FIELDS)


# ---------------------------------------------------------------------------
# Guard 2: the global trial ledger
# ---------------------------------------------------------------------------


class TestTrialLedger:
    def test_a_ticker_with_no_history_reports_zero_not_none(self, settings: Settings) -> None:
        stats = ledger.stats_for("QQQ", settings=settings)
        assert stats.total_trials == 0
        assert stats.symbol == "QQQ"

    def test_registering_counts_a_trial_before_anything_is_tested(
        self, settings: Settings
    ) -> None:
        """The property that makes an abandoned run leave its trial behind."""
        ledger.record(preregister.register(_thesis()), settings=settings)
        assert ledger.stats_for("QQQ", settings=settings).total_trials == 1

    def test_registering_the_same_thesis_twice_is_one_trial(self, settings: Settings) -> None:
        """Otherwise re-running an identical thesis inflates its own denominator and makes the
        correction harsher every time someone presses the button."""
        for _ in range(3):
            ledger.record(preregister.register(_thesis()), settings=settings)
        assert ledger.stats_for("QQQ", settings=settings).total_trials == 1

    def test_abandoned_theses_still_count(self, settings: Settings) -> None:
        """The invisible-denominator failure this package is built around."""
        record = preregister.register(_thesis())
        ledger.record(record, settings=settings)
        ledger.update_outcome(
            record.thesis_hash, status=ThesisStatus.ABANDONED, settings=settings
        )

        stats = ledger.stats_for("QQQ", settings=settings)
        assert stats.total_trials == 1
        assert stats.abandoned == 1

    def test_the_denominator_survives_a_restart(self, settings: Settings) -> None:
        """Each call opens and closes its own connection, so this is a genuine round trip through
        the file rather than through process memory."""
        for i in range(5):
            ledger.record(preregister.register(_thesis(horizon=i + 1)), settings=settings)
        assert ledger.stats_for("QQQ", settings=settings).total_trials == 5
        assert ledger.stats_for("QQQ", settings=settings).total_trials == 5

    def test_trials_are_scoped_per_ticker(self, settings: Settings) -> None:
        ledger.record(preregister.register(_thesis(symbol="QQQ")), settings=settings)
        ledger.record(preregister.register(_thesis(symbol="SPY")), settings=settings)
        assert ledger.stats_for("QQQ", settings=settings).total_trials == 1
        assert ledger.stats_for("SPY", settings=settings).total_trials == 1

    def test_an_outcome_update_cannot_change_the_claim(self, settings: Settings) -> None:
        """The update statement has no columns for the hypothesis, the rules or the criterion.
        Attaching a result must never be a path by which the claim moves."""
        record = preregister.register(_thesis())
        ledger.record(record, settings=settings)
        ledger.update_outcome(
            record.thesis_hash,
            status=ThesisStatus.HOLDOUT_TESTED,
            verdict=Verdict.REJECTED,
            settings=settings,
        )

        stored = ledger.records_for("QQQ", settings=settings)[0]
        assert stored.thesis.hypothesis == _thesis().hypothesis
        assert stored.thesis_hash == record.thesis_hash

    def test_the_fortieth_q_value_reflects_the_thirty_nine_before_it(
        self, settings: Settings
    ) -> None:
        """The headline property. The same p-value gets a harsher q-value in a bigger family, and
        the family is everything ever registered for the ticker -- not this session."""
        record = preregister.register(_thesis(horizon=1))
        ledger.record(record, settings=settings)
        ledger.update_outcome(
            record.thesis_hash, status=ThesisStatus.IN_SAMPLE_TESTED, p_value=0.01,
            settings=settings,
        )

        q_small, m_small = ledger.correct_over_ledger(
            "QQQ", 0.01, thesis_hash=record.thesis_hash, settings=settings
        )

        for i in range(2, 41):
            other = preregister.register(_thesis(horizon=i))
            ledger.record(other, settings=settings)
            ledger.update_outcome(
                other.thesis_hash, status=ThesisStatus.IN_SAMPLE_TESTED, p_value=0.5,
                settings=settings,
            )

        q_large, m_large = ledger.correct_over_ledger(
            "QQQ", 0.01, thesis_hash=record.thesis_hash, settings=settings
        )

        assert m_small == 1
        assert m_large == 40
        assert q_large is not None and q_small is not None
        assert q_large > q_small

    def test_a_candidate_is_never_counted_twice_in_its_own_family(
        self, settings: Settings
    ) -> None:
        """The defect this API shape exists to prevent: an earlier version guessed the candidate's
        slot by looking for a NULL p-value, so a thesis whose outcome had already been written got
        appended as a second trial and inflated `m` on every run."""
        record = preregister.register(_thesis())
        ledger.record(record, settings=settings)
        ledger.update_outcome(
            record.thesis_hash, status=ThesisStatus.IN_SAMPLE_TESTED, p_value=0.01,
            settings=settings,
        )

        _, family = ledger.correct_over_ledger(
            "QQQ", 0.01, thesis_hash=record.thesis_hash, settings=settings
        )
        assert family == 1
        assert ledger.stats_for("QQQ", settings=settings).total_trials == 1

    def test_untestable_trials_still_swell_the_denominator(self, settings: Settings) -> None:
        """An abandoned thesis has no p-value and still consumed a slot. Excluding it would shrink
        the denominator every other q-value depends on."""
        pending = preregister.register(_thesis(horizon=1))
        ledger.record(pending, settings=settings)
        _, m_before = ledger.correct_over_ledger(
            "QQQ", 0.02, thesis_hash=pending.thesis_hash, settings=settings
        )

        for i in range(2, 12):
            abandoned = preregister.register(_thesis(horizon=i))
            ledger.record(abandoned, settings=settings)
            ledger.update_outcome(
                abandoned.thesis_hash, status=ThesisStatus.ABANDONED, settings=settings
            )

        q_after, m_after = ledger.correct_over_ledger(
            "QQQ", 0.02, thesis_hash=pending.thesis_hash, settings=settings
        )
        assert m_before == 1
        assert m_after == 11
        assert q_after is not None and q_after > 0.02

    def test_a_candidate_fills_its_own_slot_rather_than_appending_a_duplicate(
        self, settings: Settings
    ) -> None:
        """Registration precedes testing, so the candidate is already in the family. Appending it
        again would inflate `m` by one on every run, which compounds."""
        record = preregister.register(_thesis())
        ledger.record(record, settings=settings)
        _, family = ledger.correct_over_ledger(
            "QQQ", 0.03, thesis_hash=record.thesis_hash, settings=settings
        )
        assert family == 1

    def test_an_unidentified_candidate_is_appended_rather_than_guessed_at(
        self, settings: Settings
    ) -> None:
        """Omitting the hash means "this p-value has no row yet", and appending is the correct
        answer. The old guessing behaviour is gone: it silently mis-slotted an identified candidate,
        which is worse than being asked to say which one it is."""
        record = preregister.register(_thesis())
        ledger.record(record, settings=settings)
        _, family = ledger.correct_over_ledger("QQQ", 0.03, settings=settings)
        assert family == 2

    def test_the_research_ledger_is_not_the_brokerage_ledger(self, settings: Settings) -> None:
        """A research feature must not be able to write anywhere near the user's real transactions."""
        assert ledger.ledger_path(settings) != settings.ledger_path
        assert ledger.ledger_path(settings).name == "thesis.sqlite"


# ---------------------------------------------------------------------------
# Guard 3: the locked holdout
# ---------------------------------------------------------------------------


class TestHoldout:
    def test_the_split_reserves_the_tail(self, settings: Settings) -> None:
        bars = _bars(2000)
        split_date = holdout.split(bars)
        in_sample, out = holdout.split_frame(bars, split_date)

        assert len(in_sample) + len(out) == len(bars)
        assert len(out) == pytest.approx(2000 * holdout.HOLDOUT_FRACTION, abs=2)
        assert in_sample["ts"].max() < out["ts"].min()

    def test_a_short_history_is_refused_rather_than_split_thinly(self) -> None:
        """A holdout result computed over eleven bars reads like confirmation and carries none."""
        with pytest.raises(holdout.HoldoutUnavailable, match="under the"):
            holdout.split(_bars(400))

    def test_an_empty_history_is_refused(self) -> None:
        with pytest.raises(holdout.HoldoutUnavailable):
            holdout.split(_bars(0))

    def test_the_split_date_never_moves_once_set(self, settings: Settings) -> None:
        """Recomputing as history grows would slide the boundary forward, feeding previously
        held-out sessions into the in-sample period -- the guarantee would decay untouched."""
        first = holdout.establish("QQQ", _bars(2000), settings=settings)
        later = holdout.establish("QQQ", _bars(4000, seed=9), settings=settings)
        assert later.split_date == first.split_date

    def test_the_first_evaluation_is_permitted(self, settings: Settings) -> None:
        holdout.establish("QQQ", _bars(2000), settings=settings)
        state = holdout.claim("QQQ", "abc123", settings=settings)
        assert state.status is HoldoutStatus.SPENT
        assert state.attempts == 1

    def test_a_second_evaluation_is_refused_and_burns_the_holdout(
        self, settings: Settings
    ) -> None:
        """Refused *and recorded*. A refusal that leaves no trace produces a system where the stored
        result still looks clean to anyone who did not witness it."""
        holdout.establish("QQQ", _bars(2000), settings=settings)
        holdout.claim("QQQ", "abc123", settings=settings)

        with pytest.raises(holdout.HoldoutBurned, match="second look"):
            holdout.claim("QQQ", "def456", settings=settings)

        state = holdout.load("QQQ", settings=settings)
        assert state is not None
        assert state.status is HoldoutStatus.BURNED
        assert state.attempts == 2

    def test_the_burned_state_persists_and_keeps_counting(self, settings: Settings) -> None:
        holdout.establish("QQQ", _bars(2000), settings=settings)
        holdout.claim("QQQ", "a", settings=settings)
        for _ in range(3):
            with pytest.raises(holdout.HoldoutBurned):
                holdout.claim("QQQ", "b", settings=settings)

        state = holdout.load("QQQ", settings=settings)
        assert state is not None
        assert state.attempts == 4
        assert state.status is HoldoutStatus.BURNED

    def test_the_first_evaluations_thesis_is_remembered(self, settings: Settings) -> None:
        """So a later reader can see which thesis actually got the one clean look."""
        holdout.establish("QQQ", _bars(2000), settings=settings)
        holdout.claim("QQQ", "the-real-one", settings=settings)
        with pytest.raises(holdout.HoldoutBurned):
            holdout.claim("QQQ", "a-later-one", settings=settings)

        state = holdout.load("QQQ", settings=settings)
        assert state is not None
        assert state.evaluated_thesis_hash == "the-real-one"

    def test_holdouts_are_per_ticker(self, settings: Settings) -> None:
        holdout.establish("QQQ", _bars(2000), settings=settings)
        holdout.establish("SPY", _bars(2000, seed=3), settings=settings)
        holdout.claim("QQQ", "x", settings=settings)

        spy = holdout.load("SPY", settings=settings)
        assert spy is not None
        assert spy.status is HoldoutStatus.UNUSED

    def test_claiming_without_establishing_is_refused(self, settings: Settings) -> None:
        with pytest.raises(holdout.HoldoutUnavailable, match="no holdout"):
            holdout.claim("NOPE", "x", settings=settings)

    def test_describe_says_what_each_state_means(self, settings: Settings) -> None:
        """The UI must be able to render "this is compromised" without re-deriving it."""
        assert "never evaluated" in holdout.describe(
            holdout.establish("QQQ", _bars(2000), settings=settings)
        )
        holdout.claim("QQQ", "x", settings=settings)
        assert "no further out-of-sample test" in holdout.describe(
            holdout.load("QQQ", settings=settings)
        )
        with pytest.raises(holdout.HoldoutBurned):
            holdout.claim("QQQ", "y", settings=settings)
        assert "Treat its numbers as in-sample" in holdout.describe(
            holdout.load("QQQ", settings=settings)
        )
        assert "No holdout established" in holdout.describe(None)


class TestEvidenceShape:
    def test_edge_is_none_when_either_side_is_unmeasurable(self) -> None:
        assert Evidence(horizon=20, hit_rate=0.6).edge is None
        assert Evidence(horizon=20, baseline_hit_rate=0.5).edge is None
        assert Evidence(horizon=20, hit_rate=0.6, baseline_hit_rate=0.5).edge == pytest.approx(0.1)

    def test_a_q_value_records_the_family_it_was_corrected_over(self) -> None:
        """A q-value without its family size is not interpretable, and the family grows."""
        assert "trials_at_evaluation" in Evidence.model_fields


class TestCatalogueCriteriaStayWithinWhatIsMeasured:
    """Guard 1 records a falsification criterion; it does not execute one.

    `evaluate_thesis` measures the same thing for every thesis -- conditional hit rate against the
    instrument's unconditional baseline at the stated horizon, plus direction and sample size. It
    computes no drawdown, no Sharpe, no unlevered comparison. So a template whose hypothesis or
    criterion is *worded* in terms of one of those is scored on something other than what it claims,
    and the verdict does not answer the question asked.

    That is not hypothetical. `trend_following` and `decay_avoidance` both stated drawdown claims
    and were both scored on hit rate, and it survived review because the sentences read as though
    something had checked them. These assertions exist so that reopens loudly rather than silently.

    Extending the engine is the way to earn a drawdown criterion back -- this test should be updated
    when `evaluate_thesis` genuinely measures one, never to make a re-added claim pass.
    """

    #: Quantities the loop does not compute. Named individually rather than as a blanket ban on
    #: numbers, because a criterion *should* be specific about hit rates and horizons.
    UNMEASURED = ("drawdown", "sharpe", "sortino", "volatility", "unlevered", "buy-and-hold")

    def test_no_template_promises_a_quantity_the_loop_never_computes(self) -> None:
        from app.thesis.author import CATALOGUE

        offenders: list[tuple[str, str, str]] = []
        for template in CATALOGUE:
            for field in ("hypothesis", "falsifies_if"):
                text = getattr(template, field).lower()
                for term in self.UNMEASURED:
                    if term in text:
                        offenders.append((template.key, field, term))
        assert offenders == [], (
            "these templates name a quantity `evaluate_thesis` does not measure, so their verdict "
            f"would not answer the question they ask: {offenders}"
        )

    def test_every_template_still_states_a_real_criterion(self) -> None:
        """The counterweight: the fix above must not have produced empty or generic criteria."""
        from app.thesis.author import CATALOGUE

        for template in CATALOGUE:
            assert len(template.falsifies_if.strip()) > 40, template.key
            assert "hit rate" in template.falsifies_if.lower(), template.key
