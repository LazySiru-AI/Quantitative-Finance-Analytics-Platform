"""The workflow orchestrator, driven end-to-end with the model layer and market data stubbed.

No test here makes a real model call or reads a real bar. `regime.classify` and `_scan_signals` are
monkeypatched so the deterministic spine runs without market data, and the child-launch helpers are
monkeypatched to return canned `DeskRun`s in place of real Trading Agents / Vibe runs. What is
exercised for real is the orchestration itself: the stage sequence, the per-arm gating, the budget
gate on the fan-out, cancellation propagation, and the fact that every candidate -- passed or
refused -- is written to the study's candidate log before any order is staged.

Strategy cards and the regime map are loaded from the real library (they live under `backend/app/`,
not the temp data dir), so the card sizing and universe are the genuine ones.
"""

from __future__ import annotations

import datetime as dt
import threading
from decimal import Decimal

import pytest

from app.agentdesk.models import DeskRun
from app.agents.models import AgentBudget
from app.workflow import book as book_mod
from app.workflow import candidates as candidates_mod
from app.workflow import pipeline
from app.workflow import service as workflow_service
from app.workflow.pipeline import WorkflowConfig, run_workflow
from app.workflow.regime import RegimeCall
from app.workflow.schemas import WorkflowRunRequest

TRADE_DATE = dt.date(2026, 8, 28)


def _canned_regime(label: str = "risk_on_trend") -> RegimeCall:
    return RegimeCall(label=label, as_of=TRADE_DATE, inputs=(), warnings=(), confidence=Decimal("0.75"))


def _canned_ta_run(symbol: str, *, rating: str, state: str = "succeeded", cost: str = "3.00") -> DeskRun:
    return DeskRun(
        run_id=f"ta-{symbol}",
        kind="tradingagents",
        state=state,
        created_at=dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.UTC),
        completed_at=dt.datetime(2026, 8, 28, 12, 5, tzinfo=dt.UTC),
        config={"symbol": symbol},
        final_md=f"Decision for {symbol}.\n\nRating: {rating}",
        final_rating=rating,
        budget=AgentBudget(cap_usd=Decimal("4.00"), spent_usd=Decimal(cost), calls=1),
    )


def _canned_vibe_run(symbol: str, *, verdict: str, state: str = "succeeded", cost: str = "2.00") -> DeskRun:
    return DeskRun(
        run_id=f"vibe-{symbol}",
        kind="vibedesk",
        state=state,
        created_at=dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.UTC),
        completed_at=dt.datetime(2026, 8, 28, 12, 5, tzinfo=dt.UTC),
        config={"symbol": symbol},
        final_md=f"Review of {symbol}.\n\nVERDICT: {verdict}",
        final_rating="",
        budget=AgentBudget(cap_usd=Decimal("4.00"), spent_usd=Decimal(cost), calls=1),
    )


@pytest.fixture
def stub_desk(monkeypatch: pytest.MonkeyPatch):
    """Stub the model layer and market data, and let the test script each candidate's gate outcomes.

    Returns a small controller the test configures with per-symbol ratings/verdicts before it drives
    the run.
    """

    class Controller:
        def __init__(self) -> None:
            self.firing: list[str] = ["NVDA", "AMD", "INTC"]
            self.ratings: dict[str, str] = {}
            self.verdicts: dict[str, str] = {}
            self.ta_state: dict[str, str] = {}
            self.vibe_final_md: dict[str, str] = {}

    ctl = Controller()

    monkeypatch.setattr(pipeline.regime_mod, "classify", lambda **_: _canned_regime())
    monkeypatch.setattr(
        pipeline, "_scan_signals",
        lambda card, *, settings, as_of, universe=None, entry_rule=None: list(ctl.firing),
    )
    monkeypatch.setattr(pipeline, "_launch_ta", lambda symbol, *, ctx, budget_usd: f"ta-{symbol}")
    monkeypatch.setattr(pipeline, "_launch_vibe", lambda symbol, question, *, ctx, budget_usd: f"vibe-{symbol}")

    def fake_await(kind, run_id, *, settings, cancel):
        symbol = run_id.split("-", 1)[1]
        if kind == "tradingagents":
            return _canned_ta_run(symbol, rating=ctl.ratings.get(symbol, "Hold"),
                                  state=ctl.ta_state.get(symbol, "succeeded"))
        run = _canned_vibe_run(symbol, verdict=ctl.verdicts.get(symbol, "INCONCLUSIVE"))
        if symbol in ctl.vibe_final_md:
            run = run.model_copy(update={"final_md": ctl.vibe_final_md[symbol]})
        return run

    monkeypatch.setattr(pipeline, "_await_child", fake_await)
    return ctl


def _run(settings, *, card_id: str = "B-momentum", **overrides) -> DeskRun:
    """Save an initial workflow run and drive it synchronously in-thread."""
    config = WorkflowConfig(
        agent_card_id=card_id,
        trade_date=TRADE_DATE,
        budget_usd=overrides.get("budget_usd", Decimal("20.00")),
        per_child_budget_usd=overrides.get("per_child_budget_usd", Decimal("4.00")),
        max_research_symbols=overrides.get("max_research_symbols", 3),
        analysts=None,
        debate_rounds=None,
        risk_rounds=None,
        arms_enabled=overrides.get("arms_enabled", ("raw_signal", "ta_gated", "vibe_gated", "full_workflow")),
        model="claude-opus-5",
        universe_mode=overrides.get("universe_mode", "card"),
        selector_id=overrides.get("selector_id"),
        candidate_pool=overrides.get("candidate_pool"),
        rank_key=overrides.get("rank_key"),
        screen_top_n=overrides.get("screen_top_n"),
    )
    from app.agentdesk.store import RunStore

    run = DeskRun(
        run_id=overrides.get("run_id", "wf-test-1"),
        kind="workflow",
        state="queued",
        created_at=dt.datetime(2026, 8, 28, 11, 0, tzinfo=dt.UTC),
        config={"agent_card_id": card_id, "child_runs": {}},
        stages=pipeline.build_stage_plan(config),
        budget=AgentBudget(cap_usd=config.budget_usd),
    )
    RunStore(settings, "workflow").save(run)
    cancel = overrides.get("cancel", threading.Event())
    run_workflow(run.run_id, config, settings=settings, cancel=cancel)
    loaded = RunStore(settings, "workflow").load(run.run_id)
    assert loaded is not None
    return loaded


