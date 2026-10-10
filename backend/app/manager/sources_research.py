"""Layer A builders for everything the app has learned or observed: the research programme, desk
runs, live decisions, personas, market, events, news and data health. See `app.manager.models` for
the pinned shapes every builder here returns, in particular `FIGURE_KEYS` for the figure names each
area may emit.

Every builder: `(ctx: SourceContext) -> SnapshotSection` with `key` equal to its own area. Money and
rates are decimal STRINGS (a rate is a 0-1 fraction). Where a source cannot say when it last changed
-- four of the freshness catalogue's sources share a URL-less HTTP cache -- the section reports the
age as unknown rather than implying it is current.

**`SourceContext` is imported from `app.manager.sources`, the shared dataclass (`settings`, `as_of`,
`scope`, `now`) that module's `collect()` builds once per snapshot and passes to every builder in
this module and its `sources_owner` sibling. (For a while during this feature's build the two modules
disagreed -- `sources.py` had briefly regressed to a monolithic `collect()` with no `SourceContext` at
all, and this module carried its own reproduced-verbatim copy of the dataclass as a stopgap so its own
builders and tests stayed self-contained. `app.manager.sources` is back to being the dispatcher +
`SourceContext` owner it was built against, so that stopgap copy is gone and this import is the only
`SourceContext` there is.)

**Import style, and why it matters for tests.** Every upstream call below is bound at module level
under its own name (`get_next_round_briefing`, `list_evolution_generations`, `RunStore`, ...) rather
than referenced as `some_module.func(...)` inline. A test forces a builder's `ok=False` path by
monkeypatching that name directly on this module (`monkeypatch.setattr(sources_research,
"get_next_round_briefing", raiser)`) -- which works regardless of whether the name started life as a
plain function, a class, or an aliased import, because the patch lands on the attribute this module
actually calls.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import math
from decimal import Decimal

from app.agentdesk.live_loop import list_decisions as list_live_decisions
from app.agentdesk.models import DeskKind
from app.agentdesk.store import RunStore
from app.api.competition_narrative import next_round as get_next_round_briefing
from app.evolution.history import list_generations as list_evolution_generations
from app.evolution.promotion import load_promotions, read_pending_seats
from app.manager.models import SectionItem, SnapshotSection, SourceRef
from app.manager.sources import SourceContext
from app.market.calendar import build_calendar
from app.market.freshness import report as freshness_report
from app.market.macro import build_snapshot as build_macro_snapshot
from app.market.news import build_macro_panel
from app.market.social_history import status as social_daemon_status
from app.personas.service import chat_context as persona_chat_context
from app.personas.service import list_cards as list_persona_cards
from app.personas.service import regime as persona_regime
from app.personas.service import watchlist as persona_watchlist

__all__ = [
    "SourceContext",
    "data_section",
    "desks_section",
    "events_section",
    "live_section",
    "market_section",
    "news_section",
    "personas_section",
    "research_section",
]

#: The three desk kinds `desks_section` reads. `"manager"` is a fourth `DeskKind` (the manager's own
#: commissioned runs) and is deliberately excluded -- this section reports on the research/live desks,
#: not on itself.
_DESK_KINDS: tuple[DeskKind, ...] = ("tradingagents", "vibedesk", "workflow")

#: How far back `desks_section` and `live_section` look for "recent". Bounded, per this module's own
#: brief, rather than an unbounded scan of every run/decision ever recorded.
_LOOKBACK = dt.timedelta(days=7)

#: Per-kind cap on how many runs `RunStore.list_runs` is asked for, so a desk with a long history
#: never turns one snapshot collection into an unbounded disk read.
_RUN_LIMIT = 25


def _figs(**values: object) -> dict[str, str]:
    """Build a `figures` dict from keyword values, dropping any that are `None` or a non-finite float
    -- the "never a fabricated zero" rule applied at the one place every builder below constructs a
    figures mapping. Every surviving value is stringified so it parses as `Decimal` downstream."""
    out: dict[str, str] = {}
    for key, value in values.items():
        if value is None:
            continue
        if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
            continue
        out[key] = str(value)
    return out


def _dedupe_id(candidate: str, seen: set[str]) -> str:
    """`candidate`, or `candidate#2`, `candidate#3`, ... the first time it collides -- so a section
    whose natural id (a URL, a kind+date+title triple) is not guaranteed unique still produces unique
    `SectionItem.id`s, per this module's own contract."""
    item_id = candidate
    suffix = 2
    while item_id in seen:
        item_id = f"{candidate}#{suffix}"
        suffix += 1
    seen.add(item_id)
    return item_id


