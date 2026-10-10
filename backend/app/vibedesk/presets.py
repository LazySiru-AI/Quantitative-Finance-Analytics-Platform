"""Preset loading, DAG validation and topological layering.

A preset is a JSON file under `presets/` (see `app.vibedesk`'s own module docstring for why JSON and
not YAML). This module is the only place that reads that file and the only place that decides how its
tasks are ordered: `load_preset` parses and validates in one step, so nothing downstream ever holds a
`Preset` whose graph has not already been proven acyclic and fully resolved.

**Layer assignment is longest-path, not first-available-slot.** A task's `layer` is the length of the
longest dependency chain beneath it, not the smallest layer consistent with its declared deps. That
matters here because `app.agentdesk.models.StageRecord.layer` is the same field the API contract pins,
and `app.vibedesk.runtime` runs one layer at a time in lockstep -- a task assigned too low a layer
would run before a dependency two hops back had actually finished, not just before its direct parent.
Longest-path is also what makes the layering unique for a given DAG, so two callers computing it never
disagree.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DagError",
    "Preset",
    "PresetAgent",
    "PresetNotFound",
    "PresetTask",
    "PresetVariable",
    "list_presets",
    "load_preset",
    "presets_dir",
    "topological_layers",
    "validate_dag",
]


class PresetNotFound(LookupError):
    """No `<name>.json` under `presets_dir()`."""

    def __init__(self, name: str) -> None:
        super().__init__(f"no vibedesk preset named {name!r}")
        self.name = name


class DagError(ValueError):
    """A preset's task graph is not a valid DAG: an unknown agent, an unknown dependency, a duplicate
    task id, or a cycle. Raised eagerly by `load_preset` (via `validate_dag`) so nothing downstream --
    the API, the runtime -- ever has to discover a broken preset mid-run."""


@dataclass(frozen=True)
class PresetAgent:
    """One seat in the desk: a role, a system prompt, and the evidence sections it is entitled to."""

    id: str
    label: str
    blurb: str
    evidence: tuple[str, ...]
    system: str


@dataclass(frozen=True)
class PresetTask:
    """One node in the DAG: which agent runs it, what it waits on, and its prompt template.

    `layer` is computed by `load_preset`/`topological_layers`, never authored in the JSON -- see this
    module's own docstring for why it must be longest-path and therefore derived, not declared.
    """

    id: str
    agent_id: str
    depends_on: tuple[str, ...]
    prompt: str
    layer: int = 0


@dataclass(frozen=True)
class PresetVariable:
    """One run-time variable a preset's task prompts may reference via `str.format`."""

    name: str
    label: str
    required: bool
    default: str


@dataclass(frozen=True)
class Preset:
    """One desk definition: its agents, its task DAG, and the variables its prompts accept."""

    name: str
    label: str
    blurb: str
    variables: tuple[PresetVariable, ...]
    agents: tuple[PresetAgent, ...]
    tasks: tuple[PresetTask, ...]


def presets_dir() -> Path:
    """`backend/app/vibedesk/presets/` -- where every preset's `<name>.json` lives, this module's file
    resolved rather than a path built from `Settings`, because presets ship with the source tree the
    same way `app.paper.library`'s card JSON does; they are not per-deployment data."""
    return Path(__file__).resolve().parent / "presets"


def _parse_preset(name: str, data: dict[str, Any]) -> Preset:
    agents = tuple(
        PresetAgent(
            id=agent["id"],
            label=agent["label"],
            blurb=agent["blurb"],
            evidence=tuple(agent.get("evidence", ())),
            system=agent["system"],
        )
        for agent in data.get("agents", ())
    )
    variables = tuple(
        PresetVariable(
            name=variable["name"],
            label=variable["label"],
            required=bool(variable.get("required", False)),
            default=variable.get("default", ""),
        )
        for variable in data.get("variables", ())
    )
    tasks = tuple(
        PresetTask(
            id=task["id"],
            agent_id=task["agent_id"],
            depends_on=tuple(task.get("depends_on", ())),
            prompt=task["prompt"],
        )
        for task in data.get("tasks", ())
    )
    preset = Preset(
        name=data.get("name", name),
        label=data["label"],
        blurb=data["blurb"],
        variables=variables,
        agents=agents,
        tasks=tasks,
    )
    validate_dag(preset)
    layers = topological_layers(preset)
    layered_by_id = {task.id: task for layer in layers for task in layer}
    return Preset(
        name=preset.name,
        label=preset.label,
        blurb=preset.blurb,
        variables=preset.variables,
        agents=preset.agents,
        tasks=tuple(layered_by_id[task.id] for task in preset.tasks),
    )


