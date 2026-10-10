"""Tests for `app.evolution.dossier`.

Every fixture builds a synthetic `data/`/`library/` tree under `tmp_path` -- never the real
`backend/app/paper/library/` or the real `data/loop/` -- except the one test that explicitly exercises
"a real genome from the library" (`TestComposeDossierRealCard`), which reads the shipped
`g1859-fd7c2c196f35.json` card but still points `data_dir` at an empty `tmp_path` so it never touches
the live, concurrently-edited `data/loop/` tree.

Following `tests/test_evolution_history.py`'s and `tests/test_evolution_seating.py`'s own conventions:
real model objects (`GenerationOutcome.model_dump_json()`, `promotion.request_seat`) build the on-disk
shape rather than hand-approximated JSON, and private helpers (`dossier._cautions`,
`dossier._phrase_bool`, ...) are imported and called directly for focused unit coverage, the same way
`tests/test_evolution_feedback.py` reaches into `feedback._adjusted_value` / `feedback._pp`.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.config import Settings
from app.evolution import dossier, promotion
from app.evolution.ledger import Ledger, LedgerEntry
from app.evolution.models import GenerationOutcome, PendingSeat, Standing, loop_root
from app.tournament.purposes import Purpose

_START = dt.datetime(2026, 8, 1, tzinfo=dt.UTC)
_REAL_LIBRARY = Path(__file__).resolve().parents[1] / "backend" / "app" / "paper" / "library"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        rounds_dir=tmp_path / "data" / "rounds",
        library_dir=tmp_path / "library",
    )


def _card_payload(genome_id: str, **overrides: object) -> dict:
    payload: dict = {
        "agent_id": genome_id,
        "display_name": f"auto {genome_id}",
        "discipline": "mean-reversion",
        "purpose": "roth",
        "thesis": "Machine-proposed test candidate.",
        "universe": ["CSCO", "AMAT", "LRCX", "KLAC", "INTU", "IGV"],
        "entry": "close > sma(135) and ema(13) crosses_above ema(21)",
        "exit": "ema(13) crosses_below ema(21)",
        "stop_loss_pct": "0.08",
        "take_profit_pct": None,
        "max_hold_days": 93,
        "max_positions": 3,
        "position_pct": "0.2",
        "rank_by": None,
        "designed_through": "2026-02-13",
    }
    payload.update(overrides)
    return payload


def _write_card(settings: Settings, genome_id: str, *, tier: str = "candidates", **overrides: object) -> Path:
    path = settings.library_dir / tier / f"{genome_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_card_payload(genome_id, **overrides)), encoding="utf-8")
    return path


def _standing(
    genome_id: str,
    *,
    rank: int = 1,
    median_excess: str | None = "0.25",
    worst_excess: str | None = "-0.10",
    hit_rate: float | None = 0.6,
    total_trades: int = 50,
    holdout_median_excess: str | None = "0.15",
    q_value: float | None = 0.01,
) -> Standing:
    return Standing(
        genome_id=genome_id,
        agent_id=genome_id,
        display_name=f"card {genome_id}",
        rank=rank,
        eligible=True,
        windows_run=5,
        median_excess=None if median_excess is None else Decimal(median_excess),
        worst_excess=None if worst_excess is None else Decimal(worst_excess),
        hit_rate=hit_rate,
        total_trades=total_trades,
        holdout_median_excess=None if holdout_median_excess is None else Decimal(holdout_median_excess),
        q_value=q_value,
    )


def _outcome(
    generation: int,
    *,
    standings: tuple[Standing, ...] = (),
    windows: tuple[str, ...] = ("bear-2022", "chop-2015"),
    holdout_windows: tuple[str, ...] = ("covid", "q4-2018"),
    purpose: Purpose = Purpose.ROTH,
    minutes_offset: int = 0,
) -> GenerationOutcome:
    started = _START + dt.timedelta(minutes=minutes_offset)
    return GenerationOutcome(
        generation=generation,
        round_id=f"r1-auto-gen{generation:04d}",
        purpose=purpose,
        status="succeeded",
        started_at=started,
        finished_at=started + dt.timedelta(seconds=30),
        windows=windows,
        holdout_windows=holdout_windows,
        genome_ids=tuple(s.genome_id for s in standings),
        standings=standings,
    )


def _write_generation(
    settings: Settings,
    generation: int,
    *,
    outcome: GenerationOutcome,
    plan_candidates: tuple[str, ...] = (),
) -> Path:
    gen_dir = loop_root(settings) / f"gen{generation:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "OUTCOME.json").write_text(outcome.model_dump_json(indent=2), encoding="utf-8")
    lines = [f"# Generation {generation} plan", "", "## Candidates", ""]
    for genome_id, kind, parents, notes in (
        plan_candidates
        or tuple((s.genome_id, "random", (), f"random candidate {s.genome_id}") for s in outcome.standings)
    ):
        parents_text = "none" if not parents else repr(list(parents))
        lines.append(f"- `{genome_id}` ({kind}, rules, parents={parents_text}) -- {notes}")
        lines.append("  - universe: CSCO, AMAT")
        lines.append('  - traits: {}')
    (gen_dir / "PLAN.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return gen_dir


def _seat(genome_id: str, *, library_path: str, purpose: Purpose = Purpose.ROTH, **overrides: object) -> PendingSeat:
    fields: dict = {
        "genome_id": genome_id,
        "agent_id": genome_id,
        "purpose": purpose,
        "requested_at": dt.datetime(2026, 8, 26, 12, 0, tzinfo=dt.UTC),
        "generations": (1,),
        "window_sets": (("bear-2022", "chop-2015"),),
        "median_excess": Decimal("0.25"),
        "holdout_median_excess": Decimal("0.15"),
        "q_value": 0.01,
        "library_path": library_path,
        "reason": "test seat request",
    }
    fields.update(overrides)
    return PendingSeat(**fields)


# ---------------------------------------------------------------------------
# headline() / short_id() -- discipline must never drive the headline
# ---------------------------------------------------------------------------


class TestHeadlineAndShortId:
    def test_headline_is_built_from_the_rule_not_discipline(self) -> None:
        text = dossier.headline(
            entry_expr="close > sma(135) and ema(13) crosses_above ema(21)",
            exit_expr="ema(13) crosses_below ema(21)",
            universe=["CSCO", "AMAT", "LRCX", "KLAC", "INTU", "IGV"],
            purpose="roth",
        )
        assert text == "EMA 13/21 crossover, 135-day regime filter · CSCO/AMAT/LRCX +3 · Roth"
        assert "mean-reversion" not in text.lower()

    def test_identical_rule_different_discipline_yields_identical_headline(self) -> None:
        """The g1815/g1823 case: same rule, same universe, different `discipline` -- the headline
        must not diverge on a label that disagrees with the rule."""
        common = {
            "entry_expr": "close > sma(92) and ema(12) crosses_above ema(15)",
            "exit_expr": "ema(12) crosses_below ema(15)",
            "universe": ["AAPL", "MSFT"],
            "purpose": "roth",
        }
        breakout_headline = dossier.headline(**common)
        mean_reversion_headline = dossier.headline(**common)
        assert breakout_headline == mean_reversion_headline

    def test_unparseable_entry_falls_back_to_raw_text_not_discipline(self) -> None:
        text = dossier.headline(
            entry_expr="not a valid rule (((",
            exit_expr="close < sma(10)",
            universe=["AAPL"],
            purpose="trading",
        )
        assert "not a valid rule (((" in text

    def test_headline_handles_missing_universe_and_purpose(self) -> None:
        text = dossier.headline(entry_expr=None, exit_expr=None, universe=[], purpose="")
        assert "no tickers" in text
        assert "Unlabeled purpose" in text

    def test_short_id(self) -> None:
        assert dossier.short_id("g1859-fd7c2c196f35") == "g1859·fd7c"

    def test_short_id_tolerates_an_id_with_no_separator(self) -> None:
        assert dossier.short_id("nodashhere") == "nodashhere"


# ---------------------------------------------------------------------------
# universe_note()
# ---------------------------------------------------------------------------


class TestUniverseNote:
    def test_known_and_unclassified_mix(self) -> None:
        note = dossier.universe_note(["AMAT", "LRCX", "KLAC", "ZZZZ"])
        assert note.startswith("4 names:")
        assert "unclassified" in note

    def test_empty_universe(self) -> None:
        assert dossier.universe_note([]) == "No tickers are named in this universe."

    def test_single_shared_label(self) -> None:
        note = dossier.universe_note(["AMAT", "LRCX", "KLAC"])
        assert note == "3 names, all semiconductor equipment."


# ---------------------------------------------------------------------------
# Plain-English renderer -- every distinct entry/exit form actually present in the shipped library,
# plus specific-content assertions for the forms that exercise each branch of `_phrase_indicator`.
# ---------------------------------------------------------------------------


def _real_library_expressions() -> list[tuple[str, str, str]]:
    """`(genome_id, entry, exit)` for every candidate card shipped in the real library that has both
    fields -- deduplicated by (entry, exit) pair so the parametrized test covers every distinct form
    once rather than the ~40 near-duplicates of the crossover+filter template."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, str]] = []
    for path in sorted(glob.glob(str(_REAL_LIBRARY / "candidates" / "*.json"))):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        entry, exit_ = data.get("entry"), data.get("exit")
        if not isinstance(entry, str) or not isinstance(exit_, str):
            continue
        key = (entry, exit_)
        if key in seen:
            continue
        seen.add(key)
        out.append((data.get("agent_id", Path(path).stem), entry, exit_))
    return out


