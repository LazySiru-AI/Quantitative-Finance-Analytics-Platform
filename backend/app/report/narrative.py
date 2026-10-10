"""The grounding contract: prose may cite computed facts and may not write numbers.

This module is the enforcement point named in :mod:`app.report`'s docstring. It does three things,
in a fixed order, and the order is the design.

1. :func:`verify` refuses a draft that names a fact the bundle does not hold, that writes a bare
   numeral, or that contains something shaped like a reference but malformed.
2. :func:`render` substitutes values, and **only accepts a draft that verified**. There is no
   function here that renders unverified text.
3. :func:`compose` runs both and returns a :class:`~app.report.models.RenderedNarrative`, which
   therefore cannot exist without a passing :class:`~app.report.models.GroundingReport`.

**Why a checker rather than a prompt.** "Only cite figures from the bundle" is an instruction a
language model follows most of the time. The failures are not obvious ones -- they are fluent,
plausible sentences containing a number nobody computed, which is the single hardest kind of error
for a reader to catch, because everything about the sentence signals that someone did the work. A
checker fails on those in the same way it fails on nonsense.

**Why bare numerals are refused outright.** The alternative is deciding, per number, whether the
writer had a source for it -- and that decision cannot be made by reading the text, which is the
whole problem. Refusing every digit outside a reference makes the rule mechanical. It costs the
builder some work: a parameter that legitimately belongs in prose, like the 50 in a 50/200
crossover, has to be emitted as a fact. That cost is the point. It forces someone to decide, in
advance and in code, what the report is allowed to say.

**Numerals are matched by Unicode category, not by ``0-9``.** U+0664 (Arabic-Indic four) and U+FF14
(fullwidth four) are decimal digits (category ``Nd``): they render as readable numbers and ``int()``
parses them, but an ASCII-only check waves them through. The same reasoning extends past ``Nd``:
U+00B2 (superscript two) and U+2461 (circled digit two) are category ``No``, and U+216B (Roman
numeral twelve) is category ``Nl`` -- none are ``0-9``, all read as a number to anyone looking at the
screen. ``_is_digit`` tests all three categories. The characters are named by codepoint here rather
than written out because a linter -- correctly -- flags ambiguous Unicode in source, which is the
same instinct this check encodes.

**The reference delimiter gets the same treatment.** ``{{`` and ``}}`` are ASCII by construction, but
U+FF5B/U+FF5D (fullwidth curly brackets) and a handful of other compatibility and presentation forms
render as ordinary braces to a reader while an ASCII-only scan does not recognize them at all -- not
as a reference, not as a malformed one, just as inert text a number quietly rode in on.
``_fold_braces`` maps the known lookalikes onto ASCII before either the reference or the malformed-
reference scan runs, so a lookalike-delimited citation is judged exactly as its ASCII twin would be:
resolved if the bundle holds the fact, refused if it does not.

**What this does not catch, stated in the report itself.** "Roughly a third", "nearly doubled",
"catastrophic" -- verbal quantities carry no digits and pass.
:attr:`~app.report.models.GroundingReport.caveat` says so on every report, because a green check
that implies more than it verified is worse than no check.

**Also not caught: a hedge wrapped around a valid reference.** "At least {{fact:drawdown.max_depth}},
likely worse intraday" cites a real fact and then rewrites what it asserts about that fact in the
words around it. This is deliberately not checked. The set of modifiers that change a number's
meaning without touching its digits is open-ended, and a deny-list of hedge phrases is an arms race
against phrasing, not a check -- exactly the kind of "read the prose and decide" problem the module's
other docstrings already reject as unwinnable. A narrative can therefore still say a computed number
is "at least", "roughly", or "a conservative estimate" of itself; :func:`verify` only guarantees that
the numeral came from the bundle, never that the sentence around it is honest about what the numeral
means. See ``TestKnownGaps`` in the test module for the reproduced cases this leaves open.

**What an untrusted draft's rendering adds, and why.** :func:`verify` can confirm a cited id resolves;
it cannot confirm the id matches what the surrounding sentence claims about it -- "a Sharpe ratio of
{{fact:rules.best_edge}}" verifies cleanly even though ``rules.best_edge`` is a hit-rate edge, not a
Sharpe ratio, because nothing here reads prose. Parsing the sentence to catch that is the same
unwinnable problem as the hedge-word case above. So :func:`render` does not try: for a draft whose
``source`` is not ``"template"`` -- the shipped narrators are deterministic templates and are hand-
verified against the ids they cite; anything else is treated as unverified, e.g. LLM-authored, prose
-- every substituted value carries its fact's own label alongside it. A mislabeled citation then reads
as self-contradicting on the page itself, where a reader can catch it, instead of merely passing a
check and being discarded. Template narrators keep rendering bare values, because appending a label
to prose already checked by hand against the correct id is pure noise.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping

from app.market.models import jsonable_float
from app.report.models import (
    FACT_REFERENCE_PATTERN,
    Fact,
    FactBundle,
    FactKind,
    GroundingReport,
    GroundingViolation,
    NarrativeDraft,
    RenderedNarrative,
    ViolationKind,
)

__all__ = [
    "DEFAULT_NARRATORS",
    "SECTION_TITLES",
    "GroundingError",
    "Narrator",
    "compose",
    "format_fact",
    "render",
    "verify",
]

#: A narrator turns a bundle into a draft. Nothing more: it may not fetch, compute or format.
type Narrator = Callable[[FactBundle], NarrativeDraft]

_REFERENCE = re.compile(FACT_REFERENCE_PATTERN)

#: Anything opening a reference. Used to find malformed ones -- a `{{` that `_REFERENCE` did not
#: match is a mistake, and letting it render as literal text would put `{{fact:whatever}}` in front
#: of a reader, or worse, quietly drop a number from a sentence that still reads as complete.
_ANY_BRACE = re.compile(r"\{\{.*?(?:\}\}|$)", re.DOTALL)

#: How much context to show either side of a violation.
_EXCERPT_PAD = 24

#: Codepoints that a reader sees as an ordinary curly brace and that Unicode itself declares
#: equivalent to one -- each has a compatibility decomposition to ``{``/``}`` (fullwidth, small-form,
#: and vertical-presentation variants), which is exactly what ``unicodedata.normalize("NFKC", ...)``
#: folds. There is no single Unicode category for "brace" the way ``Nd``/``Nl``/``No`` cover digits,
#: so this table is that same idea built by hand: every entry was checked against NFKC folding to
#: ``{`` or ``}`` rather than picked by eye -- deliberately not including glyphs that merely look
#: similar (e.g. the dingbat "ornament" brackets), since those have no such decomposition and
#: including them would be exactly the eyeballing this table exists to avoid. Named by codepoint,
#: never pasted as the glyph, for the reason given in the module docstring -- this is exactly the
#: ambiguous-character situation the linter's own rule exists to flag.
_BRACE_LOOKALIKES: dict[str, str] = {
    chr(0xFF5B): "{",  # FULLWIDTH LEFT CURLY BRACKET
    chr(0xFF5D): "}",  # FULLWIDTH RIGHT CURLY BRACKET
    chr(0xFE5B): "{",  # SMALL LEFT CURLY BRACKET
    chr(0xFE5C): "}",  # SMALL RIGHT CURLY BRACKET
    chr(0xFE37): "{",  # PRESENTATION FORM FOR VERTICAL LEFT CURLY BRACKET
    chr(0xFE38): "}",  # PRESENTATION FORM FOR VERTICAL RIGHT CURLY BRACKET
}

_BRACE_TRANSLATION = str.maketrans(_BRACE_LOOKALIKES)


class GroundingError(ValueError):
    """Raised when rendering is attempted on a draft that did not verify.

    A distinct type so a caller cannot conflate "this narrative is ungrounded" with any other
    ``ValueError`` from the formatting path and handle both the same way.
    """


#: Unicode general categories that render as a number to a reader. ``Nd`` (decimal digit, e.g.
#: U+FF14 fullwidth four) is the obvious one; ``Nl`` (letterlike numeral, e.g. U+216B Roman numeral
#: twelve) and ``No`` (every other numeric form, e.g. U+00B2 superscript two, U+2461 circled digit
#: two, U+00BD vulgar fraction one half) read just as plainly as a number even though ``int()`` will
#: not parse most of them. Restricting the check to ``Nd`` alone is exactly the ASCII-only mistake
#: this function exists to avoid, one category short.
_NUMERIC_CATEGORIES = frozenset({"Nd", "Nl", "No"})


def _is_digit(char: str) -> bool:
    """True for any Unicode character that renders as a number, not merely ASCII ``0-9``.

    U+0664 and U+FF14 are digits to a reader and to ``int()``, so an ASCII-only check would pass a
    draft that renders as a perfectly ordinary number on screen. Widened past category ``Nd`` to
    ``Nl`` and ``No`` for the same reason: a Roman numeral, a circled digit, or a superscript reads as
    a number just as readily and an ``Nd``-only check would wave all three through.
    """
    return unicodedata.category(char) in _NUMERIC_CATEGORIES


def _fold_braces(text: str) -> str:
    """Map brace lookalikes onto ASCII ``{``/``}`` so the reference scan sees what a reader sees.

    A one-for-one character translation, not ``unicodedata.normalize("NFKC", text)``: NFKC also folds
    ligatures and other compatibility forms that have nothing to do with braces, which can change the
    string's length and shift every ``match.span()`` computed against the folded text away from the
    character actually written in the draft. Restricting the table to brace lookalikes keeps the
    folded text exactly as long as the original, so positions found in it still index correctly into
    the draft's real text -- which is what excerpts and violation offsets are built from.
    """
    return text.translate(_BRACE_TRANSLATION)


def _excerpt(text: str, start: int, end: int) -> str:
    left = max(0, start - _EXCERPT_PAD)
    right = min(len(text), end + _EXCERPT_PAD)
    prefix = "…" if left > 0 else ""
    suffix = "…" if right < len(text) else ""
    return f"{prefix}{text[left:right]}{suffix}".replace("\n", " ")


def verify(draft: NarrativeDraft, bundle: FactBundle) -> GroundingReport:
    """Check a draft against the bundle. Never raises; a failure is a report.

    Collects **every** violation rather than stopping at the first. A writer -- human or model --
    fixing one problem at a time through five round trips is a worse experience than seeing all five,
    and for a model in a loop it is five times the cost for the same outcome.
    """
    text = draft.text
    violations: list[GroundingViolation] = []

    if not text.strip():
        return GroundingReport(
            grounded=False,
            violations=[
                GroundingViolation(
                    kind=ViolationKind.EMPTY,
                    detail="the draft is empty; an empty narrative is not a grounded one",
                    position=0,
                )
            ],
            cited=[],
        )

    # Fold lookalike braces (fullwidth, small-form, vertical, ornamental) onto ASCII before either
    # scan below runs. Translation is length-preserving (see `_fold_braces`), so every span found
    # against `folded` still indexes correctly into `text` for excerpts and reported positions. This
    # is what makes a reference delimited with e.g. U+FF5B/U+FF5D judged exactly as its ASCII twin
    # would be, instead of being invisible to both the reference and the malformed-reference scan --
    # which is how such a payload previously reached rendered output unexamined.
    folded = _fold_braces(text)

    # Malformed references first: a `{{...}}` span that the strict pattern rejected. Found before
    # the numeral scan so `{{fact:bad id}}` is reported as a malformed reference rather than as
    # whatever its contents happen to look like.
    valid_spans: list[tuple[int, int]] = [m.span() for m in _REFERENCE.finditer(folded)]
    for match in _ANY_BRACE.finditer(folded):
        if match.span() in valid_spans:
            continue
        violations.append(
            GroundingViolation(
                kind=ViolationKind.MALFORMED_REFERENCE,
                detail=(
                    # Sliced from `text`, not `match.group(0)`, so a lookalike-braced payload is
                    # quoted back to the writer as they actually typed it rather than as its folded
                    # ASCII stand-in.
                    f"{text[match.start():match.end()]!r} is not a valid fact reference; the only "
                    "accepted form is {{fact:some.id}} with a lowercase dotted id"
                ),
                position=match.start(),
                excerpt=_excerpt(text, match.start(), match.end()),
            )
        )

    # Unknown facts.
    cited: list[str] = []
    for match in _REFERENCE.finditer(folded):
        fact_id = match.group(1)
        if fact_id not in cited:
            cited.append(fact_id)
        if bundle.get(fact_id) is None:
            violations.append(
                GroundingViolation(
                    kind=ViolationKind.UNKNOWN_FACT,
                    detail=(
                        f"no computed fact {fact_id!r}; the prose asserted a figure nothing in this "
                        "report produced"
                    ),
                    position=match.start(),
                    excerpt=_excerpt(text, match.start(), match.end()),
                )
            )

    # Bare numerals, anywhere outside a valid reference. Spans are checked rather than the text
    # being stripped and re-scanned, so reported positions point into the original draft.
    for index, char in enumerate(text):
        if not _is_digit(char):
            continue
        if any(start <= index < end for start, end in valid_spans):
            continue
        violations.append(
            GroundingViolation(
                kind=ViolationKind.BARE_NUMERAL,
                detail=(
                    f"the digit {char!r} appears outside a fact reference; every number in a "
                    "narrative must arrive through {{fact:...}} so it cannot drift from the data "
                    "or be invented"
                ),
                position=index,
                excerpt=_excerpt(text, index, index + 1),
            )
        )

    return GroundingReport(grounded=not violations, violations=violations, cited=cited)


def format_fact(fact: Fact) -> str:
    """Render one fact's value by its declared kind.

    Formatting lives here and on the fact, never at a call site, so the same figure cannot appear as
    ``0.058`` in one sentence and ``5.8%`` in another. ``None`` is an em dash in every kind: a
    statistic that could not be measured must never render as a zero, which is a claim.
    """
    value = fact.value
    if value is None:
        return "—"
    if isinstance(value, str):
        return value

    numeric = jsonable_float(float(value))
    if numeric is None:
        # NaN or infinity reached a fact. Rendering it as "nan" would put a broken token in prose;
        # an em dash says the same thing the None case does, which is what this actually is.
        return "—"

    match fact.kind:
        case FactKind.PERCENT:
            return f"{numeric * 100:.1f}%"
        case FactKind.SIGNED_PERCENT:
            return f"{numeric * 100:+.1f}%"
        case FactKind.RATIO:
            return f"{numeric:.2f}"
        case FactKind.CURRENCY:
            return f"${numeric:,.2f}"
        case FactKind.COUNT:
            return f"{round(numeric):,}"
        case FactKind.DATE | FactKind.TEXT:
            return str(value)


def render(draft: NarrativeDraft, bundle: FactBundle, grounding: GroundingReport) -> str:
    """Substitute fact values into a draft. **Requires a passing report.**

    Taking the :class:`~app.report.models.GroundingReport` as an argument rather than recomputing it
    is deliberate: it makes "was this verified?" a thing the caller must already have an answer to,
    instead of a step that can be skipped. Passing a failing report raises rather than rendering
    partial prose, because a paragraph with one ungrounded figure removed still reads as complete.

    For ``draft.source == "template"`` a citation renders as a bare value, e.g. ``-90.5%``. For any
    other source it renders with its fact's own label attached, e.g. ``-90.5% (deepest drawdown)`` --
    see the module docstring's "What an untrusted draft's rendering adds" section for why: `verify`
    can confirm an id resolves but not that the prose around it describes what the fact means, and a
    mislabeled citation is meant to be visibly wrong on the page rather than merely unchecked.
    """
    if not grounding.grounded:
        kinds = ", ".join(sorted({v.kind.value for v in grounding.violations}))
        raise GroundingError(
            f"refusing to render an ungrounded narrative ({len(grounding.violations)} violation(s): "
            f"{kinds}); see GroundingReport.violations"
        )

    def substitute(match: re.Match[str]) -> str:
        fact = bundle.get(match.group(1))
        if fact is None:  # pragma: no cover - verify() already refused this
            raise GroundingError(f"fact {match.group(1)!r} vanished between verification and render")
        value = format_fact(fact)
        if draft.source == "template":
            # Hand-written and hand-verified against the ids it cites; a label alongside the value
            # would be pure noise, since the whole point of a template is that the pairing was
            # checked by the person who wrote it.
            return value
        # Untrusted draft: `verify` only confirmed this id resolves, not that the sentence around it
        # describes what the fact actually measures -- "a Sharpe ratio of {{fact:rules.best_edge}}"
        # verifies cleanly even when `rules.best_edge` is a hit-rate edge, because nothing here reads
        # prose. Parsing the sentence to catch that is unwinnable in general, so instead the fact's
        # own label rides along with its value: a mislabeled citation then reads as self-contradicting
        # on the page -- "a Sharpe ratio of 3.6% (best edge)" -- where a reader can catch it, rather
        # than passing a check and being discarded.
        return f"{value} ({fact.label})"

    # Fold lookalike braces before substituting, matching the scan `verify` just ran -- otherwise a
    # reference written with e.g. U+FF5B/U+FF5D would have been judged (correctly) as a real citation
    # but would then survive into the output unsubstituted, because `_REFERENCE` alone never matched
    # its ASCII-only pattern against the original glyphs.
    return _REFERENCE.sub(substitute, _fold_braces(draft.text))


def compose(draft: NarrativeDraft, bundle: FactBundle) -> RenderedNarrative | GroundingReport:
    """Verify then render. Returns the narrative on success, the failing report on refusal.

    The union return is the whole point: a caller that wants prose has to look at which of the two
    it got, and the object carrying rendered text cannot be constructed any other way. Returning an
    optional narrative plus a separate report would let a caller ignore the report.
    """
    grounding = verify(draft, bundle)
    if not grounding.grounded:
        return grounding

    cited_facts = [f for f in (bundle.get(i) for i in grounding.cited) if f is not None]
    return RenderedNarrative(
        text=render(draft, bundle, grounding),
        draft=draft,
        grounding=grounding,
        cited_facts=cited_facts,
    )


# ---------------------------------------------------------------------------
# The default narrator
# ---------------------------------------------------------------------------
#
# Deterministic, and it goes through the identical verification path -- no bypass for "our own"
# prose. That is not ceremony: these templates are written by hand against fact ids that the builder
# emits, and the two drift the moment either changes. Running them through `verify` turns that drift
# into a failing test rather than a report sentence reading "the deepest drawdown was {{fact:...}}".


def _sentence(template: str, bundle: FactBundle, required: tuple[str, ...]) -> str | None:
    """A template, or ``None`` when the bundle lacks a fact it needs.

    Dropping the sentence is the correct behaviour and the alternative is worse: rendering it with an
    em dash produces "the deepest drawdown was —", which reads as a measurement that came out blank
    rather than as a question that was never answerable on this data.
    """
    if any(bundle.get(fact_id) is None for fact_id in required):
        return None
    if any(bundle.facts[fact_id].value is None for fact_id in required):
        return None
    return template


def draft_overview(bundle: FactBundle) -> NarrativeDraft:
    """Prose for the report's summary section, built from whatever the bundle actually holds."""
    parts = [
        _sentence(
            "{{fact:instrument.name}} ({{fact:instrument.symbol}}) is covered here over "
            "{{fact:sample.bars}} stored sessions, from {{fact:sample.first_bar}} to "
            "{{fact:sample.last_bar}}.",
            bundle,
            ("instrument.name", "instrument.symbol", "sample.bars", "sample.first_bar",
             "sample.last_bar"),
        ),
        _sentence(
            "Every figure below is conditional on that window.",
            bundle,
            (),
        ),
    ]
    return NarrativeDraft(text=" ".join(p for p in parts if p), source="template")


