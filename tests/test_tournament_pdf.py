"""Tests for `app.tournament.report_pdf.render_agent_report`.

Two other workers are building `app.tournament.runner`, `app.tournament.scoring` and
`app.tournament.roster` concurrently, so every `AgentResult`/`StrategyCard`/`RealisedTrade` here is
built by hand from `app.tournament.models` rather than produced by a run -- this file imports nothing
from those three modules.

**Why some assertions read `_results_rows`/`_reward_risk_rows` directly instead of only parsing the
rendered PDF.** `pypdf` text extraction is reliable for verbatim strings (the entry/exit rules, the
limitations prose) but a poor tool for asserting that one specific table cell holds an em dash and
not the literal digit ``"0"`` -- extracted text loses the table's row/column structure, so a
substring check could pass by accident (the dash for one metric, the digit from an unrelated date, on
adjacent lines). The row-building functions in `report_pdf` are pure (`AgentResult` in, `list[str]`
rows out) specifically so a test can assert on the exact cell content before it ever becomes a
`reportlab` flowable. Where verbatim text in the rendered document is what actually matters --
whether the entry rule survived unmangled, whether the limitations paragraph is present -- this file
does render the PDF and read it back with `pypdf`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.tournament.models import (
    DESIGN_THROUGH,
    TRADE_END,
    TRADE_START,
    AgentResult,
    Discipline,
    RealisedTrade,
    StrategyCard,
    TournamentResult,
)
from app.tournament.report_pdf import (
    _DASH,
    _benchmark_rows,
    _brackets_rows,
    _results_rows,
    _reward_risk_rows,
    render_agent_report,
)

# ---------------------------------------------------------------------------
# Builders. Every AgentResult in this file is constructed from these, never from a tournament run.
# ---------------------------------------------------------------------------


def make_card(**overrides: object) -> StrategyCard:
    fields: dict[str, object] = dict(
        agent_id="alpha-trend",
        display_name="Alpha Analyst",
        discipline=Discipline.TREND,
        thesis="Momentum persists for several weeks after a confirmed 50/200 golden cross.",
        universe=("AAPL", "MSFT"),
        entry="close > sma_50 and sma_50 > sma_200 and volume > avg_volume_20",
        exit="close < sma_20 or rsi_14 > 80",
        stop_loss_pct=Decimal("0.08"),
        take_profit_pct=Decimal("0.20"),
        max_hold_days=60,
        max_positions=4,
        position_pct=Decimal("0.20"),
        designed_through=DESIGN_THROUGH,
    )
    fields.update(overrides)
    return StrategyCard(**fields)  # type: ignore[arg-type]


def make_trade(**overrides: object) -> RealisedTrade:
    fields: dict[str, object] = dict(
        symbol="AAPL",
        entry_date=TRADE_START,
        entry_price=Decimal("150.00"),
        exit_date=TRADE_START + dt.timedelta(days=5),
        exit_price=Decimal("162.00"),
        quantity=Decimal("10"),
        exit_reason="rule",
        pnl=Decimal("120.00"),
        return_pct=Decimal("0.08"),
        bars_held=5,
    )
    fields.update(overrides)
    return RealisedTrade(**fields)  # type: ignore[arg-type]


def make_result(**overrides: object) -> AgentResult:
    fields: dict[str, object] = dict(
        card=make_card(),
        sessions=127,
        starting_equity=Decimal("100000"),
        ending_equity=Decimal("112000"),
        total_return=Decimal("0.12"),
        max_drawdown=Decimal("0.05"),
        sharpe=1.2,
        sortino=1.5,
        volatility=0.18,
        exposure=0.6,
        win_rate=0.55,
        profit_factor=Decimal("1.8"),
        realised_reward_risk=Decimal("1.5"),
        trades=(make_trade(),),
        rejections=(),
        benchmark_return=Decimal("0.09"),
        p_value=0.03,
        q_value=0.06,
    )
    fields.update(overrides)
    return AgentResult(**fields)  # type: ignore[arg-type]


def make_tournament(agents: tuple[AgentResult, ...]) -> TournamentResult:
    return TournamentResult(
        generated_at=dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.UTC),
        trade_start=TRADE_START,
        trade_end=TRADE_END,
        sessions=127,
        agents=agents,
    )


def extract_text(path: Path) -> str:
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pdf_is_written_nonempty_and_starts_with_pdf_magic(tmp_path: Path) -> None:
    result = make_result()
    out_path = render_agent_report(result, out_dir=tmp_path)

    assert out_path == tmp_path / "alpha-trend.pdf"
    assert out_path.exists()
    data = out_path.read_bytes()
    assert len(data) > 0
    assert data.startswith(b"%PDF")


def test_none_metrics_render_as_dash_never_as_the_digit_zero() -> None:
    """A None metric must render as an em dash. It must not render as ``0`` -- the repo treats an
    unmeasured quantity and a measured zero as different claims, and this module must not blur them.
    """
    result = make_result(
        sharpe=None,
        sortino=None,
        volatility=None,
        exposure=None,
        win_rate=None,
        profit_factor=None,
        realised_reward_risk=None,
        benchmark_return=None,
    )
    rows = dict(_results_rows(result))
    assert rows["Sharpe"] == _DASH
    assert rows["Sortino"] == _DASH
    assert rows["Volatility"] == _DASH
    assert rows["Exposure"] == _DASH
    assert rows["Win rate"] == _DASH
    assert rows["Profit factor"] == _DASH
    for label, value in rows.items():
        if label == "Trade count":
            continue  # a real, measured count -- "0" would be correct here, just not in this fixture
        assert value != "0"
        assert not value.startswith("0.00")

    rr_rows = dict(_reward_risk_rows(result))
    assert rr_rows["Realised reward:risk"] == _DASH

    bench_rows = dict(_benchmark_rows(result))
    assert bench_rows["Buy-and-hold benchmark return, same sessions"] == _DASH
    # No excess-over-benchmark row is added when benchmark_return is None (nothing to subtract).
    assert "Excess over benchmark" not in bench_rows


def test_a_real_zero_metric_is_not_hidden_behind_the_dash() -> None:
    """The flip side of the previous test: a metric that was computed and happened to be exactly
    zero must render as ``0``, not as the dash reserved for ``None``."""
    result = make_result(win_rate=0.0, exposure=0.0)
    rows = dict(_results_rows(result))
    assert rows["Win rate"] == "0.00%"
    assert rows["Exposure"] == "0.00%"
    assert rows["Win rate"] != _DASH
    assert rows["Exposure"] != _DASH


def test_brackets_rows_render_none_brackets_as_dash() -> None:
    result = make_result(
        card=make_card(stop_loss_pct=None, take_profit_pct=None, max_hold_days=None)
    )
    rows = dict(_brackets_rows(result))
    assert rows["Stop loss"] == _DASH
    assert rows["Take profit"] == _DASH
    assert rows["Max hold days"] == _DASH


def test_entry_and_exit_expressions_appear_verbatim(tmp_path: Path) -> None:
    entry = "close > sma_50 and sma_50 > sma_200 and volume > avg_volume_20"
    exit_ = "close < sma_20 or rsi_14 > 80"
    result = make_result(card=make_card(entry=entry, exit=exit_))
    out_path = render_agent_report(result, out_dir=tmp_path)

    text = extract_text(out_path)
    assert entry in text
    assert exit_ in text


def test_thesis_appears_verbatim(tmp_path: Path) -> None:
    thesis = "Momentum persists for several weeks after a confirmed 50/200 golden cross."
    result = make_result(card=make_card(thesis=thesis))
    out_path = render_agent_report(result, out_dir=tmp_path)

    text = extract_text(out_path)
    assert thesis in text


def test_limitations_block_is_present_and_specific(tmp_path: Path) -> None:
    result = make_result()
    out_path = render_agent_report(result, out_dir=tmp_path)
    text = extract_text(out_path)

    assert "Limitations" in text
    assert "127 sessions" in text
    assert "one market regime" in text
    assert "selection effect" in text
    assert "already trades these names" in text
    assert "simulated" in text.lower()
    assert "adverse slippage" in text
    assert "not investment advice" in text


def test_window_states_design_and_trade_dates_and_out_of_sample_claim(tmp_path: Path) -> None:
    result = make_result()
    out_path = render_agent_report(result, out_dir=tmp_path)
    text = extract_text(out_path)

    assert DESIGN_THROUGH.isoformat() in text
    assert TRADE_START.isoformat() in text
    assert TRADE_END.isoformat() in text
    assert "127 sessions" in text
    assert "out-of-sample" in text


def test_zero_trades_renders_without_raising(tmp_path: Path) -> None:
    result = make_result(trades=(), profit_factor=None, realised_reward_risk=None, p_value=None)
    out_path = render_agent_report(result, out_dir=tmp_path)

    assert out_path.read_bytes().startswith(b"%PDF")
    text = extract_text(out_path)
    assert "No trades closed" in text
    rows = dict(_results_rows(result))
    assert rows["Trade count"] == "0"  # measured, not unmeasured -- must not be a dash


def test_long_trade_list_does_not_blow_up_and_states_the_true_count(tmp_path: Path) -> None:
    trades = tuple(make_trade(symbol=f"SYM{i}", quantity=Decimal(str(i + 1))) for i in range(500))
    result = make_result(trades=trades)
    out_path = render_agent_report(result, out_dir=tmp_path)

    assert out_path.read_bytes().startswith(b"%PDF")
    text = extract_text(out_path)
    assert "Showing the first 50 of 500 trades." in text


def test_rejections_are_listed_when_present(tmp_path: Path) -> None:
    result = make_result(
        rejections=("insufficient cash for AAPL buy on 2026-03-02", "position cap reached for MSFT")
    )
    out_path = render_agent_report(result, out_dir=tmp_path)
    text = extract_text(out_path)

    assert "insufficient cash for AAPL buy on 2026-03-02" in text
    assert "position cap reached for MSFT" in text


def test_no_rejections_says_so_explicitly(tmp_path: Path) -> None:
    result = make_result(rejections=())
    out_path = render_agent_report(result, out_dir=tmp_path)
    text = extract_text(out_path)

    assert "None. Every order this strategy sent was accepted." in text


def test_q_value_without_tournament_says_no_correction_was_applied(tmp_path: Path) -> None:
    result = make_result(p_value=0.02, q_value=None)
    out_path = render_agent_report(result, out_dir=tmp_path, tournament=None)
    text = extract_text(out_path)

    assert "not available" in text
    assert "no correction" in text.lower()


def test_q_value_with_tournament_states_the_strategy_count(tmp_path: Path) -> None:
    other_agents = tuple(make_result(card=make_card(agent_id=f"agent-{i}")) for i in range(9))
    this_result = make_result(p_value=0.01, q_value=0.04)
    tournament = make_tournament((this_result, *other_agents))

    out_path = render_agent_report(this_result, out_dir=tmp_path, tournament=tournament)
    text = extract_text(out_path)

    assert "across the 10 strategies" in text


def test_planned_versus_realised_reward_risk_side_by_side() -> None:
    card = make_card(stop_loss_pct=Decimal("0.10"), take_profit_pct=Decimal("0.25"))
    result = make_result(card=card, realised_reward_risk=Decimal("1.75"))

    rows = dict(_reward_risk_rows(result))
    assert rows["Planned reward:risk (card)"] == "2.50"
    assert rows["Realised reward:risk"] == "1.75"


def test_benchmark_comparison_includes_excess_when_both_present() -> None:
    result = make_result(total_return=Decimal("0.15"), benchmark_return=Decimal("0.09"))
    rows = dict(_benchmark_rows(result))
    assert rows["Strategy total return"] == "15.00%"
    assert rows["Buy-and-hold benchmark return, same sessions"] == "9.00%"
    assert rows["Excess over benchmark"] == "6.00%"


def test_money_fields_keep_decimal_precision_in_the_trade_table(tmp_path: Path) -> None:
    """Regression guard for the no-float rule: an entry price with three decimal places must survive
    into the rendered PDF exactly, which would not happen if it were ever coerced through float."""
    trade = make_trade(entry_price=Decimal("123.451"), exit_price=Decimal("130.999"))
    result = make_result(trades=(trade,))
    out_path = render_agent_report(result, out_dir=tmp_path)
    text = extract_text(out_path)

    assert "$123.45" in text
    assert "$131.00" in text


def test_out_dir_is_created_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "reports" / "tournament-2026-08-18"
    result = make_result()
    out_path = render_agent_report(result, out_dir=nested)
    assert out_path.exists()


def test_filename_comes_from_agent_id(tmp_path: Path) -> None:
    result = make_result(card=make_card(agent_id="my-unique-slug"))
    out_path = render_agent_report(result, out_dir=tmp_path)
    assert out_path.name == "my-unique-slug.pdf"


@pytest.mark.parametrize("universe_size", [1, 12])
def test_universe_boundary_sizes_render(tmp_path: Path, universe_size: int) -> None:
    universe = tuple(f"SYM{i}" for i in range(universe_size))
    result = make_result(card=make_card(agent_id=f"boundary-{universe_size}", universe=universe))
    out_path = render_agent_report(result, out_dir=tmp_path)
    text = extract_text(out_path)
    for symbol in universe:
        assert symbol in text


# ---------------------------------------------------------------------------
# Window resolution -- explicit window, tournament's window, and the fallback constants
# ---------------------------------------------------------------------------


def _window_sentence(start: dt.date, end: dt.date) -> str:
    """The window-section phrase that pins down which window was actually printed. Checking this
    exact phrase rather than bare date substrings matters here: `make_trade`'s default
    `entry_date`/`exit_date` fall on `TRADE_START`, so `TRADE_START.isoformat()` legitimately
    appears in the trades table regardless of which window the "Trading window" section names."""
    return f"Traded {start.isoformat()} through {end.isoformat()}"


def test_explicit_window_argument_renders_and_the_constants_do_not(tmp_path: Path) -> None:
    """A caller running a different window than the module's default (the whole point of the
    `window` parameter) must see *that* window in the PDF, not the fixed `TRADE_START`/`TRADE_END`
    the report used to always print regardless of what actually ran."""
    custom_start = dt.date(2023, 8, 21)
    custom_end = dt.date(2025, 1, 15)
    result = make_result()

    out_path = render_agent_report(result, out_dir=tmp_path, window=(custom_start, custom_end))
    text = extract_text(out_path)

    assert _window_sentence(custom_start, custom_end) in text
    assert _window_sentence(TRADE_START, TRADE_END) not in text


def test_tournament_window_is_used_when_it_differs_from_the_constants(tmp_path: Path) -> None:
    """With no explicit `window`, a supplied `tournament` is the next source of truth -- its own
    `trade_start`/`trade_end` is the window that actually produced `result`, which can legitimately
    differ from the module constants."""
    custom_start = dt.date(2023, 8, 21)
    custom_end = dt.date(2025, 1, 15)
    result = make_result()
    tournament = TournamentResult(
        generated_at=dt.datetime(2026, 8, 18, 12, 0, tzinfo=dt.UTC),
        trade_start=custom_start,
        trade_end=custom_end,
        sessions=127,
        agents=(result,),
    )

    out_path = render_agent_report(result, out_dir=tmp_path, tournament=tournament)
    text = extract_text(out_path)

    assert _window_sentence(custom_start, custom_end) in text
    assert _window_sentence(TRADE_START, TRADE_END) not in text


def test_window_starting_before_design_cutoff_renders_in_sample_warning(tmp_path: Path) -> None:
    result = make_result()
    window = (dt.date(2023, 8, 21), TRADE_END)

    out_path = render_agent_report(result, out_dir=tmp_path, window=window)
    text = extract_text(out_path)

    # Split across two checks rather than one phrase: `pypdf` extraction inserts a line-wrap
    # newline where the rendered paragraph wraps, and that wrap point is a layout detail, not part
    # of the sentence under test.
    assert "in-sample" in text
    assert "does not measure" in text
    assert "out-of-sample performance" in text


def test_window_starting_on_design_cutoff_also_renders_in_sample_warning(tmp_path: Path) -> None:
    """`window[0] <= DESIGN_THROUGH` -- the boundary day itself counts as overlap, not just
    windows that start strictly before it."""
    result = make_result()
    window = (DESIGN_THROUGH, TRADE_END)

    out_path = render_agent_report(result, out_dir=tmp_path, window=window)
    text = extract_text(out_path)

    assert "in-sample" in text


def test_window_starting_after_design_cutoff_does_not_render_in_sample_warning(
    tmp_path: Path,
) -> None:
    result = make_result()
    window = (TRADE_START, TRADE_END)
    assert window[0] > DESIGN_THROUGH  # sanity: this is the genuinely out-of-sample case

    out_path = render_agent_report(result, out_dir=tmp_path, window=window)
    text = extract_text(out_path)

    assert "in-sample" not in text
    assert "out-of-sample" in text


def test_overlapping_window_does_not_also_claim_to_be_out_of_sample(tmp_path: Path) -> None:
    """The two window sentences are mutually exclusive, not additive.

    The first three-year run printed both -- "which is what makes this an out-of-sample result"
    immediately followed by "the analyst designed this strategy with sight of part of the data it
    just traded" -- in the same paragraph. A reader cannot act on a report that contradicts itself
    inside four lines, so the out-of-sample claim is now conditional on the window rather than
    asserted unconditionally.
    """
    result = make_result()
    window = (dt.date(2023, 8, 21), TRADE_END)
    assert window[0] < DESIGN_THROUGH

    out_path = render_agent_report(result, out_dir=tmp_path, window=window)
    text = extract_text(out_path)

    assert "in-sample" in text
    assert "makes this an out-of-sample result" not in text
