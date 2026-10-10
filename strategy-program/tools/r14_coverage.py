"""Which windows each card actually ran, grouped by base family.

The spread measurement is only valid if a base and its variants ran the *same* windows -- a
median over eight windows is not comparable to a median over six. Both shortfalls trace to a
symbol with zero bars in the window (META pre-IPO in chop-2011, AVGO pre-IPO in gfc), which is a
property of the universe, so a base and its variants should fail together. Checked, not assumed.
"""
from pathlib import Path

R = Path("data/rounds/r14-2026-08/results")
BASES = ["B3-concentrated", "c19-volatility", "B-momentum", "A-rotation", "C-trend", "c21-uncorrelated"]

cov = {}
for w in sorted(p.name for p in R.iterdir() if p.is_dir()):
    for f in (R / w / "runs").glob("*.json"):
        cov.setdefault(f.stem.replace("r1-", "", 1), set()).add(w)

for base in BASES:
    fam = sorted(a for a in cov if a == base or a.startswith(base + "-"))
    sets = {a: cov[a] for a in fam}
    uniform = len({frozenset(s) for s in sets.values()}) == 1
    n = len(next(iter(sets.values())))
    print(f"{base:20} {len(fam)} cards  {n} windows  {'UNIFORM' if uniform else '!! RAGGED'}")
    if not uniform:
        for a, s in sets.items():
            print(f"     {a:32} {sorted(s)}")
    else:
        print(f"     {sorted(next(iter(sets.values())))}")