def _config(**overrides) -> WorkflowConfig:
    """A `WorkflowConfig` with the same defaults `_run` uses, for tests that need to construct and run
    two configs directly (bypassing `_run`'s single-config shape) -- notably the card-mode
    byte-for-byte regression, which must compare a config with `universe_mode` truly omitted (the
    dataclass default) against one with it passed explicitly."""
    defaults: dict[str, object] = dict(
        agent_card_id="B-momentum",
        trade_date=TRADE_DATE,
        budget_usd=Decimal("20.00"),
        per_child_budget_usd=Decimal("4.00"),
        max_research_symbols=3,
        analysts=None,
        debate_rounds=None,
        risk_rounds=None,
        arms_enabled=("raw_signal", "ta_gated", "vibe_gated", "full_workflow"),
        model="claude-opus-5",
    )
    defaults.update(overrides)
    return WorkflowConfig(**defaults)  # type: ignore[arg-type]


def _run_config(settings, config: WorkflowConfig, *, run_id: str) -> DeskRun:
    from app.agentdesk.store import RunStore

    run = DeskRun(
        run_id=run_id,
        kind="workflow",
        state="queued",
        created_at=dt.datetime(2026, 8, 28, 11, 0, tzinfo=dt.UTC),
        config={"agent_card_id": config.agent_card_id, "child_runs": {}},
        stages=pipeline.build_stage_plan(config),
        budget=AgentBudget(cap_usd=config.budget_usd),
    )
    RunStore(settings, "workflow").save(run)
    run_workflow(run_id, config, settings=settings, cancel=threading.Event())
    loaded = RunStore(settings, "workflow").load(run_id)
    assert loaded is not None
    return loaded


def test_screen_run_threads_prior_shortlist_into_the_next_run(settings, stub_desk, monkeypatch) -> None:
    """Live hysteresis: a named selector's second screen run sees the first run's shortlist as its
    `prior_picks`. Proven end-to-end through `run_workflow`/`_stage_universe_select`, not by calling the
    store functions directly -- the whole point of the wiring is that the stage does the load/save."""
    from app.workflow import universe as universe_mod

    seen_prior: list[tuple[str, ...]] = []

    def fake_select_for_workflow(
        selector_id, *, as_of, regime_label, settings, prior_picks, card_universe, top_n_override=None
    ):
        seen_prior.append(tuple(prior_picks))
        return ("AAA", "BBB")

    monkeypatch.setattr(universe_mod, "select_for_workflow", fake_select_for_workflow)

    common = dict(
        universe_mode="screen",
        selector_id="mom12_1_hysteresis",
        arms_enabled=("raw_signal", "full_workflow"),
    )
    _run(settings, run_id="wf-screen-1", **common)
    _run(settings, run_id="wf-screen-2", **common)

    # First run starts hysteresis cold; the second sees the first run's persisted shortlist.
    assert seen_prior == [(), ("AAA", "BBB")]
    assert universe_mod.load_prior_shortlist(settings, selector_id="mom12_1_hysteresis") == ("AAA", "BBB")


def test_card_mode_run_writes_no_prior_shortlist(settings, stub_desk) -> None:
    """Card mode carries no day-over-day state, so it must not touch the hysteresis store at all."""
    from app.workflow import universe as universe_mod

    _run(settings, run_id="wf-card-1")  # default universe_mode="card"
    assert universe_mod.load_prior_shortlist(settings, selector_id="mom12_1_hysteresis") == ()


def test_screen_run_writes_screen_books_never_card_books(settings, stub_desk, monkeypatch) -> None:
    """A screen run must stage into the screen books (`book/screen/<arm>.json`), never the card books
    the in-flight 4-arm study owns. Guards the `_book_source` threading in `_stage_orders`/the gates:
    without it a screen run would load, stage into, and overwrite the card `<arm>.json` files."""
    from app.workflow import book as book_mod
    from app.workflow import universe as universe_mod

    # Empty shortlist -> no candidates fire, but `_stage_orders` still loads+saves each screened arm's
    # book, which is exactly the load/save path whose universe_source we are asserting.
    monkeypatch.setattr(universe_mod, "select_for_workflow", lambda *a, **k: ())

    _run(
        settings, run_id="wf-screen-books",
        universe_mode="screen", selector_id="mom12_1_hysteresis",
        arms_enabled=("raw_signal", "full_workflow"),
    )

    for arm in ("raw_signal", "full_workflow"):
        assert book_mod.book_path(settings, arm, universe_source="screen").is_file(), arm
        assert not book_mod.book_path(settings, arm, universe_source="card").is_file(), arm


def test_full_run_reaches_succeeded_with_all_eight_stage_kinds(settings, stub_desk) -> None:
    """The happy path: regime -> select -> scan -> research xN -> follow-up -> vibe xN -> plan ->
    orders, ending succeeded."""
    stub_desk.ratings = {"NVDA": "Buy", "AMD": "Hold", "INTC": "Overweight"}
    stub_desk.verdicts = {"NVDA": "SUPPORT", "AMD": "REFUTE", "INTC": "SUPPORT"}

    run = _run(settings)

    assert run.state == "succeeded"
    stage_ids = {s.stage_id for s in run.stages}
    assert {"regime_call", "strategy_select", "candidate_scan", "followup_questions",
            "entry_plan", "stage_orders"} <= stage_ids
    assert {"research_NVDA", "research_AMD", "research_INTC"} <= stage_ids
    assert {"vibe_NVDA", "vibe_AMD", "vibe_INTC"} <= stage_ids
    assert all(s.state in ("succeeded", "degraded") for s in run.stages)


@pytest.mark.parametrize(
    "day, expected",
    [
        (dt.date(2026, 9, 3), dt.date(2026, 9, 4)),  # Thursday -> Friday
        (dt.date(2026, 9, 4), dt.date(2026, 9, 7)),  # Friday    -> Monday (never Saturday)
        (dt.date(2026, 9, 5), dt.date(2026, 9, 7)),  # Saturday  -> Monday
        (dt.date(2026, 9, 6), dt.date(2026, 9, 7)),  # Sunday    -> Monday
    ],
)
def test_next_business_day_never_stamps_a_weekend_fill_date(day, expected) -> None:
    """`_stage_orders`' `fill_date` is written verbatim into `Fill.trade_date` and the tax lot's
    `acquired_date` (see `app.workflow.book._order_to_fill` / `held_lots`) and is never re-resolved to a
    real session at fill time. A bare `+1 day` therefore stamped a Saturday acquisition date on every
    Friday session, corrupting the short/long-term boundary and the 61-day wash-sale window. This pins
    the weekday-advancing replacement: a Friday fills Monday, and a date already on the weekend rolls
    forward rather than compounding the error."""
    assert pipeline._next_business_day(day) == expected


