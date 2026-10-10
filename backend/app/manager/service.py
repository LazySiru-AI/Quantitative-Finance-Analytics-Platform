"""Thin policy layer for the manager desk (Phase 1: config, changes, snapshot-now).

Mirrors the shape `app.personas.trader_service` / `app.personas.service` already established: this
module resolves settings, calls the layer A/B primitives (`app.manager.sources.collect`,
`app.manager.snapshots`, `app.manager.rules.diff`), and is the only thing `app.api.manager` calls
into. **No model calls happen anywhere in this module** -- briefs, chat and commissions are later
phases (layer C), so everything here works with the agent layer down; `config()` merely *reports*
whether the agent layer is reachable, via `app.agents.client.is_available()`, the same probe
`AgentDeskLanding` already uses.

`ManagerError` mirrors `app.personas.service.PersonaError`'s shape (a message plus the status code
the router should map it to) rather than reusing that class directly, so this package does not take
an import dependency on `app.personas` for an unrelated feature. Phase 1's three functions do not
actually raise it -- `collect` is documented never to raise, and `window` is validated by the router's
own `Literal` query param before `changes()` ever runs -- but the type exists now so layer C's
grounded stages (brief, chat, commissions) have a single error shape to raise into from day one.

Built against `app.manager.snapshots` (`save`/`load`/`latest`/`list_dates`) and `app.manager.rules.
diff` exactly as pinned in this shard's brief. Two things did not match the brief once the sibling
modules actually landed, recorded here rather than papered over:

- `app.manager.sources.collect`'s real signature is `collect(settings, *, scope: Scope, as_of:
  dt.date | None = None) -> ManagerSnapshot` -- no `now` parameter (the brief's pin had one) and
  `scope` has no default (the brief's pin defaulted it to `"owner"`). Every call site below passes
  `scope=` explicitly regardless, so the missing default cost nothing; the `now` seam simply isn't
  there; `collect` computes its own wall clock internally.
- A concurrently-edited copy of `snapshots.py` briefly carried a `latest()` that returned
  `tuple[date, ManagerSnapshot]` plus an extra `window_bounds` helper, and `rules.py` briefly carried
  a `diff()` taking `since`/`until`/`scope` instead of `prior_snapshot`. Both files' own docstrings
  now say explicitly that shape was scope drift from elsewhere in the tree and have settled back to
  the pinned signatures this module is written against below.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import uuid
from decimal import Decimal, InvalidOperation

from app.agentdesk.jobs import RunAlreadyActive, registry
from app.agentdesk.models import DeskRun
from app.agentdesk.store import RunStore
from app.agents.client import is_available
from app.agents.models import AgentBudget, AgentUnavailable, BudgetExhausted
from app.agents.spend import LEDGER, SpendCapExceeded
from app.config import Settings
from app.manager import chat as chat_mod
from app.manager import commissions as commissions_mod
from app.manager import pipeline, snapshots
from app.manager.models import (
    Brief,
    Caps,
    ChangeSet,
    Commission,
    ManagerChatThread,
    ManagerChatTurn,
    ManagerConfig,
    ManagerSnapshot,
    Scope,
    Window,
)
from app.manager.rules import diff
from app.manager.sources import collect

__all__ = [
    "ManagerError",
    "approve_commission",
    "cancel_run",
    "changes",
    "chat_turn",
    "config",
    "create_chat",
    "decline_commission",
    "delete_chat",
    "get_brief",
    "get_chat",
    "get_run",
    "latest_brief",
    "list_chats",
    "list_runs",
    "run_scheduled_brief",
    "snapshot_now",
    "start_brief",
]

_log = logging.getLogger(__name__)

#: Hard cap on turns in one manager chat thread, mirroring `app.personas.chat.MAX_TURNS` -- past this
#: a thread is asked to start a fresh one rather than grow an unbounded, ever-costlier context.
MANAGER_MAX_TURNS = 40


class ManagerError(Exception):
    """A domain error the router maps to an HTTP status. `status_code` carries the mapping so the
    router stays a one-liner (`raise HTTPException(exc.status_code, str(exc))`), the same contract
    `app.personas.service.PersonaError` uses."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def config(settings: Settings) -> ManagerConfig:
    """The manager tab's landing state: caps, autonomy/autopilot settings, whether the agent layer is
    reachable right now, and the two "when did anything last happen" timestamps.

    Every field here is either a settings value or a best-effort read of on-disk state that is
    expected to be absent on day one (no snapshot yet, no manager run yet) -- neither absence is an
    error, both surface as `None`.
    """
    agent_available, agent_reason = is_available()

    caps = Caps(
        brief_usd=settings.manager_brief_cap_usd,
        commission_usd=settings.manager_commission_cap_usd,
        chat_usd=settings.manager_chat_cap_usd,
        daily_usd=format(settings.model_spend_daily_cap_usd, "f"),
    )

    unattended_kinds = tuple(
        kind.strip() for kind in settings.manager_unattended_kinds.split(",") if kind.strip()
    )

    dates = snapshots.list_dates(settings, "owner")
    last_snapshot_at = max(dates).isoformat() if dates else None

    # `RunStore.list_runs` already answers "no runs directory yet" with `()` rather than raising
    # (see its own docstring), so no extra try/except is needed here to satisfy "must not crash when
    # there is no manager run yet".
    runs = RunStore(settings, "manager").list_runs(limit=1)
    last_brief_at = runs[0].created_at.isoformat() if runs else None

    return ManagerConfig(
        agent_available=agent_available,
        agent_reason=agent_reason,
        autonomy=settings.manager_autonomy,
        unattended_kinds=unattended_kinds,
        autopilot_enabled=settings.manager_autopilot_enabled,
        brief_time_et=settings.manager_brief_time_et,
        caps=caps,
        last_brief_at=last_brief_at,
        last_snapshot_at=last_snapshot_at,
        spent_today_usd=format(LEDGER.spent_last_24h(), "f"),
    )


