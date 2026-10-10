"""Run CLI. The persona drives the week one subcommand at a time.

Sessions are separate processes because the decision-maker between them is a subagent, not a
function call. Everything the run needs therefore lives on disk under ``uat/runs/<run-id>/`` and is
reloaded on each invocation; nothing is held in memory across a session boundary.

The five subcommands map onto the persona's own process:

===========  ==================================================================================
``init``     Create the run directory, resolve the session calendar, fund the account.
``brief``    What the persona is allowed to know at the start of session N. Enforces the
             lookahead boundary: the brief is built from an ``AsOfMarket`` pinned to the prior
             session's close, so there is no way for a later price to reach the persona through it.
``orders``   Submit session N's order batch. Prints fills and rejections.
``close``    Mark the book at session N's own close and append the session record.
``finalize`` Render the week's fills as a broker export, load it through the real ingest path,
             and write the metrics file.
===========  ==================================================================================

Every command prints JSON on stdout and nothing else, so a subagent can consume the output without
having to parse prose.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

# The harness imports the application, so `backend/` has to be importable. Resolved from this file's
# location rather than assumed from the working directory: the persona invokes these commands from
# wherever it happens to be.
_HARNESS = Path(__file__).resolve().parent
_UAT = _HARNESS.parent
_REPO = _UAT.parent
for _path in (_REPO / "backend", _REPO):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from uat.harness import feedback as feedback_mod  # noqa: E402
from uat.harness.ingest import (  # noqa: E402
    ingest_fills,
    provision_sandbox,
    sandbox_settings,
    write_activity_csv,
)
from uat.harness.marketdata import AsOfMarket, SessionCalendar, UnpricedSymbol  # noqa: E402
from uat.harness.paperbroker import (  # noqa: E402
    Fill,
    Mandate,
    Order,
    PaperBroker,
    load_mandate,
    summarize,
)

__all__ = ["main"]


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------


class Run:
    """One persona's week on disk."""

    def __init__(self, run_dir: Path) -> None:
        self.dir = run_dir
        self.meta_path = run_dir / "run.json"
        self.state_path = run_dir / "state.json"
        self.orders_path = run_dir / "orders.jsonl"
        self.fills_path = run_dir / "fills.jsonl"
        self.sessions_path = run_dir / "sessions.jsonl"
        self.feedback_path = run_dir / "feedback.jsonl"
        self.csv_path = run_dir / "fills.csv"
        self.metrics_path = run_dir / "metrics.json"

    # -- meta --------------------------------------------------------------

    @property
    def meta(self) -> dict[str, Any]:
        if not self.meta_path.exists():
            raise SystemExit(
                f"no run at {self.dir}; run `init` first"
            )
        return json.loads(self.meta_path.read_text(encoding="utf-8"))

    def write_meta(self, meta: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(
            json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )

    # -- broker ------------------------------------------------------------

    def mandate(self) -> Mandate:
        return load_mandate(_REPO / self.meta["persona_setup"])

    def broker(self) -> PaperBroker:
        mandate = self.mandate()
        if not self.state_path.exists():
            return PaperBroker(mandate)
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        return PaperBroker.from_state(mandate, state)

    def save_broker(self, broker: PaperBroker) -> None:
        self.state_path.write_text(
            json.dumps(broker.to_state(), indent=2) + "\n", encoding="utf-8"
        )

    # -- calendar ----------------------------------------------------------

    def session(self, index: int) -> dict[str, Any]:
        sessions = self.meta["sessions"]
        if not 1 <= index <= len(sessions):
            raise SystemExit(
                f"session {index} is outside this run's 1..{len(sessions)}"
            )
        return sessions[index - 1]

    def append(self, path: Path, rows: list[dict[str, Any]]) -> None:
        with path.open("a", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _fingerprint(settings: Any) -> tuple[str, int]:
    """The sandbox ledger's fingerprint and row count, or a null reading if it does not exist yet."""
    from app.db import sqlite

    if not settings.ledger_path.exists():
        return ("", 0)
    with sqlite.connect(settings.ledger_path, read_only=True) as conn:
        return sqlite.ledger_fingerprint(conn)


def _emit(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def _resolve_sandbox(meta: dict[str, Any], requested: str | None) -> str:
    """The sandbox this run was ``init``ed with, or a loud failure if the caller asked for another.

    ``brief``/``orders``/``close``/``finalize``/``feedback`` are separate process invocations -- see
    the module docstring -- so nothing else would catch a session pointed at the wrong ledger by a
    mistyped or copy-pasted ``--sandbox``. Reading it back from ``run.json`` rather than trusting the
    flag on every later call is what makes that mistake fail immediately instead of silently mixing
    one run's fills into another's book. Runs written before this parameter existed have no
    ``"sandbox"`` key; they default to ``"sandbox"``, the same path they always used.
    """
    recorded = meta.get("sandbox", "sandbox")
    if requested is not None and requested != recorded:
        raise SystemExit(
            f"--sandbox {requested!r} does not match the sandbox this run was initialised with "
            f"({recorded!r}); refusing rather than silently operating on the wrong ledger. Pass "
            f"--sandbox {recorded!r} or omit the flag."
        )
    return recorded


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


def cmd_init(args: argparse.Namespace) -> int:
    persona_setup = Path(args.persona)
    if not persona_setup.is_absolute():
        persona_setup = _REPO / persona_setup
    mandate = load_mandate(persona_setup)

    settings = provision_sandbox(_REPO, name=args.sandbox)
    calendar = SessionCalendar(
        start=dt.date.fromisoformat(args.start),
        end=dt.date.fromisoformat(args.end),
        settings=settings,
        benchmark=args.benchmark,
    )

    run_id = args.run_id or f"{args.start}_{mandate.persona_id}"
    run = Run(_UAT / "runs" / run_id)
    if run.meta_path.exists() and not args.force:
        raise SystemExit(f"run {run_id} already exists; pass --force to start it over")

    run.dir.mkdir(parents=True, exist_ok=True)
    for path in (run.orders_path, run.fills_path, run.sessions_path):
        path.unlink(missing_ok=True)

    universe = _universe(settings, as_of=calendar.sessions[0].decided_on)

    run.write_meta(
        {
            "run_id": run_id,
            "persona_id": mandate.persona_id,
            "persona_setup": str(persona_setup.relative_to(_REPO)).replace("\\", "/"),
            "created_at": dt.datetime.now(dt.UTC).isoformat(),
            "sandbox": args.sandbox,
            "benchmark": args.benchmark,
            "starting_cash": format(mandate.starting_cash, "f"),
            "funded_on": calendar.sessions[0].decided_on.isoformat(),
            "sessions": [
                {
                    "index": s.index,
                    "date": s.date.isoformat(),
                    "decided_on": s.decided_on.isoformat(),
                }
                for s in calendar
            ],
            "universe": universe,
            "sandbox_ledger": str(settings.ledger_path.relative_to(_REPO)).replace("\\", "/"),
        }
    )

    broker = PaperBroker(mandate)
    run.save_broker(broker)

    _emit(
        {
            "run_id": run_id,
            "run_dir": str(run.dir.relative_to(_REPO)).replace("\\", "/"),
            "sandbox": args.sandbox,
            "persona": mandate.display_name,
            "sessions": len(calendar),
            "first_session": calendar.sessions[0].date.isoformat(),
            "last_session": calendar.sessions[-1].date.isoformat(),
            "starting_cash": format(mandate.starting_cash, "f"),
            "universe_size": len(universe),
        }
    )
    return 0


def _universe(settings: Any, *, as_of: dt.date) -> list[str]:
    """Symbols the store can actually price, which is the only universe the run can trade.

    Filtered to what the ledger's own symbol rule accepts (``^[A-Z][A-Z0-9]{0,5}(\\.[A-Z]{1,2})?$``
    in the Robinhood adapter), so an index or futures symbol the store happens to carry -- ``^VIX``,
    ``DX-Y.NYB`` -- is available for *context* but cannot be ordered. Letting the persona try to buy
    one would produce an order that fails at CSV ingest rather than at submission, which is a
    confusing place to discover it.
    """
    bars = settings.bars_dir / "interval=1d"
    if not bars.exists():
        return []
    import re

    tradeable = re.compile(r"^[A-Z][A-Z0-9]{0,5}(\.[A-Z]{1,2})?$")
    symbols = sorted(
        path.name.split("=", 1)[1] for path in bars.iterdir() if path.name.startswith("symbol=")
    )
    return [s for s in symbols if tradeable.match(s)]


# ---------------------------------------------------------------------------
# brief
# ---------------------------------------------------------------------------


def cmd_brief(args: argparse.Namespace) -> int:
    run = Run(_UAT / "runs" / args.run_id)
    meta = run.meta
    session = run.session(args.session)
    settings = sandbox_settings(_REPO, name=_resolve_sandbox(meta, args.sandbox))

    decided_on = dt.date.fromisoformat(session["decided_on"])
    market = AsOfMarket(as_of=decided_on, settings=settings)
    broker = run.broker()

    watch = args.watch or []
    context = {symbol: _symbol_context(market, symbol) for symbol in watch}

    _emit(
        {
            "run_id": meta["run_id"],
            "session": session["index"],
            "of_sessions": len(meta["sessions"]),
            "trading_on": session["date"],
            "decision_data_through": session["decided_on"],
            "fill_rule": (
                "orders submitted for this session fill at the open of "
                f"{session['date']}, plus adverse slippage"
            ),
            "book": broker.snapshot(market),
            "benchmark": _symbol_context(market, meta["benchmark"]),
            "watchlist": context,
            "universe": meta["universe"],
            "prior_rejections": [
                r.to_json() for r in broker.rejections if r.session == session["index"] - 1
            ],
            "known_findings": _known_findings(run),
        }
    )
    return 0


def _known_findings(current: Run) -> list[dict[str, str]]:
    """Every ``finding_id`` previous runs recorded, with the title it was filed under.

    In the brief because ``finding_id`` is the dedupe key *across* runs: a confirmed item that
    reappears under the same id is a regression, and one filed under a fresh id for the same problem
    is invisible to that check. A persona cannot honour that convention without knowing which ids
    exist, and telling it to "reuse the existing id" while handing it a backlog whose items are
    numbered prose is how it ends up improvising one.

    Run 2 shows both halves of that. Three re-tests correctly reused run 1's ids, and a fourth --
    confirming the rule grammar's hint was fixed -- was filed under
    ``backtest-event-study-no-technical-indicators``, which run 1 had used for the same root cause on
    a different surface. The id was right and the title described the surface re-tested rather than
    the problem, so the entry read as an open event-study gap to anyone skimming ids. It was, in
    fact, a confirmed fix.

    Titles travel with the ids for exactly that reason: an id alone invites the reader -- persona or
    orchestrator -- to infer the problem from the slug, which is the mistake this list exists to stop.
    """
    seen: dict[str, str] = {}
    runs_dir = current.dir.parent
    if not runs_dir.exists():
        return []
    for run_dir in sorted(runs_dir.iterdir()):
        if run_dir == current.dir or not run_dir.is_dir():
            continue
        feedback = run_dir / "feedback.jsonl"
        if not feedback.exists():
            continue
        for line in feedback.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            # Last writer wins: a later run's title is the more current description of the problem.
            seen[record["finding_id"]] = record.get("title", "")
    return [{"finding_id": k, "title": v} for k, v in sorted(seen.items())]


def _symbol_context(market: AsOfMarket, symbol: str) -> dict[str, Any]:
    """A compact read on one symbol, as of the decision date.

    Deliberately thin: closes, a couple of moving averages and the recent range. The persona is
    meant to get its analysis from the *application under test* -- that is the point of the exercise
    -- so anything richer than this competes with the thing being evaluated.
    """
    try:
        frame = market.history(symbol, lookback_days=400)
    except (UnpricedSymbol, FileNotFoundError):
        return {"symbol": symbol, "available": False}
    if frame.empty:
        return {"symbol": symbol, "available": False}

    closes = [Decimal(str(round(float(c), 4))) for c in frame["close"]]
    last = closes[-1]

    def sma(window: int) -> str | None:
        if len(closes) < window:
            return None
        return format(sum(closes[-window:]) / window, ".4f")

    def change(window: int) -> str | None:
        if len(closes) <= window or closes[-window - 1] == 0:
            return None
        return format((last - closes[-window - 1]) / closes[-window - 1], ".6f")

    return {
        "symbol": symbol,
        "available": True,
        "as_of": market.as_of.isoformat(),
        "close": format(last, "f"),
        "sma20": sma(20),
        "sma50": sma(50),
        "sma200": sma(200),
        "change_1d_pct_of_1": change(1),
        "change_5d_pct_of_1": change(5),
        "change_20d_pct_of_1": change(20),
        "range_52w": {
            "high": format(max(closes[-252:]), "f"),
            "low": format(min(closes[-252:]), "f"),
        },
        "bars_available": len(closes),
    }


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------


def _order_quantity(raw: dict[str, Any], *, order_id: str) -> Decimal:
    """The persona-supplied ``quantity``, or a clean failure naming the order and the value.

    Every command in this CLI is documented to print JSON on stdout and nothing else so a subagent
    can consume it -- a persona has no way to parse a raw ``decimal.InvalidOperation`` traceback out
    of that contract. Unlike ``stop_level``, quantity has no "not specified" reading worth
    tolerating: an order with no quantity is not an order.
    """
    value = raw["quantity"]
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise SystemExit(
            f"order {order_id!r}: quantity {value!r} is not a valid number"
        ) from exc


def _order_stop_level(raw: dict[str, Any], *, order_id: str) -> Decimal | None:
    """The persona-supplied ``stop_level``, tolerant of the ways "no stop" gets spelled.

    A sell that closes a position, or an order submitted purely to probe a mandate rule, legitimately
    has no stop level -- there is nothing to protect. JSON ``null`` (or the key omitted), the empty
    string, and the placeholder ``"n/a"`` a persona reaches for when a field does not apply all mean
    exactly that and are treated identically. Anything else must parse as a number; a persona forced
    to guess a numeric placeholder to dodge a crash is worse than a validation error that says what
    was wrong. That guess is exactly what a prior run's persona had to make: `Decimal("n/a")` raised
    an unhandled `decimal.InvalidOperation` and burned working time mid-session before it found a
    workaround.
    """
    value = raw.get("stop_level")
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in ("", "n/a"):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise SystemExit(
            f"order {order_id!r}: stop_level {value!r} is not a valid number "
            '(use null, "", or "n/a" for no stop)'
        ) from exc


def cmd_orders(args: argparse.Namespace) -> int:
    run = Run(_UAT / "runs" / args.run_id)
    meta = run.meta
    session = run.session(args.session)
    settings = sandbox_settings(_REPO, name=_resolve_sandbox(meta, args.sandbox))

    decided_on = dt.date.fromisoformat(session["decided_on"])
    fill_date = dt.date.fromisoformat(session["date"])
    market = AsOfMarket(as_of=decided_on, settings=settings)
    broker = run.broker()

    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    raw_orders = payload["orders"] if isinstance(payload, dict) else payload

    results: list[dict[str, Any]] = []
    submitted: list[dict[str, Any]] = []

    for position, raw in enumerate(raw_orders):
        order_id = raw.get("order_id") or f"s{session['index']}-{position + 1}"
        order = Order(
            order_id=order_id,
            session=session["index"],
            decided_on=decided_on,
            symbol=str(raw["symbol"]).upper(),
            side=raw["side"],
            quantity=_order_quantity(raw, order_id=order_id),
            thesis=raw.get("thesis", ""),
            invalidation=raw.get("invalidation", ""),
            stop_level=_order_stop_level(raw, order_id=order_id),
            regime=raw.get("regime"),
            conviction=raw.get("conviction"),
            evidence=tuple(raw.get("evidence", ())),
        )
        submitted.append(order.to_json())
        outcome = broker.submit(order, market=market, fill_date=fill_date)
        if isinstance(outcome, Fill):
            results.append({"status": "filled", **outcome.to_json()})
        else:
            results.append({"status": "rejected", **outcome.to_json()})

    run.append(run.orders_path, submitted)
    run.append(
        run.fills_path,
        [r for r in results if r["status"] == "filled"],
    )
    run.save_broker(broker)

    post = AsOfMarket(as_of=fill_date, settings=settings)
    _emit(
        {
            "session": session["index"],
            "trading_on": session["date"],
            "results": results,
            "filled": sum(1 for r in results if r["status"] == "filled"),
            "rejected": sum(1 for r in results if r["status"] == "rejected"),
            "book_after": broker.snapshot(post),
        }
    )
    return 0


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def cmd_close(args: argparse.Namespace) -> int:
    run = Run(_UAT / "runs" / args.run_id)
    meta = run.meta
    session = run.session(args.session)
    settings = sandbox_settings(_REPO, name=_resolve_sandbox(meta, args.sandbox))

    fill_date = dt.date.fromisoformat(session["date"])
    market = AsOfMarket(as_of=fill_date, settings=settings)
    broker = run.broker()

    snapshot = broker.snapshot(market)
    mandate = run.mandate()
    equity = Decimal(snapshot["equity"])

    session_fills = [f for f in broker.fills if f.session == session["index"]]

    # Ingest this session's fills now rather than at the end of the run, so tomorrow's brief and the
    # dashboard the persona reviews are looking at the same book. One export per session -- see
    # `write_activity_csv` for why a single growing file would collide with itself.
    ingest = None
    if session_fills or session["index"] == 1:
        export = run.dir / "imports" / f"session-{session['index']}.csv"
        write_activity_csv(
            export,
            fills=session_fills,
            mandate=mandate,
            funded_on=(
                dt.date.fromisoformat(meta["funded_on"]) if session["index"] == 1 else None
            ),
        )
        ingest = ingest_fills(export, mandate=mandate, settings=settings).to_json()

    record = {
        "session": session["index"],
        "date": session["date"],
        "closed_at": dt.datetime.now(dt.UTC).isoformat(),
        "book": snapshot,
        "equity": format(equity, "f"),
        "pnl_since_inception": format(equity - mandate.starting_cash, "f"),
        "benchmark": _symbol_context(market, meta["benchmark"]),
        "fills_this_session": [f.to_json() for f in session_fills],
        "rejections_this_session": [
            r.to_json() for r in broker.rejections if r.session == session["index"]
        ],
        "ingest": ingest,
        "journal": args.journal or "",
    }
    run.append(run.sessions_path, [record])
    _emit(record)
    return 0


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------


def cmd_feedback(args: argparse.Namespace) -> int:
    run = Run(_UAT / "runs" / args.run_id)
    meta = run.meta
    _resolve_sandbox(meta, args.sandbox)  # validate only; feedback never touches the ledger
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    findings = payload["findings"] if isinstance(payload, dict) else payload

    now = dt.datetime.now(dt.UTC).isoformat()
    for finding in findings:
        finding.setdefault("run_id", meta["run_id"])
        finding.setdefault("persona_id", meta["persona_id"])
        finding.setdefault("observed_at", now)

    try:
        written = feedback_mod.append_findings(run.feedback_path, findings)
    except (feedback_mod.FindingError, ValueError) as exc:
        _emit({"accepted": 0, "error": str(exc)})
        return 1

    _emit({"accepted": written, "total_in_run": len(feedback_mod.load_findings(run.feedback_path))})
    return 0


# ---------------------------------------------------------------------------
# finalize
# ---------------------------------------------------------------------------


def cmd_finalize(args: argparse.Namespace) -> int:
    run = Run(_UAT / "runs" / args.run_id)
    meta = run.meta
    settings = sandbox_settings(_REPO, name=_resolve_sandbox(meta, args.sandbox))
    mandate = run.mandate()
    broker = run.broker()

    funded_on = dt.date.fromisoformat(meta["funded_on"])
    # The combined export is a human-readable artifact of the week, not an ingest input: every fill
    # in it already entered the ledger through its own per-session file during `close`.
    write_activity_csv(
        run.csv_path, fills=broker.fills, mandate=mandate, funded_on=funded_on
    )

    # Re-ingest the per-session exports. Every row is already in the ledger, so a correct
    # application reports all of them as duplicates and leaves the fingerprint unmoved. This is the
    # run confirming the idempotency claim in `app.db.sqlite.insert_transactions` rather than
    # trusting it -- and it is a claim worth confirming, since re-importing an unchanged broker
    # export is the single most likely thing a real user does by accident.
    exports = sorted((run.dir / "imports").glob("session-*.csv"))
    before = _fingerprint(settings)
    replays = [
        ingest_fills(export, mandate=mandate, settings=settings).to_json() for export in exports
    ]
    after = _fingerprint(settings)
    idempotent = (
        before == after
        and all(r["inserted"] == 0 for r in replays)
        and all(not r["conflicts"] for r in replays)
    )

    last_session = dt.date.fromisoformat(meta["sessions"][-1]["date"])
    market = AsOfMarket(as_of=last_session, settings=settings)
    final = broker.snapshot(market)
    equity = Decimal(final["equity"])
    start = mandate.starting_cash

    benchmark = _symbol_context(market, meta["benchmark"])
    first_session = dt.date.fromisoformat(meta["sessions"][0]["date"])
    bench_start = AsOfMarket(as_of=first_session, settings=settings).close(meta["benchmark"])
    bench_end = Decimal(benchmark["close"])

    metrics = {
        "run_id": meta["run_id"],
        "persona_id": meta["persona_id"],
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "window": {
            "first_session": meta["sessions"][0]["date"],
            "last_session": meta["sessions"][-1]["date"],
            "sessions": len(meta["sessions"]),
        },
        "performance": {
            "starting_cash": format(start, "f"),
            "ending_equity": format(equity, "f"),
            "pnl": format(equity - start, "f"),
            "return_pct_of_1": format((equity - start) / start, ".6f"),
            "benchmark": meta["benchmark"],
            "benchmark_return_pct_of_1": format((bench_end - bench_start) / bench_start, ".6f"),
            "$comment": (
                "Five sessions of a notional $10,000 sleeve. Far too short a window to say anything "
                "about the persona's process, and not intended to -- these figures exist to give "
                "the dashboard non-trivial numbers to display, not to evaluate a strategy."
            ),
        },
        "activity": dict(summarize(broker.fills, broker.rejections)),
        "final_book": final,
        "ingest": {
            "exports": [p.name for p in exports],
            "replay": replays,
            "fingerprint_before_replay": before[0],
            "fingerprint_after_replay": after[0],
            "ledger_txn_count": after[1],
            "idempotent": idempotent,
        },
        "findings_recorded": len(feedback_mod.load_findings(run.feedback_path)),
    }
    run.metrics_path.write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _emit(metrics)
    return 0


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="uat.harness.run",
        description="Drive a UAT persona through a trading week against the dashboard.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # `init` picks the sandbox; every later subcommand for the same run must agree with what it
    # picked (see `_resolve_sandbox`), so their `--sandbox` defaults to `None` -- "whatever this run
    # was initialised with" -- rather than repeating the literal default and risking a stale flag
    # silently overriding it.
    _later_sandbox_help = (
        "must match the sandbox this run was `init`ed with (see run.json); omit to use it "
        "automatically"
    )

    p_init = sub.add_parser("init", help="create a run")
    p_init.add_argument("--persona", default="uat/personas/pro-investor-01.setup.json")
    p_init.add_argument("--start", required=True, help="first session date, YYYY-MM-DD")
    p_init.add_argument("--end", required=True, help="last session date, YYYY-MM-DD")
    p_init.add_argument("--benchmark", default="SPY")
    p_init.add_argument("--run-id", dest="run_id", default=None)
    p_init.add_argument("--force", action="store_true")
    p_init.add_argument(
        "--sandbox",
        default="sandbox",
        help="name under uat/sandbox/ this run's ledger and store live in",
    )
    p_init.set_defaults(func=cmd_init)

    p_brief = sub.add_parser("brief", help="what the persona may know at session start")
    p_brief.add_argument("--run-id", dest="run_id", required=True)
    p_brief.add_argument("--session", type=int, required=True)
    p_brief.add_argument("--watch", nargs="*", default=[])
    p_brief.add_argument("--sandbox", default=None, help=_later_sandbox_help)
    p_brief.set_defaults(func=cmd_brief)

    p_orders = sub.add_parser("orders", help="submit a session's order batch")
    p_orders.add_argument("--run-id", dest="run_id", required=True)
    p_orders.add_argument("--session", type=int, required=True)
    p_orders.add_argument("--file", required=True, help="JSON file: {\"orders\": [...]}")
    p_orders.add_argument("--sandbox", default=None, help=_later_sandbox_help)
    p_orders.set_defaults(func=cmd_orders)

    p_close = sub.add_parser("close", help="mark the book at the session close")
    p_close.add_argument("--run-id", dest="run_id", required=True)
    p_close.add_argument("--session", type=int, required=True)
    p_close.add_argument("--journal", default="")
    p_close.add_argument("--sandbox", default=None, help=_later_sandbox_help)
    p_close.set_defaults(func=cmd_close)

    p_feedback = sub.add_parser("feedback", help="record findings")
    p_feedback.add_argument("--run-id", dest="run_id", required=True)
    p_feedback.add_argument("--file", required=True, help="JSON file: {\"findings\": [...]}")
    p_feedback.add_argument("--sandbox", default=None, help=_later_sandbox_help)
    p_feedback.set_defaults(func=cmd_feedback)

    p_final = sub.add_parser("finalize", help="export, ingest and measure")
    p_final.add_argument("--run-id", dest="run_id", required=True)
    p_final.add_argument("--sandbox", default=None, help=_later_sandbox_help)
    p_final.set_defaults(func=cmd_finalize)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
