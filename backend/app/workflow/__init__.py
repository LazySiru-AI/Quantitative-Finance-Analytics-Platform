"""The Agent Workflow desk: the orchestrator that chains the other two and then trades.

The two existing desks stop at prose. `app.tradingagents` says so in its own words -- "the trader's
entry, stop and size are prose, and the paper broker never sees them" -- and `app.vibedesk` refuses
a `place_order` surface on purpose. That was the right call for a research desk. It also means the
question the owner actually wants answered has never been asked: **does the research change the
outcome?** A rating nobody trades on cannot be scored against one nobody trades on either.

This package closes that loop. One workflow run:

1. classifies the market regime deterministically (`regime`),
2. selects a strategy card for it, refusing a switch whose tax bill outweighs it (`taxcheck`),
3. scans that card's universe for entry candidates through the existing rules engine,
4. runs child `tradingagents` and `vibedesk` runs on those candidates -- in-process via their
   service functions, never over HTTP,
5. synthesises an entry plan, and
6. stages next-open orders onto a persistent paper book (`book`).

**Entries are judged; exits are mechanical.** The six steps above decide what to *buy* -- the
expensive, model-driven half the four-arm study exists to measure. Nothing in them closes a position.
That is `exits`, which runs once a session off stored bars, applies the selected card's own stop,
take-profit, hold cap and `exit` expression in `app.tournament.runner`'s exact precedence, and stages
a sell filled at the next open. It costs no model call, so an exit never confounds the gate the study
is measuring. Both daily steps -- the in-process daemon (`loop.run_once`) and the Phase B scheduled
task (`phase_b`) -- fill what is due first and only then decide exits, so a position bought this
morning is in the book its own exit is evaluated against.

**Four books, not one.** Every run stages orders into four parallel arms -- `raw_signal`,
`ta_gated`, `vibe_gated`, `full_workflow` -- from the *same* regime call, card and candidate set, on
the same dates with the same mandate and starting cash. The arms diverge at exactly one point: the
gate that decides which candidates survive. That is what makes the comparison a paired one, and it
is why the raw candidate list is recorded before any gating rather than reconstructed afterwards.

**This package owns the only persistent trade ledger in the codebase.** `app.paperdesk` recomputes
its book by replay from stored bars on every request, which is correct for a card whose decisions
are a pure function of price history and impossible for an agent whose decisions are not. A
workflow order is a judgement made on day N that cannot be re-derived on day N+1, so it is written
down. See `app.workflow.book`.

Nothing here re-implements the broker, the tax engines or the metrics. `app.paper.paperbroker`
already prices a next-open fill (including from a live quote when the open bar is not stored yet),
`app.paper.papertax` already runs FIFO lots through wash sales and the short/long split, and
`app.backtest.metrics` already computes the performance figures every other part of this project is
scored on. Using anything else here would make the arms incomparable with the rest of the programme,
which is the entire point of the exercise.
"""

from __future__ import annotations
