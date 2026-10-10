"""Preset desks of role agents, run as a dependency graph.

The design is copied from `externalProjects/Vibe-Trading`'s swarm (`agent/src/swarm/`): a preset
declares a set of agents and a set of tasks with dependencies between them; the runtime validates the
graph, computes topological layers, and runs each layer's tasks in parallel. What that buys over the
fixed pipeline in `app.tradingagents` is that adding a desk is a data change, not a code change.

**Presets are JSON, not YAML.** Upstream uses YAML. `pyyaml` is present in this project's virtualenv
as a transitive dependency of something else and is *not* declared in `backend/pyproject.toml`, so
reading presets with it would make this feature depend on a package nothing has promised to keep
installed -- the kind of thing that works locally and fails in the Docker build. JSON needs no
dependency, and the card library under `backend/app/paper/library/` already establishes JSON as how
this codebase stores declarative definitions on disk.

**Three rules the runtime enforces, each one copied because upstream learned it the hard way.**

1. *Downstream agents receive summaries, never full reports.* A task's `input_from` names the
   upstream tasks whose one-paragraph summaries are spliced into its prompt. Passing full text
   instead makes prompt size grow with the square of the desk, and the last agent in a five-agent
   desk ends up reading more than it can use.
2. *A task whose upstream failed is `blocked`, never quietly completed.* This is not a cosmetic
   status. This project has its own scar for eliding the distinction -- an evolution loop reported
   "running" through 1,644 consecutive identical failures because per-iteration resilience hid the
   aggregate. A blocked task is evidence about its upstream; a task silently marked done is a lie
   about the desk's output.
3. *Ground truth is fetched before any agent runs.* The run's symbol is resolved into an
   `app.agentdesk.models.EvidencePack` once and rendered into every agent's prompt, including the
   synthesiser agents that have no data sections of their own. An aggregator that cannot see the
   underlying figures will invent them to make its summary read well, which is exactly the failure
   `app.agentdesk.grounding` then catches -- catching it is good, not needing to is better.

Nothing here executes anything, and no preset may declare an agent that does. Upstream ships a live
execution path behind a consented mandate; that subsystem is deliberately not reproduced -- see
`docs/AGENT-GAP-ANALYSIS.md` §4.10 for what it would take if the question ever arises.
"""
