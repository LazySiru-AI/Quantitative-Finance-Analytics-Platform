"""Structural invariants for the compressed agent prompts.

This does not check prose quality -- there is no automated test for "concise but still correct" --
it checks the handful of guarantees a compression pass must never silently drop: every role still has
a prompt, the referee's machine-parsed verdict contract (`app.workflow.verdict.parse_verdict`) still
has all three literal words and the last-line instruction, the shared preamble still tells the model
not to round a decimal to a bare integer and not to abbreviate a date (the two ways terseness has
previously caused `app.agentdesk.grounding` to false-reject a stage's own report), and the portfolio
manager's prompt still names all five rating tiers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.tradingagents import prompts

_WHITESPACE_RE = re.compile(r"\s+")


def _collapsed(text: str) -> str:
    """`text` with every run of whitespace (including a mid-phrase line wrap in a source triple-quoted
    string) collapsed to a single space, so a substring check for a multi-word phrase does not
    spuriously fail just because the prompt happened to wrap between two of its words."""
    return _WHITESPACE_RE.sub(" ", text)


_FOLLOWUP_REVIEW_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "app"
    / "vibedesk"
    / "presets"
    / "followup_review.json"
)

_RATING_TIERS = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
_VERDICT_WORDS = ("SUPPORT", "REFUTE", "INCONCLUSIVE")


def _followup_review() -> dict:
    return json.loads(_FOLLOWUP_REVIEW_PATH.read_text(encoding="utf-8"))


def _agent_system(preset: dict, agent_id: str) -> str:
    for agent in preset["agents"]:
        if agent["id"] == agent_id:
            return agent["system"]
    raise AssertionError(f"no agent {agent_id!r} in followup_review.json")


class TestTradingAgentsPromptModule:
    def test_every_role_prompt_is_non_empty(self) -> None:
        for role, system in prompts.SYSTEM_FOR_ROLE.items():
            assert isinstance(system, str) and system.strip(), f"{role} has an empty prompt"

    def test_shared_preamble_forbids_rounding_to_a_bare_integer(self) -> None:
        # `app.agentdesk.grounding._add_grounded` admits a grounded figure at its own precision and
        # at coarser *decimal* roundings, but never as a bare integer -- a terse "9.73" -> "10"
        # collapse is not a rounding grounding admits, so the prompt must forbid it explicitly.
        assert "bare integer" in prompts._GROUNDING

    def test_shared_preamble_requires_full_iso_dates(self) -> None:
        # `app.agentdesk.grounding._DATE_RE` only exempts full-shape dates (`2026-08-28`,
        # `2026/08/28`, `08/28/2026`, or the bare `2026-08` month) from being scanned as numbers. A
        # short form like "8/28" leaks its day digits as an ungrounded token and false-rejects.
        assert "YYYY-MM-DD" in prompts._GROUNDING
        assert "ISO" in prompts._GROUNDING

    def test_every_prompt_carries_the_grounding_and_date_guardrails(self) -> None:
        # The two guardrails live in `_GROUNDING`, which every role prompt except `reflector`
        # splices in via `_PREAMBLE` -- confirm the splice actually reached each such role, not just
        # the constant itself. `reflector` never carried `_PREAMBLE` (it reasons over a realised
        # return and a benchmark return it is handed directly, not a fresh evidence pack it must cite
        # figures from), so it is excluded here exactly as it always was.
        for role, system in prompts.SYSTEM_FOR_ROLE.items():
            if role == "reflector":
                continue
            collapsed = _collapsed(system)
            assert "bare integer" in collapsed, f"{role} prompt is missing the no-rounding guardrail"
            assert "YYYY-MM-DD" in collapsed, f"{role} prompt is missing the full-ISO-date guardrail"

    def test_debate_rule_requires_engaging_the_other_sides_specific_claims(self) -> None:
        for role in ("bull_researcher", "bear_researcher"):
            system = _collapsed(prompts.SYSTEM_FOR_ROLE[role])
            assert "specific claims" in system, f"{role} prompt dropped the engagement rule"

    def test_research_manager_and_portfolio_manager_name_the_five_tier_scale(self) -> None:
        for role in ("research_manager", "portfolio_manager"):
            system = prompts.SYSTEM_FOR_ROLE[role]
            for tier in _RATING_TIERS:
                assert tier in system, f"{role} prompt dropped rating tier {tier!r}"

    def test_portfolio_manager_requires_executive_summary_falsifier_and_risk_attribution(self) -> None:
        system = _collapsed(prompts.SYSTEM_FOR_ROLE["portfolio_manager"]).lower()
        assert "executive summary" in system
        assert "falsify" in system
        assert "risk analyst" in system and "persuasive" in system

    def test_market_analyst_still_requires_a_stated_falsifier(self) -> None:
        system = prompts.SYSTEM_FOR_ROLE["market_analyst"]
        assert "falsif" in system.lower()

    def test_reflector_still_states_its_own_brevity_requirement(self) -> None:
        system = _collapsed(prompts.SYSTEM_FOR_ROLE["reflector"]).lower()
        assert "two to four sentences" in system


class TestFollowupReviewPreset:
    def test_preset_json_parses(self) -> None:
        preset = _followup_review()
        assert preset["name"] == "followup_review"
        assert {agent["id"] for agent in preset["agents"]} == {
            "supporting_analyst",
            "skeptical_analyst",
            "referee",
        }

    def test_every_agent_system_prompt_is_non_empty(self) -> None:
        preset = _followup_review()
        for agent in preset["agents"]:
            assert isinstance(agent["system"], str) and agent["system"].strip(), (
                f"{agent['id']} has an empty system prompt"
            )

    def test_analyst_prompts_carry_the_grounding_and_date_guardrails(self) -> None:
        preset = _followup_review()
        for agent_id in ("supporting_analyst", "skeptical_analyst", "referee"):
            system = _collapsed(_agent_system(preset, agent_id))
            assert "bare integer" in system, f"{agent_id} prompt is missing the no-rounding guardrail"
            assert "YYYY-MM-DD" in system, f"{agent_id} prompt is missing the full-ISO-date guardrail"

    def test_referee_prompt_contains_all_three_literal_verdict_strings(self) -> None:
        preset = _followup_review()
        referee_system = _agent_system(preset, "referee")
        for word in _VERDICT_WORDS:
            assert f"VERDICT: {word}" in referee_system, (
                f"referee prompt dropped the literal verdict string 'VERDICT: {word}'"
            )

    def test_referee_prompt_still_instructs_the_verdict_as_the_trailing_line(self) -> None:
        preset = _followup_review()
        referee_system = _collapsed(_agent_system(preset, "referee")).lower()
        assert "last line" in referee_system
        assert "nothing after it" in referee_system

    def test_referee_prompt_still_allows_an_explicit_inconclusive_ruling(self) -> None:
        # `app.workflow.verdict.parse_verdict` treats an explicit `VERDICT: INCONCLUSIVE` the same as
        # a missing verdict line downstream, but the two must stay distinguishable in the prompt: the
        # model has to be told that abstaining is a correct, complete answer, not a cop-out.
        preset = _followup_review()
        referee_system = _collapsed(_agent_system(preset, "referee")).lower()
        assert "inconclusive" in referee_system
        assert "not a failure to decide" in referee_system or "not a cop-out" in referee_system
