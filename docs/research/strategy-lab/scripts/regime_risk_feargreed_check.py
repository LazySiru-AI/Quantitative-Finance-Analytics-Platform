"""regime-risk stream: is CNN Fear & Greed testable here at all? (note p.11, "[Macro] Fear & Greed /
VIX based investment strategies" -- the Fear & Greed half).

This is a static-analysis + citation script, not a backtest: it makes **no live network call** of its
own. `app.market.fear_greed.py` and `app.market.macro.py` were read directly (see report and this
script's assertions) to establish the architectural fact that matters: unlike `^VIX`, which is a
symbol in `app.market.store`'s bar cache and reachable via `quantlab.bars_frame("^VIX")`, Fear & Greed
has **no entry in `app.market.macro._SERIES_CATALOG`** -- the one dict `load_series` (the function
that answers "give me history for this id") can serve from. `build_snapshot`/`load_fear_greed` return
exactly one `FearGreed` object, "right now," rebuilt fresh (behind a 24h cache) on every call, never
appended to a growing archive.

This script asserts that fact directly against the running application (`_SERIES_CATALOG` has no F&G
key), then cites -- without re-fetching -- the one piece of empirical evidence already on disk in this
study: the macro stream's `data/macro_snapshot.json` (`app_macro_panel.fear_greed`), produced by
`scripts/macro_snapshot.py`'s own live call to `load_fear_greed`. That call happened to observe CNN's
raw endpoint returning `n_history_points=251` spanning `2025-08-11` to `2026-08-11` -- so the live CNN
payload *does* carry a trailing composite-score history via `CnnFearGreedProvider._parse_history`
(`FearGreed.history`). Three things keep that from making a Fear & Greed backtest testable in this
study:

1. It is never persisted -- `FearGreed.history` lives only inside the single object one call returns,
   and is discarded the moment that call returns; nothing appends it to the app's own store.
2. It is not reachable through `quantlab.bars_frame`, the harness this study is scoped to (BRIEF.md
   section 3), which reads `app.market.store` -- and F&G is absent from that store's registry.
3. Even taken as-is, ~251 daily points is about one year -- an order of magnitude short of the
   multi-decade, multi-regime history this study's independent-sample and BH-correction discipline
   needs (contrast `^VIX`'s multi-decade cached history, used in `regime_risk_vix.py`), and it is a
   single composite score CNN computes with an undocumented, non-reproducible weighting (see
   `fear_greed.py`'s own docstring on why the local fallback cannot even reproduce CNN's number from
   the same raw components).

Verdict: untestable in this study, for an architectural reason (no persisted/joinable series), not a
transient network failure -- and that is itself the finding BRIEF.md asks this stream to report.

Run from docs/research/strategy-lab/:
    ../../../.venv/Scripts/python.exe scripts/regime_risk_feargreed_check.py
"""

from __future__ import annotations

import json
import sys

sys.path.insert(0, "lib")

from quantlab import LAB, write  # noqa: E402

from app.market import macro as macro_mod  # noqa: E402


def main() -> None:
    catalog_keys = sorted(macro_mod._SERIES_CATALOG.keys())  # noqa: SLF001 -- inspecting, not mutating
    fear_greed_in_catalog = any("fear" in k.lower() or "greed" in k.lower() for k in catalog_keys)
    print(f"_SERIES_CATALOG has {len(catalog_keys)} ids: {catalog_keys}")
    print(f"Fear & Greed present in _SERIES_CATALOG: {fear_greed_in_catalog}")
    assert not fear_greed_in_catalog, (
        "unexpected: a Fear & Greed id appeared in _SERIES_CATALOG -- the untestability finding "
        "would need revisiting"
    )

    print(f"public API surface for Fear & Greed: {[n for n in macro_mod.__all__ if 'fear' in n.lower() or 'greed' in n.lower()]}")
    print("-> only `load_fear_greed` (current reading) and `build_snapshot`'s `.fear_greed` field "
          "(also current reading) exist; there is no `load_series('fear_greed', ...)` or equivalent.")

    citation_path = LAB / "data" / "macro_snapshot.json"
    citation = None
    if citation_path.exists():
        d = json.loads(citation_path.read_text(encoding="utf-8"))
        fg = d.get("app_macro_panel", {}).get("fear_greed")
        if fg is not None:
            citation = {
                "source_file": "data/macro_snapshot.json",
                "source_script": "scripts/macro_snapshot.py (macro stream, not this stream)",
                "observed_score": fg.get("score"),
                "observed_rating": fg.get("rating"),
                "observed_source": fg.get("source"),
                "observed_as_of": fg.get("as_of"),
                "n_history_points": fg.get("n_history_points"),
                "history_span": fg.get("history_span"),
            }
            print(f"\nCited from data/macro_snapshot.json (already on disk, not re-fetched here):")
            print(f"  source={fg.get('source')} (i.e. CNN was reachable at that run)")
            print(f"  n_history_points={fg.get('n_history_points')} span={fg.get('history_span')}")
        else:
            print("\nWARNING: data/macro_snapshot.json has no app_macro_panel.fear_greed node.")
    else:
        print("\nWARNING: data/macro_snapshot.json not found -- run macro_snapshot.py (macro stream) "
              "first for the empirical citation. The architectural finding above (no _SERIES_CATALOG "
              "entry) stands regardless.")

    result = {
        "series_catalog_keys": catalog_keys,
        "fear_greed_in_series_catalog": fear_greed_in_catalog,
        "public_fear_greed_api": [n for n in macro_mod.__all__ if "fear" in n.lower() or "greed" in n.lower()],
        "citation_from_macro_snapshot": citation,
        "verdict": "untestable: no persisted/joinable Fear & Greed series exists anywhere this "
        "study's harness can reach; a single call returns one current reading (plus a transient, "
        "unpersisted ~1y composite-score history straight from CNN's own payload when CNN answers, "
        "per the citation above -- too short and not store-backed regardless).",
    }
    write(result, "regime_risk_feargreed_check")
    print("\n=== regime_risk_feargreed_check.py complete ===")


if __name__ == "__main__":
    main()
