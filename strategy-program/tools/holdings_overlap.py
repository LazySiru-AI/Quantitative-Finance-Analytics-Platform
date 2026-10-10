"""Distinctness measured on what a card *holds*, across the whole live window rather than one day.

Round 12 replaces the distinctness rule. Rounds 6-11 used two proxies for "a different idea" --
`StrategyCard.discipline`, and a base-family map grouping the four `B` variants as one entry -- and
both have now failed on the same axis: they classify by what a card *descends from*, not by what it
*shows the reader*. `data/rounds/r11-2026-08/SELECTION.md` section 8 is the case that broke them:
`B3-concentrated` and `B-momentum` are one base family and were therefore mutually exclusive, while
their actual holdings differ by two names out of six -- a difference the owner judged worth a seat,
and the rule could not see at all.

**This is not round 7's overlap cap revived, and the difference matters.** That cap
(`data/rounds/r7-2026-08/SELECTION.md` section 2) asked *"would this pair make one portfolio too
concentrated"*, and round 8 retired it because four independent reference signals are not one
portfolio -- there is no combined book whose concentration could be a risk. That reasoning still
stands and nothing here disputes it. The question this module asks is a different one that happens to
use the same measurement: **would a reader learn anything from the second panel that the first did not
already show them?** That is a property of the desk as a *display*, not as a book, and it applies
exactly as much to signals nobody combines as to positions somebody holds.

Round 8's other objection -- that the cap cost roughly nine points of out-of-sample return by dropping
`A-rotation` -- is answered by *where* the measurement sits rather than by arguing with it. Overlap
here never chooses between cards; the ranking does that, and it runs first. Overlap only asks whether
a card already beaten by a seated one still adds something to look at.

**Novelty, not similarity, and deliberately asymmetric.** The quantity is the fraction of a
candidate's own holdings that nothing already seated is holding::

    novelty(C | seated) = mean over sessions of  |H_C(t) \\ union of H_S(t)| / |H_C(t)|

Asymmetry is the point. A card holding six names, four of which a seated card also holds, is a third
new; the same pair in the other order is *entirely* redundant, because the narrower card shows no name
the wider one does not. Symmetric measures (Jaccard, the overlap coefficient) collapse those two cases
into one number and cannot express "seat the wide one, then the narrow one adds nothing" -- which is
precisely the `B`-variant case that broke the old rule.

Measured against the **union** of everything already seated rather than pairwise, because the question
is what is already on the page, not what any single other panel holds.

**Across every session, not today's snapshot.** Round 7's own section 9.2 flagged this as its cap's
main weakness -- *"measured on today's holdings, one snapshot. Two cards that overlap now may not in
three months"* -- and it is the one criticism of that cap this module can simply fix. Held sets are
reconstructed per session from each card's trade log over the live out-of-sample window, so a pair
that happens to converge on one date is not mistaken for a pair that tracks each other for six months.

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe \\
        strategy-program/tools/holdings_overlap.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import round10
import score

from app.config import get_settings
from app.db import duck

#: The cumulative run covering the whole live out-of-sample window. `live-6` is the last of round
#: 11's six cumulative runs, so it spans 2026-02-17 to 2026-08-18 in one piece -- which is what makes
#: its trade log a complete record of what each card held on every session. The earlier tags are
#: prefixes of it and would double-count.
LIVE_RESULTS = Path("data/rounds/r11-2026-08/results/live-6")
WINDOW = (dt.date(2026, 2, 17), dt.date(2026, 8, 18))


def sessions(start: dt.date, end: dt.date) -> list[dt.date]:
    """SPY's own trading sessions across the window -- the calendar every card's dates land on."""
    settings = get_settings()
    with duck.connect(settings.analytics_path) as conn:
        bars = duck.read_bars(conn, settings.bars_dir, "SPY", duck.Interval.DAY, start=start, end=end)
    return [ts.date() for ts in bars["ts"].tolist()]


def held_by_session(agent_id: str, days: Sequence[dt.date]) -> list[frozenset[str]]:
    """The set of symbols a card held at each session's close, from its trade log.

    A closed trade is held over ``[entry_date, exit_date)`` -- inclusive of entry, exclusive of exit,
    because a position sold on a date is not held at that date's close. **A trade still open at the
    window's end carries ``exit_date is None``**, not a date equal to the window end, so it is held
    from entry through every remaining session; treating a missing exit as "sold today" would have
    silently emptied every card's book on the last day.
    """
    path = LIVE_RESULTS / "runs" / f"r1-{agent_id}.json"
    result = score.AgentResult.model_validate_json(path.read_text(encoding="utf-8"))
    out: list[frozenset[str]] = []
    for day in days:
        names = {
            trade.symbol
            for trade in result.trades
            if trade.entry_date <= day
            and (trade.exit_date is None or day < trade.exit_date)
        }
        out.append(frozenset(names))
    return out


def novelty(
    candidate: Sequence[frozenset[str]], seated: Sequence[Sequence[frozenset[str]]]
) -> tuple[float | None, float | None, int]:
    """``(mean novel names, mean novel fraction, invested sessions)`` for one candidate.

    **The count is what the rule uses; the fraction is reported beside it.** A percentage needs a
    threshold nobody can derive -- and on this field the choice between 20% and 34% is exactly the
    choice between seating the owner's fifth card and not, which is precisely the kind of free
    parameter this programme has twice had to unpick. A *count* has a natural unit instead: **one
    whole position.** A panel earns its place on the desk by showing, on average, at least one name
    that no other panel shows. That is the smallest thing a reader could possibly learn from it.

    The count also self-adjusts for slot count, which a fraction does not. One new name out of four
    is 25% and one out of six is 17%; both are the same single thing to look at, and a fixed
    percentage would hold a wide card to a stricter standard than a narrow one for no reason
    connected to what either shows.

    Sessions where the candidate holds nothing are skipped rather than scored: a card in cash is
    neither showing a new name nor repeating one, and counting those sessions either way would turn
    novelty into a measure of how often a card is invested. ``(None, None, 0)`` when the card never
    held anything -- undefined, not zero, and Gate L already removes such cards.
    """
    counts: list[int] = []
    fractions: list[float] = []
    for i, held in enumerate(candidate):
        if not held:
            continue
        already: set[str] = set()
        for other in seated:
            already |= other[i]
        new = held - already
        counts.append(len(new))
        fractions.append(len(new) / len(held))
    if not counts:
        return None, None, 0
    return sum(counts) / len(counts), sum(fractions) / len(fractions), len(counts)


def jaccard(a: Sequence[frozenset[str]], b: Sequence[frozenset[str]]) -> float | None:
    """Mean daily Jaccard, reported alongside novelty for readers who want the symmetric view.

    Not used by the rule. It is here because it is the number round 7's cap used, so a reader
    comparing the two rounds can see both quantities for the same pair rather than taking on trust
    that they differ.
    """
    scored = [
        len(x & y) / len(x | y)
        for x, y in zip(a, b, strict=True)
        if x or y
    ]
    return sum(scored) / len(scored) if scored else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument(
        "--thresholds",
        default="0.50,1.00,1.50",
        help="novel-names-per-session cut-offs to report the roster at, for sensitivity",
    )
    args = parser.parse_args(argv)

    days = sessions(*WINDOW)
    print(f"live window {WINDOW[0]} .. {WINDOW[1]} -- {len(days)} sessions\n")

    held: dict[str, list[frozenset[str]]] = {}
    for agent_id in round10.FIELD:
        try:
            held[agent_id] = held_by_session(agent_id, days)
        except FileNotFoundError:
            print(f"  !! no live run on disk for {agent_id} -- excluded")

    print("== mean names held, and how often invested ==")
    print(f"{'card':24} {'mean held':>10} {'sessions invested':>18}")
    for agent_id, series in sorted(
        held.items(), key=lambda kv: -sum(len(s) for s in kv[1]) / len(days)
    ):
        invested = sum(1 for s in series if s)
        print(
            f"{agent_id:24} {sum(len(s) for s in series) / len(days):>10.2f} "
            f"{f'{invested}/{len(days)}':>18}"
        )

    # Round 11's ranking, which runs first. Overlap never reorders it -- it only asks whether a card
    # already beaten by a seated one still shows the reader something.
    ranking = ["B3-concentrated", "B-momentum", "B4-tight-stop", "B2-hold-90", "A-rotation", "C-trend"]
    ranking = [a for a in ranking if a in held]

    print("\n== pairwise: novelty of ROW given COLUMN alone, and (symmetric Jaccard) ==")
    head = " ".join(f"{a[:11]:>13}" for a in ranking)
    print(f"{'':24} {head}")
    pairwise: dict[str, dict[str, float | None]] = {}
    for a in ranking:
        cells = []
        for b in ranking:
            if a == b:
                cells.append(f"{'--':>13}")
                continue
            count, frac, _ = novelty(held[a], [held[b]])
            pairwise.setdefault(a, {})[b] = count
            cells.append(
                f"{count:>5.2f} ({frac * 100:>3.0f}%)" if count is not None else f"{'n/a':>13}"
            )
        print(f"{a:24} " + " ".join(cells))
    print("  Read across: 'if only the column card were seated, the row card would still show this")
    print("  many names nothing else does' (and that as a fraction of its own book). Asymmetric on")
    print("  purpose -- see the module docstring.")

    # The symmetric view, which the rule does not use. Printed because round 7's retired cap was
    # stated in exactly this quantity, so a reader comparing the two rounds can see both numbers for
    # the same pair rather than taking on trust that they measure different things.
    print("\n== mean daily Jaccard (symmetric) -- round 7's quantity, for comparison only ==")
    print(f"{'':24} {head}")
    for a in ranking:
        cells = []
        for b in ranking:
            jac = None if a == b else jaccard(held[a], held[b])
            cells.append(f"{'--':>13}" if jac is None else f"{jac * 100:>12.0f}%")
        print(f"{a:24} " + " ".join(cells))

    results: dict[str, list[str]] = {}
    for raw in args.thresholds.split(","):
        threshold = float(raw)
        print(f"\n== walking the ranking at novelty >= {threshold:.2f} ==")
        seats: list[str] = []
        for agent_id in ranking:
            if not seats:
                seats.append(agent_id)
                print(f"  SEAT {agent_id:22} (first ranked -- nothing to be redundant with)")
                continue
            count, frac, n = novelty(held[agent_id], [held[s] for s in seats])
            if count is None:
                print(f"  skip {agent_id:22} -- never held anything; novelty undefined")
            elif count >= threshold:
                seats.append(agent_id)
                print(
                    f"  SEAT {agent_id:22} {count:>5.2f} novel names ({frac * 100:>4.1f}% of its "
                    f"book) over {n} invested sessions"
                )
            else:
                print(
                    f"  skip {agent_id:22} {count:>5.2f} novel names ({frac * 100:>4.1f}%) "
                    f"-- below the line"
                )
        results[f"{threshold:.2f}"] = list(seats)
        print(f"  -> {len(seats)} seats: {', '.join(seats)}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "window": [d.isoformat() for d in WINDOW],
                    "sessions": len(days),
                    "ranking": ranking,
                    "pairwise_novel_names": pairwise,
                    "seats_by_threshold": results,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
