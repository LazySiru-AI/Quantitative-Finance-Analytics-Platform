"""Run `app.workflow.regime_backtest` over a real historical window and write
`docs/reports/regime-backtest.md`.

    .venv/Scripts/python.exe tools/regime_backtest_report.py
    .venv/Scripts/python.exe tools/regime_backtest_report.py --start 2023-01-01 --end 2026-06-30
    .venv/Scripts/python.exe tools/regime_backtest_report.py --no-macro

**What this script is, and is not.** It is the one caller in this codebase that actually executes
`app.workflow.regime_backtest.regime_history` and `.score_regime_map` over real, stored market data
and writes their findings to a Markdown report -- see that module's own docstring for what the
classifier replay is and is not able to backtest, and for the geometric-decomposition approximation
`score_regime_map` uses to build a daily return series out of `app.tournament.runner.run_card`'s trade
list. It is **not** a change to `docs/WORKFLOW-STUDY-PLAN.md`'s pre-registered decision rule, and the
report this script writes says so in its own closing section -- this is informational research into
whether `regime_map.json`'s card assignments are supported by history, run once, outside that
pre-registration, and it settles nothing about the pre-registered study on its own.

**The one network call this script makes, and why it is still zero *model* cost.** `classify`'s macro
signal (the 10Y-2Y spread) has a genuine published daily history on FRED (`T10Y2Y`), and
`app.workflow.regime_backtest.regime_history` is built to accept it from the caller rather than
fetching it itself -- see that module's docstring. This script is that caller: a single, one-time,
keyless (or keyed, if `Settings.fred_key` is configured) CSV fetch of `T10Y2Y`'s whole history via
`app.market.providers.fred.FredProvider`, cached on disk like every other provider call in this
codebase. If that fetch fails for any reason (no network in this environment, FRED unreachable, a
malformed response) this script does not fail the whole report -- it proceeds with the macro signal
left unavailable for the whole window, exactly as `classify` already handles a caller who never
supplies one, and says so plainly in the written report rather than silently downgrading the numbers.
Nothing here calls an LLM; the classifier is deterministic arithmetic and the card engine is a rule
DSL, so this script's total model spend is $0 regardless of window size.

**Sequential, on purpose.** `app.workflow.regime_backtest.score_regime_map` already runs its four
`run_card` calls one at a time (see that function's own docstring); this script does not add any
further concurrency on top -- one report generation, start to finish, in one process.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import httpx

from app.config import REPO_ROOT, Settings, get_settings
from app.market import store as market_store
from app.market.cache import CachingTransport
from app.market.models import Interval
from app.market.providers.fred import FredProvider
from app.workflow.regime import RegimeLabel
from app.workflow.regime_backtest import (
    RegimeHistoryResult,
    RegimeMapScoreEntry,
    RegimeMapScoreResult,
    regime_history,
    score_regime_map,
)

__all__ = ["main", "parse_args"]

#: Default window length -- "moderate" per this shard's own host-constraint note (backtests are
#: memory-heavy on a 16GB machine; keep it to 2-3 years). Three years gives the classifier's history a
#: real chance at seeing more than one macro regime without approaching the point where four
#: sequential `run_card` calls over a wide, many-symbol universe get expensive.
_DEFAULT_WINDOW_YEARS = 3

_REPORT_PATH = REPO_ROOT / "docs" / "reports" / "regime-backtest.md"

_LABEL_ORDER: tuple[RegimeLabel, ...] = (
    "risk_on_trend",
    "risk_off",
    "choppy_neutral",
    "high_vol_stress",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--start", type=dt.date.fromisoformat, default=None, help="window start (default: 3y before --end)"
    )
    parser.add_argument(
        "--end", type=dt.date.fromisoformat, default=None, help="window end (default: latest stored SPY bar)"
    )
    parser.add_argument(
        "--no-macro",
        action="store_true",
        help="skip the FRED T10Y2Y fetch entirely; the macro signal is left unavailable",
    )
    parser.add_argument(
        "--output", type=Path, default=_REPORT_PATH, help=f"where to write the report (default: {_REPORT_PATH})"
    )
    return parser.parse_args(argv)


def _default_window(*, settings: Settings) -> tuple[dt.date, dt.date]:
    """`(start, end)` -- `end` is the latest stored SPY session, `start` is `_DEFAULT_WINDOW_YEARS`
    before it. Reading the store's own latest date, rather than `dt.date.today()`, is what keeps this
    script from asking for a window the store cannot actually answer for on whatever day it is run."""
    frame = market_store.read_frame("SPY", Interval.DAY, settings=settings)
    if frame.empty:
        raise SystemExit(
            "no stored SPY bars at all -- this script needs the real, synced bar store "
            "(data/store/bars), which is gitignored and not present on a fresh clone"
        )
    end = frame["ts"].max().date()
    start = end - dt.timedelta(days=365 * _DEFAULT_WINDOW_YEARS)
    return start, end


#: How long the cached T10Y2Y CSV/JSON response is trusted before a re-fetch -- generous, since this
#: is a slow-moving daily series and this script is not meant to be run more than a few times a day.
_MACRO_CACHE_TTL = 86400.0


def _fetch_macro_history(*, settings: Settings) -> tuple[dict[dt.date, float], str | None]:
    """`({date: 2s10s spread pct}, warning)` -- FRED's `T10Y2Y` full published history, fetched once
    through the same on-disk `CachingTransport` every other provider call in this codebase shares
    (`app.market.macro._cached_client` builds an identical wrapper for its own FRED/CNN calls).
    `warning` is `None` on success; on any failure it is a human-readable reason and the mapping is
    empty, which `regime_history` already treats as "macro signal unavailable for this call" (it is
    optional and defaults to `None` for exactly this case) -- see the module docstring's "one network
    call" section for why a failure here degrades gracefully instead of aborting the report.
    """
    try:
        transport = CachingTransport(
            httpx.HTTPTransport(), settings.cache_dir / "http", ttl=_MACRO_CACHE_TTL
        )
        client = httpx.Client(transport=transport, timeout=30.0)
        try:
            provider = FredProvider(client, api_key=settings.fred_key)
            series = provider.fetch_series("T10Y2Y")
        finally:
            client.close()
    except Exception as exc:
        # Reported in the written report, not swallowed -- see this function's docstring.
        return {}, f"{type(exc).__name__}: {exc}"

    by_date = {point.date: point.value for point in series.points if point.value is not None}
    if not by_date:
        warning = "; ".join(w.message for w in series.warnings) or "FRED returned no observations"
        return {}, warning
    return by_date, None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _pct(value: Decimal | float | None, *, places: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.{places}f}%"


def _num(value: Decimal | float | None, *, places: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{places}f}"


def _frequency_table(history: RegimeHistoryResult) -> str:
    total = len(history.days)
    lines = ["| Regime | Sessions | Share |", "|---|---:|---:|"]
    for label in _LABEL_ORDER:
        count = history.frequencies.get(label, 0)
        share = f"{count / total * 100:.1f}%" if total else "n/a"
        lines.append(f"| `{label}` | {count} | {share} |")
    lines.append(f"| **Total** | **{total}** | **100.0%** |")
    return "\n".join(lines)


def _transition_matrix(history: RegimeHistoryResult) -> str:
    header = "| from \\ to | " + " | ".join(f"`{b}`" for b in _LABEL_ORDER) + " |"
    sep = "|---|" + "---:|" * len(_LABEL_ORDER)
    lines = [header, sep]
    for a in _LABEL_ORDER:
        row = history.transitions.get(a, {})
        cells = " | ".join(str(row.get(b, 0)) for b in _LABEL_ORDER)
        lines.append(f"| `{a}` | {cells} |")
    return "\n".join(lines)


def _entry_section(entry: RegimeMapScoreEntry) -> str:
    lines = [f"### `{entry.label}` — primary card `{entry.agent_id}`", ""]
    lines.append(
        f"Full ordered map for this label: {', '.join(f'`{a}`' for a in entry.mapped_agent_ids)} "
        "(only the primary, index-0 card above was run -- see the module docstring for why)."
    )
    lines.append("")

    if entry.error is not None:
        lines.append(f"**Could not be scored.** `{entry.error}`")
        return "\n".join(lines)

    lines.append(
        f"Whole-window: total_return={_pct(entry.whole_window_total_return)}, "
        f"sharpe={_num(entry.whole_window_sharpe)}, trades={entry.whole_window_trades}."
    )
    lines.append("")

    split = entry.split
    assert split is not None  # error is None, so score_regime_map always populates split
    lines.append(
        "| | in-regime | out-of-regime |\n"
        "|---|---:|---:|\n"
        f"| sessions | {split.in_regime_sessions} | {split.out_of_regime_sessions} |\n"
        f"| trade entries | {split.in_regime_trade_entries} | {split.out_of_regime_trade_entries} |\n"
        f"| total return | {_pct(split.in_regime.total_return)} | {_pct(split.out_of_regime.total_return)} |\n"
        f"| CAGR | {_pct(split.in_regime.cagr)} | {_pct(split.out_of_regime.cagr)} |\n"
        f"| volatility (ann.) | {_pct(split.in_regime.volatility)} | {_pct(split.out_of_regime.volatility)} |\n"
        f"| Sharpe | {_num(split.in_regime.sharpe)} | {_num(split.out_of_regime.sharpe)} |\n"
        f"| max drawdown | {_pct(split.in_regime.max_drawdown)} | {_pct(split.out_of_regime.max_drawdown)} |\n"
        f"| exposure | {_pct(split.in_regime.exposure)} | {_pct(split.out_of_regime.exposure)} |"
    )
    lines.append("")
    lines.append(
        "`CAGR`/volatility/Sharpe read `n/a` under a year of in-subset sessions -- "
        "`app.backtest.metrics.compute` refuses to annualise a sample that thin (see that module's own "
        "docstring); a blank cell here is the honest absence of a claim, not a missing number."
    )
    return "\n".join(lines)


def _conclusion(history: RegimeHistoryResult, score: RegimeMapScoreResult) -> str:
    lines = [
        "Every comparison above is `total_return` on the *same card, same window*, split by which "
        "sessions the classifier called this label versus every other label -- the direct test of "
        "`regime_map.json`'s premise that each label's assigned card suits sessions carrying that "
        "label specifically. A card whose in-regime and out-of-regime rows look alike is evidence the "
        "assignment carries no information over this window; a card that diverges materially, in the "
        "direction its own thesis predicts, is evidence the mapping is doing something real.",
        "",
    ]
    scored = [e for e in score.entries if e.split is not None]
    failed = [e for e in score.entries if e.error is not None]
    if failed:
        lines.append(
            f"{len(failed)} of {len(score.entries)} label(s) could not be scored at all: "
            + "; ".join(f"`{e.label}` ({e.error})" for e in failed)
        )
        lines.append("")
    if not scored:
        lines.append(
            "**No label produced a usable split.** This section cannot draw a conclusion about the "
            "map's premise from this run; see the errors above."
        )
    else:
        for entry in scored:
            split = entry.split
            assert split is not None
            in_ret = split.in_regime.total_return
            out_ret = split.out_of_regime.total_return
            if in_ret is None or out_ret is None:
                lines.append(f"- `{entry.label}` (`{entry.agent_id}`): total_return unavailable for one side.")
                continue
            gap = in_ret - out_ret
            comparison = (
                "higher than" if gap > 0 else ("lower than" if gap < 0 else "identical to")
            )
            lines.append(
                f"- `{entry.label}` (`{entry.agent_id}`): in-regime total_return was "
                f"{comparison} out-of-regime ({_pct(in_ret)} vs "
                f"{_pct(out_ret)}, gap {_pct(gap)}), over {split.in_regime_sessions} in-regime and "
                f"{split.out_of_regime_sessions} out-of-regime session(s)."
            )
    lines.append("")
    lines.append(
        "**This finding does not alter `docs/WORKFLOW-STUDY-PLAN.md`'s pre-registered decision "
        "rule.** That study governs whether the Agent Workflow desk's model-gated arms beat "
        "`raw_signal`; this report is a separate, informational check of whether the *deterministic* "
        "regime classifier's static card map is supported by history, run once, outside that "
        "pre-registration. A null result here (no material in/out difference) is a real and expected "
        "finding, consistent with this programme's base rate that most measured edges do not survive "
        "-- it is not evidence the classifier or the map is broken, and neither result edits "
        "`app/workflow/regime.py`'s thresholds or `regime_map.json`'s assignments; that stays a "
        "human decision, made out of band from this script."
    )
    return "\n".join(lines)


def render_report(
    history: RegimeHistoryResult,
    score: RegimeMapScoreResult,
    *,
    macro_warning: str | None,
    generated_at: dt.datetime,
) -> str:
    parts = [
        "# Regime backtest — deterministic classifier and static card map",
        "",
        f"Generated {generated_at.isoformat()} by `tools/regime_backtest_report.py`, over "
        f"`{history.start.isoformat()}` to `{history.end.isoformat()}` "
        f"({len(history.days)} trading sessions). Zero model-call cost: `app.workflow.regime.classify` "
        "is deterministic arithmetic and `app.tournament.runner.run_card` evaluates a rule DSL -- "
        "no LLM was called to produce any number in this report.",
        "",
        "**This is informational research, not a pre-registered study, and it does not alter "
        "`docs/WORKFLOW-STUDY-PLAN.md`'s decision rule** -- see the Conclusion section.",
        "",
        "## Data availability",
        "",
        (
            f"2s10s spread (FRED `T10Y2Y`): available, {sum(1 for _ in history.days)} sessions "
            "matched against a fetched history."
            if macro_warning is None
            else f"2s10s spread (FRED `T10Y2Y`): **unavailable** -- {macro_warning}. Every "
            "`RegimeCall` below is missing the macro signal; `classify`'s own confidence arithmetic "
            "drops it from the denominator rather than fabricating a reading."
        ),
        (
            "Composite Fear & Greed: **unavailable for the whole window, by construction.** CNN's "
            "endpoint has no as-of capability (see `app.market.macro`'s own module docstring), so "
            "`app.workflow.regime_backtest.regime_history` never backtests this signal at all -- see "
            "that module's docstring, \"What is, and is not, backtestable\"."
        ),
        "",
        "## Regime frequency",
        "",
        _frequency_table(history),
        "",
        "## Regime transition matrix",
        "",
        "Row = the label a session carried; column = the label the *next* session (in trading-session "
        "order, not calendar order) carried.",
        "",
        _transition_matrix(history),
        "",
        "## Per-card in-regime vs out-of-regime comparison",
        "",
        (
            "Each label's primary mapped card (`regime_map.json`'s index-0 entry) is run once over "
            "the full window via `app.tournament.runner.run_card`, then its trades are redistributed "
            "into a daily return series and split by which sessions carry this label versus any "
            "other -- see `app.workflow.regime_backtest`'s module docstring for the exact "
            "geometric-decomposition rule this uses, since `run_card`'s own `AgentResult` carries no "
            "day-by-day equity curve to split directly."
        ),
        "",
    ]
    for label in _LABEL_ORDER:
        entry = next(e for e in score.entries if e.label == label)
        parts.append(_entry_section(entry))
        parts.append("")

    parts.append("## Conclusion")
    parts.append("")
    parts.append(_conclusion(history, score))
    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()

    start, end = (args.start, args.end)
    if start is None or end is None:
        default_start, default_end = _default_window(settings=settings)
        start = start or default_start
        end = end or default_end

    print(f"regime_backtest_report: window {start.isoformat()} .. {end.isoformat()}")

    macro_by_date: dict[dt.date, float] = {}
    macro_warning: str | None = None
    if not args.no_macro:
        print("regime_backtest_report: fetching FRED T10Y2Y history ...")
        macro_by_date, macro_warning = _fetch_macro_history(settings=settings)
        if macro_warning is not None:
            print(f"regime_backtest_report: macro fetch unavailable -- {macro_warning}")
        else:
            print(f"regime_backtest_report: got {len(macro_by_date)} T10Y2Y observations")
    else:
        macro_warning = "--no-macro was passed"

    print("regime_backtest_report: classifying regime history ...")
    history = regime_history(
        start, end, settings=settings, macro_2s10s_by_date=macro_by_date or None
    )
    print(f"regime_backtest_report: classified {len(history.days)} sessions")
    print(f"regime_backtest_report: frequencies {history.frequencies}")

    print("regime_backtest_report: scoring regime_map.json's primary cards (sequential) ...")
    score = score_regime_map(history, settings=settings)
    for entry in score.entries:
        status = entry.error if entry.error is not None else "ok"
        print(f"regime_backtest_report:   {entry.label} -> {entry.agent_id}: {status}")

    report = render_report(
        history, score, macro_warning=macro_warning, generated_at=dt.datetime.now(dt.UTC)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"regime_backtest_report: wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
