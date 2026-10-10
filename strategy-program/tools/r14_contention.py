"""Contention census, counting only *economic* differences.

The first version of this census compared trade lists in order and reported the control as moving in
2 of 8 windows -- which would have falsified the round. The control's sets were identical and only
the row order differed, so the ranking key sorts the log without touching the book. Order is not
contention; the set is. Every figure below compares sorted sets and cross-checks ending equity.
"""
import json
from pathlib import Path

R = Path("data/rounds/r14-2026-08/results")
FAM = {
    "B3-concentrated": (12, 4), "c19-volatility": (12, 4), "B-momentum": (12, 6),
    "A-rotation": (9, 3), "C-trend": (9, 5), "c21-uncorrelated": (6, 6),
}


def book(agent, w):
    f = R / w / "runs" / f"r1-{agent}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    trades = sorted(
        (t.get("symbol"), t.get("entry_date"), t.get("exit_date"), t.get("shares"))
        for t in (d.get("trades") or [])
    )
    return trades, d.get("ending_equity")


wins = sorted(p.name for p in R.iterdir() if p.is_dir())
print(f"{'card':20}{'univ':>6}{'slots':>7}{'headroom':>10}{'windows':>9}{'contested':>12}")
for base, (u, s) in FAM.items():
    keys = ["rs"] if base == "c21-uncorrelated" else ["rs", "lowvol", "stretch"]
    ran = moved = 0
    for w in wins:
        b = book(base, w)
        if b is None:
            continue
        ran += 1
        if any((v := book(f"{base}-{k}", w)) is not None and v != b for k in keys):
            moved += 1
    print(f"{base:20}{u:>6}{s:>7}{u-s:>10}{ran:>9}{f'{moved}/{ran}':>12}")