# ---------------------------------------------------------------------------
# research: the competition/evolution programme
# ---------------------------------------------------------------------------


def research_section(ctx: SourceContext) -> SnapshotSection:
    try:
        briefing = get_next_round_briefing()
        page, _total, _unreadable = list_evolution_generations(ctx.settings, limit=10)
        seats = read_pending_seats(ctx.settings)
    except Exception as exc:
        return SnapshotSection(
            key="research",
            ok=False,
            warnings=(f"research programme unavailable: {type(exc).__name__}: {exc}",),
        )

    pending = [seat for seat in seats if seat.status == "pending"]

    items: list[SectionItem] = []
    for summary in page:
        median_excess = summary.leader.median_excess if summary.leader else None
        q_value = summary.field.q_value.median if summary.field.q_value else None
        items.append(
            SectionItem(
                id=f"gen:{summary.generation}",
                label=f"Generation {summary.generation} ({summary.purpose}, {summary.status})",
                figures=_figs(median_excess=median_excess, q_value=q_value),
                observed_at=summary.finished_at.isoformat(),
                refs=(
                    SourceRef(
                        kind="gen", id=str(summary.generation), label=f"gen {summary.generation}"
                    ),
                ),
                text=(
                    f"gen {summary.generation}: {summary.status}, {summary.candidates} candidates, "
                    f"{len(summary.promoted)} promoted"
                ),
            )
        )

    for seat in pending:
        items.append(
            SectionItem(
                id=seat.genome_id,
                label=f"{seat.agent_id} ({seat.purpose}) seat request",
                figures=_figs(median_excess=seat.median_excess, q_value=seat.q_value),
                observed_at=seat.requested_at.isoformat(),
                refs=(SourceRef(kind="seat", id=seat.genome_id, label=seat.genome_id),),
                text=seat.reason[:200],
            )
        )

    #: Blockers are next-round-briefing prose, not a stable-id upstream record, so `blocker_added`
    #: keys on list position within this collect -- the rule itself only needs the id to be absent
    #: from `previous` to count as new, and `observed_at` is deliberately left `None` (see the rule's
    #: own docstring: it is a diff rule, not a stream rule, so it does not need one).
    for i, blocker_text in enumerate(briefing.blockers):
        items.append(
            SectionItem(
                id=f"blocker:{i}",
                label=blocker_text,
                observed_at=None,
                text=blocker_text,
            )
        )

    #: Promotions recorded in the lookback window, read from the append-only audit trail
    #: (`app.evolution.promotion.load_promotions`) rather than re-derived from `page`'s own
    #: `GenerationSummary.promoted` -- this is the record with a real `promoted_at` timestamp, which
    #: `promotion_recorded` (a stream rule) needs to tell "new" from "old". A read failure here must
    #: not sink the rest of an otherwise-healthy research section -- see the module docstring's
    #: fail-soft convention -- so it is guarded on its own rather than folded into the try/except above.
    promo_warnings: list[str] = []
    window_start = ctx.now - _LOOKBACK
    try:
        promotions = load_promotions(ctx.settings)
    except Exception as exc:
        promotions = ()
        promo_warnings.append(f"promotions unavailable: {type(exc).__name__}: {exc}")

    for record in promotions:
        if record.promoted_at < window_start:
            continue
        items.append(
            SectionItem(
                id=f"promo:{record.genome_id}",
                label=f"{record.agent_id} promoted ({record.purpose})",
                figures=_figs(promoted_count=1),
                observed_at=record.promoted_at.isoformat(),
                refs=(SourceRef(kind="seat", id=record.genome_id, label=record.genome_id),),
                text=(
                    f"{record.agent_id} ({record.purpose}) promoted; "
                    f"median excess {record.median_excess}"
                ),
            )
        )

    generation = page[0].generation if page else None
    #: Promotions within the fetched window only (bounded, per this module's own "never scan
    #: everything" rule) -- not a lifetime total.
    promoted_count = sum(len(summary.promoted) for summary in page)

    text = (
        f"next round {briefing.next_round_id} (pre_registered={briefing.pre_registered}), "
        f"{len(briefing.blockers)} blockers; "
        f"latest generation {generation if generation is not None else 'n/a'}, "
        f"{promoted_count} promoted across last {len(page)} generations, "
        f"{len(pending)} pending seats"
    )

    return SnapshotSection(
        key="research",
        ok=True,
        as_of=ctx.now.isoformat(),
        text=text,
        figures=_figs(generation=generation, promoted_count=promoted_count, pending_seats=len(pending)),
        items=tuple(items),
        warnings=tuple(promo_warnings),
    )


