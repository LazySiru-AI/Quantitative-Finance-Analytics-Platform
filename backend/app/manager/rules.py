"""Layer B change detection: `diff` turns a pair of `ManagerSnapshot`s into a `ChangeSet`.

**No model calls anywhere in this module.** Every rule is a small, pure, deterministic function of two
snapshots (and, for one rule, a cross-section lookup within them) -- this is what lets the manager tab
show "what changed" even while the agent layer is down, and what lets each rule be tested in complete
isolation from every other one.

Two mechanisms, matching `docs/MANAGER-DESK-PLAN.md` §4:

1. **Diff rules** compare a `SectionItem`/`SnapshotSection` in `current` against its counterpart (same
   `id`, or the section's own figures) in `previous`. They require both snapshots, so they produce
   nothing when `previous is None` -- there is nothing to diff against on the tab's first-ever day.
2. **Stream rules** surface `SectionItem`s in `current` whose own `observed_at` is newer than
   `previous.as_of` (or, absent a previous snapshot, newer than the window's own lookback from
   `current.as_of`). These need only `current`, which is exactly why `previous is None` still yields a
   useful, non-empty `ChangeSet` -- streams still fire.

Every rule is registered in `_REGISTRY` under its own id from `models.RULES`; `RULE_IDS` exposes the
registered set for a test (or a future caller) to assert against the pinned catalogue. A rule never
runs against a section that is `ok=False` in the snapshot(s) it needs -- `diff()` gates that centrally
so no individual rule function has to re-check it -- but every `ok=False` area in `current` still lands
in `ChangeSet.sections_missing`, named, never silently dropped.

Id-prefix conventions used by the item-level rules below (`wl:`, `note:`, `persona:`, `gen:`, `promo:`,
`blocker:`, `sweep:`, and the literal id `daemon:social`) are this module's own reading of the generic
`SnapshotSection`/`SectionItem` shape pinned in `models.py` -- layer A (`sources_owner`/
`sources_research`) is unbuilt as of this writing, so these are documented choices for whichever
builder wires up each area, not something copied from existing code.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.manager.models import (
    RULES,
    Area,
    ChangeItem,
    ChangeSet,
    ManagerSnapshot,
    SectionItem,
    Severity,
    SnapshotSection,
    SourceRef,
    Window,
)

__all__ = ["RULE_IDS", "diff"]

# ---------------------------------------------------------------------------
# Thresholds -- named constants, read here and nowhere inlined.
# ---------------------------------------------------------------------------

#: `position_weight_moved` severities: |delta weight| in [NOTABLE, ATTENTION) -> notable, >= ATTENTION
#: -> attention. Below NOTABLE is noise (a position's weight jitters with the market every day).
POSITION_WEIGHT_NOTABLE = Decimal("0.02")
POSITION_WEIGHT_ATTENTION = Decimal("0.05")
#: `position_day_move`: a position must have moved at least this much today...
POSITION_DAY_MOVE_PCT = Decimal("0.03")
#: ...and be at least this large a slice of the book, so a 10%-in-a-day move in a 0.1%-weight position
#: does not read as an "attention" item.
POSITION_DAY_MOVE_MIN_WEIGHT = Decimal("0.02")
#: `cash_below_floor`: the owner's own comfort floor, not a margin-call level.
CASH_FLOOR_USD = Decimal("1000")
#: `wash_window_closing`: a wash-sale replacement window inside this many days of clearing is worth a
#: flag; the exact rule window (30 days) lives in the tax engine, not here.
WASH_CLOSING_DAYS = Decimal("3")
#: `ytd_net_gain_crossed`: a round, materiality-sized number -- crossing it (in either direction, by
#: magnitude) is worth a look even without a specific tax-planning trigger behind it.
YTD_NET_GAIN_THRESHOLD_USD = Decimal("10000")
#: `seat_excess_moved`.
SEAT_EXCESS_MOVE = Decimal("0.02")
#: `book_drawdown_deepened`: drawdown must have worsened (gotten more negative) by at least this much.
BOOK_DRAWDOWN_WORSEN = Decimal("0.02")
#: `macro_beyond_week_range`: the day move must clear this floor before "bigger than the week move" is
#: worth reporting -- otherwise two near-zero numbers on a quiet day trip the rule on rounding noise.
MACRO_DAY_MIN_ABS = Decimal("0.005")
#: `fear_greed_regime_changed` band edges (CNN Fear & Greed convention: 0-100).
FEAR_GREED_BANDS: tuple[Decimal, Decimal, Decimal, Decimal] = (
    Decimal("25"), Decimal("45"), Decimal("55"), Decimal("75"),
)
FEAR_GREED_BAND_NAMES: tuple[str, str, str, str, str] = (
    "extreme_fear", "fear", "neutral", "greed", "extreme_greed",
)

#: `new_tax_warning_group`: a `SectionItem.text` may carry `;`-separated tokens; a token starting with
#: this marker names a tax-warning group (e.g. `"tax-warning:wash-sale"`).
TAX_WARNING_MARKER = "tax-warning:"
#: Substring markers `SectionItem.text` is checked for, case-insensitively. Layer A's own convention
#: (see the module docstring); a plain substring rather than a closed vocabulary because `text` is
#: documented in `models.py` as "one dense line the model may read", not a structured field.
STALE_MARKER = "stale"
FAILED_MARKER = "failed"
UNHEALTHY_MARKER = "unhealthy"
PROMOTED_MARKER = "promoted"

#: Id prefixes that distinguish sub-kinds of item within one section's flat `items` tuple.
GEN_ID_PREFIX = "gen:"
PROMO_ID_PREFIX = "promo:"
BLOCKER_ID_PREFIX = "blocker:"
NOTE_ID_PREFIX = "note:"
WATCHLIST_ID_PREFIX = "wl:"
PERSONA_ID_PREFIX = "persona:"
SWEEP_ID_PREFIX = "sweep:"
SOCIAL_DAEMON_ID = "daemon:social"

#: How far back a stream rule looks when there is no `previous` snapshot to anchor on (the tab's
#: first-ever day for this scope) -- one calendar day for "yesterday", seven for "week"; "custom" falls
#: back to one day rather than guessing a caller-specific span.
_STREAM_WINDOW_DAYS: dict[str, int] = {"yesterday": 1, "week": 7, "custom": 1}


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _dec(raw: str | None) -> Decimal | None:
    """Parse a figure string, or `None` for a missing/unparseable one -- never raises."""
    if raw is None:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _parse_dt(raw: str | None) -> dt.datetime | None:
    """Parse an ISO-8601 timestamp (accepting a trailing `Z`), or `None` -- never raises. A naive
    result is treated as UTC, matching every other timestamp in this codebase."""
    if raw is None:
        return None
    text = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _pct(value: Decimal) -> str:
    return f"{value * 100:+.1f}%"


def _by_id(section: SnapshotSection) -> dict[str, SectionItem]:
    return {item.id: item for item in section.items}


def _stance(item: SectionItem) -> str:
    """`"bullish"`/`"bearish"`/`"neutral"` from a personas item's bullish/bearish tallies."""
    bull = _dec(item.figures.get("bullish_count")) or Decimal(0)
    bear = _dec(item.figures.get("bearish_count")) or Decimal(0)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "neutral"