def draft_drawdown(bundle: FactBundle) -> NarrativeDraft:
    """Prose for the drawdown section."""
    parts = [
        _sentence(
            "The deepest decline on a {{fact:drawdown.basis}} basis was "
            "{{fact:drawdown.max_depth}}, running from {{fact:drawdown.peak_date}} to a trough on "
            "{{fact:drawdown.trough_date}}.",
            bundle,
            ("drawdown.basis", "drawdown.max_depth", "drawdown.peak_date", "drawdown.trough_date"),
        ),
        _sentence(
            "It took {{fact:drawdown.bars_to_recovery}} sessions to regain the prior peak.",
            bundle,
            ("drawdown.bars_to_recovery",),
        ),
        _sentence(
            "That decline has not yet recovered; it has been underwater for "
            "{{fact:drawdown.bars_underwater}} sessions and counting.",
            bundle,
            ("drawdown.still_underwater", "drawdown.bars_underwater"),
        )
        if bundle.get("drawdown.still_underwater") is not None
        and bundle.facts["drawdown.still_underwater"].value == "yes"
        else None,
        _sentence(
            "Across the whole history there were {{fact:drawdown.episodes}} distinct drawdown "
            "episodes.",
            bundle,
            ("drawdown.episodes",),
        ),
    ]
    return NarrativeDraft(text=" ".join(p for p in parts if p), source="template")