# ---------------------------------------------------------------------------
# desks: TradingAgents / VibeDesk / Agent Workflow runs
# ---------------------------------------------------------------------------


def desks_section(ctx: SourceContext) -> SnapshotSection:
    try:
        window_start = ctx.now - _LOOKBACK
        items: list[SectionItem] = []
        for kind in _DESK_KINDS:
            store = RunStore(ctx.settings, kind)
            for run in store.list_runs(limit=_RUN_LIMIT):
                stamp = run.completed_at or run.created_at
                if stamp < window_start:
                    continue
                stages_total = len(run.stages)
                stages_done = sum(1 for stage in run.stages if stage.state not in ("pending", "running"))
                label = f"{kind} · {run.state}"
                text_bits = [label]
                if run.final_rating:
                    text_bits.append(f"rating {run.final_rating}")
                if run.degraded:
                    text_bits.append("degraded")
                items.append(
                    SectionItem(
                        id=run.run_id,
                        label=label,
                        figures=_figs(
                            cost_usd=run.cost_usd,
                            stages_done=stages_done,
                            stages_total=stages_total,
                        ),
                        observed_at=stamp.isoformat(),
                        refs=(
                            SourceRef(kind="run", id=run.run_id, label=f"{kind} {run.run_id[:8]}"),
                        ),
                        text=", ".join(text_bits),
                    )
                )
    except Exception as exc:
        return SnapshotSection(
            key="desks", ok=False, warnings=(f"desk runs unavailable: {type(exc).__name__}: {exc}",)
        )

    total_cost = sum(
        (Decimal(item.figures["cost_usd"]) for item in items if "cost_usd" in item.figures),
        Decimal("0"),
    )
    total_done = sum(int(item.figures.get("stages_done", 0)) for item in items)
    total_stages = sum(int(item.figures.get("stages_total", 0)) for item in items)

    return SnapshotSection(
        key="desks",
        ok=True,
        as_of=ctx.now.isoformat(),
        text=f"{len(items)} desk runs in the last 7 days; ${total_cost} total cost.",
        figures=_figs(cost_usd=total_cost, stages_done=total_done, stages_total=total_stages),
        items=tuple(items),
    )


# ---------------------------------------------------------------------------
# live: the live-decision loop
# ---------------------------------------------------------------------------


def live_section(ctx: SourceContext) -> SnapshotSection:
    try:
        records = list_live_decisions(ctx.settings, limit=100)
    except Exception as exc:
        return SnapshotSection(
            key="live", ok=False, warnings=(f"live decisions unavailable: {type(exc).__name__}: {exc}",)
        )

    items: list[SectionItem] = []
    confidences: list[float] = []
    total_cost = Decimal("0")
    for record in records:
        confidences.append(record.confidence)
        with contextlib.suppress(Exception):
            # One malformed cost string must not blank the whole section.
            total_cost += Decimal(record.cost_usd)
        rationale = record.rationale.strip()
        if len(rationale) > 160:
            rationale = rationale[:157] + "..."
        items.append(
            SectionItem(
                id=f"{record.symbol}-{record.decided_at.isoformat()}",
                label=f"{record.symbol} · {record.stance}",
                figures=_figs(confidence=record.confidence, price=record.price, cost_usd=record.cost_usd),
                observed_at=record.decided_at.isoformat(),
                refs=(SourceRef(kind="symbol", id=record.symbol, label=record.symbol),),
                text=f"{record.stance}: {rationale}",
            )
        )

    avg_confidence = sum(confidences) / len(confidences) if confidences else None

    return SnapshotSection(
        key="live",
        ok=True,
        as_of=ctx.now.isoformat(),
        text=f"{len(items)} live decisions in the recent window; total cost ${total_cost}.",
        figures=_figs(confidence=avg_confidence, cost_usd=total_cost),
        items=tuple(items),
    )