def _fear_greed_band(value: Decimal) -> str:
    edges = FEAR_GREED_BANDS
    for edge, name in zip(edges, FEAR_GREED_BAND_NAMES[:-1], strict=False):
        if value < edge:
            return name
    return FEAR_GREED_BAND_NAMES[-1]


def _tax_warning_groups(item: SectionItem) -> set[str]:
    groups: set[str] = set()
    for raw_token in item.text.split(";"):
        token = raw_token.strip()
        if token.startswith(TAX_WARNING_MARKER):
            groups.add(token[len(TAX_WARNING_MARKER):].strip())
    return groups


def _pass_through_figures(item: SectionItem, keys: tuple[str, ...]) -> dict[str, str]:
    """`item.figures` restricted to `keys` -- the raw decimal-string values layer A wrote, carried
    through verbatim rather than re-derived, for stream rules that have nothing to compute."""
    return {key: value for key, value in item.figures.items() if key in keys}


def _stream_cutoff(
    current: ManagerSnapshot, previous: ManagerSnapshot | None, window: Window
) -> dt.datetime:
    """The instant a stream item's `observed_at` must be strictly newer than to surface."""
    if previous is not None:
        anchor = dt.date.fromisoformat(previous.as_of)
        return dt.datetime.combine(anchor, dt.time.min, tzinfo=dt.UTC)
    anchor = dt.date.fromisoformat(current.as_of)
    span = _STREAM_WINDOW_DAYS.get(window, 1)
    return dt.datetime.combine(anchor - dt.timedelta(days=span), dt.time.min, tzinfo=dt.UTC)


@dataclass(frozen=True)
class _Ctx:
    """What every rule function is handed alongside its own area's section pair. Carries the whole
    snapshots (not just the pair) so the one cross-section rule (`stance_flipped_on_holding`) can reach
    into `account` without every other rule needing that plumbing."""

    current: ManagerSnapshot
    previous: ManagerSnapshot | None
    window: Window
    prior_snapshot: str | None
    stream_cutoff: dt.datetime