@pytest.mark.parametrize("genome_id,entry,exit_", _real_library_expressions())
def test_every_distinct_real_library_form_translates_or_honestly_falls_back(
    genome_id: str, entry: str, exit_: str
) -> None:
    entry_plain = dossier._sentence("Buys when", entry)
    exit_plain = dossier._sentence(
        "Sells when", exit_, entry_crosses=dossier._entry_crosses(entry)
    )
    for text in (entry_plain, exit_plain):
        assert text
        # Every real library expression parses under this grammar (it is what the engine actually
        # evaluates), so a translation failure here would mean this module is missing an indicator
        # phrase -- catch that as a hard failure rather than silently accepting the raw-text fallback.
        assert "Could not translate" not in text, f"{genome_id}: {text}"


class TestPlainEnglishSpecificForms:
    def test_g1859_entry_and_exit_match_the_spec_example_shape(self) -> None:
        entry_crosses = dossier._entry_crosses("close > sma(135) and ema(13) crosses_above ema(21)")
        entry_plain = dossier._sentence("Buys when", "close > sma(135) and ema(13) crosses_above ema(21)")
        exit_plain = dossier._sentence(
            "Sells when", "ema(13) crosses_below ema(21)", entry_crosses=entry_crosses
        )
        assert entry_plain == (
            "Buys when the price is above the 135-day average (a rising-market filter) and "
            "the 13-day average crosses above the 21-day average."
        )
        assert exit_plain == "Sells when the 13-day average crosses back below the 21-day average."

    def test_rsi_oversold_annotation(self) -> None:
        text = dossier._sentence("Buys when", "rsi(14) < 30")
        assert "oversold territory" in text

    def test_rsi_overbought_annotation(self) -> None:
        text = dossier._sentence("Sells when", "rsi(14) > 70")
        assert "overbought territory" in text

    def test_bollinger_bands(self) -> None:
        text = dossier._sentence("Buys when", "close < bb_lower(20,2)")
        assert "Bollinger channel" in text

    def test_swing_high(self) -> None:
        text = dossier._sentence("Buys when", "close crosses_above swing_high(20)")
        assert "swing high" in text

    def test_arithmetic_operand(self) -> None:
        text = dossier._sentence("Buys when", "high - low > atr(14)")
        assert "minus" in text
        assert "average true range" in text

    def test_or_condition(self) -> None:
        text = dossier._sentence("Sells when", "close < sma(100) or rsi(14) < 40")
        assert " or " in text

    def test_missing_rule_says_so(self) -> None:
        assert dossier._sentence("Buys when", None) == "No rule is defined."
        assert dossier._sentence("Buys when", "") == "No rule is defined."

    def test_unparseable_expression_falls_back_and_says_so(self) -> None:
        text = dossier._sentence("Buys when", "close >>> 5")
        assert "Could not translate" in text
        assert "close >>> 5" in text

    def test_unknown_indicator_output_falls_back_and_says_so(self) -> None:
        # `macd(12,26,9)` alone parses (output=None) but this module has a phrase for it; force an
        # untranslatable node directly to prove the fallback path itself, independent of coverage.
        with pytest.raises(dossier._UntranslatableError):
            dossier._phrase_indicator(
                dossier.IndicatorRef(name="totally_unknown", args=(), output=None)
            )


