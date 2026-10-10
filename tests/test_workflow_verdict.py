"""Tests for the `followup_review` Vibe Trading preset and its deterministic verdict parser.

Two things are under test: that `followup_review.json` is a well-formed preset per
`app.vibedesk.presets`'s own schema (loads, validates as a DAG, layers as expected, uses only real
evidence section keys, and interpolates only names the runtime actually supplies), and that
`app.workflow.verdict.parse_verdict` extracts the referee's final verdict deterministically -- no model
call, tolerant of markdown decoration and trailing prose, defaulting to INCONCLUSIVE (not a crash and
not a guess) when no verdict line is present at all.
"""

from __future__ import annotations

import re

from app.agentdesk.evidence import SECTION_KEYS
from app.vibedesk.presets import load_preset, topological_layers
from app.workflow.verdict import parse_verdict

# ---------------------------------------------------------------------------
# The preset itself
# ---------------------------------------------------------------------------

#: Names the runtime injects into every task's format namespace regardless of whether the preset
#: declares them as formal `variables` -- see `app.vibedesk.runtime._format_vars`'s own docstring.
_RUNTIME_INJECTED = {"symbol", "question"}

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _preset():
    return load_preset("followup_review")


def test_preset_loads_and_validates() -> None:
    preset = _preset()
    assert preset.name == "followup_review"
    assert preset.agents
    assert preset.tasks


def test_preset_has_exactly_two_layers() -> None:
    preset = _preset()
    layers = topological_layers(preset)
    assert len(layers) == 2
    # layer 0: the two opposing reads, independent of each other
    assert {task.agent_id for task in layers[0]} == {"supporting_analyst", "skeptical_analyst"}
    # layer 1: a single referee depending on both
    assert len(layers[1]) == 1
    referee_task = layers[1][0]
    assert set(referee_task.depends_on) == {task.id for task in layers[0]}


def test_evidence_sections_are_all_real_section_keys() -> None:
    preset = _preset()
    for agent in preset.agents:
        for section in agent.evidence:
            assert section in SECTION_KEYS, f"agent {agent.id!r} declares unknown evidence section {section!r}"


def test_every_prompt_placeholder_is_declared_or_runtime_injected() -> None:
    preset = _preset()
    declared = {variable.name for variable in preset.variables}
    allowed = declared | _RUNTIME_INJECTED
    for task in preset.tasks:
        placeholders = set(_PLACEHOLDER_RE.findall(task.prompt))
        unknown = placeholders - allowed
        assert not unknown, f"task {task.id!r} references undeclared placeholder(s): {unknown}"


def test_question_is_actually_interpolated_somewhere() -> None:
    preset = _preset()
    assert any("{question}" in task.prompt for task in preset.tasks)


def test_question_variable_declared_without_tripping_required_gate() -> None:
    """`app.vibedesk.service._validate_variables` only special-cases the `symbol` variable to read from
    `StartSwarmRequest.symbol` -- any other declared variable is checked against `req.variables`, which
    is never where `question` actually arrives (it has its own dedicated `StartSwarmRequest.question`
    field, injected unconditionally by `runtime._format_vars`). Declaring `question` as `required: True`
    would therefore make `_validate_variables` reject every legitimate request that supplies the
    question only via the dedicated field. This preset declares `question` as `required: False` (with
    an empty default) specifically to avoid that false rejection."""
    preset = _preset()
    question_var = next(v for v in preset.variables if v.name == "question")
    assert question_var.required is False


# ---------------------------------------------------------------------------
# parse_verdict
# ---------------------------------------------------------------------------


def test_parses_explicit_support() -> None:
    text = "Some report body.\n\nVERDICT: SUPPORT"
    assert parse_verdict(text) == ("SUPPORT", True)


def test_parses_explicit_refute() -> None:
    text = "Some report body.\n\nVERDICT: REFUTE"
    assert parse_verdict(text) == ("REFUTE", True)


def test_parses_explicit_inconclusive() -> None:
    text = "Some report body.\n\nVERDICT: INCONCLUSIVE"
    assert parse_verdict(text) == ("INCONCLUSIVE", True)


def test_parses_case_insensitively() -> None:
    assert parse_verdict("verdict: support") == ("SUPPORT", True)
    assert parse_verdict("Verdict: Refute") == ("REFUTE", True)


def test_parses_markdown_decorated_line() -> None:
    text = "The evidence does not hold up.\n\n**VERDICT: REFUTE**"
    assert parse_verdict(text) == ("REFUTE", True)


def test_parses_underscore_emphasis() -> None:
    text = "Report body.\n\n_VERDICT: SUPPORT_"
    assert parse_verdict(text) == ("SUPPORT", True)


def test_parses_trailing_text_after_verdict_line() -> None:
    text = "Report body.\n\nVERDICT: INCONCLUSIVE\n\nThanks for reading, and good luck out there."
    assert parse_verdict(text) == ("INCONCLUSIVE", False) or parse_verdict(text)[0] == "INCONCLUSIVE"
    # The verdict itself must still parse explicitly even though prose follows it.
    verdict, was_explicit = parse_verdict(text)
    assert verdict == "INCONCLUSIVE"
    assert was_explicit is True


def test_parses_last_verdict_line_when_multiple_present() -> None:
    """Scans from the end: an earlier draft/self-correction inside the reasoning must not win over the
    genuinely final verdict line."""
    text = "Draft thought: VERDICT: SUPPORT\n\nOn reflection:\n\nVERDICT: REFUTE"
    assert parse_verdict(text) == ("REFUTE", True)


def test_no_verdict_line_defaults_to_inconclusive_and_not_explicit() -> None:
    text = "This report never states a verdict line at all, just prose about the instrument."
    assert parse_verdict(text) == ("INCONCLUSIVE", False)


def test_empty_string_defaults_to_inconclusive_and_not_explicit() -> None:
    assert parse_verdict("") == ("INCONCLUSIVE", False)


def test_bare_word_in_prose_does_not_falsely_parse_as_a_verdict() -> None:
    """Guards against a too-greedy regex: the word 'refute' appearing in an ordinary sentence, with no
    `VERDICT:` label anywhere in the text, must not be mistaken for an explicit REFUTE verdict."""
    text = "The bear's argument fails to refute the bull's core point about margins."
    assert parse_verdict(text) == ("INCONCLUSIVE", False)


def test_bare_word_support_in_prose_does_not_falsely_parse() -> None:
    text = "Nothing in the filing appears to support that reading of the guidance."
    assert parse_verdict(text) == ("INCONCLUSIVE", False)
