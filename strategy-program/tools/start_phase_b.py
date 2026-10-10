"""Seed Round 33 Phase B: launch the first live screened workflow run.

Runs the promoted selector (mom12_1_hysteresis) in screen mode on the newest session,
through the real validated service path (agent-availability check, arm restriction,
registry slot). Bounded budget for this first validation/seed run. Polls to terminal and
prints the outcome, cost, and the screen books it created.

    .venv/Scripts/python.exe -u strategy-program/tools/start_phase_b.py
"""

from __future__ import annotations

import time

from app.agentdesk.store import RunStore
from app.config import Settings
from app.workflow import book as book_mod
from app.workflow import service
from app.workflow.schemas import WorkflowRunRequest

_TERMINAL = {"succeeded", "failed", "cancelled"}


def main() -> None:
    settings = Settings()
    req = WorkflowRunRequest(
        universe_mode="screen",
        selector_id="mom12_1_hysteresis",
        screen_top_n=10,  # live widening of the promoted selector's shortlist, for study accrual
        arms_enabled=["raw_signal", "full_workflow"],
        budget_usd="16.00",
        per_child_budget_usd="4.00",
        max_research_symbols=3,
    )
    run = service.start_workflow_run(req, settings=settings)
    print(f"launched screen run {run.run_id} (selector=mom12_1_hysteresis, arms=raw_signal+full_workflow)", flush=True)

    store = RunStore(settings, "workflow")
    last_stage = ""
    deadline = time.time() + 3300  # ~55 min ceiling
    final = None
    while time.time() < deadline:
        cur = store.load(run.run_id)
        if cur is None:
            print("run vanished from the store", flush=True)
            return
        running = next((s.stage_id for s in cur.stages if s.state == "running"), "")
        if running and running != last_stage:
            print(f"  stage: {running}", flush=True)
            last_stage = running
        if cur.state in _TERMINAL:
            final = cur
            break
        time.sleep(8)

    if final is None:
        print("TIMEOUT: run did not reach a terminal state within the ceiling", flush=True)
        return

    print(f"\nFINAL state: {final.state}", flush=True)
    if final.error:
        print(f"error: {final.error}", flush=True)
    print(f"budget spent: ${final.budget.spent_usd} over {final.budget.calls} call(s)", flush=True)

    from app.workflow.pipeline import STARTING_CASH

    for arm in ("raw_signal", "full_workflow"):
        path = book_mod.book_path(settings, arm, universe_source="screen")  # type: ignore[arg-type]
        if not path.is_file():
            print(f"  screen book {arm}: MISSING at {path}", flush=True)
            continue
        book = book_mod.load_book(
            settings, arm, starting_cash=STARTING_CASH, card_id="", universe_source="screen"  # type: ignore[arg-type]
        )
        symbols = sorted({o.symbol for o in book.orders})
        print(f"  screen book {arm}: {len(book.orders)} staged order(s) {symbols}", flush=True)

    if final.final_md:
        print("\n--- stage_orders summary ---", flush=True)
        print(final.final_md[:1200], flush=True)


if __name__ == "__main__":
    main()
