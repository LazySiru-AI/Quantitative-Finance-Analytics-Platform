"""Tests for `app.manager.rules.diff` -- one test per rule id in `models.RULES`, plus the
bookkeeping/edge-case contract described in the shard brief.

Each per-rule test builds a minimal (T-1, T) `ManagerSnapshot` pair -- via the `mk_snapshot`/
`mk_section`/`mk_item` helpers below -- that makes exactly that rule fire, then asserts that rule id
(and, where the brief pins it, its severity) appears in the resulting `ChangeSet` and that no other
rule id appears alongside it. Because `diff()` only ever runs a rule against an area that is present in
`current.sections`, a fixture naming only the one or two areas a test cares about is enough to keep
unrelated rules from firing -- see the module docstring in `app.manager.rules` for why that isolation
is structural, not incidental.
"""

from __future__ import annotations

from decimal import Decimal

from app.manager import rules
from app.manager.models import (
    RULES,
    Area,
    ChangeSet,
    ManagerSnapshot,
    Scope,
    SectionItem,
    SnapshotSection,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def mk_item(
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


def mk_section(
    key: Area,
    *,
    ok: bool = True,
    items: tuple[SectionItem, ...] = (),
    figures: dict[str, str] | None = None,
    text: str = "",
    warnings: tuple[str, ...] = (),
    as_of: str | None = None,
) -> SnapshotSection:
    return SnapshotSection(
        key=key, ok=ok, as_of=as_of, text=text, figures=figures or {}, items=items, warnings=warnings,
    )


def mk_snapshot(
    as_of: str, *, scope: Scope = "owner", sections: tuple[SnapshotSection, ...] = ()
) -> ManagerSnapshot:
    return ManagerSnapshot(
        scope=scope, as_of=as_of, generated_at=f"{as_of}T09:45:00+00:00", sections=sections,
    )


PREV_DAY = "2026-09-07"
CUR_DAY = "2026-09-08"
STREAM_TS = f"{CUR_DAY}T10:00:00+00:00"  # after PREV_DAY's midnight -> "new" for stream rules


def rule_ids(changes: ChangeSet) -> set[str]:
    return {item.rule for item in changes.items}


def run_diff(prev: ManagerSnapshot | None, cur: ManagerSnapshot) -> ChangeSet:
    return rules.diff(cur, prev, window="yesterday")


# ---------------------------------------------------------------------------
# account
# ---------------------------------------------------------------------------


class TestPositionWeightMoved:
    def test_fires_attention_on_a_large_weight_move(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("account", items=(mk_item("AAPL", figures={"weight_pct": "0.10"}),)),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", items=(mk_item("AAPL", figures={"weight_pct": "0.16"}),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"position_weight_moved"}
        item = changes.items[0]
        assert item.severity == "attention"
        assert item.area == "account"


class TestPositionDayMove:
    def test_fires_attention_on_a_big_day_move_at_meaningful_weight(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("account"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", items=(
                mk_item("MSFT", figures={"weight_pct": "0.05", "day_change_pct": "-0.04"}),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"position_day_move"}
        assert changes.items[0].severity == "attention"


class TestSymbolBecameUnpriced:
    def test_fires_when_market_value_disappears(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("account", items=(
                mk_item("GOOG", figures={"market_value": "1500.00", "weight_pct": "0.02"}),
            )),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", items=(mk_item("GOOG", figures={"weight_pct": "0.02"}),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"symbol_became_unpriced"}
        assert changes.items[0].severity == "attention"


class TestEquityIncomplete:
    def test_fires_when_unpriced_count_appears_today(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("account"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", figures={"unpriced_count": "2"}),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"equity_incomplete"}
        assert changes.items[0].severity == "notable"


class TestNewTaxWarningGroup:
    def test_fires_when_a_position_picks_up_a_wash_sale_marker(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("account"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", items=(mk_item("TSLA", text="tax-warning:wash-sale"),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"new_tax_warning_group"}
        assert changes.items[0].severity == "notable"


class TestCashBelowFloor:
    def test_fires_when_cash_is_under_the_floor(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("account", figures={"cash_balance": "5000"}),))
        cur = mk_snapshot(CUR_DAY, sections=(mk_section("account", figures={"cash_balance": "500"}),))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"cash_below_floor"}
        assert changes.items[0].severity == "notable"
        assert Decimal(changes.items[0].figures["cash_balance"]) == Decimal("500")


# ---------------------------------------------------------------------------
# tax
# ---------------------------------------------------------------------------


class TestWashWindowOpened:
    def test_fires_when_a_symbol_gets_an_open_window(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("tax"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("tax", items=(mk_item("NFLX", figures={"days_until_safe": "10"}),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"wash_window_opened"}
        assert changes.items[0].severity == "notable"


class TestWashWindowClosing:
    def test_fires_attention_within_the_closing_threshold(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("tax", items=(mk_item("NFLX2", figures={"days_until_safe": "10"}),)),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("tax", items=(mk_item("NFLX2", figures={"days_until_safe": "2"}),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"wash_window_closing"}
        assert changes.items[0].severity == "attention"


class TestYtdNetGainCrossed:
    def test_fires_when_magnitude_crosses_the_threshold(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("tax", figures={"ytd_net_gain": "8000"}),))
        cur = mk_snapshot(CUR_DAY, sections=(mk_section("tax", figures={"ytd_net_gain": "12000"}),))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"ytd_net_gain_crossed"}
        assert changes.items[0].severity == "notable"


class TestNewPermanentDisallowance:
    def test_fires_attention_when_permanently_disallowed_rises(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("tax", figures={"permanently_disallowed": "0"}),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("tax", figures={"permanently_disallowed": "500"}),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"new_permanent_disallowance"}
        assert changes.items[0].severity == "attention"


# ---------------------------------------------------------------------------
# paperdesk / persona_books / persona_traders
# ---------------------------------------------------------------------------


class TestSeatExcessMoved:
    def test_fires_on_a_meaningful_excess_return_move(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("paperdesk", items=(mk_item("seat:mom", figures={"excess_return": "0.01"}),)),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("paperdesk", items=(mk_item("seat:mom", figures={"excess_return": "0.05"}),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"seat_excess_moved"}
        assert changes.items[0].severity == "notable"


class TestSeatPromoted:
    def test_fires_as_a_stream_event_on_promotion(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("paperdesk"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("paperdesk", items=(
                mk_item("seat:val", observed_at=STREAM_TS, text="Seat promoted to the live book."),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"seat_promoted"}
        assert changes.items[0].severity == "notable"


class TestSeatRejectedOrders:
    def test_fires_as_a_stream_event_on_rejections(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("paperdesk"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("paperdesk", items=(
                mk_item("seat:beta", observed_at=STREAM_TS, figures={"rejection_count": "3"}),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"seat_rejected_orders"}
        assert changes.items[0].severity == "attention"


class TestTraderDecisionTraded:
    def test_fires_when_decision_count_rises(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("persona_traders", items=(
                mk_item("persona:buffett", figures={"decision_count": "2"}),
            )),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("persona_traders", items=(
                mk_item("persona:buffett", figures={"decision_count": "3"}),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"trader_decision_traded"}
        assert changes.items[0].severity == "notable"


class TestBookDrawdownDeepened:
    def test_fires_attention_when_drawdown_worsens(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("paperdesk", figures={"max_drawdown": "-0.10"}),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("paperdesk", figures={"max_drawdown": "-0.13"}),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"book_drawdown_deepened"}
        assert changes.items[0].severity == "attention"


# ---------------------------------------------------------------------------
# research
# ---------------------------------------------------------------------------


class TestGenerationFinished:
    def test_fires_as_a_stream_event(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("research"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("research", items=(mk_item("gen:42", observed_at=STREAM_TS),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"generation_finished"}
        assert changes.items[0].severity == "notable"


class TestPendingSeatAdded:
    def test_fires_when_pending_seats_rises(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("research", figures={"pending_seats": "1"}),))
        cur = mk_snapshot(CUR_DAY, sections=(mk_section("research", figures={"pending_seats": "2"}),))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"pending_seat_added"}
        assert changes.items[0].severity == "notable"


class TestBlockerAdded:
    def test_fires_when_a_new_blocker_item_appears(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("research"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("research", items=(mk_item("blocker:1", text="Waiting on broker export."),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"blocker_added"}
        assert changes.items[0].severity == "attention"


class TestPromotionRecorded:
    def test_fires_as_a_stream_event(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("research"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("research", items=(mk_item("promo:7", observed_at=STREAM_TS),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"promotion_recorded"}
        assert changes.items[0].severity == "notable"


# ---------------------------------------------------------------------------
# desks / live
# ---------------------------------------------------------------------------


class TestDeskRunFinished:
    def test_fires_when_all_stages_complete(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("desks"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("desks", items=(
                mk_item(
                    "run:1", observed_at=STREAM_TS, text="All stages complete.",
                    figures={"stages_done": "6", "stages_total": "6"},
                ),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"desk_run_finished"}
        assert changes.items[0].severity == "notable"


class TestDeskRunFailed:
    def test_fires_when_the_run_reports_failed(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("desks"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("desks", items=(
                mk_item("run:2", observed_at=STREAM_TS, text="Run failed during triage stage."),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"desk_run_failed"}
        assert changes.items[0].severity == "attention"


class TestLiveDecisionMade:
    def test_fires_as_a_stream_event(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("live"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("live", items=(mk_item("dec:1", observed_at=STREAM_TS),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"live_decision_made"}
        assert changes.items[0].severity == "notable"


# ---------------------------------------------------------------------------
# personas
# ---------------------------------------------------------------------------


class TestStanceFlippedOnHolding:
    def test_fires_attention_when_a_held_symbols_stance_inverts(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("account", items=(mk_item("AAPL"),)),
            mk_section("personas", items=(
                mk_item("wl:AAPL", figures={"bullish_count": "5", "bearish_count": "1"}),
            )),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", items=(mk_item("AAPL"),)),
            mk_section("personas", items=(
                mk_item("wl:AAPL", figures={"bullish_count": "1", "bearish_count": "5"}),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"stance_flipped_on_holding"}
        assert changes.items[0].severity == "attention"

    def test_does_not_fire_when_the_symbol_is_not_held(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("account", items=(mk_item("MSFT"),)),
            mk_section("personas", items=(
                mk_item("wl:AAPL", figures={"bullish_count": "5", "bearish_count": "1"}),
            )),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", items=(mk_item("MSFT"),)),
            mk_section("personas", items=(
                mk_item("wl:AAPL", figures={"bullish_count": "1", "bearish_count": "5"}),
            )),
        ))

        changes = run_diff(prev, cur)

        assert "stance_flipped_on_holding" not in rule_ids(changes)


class TestPersonaNewNotes:
    def test_fires_as_a_stream_event(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("personas"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("personas", items=(
                mk_item("note:123", observed_at=STREAM_TS, label="New idea on NVDA"),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"persona_new_notes"}
        assert changes.items[0].severity == "fyi"


class TestWatchlistEntrant:
    def test_fires_when_a_symbol_newly_appears(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("personas"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("personas", items=(mk_item("wl:NVDA"),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"watchlist_entrant"}
        assert changes.items[0].severity == "notable"


class TestWatchlistLeaver:
    def test_fires_when_a_symbol_disappears(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("personas", items=(mk_item("wl:AMD"),)),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(mk_section("personas"),))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"watchlist_leaver"}
        assert changes.items[0].severity == "notable"


class TestRegimeTallyChanged:
    def test_fires_when_the_section_level_tally_shifts(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("personas", figures={"risk_on": "3"}),))
        cur = mk_snapshot(CUR_DAY, sections=(mk_section("personas", figures={"risk_on": "5"}),))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"regime_tally_changed"}
        assert changes.items[0].severity == "fyi"


class TestPersonaProfileStale:
    def test_fires_when_a_profile_newly_reports_stale(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("personas"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("personas", items=(
                mk_item("persona:buffett", text="Profile is stale: no notes in 90 days."),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"persona_profile_stale"}
        assert changes.items[0].severity == "notable"


# ---------------------------------------------------------------------------
# market / events
# ---------------------------------------------------------------------------


class TestMacroBeyondWeekRange:
    def test_fires_when_the_day_move_exceeds_the_week_move(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("market"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("market", items=(
                mk_item("VIX", figures={"change_day": "0.08", "change_week": "0.02"}),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"macro_beyond_week_range"}
        assert changes.items[0].severity == "notable"


class TestFearGreedRegimeChanged:
    def test_fires_notable_on_a_non_extreme_band_change(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("market", figures={"fear_greed": "40"}),))
        cur = mk_snapshot(CUR_DAY, sections=(mk_section("market", figures={"fear_greed": "60"}),))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"fear_greed_regime_changed"}
        assert changes.items[0].severity == "notable"

    def test_fires_attention_when_the_new_band_is_extreme(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("market", figures={"fear_greed": "40"}),))
        cur = mk_snapshot(CUR_DAY, sections=(mk_section("market", figures={"fear_greed": "80"}),))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"fear_greed_regime_changed"}
        assert changes.items[0].severity == "attention"


class TestEventEnteringWindow:
    def test_fires_as_a_stream_event(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("events"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("events", items=(mk_item("evt:fomc", observed_at=STREAM_TS),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"event_entering_window"}
        assert changes.items[0].severity == "notable"


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------


class TestSourceWentStale:
    def test_fires_when_status_flips_fresh_to_stale(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("data", items=(mk_item("src:polygon", text="fresh"),)),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("data", items=(mk_item("src:polygon", text="data went stale"),)),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"source_went_stale"}
        assert changes.items[0].severity == "attention"


class TestRefreshSweepFailed:
    def test_fires_as_a_stream_event(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("data"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("data", items=(
                mk_item("sweep:daily", observed_at=STREAM_TS, text="Refresh sweep failed."),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"refresh_sweep_failed"}
        assert changes.items[0].severity == "attention"


class TestSocialDaemonUnhealthy:
    def test_fires_as_a_stream_event(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("data"),))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("data", items=(
                mk_item("daemon:social", observed_at=STREAM_TS, text="Social daemon is unhealthy."),
            )),
        ))

        changes = run_diff(prev, cur)

        assert rule_ids(changes) == {"social_daemon_unhealthy"}
        assert changes.items[0].severity == "attention"


# ---------------------------------------------------------------------------
# Registry + bookkeeping contract
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registered_rule_ids_are_a_subset_of_models_rules(self) -> None:
        assert set(RULES) >= rules.RULE_IDS

    def test_every_pinned_rule_id_is_registered(self) -> None:
        # This shard implements all 34 pinned ids -- see the report for the (empty) "not implemented"
        # list. If that ever changes, this is the test that should be relaxed, deliberately.
        assert set(RULES) == rules.RULE_IDS


class TestNoPreviousSnapshot:
    def test_yields_streams_only_with_since_none_and_no_crash(self) -> None:
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("desks", items=(
                mk_item(
                    "run:1", observed_at=STREAM_TS, text="done",
                    figures={"stages_done": "1", "stages_total": "1"},
                ),
            )),
        ))

        changes = rules.diff(cur, None, window="yesterday")

        assert changes.since is None
        assert changes.until == CUR_DAY
        assert changes.prior_snapshot is None
        assert rule_ids(changes) == {"desk_run_finished"}

    def test_diff_only_rules_produce_nothing_without_a_previous_snapshot(self) -> None:
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", items=(mk_item("AAPL", figures={"weight_pct": "0.10"}),)),
        ))

        changes = rules.diff(cur, None, window="yesterday")

        assert changes.items == ()


class TestOkFalseSection:
    def test_missing_section_is_named_and_produces_no_false_no_change(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("account", items=(mk_item("AAPL", figures={"weight_pct": "0.10"}),)),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", ok=False, warnings=("ledger unreachable",)),
        ))

        changes = rules.diff(cur, prev, window="yesterday")

        assert changes.sections_missing == ("account",)
        assert not any(item.area == "account" for item in changes.items)


class TestNoFalsePositiveOnUnchangedPair:
    def test_an_identical_pair_produces_nothing(self) -> None:
        section = mk_section(
            "account",
            items=(mk_item("AAPL", figures={"weight_pct": "0.10"}),),
            figures={"cash_balance": "50000"},
        )
        prev = mk_snapshot(PREV_DAY, sections=(section,))
        cur = mk_snapshot(CUR_DAY, sections=(section,))

        changes = rules.diff(cur, prev, window="yesterday")

        assert changes.items == ()


class TestFiguresAreDecimalParseable:
    def test_every_emitted_figure_value_parses_as_decimal(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(
            mk_section("account", items=(mk_item("AAPL", figures={"weight_pct": "0.10"}),)),
            mk_section("tax", figures={"ytd_net_gain": "8000"}),
            mk_section("market", items=(
                mk_item("VIX", figures={"change_day": "0.08", "change_week": "0.02"}),
            )),
        ))
        cur = mk_snapshot(CUR_DAY, sections=(
            mk_section("account", items=(mk_item("AAPL", figures={"weight_pct": "0.16"}),)),
            mk_section("tax", figures={"ytd_net_gain": "12000"}),
            mk_section("market", items=(
                mk_item("VIX", figures={"change_day": "0.08", "change_week": "0.02"}),
            )),
        ))

        changes = rules.diff(cur, prev, window="yesterday", prior_snapshot="2026-09-07.owner.json")

        assert changes.items  # sanity: the fixture actually produced something to check
        for item in changes.items:
            for value in item.figures.values():
                Decimal(value)  # raises if not parseable


class TestChangeSetBookkeeping:
    def test_since_until_and_prior_snapshot_are_populated(self) -> None:
        prev = mk_snapshot(PREV_DAY, sections=(mk_section("tax", figures={"ytd_net_gain": "8000"}),))
        cur = mk_snapshot(CUR_DAY, sections=(mk_section("tax", figures={"ytd_net_gain": "12000"}),))

        changes = rules.diff(
            cur, prev, window="week", prior_snapshot="2026-09-07.owner.json",
        )

        assert changes.since == PREV_DAY
        assert changes.until == CUR_DAY
        assert changes.window == "week"
        assert changes.scope == "owner"
        assert changes.prior_snapshot == "2026-09-07.owner.json"