def test_each_arm_gates_the_same_candidate_set_differently(settings, stub_desk) -> None:
    """The paired design: the four arms see identical candidates and diverge only at the gate.

    NVDA passes both gates, AMD passes neither, INTC passes only TA. So raw stages 3, ta_gated 2
    (NVDA+INTC), vibe_gated 1 (NVDA), full_workflow 1 (NVDA only, needing both).
    """
    stub_desk.ratings = {"NVDA": "Buy", "AMD": "Hold", "INTC": "Overweight"}
    stub_desk.verdicts = {"NVDA": "SUPPORT", "AMD": "REFUTE", "INTC": "REFUTE"}

    _run(settings)

    def staged(arm: str) -> set[str]:
        book = book_mod.load_book(settings, arm, starting_cash=Decimal("100000"), card_id="B-momentum")
        return {o.symbol for o in book.orders}

    assert staged("raw_signal") == {"NVDA", "AMD", "INTC"}
    assert staged("ta_gated") == {"NVDA", "INTC"}
    assert staged("vibe_gated") == {"NVDA"}
    assert staged("full_workflow") == {"NVDA"}


def test_every_candidate_including_refused_is_logged_before_staging(settings, stub_desk) -> None:
    """The study's refused set: the candidate log must carry AMD (refused everywhere) with its gate
    rulings, which no order book records."""
    stub_desk.ratings = {"NVDA": "Buy", "AMD": "Hold", "INTC": "Overweight"}
    stub_desk.verdicts = {"NVDA": "SUPPORT", "AMD": "REFUTE", "INTC": "REFUTE"}

    _run(settings)

    obs = {o.symbol: o for o in candidates_mod.read_observations(settings=settings)}
    assert set(obs) == {"NVDA", "AMD", "INTC"}
    amd = obs["AMD"]
    gates = {g.gate: g.passed for g in amd.gates}
    assert gates == {"ta_gated": False, "vibe_gated": False, "full_workflow": False}


def test_over_cap_fired_names_are_logged_but_never_researched(settings, stub_desk) -> None:
    """#7: a name that fires beyond `max_research_symbols` is recorded in the observation log with
    `skip_reason="over_cap"` -- so the study's negative record is no longer silently missing every
    name a busy session fired past the cap -- but it is never gated, researched, or staged into any
    arm's book. Research behaviour is unchanged: only the capped top-N reach the books."""
    stub_desk.firing = ["NVDA", "AMD", "INTC"]  # entry_rank 1, 2, 3
    stub_desk.ratings = {"NVDA": "Buy", "AMD": "Buy", "INTC": "Buy"}
    stub_desk.verdicts = {"NVDA": "SUPPORT", "AMD": "SUPPORT", "INTC": "SUPPORT"}

    _run(settings, max_research_symbols=2)

    obs = {o.symbol: o for o in candidates_mod.read_observations(settings=settings)}
    # Every fired name is logged, including the one past the cap.
    assert set(obs) == {"NVDA", "AMD", "INTC"}
    assert obs["INTC"].skip_reason == "over_cap"
    assert obs["NVDA"].skip_reason is None and obs["AMD"].skip_reason is None

    # But research/staging is untouched: only the capped top-2 reach the books, INTC never does --
    # not even the no-gate `raw_signal` arm, which stages every *researched* candidate.
    def staged(arm: str) -> set[str]:
        book = book_mod.load_book(settings, arm, starting_cash=Decimal("100000"), card_id="B-momentum")
        return {o.symbol for o in book.orders}

    assert staged("raw_signal") == {"NVDA", "AMD"}
    assert staged("full_workflow") == {"NVDA", "AMD"}
    assert all("INTC" not in staged(a) for a in ("raw_signal", "ta_gated", "vibe_gated", "full_workflow"))


def test_budget_gate_stops_launching_children_when_exhausted(settings, stub_desk) -> None:
    """A whole-run cap smaller than two children's cost stops the fan-out after the first, marking the
    rest skipped rather than overspending."""
    stub_desk.firing = ["NVDA", "AMD", "INTC"]
    stub_desk.ratings = {"NVDA": "Buy", "AMD": "Buy", "INTC": "Buy"}
    stub_desk.verdicts = {"NVDA": "SUPPORT", "AMD": "SUPPORT", "INTC": "SUPPORT"}

    # cap 5.00, each child costs 3.00 -> the first research child fits, the second does not.
    run = _run(settings, budget_usd=Decimal("5.00"), per_child_budget_usd=Decimal("4.00"))

    research_states = {s.stage_id: s.state for s in run.stages if s.stage_id.startswith("research_")}
    assert research_states["research_NVDA"] in ("succeeded", "degraded")
    assert research_states["research_AMD"] == "skipped"
    assert research_states["research_INTC"] == "skipped"


def test_a_defaulted_vibe_verdict_is_recorded_as_not_explicit(settings, stub_desk) -> None:
    """A Vibe run that never emits a parseable VERDICT defaults to INCONCLUSIVE (no trade) and is
    logged as an abstention, not a judgement."""
    stub_desk.ratings = {"NVDA": "Buy"}
    stub_desk.verdicts = {"NVDA": "SUPPORT"}
    stub_desk.firing = ["NVDA"]
    stub_desk.vibe_final_md = {"NVDA": "A thoughtful review with no verdict line at all."}

    _run(settings)

    (obs,) = candidates_mod.read_observations(settings=settings)
    vibe_gate = next(g for g in obs.gates if g.gate == "vibe_gated")
    assert vibe_gate.passed is False
    assert vibe_gate.was_explicit is False