def load_preset(name: str) -> Preset:
    """Read, parse and validate `<name>.json`. Raises `PresetNotFound` if the file does not exist and
    `DagError` if its task graph is not a valid DAG -- both eagerly, at load time."""
    path = presets_dir() / f"{name}.json"
    if not path.is_file():
        raise PresetNotFound(name)
    data = json.loads(path.read_text(encoding="utf-8"))
    return _parse_preset(name, data)


def list_presets() -> tuple[Preset, ...]:
    """Every `.json` file under `presets_dir()`, loaded and validated, sorted by `name`."""
    if not presets_dir().is_dir():
        return ()
    names = sorted(path.stem for path in presets_dir().glob("*.json"))
    return tuple(load_preset(name) for name in names)


def validate_dag(preset: Preset) -> None:
    """Raise `DagError` for an unknown `agent_id`, an unknown `depends_on` id, a duplicate task id, or
    a cycle. Never hangs on a cycle -- the DFS below tracks the recursion stack explicitly and raises
    the instant a node on it is revisited, rather than looping."""
    agent_ids = {agent.id for agent in preset.agents}
    task_ids: set[str] = set()
    for task in preset.tasks:
        if task.id in task_ids:
            raise DagError(f"preset {preset.name!r}: duplicate task id {task.id!r}")
        task_ids.add(task.id)

    for task in preset.tasks:
        if task.agent_id not in agent_ids:
            raise DagError(
                f"preset {preset.name!r}: task {task.id!r} references unknown agent {task.agent_id!r}"
            )
        for dep in task.depends_on:
            if dep not in task_ids:
                raise DagError(
                    f"preset {preset.name!r}: task {task.id!r} depends on unknown task {dep!r}"
                )

    by_id = {task.id: task for task in preset.tasks}
    state: dict[str, int] = {}  # 0 = unvisited, 1 = on stack, 2 = done

    def visit(task_id: str, path: tuple[str, ...]) -> None:
        mark = state.get(task_id, 0)
        if mark == 2:
            return
        if mark == 1:
            cycle = " -> ".join((*path, task_id))
            raise DagError(f"preset {preset.name!r}: dependency cycle: {cycle}")
        state[task_id] = 1
        for dep in by_id[task_id].depends_on:
            visit(dep, (*path, task_id))
        state[task_id] = 2

    for task in preset.tasks:
        visit(task.id, ())


def topological_layers(preset: Preset) -> tuple[tuple[PresetTask, ...], ...]:
    """Every task grouped by its longest-path layer, layer 0 first, and each returned `PresetTask`
    carries its computed `layer`. Tasks within one inner tuple have no dependency relationship between
    them and are the set `app.vibedesk.runtime` runs together.

    Assumes `preset` has already passed `validate_dag` -- called unconditionally at the top so a
    caller handing this a cyclic or otherwise malformed preset gets the same `DagError` `load_preset`
    would raise, rather than infinite recursion.
    """
    validate_dag(preset)
    by_id = {task.id: task for task in preset.tasks}
    depth_cache: dict[str, int] = {}

    def depth(task_id: str) -> int:
        if task_id in depth_cache:
            return depth_cache[task_id]
        deps = by_id[task_id].depends_on
        value = 0 if not deps else 1 + max(depth(dep) for dep in deps)
        depth_cache[task_id] = value
        return value

    layered: dict[int, list[PresetTask]] = {}
    for task in preset.tasks:
        layer = depth(task.id)
        layered.setdefault(layer, []).append(task)

    result: list[tuple[PresetTask, ...]] = []
    for layer_index in sorted(layered):
        tasks_in_layer = tuple(
            PresetTask(
                id=task.id,
                agent_id=task.agent_id,
                depends_on=task.depends_on,
                prompt=task.prompt,
                layer=layer_index,
            )
            for task in layered[layer_index]
        )
        result.append(tasks_in_layer)
    return tuple(result)
