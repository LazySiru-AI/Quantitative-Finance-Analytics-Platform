"""Run every strategy card through the mock broker and score the tournament.

    python -m app.tournament --cards ../docs/tournament/cards --out ../docs/tournament/results

Results are written per agent **as each run finishes**, not batched at the end. A tournament is
roughly a minute per card and any one of them can fail on a data gap; losing twenty-five completed
runs because the twenty-sixth raised would be a poor trade for the small amount of tidiness it buys.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import sys
import time
from decimal import Decimal
from pathlib import Path

from app.config import get_settings
from app.paper.paperbroker import load_mandate
from app.tournament.models import TRADE_END, TRADE_START, AgentResult, StrategyCard
from app.tournament.report_pdf import render_agent_report
from app.tournament.runner import run_card
from app.tournament.scoring import score

#: JSON files that legitimately sit in a cards directory without being cards. `StrategyCard` forbids
#: extra fields, so loading one raises a wall of validation errors naming every missing required
#: field, which buries the actual cause -- and because card loading happens before the per-card
#: try/except in `main`, it takes the whole run down rather than skipping one entry. A sidecar beside
#: the cards it describes is the natural place for per-card metadata; see
#: `strategy-program/tools/windows.py`'s provenance loader, which reads exactly this file.
_NOT_CARDS = frozenset({"provenance.json"})


def _cards(root: Path) -> list[tuple[str, StrategyCard]]:
    """Every card under `root`, tagged with the round its directory implies.

    Round two lives in a `round2/` subdirectory rather than in a field on the card, so the tag is
    derived from the path. The alternative -- a `round` field on `StrategyCard` -- would have meant
    changing the frozen contract after thirteen analysts had already submitted against it.
    """
    found: list[tuple[str, StrategyCard]] = []
    for path in sorted(root.glob("*.json")):
        if path.name in _NOT_CARDS:
            continue
        found.append(("r1", StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))))
    for path in sorted((root / "round2").glob("*.json")):
        if path.name in _NOT_CARDS:
            continue
        found.append(("r2", StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cards", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--persona", type=Path, default=Path("../uat/personas/pro-investor-01.setup.json")
    )
    parser.add_argument("--alpha", type=float, default=0.10)
    parser.add_argument("--skip-pdf", action="store_true")
    parser.add_argument(
        "--honour-persona-cap",
        action="store_true",
        help="keep the persona's 25%% single-name cap, which blocks five submitted cards outright",
    )
    parser.add_argument(
        "--start",
        type=dt.date.fromisoformat,
        default=TRADE_START,
        help="first session traded, ISO date (default: %(default)s)",
    )
    parser.add_argument(
        "--end",
        type=dt.date.fromisoformat,
        default=TRADE_END,
        help="last session traded, ISO date (default: %(default)s)",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="comma-separated substrings; run only cards whose agent_id contains one of them",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    mandate = load_mandate(args.persona)
    print(f"window: {args.start.isoformat()} -> {args.end.isoformat()}", flush=True)

    # The persona's own mandate caps a single name at 25% of the book. `StrategyCard` never checked
    # against it -- it validates only that `position_pct * max_positions <= 1.0` -- so five of the
    # twenty-six submitted cards specified a position size the broker would refuse outright, and
    # did: a06 took zero trades against 9 rejections, a07 filled 6 orders against 449. Analysts
    # were shown the card rule and never the mandate rule, so those books were unrunnable through
    # no fault of their design.
    #
    # The tournament therefore runs with the single-name cap raised to whatever the card contract
    # itself permits. That is a deliberate loosening of a real risk control, and it is disclosed
    # rather than silent: a concentrated card is now allowed to be as concentrated as it said it
    # was, and its drawdown should be read in that light. Every other mandate rule -- cash,
    # settlement, minimum clip, whole shares, slippage, fees -- is untouched.
    if args.honour_persona_cap:
        print(f"single-name cap: persona default {mandate.max_single_name_weight}", flush=True)
    else:
        mandate = dataclasses.replace(mandate, max_single_name_weight=Decimal(1))
        print(
            "single-name cap: raised to 1.0 so cards run as written (see module docstring)",
            flush=True,
        )
    args.out.mkdir(parents=True, exist_ok=True)
    runs_dir = args.out / "runs"
    runs_dir.mkdir(exist_ok=True)

    cards = _cards(args.cards)
    if args.only:
        substrings = [s.strip() for s in args.only.split(",") if s.strip()]
        found = len(cards)
        cards = [
            (round_tag, card)
            for round_tag, card in cards
            if any(s in card.agent_id for s in substrings)
        ]
        print(f"{len(cards)} of {found} cards selected by --only={args.only!r}", flush=True)
    else:
        print(f"{len(cards)} cards", flush=True)

    results: list[tuple[str, AgentResult]] = []
    for index, (round_tag, card) in enumerate(cards, start=1):
        started = time.time()
        try:
            result = run_card(
                card, settings=settings, mandate=mandate, start=args.start, end=args.end
            )
        except Exception as exc:
            print(
                f"[{index}/{len(cards)}] {round_tag} {card.agent_id}: FAILED {type(exc).__name__}: {exc}",
                flush=True,
            )
            continue
        results.append((round_tag, result))
        (runs_dir / f"{round_tag}-{card.agent_id}.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )
        print(
            f"[{index}/{len(cards)}] {round_tag} {card.agent_id}: {time.time() - started:.0f}s "
            f"trades={len(result.trades)} ret={float(result.total_return):+.2%} "
            f"dd={float(result.max_drawdown):.2%} rej={len(result.rejections)}",
            flush=True,
        )

    if not results:
        print("no runs completed", flush=True)
        return 1

    # Benjamini-Hochberg over **every** strategy tried, both rounds together. Correcting within a
    # round would halve the denominator and flatter everything in it, which is the precise failure
    # the correction exists to prevent -- 26 strategies were tried, so 26 is the honest count.
    overall = score(
        [r for _, r in results], alpha=args.alpha, trade_start=args.start, trade_end=args.end
    )
    (args.out / "tournament.json").write_text(overall.model_dump_json(indent=2), encoding="utf-8")

    for tag in ("r1", "r2"):
        subset = [r for t, r in results if t == tag]
        if subset:
            per_round = score(
                subset, alpha=args.alpha, trade_start=args.start, trade_end=args.end
            )
            (args.out / f"tournament-{tag}.json").write_text(
                per_round.model_dump_json(indent=2), encoding="utf-8"
            )
            print(f"{tag}: {len(subset)} agents, {per_round.discoveries} discoveries", flush=True)

    print(
        f"overall: {len(results)} agents, {overall.discoveries} discoveries at alpha={args.alpha}",
        flush=True,
    )

    if not args.skip_pdf:
        pdf_dir = args.out / "pdf"
        pdf_dir.mkdir(exist_ok=True)
        for tag in ("r1", "r2"):
            (pdf_dir / tag).mkdir(exist_ok=True)
        # Keyed on (round, id): the same agent_id appears in both rounds, and a dict keyed on
        # id alone hands round one's report round two's numbers -- which is exactly what the
        # first run did, writing 13 PDFs for 26 strategies.
        by_key = {
            (t, r.card.agent_id): r for (t, _), r in zip(results, overall.agents, strict=True)
        }
        for tag, result in results:
            scored = by_key.get((tag, result.card.agent_id), result)
            try:
                written = render_agent_report(
                    scored,
                    out_dir=pdf_dir / tag,
                    tournament=overall,
                    window=(args.start, args.end),
                )
                print(f"pdf {tag} {result.card.agent_id}: {written.name}", flush=True)
            except Exception as exc:
                print(f"pdf {result.card.agent_id}: FAILED {type(exc).__name__}: {exc}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