def test_cancellation_before_the_fanout_skips_the_rest(settings, stub_desk) -> None:
    """A cancel set before the run starts stops it at the first stage boundary, cancelled, with the
    remaining stages skipped and no orders staged."""
    stub_desk.ratings = {"NVDA": "Buy"}
    cancel = threading.Event()
    cancel.set()

    run = _run(settings, cancel=cancel)

    assert run.state == "cancelled"
    book = book_mod.load_book(settings, "raw_signal", starting_cash=Decimal("100000"), card_id="B-momentum")
    assert book.orders == ()


def test_no_candidates_still_completes_and_stages_zero(settings, stub_desk) -> None:
    """A scan that fires nothing completes cleanly: the fan-out and plan stages are skipped, orders
    stage zero, the run succeeds."""
    stub_desk.firing = []

    run = _run(settings)

    assert run.state == "succeeded"
    followup = next(s for s in run.stages if s.stage_id == "followup_questions")
    assert followup.state == "skipped"
    book = book_mod.load_book(settings, "raw_signal", starting_cash=Decimal("100000"), card_id="B-momentum")
    assert book.orders == ()


def test_child_run_ids_are_persisted_to_config_for_the_study(settings, stub_desk) -> None:
    """The study bills each arm's research spend from `DeskRun.config["child_runs"]`; if the pipeline
    only holds that map in memory, every arm's research cost silently computes to zero. So the map
    must be on the persisted run, keyed stage_id -> child run id."""
    stub_desk.firing = ["NVDA", "AMD"]
    stub_desk.ratings = {"NVDA": "Buy", "AMD": "Buy"}
    stub_desk.verdicts = {"NVDA": "SUPPORT", "AMD": "SUPPORT"}

    run = _run(settings)

    child_runs = run.config.get("child_runs")
    assert isinstance(child_runs, dict)
    assert child_runs.get("research_NVDA") == "ta-NVDA"
    assert child_runs.get("vibe_NVDA") == "vibe-NVDA"
    assert child_runs.get("research_AMD") == "ta-AMD"


def test_auto_select_feeds_the_incumbent_books_lots_into_the_tax_switch_check(
    settings, stub_desk, monkeypatch
) -> None:
    """The tax switch check is only real if it sees actual open lots. On an auto-select run whose
    incumbent card differs from the regime's pick, `_choose_card` must derive the full_workflow book's
    held lots and hand them to `evaluate_switch` -- not the empty tuple it used to pass.
    """
    from decimal import Decimal

    from app.workflow import book as book_mod
    from app.workflow import pipeline as pl
    from app.workflow import taxcheck as taxcheck_mod
    from tests.test_workflow_book import _book_with_orders, _filled_order

    # Seed the full_workflow book with a held lot under an incumbent card that is NOT the regime pick,
    # so the switch path (not the "no switch" early return) is taken.
    seeded = _book_with_orders(
        (_filled_order(order_id="o1", symbol="AAA", side="buy", qty="10", price="100",
                       day=dt.date(2026, 3, 3)),)
    ).model_copy(update={"arm": "full_workflow", "current_card_id": "INCUMBENT-CARD"})
    book_mod.save_book(settings, seeded)

    captured: dict[str, object] = {}

    def spy_evaluate_switch(*, positions, **kwargs):
        captured["positions"] = positions
        return taxcheck_mod.SwitchVerdict(
            allowed=True, outcome="allowed", projected_wash_disallowance=Decimal(0),
            st_premium_cost=Decimal(0), days_to_long_term=(), reason="clean",
        )

    monkeypatch.setattr(pl.taxcheck_mod, "evaluate_switch", spy_evaluate_switch)

    _run(settings, card_id=None)

    positions = captured.get("positions")
    assert positions is not None and len(positions) == 1
    assert positions[0].symbol == "AAA"
    assert positions[0].quantity == Decimal("10")
    assert positions[0].acquired_date == dt.date(2026, 3, 3)


def test_service_rejects_unknown_arm_and_bad_budget(settings, monkeypatch) -> None:
    """422 surface: the service validates arms and budget before a run is ever created."""
    monkeypatch.setattr(workflow_service.agents_client, "is_available", lambda: (True, ""))

    with pytest.raises(workflow_service.InvalidRequest):
        workflow_service.start_workflow_run(
            WorkflowRunRequest(arms_enabled=["not_an_arm"]), settings=settings
        )
    with pytest.raises(workflow_service.InvalidRequest):
        workflow_service.start_workflow_run(
            WorkflowRunRequest(budget_usd="-1"), settings=settings
        )


def test_service_reports_agent_unavailable(settings, monkeypatch) -> None:
    """503 surface: no credential means the run cannot launch its research children, so it is refused
    at submission rather than three stages deep."""
    from app.agents.models import AgentUnavailable

    monkeypatch.setattr(
        workflow_service.agents_client, "is_available", lambda: (False, "no credential configured")
    )
    with pytest.raises(AgentUnavailable):
        workflow_service.start_workflow_run(WorkflowRunRequest(), settings=settings)


# ---------------------------------------------------------------------------
# universe_select: stage plumbing
# ---------------------------------------------------------------------------


def test_universe_select_stage_sits_between_strategy_select_and_candidate_scan(settings, stub_desk) -> None:
    stub_desk.ratings = {"NVDA": "Buy", "AMD": "Hold", "INTC": "Overweight"}
    stub_desk.verdicts = {"NVDA": "SUPPORT", "AMD": "REFUTE", "INTC": "SUPPORT"}

    run = _run(settings)

    ids = [s.stage_id for s in run.stages]
    assert "universe_select" in ids
    assert ids.index("strategy_select") < ids.index("universe_select") < ids.index("candidate_scan")

    universe_stage = next(s for s in run.stages if s.stage_id == "universe_select")
    assert universe_stage.depends_on == ("strategy_select",)
    scan_stage = next(s for s in run.stages if s.stage_id == "candidate_scan")
    assert scan_stage.depends_on == ("universe_select",)
    assert universe_stage.state == "succeeded"


