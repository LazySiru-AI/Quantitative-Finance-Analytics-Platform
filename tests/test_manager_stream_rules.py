"""The missing proof that layer A (`app.manager.sources_research`) and layer B (`app.manager.rules`)
actually compose: this builds `ManagerSnapshot`s whose `SectionItem`s are shaped EXACTLY the way
`sources_research`'s builders now emit them (see that module for each id/marker convention) and feeds
them through `rules.diff`, asserting the relevant stream rule fires.

Before this feature's fix, `sources_research` emitted `gen-{n}` (a hyphen) while `rules.py` matched
`gen:{n}` (a colon prefix) -- and emitted no `promo:`, `blocker:`, `note:`, `persona:` (stale),
`sweep:`, or `daemon:social` items at all. `tests/test_manager_rules.py` proved the rules fire against
hand-written fixtures shaped however that test's author guessed layer A would look; it could not catch
a mismatch against what layer A actually emits, because it never imports `sources_research`. This file
closes that gap: every fixture below is shaped by hand to match `sources_research`'s real emissions
(field for field, not the rule's own assumptions), not by calling the builders themselves -- the
builders need real upstream data (a vault, a ledger, `promotions.jsonl`, ...) that
`test_manager_sources_research.py` already exercises with mocks; this file's job is narrower and
purely structural: "if layer A emits an item shaped like *this*, does layer B's rule actually see it."
"""

from __future__ import annotations

from app.manager import rules
from app.manager.models import Area, ChangeSet, ManagerSnapshot, Scope, SectionItem, SnapshotSection

# ---------------------------------------------------------------------------
# Fixture helpers -- deliberately a fresh, self-contained copy rather than importing
# tests/test_manager_rules.py's private helpers; this file's fixtures are pinned to layer A's actual
# shapes, not to whatever that other file's helpers evolve to support.
# ---------------------------------------------------------------------------


def _item(
    item_id: str,
    *,
    label: str | None = None,
    figures: dict[str, str] | None = None,
    observed_at: str | None = None,
    text: str = "",
) -> SectionItem:
    return SectionItem(
        id=item_id, label=label or item_id, figures=figures or {}, observed_at=observed_at, text=text,
    )


def _section(
    key: Area,
    *,
    ok: bool = True,
    items: tuple[SectionItem, ...] = (),
    figures: dict[str, str] | None = None,
    text: str = "",
) -> SnapshotSection:
    return SnapshotSection(key=key, ok=ok, text=text, figures=figures or {}, items=items)


def _snap(as_of: str, *, scope: Scope = "owner", sections: tuple[SnapshotSection, ...] = ()) -> ManagerSnapshot:
    return ManagerSnapshot(
        scope=scope, as_of=as_of, generated_at=f"{as_of}T09:45:00+00:00", sections=sections,
    )


PREV_DAY = "2026-09-07"
CUR_DAY = "2026-09-08"
#: After PREV_DAY's midnight -> "new" for stream rules; matches `_stream_cutoff`'s anchor on
#: `previous.as_of` (see `app.manager.rules`).
STREAM_TS = f"{CUR_DAY}T10:00:00+00:00"


def rule_ids(changes: ChangeSet) -> set[str]:
    return {item.rule for item in changes.items}


def run_diff(prev: ManagerSnapshot | None, cur: ManagerSnapshot) -> ChangeSet:
    return rules.diff(cur, prev, window="yesterday")


# ---------------------------------------------------------------------------
# research: generation_finished, promotion_recorded, blocker_added
# ---------------------------------------------------------------------------


