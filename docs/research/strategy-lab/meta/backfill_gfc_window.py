"""Backfill the regime window the study's own brief left out.

**The defect.** The first version of `BRIEF.md` listed regime windows running `bull_2003_2007` to
2007-10-31 and resuming at `qe_bull_2009_2019` on 2009-04-01. Nothing covered 2007-11-01 to
2009-03-31 -- the global financial crisis, and SPY's worst drawdown in the entire sample at -56.5%.
Every stream inherited the list verbatim from the brief, so every stream's regime table has the same
hole. The `mean-reversion` analyst found it; the author of the brief did not.

**What it did and did not affect.** Nothing statistical: regime windows produce strategy mechanics
only -- no hit rates, no p-values, no q-values -- and are excluded from every correction family by
design. The crisis bars were present in every full-history aggregate throughout. What was lost is
the regime breakdown for the single most punishing stretch in the sample, which is exactly the
window a reader would want when asking whether a mean-reversion rule survives a real bear market.

**Why backfill rather than re-run.** Re-running four streams to recover a descriptive table would
cost hours and would also re-run every statistical test, producing a second set of numbers that
would then have to be reconciled with the ones already reported. This script instead reads each
stream's own `ideas_declared` back out of its primary JSON -- the exact declared family, no
retyping, no chance of a transcription drift -- and runs only the missing window's strategy
mechanics through the same `quantlab.strategy_backtest` every stream used.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB / "lib"))

from quantlab import Idea, bars_frame, slice_window, strategy_backtest  # noqa: E402

GFC = ("gfc_2007_2009", "2007-11-01", "2009-03-31")
PRIMARY = ["SPY", "QQQ", "IWM", "XLK", "XLV"]

#: Fields on `Idea`. Anything else in the stored dict (a stream's own annotations) is ignored.
IDEA_FIELDS = set(Idea.__dataclass_fields__)


def main() -> None:
    label, first, last = GFC
    out: dict[str, dict] = {}

    bars_by_symbol = {}
    for symbol in PRIMARY:
        full = bars_frame(symbol)
        window = slice_window(full, first, last)
        bars_by_symbol[symbol] = window
        print(f"{symbol}: {len(window)} bars in {label} ({first} -> {last})")
        if len(window) < 250:
            print(f"  WARNING: under the 250-bar floor the streams applied; results are indicative only")

    for path in sorted((LAB / "data").glob("*_primary.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        stream = payload.get("family", path.stem)
        declared = payload.get("ideas_declared", [])
        print(f"\n=== {stream}: {len(declared)} declared ideas ===")
        stream_out: dict[str, dict] = {}

        for raw in declared:
            idea = Idea(**{k: v for k, v in raw.items() if k in IDEA_FIELDS})
            per_symbol = {}
            for symbol in PRIMARY:
                window = bars_by_symbol[symbol]
                try:
                    result = strategy_backtest(window, idea)
                except Exception as exc:
                    per_symbol[symbol] = {"error": f"{type(exc).__name__}: {exc}"}
                    continue
                if result is None:
                    per_symbol[symbol] = {"skipped": "no exit and no max_holding_bars"}
                    continue
                per_symbol[symbol] = result
                s, b = result["strategy"], result["buy_hold"]
                print(
                    f"  {idea.key:<32} {symbol:<5} "
                    f"strat_tr={_f(s['total_return']):>8} bh_tr={_f(b['total_return']):>8} "
                    f"strat_dd={_f(s['max_drawdown']):>8} bh_dd={_f(b['max_drawdown']):>8} "
                    f"exp={_f(s['exposure']):>6} trades={s['trades']}"
                )
            stream_out[idea.key] = {"declared": raw, "by_symbol": per_symbol}
        out[stream] = stream_out

    # A crisis window is where "beat buy-and-hold" finally has a chance to mean something, because
    # buy-and-hold's own number is deeply negative. Count it explicitly rather than leaving the
    # reader to scan the table.
    print("\n--- rules that beat buy-and-hold's total return inside the crisis window ---")
    beat = 0
    total = 0
    for stream, ideas in out.items():
        for key, entry in ideas.items():
            for symbol, r in entry["by_symbol"].items():
                if not isinstance(r, dict) or "strategy" not in r:
                    continue
                total += 1
                if r.get("beats_buy_hold_total_return"):
                    beat += 1
                    print(
                        f"  {stream:<18} {key:<32} {symbol:<5} "
                        f"strat={_f(r['strategy']['total_return'])} vs bh={_f(r['buy_hold']['total_return'])}"
                    )
    print(f"\n{beat} of {total} idea x symbol cells beat buy-and-hold inside {label}.")

    payload = {
        "window": {"label": label, "first": first, "last": last},
        "symbols": PRIMARY,
        "bars_per_symbol": {s: len(b) for s, b in bars_by_symbol.items()},
        "note": (
            "Descriptive strategy mechanics only. No p-values: regime windows are outside every "
            "correction family in this study, by design. Backfills the window omitted from the "
            "first version of BRIEF.md."
        ),
        "beat_buy_hold": {"count": beat, "of": total},
        "streams": out,
    }
    path = LAB / "data" / "gfc_backfill.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {path}")


def _f(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.3f}"


if __name__ == "__main__":
    main()
