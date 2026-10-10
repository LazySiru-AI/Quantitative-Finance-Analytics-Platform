"""Claude-backed proposal agents for the evolution loop.

`app.evolution` searches by seeded mutation. This package is the other proposer: one that reads the
last generation's findings, the owner's stated goal and the lane's ticker pool, and designs the next
slate deliberately. `strategy-program/AGENTS-INTEGRATION-PLAN.md` Phase F sanctions exactly this and
only this -- proposal (phase 1) and post-mortem (phase 6); scoring stays deterministic and serial.

    models.py    the contract: what an agent may produce, and the audit record of every call
    client.py    credential resolution, the call itself, cost accounting and the budget cap
    prompts.py   the system prompts, frozen and cache-friendly
    designer.py  findings + pool + goal -> a generation of candidate genomes
    scout.py     the news panel -> which pool tickers this generation should bias toward

Nothing here is required for the loop to run. Every failure -- missing credentials, an exhausted
budget, a refusal, a malformed response -- degrades to `app.evolution.proposer`'s deterministic path
and is recorded. The agent makes the search better; it is never what makes it work.
"""