def test_generation_finished_fires_on_sources_researchs_gen_colon_id() -> None:
    """`research_section` emits `gen:{generation}` (a colon, not the old `gen-{generation}` hyphen)
    with the generation's own `finished_at` as `observed_at` -- see
    `sources_research.research_section`'s `gen:` item."""
    prev = _snap(PREV_DAY, sections=(_section("research"),))
    cur = _snap(CUR_DAY, sections=(
        _section("research", items=(
            _item(
                "gen:42", observed_at=STREAM_TS,
                label="Generation 42 (trading, succeeded)",
                figures={"median_excess": "0.031", "q_value": "0.2"},
                text="gen 42: succeeded, 8 candidates, 1 promoted",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"generation_finished"}
    assert changes.items[0].severity == "notable"


def test_promotion_recorded_fires_on_sources_researchs_promo_colon_id() -> None:
    """`research_section` emits `promo:{genome_id}` from `app.evolution.promotion.load_promotions`,
    `observed_at` set to that record's own `promoted_at` -- see `sources_research.research_section`'s
    `promo:` item, added because layer A previously emitted no `promo:` items at all."""
    prev = _snap(PREV_DAY, sections=(_section("research"),))
    cur = _snap(CUR_DAY, sections=(
        _section("research", items=(
            _item(
                "promo:g-9", observed_at=STREAM_TS,
                label="scout promoted (trading)",
                figures={"promoted_count": "1"},
                text="scout (trading) promoted; median excess 0.045",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"promotion_recorded"}
    assert changes.items[0].severity == "notable"
    assert changes.items[0].figures.get("promoted_count") == "1"


def test_blocker_added_fires_on_sources_researchs_blocker_colon_id() -> None:
    """`research_section` emits one `blocker:{i}` item per `NextRoundBriefing.blockers` entry, keyed
    by list position with `observed_at=None` (a diff rule, not a stream one) -- see
    `sources_research.research_section`'s `blocker:` item, added because layer A previously emitted no
    `blocker:` items at all."""
    prev = _snap(PREV_DAY, sections=(_section("research"),))
    cur = _snap(CUR_DAY, sections=(
        _section("research", items=(
            _item(
                "blocker:0", observed_at=None,
                label="No plan file committed for the next round yet.",
                text="No plan file committed for the next round yet.",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"blocker_added"}
    assert changes.items[0].severity == "attention"


# ---------------------------------------------------------------------------
# personas: persona_new_notes, persona_profile_stale
# ---------------------------------------------------------------------------


def test_persona_new_notes_fires_on_sources_researchs_note_colon_id() -> None:
    """`personas_section` emits `note:{slug}` per persona card inside the 7-day lookback, mirroring
    the card's own `note_count`/`headline`/`as_of` -- see `sources_research.personas_section`'s
    `note:` item, added because layer A previously only emitted the bare-slug persona item."""
    prev = _snap(PREV_DAY, sections=(_section("personas"),))
    cur = _snap(CUR_DAY, sections=(
        _section("personas", items=(
            _item(
                "note:buffett", observed_at=STREAM_TS,
                label="New note: Warren Buffett",
                figures={"note_count": "12"},
                text="Turned bullish on semis",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"persona_new_notes"}
    assert changes.items[0].severity == "fyi"


def test_persona_profile_stale_fires_on_sources_researchs_persona_colon_id_with_stale_marker() -> None:
    """`personas_section` emits `persona:{slug}` only when `app.personas.service.chat_context` reports
    `stale=True`, with `"...profile is stale: ..."` in `text` -- see
    `sources_research.personas_section`'s `persona:` item, added because layer A previously emitted no
    `persona:`-prefixed items at all (the bare-slug item never carries the `STALE_MARKER` rules.py
    checks for)."""
    prev = _snap(PREV_DAY, sections=(_section("personas"),))
    cur = _snap(CUR_DAY, sections=(
        _section("personas", items=(
            _item(
                "persona:buffett", observed_at=STREAM_TS,
                label="Warren Buffett",
                text="Warren Buffett profile is stale: 12 note(s) on file, profile covers 3.",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"persona_profile_stale"}
    assert changes.items[0].severity == "notable"


# ---------------------------------------------------------------------------
# data: refresh_sweep_failed, social_daemon_unhealthy
# ---------------------------------------------------------------------------


def test_refresh_sweep_failed_fires_on_sources_researchs_sweep_colon_id() -> None:
    """`data_section` emits `sweep:refresh` when `app.market.refresh.status()['failed'] > 0` or
    `['error']` is set, with `"refresh sweep failed: ..."` in `text` -- see
    `sources_research.data_section`'s `sweep:` item, added because layer A previously emitted no
    `sweep:`-prefixed items at all."""
    prev = _snap(PREV_DAY, sections=(_section("data"),))
    cur = _snap(CUR_DAY, sections=(
        _section("data", items=(
            _item(
                "sweep:refresh", observed_at=STREAM_TS,
                label="Market data refresh sweep",
                text="refresh sweep failed: 3 symbol(s) failed",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"refresh_sweep_failed"}
    assert changes.items[0].severity == "attention"


def test_social_daemon_unhealthy_fires_on_sources_researchs_daemon_social_id() -> None:
    """`data_section` emits the literal id `daemon:social` when
    `app.market.social_history.status()['healthy']` is `False`, with `"...unhealthy..."` in `text` --
    see `sources_research.data_section`'s `daemon:social` item, added because layer A previously
    emitted no such item at all."""
    prev = _snap(PREV_DAY, sections=(_section("data"),))
    cur = _snap(CUR_DAY, sections=(
        _section("data", items=(
            _item(
                "daemon:social", observed_at=STREAM_TS,
                label="Social snapshot daemon",
                text="social snapshot daemon is unhealthy: 6 consecutive failed tick(s) "
                     "(last error: connection reset).",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"social_daemon_unhealthy"}
    assert changes.items[0].severity == "attention"


# ---------------------------------------------------------------------------
# desks / live: desk_run_finished, desk_run_failed, live_decision_made
# ---------------------------------------------------------------------------


def test_desk_run_finished_fires_on_sources_researchs_run_id_and_text() -> None:
    """`desks_section` puts `"{kind} · {state}"` in `text` and `stages_done`/`stages_total` in
    `figures`, keyed by the run's own `run_id` -- verifying this composes rather than changing it,
    per the brief (this rule was already believed to work)."""
    prev = _snap(PREV_DAY, sections=(_section("desks"),))
    cur = _snap(CUR_DAY, sections=(
        _section("desks", items=(
            _item(
                "run-abc123", observed_at=STREAM_TS,
                label="tradingagents · succeeded",
                figures={"cost_usd": "1.50", "stages_done": "6", "stages_total": "6"},
                text="tradingagents · succeeded, rating buy",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"desk_run_finished"}
    assert changes.items[0].severity == "notable"


def test_desk_run_failed_fires_on_sources_researchs_run_id_and_text() -> None:
    """A `state=="failed"` run's `text` is `"{kind} · failed"` -- the literal `FAILED_MARKER`
    substring `rules._desk_run_failed` checks for -- verifying this composes rather than changing it,
    per the brief (this rule was already believed to work, contingent on this exact text shape)."""
    prev = _snap(PREV_DAY, sections=(_section("desks"),))
    cur = _snap(CUR_DAY, sections=(
        _section("desks", items=(
            _item(
                "run-def456", observed_at=STREAM_TS,
                label="tradingagents · failed",
                figures={"cost_usd": "0.80", "stages_done": "2", "stages_total": "6"},
                text="tradingagents · failed",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"desk_run_failed"}
    assert changes.items[0].severity == "attention"


def test_live_decision_made_fires_on_sources_researchs_symbol_decided_at_id() -> None:
    """`live_section` keys each item `"{symbol}-{decided_at.isoformat()}"` -- verifying this composes
    rather than changing it, per the brief (this rule was already believed to work)."""
    prev = _snap(PREV_DAY, sections=(_section("live"),))
    cur = _snap(CUR_DAY, sections=(
        _section("live", items=(
            _item(
                "AAPL-2026-09-08T10:00:00+00:00", observed_at=STREAM_TS,
                label="AAPL · bullish",
                figures={"confidence": "0.72", "price": "228.10", "cost_usd": "0.03"},
                text="bullish: RSI turned up on strong volume",
            ),
        )),
    ))

    changes = run_diff(prev, cur)

    assert rule_ids(changes) == {"live_decision_made"}
    assert changes.items[0].severity == "notable"
