"""A fourteen-stage analyst-to-portfolio-manager pipeline over one instrument on one date.

The orchestration is copied from `externalProjects/TradingAgents`; none of the code is. That system
is a LangGraph `StateGraph` because its analysts run ReAct tool loops and need a graph runtime to
manage the cycles. Ours do not -- every stage here receives a pre-built `EvidencePack` and makes one
structured call -- so what is left after removing the tool loops is a sequence with two bounded
counting loops in it, and that is a `for` statement. Adding a graph library to express it would buy
nothing and cost a dependency.

What *is* copied, deliberately and in detail:

- **The stage sequence.** Four analysts, then a bull-bear debate, then a judge, then a trader, then a
  three-way risk debate, then a final judge. The value is in the shape: independent reads before any
  argument, an argument before any decision, and a decision stressed by three fixed perspectives
  before it is final.
- **The debate arithmetic.** Research terminates at `2 * debate_rounds` turns and risk at
  `3 * risk_rounds`, with the bull always speaking first and the risk panel cycling
  aggressive → conservative → neutral.
- **Deterministic rating extraction.** `parse_rating` is a regex over the portfolio manager's own
  text, never a second model call. Upstream used a model for this and replaced it; a model in the
  parsing path is a model in the scoring path.
- **Outcome-resolved memory.** A decision is logged `pending` with no model call. On a later run of
  the same instrument it is resolved against realised return versus a benchmark, a short reflection
  is written, and the lessons are read by the portfolio manager alone. Analysts, researchers, the
  trader and the risk panel never see them -- the desk's history should inform the final judgement,
  not bias the reads that feed it.

What is not copied: the vendor router (we have `app.market.registry`), the ReAct tool loops (see
`app.agentdesk`'s docstring for why pre-fetch replaces them), the message-clear nodes they require,
and the dead `tools_social` edge upstream still registers for an analyst that never emits a tool call.

Nothing here executes anything. The trader's entry, stop and size are prose, and the paper broker
never sees them.
"""
