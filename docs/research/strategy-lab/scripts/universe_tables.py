"""Renders the markdown tables for `reports/universe.md` from `data/universe.json`.

Not a separate analysis -- every number here is already in the JSON that `scripts/universe.py`
wrote; this script only formats and ranks it, and the ranking formulas are written out in full so
they are auditable from this file, per the brief's "the ranking criterion stated in the table
caption" requirement. Output is printed to stdout and pasted into the report by hand.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# docs/research/strategy-lab/scripts/universe_tables.py -> scripts -> strategy-lab
LAB = Path(__file__).resolve().parents[1]
d = json.loads((LAB / "data" / "universe.json").read_text(encoding="utf-8"))

coverage = d["coverage"]
refused = d["refused"]
long_char = d["long_horizon_character"]
swing_char = d["swing_character"]
decay = d["leveraged_decay"]
near_dupes = d["near_duplicate_pairs_3y"]
MIN_STUDY = d["min_bars_for_study"]

LEVERAGED = set(d["candidates_declared"]["leveraged"].keys())


def pct(x, dp=1):
    return "n/a" if x is None else f"{x * 100:.{dp}f}%"


def num(x, dp=2):
    return "n/a" if x is None else f"{x:.{dp}f}"


# ---------------------------------------------------------------------------
# Part A: coverage table
# ---------------------------------------------------------------------------
print("## Part A coverage table\n")
print("| symbol | category | first | last | bars | status |")
print("|---|---|---|---|---|---|")
for cat, syms in d["candidates_declared"].items():
    for sym in syms:
        if sym in coverage:
            c = coverage[sym]
            status = "below 1000-bar study floor" if c["below_study_floor"] else "ok"
            print(f"| {sym} | {cat} | {c['first']} | {c['last']} | {c['bars']} | {status} |")
        elif sym in refused:
            r = refused[sym]
            err = r["error"].replace("\n", " ").replace("\r", " ").strip()
            print(f"| {sym} | {cat} | -- | -- | -- | REFUSED: {err[:120]} |")
print()

# ---------------------------------------------------------------------------
# Long-horizon table
# ---------------------------------------------------------------------------
print("\n## Long-horizon character (full history)\n")
print("| symbol | first bar | bars | CAGR full | CAGR 10y | vol (ann) | Sharpe(rf=0) | max DD | worst episode | recovery | current DD | %days>SMA200 |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
for sym, lc in long_char.items():
    cov = coverage[sym]
    we = lc["worst_episode"]
    we_str = "n/a" if we is None else f"{we['peak_date']}→{we['trough_date']}"
    rec = lc["worst_episode_recovery_days"]
    rec_str = "n/a" if rec is None else (f"{rec}d" if we and not we["still_underwater"] else f"{rec}d (?)")
    if we and we["still_underwater"]:
        rec_str = "still underwater"
    cur = lc["current_drawdown"]
    cur_str = "at high" if cur is None else f"{pct(cur['depth'])} ({cur['bars_underwater']}d)"
    print(
        f"| {sym} | {cov['first']} | {cov['bars']} | {pct(lc['cagr_full'])} | {pct(lc['cagr_10y'])} | "
        f"{pct(lc['vol_full'])} | {num(lc['sharpe_full'])} | {pct(lc['max_dd_full'])} | {we_str} | {rec_str} | "
        f"{cur_str} | {pct(lc['pct_days_above_sma200'])} |"
    )

# ---------------------------------------------------------------------------
# Swing table
# ---------------------------------------------------------------------------
print("\n\n## Swing character (full history vs trailing 3y)\n")
print("| symbol | ATR%/close (3y) | ATR%/close (full) | 20d RV (3y, ann) | avg\\|daily move\\| (3y) | autocorr 1d (3y) | VR-5 (3y) | VR-20 (3y) | VR-5 nblk | VR-20 nblk |")
print("|---|---|---|---|---|---|---|---|---|---|")
for sym, sc in swing_char.items():
    print(
        f"| {sym} | {pct(sc['atr_pct_mean_3y'], 2)} | {pct(sc['atr_pct_mean_full'], 2)} | "
        f"{pct(sc['realised_vol_20d_mean_3y'])} | {pct(sc['avg_abs_daily_move_3y'], 2)} | "
        f"{num(sc['autocorr_1d_3y'], 3)} | {num(sc['variance_ratio_5_3y'], 3)} | {num(sc['variance_ratio_20_3y'], 3)} | "
        f"{sc['variance_ratio_5_3y_nblocks']} | {sc['variance_ratio_20_3y_nblocks']} |"
    )

# ---------------------------------------------------------------------------
# Ranked table 1: swing suitability
# swing_score = average of two cross-sectional ranks:
#   rank_a: rank by atr_pct_mean_3y descending (bigger measured daily range = more room over a
#           5bps-each-way / 10bps-round-trip cost)
#   rank_b: rank by variance_ratio_20_3y ascending (further below 1.0 = more mean-reverting, the
#           behaviour this study's mean-reversion templates -- band_reversion, oversold_bounce --
#           are built to exploit)
# Only symbols with >= MIN_STUDY bars are ranked; leveraged products are flagged, not excluded.
# ---------------------------------------------------------------------------
eligible = {s: sc for s, sc in swing_char.items() if coverage[s]["bars"] >= MIN_STUDY}
by_atr = sorted(eligible, key=lambda s: -(eligible[s]["atr_pct_mean_3y"] or -1))
rank_a = {s: i + 1 for i, s in enumerate(by_atr)}
by_vr20 = sorted(eligible, key=lambda s: (eligible[s]["variance_ratio_20_3y"] if eligible[s]["variance_ratio_20_3y"] is not None else 999))
rank_b = {s: i + 1 for i, s in enumerate(by_vr20)}
composite = {s: (rank_a[s] + rank_b[s]) / 2 for s in eligible}
ranked_swing = sorted(eligible, key=lambda s: composite[s])

print("\n\n## RANKED TABLE 1 -- short-term swing character")
print(
    "Ranking criterion: composite = average of (rank by trailing-3y mean ATR%/close, descending -- "
    "more measured daily range relative to the 5bps-each-way cost) and (rank by trailing-3y 20-day "
    "variance ratio, ascending -- further below 1.0 is more mean-reverting). Restricted to symbols "
    f"with >= {MIN_STUDY} bars. Leveraged products are flagged (*) -- their large ATR%% is amplified "
    "range, not amplified edge; see Part C.\n")
print("| rank | symbol | ATR%(3y) | rank_atr | VR-20(3y) | rank_vr | composite |")
print("|---|---|---|---|---|---|---|")
for i, s in enumerate(ranked_swing, 1):
    flag = " *" if s in LEVERAGED else ""
    print(f"| {i} | {s}{flag} | {pct(eligible[s]['atr_pct_mean_3y'],2)} | {rank_a[s]} | {num(eligible[s]['variance_ratio_20_3y'],3)} | {rank_b[s]} | {composite[s]:.1f} |")

# ---------------------------------------------------------------------------
# Ranked table 2: long-term holding character
# composite = average of three cross-sectional ranks:
#   rank_d: rank by max_dd_full descending (least negative / shallowest drawdown first)
#   rank_e: rank by worst-episode recovery days ascending (still-underwater treated as worst = last)
#   rank_f: rank by full-history CAGR descending
# ---------------------------------------------------------------------------
eligible2 = {s: lc for s, lc in long_char.items() if coverage[s]["bars"] >= MIN_STUDY}
by_dd = sorted(eligible2, key=lambda s: -(eligible2[s]["max_dd_full"] if eligible2[s]["max_dd_full"] is not None else -1))
rank_d = {s: i + 1 for i, s in enumerate(by_dd)}


def recovery_key(s):
    we = eligible2[s]["worst_episode"]
    rec = eligible2[s]["worst_episode_recovery_days"]
    if we is None:
        return 10**9
    if we["still_underwater"] or rec is None:
        return 10**8
    return rec


by_rec = sorted(eligible2, key=recovery_key)
rank_e = {s: i + 1 for i, s in enumerate(by_rec)}
by_cagr = sorted(eligible2, key=lambda s: -(eligible2[s]["cagr_full"] if eligible2[s]["cagr_full"] is not None else -1))
rank_f = {s: i + 1 for i, s in enumerate(by_cagr)}
composite2 = {s: (rank_d[s] + rank_e[s] + rank_f[s]) / 3 for s in eligible2}
ranked_long = sorted(eligible2, key=lambda s: composite2[s])

print("\n\n## RANKED TABLE 2 -- long-term holding character")
print(
    "Ranking criterion: composite = average of (rank by full-history max drawdown, descending -- "
    "shallowest first), (rank by the worst episode's recovery time in days, ascending -- fastest "
    "first; a still-underwater episode ranks last), and (rank by full-history CAGR, descending). "
    f"Restricted to symbols with >= {MIN_STUDY} bars. Leveraged products flagged (*) -- see Part C.\n")
print("| rank | symbol | max DD | rank_dd | recovery | rank_rec | CAGR full | rank_cagr | composite |")
print("|---|---|---|---|---|---|---|---|---|")
for i, s in enumerate(ranked_long, 1):
    flag = " *" if s in LEVERAGED else ""
    lc = eligible2[s]
    we = lc["worst_episode"]
    rec_str = "still underwater" if (we and we["still_underwater"]) else (f"{lc['worst_episode_recovery_days']}d" if lc['worst_episode_recovery_days'] is not None else "n/a")
    print(f"| {i} | {s}{flag} | {pct(lc['max_dd_full'])} | {rank_d[s]} | {rec_str} | {rank_e[s]} | {pct(lc['cagr_full'])} | {rank_f[s]} | {composite2[s]:.2f} |")

# ---------------------------------------------------------------------------
# Leveraged decay
# ---------------------------------------------------------------------------
print("\n\n## Leveraged decay detail\n")
for sym, dd in decay.items():
    print(f"### {sym}  (factor {dd.get('factor')}x, in app registry={dd.get('in_app_registry')}, app underlying={dd.get('app_registry_underlying')})")
    for label, w in dd.get("windows", {}).items():
        if "skipped" in w:
            print(f"  {label}: skipped -- {w['skipped']}")
        else:
            print(
                f"  {label}: {w['start']}→{w['end']}  lev={w['leveraged_return']*100:+.1f}%  "
                f"underlying={w['underlying_return']*100:+.1f}%  k*underlying={w['k_times_underlying']*100:+.1f}%  "
                f"gap={w['gap_vs_k_times_underlying']*100:+.1f}pp"
            )
    ep = dd.get("worst_drawdown_episode")
    if ep:
        print(
            f"  worst episode {ep['peak_date']}→{ep['trough_date']}: lev close-close={num(ep['leveraged_depth_close_to_close'],3)} "
            f"(profile depth {num(ep['leveraged_profile_depth'],3)})  underlying={num(ep['underlying_return_same_dates'],3)}  "
            f"k*underlying={num(ep['k_times_underlying'],3)}  gap={num(ep['gap_vs_k_times_underlying'],3)}"
        )
    print()

# ---------------------------------------------------------------------------
# Near-duplicate pairs
# ---------------------------------------------------------------------------
print("\n## Near-duplicate pairs (|corr| > 0.90, trailing 3y daily log returns)\n")
print(f"n={len(near_dupes)} pairs, n_rows={d['correlation_n_rows']}\n")
print("| a | b | corr |")
print("|---|---|---|")
for p in near_dupes:
    print(f"| {p['a']} | {p['b']} | {p['corr']:+.3f} |")