# ---------------------------------------------------------------------------
# risk_plain / sizing_plain
# ---------------------------------------------------------------------------


class TestRiskAndSizingPlain:
    def test_full_risk_profile(self) -> None:
        text = dossier._risk_plain(
            {"stop_loss_pct": "0.08", "take_profit_pct": None, "max_hold_days": 93}
        )
        assert text == (
            "Cuts a losing position at −8%. No profit target. "  # noqa: RUF001
            "Force-closes any position still open after 93 trading days."
        )

    def test_no_stop_no_target_no_hold_limit(self) -> None:
        text = dossier._risk_plain({"stop_loss_pct": None, "take_profit_pct": None, "max_hold_days": None})
        assert text == "No stop loss is set. No profit target. No maximum hold period."

    def test_sizing_under_full_allocation(self) -> None:
        text = dossier._sizing_plain({"max_positions": 3, "position_pct": "0.2"})
        assert text == (
            "At most 3 positions at once, 20% of the book each — "
            "so at most 60% invested, the rest in cash."
        )

    def test_sizing_missing_fields(self) -> None:
        assert dossier._sizing_plain({}) == "Position sizing is not fully specified on this card."


# ---------------------------------------------------------------------------
# Caution rules -- each fires, and each does not fire, in isolation.
# ---------------------------------------------------------------------------


def _context(**overrides: object) -> dossier.Context:
    fields: dict = {
        "field_median_excess_this_generation": Decimal("0.18"),
        "field_median_excess_same_purpose": Decimal("0.0224"),
        "field_median_excess_all_purposes": Decimal("0.0565"),
        "field_holdout_median_same_purpose": Decimal("0.1288"),
        "field_holdout_median_all_purposes": Decimal("0.1502"),
        "field_holdout_positive_fraction_same_purpose": 0.90,
        "field_holdout_positive_fraction_all_purposes": 0.943,
        "holdout_measurements_same_purpose": 1196,
        "holdout_measurements_all_purposes": 2364,
        "percentile_all_time": 0.9975,
        "candidates_ever_run": 1887,
        "generations_with_outcomes": 233,
        "noise_floor_pp": Decimal("21.2"),
        "margin_over_noise_pp": Decimal("3.45"),
    }
    fields.update(overrides)
    return dossier.Context(**fields)


def _evidence_row(**overrides: object) -> dossier.EvidenceRow:
    fields: dict = {
        "generation": 1859,
        "round_id": "r17-auto",
        "rank": 1,
        "field_size": 10,
        "windows": ("bear-2022", "chop-2015"),
        "median_excess": Decimal("0.2465"),
        "worst_excess": Decimal("-0.1093"),
        "hit_rate": 0.6,
        "total_trades": 51,
        "holdout_median_excess": Decimal("0.1487"),
        "holdout_windows": ("covid", "q4-2018"),
        "q_value": 0.01,
    }
    fields.update(overrides)
    return dossier.EvidenceRow(**fields)


def _empty_overlap() -> dossier.Overlap:
    return dossier.Overlap(with_shelved=(), with_seated=(), note="No shelved or seated card shares a ticker with this one.")


def _clean_cautions(**overrides: object) -> tuple[dossier.Caution, ...]:
    """A baseline call to `_cautions` where nothing fires, so each test below can flip exactly one
    input and assert exactly one rule's presence/absence changes."""
    kwargs: dict = {
        "evidence": (_evidence_row(), _evidence_row(generation=1863, windows=("gfc", "recent"))),
        "universe": ("AAPL", "MSFT", "GOOGL", "AMZN", "META"),
        "context": _context(
            field_holdout_positive_fraction_all_purposes=0.5, candidates_ever_run=100
        ),
        "overlap": _empty_overlap(),
        "discipline_label": "mean-reversion",
        "label_mismatch": None,
        "template_sibling_count": 0,
        "card_holdout": Decimal("0.1487"),
        "card_q": 0.01,
    }
    kwargs.update(overrides)
    return dossier._cautions(**kwargs)