def snapshot_now(settings: Settings, *, scope: Scope = "owner") -> ManagerSnapshot:
    """Collect a fresh snapshot and persist it (`POST /api/manager/snapshot`'s job -- the only place
    in this module that saves; `changes()` below deliberately never does)."""
    snapshot = collect(settings, scope=scope)
    snapshots.save(settings, snapshot)
    _notify_changes(settings, scope=scope)
    return snapshot


def _notify_changes(settings: Settings, *, scope: Scope) -> None:
    """Announce the just-saved snapshot's yesterday-window changes through `app.notify`.

    Runs after the save, never before: the snapshot is the thing that matters, a notification is a
    side effect of it, and the whole body is wrapped so that a notify defect (an unwritable directory,
    a channel that hangs) can only cost a log line. `emit` dedupes on `ChangeItem.id`, so taking three
    snapshots in an afternoon announces each change once rather than three times -- which is why the
    dedupe key is the item's own id and not a derived one.

    On day one there is no prior snapshot, `changes()` diffs against `None` and returns a
    streams-only `ChangeSet`; that is a valid, quiet result, not an error.
    """
    try:
        from app.notify import emit

        for item in changes(settings, window="yesterday", scope=scope).items:
            emit(
                settings,
                kind="manager.change",
                severity=item.severity,
                headline=item.headline,
                detail=item.detail,
                # `kind:id` -- a usable pointer; `str(SourceRef)` would render the model repr.
                refs=tuple(f"{ref.kind}:{ref.id}" for ref in item.source_refs),
                source=f"manager:{item.area}:{item.rule}",
                dedupe_id=item.id,
            )
    except Exception:
        _log.exception("manager: notify hook failed after snapshot; the snapshot itself is saved")


