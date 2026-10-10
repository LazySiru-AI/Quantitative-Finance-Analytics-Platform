"""Study-wide multiplicity correction across every analyst's family.

**The problem this exists to solve.** Each stream declares its own family and Benjamini-Hochberg
corrects within it. That is correct *for that stream*. But five analysts each running ~40 tests
against the same five symbols and the same historical path have collectively run ~200 tests, and a
q-value of 0.06 inside a 40-test ledger is a materially weaker claim once you know it was the best
of 200. Reporting only the within-stream q would let the study as a whole p-hack by division of
labour -- the exact failure the per-stream discipline is meant to prevent, reintroduced one level up.

So: pool every **primary** cell from every stream into one ledger and re-correct. A finding that
survives both its own stream's correction and the study-wide correction is a genuinely different
claim from one that survives only the former, and the consolidated report must distinguish them.

**What is pooled and what is not.** Primary families only -- the `cells` array of any
`*_primary.json`. Exploratory horizon sweeps are already declared descriptive and carry their own
separate ledgers; folding them in would punish the primary families for a search the study already
labelled as non-confirmatory. Replication runs are excluded for the same reason in reverse: they are
a second look at an already-surviving hypothesis, not a new test of a new one.

**This does not make the pooled q the "true" one.** The five symbols are heavily correlated with each
other, and Benjamini-Hochberg controls the false discovery rate under independence or positive
dependence -- not under the arbitrary correlation structure of overlapping equity indices on one
historical path. Both numbers are reported; neither is the whole story, and the report says so.

**Pooling is not monotonically stricter, and the first run of this script demonstrated it.** BH
compares each p-value against ``(rank / m) * alpha``, so a cell's q depends on how many *other*
small p-values share its ledger, not on ``m`` alone. `trend-ma`'s XLV `intermediate_cross_ema20_sma50`
(p = 0.0176) had q = 0.793 inside its own 45-test family and q = 0.458 in the pooled 130-test one --
it *improved*, because pooling surrounded it with four other cells whose p-values were smaller still.
The pooled ledger is therefore a different reference class, not a bigger penalty: it asks "how does
this rank among everything the study tried", which is the question a reader who commissioned all five
streams is actually asking. Where the two disagree, report both and say which question each answers.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(LAB / "lib"))

from quantlab import SCREEN_ALPHA  # noqa: E402
from app.backtest import scan as scan_mod  # noqa: E402


def load_primary_families() -> list[tuple[str, dict]]:
    """Every `*_primary.json` in `data/`, newest name order, with its parsed contents."""
    out = []
    for path in sorted((LAB / "data").glob("*_primary.json")):
        try:
            out.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
        except Exception as exc:
            print(f"  SKIPPED {path.name}: {type(exc).__name__}: {exc}")
    return out


def main() -> None:
    families = load_primary_families()
    if not families:
        print("No *_primary.json found in data/ -- nothing to pool yet.")
        return

    pooled: list[dict] = []
    print(f"Pooling {len(families)} primary families:\n")
    for name, payload in families:
        cells = payload.get("cells", [])
        print(f"  {name:<40} family={payload.get('family','?'):<20} cells={len(cells)}")
        for c in cells:
            pooled.append({**c, "source_file": name, "stream": payload.get("family", name)})

    q = scan_mod.benjamini_hochberg([c.get("p_value") for c in pooled])
    for c, qq in zip(pooled, q, strict=True):
        c["q_value_studywide"] = qq

    testable = [c for c in pooled if c.get("p_value") is not None]
    print(f"\nStudy-wide family: {len(pooled)} cells, {len(testable)} with a computable p-value.\n")

    # Survivors under each reading, and -- the interesting column -- the difference between them.
    within = [c for c in pooled if (c.get("q_value") is not None and c["q_value"] <= SCREEN_ALPHA)]
    across = [c for c in pooled if (c["q_value_studywide"] is not None and c["q_value_studywide"] <= SCREEN_ALPHA)]
    demoted = [c for c in within if c not in across]

    def line(c: dict) -> str:
        edge = c.get("edge")
        return (
            f"    {c['stream']:<18} {c['symbol']:<6} {c['idea']:<30} "
            f"h={c.get('horizon'):<3} edge={'n/a' if edge is None else f'{edge:+.3f}':<8} "
            f"n={c.get('n_independent'):<5} p={c.get('p_value'):.5f} "
            f"q_stream={c.get('q_value'):.4f} q_study={c['q_value_studywide']:.4f}"
        )

    print(f"Survived within-stream correction ({len(within)}):")
    for c in sorted(within, key=lambda c: c["p_value"]):
        print(line(c))
    print(f"\nSurvived study-wide correction ({len(across)}):")
    for c in sorted(across, key=lambda c: c["p_value"]):
        print(line(c))
    print(f"\nDemoted by pooling -- survived its own stream but not the study ({len(demoted)}):")
    for c in sorted(demoted, key=lambda c: c["p_value"]):
        print(line(c))

    # Ten smallest p-values regardless of survival: the report needs the near misses too, so a
    # reader can see whether the study was flat everywhere or clustered near the threshold.
    print("\nTen smallest p-values in the pooled family:")
    for c in sorted(testable, key=lambda c: c["p_value"])[:10]:
        print(line(c))

    out = {
        "pooled_family_size": len(pooled),
        "testable_cells": len(testable),
        "screen_alpha": SCREEN_ALPHA,
        "families": [
            {"file": n, "family": p.get("family"), "cells": len(p.get("cells", []))}
            for n, p in families
        ],
        "survived_within_stream": within,
        "survived_study_wide": across,
        "demoted_by_pooling": demoted,
        "cells": pooled,
    }
    path = LAB / "data" / "meta_correction.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
