"""Structural tests for the `sentiment_intelligence_team` vibedesk preset.

This preset is a pure-JSON addition under `app/vibedesk/presets/` (see `app.vibedesk.presets`'
module docstring: any `<name>.json` there is discovered automatically by `list_presets()`/`load_preset()`
-- no code change is needed to register it). This module proves the file loads, validates as a DAG, and
declares only evidence sections `app.agentdesk.evidence` actually knows how to build; it makes no real
model call, the same boundary `tests/test_vibedesk.py` draws for the other shipped presets.
"""

from __future__ import annotations

from app.agentdesk.evidence import SECTION_KEYS
from app.vibedesk.presets import list_presets, load_preset, topological_layers, validate_dag

PRESET_NAME = "sentiment_intelligence_team"


class TestSentimentIntelligenceTeamShape:
    def test_is_discovered_by_list_presets(self) -> None:
        names = {preset.name for preset in list_presets()}
        assert PRESET_NAME in names

    def test_loads_and_validates_as_a_dag(self) -> None:
        preset = load_preset(PRESET_NAME)
        validate_dag(preset)  # must not raise

    def test_has_the_expected_agents(self) -> None:
        preset = load_preset(PRESET_NAME)
        agent_ids = {agent.id for agent in preset.agents}
        assert agent_ids == {
            "news_analyst",
            "social_retail_analyst",
            "macro_events_analyst",
            "sentiment_synthesizer",
        }

    def test_every_declared_evidence_section_is_a_known_section_key(self) -> None:
        preset = load_preset(PRESET_NAME)
        for agent in preset.agents:
            unknown = set(agent.evidence) - set(SECTION_KEYS)
            assert not unknown, f"agent {agent.id!r} declares unknown evidence section(s): {unknown}"

    def test_each_analyst_declares_the_evidence_the_design_calls_for(self) -> None:
        preset = load_preset(PRESET_NAME)
        by_id = {agent.id: agent for agent in preset.agents}
        assert set(by_id["news_analyst"].evidence) == {"news"}
        assert set(by_id["social_retail_analyst"].evidence) == {"social", "macro"}
        assert set(by_id["macro_events_analyst"].evidence) == {"macro", "events"}

    def test_the_dag_fans_three_analysts_into_one_synthesizer(self) -> None:
        preset = load_preset(PRESET_NAME)
        by_id = {task.id: task for task in preset.tasks}

        analyst_task_ids = {"news", "social", "macro_events"}
        synthesize = by_id["synthesize"]
        assert synthesize.agent_id == "sentiment_synthesizer"
        assert set(synthesize.depends_on) == analyst_task_ids

        for task_id in analyst_task_ids:
            assert by_id[task_id].depends_on == ()

    def test_topological_layers_put_the_three_analysts_in_layer_zero_and_the_synthesizer_alone_in_layer_one(
        self,
    ) -> None:
        preset = load_preset(PRESET_NAME)
        layers = topological_layers(preset)
        assert len(layers) == 2
        assert {task.id for task in layers[0]} == {"news", "social", "macro_events"}
        assert [task.id for task in layers[1]] == ["synthesize"]
        for task in layers[0]:
            assert task.layer == 0
        assert layers[1][0].layer == 1

    def test_has_a_symbol_variable_required_and_a_horizon_variable_optional(self) -> None:
        preset = load_preset(PRESET_NAME)
        by_name = {variable.name: variable for variable in preset.variables}
        assert by_name["symbol"].required is True
        assert by_name["horizon"].required is False

    def test_every_task_prompt_only_references_declared_variables(self) -> None:
        # A prompt referencing a `{placeholder}` that is not one of the preset's declared variables
        # would raise a KeyError at runtime the first time `str.format` actually runs it -- catch that
        # here instead, the same class of defect `app.vibedesk.service`'s variable validation guards
        # against for the run-time supplied values.
        preset = load_preset(PRESET_NAME)
        variable_names = {variable.name for variable in preset.variables}
        for task in preset.tasks:
            task.prompt.format(**{name: "x" for name in variable_names})


class TestSentimentIntelligenceTeamAlongsideShippedPresets:
    def test_all_shipped_presets_including_this_one_load_and_validate(self) -> None:
        all_presets = list_presets()
        names = {preset.name for preset in all_presets}
        assert PRESET_NAME in names
        for preset in all_presets:
            validate_dag(preset)  # must not raise
            layers = topological_layers(preset)
            assert layers