def changes(
    settings: Settings,
    *,
    window: Window,
    date: dt.date | None = None,
    scope: Scope = "owner",
) -> ChangeSet:
    """The change set for `window`, as of `date` (today when omitted).

    `current` prefers a saved snapshot for `date`; when none exists it collects fresh but does **not**
    save -- a read stays a read, saving is `snapshot_now`'s job alone. `previous` selection is the
    feature:

    - `"yesterday"` and `"custom"`: the newest saved snapshot strictly before the current date
      (`snapshots.latest(..., before=current_date)`). For `"custom"`, `date` names the *current* date;
      the semantics are otherwise identical to `"yesterday"`.
    - `"week"`: the newest saved snapshot strictly before `current_date - 7 days`. If none is that
      old, falls back to the single oldest snapshot available (if any) and says so in
      `ChangeSet.warnings`, rather than silently comparing against a too-recent snapshot.

    `previous` may end up `None` (no prior snapshot ever exists) -- a valid, expected day-one state.
    `diff` is handed `None` and returns a streams-only `ChangeSet` rather than this function raising.
    """
    now = _now()
    current_date = date if date is not None else now.date()

    current = snapshots.load(settings, current_date, scope)
    if current is None:
        current = collect(settings, scope=scope, as_of=current_date)

    extra_warnings: tuple[str, ...] = ()
    previous: ManagerSnapshot | None

    if window == "week":
        cutoff = current_date - dt.timedelta(days=7)
        dates = snapshots.list_dates(settings, scope)
        eligible = [d for d in dates if d < cutoff]
        if eligible:
            previous = snapshots.load(settings, max(eligible), scope)
        elif dates:
            oldest = min(dates)
            previous = snapshots.load(settings, oldest, scope)
            extra_warnings = (
                f"no snapshot older than {cutoff.isoformat()}; "
                f"using earliest available ({oldest.isoformat()}) instead",
            )
        else:
            previous = None
    else:  # "yesterday" or "custom"
        previous = snapshots.latest(settings, scope, before=current_date)

    prior_snapshot = previous.as_of if previous is not None else None

    change_set = diff(current, previous, window=window, prior_snapshot=prior_snapshot)
    if extra_warnings:
        change_set = change_set.model_copy(
            update={"warnings": tuple(change_set.warnings) + extra_warnings}
        )
    return change_set


# ---------------------------------------------------------------------------
# Briefs -- one brief is one manager DeskRun (layer C, Phase 2)
# ---------------------------------------------------------------------------


def _pipeline_config(
    settings: Settings, *, window: Window, date: dt.date | None, scope: Scope,
) -> pipeline.ManagerConfig:
    """Map settings + request into the pipeline's internal `ManagerConfig`. The per-brief cap bounds
    all of a brief's grounded stages together; the daily cap is the aggregate `LEDGER` ceiling each
    stage checks before spending."""
    try:
        cap = Decimal(settings.manager_brief_cap_usd)
    except InvalidOperation:
        cap = Decimal("3")
    return pipeline.ManagerConfig(
        window=window, date=date, scope=scope,
        model=settings.manager_model, synthesis_model=settings.manager_synthesis_model,
        cap_usd=cap, daily_cap_usd=settings.model_spend_daily_cap_usd,
    )


def start_brief(
    settings: Settings, *, window: Window = "yesterday", date: dt.date | None = None,
    scope: Scope = "owner",
) -> DeskRun:
    """Kick off one manager brief as a `kind="manager"` DeskRun and return it queued (poll
    `/runs/{run_id}`). Claims the single manager registry slot; a second concurrent brief is a 409.
    Mirrors `app.tradingagents.service.start_run`'s persist-then-registry-start shape exactly."""
    cfg = _pipeline_config(settings, window=window, date=date, scope=scope)
    run_id = uuid.uuid4().hex
    run = DeskRun(
        run_id=run_id, kind="manager", state="queued", created_at=_now(),
        config={"window": window, "date": date.isoformat() if date else None, "scope": scope},
        stages=pipeline.build_stage_plan(), budget=AgentBudget(cap_usd=cfg.cap_usd),
    )
    store = RunStore(settings, "manager")
    store.save(run)
    try:
        registry().start(
            "manager", run_id,
            lambda cancel: pipeline.run_manager_brief(run_id, cfg, settings=settings, cancel=cancel),
        )
    except RunAlreadyActive as exc:
        store.delete(run_id)
        raise ManagerError("a manager brief is already running", status_code=409) from exc
    return run