def _plural(bundle: FactBundle, fact_id: str, singular: str, plural: str) -> str:
    """Choose a verb form from a count without writing the count.

    A narrator is Python and may *read* a fact's value freely -- what it may not do is put a numeral
    into its output. Branching on the value to pick "is" or "are" is therefore fine, and skipping it
    produces "1 rules are currently firing", which reads as a bug in the report rather than as the
    grammar slip it is.
    """
    fact = bundle.get(fact_id)
    if fact is None or not isinstance(fact.value, (int, float)):
        return plural
    return singular if round(float(fact.value)) == 1 else plural


def draft_evidence(bundle: FactBundle) -> NarrativeDraft:
    """Prose for the decision-table section.

    Note what this deliberately does not say. There is no sentence claiming a rule works, because the
    bundle holds no fact that would support one.

    And note what the strongest sentence here has to carry. "The largest measured edge" is selected
    by magnitude, which means it is systematically the rule with the smallest sample -- a big edge on
    few observations is exactly what noise produces, and picking the maximum over twelve rules is a
    selection procedure with no correction applied. So the sentence names the significance verdict
    and the independent sample size in the same breath as the number, and a following sentence spells
    out the selection effect. Reporting the figure without them would reproduce, inside the report,
    the error the entire project is arranged to prevent.
    """
    firing_verb = _plural(bundle, "rules.firing", "is", "are")
    parts = [
        _sentence(
            f"Of {{{{fact:rules.total}}}} catalogued rules, {{{{fact:rules.firing}}}} {firing_verb} "
            "currently firing.",
            bundle,
            ("rules.total", "rules.firing"),
        ),
        _sentence(
            "The largest measured edge at {{fact:rules.best_horizon}} bars belongs to "
            "{{fact:rules.best_rule}}, at {{fact:rules.best_edge}} against a baseline of "
            "{{fact:rules.best_baseline}} on {{fact:rules.best_independent_n}} independent "
            "observations, which this project grades as {{fact:rules.best_significance}}.",
            bundle,
            ("rules.best_horizon", "rules.best_rule", "rules.best_edge", "rules.best_baseline",
             "rules.best_independent_n", "rules.best_significance"),
        ),
        _sentence(
            "That rule was selected for having the largest edge, which is not the same as having "
            "the best evidence: the biggest measured effect across a set of rules tends to be the "
            "one with the fewest observations behind it, and no correction for having looked at all "
            "of them is applied here.",
            bundle,
            ("rules.best_edge",),
        ),
        _sentence(
            "None of the catalogued rules reaches the sample size this project treats as "
            "sufficient, so all of them are reported as insufficient evidence rather than as "
            "findings.",
            bundle,
            ("rules.all_insufficient",),
        )
        if bundle.get("rules.all_insufficient") is not None
        and bundle.facts["rules.all_insufficient"].value == "yes"
        else None,
    ]
    return NarrativeDraft(text=" ".join(p for p in parts if p), source="template")


#: Section id to narrator, and the section titles the report uses.
#:
#: A mapping rather than a chain of ifs so the API layer and the tests iterate the same set, and
#: adding a section is one entry rather than an edit in three places.
DEFAULT_NARRATORS: Mapping[str, Narrator] = {
    "overview": draft_overview,
    "drawdown": draft_drawdown,
    "evidence": draft_evidence,
}

SECTION_TITLES: Mapping[str, str] = {
    "overview": "Overview",
    "drawdown": "Drawdown history",
    "evidence": "Rule evidence",
}
