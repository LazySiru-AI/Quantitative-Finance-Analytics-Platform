"""Backfill Round 33 Phase B with the last N trading sessions of DETERMINISTIC history.

Why deterministic-only: the child research (Trading Agents / Vibe) reads *current* news and social
sentiment -- `app.agentdesk.evidence._news_evidence`/`_social_evidence` take no `as_of` -- so running
research for a past decision date would leak today's news into a historical decision. Price, indicator,
regime, selector and the entry-rule scan are all as-of-clean, so this backfill runs the real pipeline
per past session with research STARVED (budget_usd below per_child_budget_usd, so the pipeline's own
budget backstop skips every child launch): zero spend, zero look-ahead. That populates the raw_signal
(null-arm) screen book and the candidate-observation log with a real ~1-month history; the gated arms
(ta_gated / vibe_gated / full_workflow) intentionally stay empty and accrue live going forward, where
the news the research reads is genuinely contemporaneous.

    .venv/Scripts/python.exe -u strategy-program/tools/backfill_phase_b.py [--sessions 21] [--no-reset]

Runs chronologically so hysteresis (the prior_shortlist store) builds forward from cold. `--no-reset`
keeps any existing screen books / prior_shortlist; the default resets them for a clean backfill.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import threading
from decimal import Decimal

from app.agentdesk.models import DeskRun, agentdesk_dir
from app.agents.models import AgentBudget
from app.config import Settings
from app.market import store as market_store
from app.market.models import Interval
from app.workflow import book as book_mod
from app.workflow import phase_b
from app.workflow.phase_b import (
    PHASE_B_MAX_RESEARCH_SYMBOLS,
    PHASE_B_SCREEN_ENTRY_RULE,
    PHASE_B_SCREEN_TOP_N,
    PHASE_B_SELECTOR_ID,
)
from app.workflow.pipeline import SCREENED_ARMS, WorkflowConfig, build_stage_plan, run_workflow

# Carry the shortlist into the raw arm without ever paying for research: max_research_symbols wide
# enough that every fired candidate is carried, but budget below one child so the pipeline's own gate 6
# skips every launch. (PHASE_B_MAX_RESEARCH_SYMBOLS caps how many are carried; widen it to the shortlist
# size here so the raw null arm sees the whole fired set.)
_BACKFILL_MAX_RESEARCH = max(PHASE_B_SCREEN_TOP_N, PHASE_B_MAX_RESEARCH_SYMBOLS)
_STARVED_BUDGET = Decimal("0.01")  # < per-child, so no child research run ever launches
_PER_CHILD = Decimal("4.00")


def _sessions(settings: Settings, n: int) -> list[dt.date]:
    frame = market_store.read_frame("SPY", Interval.DAY, settings=settings)
    if frame is None or frame.empty:
        raise SystemExit("SPY daily bars are not in the store; cannot pick sessions.")
    dates = [d for d in frame["ts"].dt.date]
    return dates[-n:]


def _reset_screen_state(settings: Settings) -> None:
    base = agentdesk_dir(settings) / "workflow"
    for sub in ("book/screen", "prior_shortlist"):
        path = base / sub
        if path.exists():
            shutil.rmtree(path)


def _config(session: dt.date) -> WorkflowConfig:
    return WorkflowConfig(
        agent_card_id=None,
        trade_date=session,
        budget_usd=_STARVED_BUDGET,
        per_child_budget_usd=_PER_CHILD,
        max_research_symbols=_BACKFILL_MAX_RESEARCH,
        analysts=None,
        debate_rounds=None,
        risk_rounds=None,
        arms_enabled=SCREENED_ARMS,
        model="claude-haiku-4-5-20251001",
        universe_mode="screen",
        selector_id=PHASE_B_SELECTOR_ID,
        candidate_pool=None,
        rank_key=None,
        screen_top_n=PHASE_B_SCREEN_TOP_N,
        screen_entry_rule=PHASE_B_SCREEN_ENTRY_RULE,
        weekly_budget_usd=Decimal("100"),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=int, default=21, help="trailing trading sessions to backfill")
    parser.add_argument("--no-reset", action="store_true", help="keep existing screen books / prior_shortlist")
    args = parser.parse_args()

    settings = Settings()
    if not args.no_reset:
        _reset_screen_state(settings)
        print("reset screen books + prior_shortlist", flush=True)

    sessions = _sessions(settings, args.sessions)
    print(f"backfilling {len(sessions)} sessions: {sessions[0]} .. {sessions[-1]}", flush=True)

    from app.agentdesk.store import RunStore

    store = RunStore(settings, "workflow")
    total_staged = 0
    for session in sessions:
        # Fill any prior session's staged orders off this session's stored open (catch-up).
        filled, _rej, _pend = phase_b._fill_screen_books(settings, today=session)

        config = _config(session)
        run_id = f"pb-backfill-{session.isoformat()}"
        run = DeskRun(
            run_id=run_id, kind="workflow", state="queued",
            created_at=dt.datetime(session.year, session.month, session.day, 21, 0, tzinfo=dt.UTC),
            config={"agent_card_id": None, "child_runs": {}},
            stages=build_stage_plan(config),
            budget=AgentBudget(cap_usd=config.budget_usd),
        )
        store.save(run)
        run_workflow(run_id, config, settings=settings, cancel=threading.Event())

        raw = book_mod.load_book(settings, "raw_signal", starting_cash=Decimal("100000"), card_id="", universe_source="screen")
        staged_today = sum(1 for o in raw.orders if o.decision_date == session)
        total_staged += staged_today
        if staged_today or filled:
            print(f"  {session}: filled {filled}, staged {staged_today} (raw)", flush=True)

    print("\n--- backfill complete ---", flush=True)
    for arm in SCREENED_ARMS:
        path = book_mod.book_path(settings, arm, universe_source="screen")
        if not path.is_file():
            print(f"  {arm} screen book: (none)", flush=True)
            continue
        book = book_mod.load_book(settings, arm, starting_cash=Decimal("100000"), card_id="", universe_source="screen")
        filled_n = sum(1 for o in book.orders if o.status == "filled")
        pending_n = sum(1 for o in book.orders if o.status == "pending")
        print(f"  {arm} screen book: {len(book.orders)} orders ({filled_n} filled, {pending_n} pending)", flush=True)
    print(f"  total raw orders staged across backfill: {total_staged}", flush=True)


if __name__ == "__main__":
    main()