# ---------------------------------------------------------------------------
# personas: influencer digest, watchlist, regime
# ---------------------------------------------------------------------------


def personas_section(ctx: SourceContext) -> SnapshotSection:
    try:
        cards = list_persona_cards(ctx.settings)
        wl = persona_watchlist(ctx.settings)
        reg = persona_regime(ctx.settings)
    except Exception as exc:
        return SnapshotSection(
            key="personas", ok=False, warnings=(f"personas unavailable: {type(exc).__name__}: {exc}",)
        )

    items: list[SectionItem] = []
    persona_warnings: list[str] = []
    window_start = ctx.now - _LOOKBACK
    for card in cards:
        items.append(
            SectionItem(
                id=card.persona.slug,
                label=card.persona.display_name,
                figures=_figs(note_count=card.note_count),
                observed_at=card.as_of.isoformat() if card.as_of else None,
                refs=(
                    SourceRef(kind="persona", id=card.persona.slug, label=card.persona.display_name),
                ),
                text=card.headline,
            )
        )

        #: A `note:` item per persona whose card is recent -- this is what lets `persona_new_notes`
        #: (a stream rule keyed on the `note:` id prefix) see this persona's own card as "new" without
        #: colliding with the bare-slug item above, which the diff/cross-section rules already key on.
        if card.as_of is not None and card.as_of >= window_start:
            items.append(
                SectionItem(
                    id=f"note:{card.persona.slug}",
                    label=f"New note: {card.persona.display_name}",
                    figures=_figs(note_count=card.note_count),
                    observed_at=card.as_of.isoformat(),
                    refs=(
                        SourceRef(kind="persona", id=card.persona.slug, label=card.persona.display_name),
                    ),
                    text=card.headline,
                )
            )

        #: A `persona:` item, present only when the consolidated profile is actually stale -- guarded
        #: per persona so one broken vault read cannot sink every other persona's row, and this is a
        #: local vault read (`app.personas.service.chat_context`), never a network call, so doing it
        #: once per persona here does not turn this collect into an unbounded fan-out.
        try:
            chat_ctx = persona_chat_context(ctx.settings, card.persona.slug)
        except Exception as exc:
            persona_warnings.append(
                f"chat context unavailable for {card.persona.slug}: {type(exc).__name__}: {exc}"
            )
        else:
            if chat_ctx.stale:
                items.append(
                    SectionItem(
                        id=f"persona:{card.persona.slug}",
                        label=card.persona.display_name,
                        observed_at=card.as_of.isoformat() if card.as_of else None,
                        refs=(
                            SourceRef(
                                kind="persona", id=card.persona.slug, label=card.persona.display_name
                            ),
                        ),
                        text=(
                            f"{card.persona.display_name} profile is stale: "
                            f"{chat_ctx.note_count} note(s) on file, profile covers "
                            f"{chat_ctx.profile_note_count}."
                        ),
                    )
                )

    for entry in wl.entries:
        items.append(
            SectionItem(
                id=f"wl:{entry.symbol}",
                label=entry.symbol,
                figures=_figs(bullish_count=entry.bullish_count, bearish_count=entry.bearish_count),
                observed_at=entry.as_of.isoformat() if entry.as_of else None,
                refs=(SourceRef(kind="symbol", id=entry.symbol, label=entry.symbol),),
                text=entry.latest_reasoning or (
                    f"{entry.bullish_count} bullish / {entry.bearish_count} bearish"
                ),
            )
        )

    text = (
        f"{len(cards)} personas tracked; regime {reg.risk_on} risk-on / {reg.risk_off} risk-off / "
        f"{reg.mixed} mixed; {len(wl.entries)} watchlist symbols"
    )

    return SnapshotSection(
        key="personas",
        ok=True,
        as_of=reg.as_of.isoformat(),
        text=text,
        figures=_figs(risk_on=reg.risk_on, risk_off=reg.risk_off, mixed=reg.mixed),
        items=tuple(items),
        warnings=tuple(persona_warnings),
    )


# ---------------------------------------------------------------------------
# market: macro rates/oil/fear-greed/movers
# ---------------------------------------------------------------------------