def _codes(cautions: tuple[dossier.Caution, ...]) -> set[str]:
    return {c.code for c in cautions}


class TestCautions:
    def test_clean_field_fires_nothing(self) -> None:
        assert _clean_cautions() == ()

    def test_holdout_does_not_discriminate_fires_above_80pct(self) -> None:
        cautions = _clean_cautions(
            context=_context(field_holdout_positive_fraction_all_purposes=0.943)
        )
        assert "holdout-does-not-discriminate" in _codes(cautions)

    def test_holdout_does_not_discriminate_does_not_fire_at_or_below_80pct(self) -> None:
        cautions = _clean_cautions(
            context=_context(field_holdout_positive_fraction_all_purposes=0.80)
        )
        assert "holdout-does-not-discriminate" not in _codes(cautions)

    def test_holdout_does_not_discriminate_states_the_matching_denominator(self) -> None:
        """Regression: the printed fraction and the printed count must describe the same
        population -- pairing a fraction computed over measured holdout rows with a distinct-genome
        count is exactly the mismatch this test guards against."""
        cautions = _clean_cautions(
            context=_context(
                field_holdout_positive_fraction_all_purposes=0.943,
                holdout_measurements_all_purposes=2364,
                candidates_ever_run=1887,
            )
        )
        matches = [c for c in cautions if c.code == "holdout-does-not-discriminate"]
        assert matches
        assert "2364" in matches[0].text
        assert "1887" not in matches[0].text

    def test_holdout_does_not_discriminate_compares_against_the_same_purpose_median(self) -> None:
        cautions = _clean_cautions(
            context=_context(
                field_holdout_positive_fraction_all_purposes=0.943,
                field_holdout_median_same_purpose=Decimal("0.1288"),
            ),
            card_holdout=Decimal("0.1487"),
        )
        matches = [c for c in cautions if c.code == "holdout-does-not-discriminate"]
        assert matches
        assert "above" in matches[0].text
        assert "+12.88%" in matches[0].text
        assert "+14.87%" in matches[0].text

    def test_q_above_5pct_fires_above_threshold(self) -> None:
        cautions = _clean_cautions(card_q=0.069)
        matches = [c for c in cautions if c.code == "q-above-5pct"]
        assert matches and "0.069" in matches[0].text

    def test_q_above_5pct_fires_when_null(self) -> None:
        cautions = _clean_cautions(card_q=None)
        matches = [c for c in cautions if c.code == "q-above-5pct"]
        assert matches and "undefined" in matches[0].text

    def test_q_above_5pct_does_not_fire_below_threshold(self) -> None:
        cautions = _clean_cautions(card_q=0.01)
        assert "q-above-5pct" not in _codes(cautions)

    def test_q_above_5pct_uses_candidates_ever_run_as_the_hypothesis_count(self) -> None:
        cautions = _clean_cautions(card_q=0.069, context=_context(candidates_ever_run=1887))
        matches = [c for c in cautions if c.code == "q-above-5pct"]
        assert matches and "1887" in matches[0].text

    def test_margin_inside_noise_fires_when_best_median_below_floor(self) -> None:
        cautions = _clean_cautions(evidence=(_evidence_row(median_excess=Decimal("0.10")),))
        assert "margin-inside-noise" in _codes(cautions)

    def test_margin_inside_noise_fires_when_no_median_ever_measured(self) -> None:
        cautions = _clean_cautions(evidence=(_evidence_row(median_excess=None),))
        assert "margin-inside-noise" in _codes(cautions)

    def test_margin_inside_noise_does_not_fire_when_best_clears_the_floor(self) -> None:
        cautions = _clean_cautions(evidence=(_evidence_row(median_excess=Decimal("0.30")),))
        assert "margin-inside-noise" not in _codes(cautions)

    def test_thin_trades_fires_under_30(self) -> None:
        cautions = _clean_cautions(evidence=(_evidence_row(total_trades=29),))
        assert "thin-trades" in _codes(cautions)

    def test_thin_trades_does_not_fire_at_30(self) -> None:
        cautions = _clean_cautions(evidence=(_evidence_row(total_trades=30),))
        assert "thin-trades" not in _codes(cautions)

    def test_narrow_universe_fires_under_5(self) -> None:
        cautions = _clean_cautions(universe=("AAPL", "MSFT"))
        assert "narrow-universe" in _codes(cautions)

    def test_narrow_universe_does_not_fire_at_5(self) -> None:
        cautions = _clean_cautions(universe=("AAPL", "MSFT", "GOOGL", "AMZN", "META"))
        assert "narrow-universe" not in _codes(cautions)

    def test_worst_window_deep_fires_below_minus_20pp(self) -> None:
        cautions = _clean_cautions(evidence=(_evidence_row(worst_excess=Decimal("-0.21")),))
        assert "worst-window-deep" in _codes(cautions)

    def test_worst_window_deep_does_not_fire_at_minus_20pp(self) -> None:
        cautions = _clean_cautions(evidence=(_evidence_row(worst_excess=Decimal("-0.20")),))
        assert "worst-window-deep" not in _codes(cautions)

    def test_single_window_set_fires_with_one_distinct_set(self) -> None:
        cautions = _clean_cautions(
            evidence=(_evidence_row(windows=("gfc",)), _evidence_row(generation=1863, windows=("gfc",)))
        )
        assert "single-window-set" in _codes(cautions)

    def test_single_window_set_fires_with_no_evidence(self) -> None:
        cautions = _clean_cautions(evidence=())
        assert "single-window-set" in _codes(cautions)

    def test_single_window_set_does_not_fire_with_two_distinct_sets(self) -> None:
        cautions = _clean_cautions()  # baseline already uses two differing window tuples
        assert "single-window-set" not in _codes(cautions)

    def test_shelf_crowding_fires_at_or_above_60pct_jaccard(self) -> None:
        overlap = dossier.Overlap(
            with_shelved=(
                dossier.OverlapEntry(
                    genome_id="g-other", headline="X · AMAT/LRCX · Roth",
                    shared_tickers=("AMAT", "LRCX"), jaccard=0.6,
                ),
            ),
            with_seated=(),
            note="1 shelved card already trades AMAT, LRCX in common with this one.",
        )
        cautions = _clean_cautions(overlap=overlap)
        assert "shelf-crowding" in _codes(cautions)

    def test_shelf_crowding_does_not_fire_below_60pct_jaccard(self) -> None:
        overlap = dossier.Overlap(
            with_shelved=(
                dossier.OverlapEntry(
                    genome_id="g-other", headline="X · AMAT/LRCX · Roth",
                    shared_tickers=("AMAT",), jaccard=0.3,
                ),
            ),
            with_seated=(),
            note="",
        )
        cautions = _clean_cautions(overlap=overlap)
        assert "shelf-crowding" not in _codes(cautions)

    def test_never_saw_a_crash_fires_when_no_crash_window_run(self) -> None:
        cautions = _clean_cautions(
            evidence=(
                _evidence_row(windows=("bear-2022",), holdout_windows=("bull-2024",)),
                _evidence_row(generation=1863, windows=("chop-2015",), holdout_windows=("bull-2024",)),
            )
        )
        assert "never-saw-a-crash" in _codes(cautions)

    def test_never_saw_a_crash_does_not_fire_when_a_holdout_crash_window_was_run(self) -> None:
        cautions = _clean_cautions(
            evidence=(_evidence_row(windows=("bear-2022",), holdout_windows=("covid", "q4-2018")),)
        )
        assert "never-saw-a-crash" not in _codes(cautions)

    def test_label_does_not_match_rule_fires_when_a_mismatch_is_supplied(self) -> None:
        cautions = _clean_cautions(label_mismatch=("g1815-d05786e4c611", "breakout"))
        matches = [c for c in cautions if c.code == "label-does-not-match-rule"]
        assert matches
        assert "g1815-d05786e4c611" in matches[0].text
        assert "breakout" in matches[0].text

    def test_label_does_not_match_rule_absent_when_no_mismatch(self) -> None:
        assert "label-does-not-match-rule" not in _codes(_clean_cautions(label_mismatch=None))

    def test_template_is_not_distinct_fires_with_siblings(self) -> None:
        cautions = _clean_cautions(template_sibling_count=24)
        matches = [c for c in cautions if c.code == "template-is-not-distinct"]
        assert matches and "24" in matches[0].text

    def test_template_is_not_distinct_absent_with_zero_siblings(self) -> None:
        assert "template-is-not-distinct" not in _codes(_clean_cautions(template_sibling_count=0))

    def test_caution_order_matches_the_spec_table_then_the_two_additions(self) -> None:
        cautions = dossier._cautions(
            evidence=(
                _evidence_row(
                    median_excess=Decimal("0.05"),
                    q_value=0.5,
                    total_trades=5,
                    worst_excess=Decimal("-0.5"),
                    holdout_windows=("bull-2024",),
                ),
            ),
            universe=("AAPL",),
            context=_context(field_holdout_positive_fraction_all_purposes=0.9),
            overlap=dossier.Overlap(
                with_shelved=(
                    dossier.OverlapEntry(genome_id="g-x", headline="h", shared_tickers=("AAPL",), jaccard=1.0),
                ),
                with_seated=(),
                note="",
            ),
            discipline_label="breakout",
            label_mismatch=("g-y", "mean-reversion"),
            template_sibling_count=3,
            card_holdout=Decimal("0.01"),
            card_q=0.5,
        )
        codes = [c.code for c in cautions]
        assert codes == [
            "holdout-does-not-discriminate",
            "q-above-5pct",
            "margin-inside-noise",
            "thin-trades",
            "narrow-universe",
            "worst-window-deep",
            "single-window-set",
            "shelf-crowding",
            "never-saw-a-crash",
            "label-does-not-match-rule",
            "template-is-not-distinct",
        ]


