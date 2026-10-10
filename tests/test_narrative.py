"""The grounding contract.

The plan calls for an adversarial test in which a writer asserts an uncomputed figure and the
builder rejects it. That is `TestAdversarial` below, and it is the reason this module exists: a
checker that has only ever been shown well-formed input has not been tested, it has been
demonstrated.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.db.duck import Interval
from app.report import narrative
from app.report.models import (
    Fact,
    FactBundle,
    FactKind,
    GroundingReport,
    NarrativeDraft,
    RenderedNarrative,
    ViolationKind,
)


def _bundle(**values: object) -> FactBundle:
    """A bundle from ``id=value`` pairs, with kinds inferred loosely enough for a test."""
    facts: dict[str, Fact] = {}
    for key, value in values.items():
        fact_id = key.replace("__", ".")
        kind = FactKind.TEXT if isinstance(value, str) else FactKind.PERCENT
        facts[fact_id] = Fact(
            id=fact_id,
            label=fact_id,
            value=value,  # type: ignore[arg-type]
            kind=kind,
            source="test",
        )
    return FactBundle(
        symbol="TEST",
        interval=Interval.DAY,
        generated_at=dt.datetime.now(dt.UTC),
        facts=facts,
    )


def _draft(text: str) -> NarrativeDraft:
    """A well-formed draft for tests that are not about provenance.

    ``source="template"`` -- not ``"test"`` -- because `render` now branches on it (see the fix for
    the "mislabeled citation" defect): a non-template source gets its fact labels appended to every
    substituted value. Every test built with this helper hand-verifies its own text against the
    fact ids it cites, exactly like the shipped narrators do, so it belongs in the same trusted bucket
    they do. Tests that specifically exercise untrusted-draft behaviour use `_llm_draft` instead.
    """
    return NarrativeDraft(text=text, source="template")


def _llm_draft(text: str) -> NarrativeDraft:
    """An untrusted draft: what `render` treats as unverified, LLM-authored prose."""
    return NarrativeDraft(text=text, source="llm", model="test-model")


class TestAdversarial:
    """A writer asserting figures nothing computed. Every one of these must be refused."""

    def test_an_uncomputed_fact_is_rejected(self) -> None:
        """The headline case from the plan: prose citing a figure no engine produced."""
        bundle = _bundle(drawdown__max_depth=-0.905)
        report = narrative.verify(
            _draft("The Sharpe ratio was {{fact:strategy.sharpe}}."), bundle
        )

        assert report.grounded is False
        assert [v.kind for v in report.violations] == [ViolationKind.UNKNOWN_FACT]
        assert "strategy.sharpe" in report.violations[0].detail

    def test_a_bare_numeral_is_rejected(self) -> None:
        """The subtler and more dangerous case: a fluent sentence with an invented number in it.
        Nothing about the prose signals that nobody computed it."""
        report = narrative.verify(
            _draft("The instrument fell 90.5% from its peak."), _bundle()
        )

        assert report.grounded is False
        assert all(v.kind is ViolationKind.BARE_NUMERAL for v in report.violations)
        assert report.violations[0].position == len("The instrument fell ")

    def test_a_number_smuggled_beside_a_valid_citation_is_still_caught(self) -> None:
        """The realistic failure: mostly-correct prose that cites properly and then adds one figure
        of its own. A checker that stopped at the first valid reference would pass this."""
        bundle = _bundle(drawdown__max_depth=-0.905)
        report = narrative.verify(
            _draft("It fell {{fact:drawdown.max_depth}} and recovered within 14 months."), bundle
        )

        assert report.grounded is False
        assert any(v.kind is ViolationKind.BARE_NUMERAL for v in report.violations)
        assert "drawdown.max_depth" in report.cited

    @pytest.mark.parametrize(
        ("codepoint", "name"),
        [
            (0xFF14, "FULLWIDTH DIGIT FOUR"),
            (0x0664, "ARABIC-INDIC DIGIT FOUR"),
            (0x09EA, "BENGALI DIGIT FOUR"),
            (0x1D7DA, "MATHEMATICAL DOUBLE-STRUCK DIGIT TWO"),
        ],
    )
    def test_a_non_ascii_digit_is_caught(self, codepoint: int, name: str) -> None:
        """An ASCII-only scan misses these, and they render as ordinary numbers on screen.

        Written as codepoints rather than literals so the intent is legible and so the linter's own
        ambiguous-character rule -- which is the same instinct this check encodes -- does not have to
        be suppressed.
        """
        char = chr(codepoint)
        report = narrative.verify(_draft(f"The drawdown was {char}0%."), _bundle())

        assert report.grounded is False, f"{name} slipped through"
        assert any(v.kind is ViolationKind.BARE_NUMERAL for v in report.violations)

    def test_a_malformed_reference_is_rejected_rather_than_rendered_literally(self) -> None:
        """Left alone it would print `{{fact:}}` to a reader, or silently drop a figure from a
        sentence that still scans as complete."""
        for text in ("Depth was {{fact:}}.", "Depth was {{fact:Bad.Id}}.", "Depth was {{fact:x"):
            report = narrative.verify(_draft(text), _bundle())
            assert report.grounded is False, text
            assert any(v.kind is ViolationKind.MALFORMED_REFERENCE for v in report.violations), text

    def test_every_violation_is_reported_not_just_the_first(self) -> None:
        """A writer fixing one problem per round trip is a bad experience for a human and five times
        the cost for a model in a loop."""
        report = narrative.verify(
            _draft("It fell 90% over 3 years, per {{fact:nope.missing}}."), _bundle()
        )
        kinds = {v.kind for v in report.violations}
        assert ViolationKind.BARE_NUMERAL in kinds
        assert ViolationKind.UNKNOWN_FACT in kinds
        assert len(report.violations) >= 4  # 9, 0, 3, and the unknown fact

    def test_an_empty_draft_is_not_grounded(self) -> None:
        for text in ("", "   ", "\n\t "):
            report = narrative.verify(_draft(text), _bundle())
            assert report.grounded is False
            assert report.violations[0].kind is ViolationKind.EMPTY


class TestRenderingRequiresVerification:
    """There is no path from an unverified draft to displayable text."""

    def test_render_refuses_an_ungrounded_report(self) -> None:
        bundle = _bundle(a__b=0.5)
        draft = _draft("It was 50%.")
        report = narrative.verify(draft, bundle)

        with pytest.raises(narrative.GroundingError, match="ungrounded"):
            narrative.render(draft, bundle, report)

    def test_render_refuses_a_forged_passing_report(self) -> None:
        """Even handed a hand-built `grounded=True`, the substitution cannot invent a value for a
        fact the bundle does not hold -- so a caller who fakes the check still gets an error rather
        than prose."""
        draft = _draft("It was {{fact:not.here}}.")
        forged = GroundingReport(grounded=True, violations=[], cited=["not.here"])

        with pytest.raises(narrative.GroundingError):
            narrative.render(draft, _bundle(), forged)

    def test_compose_returns_the_report_on_failure_and_the_narrative_on_success(self) -> None:
        """The union return is the enforcement: a caller wanting prose must look at which it got."""
        bundle = _bundle(drawdown__max_depth=-0.905)

        failed = narrative.compose(_draft("It fell 90.5%."), bundle)
        assert isinstance(failed, GroundingReport)
        assert failed.grounded is False

        ok = narrative.compose(_draft("It fell {{fact:drawdown.max_depth}}."), bundle)
        assert isinstance(ok, RenderedNarrative)
        assert ok.text == "It fell -90.5%."
        assert ok.grounding.grounded is True

    def test_a_rendered_narrative_carries_the_facts_it_used(self) -> None:
        bundle = _bundle(drawdown__max_depth=-0.905, sample__bars="6897")
        result = narrative.compose(
            _draft("Over {{fact:sample.bars}} sessions it fell {{fact:drawdown.max_depth}}."),
            bundle,
        )
        assert isinstance(result, RenderedNarrative)
        assert [f.id for f in result.cited_facts] == ["sample.bars", "drawdown.max_depth"]


class TestProseCannotDriftFromData:
    """The reason a narrative stores a template rather than finished text."""

    def test_the_same_draft_renders_differently_when_the_data_moves(self) -> None:
        """A draft that had quoted `-90.5%` directly would be frozen at the moment someone wrote it
        and silently wrong afterwards. This is what makes a stale report worse than no report."""
        draft = _draft("The deepest decline was {{fact:drawdown.max_depth}}.")

        before = narrative.compose(draft, _bundle(drawdown__max_depth=-0.905))
        after = narrative.compose(draft, _bundle(drawdown__max_depth=-0.421))

        assert isinstance(before, RenderedNarrative)
        assert isinstance(after, RenderedNarrative)
        assert before.text == "The deepest decline was -90.5%."
        assert after.text == "The deepest decline was -42.1%."

    def test_a_draft_stops_verifying_when_its_fact_disappears(self) -> None:
        """Loudly, rather than rendering a sentence with a hole in it."""
        draft = _draft("The deepest decline was {{fact:drawdown.max_depth}}.")
        assert isinstance(narrative.compose(draft, _bundle()), GroundingReport)


class TestFormatting:
    """Formatting lives with the fact so one figure cannot appear two ways in one report."""

    @pytest.mark.parametrize(
        ("kind", "value", "expected"),
        [
            (FactKind.PERCENT, 0.0583, "5.8%"),
            (FactKind.PERCENT, -0.905, "-90.5%"),
            (FactKind.SIGNED_PERCENT, 0.0583, "+5.8%"),
            (FactKind.SIGNED_PERCENT, -0.0583, "-5.8%"),
            (FactKind.RATIO, 1.4567, "1.46"),
            (FactKind.CURRENCY, 1234.5, "$1,234.50"),
            (FactKind.COUNT, 6897, "6,897"),
            (FactKind.TEXT, "SOXL", "SOXL"),
        ],
    )
    def test_kinds_render_as_declared(
        self, kind: FactKind, value: float | str, expected: str
    ) -> None:
        fact = Fact(id="x", label="x", value=value, kind=kind, source="test")
        assert narrative.format_fact(fact) == expected

    def test_none_is_an_em_dash_in_every_kind(self) -> None:
        """Never a zero. A statistic that could not be measured rendered as `0.0%` is a claim."""
        for kind in FactKind:
            fact = Fact(id="x", label="x", value=None, kind=kind, source="test")
            assert narrative.format_fact(fact) == "—"

    def test_nan_and_infinity_render_as_an_em_dash_not_as_a_broken_token(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            fact = Fact(id="x", label="x", value=value, kind=FactKind.PERCENT, source="test")
            assert narrative.format_fact(fact) == "—"

    def test_a_null_valued_fact_is_still_citable(self) -> None:
        """Because the alternative is prose that silently omits a sentence when data is missing,
        which reads as though the question was never asked."""
        bundle = FactBundle(
            symbol="TEST",
            interval=Interval.DAY,
            generated_at=dt.datetime.now(dt.UTC),
            facts={
                "s.sharpe": Fact(
                    id="s.sharpe", label="Sharpe", value=None, kind=FactKind.RATIO, source="test"
                )
            },
        )
        result = narrative.compose(_draft("Sharpe came out {{fact:s.sharpe}}."), bundle)
        assert isinstance(result, RenderedNarrative)
        assert result.text == "Sharpe came out —."


class TestTheDefaultNarratorIsNotExempt:
    """The templates in `narrative.py` go through the identical verification. They are written by
    hand against ids the builder emits, and the two drift the moment either changes -- this turns
    that drift into a failing test rather than a report sentence reading `{{fact:...}}`."""

    def test_every_default_narrator_produces_a_grounded_draft(self) -> None:
        bundle = _bundle(
            instrument__name="SOXL",
            instrument__symbol="SOXL",
            sample__bars="4129",
            sample__first_bar="2010-03-11",
            sample__last_bar="2026-08-10",
            drawdown__basis="close",
            drawdown__max_depth=-0.905,
            drawdown__peak_date="2021-12-27",
            drawdown__trough_date="2022-10-14",
            drawdown__bars_to_recovery="1075",
            drawdown__episodes="102",
            rules__total="12",
            rules__firing="3",
            rules__best_horizon="20",
            rules__best_rule="RSI oversold",
            rules__best_edge=-0.036,
            rules__best_baseline=0.58,
            rules__best_independent_n="112",
            rules__best_significance="insufficient",
        )
        for name, narrator in narrative.DEFAULT_NARRATORS.items():
            draft = narrator(bundle)  # type: ignore[operator]
            report = narrative.verify(draft, bundle)
            assert report.grounded, f"{name}: {[v.detail for v in report.violations]}"

    def test_a_narrator_drops_sentences_whose_facts_are_missing(self) -> None:
        """Rather than rendering "the deepest drawdown was —", which reads as a measurement that came
        out blank instead of a question that was never answerable."""
        sparse = _bundle(drawdown__basis="close", drawdown__episodes="4")
        draft = narrative.draft_drawdown(sparse)

        assert narrative.verify(draft, sparse).grounded
        assert "deepest decline" not in draft.text
        assert "distinct drawdown" in draft.text

    def test_a_narrator_given_nothing_produces_an_empty_draft_that_fails_verification(self) -> None:
        """Not a silent success. An empty narrative is not a grounded one."""
        empty = _bundle()
        report = narrative.verify(narrative.draft_drawdown(empty), empty)
        assert report.grounded is False
        assert report.violations[0].kind is ViolationKind.EMPTY

    def test_the_narrators_write_no_numerals_of_their_own(self) -> None:
        """Checked against the source templates directly, so a future edit that types a number into
        a sentence fails here rather than at render time on one particular symbol."""
        rich = _bundle(
            instrument__name="X", instrument__symbol="X", sample__bars="1",
            sample__first_bar="a", sample__last_bar="b", drawdown__basis="close",
            drawdown__max_depth=-0.5, drawdown__peak_date="a", drawdown__trough_date="b",
            drawdown__bars_to_recovery="1", drawdown__episodes="1", rules__total="1",
            rules__firing="1", rules__best_horizon="1", rules__best_rule="r",
            rules__best_edge=0.1, rules__best_baseline=0.5, rules__best_independent_n="1",
            rules__best_significance="weak",
        )
        for name, narrator in narrative.DEFAULT_NARRATORS.items():
            text = narrator(rich).text  # type: ignore[operator]
            stripped = narrative._REFERENCE.sub("", text)
            assert not any(narrative._is_digit(c) for c in stripped), name


class TestEvidenceProseCarriesItsOwnCaveats:
    """The evidence sentence is the one most able to mislead, so what it must say is pinned."""

    @staticmethod
    def _rules_bundle(firing: int, significance: str = "weak") -> FactBundle:
        return _bundle(
            rules__total=12.0,
            rules__firing=float(firing),
            rules__best_horizon="20",
            rules__best_rule="EMA 50/200 Golden Cross",
            rules__best_edge=0.291,
            rules__best_baseline=0.584,
            rules__best_independent_n="8",
            rules__best_significance=significance,
        )

    def test_a_single_firing_rule_reads_as_is_not_are(self) -> None:
        """A narrator may read a count to pick a verb; it just may not write the count. Skipping
        this produces "1 rules are currently firing", which reads as a broken report."""
        text = narrative.draft_evidence(self._rules_bundle(1)).text
        assert "{{fact:rules.firing}} is currently firing" in text
        assert "are currently firing" not in text

    def test_several_firing_rules_read_as_are(self) -> None:
        text = narrative.draft_evidence(self._rules_bundle(3)).text
        assert "{{fact:rules.firing}} are currently firing" in text

    def test_the_largest_edge_is_never_stated_without_its_grade_and_sample(self) -> None:
        """A big edge on few observations is what noise produces. The number and the verdict must
        travel together or the sentence is an advertisement."""
        text = narrative.draft_evidence(self._rules_bundle(1)).text
        assert "{{fact:rules.best_edge}}" in text
        assert "{{fact:rules.best_significance}}" in text
        assert "{{fact:rules.best_independent_n}}" in text

    def test_the_selection_effect_is_spelled_out(self) -> None:
        """Picking the maximum across twelve rules is a selection procedure with no correction, and
        the report says so rather than leaving the reader to notice."""
        text = narrative.draft_evidence(self._rules_bundle(1)).text
        assert "not the same as having the best evidence" in text
        assert "fewest observations" in text

    def test_the_edge_sentence_disappears_when_the_grade_is_missing(self) -> None:
        """The grade is a required companion, so an incomplete bundle drops the whole claim rather
        than reporting the flattering half of it."""
        partial = _bundle(
            rules__total=12.0,
            rules__firing=1.0,
            rules__best_horizon="20",
            rules__best_rule="X",
            rules__best_edge=0.291,
            rules__best_baseline=0.584,
            rules__best_independent_n="8",
        )
        text = narrative.draft_evidence(partial).text
        assert "largest measured edge" not in text
        assert "currently firing" in text


class TestCaveatIsAlwaysPresent:
    def test_a_passing_report_states_what_it_did_not_verify(self) -> None:
        """A green check that implies more than it verified is worse than no check."""
        bundle = _bundle(a__b=0.5)
        report = narrative.verify(_draft("It was {{fact:a.b}}."), bundle)
        assert report.grounded
        assert "verbal quantities" in report.caveat

    def test_a_verbal_quantity_passes_and_that_is_a_known_limit(self) -> None:
        """Documented rather than hidden: this check is a guarantee about numerals, not about
        truthfulness."""
        report = narrative.verify(
            _draft("The decline was roughly a third and recovery took nearly forever."), _bundle()
        )
        assert report.grounded is True


class TestUntrustedDraftsCarryTheirProvenance:
    """QA defect: a valid citation captioned as a completely different metric.

    ``verify`` can confirm ``{{fact:rules.best_edge}}`` resolves; it cannot confirm that "a Sharpe
    ratio of" is an honest description of what ``rules.best_edge`` measures, because nothing here
    reads the sentence around the reference -- and parsing prose to catch a mismatch like that is an
    unwinnable problem, not a missing feature. The fix is not a smarter checker; it is a rendering
    change: an untrusted draft's substituted value carries its fact's own label, so a mislabeled
    citation contradicts itself on the page where a reader can see it.
    """

    @staticmethod
    def _edge_bundle() -> FactBundle:
        return FactBundle(
            symbol="TEST",
            interval=Interval.DAY,
            generated_at=dt.datetime.now(dt.UTC),
            facts={
                "rules.best_edge": Fact(
                    id="rules.best_edge",
                    label="Best edge",
                    value=0.036,
                    kind=FactKind.PERCENT,
                    source="test",
                )
            },
        )

    def test_a_valid_but_mislabeled_citation_is_self_contradicting_once_rendered(self) -> None:
        """The exact QA reproduction: `rules.best_edge` is a hit-rate edge against a baseline, cited
        under a claim that it is a Sharpe ratio. `verify` still passes it -- the id resolves -- but
        the rendered text now reads "a Sharpe ratio of 3.6% (Best edge)", which announces its own
        problem instead of reading as an authoritative, unexamined figure."""
        bundle = self._edge_bundle()
        draft = _llm_draft(
            "The strategy delivered a Sharpe ratio of {{fact:rules.best_edge}}, an exceptional "
            "risk-adjusted outcome that beat every benchmark."
        )
        result = narrative.compose(draft, bundle)

        assert isinstance(result, RenderedNarrative)
        assert result.grounding.grounded is True  # verify() only ever checked that the id resolves
        assert "3.6% (Best edge)" in result.text

    def test_a_template_draft_keeps_rendering_bare_values(self) -> None:
        """The shipped narrators are hand-verified against the ids they cite, so appending a label
        to a pairing someone already checked by hand would be pure noise. Pins that `source="template"`
        stays exempt now that non-template sources are not."""
        bundle = self._edge_bundle()
        draft = _draft("The best measured edge was {{fact:rules.best_edge}}.")
        result = narrative.compose(draft, bundle)

        assert isinstance(result, RenderedNarrative)
        assert result.text == "The best measured edge was 3.6%."

    def test_a_null_valued_fact_in_an_untrusted_draft_still_carries_its_label(self) -> None:
        """The em-dash case is not special-cased away: a missing measurement mislabeled is just as
        misleading as a present one, so the label still rides along."""
        bundle = FactBundle(
            symbol="TEST",
            interval=Interval.DAY,
            generated_at=dt.datetime.now(dt.UTC),
            facts={
                "s.sharpe": Fact(
                    id="s.sharpe", label="Sharpe", value=None, kind=FactKind.RATIO, source="test"
                )
            },
        )
        result = narrative.compose(_llm_draft("Sharpe came out {{fact:s.sharpe}}."), bundle)
        assert isinstance(result, RenderedNarrative)
        assert result.text == "Sharpe came out — (Sharpe)."


class TestBraceLookalikesAreNotInvisible:
    """QA defect: full-width brace lookalikes bypass both detectors and reach rendered output.

    ``{{``/``}}`` are ASCII by construction, but a reader cannot visually distinguish them from
    fullwidth or other compatibility forms of the same glyph. Left unhandled, a reference written with
    one of those was invisible to every scan here -- not flagged as malformed, not resolved, not
    rejected -- and rode into rendered output as an unexamined, reference-shaped payload.
    """

    def test_a_fullwidth_braced_reference_to_a_missing_fact_is_rejected(self) -> None:
        """The exact QA reproduction: no ASCII digits, no ASCII braces, previously grounded=True with
        an empty ``cited`` list -- the scan did not even notice a reference-shaped payload was there."""
        text = (
            f"It fell {chr(0xFF5B)}{chr(0xFF5B)}fact:drawdown.max_depth{chr(0xFF5D)}{chr(0xFF5D)} "
            "hard, no digits here at all."
        )
        report = narrative.verify(_draft(text), _bundle())

        assert report.grounded is False
        assert any(v.kind is ViolationKind.UNKNOWN_FACT for v in report.violations)
        assert "drawdown.max_depth" in report.cited

    def test_a_fullwidth_braced_reference_to_a_real_fact_resolves_and_renders(self) -> None:
        """Not merely rejected outright: judged exactly as its ASCII twin would be, including
        rendering correctly -- with the lookalike braces gone -- when the bundle does hold the fact."""
        bundle = _bundle(drawdown__max_depth=-0.905)
        text = f"It fell {chr(0xFF5B)}{chr(0xFF5B)}fact:drawdown.max_depth{chr(0xFF5D)}{chr(0xFF5D)}."
        result = narrative.compose(_draft(text), bundle)

        assert isinstance(result, RenderedNarrative)
        assert result.text == "It fell -90.5%."
        assert chr(0xFF5B) not in result.text
        assert chr(0xFF5D) not in result.text

    def test_a_malformed_fullwidth_reference_is_caught_too(self) -> None:
        """The malformed-reference scan is folded the same way, so a broken id inside lookalike braces
        is refused rather than silently ignored as ordinary text."""
        text = f"Depth was {chr(0xFF5B)}{chr(0xFF5B)}fact:{chr(0xFF5D)}{chr(0xFF5D)}."
        report = narrative.verify(_draft(text), _bundle())

        assert report.grounded is False
        assert any(v.kind is ViolationKind.MALFORMED_REFERENCE for v in report.violations)

    def test_small_form_and_vertical_presentation_lookalikes_are_caught_too(self) -> None:
        """Fullwidth is the reproduced case; the fold covers the other compatibility forms Unicode
        declares equivalent to a curly brace the same way, not just the one QA happened to try."""
        for open_char, close_char, name in (
            (chr(0xFE5B), chr(0xFE5C), "SMALL"),
            (chr(0xFE37), chr(0xFE38), "VERTICAL PRESENTATION"),
        ):
            text = f"It fell {open_char}{open_char}fact:drawdown.max_depth{close_char}{close_char}."
            report = narrative.verify(_draft(text), _bundle())
            assert report.grounded is False, name
            assert any(v.kind is ViolationKind.UNKNOWN_FACT for v in report.violations), name


class TestNumericLookalikesBeyondDecimalDigits:
    """QA defect: numeric characters outside category ``Nd`` render as readable numbers and pass.

    The module's own stated rationale for checking Unicode category rather than ``0-9`` -- these
    characters "render as readable numbers... an ASCII-only check waves them through" -- covers more
    than category ``Nd``. Roman numerals (``Nl``) and circled digits, fractions, and superscripts
    (``No``) read as numbers just as plainly and were being waved through by an ``Nd``-only check.
    """

    @pytest.mark.parametrize(
        ("codepoint", "name", "sentence"),
        [
            (0x2460, "CIRCLED DIGIT ONE", "This rule placed {c} among all candidates screened."),
            (
                0x00BD,
                "VULGAR FRACTION ONE HALF",
                "It recovered {c} of the drawdown within the quarter.",
            ),
            (0x216B, "ROMAN NUMERAL TWELVE", "The strategy ranked {c} among all catalogued rules."),
            (0x00B2, "SUPERSCRIPT TWO", "The exposure was raised to the {c} power that quarter."),
        ],
    )
    def test_a_non_decimal_numeric_character_is_caught(
        self, codepoint: int, name: str, sentence: str
    ) -> None:
        """Written as codepoints rather than literals for the same reason `test_a_non_ascii_digit_is_
        caught` is: legible intent without tripping the linter's own ambiguous-character rule."""
        char = chr(codepoint)
        report = narrative.verify(_draft(sentence.format(c=char)), _bundle())

        assert report.grounded is False, f"{name} slipped through"
        assert any(v.kind is ViolationKind.BARE_NUMERAL for v in report.violations)


class TestKnownGaps:
    """Failure modes this module knowingly does not close, pinned so each is a recorded decision
    rather than an assumption nobody checked. Referenced from the module docstring."""

    def test_hedges_wrapped_around_a_valid_reference_still_pass(self) -> None:
        """QA reproduced three variants of a hedge rewriting what a valid reference asserts, against
        an exact fact `drawdown.max_depth = -0.905`. Declined rather than patched: the set of
        modifiers that change a number's meaning without touching its digits is open-ended, and a
        deny-list of hedge phrases is an arms race against phrasing, not a check -- the same kind of
        "read the prose and decide" problem the module's other docstrings already reject as
        unwinnable for the mislabeled-citation defect. Pinned here rather than merely assumed, so a
        future change that starts catching some of these is a deliberate decision, not a surprise."""
        bundle = _bundle(drawdown__max_depth=-0.905)
        hedged = [
            "The drawdown was at least {{fact:drawdown.max_depth}}, likely worse intraday.",
            "The drawdown sits at {{fact:drawdown.max_depth}} and rising.",
            "A conservative estimate puts the drawdown at {{fact:drawdown.max_depth}}.",
        ]
        for text in hedged:
            report = narrative.verify(_draft(text), bundle)
            assert report.grounded is True, text