def market_section(ctx: SourceContext) -> SnapshotSection:
    try:
        # Deliberately called with no `as_of`: `build_snapshot`'s own docstring says passing *any*
        # `as_of` -- even today's date -- unconditionally withholds Fear & Greed (CNN has no as-of
        # query). A live collect wants the live reading, so this calls the unbounded, "now" form
        # rather than threading `ctx.as_of` through.
        snap = build_macro_snapshot(ctx.settings)
    except Exception as exc:
        return SnapshotSection(
            key="market", ok=False, warnings=(f"macro snapshot unavailable: {type(exc).__name__}: {exc}",)
        )

    items: list[SectionItem] = []
    for tile in (*snap.rates, *snap.oil):
        items.append(
            SectionItem(
                id=tile.key,
                label=tile.label,
                figures=_figs(
                    value=tile.value,
                    change_day=tile.change.day,
                    change_week=tile.change.week,
                    change_month=tile.change.month,
                ),
                observed_at=tile.as_of.isoformat() if tile.as_of else None,
                refs=(SourceRef(kind="symbol", id=tile.key, label=tile.label),),
                text=f"{tile.label}: {tile.value}" if tile.value is not None else f"{tile.label}: n/a",
            )
        )
    for mover in snap.movers:
        items.append(
            SectionItem(
                id=mover.symbol,
                label=mover.label,
                figures=_figs(
                    value=mover.price,
                    change_day=mover.change.day,
                    change_week=mover.change.week,
                    change_month=mover.change.month,
                ),
                observed_at=mover.as_of.isoformat() if mover.as_of else None,
                refs=(SourceRef(kind="symbol", id=mover.symbol, label=mover.label),),
                text=f"{mover.label}: {mover.price}" if mover.price is not None else f"{mover.label}: n/a",
            )
        )

    warnings: tuple[str, ...] = ()
    fear_greed_score: float | None = None
    if snap.fear_greed is not None:
        fear_greed_score = snap.fear_greed.score
    else:
        warnings = ("fear & greed withheld this collect (no live CNN reading available)",)

    text = (
        f"{len(items)} macro tiles; "
        f"fear & greed {fear_greed_score if fear_greed_score is not None else 'n/a'}"
    )

    return SnapshotSection(
        key="market",
        ok=True,
        as_of=snap.generated_at.isoformat(),
        text=text,
        figures=_figs(fear_greed=fear_greed_score),
        items=tuple(items),
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# events: FOMC + portfolio earnings calendar
# ---------------------------------------------------------------------------


def events_section(ctx: SourceContext) -> SnapshotSection:
    try:
        cal = build_calendar(days=7, settings=ctx.settings, today=ctx.as_of)
    except Exception as exc:
        return SnapshotSection(
            key="events", ok=False, warnings=(f"event calendar unavailable: {type(exc).__name__}: {exc}",)
        )

    items: list[SectionItem] = []
    seen_ids: set[str] = set()
    for event in cal.events:
        item_id = _dedupe_id(f"{event.kind}:{event.date.isoformat()}:{event.symbol or event.title}", seen_ids)
        days_until = (event.date - ctx.as_of).days
        detail = f" ({event.detail})" if event.detail else ""
        items.append(
            SectionItem(
                id=item_id,
                label=event.title,
                figures=_figs(days_until=days_until),
                refs=(SourceRef(kind="event", id=item_id, label=event.title),),
                text=f"{event.kind}: {event.title} [{event.confidence}]{detail}",
            )
        )

    return SnapshotSection(
        key="events",
        ok=True,
        as_of=cal.generated_at.isoformat(),
        text=f"{len(items)} events in the next 7 days.",
        items=tuple(items),
    )


# ---------------------------------------------------------------------------
# news: macro headlines
# ---------------------------------------------------------------------------


def news_section(ctx: SourceContext) -> SnapshotSection:
    try:
        panel = build_macro_panel(ctx.settings, query="", limit=20, as_of=None)
    except Exception as exc:
        return SnapshotSection(
            key="news", ok=False, warnings=(f"macro news unavailable: {type(exc).__name__}: {exc}",)
        )

    items: list[SectionItem] = []
    seen_ids: set[str] = set()
    for article in panel.news:
        item_id = _dedupe_id(article.url, seen_ids)
        title = article.title.strip()
        text = title if len(title) <= 200 else title[:197] + "..."
        items.append(
            SectionItem(
                id=item_id,
                label=title,
                observed_at=article.published.isoformat(),
                refs=(SourceRef(kind="event", id=item_id, label=article.source),),
                text=text,
            )
        )

    return SnapshotSection(
        key="news",
        ok=True,
        as_of=panel.generated_at.isoformat(),
        text=f"{len(items)} macro headlines.",
        figures=_figs(count=len(items)),
        items=tuple(items),
    )


# ---------------------------------------------------------------------------
# data: source freshness health
# ---------------------------------------------------------------------------


def data_section(ctx: SourceContext) -> SnapshotSection:
    try:
        rep = freshness_report(ctx.settings)
    except Exception as exc:
        return SnapshotSection(
            key="data", ok=False, warnings=(f"freshness report unavailable: {type(exc).__name__}: {exc}",)
        )

    sources = rep.get("sources", [])
    items: list[SectionItem] = []
    stale_count = 0
    unknown_count = 0
    for row in sources:
        status = row.get("status")
        if status == "stale":
            stale_count += 1
        elif status == "unknown":
            unknown_count += 1
        detail = row.get("detail", "")
        text = f"{status}: {detail}"
        items.append(
            SectionItem(
                id=row["key"],
                label=row.get("provider") or row["key"],
                # `age_seconds` is only ever populated when the measurement actually knows an age --
                # never guessed from an `unknown` status; see the module docstring and `report`'s own.
                figures=_figs(age_seconds=row.get("age_seconds")),
                observed_at=row.get("last_updated"),
                text=text[:300],
            )
        )

    #: A `sweep:` item when the refresh sweep itself failed -- either it could not run at all
    #: (`error`) or it ran but some symbols failed (`failed > 0`). `report()` already embeds
    #: `refresh.status()` verbatim under `"refresh"` (see that function's own docstring), so this is a
    #: read of data already fetched above, not a second upstream call. Absent entirely when nothing
    #: failed, and absent when the report carries no `"refresh"` key at all (an older/partial report).
    refresh_status: dict[str, object] = rep.get("refresh") or {}
    failed_symbols = refresh_status.get("failed") or 0
    sweep_error = refresh_status.get("error")
    if failed_symbols or sweep_error:
        detail_bits = []
        if sweep_error:
            detail_bits.append(f"error: {sweep_error}")
        if failed_symbols:
            detail_bits.append(f"{failed_symbols} symbol(s) failed")
        observed_at = refresh_status.get("finished_at") or refresh_status.get("started_at")
        items.append(
            SectionItem(
                id="sweep:refresh",
                label="Market data refresh sweep",
                observed_at=observed_at if isinstance(observed_at, str) else None,
                text=f"refresh sweep failed: {'; '.join(detail_bits)}",
            )
        )

    #: A `daemon:social` item when the social snapshot scheduler (`app.market.social_history`) has
    #: gone unhealthy -- guarded on its own call since it is a second upstream lookup `report()` does
    #: not already carry, per the module docstring's fail-soft convention: a failure here degrades to a
    #: warning, never the whole section.
    data_warnings: list[str] = []
    try:
        social = social_daemon_status()
    except Exception as exc:
        social = None
        data_warnings.append(f"social daemon status unavailable: {type(exc).__name__}: {exc}")
    if social is not None and not social.get("healthy", True):
        observed_at = social.get("last_tick_at") or rep.get("as_of")
        items.append(
            SectionItem(
                id="daemon:social",
                label="Social snapshot daemon",
                observed_at=observed_at if isinstance(observed_at, str) else None,
                text=(
                    f"social snapshot daemon is unhealthy: "
                    f"{social.get('consecutive_all_failed_ticks')} consecutive failed tick(s) "
                    f"(last error: {social.get('last_error')})."
                ),
            )
        )

    return SnapshotSection(
        key="data",
        ok=True,
        as_of=rep.get("as_of"),
        text=f"{stale_count} stale, {unknown_count} unknown of {len(sources)} sources.",
        figures=_figs(stale_count=stale_count, unknown_count=unknown_count),
        items=tuple(items),
        warnings=tuple(data_warnings),
    )