def run_scheduled_brief(settings: Settings) -> None:
    """The daily loop's seam (`app.manager.loop` calls this). Fire one `window="yesterday"` brief on
    the registry, skipping the tick if a brief (manual or scheduled) is already running -- the manager
    slot serialises, and a daily cadence never overlaps itself in practice."""
    if registry().active("manager") is not None:
        _log.info("manager.run_scheduled_brief: a brief is already active; skipping this tick")
        return
    try:
        start_brief(settings, window="yesterday")
    except ManagerError as exc:  # slot raced between the check and start -- benign
        _log.info("manager.run_scheduled_brief: %s", exc)


def get_run(settings: Settings, run_id: str) -> DeskRun:
    run = RunStore(settings, "manager").load(run_id)
    if run is None:
        raise ManagerError(f"unknown manager run {run_id!r}", status_code=404)
    return run


def list_runs(settings: Settings, *, limit: int = 25) -> tuple[DeskRun, ...]:
    return RunStore(settings, "manager").list_runs(limit=limit)


def cancel_run(settings: Settings, run_id: str) -> DeskRun:
    run = get_run(settings, run_id)
    registry().cancel(run_id)
    return run


def get_brief(settings: Settings, brief_id: str) -> Brief:
    brief = pipeline.load_brief(settings, brief_id)
    if brief is None:
        raise ManagerError(f"unknown brief {brief_id!r}", status_code=404)
    return brief


def latest_brief(settings: Settings) -> Brief:
    brief = pipeline.latest_brief(settings)
    if brief is None:
        raise ManagerError("no brief has been produced yet", status_code=404)
    return brief


# ---------------------------------------------------------------------------
# Chat (layer C, Phase 3)
# ---------------------------------------------------------------------------


def _chat_store(settings: Settings) -> chat_mod.ManagerChatStore:
    return chat_mod.ManagerChatStore(settings)


def list_chats(settings: Settings) -> list[ManagerChatThread]:
    return list(_chat_store(settings).list_threads())


def create_chat(settings: Settings) -> ManagerChatThread:
    now = _now().isoformat()
    thread = ManagerChatThread(
        thread_id=uuid.uuid4().hex, title="", created_at=now, updated_at=now,
        turn_count=0, spent_usd="0", turns=(),
    )
    _chat_store(settings).save_thread(thread)
    return thread


def get_chat(settings: Settings, thread_id: str) -> ManagerChatThread:
    thread = _chat_store(settings).load_thread(thread_id)
    if thread is None:
        raise ManagerError(f"unknown chat thread {thread_id!r}", status_code=404)
    return thread


def delete_chat(settings: Settings, thread_id: str) -> None:
    _chat_store(settings).delete_thread(thread_id)


def _snapshot_and_changes(
    settings: Settings, *, refresh: bool, scope: Scope = "owner",
) -> tuple[ManagerSnapshot, ChangeSet]:
    """The evidence a chat turn grounds in: the latest saved snapshot (or a fresh collect when none
    exists or the caller asked to refresh) plus the change set against the nearest prior snapshot."""
    today = _now().date()
    snap: ManagerSnapshot
    if refresh:
        snap = snapshot_now(settings, scope=scope)
    else:
        loaded = snapshots.load(settings, today, scope) or snapshots.latest(settings, scope)
        snap = loaded if loaded is not None else collect(settings, scope=scope, as_of=today)
    prev = snapshots.latest(settings, scope, before=dt.date.fromisoformat(snap.as_of))
    change_set = diff(snap, prev, window="yesterday", prior_snapshot=prev.as_of if prev else None)
    return snap, change_set