# ---------------------------------------------------------------------------
# compose_dossier -- 404 path
# ---------------------------------------------------------------------------


class TestComposeDossier404:
    def test_unknown_genome_returns_none(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        assert dossier.compose_dossier("g9999-doesnotexist", settings=settings) is None


# ---------------------------------------------------------------------------
# compose_dossier -- a real genome from the shipped library
# ---------------------------------------------------------------------------


class TestComposeDossierRealCard:
    def test_full_dossier_for_g1859(self, tmp_path: Path) -> None:
        settings = Settings(
            repo_root=tmp_path,
            data_dir=tmp_path / "data",
            rounds_dir=tmp_path / "data" / "rounds",
            # library_dir left at its default: the real, shipped `backend/app/paper/library/`.
        )
        result = dossier.compose_dossier("g1859-fd7c2c196f35", settings=settings)
        assert result is not None
        assert result.genome_id == "g1859-fd7c2c196f35"
        assert result.agent_id == "g1859-fd7c2c196f35"
        assert result.short_id == "g1859·fd7c"
        assert result.purpose == "roth"
        assert result.discipline_label == "mean-reversion"
        assert "not derived from the entry/exit rule" in result.discipline_label_note
        assert result.headline == (
            "EMA 13/21 crossover, 135-day regime filter · CSCO/AMAT/LRCX +3 · Roth"
        )
        assert result.what_it_does.universe == ("CSCO", "AMAT", "LRCX", "KLAC", "INTU", "IGV")
        assert "crosses back below" in result.what_it_does.exit_plain
        assert result.stage is None
        assert result.requested_at is None
        # No synthetic generations were written under this empty `data_dir` -- an honest empty
        # history, not a crash.
        assert result.evidence == ()
        assert result.origin.generation is None
        assert result.context.candidates_ever_run == 0
        assert result.context.generations_with_outcomes == 0
        # `null` is never zero: an unmeasured margin (and every field-wide stat over an empty
        # ledger) is `None`/`0` appropriately, never a fabricated number.
        assert result.context.margin_over_noise_pp is None
        assert result.context.field_median_excess_same_purpose is None
        assert result.context.field_median_excess_all_purposes is None
        assert result.context.field_holdout_median_same_purpose is None
        assert result.context.field_holdout_positive_fraction_all_purposes is None
        assert result.context.holdout_measurements_same_purpose == 0
        assert result.context.holdout_measurements_all_purposes == 0
        assert result.context.percentile_all_time is None
        assert result.what_a_decision_does.seat.startswith("Adds it to the simulated paper desk")


# ---------------------------------------------------------------------------
# compose_dossier -- evidence, origin, and field-of-the-generation, from synthetic generations
# ---------------------------------------------------------------------------


class TestComposeDossierEvidenceAndOrigin:
    def test_evidence_oldest_first_and_origin_from_plan(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        genome_id = "g0010-abc123def456"
        _write_card(settings, genome_id, discipline="mean-reversion")

        gen10 = _outcome(10, standings=(_standing(genome_id, median_excess="0.20"),))
        gen12 = _outcome(12, standings=(_standing(genome_id, median_excess="0.30"),), minutes_offset=5)
        _write_generation(
            settings, 10, outcome=gen10,
            plan_candidates=((genome_id, "mutation", ("g0005-parent000001",), "mutated from g0005-parent000001"),),
        )
        _write_generation(settings, 12, outcome=gen12)

        result = dossier.compose_dossier(genome_id, settings=settings)
        assert result is not None
        assert [row.generation for row in result.evidence] == [10, 12]
        assert result.evidence[0].median_excess == Decimal("0.20")
        assert result.evidence[1].median_excess == Decimal("0.30")
        assert result.origin.generation == 10
        assert result.origin.origin_kind == "mutation"
        assert result.origin.parents == ("g0005-parent000001",)
        assert "mutated from" in result.origin.note
        # field_median_excess_this_generation reflects the *last* generation the genome was scored in.
        assert result.context.field_median_excess_this_generation == Decimal("0.30")
        # best selection median (0.30 -> 30pp) minus the 21.2pp noise floor.
        assert result.context.margin_over_noise_pp == Decimal("30.00") - Decimal("21.2")

    def test_no_plan_record_degrades_honestly(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        genome_id = "g0020-noplan00000"
        _write_card(settings, genome_id)
        result = dossier.compose_dossier(genome_id, settings=settings)
        assert result is not None
        assert result.origin.generation is None
        assert result.origin.origin_kind is None
        assert "No generation-plan record" in result.origin.note

    def test_percentile_uses_the_seat_requests_own_median_not_a_later_rescore(
        self, tmp_path: Path
    ) -> None:
        """Reproduces the exact shape of the live g1859 defect: a genome clears the promotion gate
        (and files a `PendingSeat`) at a strong median, then gets re-run as a surviving elite under a
        harder window mix and posts a much weaker one. `percentile_all_time` -- and the
        `holdout-does-not-discriminate`/`q-above-5pct` cautions -- must reflect the seat request's own
        recorded figure, not whichever generation happens to be the most recent.

        Hand-computed expectation, not "whatever the implementation returns": the roth ledger
        population is this genome's own two rows (0.90, 0.001) plus 9 other rows at 0.01 through
        0.09 -- 11 rows total. Strict `count(v < card_median) / n` for `card_median = 0.90` (the seat
        request's own figure) is 10/11, since every other row sits below it. Using the *later*,
        weaker re-score (0.001) instead would rank at 0/11 -- the opposite end of the same field.
        """
        settings = _settings(tmp_path)
        genome_id = "g0900-strongthenweak"
        _write_card(settings, genome_id)

        # This genome's two scored generations: a strong original clearance, then a much weaker
        # re-score later (mirrors gen1859 -> gen1867 on the real ledger).
        gen_strong = _outcome(900, standings=(_standing(genome_id, median_excess="0.90", holdout_median_excess="0.40", q_value=0.001),))
        gen_weak = _outcome(910, standings=(_standing(genome_id, median_excess="0.001", holdout_median_excess="0.001", q_value=0.9), ), minutes_offset=20)
        _write_generation(settings, 900, outcome=gen_strong)
        _write_generation(settings, 910, outcome=gen_weak)

        # The seat request filed off the strong generation -- the canonical, already-decided figure.
        promotion.request_seat(
            _seat(
                genome_id,
                library_path=f"library/candidates/{genome_id}.json",
                median_excess=Decimal("0.90"),
                holdout_median_excess=Decimal("0.40"),
                q_value=0.001,
            ),
            settings=settings,
        )

        # The ledger rows this genome's own two generations would actually produce (mirrors
        # `ledger_entries_for`'s one-row-per-standing behaviour), plus 9 other roth rows spread from
        # 0.01 to 0.09.
        ledger_path = loop_root(settings) / "ledger.jsonl"
        Ledger(ledger_path).record(
            [
                LedgerEntry(
                    genome_id=genome_id, generation=900, purpose="roth", round_id="r1",
                    windows=("gfc",), median_excess=Decimal("0.90"), holdout_median_excess=Decimal("0.40"),
                    closed_trades=40, wins=30, p_value=0.001, recorded_at=_START,
                ),
                LedgerEntry(
                    genome_id=genome_id, generation=910, purpose="roth", round_id="r1",
                    windows=("chop-2015",), median_excess=Decimal("0.001"), holdout_median_excess=Decimal("0.001"),
                    closed_trades=40, wins=5, p_value=0.9, recorded_at=_START,
                ),
                *(
                    LedgerEntry(
                        genome_id=f"g0901-other{i:02d}", generation=900, purpose="roth", round_id="r1",
                        windows=("gfc",), median_excess=Decimal(f"0.0{i}"), holdout_median_excess=Decimal("0.02"),
                        closed_trades=40, wins=25, p_value=0.01, recorded_at=_START,
                    )
                    for i in range(1, 10)
                ),
            ]
        )

        result = dossier.compose_dossier(genome_id, settings=settings)
        assert result is not None
        assert [row.median_excess for row in result.evidence] == [Decimal("0.90"), Decimal("0.001")]
        # The bug this guards against: using the latest evidence row (0.001) would rank this card at
        # the very bottom of the field instead of the top.
        assert result.context.percentile_all_time == pytest.approx(10 / 11)


# ---------------------------------------------------------------------------
# compose_dossier -- overlap, label mismatch, template siblings
# ---------------------------------------------------------------------------


class TestComposeDossierOverlapAndLabelChecks:
    def test_overlap_and_shelf_crowding_against_a_shelved_and_a_seated_card(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        target_id = "g0030-target000001"
        shelved_id = "g0031-shelved00001"
        seated_id = "g0032-seated000001"

        _write_card(settings, target_id, universe=["AMAT", "LRCX", "KLAC"])
        _write_card(settings, shelved_id, universe=["AMAT", "LRCX", "AAPL"])
        _write_card(settings, seated_id, universe=["MSFT"])

        promotion.request_seat(
            _seat(shelved_id, library_path=f"library/candidates/{shelved_id}.json"), settings=settings
        )
        promotion.shelve_pending_seat(shelved_id, settings=settings)

        promotion.request_seat(
            _seat(seated_id, library_path=f"library/candidates/{seated_id}.json"), settings=settings
        )
        promotion.shelve_pending_seat(seated_id, settings=settings)
        promotion.seat_pending_seat(seated_id, settings=settings)

        result = dossier.compose_dossier(target_id, settings=settings)
        assert result is not None
        assert len(result.overlap.with_shelved) == 1
        assert result.overlap.with_shelved[0].genome_id == shelved_id
        assert set(result.overlap.with_shelved[0].shared_tickers) == {"AMAT", "LRCX"}
        assert result.overlap.with_seated == ()
        assert "shelved card" in result.overlap.note
        # 2 shared / 4 union = 0.5 -- below the 0.60 shelf-crowding threshold.
        assert "shelf-crowding" not in {c.code for c in result.cautions}

    def test_shelf_crowding_fires_through_the_full_pipeline(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        target_id = "g0040-target000002"
        shelved_id = "g0041-shelved00002"
        _write_card(settings, target_id, universe=["AMAT", "LRCX", "KLAC"])
        _write_card(settings, shelved_id, universe=["AMAT", "LRCX", "KLAC"])
        promotion.request_seat(
            _seat(shelved_id, library_path=f"library/candidates/{shelved_id}.json"), settings=settings
        )
        promotion.shelve_pending_seat(shelved_id, settings=settings)

        result = dossier.compose_dossier(target_id, settings=settings)
        assert result is not None
        assert result.overlap.with_shelved[0].jaccard == 1.0
        assert "shelf-crowding" in {c.code for c in result.cautions}

    def test_label_mismatch_and_template_sibling_cautions(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        a_id, b_id = "g1815-d0578x0001", "g1823-e2a3x0002"
        shared_fields = dict(
            universe=["AAPL", "MSFT"],
            entry="close > sma(92) and ema(12) crosses_above ema(15)",
            exit="ema(12) crosses_below ema(15)",
            stop_loss_pct="0.08",
            max_hold_days=93,
            max_positions=3,
            position_pct="0.2",
        )
        _write_card(settings, a_id, discipline="breakout", **shared_fields)
        _write_card(settings, b_id, discipline="mean-reversion", **shared_fields)

        promotion.request_seat(_seat(a_id, library_path=f"library/candidates/{a_id}.json"), settings=settings)
        promotion.request_seat(_seat(b_id, library_path=f"library/candidates/{b_id}.json"), settings=settings)

        result_b = dossier.compose_dossier(b_id, settings=settings)
        assert result_b is not None
        mismatch = [c for c in result_b.cautions if c.code == "label-does-not-match-rule"]
        assert mismatch
        assert a_id in mismatch[0].text
        assert "breakout" in mismatch[0].text

        template = [c for c in result_b.cautions if c.code == "template-is-not-distinct"]
        assert template
        assert "1 other card" in template[0].text

    def test_no_label_mismatch_when_disciplines_agree(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        a_id, b_id = "g0050-agreeaaaaa1", "g0051-agreeaaaaa2"
        shared_fields = dict(
            universe=["AAPL", "MSFT"],
            entry="close > sma(50) and ema(9) crosses_above ema(20)",
            exit="ema(9) crosses_below ema(20)",
        )
        _write_card(settings, a_id, discipline="mean-reversion", **shared_fields)
        _write_card(settings, b_id, discipline="mean-reversion", **shared_fields)
        result = dossier.compose_dossier(b_id, settings=settings)
        assert result is not None
        assert "label-does-not-match-rule" not in {c.code for c in result.cautions}


# ---------------------------------------------------------------------------
# card_summary() -- the lightweight naming-only lookup for a pending-seats list.
# ---------------------------------------------------------------------------


class TestCardSummary:
    def test_unknown_genome_returns_none(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        assert dossier.card_summary("g9999-doesnotexist", settings=settings) is None

    def test_headline_matches_the_full_dossier(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        genome_id = "g0060-summarymatch1"
        _write_card(settings, genome_id, discipline="breakout")

        summary = dossier.card_summary(genome_id, settings=settings)
        full = dossier.compose_dossier(genome_id, settings=settings)
        assert summary is not None and full is not None
        assert summary.headline == full.headline
        assert summary.short_id == full.short_id
        assert summary.discipline_label == full.discipline_label
        assert summary.discipline_label_note == full.discipline_label_note

    def test_rule_template_id_groups_same_shaped_cards(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        a_id, b_id, c_id = "g0070-tmplaaaaaa1", "g0071-tmplaaaaaa2", "g0072-tmplbbbbbb1"
        _write_card(
            settings, a_id,
            entry="close > sma(92) and ema(12) crosses_above ema(15)",
            exit="ema(12) crosses_below ema(15)",
        )
        _write_card(
            settings, b_id,
            entry="close > sma(135) and ema(13) crosses_above ema(21)",
            exit="ema(13) crosses_below ema(21)",
        )
        _write_card(settings, c_id, entry="rsi(14) < 30", exit="rsi(14) > 70")

        summary_a = dossier.card_summary(a_id, settings=settings)
        summary_b = dossier.card_summary(b_id, settings=settings)
        summary_c = dossier.card_summary(c_id, settings=settings)
        assert summary_a is not None and summary_b is not None and summary_c is not None
        assert summary_a.rule_template_id == summary_b.rule_template_id
        assert summary_a.rule_template_id != summary_c.rule_template_id

    def test_malformed_card_does_not_raise(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        path = settings.library_dir / "candidates" / "g0080-broken0000001.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        assert dossier.card_summary("g0080-broken0000001", settings=settings) is None


# ---------------------------------------------------------------------------
# Field-statistics cache -- invalidates on `ledger.jsonl`'s own mtime/size change.
# ---------------------------------------------------------------------------


class TestLedgerCache:
    def _entry(self, genome_id: str, *, purpose: str = "roth", median: str = "0.10", holdout: str = "0.05") -> LedgerEntry:
        return LedgerEntry(
            genome_id=genome_id,
            generation=1,
            purpose=purpose,
            round_id="r1",
            windows=("gfc",),
            median_excess=Decimal(median),
            holdout_median_excess=Decimal(holdout),
            closed_trades=40,
            wins=25,
            p_value=0.01,
            recorded_at=_START,
        )

    def test_repeated_call_reuses_the_cached_parse(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        ledger_path = loop_root(settings) / "ledger.jsonl"
        Ledger(ledger_path).record([self._entry("g0001-a")])

        _, entries_first = dossier._cached_ledger(settings)
        _, entries_second = dossier._cached_ledger(settings)
        assert entries_first is entries_second  # same object: no re-read happened

    def test_change_on_disk_invalidates_the_cache(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        ledger_path = loop_root(settings) / "ledger.jsonl"
        Ledger(ledger_path).record([self._entry("g0001-a", median="0.10")])

        stats_first, _ = dossier._cached_ledger(settings)
        assert stats_first.candidates_ever_run == 1

        Ledger(ledger_path).record([self._entry("g0002-b", median="0.90")])
        stats_second, entries_second = dossier._cached_ledger(settings)
        assert stats_second.candidates_ever_run == 2
        assert len(entries_second) == 2

    def test_percentile_all_time_is_scoped_to_purpose(self, tmp_path: Path) -> None:
        settings = _settings(tmp_path)
        ledger_path = loop_root(settings) / "ledger.jsonl"
        Ledger(ledger_path).record(
            [
                self._entry("g0001-a", purpose="roth", median="0.05"),
                self._entry("g0002-b", purpose="roth", median="0.10"),
                self._entry("g0003-c", purpose="roth", median="0.50"),
                self._entry("g0004-d", purpose="trading", median="0.99"),
            ]
        )
        _, entries = dossier._cached_ledger(settings)
        # Strict "<": only 0.05 sits strictly below 0.10 among the 3 roth entries -> 1/3, ignoring
        # the trading-purpose entry entirely (it must not count toward either the numerator or `n`).
        percentile = dossier._percentile_all_time(Decimal("0.10"), "roth", entries)
        assert percentile == pytest.approx(1 / 3)

    def test_percentile_all_time_ties_do_not_inflate_against_self(self, tmp_path: Path) -> None:
        """A genome recorded twice at the identical median (two consecutive clearances on
        identical-window re-runs) must not count its own tie as "below itself"."""
        settings = _settings(tmp_path)
        ledger_path = loop_root(settings) / "ledger.jsonl"
        Ledger(ledger_path).record(
            [
                self._entry("g0001-a", purpose="roth", median="0.20"),
                self._entry("g0001-a", purpose="roth", median="0.20"),  # same genome, same value
                self._entry("g0002-b", purpose="roth", median="0.05"),
            ]
        )
        _, entries = dossier._cached_ledger(settings)
        percentile = dossier._percentile_all_time(Decimal("0.20"), "roth", entries)
        assert percentile == pytest.approx(1 / 3)