def _is_stream_new(item: SectionItem, ctx: _Ctx) -> bool:
    observed = _parse_dt(item.observed_at)
    return observed is not None and observed > ctx.stream_cutoff


def _change(
    *,
    rule: str,
    area: Area,
    severity: Severity,
    item_id: str,
    headline: str,
    detail: str = "",
    as_of: str | None = None,
    observed_at: str | None = None,
    figures: dict[str, str] | None = None,
    source_refs: tuple[SourceRef, ...] = (),
) -> ChangeItem:
    return ChangeItem(
        id=f"{rule}:{area}:{item_id}",
        area=area,
        rule=rule,
        severity=severity,
        headline=_clip(headline, 160),
        detail=_clip(detail, 320),
        as_of=as_of,
        observed_at=observed_at,
        figures=figures or {},
        source_refs=source_refs,
    )


_RuleFn = Callable[[SnapshotSection, "SnapshotSection | None", _Ctx], Iterable[ChangeItem]]


# ---------------------------------------------------------------------------
# account
# ---------------------------------------------------------------------------


def _position_weight_moved(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_by_id = _by_id(prev)
    for item in cur.items:
        p = prev_by_id.get(item.id)
        if p is None:
            continue
        cw = _dec(item.figures.get("weight_pct"))
        pw = _dec(p.figures.get("weight_pct"))
        if cw is None or pw is None:
            continue
        delta = cw - pw
        if abs(delta) < POSITION_WEIGHT_NOTABLE:
            continue
        severity: Severity = "attention" if abs(delta) >= POSITION_WEIGHT_ATTENTION else "notable"
        yield _change(
            rule="position_weight_moved", area="account", severity=severity, item_id=item.id,
            headline=f"{item.id} weight moved {_pct(delta)} to {_pct(cw)}",
            detail=f"{item.id} portfolio weight moved from {_pct(pw)} to {_pct(cw)} ({_pct(delta)}).",
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={
                "weight_pct": str(cw), "prev_weight_pct": str(pw), "delta_weight_pct": str(delta),
            },
            source_refs=item.refs,
        )


def _position_day_move(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    for item in cur.items:
        move = _dec(item.figures.get("day_change_pct"))
        weight = _dec(item.figures.get("weight_pct"))
        if move is None or weight is None:
            continue
        if abs(move) < POSITION_DAY_MOVE_PCT or weight < POSITION_DAY_MOVE_MIN_WEIGHT:
            continue
        yield _change(
            rule="position_day_move", area="account", severity="attention", item_id=item.id,
            headline=f"{item.id} moved {_pct(move)} today",
            detail=f"{item.id} is {_pct(weight)} of the book and moved {_pct(move)} today.",
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={"day_change_pct": str(move), "weight_pct": str(weight)},
            source_refs=item.refs,
        )


def _symbol_became_unpriced(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_by_id = _by_id(prev)
    for item in cur.items:
        p = prev_by_id.get(item.id)
        if p is None or "market_value" not in p.figures:
            continue
        if "market_value" in item.figures:
            continue
        yield _change(
            rule="symbol_became_unpriced", area="account", severity="attention", item_id=item.id,
            headline=f"{item.id} lost its price",
            detail=f"{item.id} had a market value yesterday but has none today.",
            as_of=cur.as_of, observed_at=item.observed_at,
            source_refs=item.refs,
        )


def _equity_incomplete(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    cur_unpriced = _dec(cur.figures.get("unpriced_count"))
    if cur_unpriced is None or cur_unpriced <= 0:
        return
    prev_unpriced = _dec(prev.figures.get("unpriced_count"))
    if prev_unpriced is not None and prev_unpriced > 0:
        return
    yield _change(
        rule="equity_incomplete", area="account", severity="notable", item_id="_section",
        headline="Account totals are incomplete today",
        detail=f"{cur_unpriced} position(s) are unpriced, so total equity is a partial figure.",
        as_of=cur.as_of,
        figures={"unpriced_count": str(cur_unpriced)},
    )


def _new_tax_warning_group(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_by_id = _by_id(prev)
    for item in cur.items:
        cur_groups = _tax_warning_groups(item)
        if not cur_groups:
            continue
        p = prev_by_id.get(item.id)
        prev_groups = _tax_warning_groups(p) if p is not None else set()
        new_groups = sorted(cur_groups - prev_groups)
        if not new_groups:
            continue
        yield _change(
            rule="new_tax_warning_group", area="account", severity="notable", item_id=item.id,
            headline=f"{item.id} picked up a new tax warning",
            detail=f"{item.id} now carries the {', '.join(new_groups)} tax warning group(s).",
            as_of=cur.as_of, observed_at=item.observed_at,
            source_refs=item.refs,
        )


def _cash_below_floor(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    cash = _dec(cur.figures.get("cash_balance"))
    if cash is None or cash >= CASH_FLOOR_USD:
        return
    yield _change(
        rule="cash_below_floor", area="account", severity="notable", item_id="_section",
        headline=f"Cash balance is below the ${CASH_FLOOR_USD} floor",
        detail=f"Cash balance is ${cash}, below the ${CASH_FLOOR_USD} floor.",
        as_of=cur.as_of,
        figures={"cash_balance": str(cash)},
    )


# ---------------------------------------------------------------------------
# tax
# ---------------------------------------------------------------------------


def _wash_window_opened(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_by_id = _by_id(prev)
    for item in cur.items:
        cur_days = _dec(item.figures.get("days_until_safe"))
        if cur_days is None:
            continue
        p = prev_by_id.get(item.id)
        prev_days = _dec(p.figures.get("days_until_safe")) if p is not None else None
        if prev_days is not None:
            continue
        yield _change(
            rule="wash_window_opened", area="tax", severity="notable", item_id=item.id,
            headline=f"{item.id} opened a wash-sale window",
            detail=f"{item.id} now has an open wash-sale window ({cur_days} day(s) until safe).",
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={"days_until_safe": str(cur_days)},
            source_refs=item.refs,
        )


def _wash_window_closing(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_by_id = _by_id(prev)
    for item in cur.items:
        cur_days = _dec(item.figures.get("days_until_safe"))
        if cur_days is None or cur_days > WASH_CLOSING_DAYS:
            continue
        p = prev_by_id.get(item.id)
        prev_days = _dec(p.figures.get("days_until_safe")) if p is not None else None
        if prev_days is not None and prev_days <= WASH_CLOSING_DAYS:
            continue
        yield _change(
            rule="wash_window_closing", area="tax", severity="attention", item_id=item.id,
            headline=f"{item.id} wash-sale window closes in {cur_days}d",
            detail=f"{item.id}'s wash-sale window is {cur_days} day(s) from clearing.",
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={"days_until_safe": str(cur_days)},
            source_refs=item.refs,
        )


def _ytd_net_gain_crossed(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    cur_gain = _dec(cur.figures.get("ytd_net_gain"))
    prev_gain = _dec(prev.figures.get("ytd_net_gain"))
    if cur_gain is None or prev_gain is None:
        return
    if not (abs(prev_gain) < YTD_NET_GAIN_THRESHOLD_USD <= abs(cur_gain)):
        return
    yield _change(
        rule="ytd_net_gain_crossed", area="tax", severity="notable", item_id="_section",
        headline=f"YTD net gain crossed ${YTD_NET_GAIN_THRESHOLD_USD}",
        detail=f"YTD net gain moved from ${prev_gain} to ${cur_gain}.",
        as_of=cur.as_of,
        figures={"ytd_net_gain": str(cur_gain), "prev_ytd_net_gain": str(prev_gain)},
    )


def _new_permanent_disallowance(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    cur_amt = _dec(cur.figures.get("permanently_disallowed")) or Decimal(0)
    prev_amt = _dec(prev.figures.get("permanently_disallowed")) or Decimal(0)
    if cur_amt <= prev_amt:
        return
    yield _change(
        rule="new_permanent_disallowance", area="tax", severity="attention", item_id="_section",
        headline="New permanently disallowed loss",
        detail=f"Permanently disallowed losses rose from ${prev_amt} to ${cur_amt}.",
        as_of=cur.as_of,
        figures={
            "permanently_disallowed": str(cur_amt), "prev_permanently_disallowed": str(prev_amt),
        },
    )


# ---------------------------------------------------------------------------
# paperdesk / persona_books / persona_traders
# ---------------------------------------------------------------------------


def _seat_excess_moved(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_by_id = _by_id(prev)
    for item in cur.items:
        p = prev_by_id.get(item.id)
        if p is None:
            continue
        cur_excess = _dec(item.figures.get("excess_return"))
        prev_excess = _dec(p.figures.get("excess_return"))
        if cur_excess is None or prev_excess is None:
            continue
        delta = cur_excess - prev_excess
        if abs(delta) < SEAT_EXCESS_MOVE:
            continue
        yield _change(
            rule="seat_excess_moved", area="paperdesk", severity="notable", item_id=item.id,
            headline=f"{item.id} excess return moved {_pct(delta)}",
            detail=f"{item.id}'s excess return moved from {_pct(prev_excess)} to {_pct(cur_excess)}.",
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={
                "excess_return": str(cur_excess), "prev_excess_return": str(prev_excess),
                "delta_excess_return": str(delta),
            },
            source_refs=item.refs,
        )


def _book_drawdown_deepened(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    cur_dd = _dec(cur.figures.get("max_drawdown"))
    prev_dd = _dec(prev.figures.get("max_drawdown"))
    if cur_dd is None or prev_dd is None:
        return
    delta = cur_dd - prev_dd
    if delta > -BOOK_DRAWDOWN_WORSEN:
        return
    yield _change(
        rule="book_drawdown_deepened", area="paperdesk", severity="attention", item_id="_section",
        headline=f"Drawdown deepened to {_pct(cur_dd)}",
        detail=f"Max drawdown moved from {_pct(prev_dd)} to {_pct(cur_dd)}.",
        as_of=cur.as_of,
        figures={
            "max_drawdown": str(cur_dd), "prev_max_drawdown": str(prev_dd),
            "delta_max_drawdown": str(delta),
        },
    )


def _trader_decision_traded(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_by_id = _by_id(prev)
    for item in cur.items:
        p = prev_by_id.get(item.id)
        if p is None:
            continue
        cur_count = _dec(item.figures.get("decision_count"))
        prev_count = _dec(p.figures.get("decision_count"))
        if cur_count is None or prev_count is None or cur_count <= prev_count:
            continue
        yield _change(
            rule="trader_decision_traded", area="persona_traders", severity="notable",
            item_id=item.id,
            headline=f"{item.id} made a new trading decision",
            detail=f"{item.id}'s decision count rose from {prev_count} to {cur_count}.",
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={"decision_count": str(cur_count), "prev_decision_count": str(prev_count)},
            source_refs=item.refs,
        )


def _seat_promoted(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not _is_stream_new(item, ctx) or PROMOTED_MARKER not in item.text.lower():
            continue
        yield _change(
            rule="seat_promoted", area="paperdesk", severity="notable", item_id=item.id,
            headline=f"{item.id} was promoted",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            source_refs=item.refs,
        )


def _seat_rejected_orders(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not _is_stream_new(item, ctx):
            continue
        rejections = _dec(item.figures.get("rejection_count"))
        if rejections is None or rejections <= 0:
            continue
        yield _change(
            rule="seat_rejected_orders", area="paperdesk", severity="attention", item_id=item.id,
            headline=f"{item.id} had {rejections} order(s) rejected",
            detail=f"{item.id} logged {rejections} rejected order(s) today.",
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={"rejection_count": str(rejections)},
            source_refs=item.refs,
        )


# ---------------------------------------------------------------------------
# research
# ---------------------------------------------------------------------------


def _pending_seat_added(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    cur_n = _dec(cur.figures.get("pending_seats")) or Decimal(0)
    prev_n = _dec(prev.figures.get("pending_seats")) or Decimal(0)
    if cur_n <= prev_n:
        return
    yield _change(
        rule="pending_seat_added", area="research", severity="notable", item_id="_section",
        headline=f"{cur_n} seat(s) pending review",
        detail=f"Pending seats rose from {prev_n} to {cur_n}.",
        as_of=cur.as_of,
        figures={"pending_seats": str(cur_n), "prev_pending_seats": str(prev_n)},
    )


def _blocker_added(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_ids = {item.id for item in prev.items}
    for item in cur.items:
        if not item.id.startswith(BLOCKER_ID_PREFIX) or item.id in prev_ids:
            continue
        yield _change(
            rule="blocker_added", area="research", severity="attention", item_id=item.id,
            headline=f"New blocker: {item.label}",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            source_refs=item.refs,
        )


def _generation_finished(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not item.id.startswith(GEN_ID_PREFIX) or not _is_stream_new(item, ctx):
            continue
        yield _change(
            rule="generation_finished", area="research", severity="notable", item_id=item.id,
            headline=f"Generation finished: {item.label}",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            figures=_pass_through_figures(item, ("generation", "median_excess", "q_value")),
            source_refs=item.refs,
        )


def _promotion_recorded(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not item.id.startswith(PROMO_ID_PREFIX) or not _is_stream_new(item, ctx):
            continue
        yield _change(
            rule="promotion_recorded", area="research", severity="notable", item_id=item.id,
            headline=f"Promotion recorded: {item.label}",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            figures=_pass_through_figures(item, ("promoted_count",)),
            source_refs=item.refs,
        )


# ---------------------------------------------------------------------------
# desks / live
# ---------------------------------------------------------------------------


def _desk_run_finished(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not _is_stream_new(item, ctx) or FAILED_MARKER in item.text.lower():
            continue
        done = _dec(item.figures.get("stages_done"))
        total = _dec(item.figures.get("stages_total"))
        if done is None or total is None or total <= 0 or done < total:
            continue
        yield _change(
            rule="desk_run_finished", area="desks", severity="notable", item_id=item.id,
            headline=f"{item.label} finished",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={"stages_done": str(done), "stages_total": str(total)},
            source_refs=item.refs,
        )


def _desk_run_failed(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not _is_stream_new(item, ctx) or FAILED_MARKER not in item.text.lower():
            continue
        yield _change(
            rule="desk_run_failed", area="desks", severity="attention", item_id=item.id,
            headline=f"{item.label} failed",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            source_refs=item.refs,
        )


def _live_decision_made(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not _is_stream_new(item, ctx):
            continue
        yield _change(
            rule="live_decision_made", area="live", severity="notable", item_id=item.id,
            headline=f"Live decision: {item.label}",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            figures=_pass_through_figures(item, ("confidence", "price", "cost_usd")),
            source_refs=item.refs,
        )


# ---------------------------------------------------------------------------
# personas
# ---------------------------------------------------------------------------


def _persona_new_notes(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not item.id.startswith(NOTE_ID_PREFIX) or not _is_stream_new(item, ctx):
            continue
        yield _change(
            rule="persona_new_notes", area="personas", severity="fyi", item_id=item.id,
            headline=f"New note: {item.label}",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            figures=_pass_through_figures(item, ("note_count",)),
            source_refs=item.refs,
        )


def _watchlist_entrant(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_ids = {item.id for item in prev.items}
    for item in cur.items:
        if not item.id.startswith(WATCHLIST_ID_PREFIX) or item.id in prev_ids:
            continue
        yield _change(
            rule="watchlist_entrant", area="personas", severity="notable", item_id=item.id,
            headline=f"{item.id[len(WATCHLIST_ID_PREFIX):]} entered the watchlist",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            source_refs=item.refs,
        )


def _watchlist_leaver(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    cur_ids = {item.id for item in cur.items}
    for item in prev.items:
        if not item.id.startswith(WATCHLIST_ID_PREFIX) or item.id in cur_ids:
            continue
        yield _change(
            rule="watchlist_leaver", area="personas", severity="notable", item_id=item.id,
            headline=f"{item.id[len(WATCHLIST_ID_PREFIX):]} left the watchlist",
            as_of=cur.as_of,
            source_refs=item.refs,
        )


def _regime_tally_changed(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    deltas: dict[str, Decimal] = {}
    for key in ("risk_on", "risk_off", "mixed"):
        cv = _dec(cur.figures.get(key))
        pv = _dec(prev.figures.get(key))
        if cv is None or pv is None or cv == pv:
            continue
        deltas[key] = cv - pv
    if not deltas:
        return
    parts = ", ".join(f"{key} {'+' if delta >= 0 else ''}{delta}" for key, delta in deltas.items())
    figures = {key: cur.figures[key] for key in deltas}
    figures.update({f"delta_{key}": str(delta) for key, delta in deltas.items()})
    yield _change(
        rule="regime_tally_changed", area="personas", severity="fyi", item_id="_section",
        headline="Persona regime tally shifted",
        detail=f"Regime tally changed: {parts}.",
        as_of=cur.as_of,
        figures=figures,
    )


def _persona_profile_stale(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_by_id = _by_id(prev)
    for item in cur.items:
        if not item.id.startswith(PERSONA_ID_PREFIX) or STALE_MARKER not in item.text.lower():
            continue
        p = prev_by_id.get(item.id)
        if p is not None and STALE_MARKER in p.text.lower():
            continue
        yield _change(
            rule="persona_profile_stale", area="personas", severity="notable", item_id=item.id,
            headline=f"{item.label} profile is stale",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            source_refs=item.refs,
        )


def _stance_flipped_on_holding(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    """Cross-section: a `wl:<SYM>` persona item whose bullish/bearish stance inverted, where `<SYM>`
    is also a currently-held position -- the highest-value rule in the catalogue, per the brief."""
    if prev is None or ctx.previous is None:
        return
    account_cur = ctx.current.section("account")
    account_prev = ctx.previous.section("account")
    if account_cur is None or not account_cur.ok or account_prev is None or not account_prev.ok:
        return
    held_ids = {item.id for item in account_cur.items}
    prev_by_id = _by_id(prev)
    for item in cur.items:
        if not item.id.startswith(WATCHLIST_ID_PREFIX):
            continue
        symbol = item.id[len(WATCHLIST_ID_PREFIX):]
        if symbol not in held_ids:
            continue
        p = prev_by_id.get(item.id)
        if p is None:
            continue
        cur_stance = _stance(item)
        prev_stance = _stance(p)
        if {cur_stance, prev_stance} != {"bullish", "bearish"}:
            continue
        yield _change(
            rule="stance_flipped_on_holding", area="personas", severity="attention",
            item_id=item.id,
            headline=f"Persona stance on {symbol} flipped {prev_stance} to {cur_stance}",
            detail=f"Persona sentiment on held position {symbol} flipped from {prev_stance} "
                   f"to {cur_stance}.",
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={
                "bullish_count": item.figures.get("bullish_count", "0"),
                "bearish_count": item.figures.get("bearish_count", "0"),
            },
            source_refs=item.refs,
        )


# ---------------------------------------------------------------------------
# market / events
# ---------------------------------------------------------------------------


def _macro_beyond_week_range(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    for item in cur.items:
        day = _dec(item.figures.get("change_day"))
        week = _dec(item.figures.get("change_week"))
        if day is None or week is None:
            continue
        if abs(day) < MACRO_DAY_MIN_ABS or abs(day) <= abs(week):
            continue
        yield _change(
            rule="macro_beyond_week_range", area="market", severity="notable", item_id=item.id,
            headline=f"{item.label} moved {_pct(day)} today, beyond its week range",
            detail=f"{item.label}'s day change ({_pct(day)}) exceeds its week change ({_pct(week)}).",
            as_of=cur.as_of, observed_at=item.observed_at,
            figures={"change_day": str(day), "change_week": str(week)},
            source_refs=item.refs,
        )


def _fear_greed_regime_changed(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    cur_v = _dec(cur.figures.get("fear_greed"))
    prev_v = _dec(prev.figures.get("fear_greed"))
    if cur_v is None or prev_v is None:
        return
    cur_band = _fear_greed_band(cur_v)
    prev_band = _fear_greed_band(prev_v)
    if cur_band == prev_band:
        return
    severity: Severity = "attention" if cur_band in ("extreme_fear", "extreme_greed") else "notable"
    yield _change(
        rule="fear_greed_regime_changed", area="market", severity=severity, item_id="_section",
        headline=f"Fear & greed moved from {prev_band} to {cur_band}",
        detail=f"Fear & greed index moved from {prev_v} ({prev_band}) to {cur_v} ({cur_band}).",
        as_of=cur.as_of,
        figures={"fear_greed": str(cur_v), "prev_fear_greed": str(prev_v)},
    )


def _event_entering_window(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not _is_stream_new(item, ctx):
            continue
        yield _change(
            rule="event_entering_window", area="events", severity="notable", item_id=item.id,
            headline=f"{item.label} entering the window",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            figures=_pass_through_figures(item, ("days_until",)),
            source_refs=item.refs,
        )


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


def _source_went_stale(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    if prev is None:
        return
    prev_by_id = _by_id(prev)
    for item in cur.items:
        if STALE_MARKER not in item.text.lower():
            continue
        p = prev_by_id.get(item.id)
        if p is not None and STALE_MARKER in p.text.lower():
            continue
        yield _change(
            rule="source_went_stale", area="data", severity="attention", item_id=item.id,
            headline=f"{item.label} went stale",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            figures=_pass_through_figures(item, ("age_seconds",)),
            source_refs=item.refs,
        )


def _refresh_sweep_failed(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if not item.id.startswith(SWEEP_ID_PREFIX) or not _is_stream_new(item, ctx):
            continue
        if FAILED_MARKER not in item.text.lower():
            continue
        yield _change(
            rule="refresh_sweep_failed", area="data", severity="attention", item_id=item.id,
            headline=f"{item.label} refresh sweep failed",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            source_refs=item.refs,
        )


def _social_daemon_unhealthy(
    cur: SnapshotSection, prev: SnapshotSection | None, ctx: _Ctx
) -> Iterable[ChangeItem]:
    for item in cur.items:
        if item.id != SOCIAL_DAEMON_ID or not _is_stream_new(item, ctx):
            continue
        if UNHEALTHY_MARKER not in item.text.lower():
            continue
        yield _change(
            rule="social_daemon_unhealthy", area="data", severity="attention", item_id=item.id,
            headline="Social daemon is unhealthy",
            detail=item.text,
            as_of=cur.as_of, observed_at=item.observed_at,
            source_refs=item.refs,
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Rule:
    area: Area
    kind: str  # "diff" | "stream"
    fn: _RuleFn


_REGISTRY: dict[str, _Rule] = {
    # account
    "position_weight_moved": _Rule("account", "diff", _position_weight_moved),
    "position_day_move": _Rule("account", "diff", _position_day_move),
    "symbol_became_unpriced": _Rule("account", "diff", _symbol_became_unpriced),
    "equity_incomplete": _Rule("account", "diff", _equity_incomplete),
    "new_tax_warning_group": _Rule("account", "diff", _new_tax_warning_group),
    "cash_below_floor": _Rule("account", "diff", _cash_below_floor),
    # tax
    "wash_window_opened": _Rule("tax", "diff", _wash_window_opened),
    "wash_window_closing": _Rule("tax", "diff", _wash_window_closing),
    "ytd_net_gain_crossed": _Rule("tax", "diff", _ytd_net_gain_crossed),
    "new_permanent_disallowance": _Rule("tax", "diff", _new_permanent_disallowance),
    # paperdesk / persona books / traders
    "seat_excess_moved": _Rule("paperdesk", "diff", _seat_excess_moved),
    "seat_promoted": _Rule("paperdesk", "stream", _seat_promoted),
    "seat_rejected_orders": _Rule("paperdesk", "stream", _seat_rejected_orders),
    "trader_decision_traded": _Rule("persona_traders", "diff", _trader_decision_traded),
    "book_drawdown_deepened": _Rule("paperdesk", "diff", _book_drawdown_deepened),
    # research
    "generation_finished": _Rule("research", "stream", _generation_finished),
    "pending_seat_added": _Rule("research", "diff", _pending_seat_added),
    "blocker_added": _Rule("research", "diff", _blocker_added),
    "promotion_recorded": _Rule("research", "stream", _promotion_recorded),
    # desks / live
    "desk_run_finished": _Rule("desks", "stream", _desk_run_finished),
    "desk_run_failed": _Rule("desks", "stream", _desk_run_failed),
    "live_decision_made": _Rule("live", "stream", _live_decision_made),
    # personas
    "stance_flipped_on_holding": _Rule("personas", "diff", _stance_flipped_on_holding),
    "persona_new_notes": _Rule("personas", "stream", _persona_new_notes),
    "watchlist_entrant": _Rule("personas", "diff", _watchlist_entrant),
    "watchlist_leaver": _Rule("personas", "diff", _watchlist_leaver),
    "regime_tally_changed": _Rule("personas", "diff", _regime_tally_changed),
    "persona_profile_stale": _Rule("personas", "diff", _persona_profile_stale),
    # market / events
    "macro_beyond_week_range": _Rule("market", "diff", _macro_beyond_week_range),
    "fear_greed_regime_changed": _Rule("market", "diff", _fear_greed_regime_changed),
    "event_entering_window": _Rule("events", "stream", _event_entering_window),
    # data
    "source_went_stale": _Rule("data", "diff", _source_went_stale),
    "refresh_sweep_failed": _Rule("data", "stream", _refresh_sweep_failed),
    "social_daemon_unhealthy": _Rule("data", "stream", _social_daemon_unhealthy),
}

#: The registered rule ids -- pinned to be a subset of (here, exactly equal to) `models.RULES`. A test
#: asserts this directly; this module-level assertion fails import for anyone who breaks it too.
RULE_IDS: frozenset[str] = frozenset(_REGISTRY)
assert set(RULES) >= RULE_IDS, "app.manager.rules registered a rule id not in models.RULES"


def diff(
    current: ManagerSnapshot,
    previous: ManagerSnapshot | None,
    *,
    window: Window,
    prior_snapshot: str | None = None,
) -> ChangeSet:
    """Compare `current` against `previous` (or run streams-only when there is none) and return the
    `ChangeSet`. Never raises for missing/incomplete sections -- see the module docstring."""
    ctx = _Ctx(
        current=current, previous=previous, window=window, prior_snapshot=prior_snapshot,
        stream_cutoff=_stream_cutoff(current, previous, window),
    )

    sections_missing = tuple(section.key for section in current.sections if not section.ok)

    items: list[ChangeItem] = []
    for rule in _REGISTRY.values():
        cur_section = current.section(rule.area)
        if cur_section is None:
            continue  # area absent for this scope (e.g. an owner-only area on a member snapshot)
        prev_section = previous.section(rule.area) if previous is not None else None

        if rule.kind == "diff":
            if previous is None or not cur_section.ok:
                continue
            if prev_section is None or not prev_section.ok:
                continue
            items.extend(rule.fn(cur_section, prev_section, ctx))
        else:
            if not cur_section.ok:
                continue
            items.extend(rule.fn(cur_section, prev_section, ctx))

    return ChangeSet(
        window=window,
        since=previous.as_of if previous is not None else None,
        until=current.as_of,
        scope=current.scope,
        items=tuple(items),
        sections_missing=sections_missing,
        prior_snapshot=prior_snapshot,
    )