def chat_turn(
    settings: Settings, thread_id: str, *, question: str, refresh: bool = False,
) -> ManagerChatTurn:
    """One grounded manager chat turn, with the thread and budget policy layered over the pure
    `app.manager.chat.chat_turn`. 409 on the turn cap or the thread budget cap; 429 on the daily
    ledger; 503 when the agent layer is unavailable."""
    thread = get_chat(settings, thread_id)
    if thread.turn_count >= MANAGER_MAX_TURNS:
        raise ManagerError("this thread is full; start a new one", status_code=409)
    try:
        spent = Decimal(thread.spent_usd)
        cap = Decimal(settings.manager_chat_cap_usd)
    except InvalidOperation:
        spent, cap = Decimal(0), Decimal("2")
    if spent >= cap:
        raise ManagerError("this thread has reached its spend cap; start a new one", status_code=409)

    try:
        LEDGER.check(settings.model_spend_daily_cap_usd)
    except SpendCapExceeded as exc:
        raise ManagerError(str(exc), status_code=429) from exc

    snap, change_set = _snapshot_and_changes(settings, refresh=refresh)

    try:
        result = chat_mod.chat_turn(
            thread=thread, question=question, snapshot=snap, changes=change_set,
            settings=settings, budget=AgentBudget(cap_usd=cap), model=settings.manager_model,
        )
    except AgentUnavailable as exc:
        raise ManagerError(str(exc), status_code=503) from exc
    except BudgetExhausted as exc:
        raise ManagerError(str(exc), status_code=409) from exc

    turn = result.turn.model_copy(update={"refreshed": refresh})
    new_spent = spent + Decimal(turn.cost_usd)
    title = thread.title or question[:80]
    updated = thread.model_copy(update={
        "title": title, "updated_at": _now().isoformat(),
        "turn_count": thread.turn_count + 1, "spent_usd": format(new_spent, "f"),
        "turns": (*thread.turns, turn),
    })
    _chat_store(settings).save_thread(updated)
    return turn


# ---------------------------------------------------------------------------
# Commissions (layer C, Phase 4)
# ---------------------------------------------------------------------------


def _find_commission(brief: Brief, commission_id: str) -> Commission:
    for commission in brief.commissions:
        if commission.commission_id == commission_id:
            return commission
    raise ManagerError(f"unknown commission {commission_id!r}", status_code=404)


def _persist_commission(settings: Settings, brief: Brief, commission: Commission) -> None:
    """Best-effort write-back of one commission's new state into its brief on disk, so a poll of the
    brief reflects an approve/decline/execution. Never raises past a warning -- the returned
    `Commission` is the source of truth the caller already holds."""
    try:
        updated = tuple(
            commission if c.commission_id == commission.commission_id else c
            for c in brief.commissions
        )
        pipeline._save_brief(settings, brief.model_copy(update={"commissions": updated}))
    except Exception as exc:
        _log.warning("manager: could not persist commission %s: %s", commission.commission_id, exc)


def decline_commission(settings: Settings, brief_id: str, commission_id: str) -> Commission:
    brief = get_brief(settings, brief_id)
    declined = commissions_mod.decline(_find_commission(brief, commission_id))
    _persist_commission(settings, brief, declined)
    return declined


def approve_commission(settings: Settings, brief_id: str, commission_id: str) -> Commission:
    """Approve a proposed commission and start its child research on a background thread (a Trading
    Agents child can take many minutes), returning immediately with the commission `approved`. The
    child's terminal state is written back into the brief when it finishes; poll the brief to see it."""
    brief = get_brief(settings, brief_id)
    approved = commissions_mod.approve(_find_commission(brief, commission_id))
    _persist_commission(settings, brief, approved)

    def _run() -> None:
        result = commissions_mod.execute(approved, settings=settings)
        fresh = pipeline.load_brief(settings, brief_id)
        if fresh is not None:
            _persist_commission(settings, fresh, result)

    threading.Thread(target=_run, name=f"manager-commission-{commission_id[:8]}", daemon=True).start()
    return approved
