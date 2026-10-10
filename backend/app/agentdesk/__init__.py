"""Shared machinery for the two agent-desk features: `app.tradingagents` and `app.vibedesk`.

**Why this package exists separately from `app.agents`.** `app.agents` is the evolution loop's
proposer -- three roles, one call each, output consumed by machinery rather than read by a person.
The two desk features are the opposite shape: many calls per run, arranged in a pipeline or a DAG,
and every word of the output is rendered to a human. That difference brings three problems
`app.agents` never had to solve -- how a stage gets its facts, how a person can trust a number in the
prose, and where a multi-stage run's partial progress lives while it is still running. This package
solves those three once so neither desk solves them twice.

**The rule about numbers is relaxed here, and replaced with a stronger one.**
`strategy-program/AGENTS-INTEGRATION-PLAN.md` §0 forbids a model emitting a measurement, and
`app.agents.reviewer._reject_measurement` enforces that by scanning prose for digits. That rule is
correct for the loop, where an agent's prose sits next to a scoreboard the engine computed and any
number in it would compete with a measured one. It is unworkable for a desk whose entire job is to
read a price series and argue about it -- both systems this feature is modelled on
(`externalProjects/TradingAgents`, `externalProjects/Vibe-Trading`) have agents citing figures in
every paragraph.

So the desks do not forbid numbers. They forbid *ungrounded* numbers, and enforce it mechanically
rather than by instruction: :mod:`app.agentdesk.grounding` extracts every numeric token from a
stage's prose and rejects the stage unless each one appears in the :class:`EvidencePack` that stage
was given. A rejected stage is retried with the failure quoted back to it, up to
:data:`MAX_GROUNDING_ATTEMPTS`; a stage that still fails is released marked `degraded` with its
issues visible, never silently. This is Vibe-Trading's `GroundingLedger` design, which is the single
most transferable idea in either upstream repo, narrowed to what one structured call can support.

The evolution loop's own strict no-measurement rule is untouched -- `app.agents.reviewer` still
calls its own `_reject_measurement`, and nothing in this package is imported by `app.evolution`.

**No tool-calling, deliberately, in this version.** `app.agents.client.call_structured` is a single
structured request with no `tools` parameter, and a stage here is one such call. Facts arrive by
*pre-fetch*: the caller builds an :class:`EvidencePack` from the deterministic data layer
(`app.market`, `app.indicators`, `app.db.duck`) and renders it into the user turn. Both upstreams
validate the pattern -- TradingAgents' sentiment analyst pre-fetches all three of its sources rather
than tool-looping, and every Vibe-Trading swarm worker receives a pre-fetched "Ground Truth" block.
Pre-fetch also makes grounding checkable at all: a tool-looping agent's evidence set is whatever it
happened to fetch, whereas a pack is a fixed set of facts a verdict can be computed against.
"""
