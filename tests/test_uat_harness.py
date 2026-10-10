"""The UAT harness's own logic, where it has any.

Most of `uat/harness` is plumbing around the real application and is exercised by running a persona
week. `_known_findings` is not: it decides what previous runs a session is told about, and it exists
because getting that wrong is what produced a mis-filed finding id in run 2 — which then sat in the
backlog for a week reading as an open defect it was not.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from app.config import Settings
from app.db import duck
from app.market.models import BAR_COLUMNS, Interval
from uat.harness.marketdata import AsOfMarket
from uat.harness.paperbroker import Mandate, Order, PaperBroker, Rejection, summarize
from uat.harness.run import Run, _known_findings, _order_quantity, _order_stop_level


def _write_run(runs: Path, run_id: str, findings: list[tuple[str, str]]) -> Path:
    run_dir = runs / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "feedback.jsonl").write_text(
        "".join(
            json.dumps({"finding_id": fid, "title": title, "session": 1}) + "\n"
            for fid, title in findings
        ),
        encoding="utf-8",
    )
    return run_dir


class TestKnownFindings:
    def test_collects_ids_and_titles_from_previous_runs(self, tmp_path: Path) -> None:
        """Titles travel with the ids, deliberately.

        An id on its own invites inferring the problem from the slug — which is how
        `backtest-event-study-no-technical-indicators`, a *closed* item, was carried as an open
        event-study gap by a reader who never opened the body.
        """
        runs = tmp_path / "runs"
        _write_run(runs, "2026-08-03_p", [("cash-missing", "The portfolio has no cash")])
        current = Run(runs / "2026-08-10_p")
        current.dir.mkdir(parents=True)

        known = _known_findings(current)

        assert known == [{"finding_id": "cash-missing", "title": "The portfolio has no cash"}]

    def test_excludes_the_current_run(self, tmp_path: Path) -> None:
        """A session must not be handed its own earlier findings as prior art.

        The harness already refuses a duplicate id *within* a run; feeding this session's own ids
        back to it would invite exactly the collision that rule exists to prevent.
        """
        runs = tmp_path / "runs"
        _write_run(runs, "2026-08-03_p", [("old-one", "Filed last week")])
        current_dir = _write_run(runs, "2026-08-10_p", [("this-run", "Filed today")])

        known = _known_findings(Run(current_dir))

        assert [f["finding_id"] for f in known] == ["old-one"]

    def test_a_reused_id_keeps_the_most_recent_title(self, tmp_path: Path) -> None:
        """Reuse across runs is the recurrence signal, so the latest description is the useful one."""
        runs = tmp_path / "runs"
        _write_run(runs, "2026-01-01_p", [("drawdown-label", "Original wording")])
        _write_run(runs, "2026-06-01_p", [("drawdown-label", "Sharper wording")])
        current = Run(runs / "2026-08-10_p")
        current.dir.mkdir(parents=True)

        known = _known_findings(current)

        assert known == [{"finding_id": "drawdown-label", "title": "Sharper wording"}]

    def test_the_first_run_has_nothing_to_be_told(self, tmp_path: Path) -> None:
        runs = tmp_path / "runs"
        current = Run(runs / "2026-08-10_p")
        current.dir.mkdir(parents=True)

        assert _known_findings(current) == []

    def test_a_run_with_no_feedback_file_is_skipped(self, tmp_path: Path) -> None:
        """An initialised-but-unfiled run is a normal state mid-week, not an error."""
        runs = tmp_path / "runs"
        (runs / "2026-08-03_p").mkdir(parents=True)
        _write_run(runs, "2026-08-05_p", [("real", "A real one")])
        current = Run(runs / "2026-08-10_p")
        current.dir.mkdir(parents=True)

        assert [f["finding_id"] for f in _known_findings(current)] == ["real"]


# ---------------------------------------------------------------------------
# PaperBroker.rejections -- exactly one record per rejected order
# ---------------------------------------------------------------------------
#
# `_reject` appends the `Rejection` it builds. `submit()`'s precheck branch used to append the same
# object again on top of that, so a precheck refusal -- non-positive quantity, fractional shares on a
# whole-shares mandate, a missing thesis or invalidation -- landed in `broker.rejections` twice and
# `summarize()` over-counted it. Rejections from the price-dependent paths (`_check_buy`,
# `_check_sell`, the unpriceable-symbol paths) call `_reject` directly and were never doubled, which is
# why the bug was selective rather than uniform, and why a fix has two ways to be wrong: leaving the
# double in place, or moving it so the *other* path loses its only record.
#
# It went unnoticed through two full runs (2026-07-06, 2026-07-13) because neither produced a single
# rejection. The third run's fractional-share refusal, order `s2-8`, was the first order this harness
# ever rejected, and it came back doubled in both `rejections_this_session` and the next session's
# `prior_rejections` in `uat/runs/2026-07-20_pro-investor-01`.


def _mandate(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "persona_id": "test-persona",
        "display_name": "Test Persona",
        "account_id": "acct-1",
        "account_label": "Test Account",
        "starting_cash": Decimal("10000.00"),
        "allow_fractional_shares": False,
        "max_positions": 10,
        "max_single_name_weight": Decimal("0.25"),
        "min_clip_notional": Decimal("100.00"),
        "min_cash": Decimal("0.00"),
        "settlement_days": 1,
        "slippage_bps": Decimal("5"),
        "commission_per_trade": Decimal("1.00"),
        "sec_fee_rate": Decimal("0.0000278"),
        "taf_per_share": Decimal("0.000166"),
        "taf_cap": Decimal("8.30"),
    }
    fields.update(overrides)
    return Mandate(**fields)  # type: ignore[arg-type]


def _order(**overrides: object) -> Order:
    fields: dict[str, object] = {
        "order_id": "s1-1",
        "session": 1,
        "decided_on": dt.date(2026, 1, 5),
        "symbol": "AAPL",
        "side": "buy",
        "quantity": Decimal("10"),
        "thesis": "a thesis",
        "invalidation": "an invalidation",
    }
    fields.update(overrides)
    return Order(**fields)  # type: ignore[arg-type]


def _seed_bars(settings: Settings, symbol: str, *, on: dt.date, price: float = 100.0) -> None:
    """Write one daily bar so `AsOfMarket.open_on` has something to read."""
    frame = pd.DataFrame(
        {
            "ts": pd.Series(
                [dt.datetime.combine(on, dt.time.min, tzinfo=dt.UTC)], dtype="datetime64[us, UTC]"
            ),
            "open": [price],
            "high": [price + 1.0],
            "low": [price - 1.0],
            "close": [price],
            "adj_close": [price],
            "volume": [1_000_000],
        },
        columns=list(BAR_COLUMNS),
    )
    with duck.connect() as conn:
        duck.write_bars(conn, settings.bars_dir, symbol, Interval.DAY, frame)


class TestRejectionRecordedOnce:
    def test_a_precheck_rejection_is_recorded_exactly_once(self) -> None:
        """Fails against the pre-fix code: `broker.rejections` held the same `Rejection` twice.

        `market`/`fill_date` are never touched on this path -- `_precheck` fails before either is
        read -- so a real `AsOfMarket` is unnecessary here.
        """
        broker = PaperBroker(_mandate())
        order = _order(quantity=Decimal("0"))  # non_positive_quantity, a precheck rule

        outcome = broker.submit(order, market=None, fill_date=dt.date(2026, 1, 6))  # type: ignore[arg-type]

        assert isinstance(outcome, Rejection)
        assert outcome.rule == "non_positive_quantity"
        assert broker.rejections == [outcome]
        counts = summarize(broker.fills, broker.rejections)
        assert counts["rejections"] == 1
        assert counts["rejections_by_rule"] == {"non_positive_quantity": 1}

    def test_a_non_precheck_rejection_is_also_recorded_exactly_once(
        self, settings: Settings
    ) -> None:
        """Pins the mirror-image failure mode: a fix that stops `_reject` from appending, without
        making `submit()` append the precheck result itself, would silently un-record every
        price-dependent rejection instead of double-recording precheck ones.

        Uses a `no_short` refusal, the cheapest price-dependent path -- it only needs `open_on` to
        succeed, never `close`.
        """
        fill_date = dt.date(2026, 1, 6)
        _seed_bars(settings, "AAPL", on=fill_date)
        market = AsOfMarket(as_of=dt.date(2026, 1, 5), settings=settings)

        broker = PaperBroker(_mandate())
        order = _order(side="sell", quantity=Decimal("5"))  # nothing held to sell

        outcome = broker.submit(order, market=market, fill_date=fill_date)

        assert isinstance(outcome, Rejection)
        assert outcome.rule == "no_short"
        assert broker.rejections == [outcome]
        assert summarize(broker.fills, broker.rejections)["rejections"] == 1


# ---------------------------------------------------------------------------
# cmd_orders field parsing -- a bad stop_level or quantity must not crash the CLI
# ---------------------------------------------------------------------------
#
# Every command in this CLI is documented to print JSON on stdout and nothing else so a subagent can
# consume it. A persona wrote `"stop_level": "n/a"` -- truthy, so the old code's
# `Decimal(str(raw["stop_level"])) if raw.get("stop_level") else None` reached `Decimal("n/a")` and
# raised an unhandled `decimal.InvalidOperation`, breaking that contract and costing the persona
# working time mid-session while it guessed at a numeric placeholder to get moving again.


class TestOrderStopLevelParsing:
    @pytest.mark.parametrize("placeholder", ["n/a", "N/A", " n/a ", ""])
    def test_placeholder_strings_mean_no_stop(self, placeholder: str) -> None:
        assert _order_stop_level({"stop_level": placeholder}, order_id="s1-1") is None

    def test_json_null_means_no_stop(self) -> None:
        assert _order_stop_level({"stop_level": None}, order_id="s1-1") is None

    def test_missing_key_means_no_stop(self) -> None:
        assert _order_stop_level({}, order_id="s1-1") is None

    def test_a_real_numeric_value_still_parses(self) -> None:
        assert _order_stop_level({"stop_level": "142.50"}, order_id="s1-1") == Decimal("142.50")

    def test_a_malformed_value_names_the_order_and_the_value_instead_of_crashing(self) -> None:
        """Fails against the pre-fix code with an unhandled `decimal.InvalidOperation`, not a
        `SystemExit` naming the order."""
        with pytest.raises(SystemExit) as excinfo:
            _order_stop_level({"stop_level": "n/a-ish"}, order_id="s2-8")
        message = str(excinfo.value)
        assert "s2-8" in message
        assert "n/a-ish" in message


class TestOrderQuantityParsing:
    def test_a_real_numeric_value_still_parses(self) -> None:
        assert _order_quantity({"quantity": "12.5"}, order_id="s1-1") == Decimal("12.5")

    def test_a_malformed_value_names_the_order_and_the_value_instead_of_crashing(self) -> None:
        with pytest.raises(SystemExit) as excinfo:
            _order_quantity({"quantity": "a dozen"}, order_id="s3-2")
        message = str(excinfo.value)
        assert "s3-2" in message
        assert "a dozen" in message
