"""Influencer personas: one memory-backed agent per followed influencer.

Each persona accumulates an Obsidian-compatible markdown vault of episodic notes (one per ingested
video or pasted post), from which later phases consolidate a persona profile, answer "what would they
say about X" against our own market data, and distil a strategy card for backtesting.

The pinned wire contract and vault note schema live in `docs/INFLUENCER-CONTRACT.md`. This package
follows the same conventions as `app.agentdesk`: frozen models, thin routers, provider failures
degrade to warnings rather than 5xx, and every model claim is grounded against the source text.
"""