def test_universe_mode_card_is_byte_for_byte_unchanged(settings, stub_desk) -> None:
    """The load-bearing regression test: a `WorkflowConfig` with `universe_mode` truly omitted (the
    dataclass default) and one with `universe_mode="card"` passed explicitly must drive the pipeline
    identically -- same universe_select output, same candidate scan, same fired/researched symbols."""
    stub_desk.ratings = {"NVDA": "Buy", "AMD": "Hold", "INTC": "Overweight"}
    stub_desk.verdicts = {"NVDA": "SUPPORT", "AMD": "REFUTE", "INTC": "SUPPORT"}

    default_config = _config()
    assert default_config.universe_mode == "card"  # the dataclass default, never set explicitly here
    run_default = _run_config(settings, default_config, run_id="wf-universe-default")

    explicit_config = _config(universe_mode="card")
    run_explicit = _run_config(settings, explicit_config, run_id="wf-universe-explicit")

    def fingerprint(run: DeskRun) -> tuple[object, ...]:
        return (
            tuple(s.stage_id for s in run.stages),
            tuple(s.state for s in run.stages),
            tuple(s.summary for s in run.stages),
            tuple(s.output_md for s in run.stages),
        )

    assert fingerprint(run_default) == fingerprint(run_explicit)

    from app.workflow.pipeline import _load_card

    card = _load_card("B-momentum", settings=settings)
    assert card is not None
    universe_stage = next(s for s in run_default.stages if s.stage_id == "universe_select")
    assert universe_stage.summary == f"Card universe: {len(card.universe)} symbol(s)."
    for symbol in card.universe:
        assert symbol in universe_stage.output_md


def test_card_mode_universe_select_hands_scan_signals_exactly_card_universe(settings, monkeypatch) -> None:
    """`universe_select`'s output must equal `card.universe` verbatim in card mode, and that is exactly
    what `_scan_signals` must receive -- proven here at the argument level, independent of `stub_desk`'s
    canned firing list."""
    from app.workflow.pipeline import _load_card

    monkeypatch.setattr(pipeline.regime_mod, "classify", lambda **_: _canned_regime())
    seen: list[tuple[str, ...] | None] = []

    def spy_scan(card, *, settings, as_of, universe=None, entry_rule=None):
        seen.append(tuple(universe) if universe is not None else None)
        return []

    monkeypatch.setattr(pipeline, "_scan_signals", spy_scan)

    _run_config(settings, _config(), run_id="wf-card-universe-spy")

    card = _load_card("B-momentum", settings=settings)
    assert card is not None
    assert seen == [tuple(card.universe)]


def test_screen_mode_scans_the_selector_shortlist_not_the_card_universe(settings, monkeypatch) -> None:
    """Screen mode must hand `_scan_signals` whatever `universe.resolve_universe` returned, never
    `card.universe` -- proven with a canned shortlist disjoint from the real B-momentum card's own
    universe."""
    monkeypatch.setattr(pipeline.regime_mod, "classify", lambda **_: _canned_regime())
    monkeypatch.setattr(pipeline.universe_mod, "resolve_universe", lambda **kwargs: ("XLK", "XLU"))
    seen: list[tuple[str, ...] | None] = []

    def spy_scan(card, *, settings, as_of, universe=None, entry_rule=None):
        seen.append(tuple(universe) if universe is not None else None)
        return []

    monkeypatch.setattr(pipeline, "_scan_signals", spy_scan)

    config = _config(universe_mode="screen", selector_id="mom12_1_hysteresis")
    run = _run_config(settings, config, run_id="wf-screen-shortlist")

    assert run.state == "succeeded"
    assert seen == [("XLK", "XLU")]
    universe_stage = next(s for s in run.stages if s.stage_id == "universe_select")
    assert "XLK" in universe_stage.output_md and "XLU" in universe_stage.output_md


def test_screen_mode_entry_rule_still_hard_filters_the_shortlist(settings, monkeypatch) -> None:
    """A shortlist member the entry rule does not fire on must never become a `CandidateObservation`
    row or a staged order -- the entry rule is a hard filter over whichever universe was selected, in
    screen mode exactly as in card mode."""
    monkeypatch.setattr(pipeline.regime_mod, "classify", lambda **_: _canned_regime())
    monkeypatch.setattr(
        pipeline.universe_mod, "resolve_universe", lambda **kwargs: ("XLK", "XLU", "XLE")
    )

    def spy_scan(card, *, settings, as_of, universe=None, entry_rule=None):
        return [s for s in (universe or ()) if s == "XLU"]

    monkeypatch.setattr(pipeline, "_scan_signals", spy_scan)
    monkeypatch.setattr(pipeline, "_launch_ta", lambda symbol, *, ctx, budget_usd: f"ta-{symbol}")
    monkeypatch.setattr(
        pipeline, "_launch_vibe", lambda symbol, question, *, ctx, budget_usd: f"vibe-{symbol}"
    )

    def fake_await(kind, run_id, *, settings, cancel):
        symbol = run_id.split("-", 1)[1]
        if kind == "tradingagents":
            return _canned_ta_run(symbol, rating="Buy")
        return _canned_vibe_run(symbol, verdict="SUPPORT")

    monkeypatch.setattr(pipeline, "_await_child", fake_await)

    config = _config(
        universe_mode="screen", selector_id="mom12_1_hysteresis", arms_enabled=("raw_signal",)
    )
    run = _run_config(settings, config, run_id="wf-screen-hardfilter")

    assert run.state == "succeeded"
    obs_symbols = {o.symbol for o in candidates_mod.read_observations(settings=settings)}
    assert obs_symbols == {"XLU"}

    # A screen run stages into the screen book, never the card book (regression guard for _book_source).
    book = book_mod.load_book(
        settings, "raw_signal", starting_cash=Decimal("100000"), card_id="B-momentum",
        universe_source="screen",
    )
    staged = {o.symbol for o in book.orders}
    assert staged == {"XLU"}
    # The card book of the same arm is left untouched by a screen run.
    assert not book_mod.book_path(settings, "raw_signal", universe_source="card").is_file()


# ---------------------------------------------------------------------------
# Research-spend necessity gates (docs/WORKFLOW-RESEARCH-SPEND-SPEC.md)
#
# `_apply_necessity_gates` is exercised directly for gates 0/3/4/5, each isolated from the others --
# a `_Ctx` is built by hand against the real B-momentum card, exactly the shape `run_workflow` itself
# builds at the seam between `_stage_candidate_scan` and the symbol-stage splice. Gate 2 (the cache)
# and the mandatory end-to-end proof (this project's own standing lesson that a validator tested only
# in isolation has missed real caller behaviour before -- see grounding-gate-false-rejections.md) are
# driven through the real `run_workflow` instead, at the bottom of this section.
# ---------------------------------------------------------------------------


def _write_price_series(settings, symbol: str, *, start: dt.date, closes: list[float]) -> None:
    """`len(closes)` consecutive daily bars for `symbol`, starting `start` -- enough history for
    `app.discovery.clusters.correlation_groups` (needs >=30 return observations) and
    `app.indicators.volatility.atr`'s 14-period warmup alike."""
    import pandas as pd

    from app.db import duck
    from app.market.models import BAR_COLUMNS, Interval

    ts = pd.Series(
        [dt.datetime.combine(start + dt.timedelta(days=i), dt.time.min, tzinfo=dt.UTC) for i in range(len(closes))],
        dtype="datetime64[us, UTC]",
    )
    frame = pd.DataFrame(
        {
            "ts": ts,
            "open": closes,
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "adj_close": closes,
            "volume": [1_000_000] * len(closes),
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


def _build_ctx(
    settings,
    *,
    trade_date: dt.date,
    symbols: list[str],
    arms_enabled: tuple[str, ...] = ("raw_signal", "ta_gated", "vibe_gated", "full_workflow"),
    weekly_budget_usd: Decimal = Decimal("100"),
    switch=None,
    card_id: str = "B-momentum",
):
    """A `_Ctx` in exactly the shape `run_workflow` hands `_apply_necessity_gates` -- card loaded,
    regime set, `all_candidates`/`candidates` populated -- built directly so each gate can be tested
    in isolation from the child-launch machinery."""
    card = pipeline._load_card(card_id, settings=settings)
    assert card is not None
    config = WorkflowConfig(
        agent_card_id=card_id, trade_date=trade_date, budget_usd=Decimal("20.00"),
        per_child_budget_usd=Decimal("4.00"), max_research_symbols=max(len(symbols), 1),
        analysts=None, debate_rounds=None, risk_rounds=None,
        arms_enabled=arms_enabled, model="claude-opus-5", weekly_budget_usd=weekly_budget_usd,
    )
    ctx = pipeline._Ctx(settings=settings, config=config, trade_date=trade_date)
    ctx.card = card
    ctx.regime = _canned_regime()
    ctx.switch = switch
    ctx.all_candidates = [pipeline._Candidate(symbol=s, entry_rank=i + 1) for i, s in enumerate(symbols)]
    ctx.candidates = list(ctx.all_candidates)
    return ctx


class TestGate0WeeklyCircuitBreaker:
    def test_blocks_the_whole_run_when_trailing_spend_meets_the_cap(self, settings) -> None:
        from app.agentdesk.store import RunStore

        now = dt.datetime.now(dt.UTC)
        prior = DeskRun(
            run_id="prior-heavy-spend", kind="workflow", created_at=now - dt.timedelta(days=2),
            budget=AgentBudget(cap_usd=Decimal("100"), spent_usd=Decimal("100")),
        )
        RunStore(settings, "workflow").save(prior)

        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA", "AMD"], weekly_budget_usd=Decimal("100"))
        kept, skipped = pipeline._apply_necessity_gates(ctx)

        assert kept == []
        assert {c.symbol for c in skipped} == {"NVDA", "AMD"}
        assert all(c.skip_reason == "weekly_budget_exhausted" for c in skipped)
        assert all(c.skip_detail for c in skipped)

    def test_a_run_older_than_7_days_does_not_count_toward_the_cap(self, settings) -> None:
        from app.agentdesk.store import RunStore

        now = dt.datetime.now(dt.UTC)
        stale = DeskRun(
            run_id="prior-stale", kind="workflow", created_at=now - dt.timedelta(days=10),
            budget=AgentBudget(cap_usd=Decimal("100"), spent_usd=Decimal("95")),
        )
        RunStore(settings, "workflow").save(stale)

        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA"], weekly_budget_usd=Decimal("100"))
        kept, skipped = pipeline._apply_necessity_gates(ctx)
        assert skipped == []
        assert [c.symbol for c in kept] == ["NVDA"]

    def test_below_the_cap_admits_normally(self, settings) -> None:
        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA"])
        kept, skipped = pipeline._apply_necessity_gates(ctx)
        assert skipped == []
        assert [c.symbol for c in kept] == ["NVDA"]


class TestGate3BookCapacity:
    def test_every_enabled_arm_full_blocks_research(self, settings) -> None:
        from tests.test_workflow_book import _book_with_orders, _filled_order

        held = tuple(
            _filled_order(order_id=f"o{i}", symbol=f"HOLD{i}", side="buy", qty="1", price="100",
                          day=dt.date(2026, 1, 5))
            for i in range(8)  # default_mandate().max_positions
        )
        book = _book_with_orders(held).model_copy(update={"arm": "raw_signal"})
        book_mod.save_book(settings, book)

        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA"], arms_enabled=("raw_signal",))
        kept, skipped = pipeline._apply_necessity_gates(ctx)

        assert kept == []
        (only,) = skipped
        assert only.skip_reason == "no_book_capacity"

    def test_room_available_admits(self, settings) -> None:
        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA"], arms_enabled=("raw_signal",))
        kept, skipped = pipeline._apply_necessity_gates(ctx)
        assert skipped == []
        assert [c.symbol for c in kept] == ["NVDA"]

    def test_a_symbol_already_held_still_counts_as_room(self, settings) -> None:
        """Gate 3 admits a candidate whose own symbol is already held, even when the book is
        otherwise full -- re-researching a name already owned is never blocked by capacity."""
        from tests.test_workflow_book import _book_with_orders, _filled_order

        held = (
            *(
                _filled_order(order_id=f"o{i}", symbol=f"HOLD{i}", side="buy", qty="1", price="100",
                              day=dt.date(2026, 1, 5))
                for i in range(7)
            ),
            _filled_order(order_id="o-nvda", symbol="NVDA", side="buy", qty="1", price="100",
                         day=dt.date(2026, 1, 5)),
        )
        book = _book_with_orders(held).model_copy(update={"arm": "raw_signal"})
        book_mod.save_book(settings, book)

        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA"], arms_enabled=("raw_signal",))
        kept, skipped = pipeline._apply_necessity_gates(ctx)
        assert skipped == []
        assert [c.symbol for c in kept] == ["NVDA"]

    def test_below_min_clip_notional_blocks_research(self, settings, monkeypatch) -> None:
        monkeypatch.setattr(pipeline, "_notional_for", lambda card: Decimal("100"))  # < $500 min clip
        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA"], arms_enabled=("raw_signal",))
        kept, skipped = pipeline._apply_necessity_gates(ctx)
        assert kept == []
        assert skipped[0].skip_reason == "no_book_capacity"


class TestGate4TaxSwitch:
    def test_wash_sale_blocks_every_candidate_this_run(self, settings) -> None:
        from app.workflow import taxcheck as taxcheck_mod

        switch = taxcheck_mod.SwitchVerdict(allowed=False, outcome="blocked_wash_sale", reason="disallowed")
        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA", "AMD"], switch=switch)
        kept, skipped = pipeline._apply_necessity_gates(ctx)
        assert kept == []
        assert all(c.skip_reason == "tax_wash_sale_blocked" for c in skipped)

    def test_churn_limiter_allows_research(self, settings) -> None:
        from app.workflow import taxcheck as taxcheck_mod

        switch = taxcheck_mod.SwitchVerdict(allowed=False, outcome="blocked_churn", reason="too soon")
        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA"], switch=switch)
        kept, skipped = pipeline._apply_necessity_gates(ctx)
        assert skipped == []
        assert [c.symbol for c in kept] == ["NVDA"]

    def test_near_long_term_allows_research(self, settings) -> None:
        """The third `SwitchOutcome` the brief did not name -- must not be silently mishandled by an
        implementation that only branches on wash-sale and churn."""
        from app.workflow import taxcheck as taxcheck_mod

        switch = taxcheck_mod.SwitchVerdict(
            allowed=False, outcome="blocked_near_long_term", reason="premium too high"
        )
        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA"], switch=switch)
        kept, skipped = pipeline._apply_necessity_gates(ctx)
        assert skipped == []
        assert [c.symbol for c in kept] == ["NVDA"]

    def test_allowed_switch_never_blocks(self, settings) -> None:
        from app.workflow import taxcheck as taxcheck_mod

        switch = taxcheck_mod.SwitchVerdict(allowed=True, outcome="allowed", reason="clean")
        ctx = _build_ctx(settings, trade_date=TRADE_DATE, symbols=["NVDA"], switch=switch)
        _kept, skipped = pipeline._apply_necessity_gates(ctx)
        assert skipped == []


class TestGate5CorrelationDuplicate:
    def test_the_lower_ranked_of_two_correlated_candidates_is_refused(self, settings) -> None:
        closes = [100.0 + i for i in range(45)]
        start = dt.date(2026, 5, 1)
        _write_price_series(settings, "AAA", start=start, closes=closes)
        _write_price_series(settings, "BBB", start=start, closes=closes)  # identical series -> rho=1.0
        trade_date = start + dt.timedelta(days=len(closes) - 1)

        ctx = _build_ctx(settings, trade_date=trade_date, symbols=["AAA", "BBB"], arms_enabled=("raw_signal",))
        kept, skipped = pipeline._apply_necessity_gates(ctx)

        assert [c.symbol for c in kept] == ["AAA"]
        (only,) = skipped
        assert only.symbol == "BBB"
        assert only.skip_reason == "correlation_duplicate"

    def test_a_candidate_correlated_with_an_already_held_position_is_refused(self, settings) -> None:
        from tests.test_workflow_book import _book_with_orders, _filled_order

        closes = [100.0 + i for i in range(45)]
        start = dt.date(2026, 5, 1)
        _write_price_series(settings, "AAA", start=start, closes=closes)
        _write_price_series(settings, "CCC", start=start, closes=closes)
        trade_date = start + dt.timedelta(days=len(closes) - 1)

        book = _book_with_orders((
            _filled_order(order_id="o1", symbol="AAA", side="buy", qty="1", price="100", day=dt.date(2026, 1, 5)),
        )).model_copy(update={"arm": "raw_signal"})
        book_mod.save_book(settings, book)

        ctx = _build_ctx(settings, trade_date=trade_date, symbols=["CCC"], arms_enabled=("raw_signal",))
        kept, skipped = pipeline._apply_necessity_gates(ctx)

        assert kept == []
        assert skipped[0].skip_reason == "correlation_duplicate"

    def test_uncorrelated_candidates_are_both_admitted(self, settings) -> None:
        start = dt.date(2026, 5, 1)
        trending = [100.0 + i for i in range(45)]
        oscillating = [100.0 + 5.0 * ((i % 4) - 1.5) for i in range(45)]
        _write_price_series(settings, "AAA", start=start, closes=trending)
        _write_price_series(settings, "DDD", start=start, closes=oscillating)
        trade_date = start + dt.timedelta(days=44)

        ctx = _build_ctx(settings, trade_date=trade_date, symbols=["AAA", "DDD"], arms_enabled=("raw_signal",))
        kept, skipped = pipeline._apply_necessity_gates(ctx)

        assert skipped == []
        assert {c.symbol for c in kept} == {"AAA", "DDD"}


def test_gate6_budget_backstop_regression_pins_stage_wording_and_sets_skip_reason(settings, stub_desk) -> None:
    """Regression: gate 6's stage `error` wording is unchanged from before this feature (an existing
    caller may already parse it), and it now also feeds `skip_reason == "budget_exhausted"` onto the
    observation for the candidate the backstop actually refused.

    A single candidate whose own per-child cap the run-level budget cannot fund at all -- both its
    `research_<SYM>` and `vibe_<SYM>` stages hit the identical backstop, and the second must not
    overwrite what the first already recorded.
    """
    stub_desk.firing = ["NVDA"]
    stub_desk.ratings = {"NVDA": "Buy"}
    stub_desk.verdicts = {"NVDA": "SUPPORT"}

    run = _run(settings, budget_usd=Decimal("2.00"), per_child_budget_usd=Decimal("4.00"))

    research_nvda = next(s for s in run.stages if s.stage_id == "research_NVDA")
    vibe_nvda = next(s for s in run.stages if s.stage_id == "vibe_NVDA")
    assert research_nvda.state == "skipped"
    assert research_nvda.error == "workflow budget exhausted (2.00 < 4.00)"
    assert vibe_nvda.state == "skipped"
    assert vibe_nvda.error == "workflow budget exhausted (2.00 < 4.00)"

    (obs,) = candidates_mod.read_observations(settings=settings)
    assert obs.skip_reason == "budget_exhausted"
    assert obs.skip_detail == research_nvda.error


# ---------------------------------------------------------------------------
# Gate 2 (the cache) and the mandatory end-to-end proof, both through the real `run_workflow`.
# ---------------------------------------------------------------------------


def test_necessity_gate_skip_is_visible_in_the_observation_log_and_does_not_block_raw_signal(
    settings, stub_desk
) -> None:
    """End-to-end: a run whose weekly circuit breaker trips must (a) succeed rather than crash, (b)
    skip the entire fan-out (no research_<SYM>/vibe_<SYM> stages spliced at all), (c) still write every
    fired candidate to the observation log with `skip_reason == "weekly_budget_exhausted"`, and (d)
    still stage a `raw_signal` order for it -- the necessity-gate chain governs *research* spend only,
    never whether the study's null arm trades a symbol whose entry rule genuinely fired.
    """
    from app.agentdesk.store import RunStore

    now = dt.datetime.now(dt.UTC)
    prior = DeskRun(
        run_id="prior-heavy-spend", kind="workflow", created_at=now - dt.timedelta(days=1),
        budget=AgentBudget(cap_usd=Decimal("100"), spent_usd=Decimal("100")),
    )
    RunStore(settings, "workflow").save(prior)

    stub_desk.firing = ["NVDA"]
    run = _run(settings, run_id="wf-weekly-breaker")

    assert run.state == "succeeded"
    assert not any(s.stage_id.startswith("research_") or s.stage_id.startswith("vibe_") for s in run.stages)
    followup = next(s for s in run.stages if s.stage_id == "followup_questions")
    assert followup.state == "skipped"
    assert "necessity gates" in followup.error

    (obs,) = candidates_mod.read_observations(settings=settings)
    assert obs.symbol == "NVDA"
    assert obs.skip_reason == "weekly_budget_exhausted"
    assert obs.skip_detail
    assert all(g.passed is False for g in obs.gates)

    book = book_mod.load_book(settings, "raw_signal", starting_cash=Decimal("100000"), card_id="B-momentum")
    assert {o.symbol for o in book.orders} == {"NVDA"}


def test_gate2_cache_hit_avoids_a_second_fresh_research_cycle_and_still_stages_an_order(
    settings, stub_desk
) -> None:
    """The mandatory end-to-end proof (per this project's standing lesson that an isolated validator
    test has missed real caller behaviour before): two consecutive `run_workflow` calls on the same
    symbol/card, second one inside the cache's TTL with the price/regime unchanged.

    Run 1: no cache exists, both children launch fresh, a cache entry is written for each. Run 2:
    zero new child runs launch, the candidate's `GateDecision.verdict_source == "cached"` on both
    `ta_gated`/`vibe_gated` (and therefore `"cached"` on `full_workflow` too), and -- the part an
    isolated gate-function test cannot prove -- `_stage_orders` still stages a real order from the
    cached verdict.
    """
    start = dt.date(2026, 6, 1)
    closes = [100.0 + 0.1 * i for i in range(30)]
    _write_price_series(settings, "NVDA", start=start, closes=closes)
    run1_date = start + dt.timedelta(days=len(closes) - 1)
    run2_date = run1_date + dt.timedelta(days=5)  # inside CACHE_TTL_DAYS=21, price/regime unchanged

    stub_desk.firing = ["NVDA"]
    stub_desk.ratings = {"NVDA": "Buy"}
    stub_desk.verdicts = {"NVDA": "SUPPORT"}

    run1 = _run_config(settings, _config(trade_date=run1_date), run_id="wf-cache-run-1")
    assert run1.state == "succeeded"
    research1 = next(s for s in run1.stages if s.stage_id == "research_NVDA")
    vibe1 = next(s for s in run1.stages if s.stage_id == "vibe_NVDA")
    assert research1.state == "succeeded" and research1.cost_usd > 0
    assert vibe1.state == "succeeded" and vibe1.cost_usd > 0
    assert run1.config["child_runs"].get("research_NVDA") == "ta-NVDA"
    assert run1.config["child_runs"].get("vibe_NVDA") == "vibe-NVDA"

    from app.workflow import research_cache as research_cache_mod

    ta_entry = research_cache_mod.latest_entry("NVDA", "B-momentum", "tradingagents", settings=settings)
    vibe_entry = research_cache_mod.latest_entry("NVDA", "B-momentum", "vibedesk", settings=settings)
    assert ta_entry is not None and ta_entry.ta_rating == "Buy"
    assert vibe_entry is not None and vibe_entry.vibe_verdict == "SUPPORT"

    run2 = _run_config(settings, _config(trade_date=run2_date), run_id="wf-cache-run-2")
    assert run2.state == "succeeded"

    research2 = next(s for s in run2.stages if s.stage_id == "research_NVDA")
    vibe2 = next(s for s in run2.stages if s.stage_id == "vibe_NVDA")
    assert research2.cost_usd == Decimal("0")
    assert vibe2.cost_usd == Decimal("0")
    assert "Cache hit" in research2.summary
    assert "Cache hit" in vibe2.summary
    # Zero new child runs launched -- run2's own persisted child-run map never gained an entry.
    assert "research_NVDA" not in run2.config.get("child_runs", {})
    assert "vibe_NVDA" not in run2.config.get("child_runs", {})
    assert run2.budget.spent_usd == Decimal("0")

    obs_by_date = {o.decision_date: o for o in candidates_mod.read_observations(settings=settings, symbol="NVDA")}
    run2_obs = obs_by_date[run2_date]
    sources = {g.gate: g.verdict_source for g in run2_obs.gates}
    assert sources == {"ta_gated": "cached", "vibe_gated": "cached", "full_workflow": "cached"}
    assert run2_obs.skip_reason is None
    assert run2_obs.avoided_cost_usd == ta_entry.research_cost_usd + vibe_entry.research_cost_usd

    # The part an isolated cache-function test cannot prove: a cache hit still feeds a real staged
    # order downstream, on both runs.
    book = book_mod.load_book(settings, "full_workflow", starting_cash=Decimal("100000"), card_id="B-momentum")
    staged_dates = {o.decision_date for o in book.orders if o.symbol == "NVDA"}
    assert run1_date in staged_dates
    assert run2_date in staged_dates
