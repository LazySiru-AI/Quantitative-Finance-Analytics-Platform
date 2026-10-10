"""Round 33 Phase A — the real, pre-registered selector bake-off run.

Implements the §5 regime reconstruction and §6 walk-forward windows from
`strategy-program/ROUND-33-PLAN.md`, drives the frozen grader
(`app.discovery.selector_bakeoff`) over every trading session, and applies the §7
mechanical gate to name the promoted selector. Writes a JSON + markdown report under
`data/rounds/r33-<yyyy-mm>/`.

Run from the repo root with the repo venv:
    .venv/Scripts/python.exe strategy-program/tools/round33_bakeoff.py [--smoke]

`--smoke` runs a tiny recent window across all eight selectors to validate the wiring
and measure per-session cost before the full multi-year run.

Not investment advice. The regime instrument is the three-signal reconstruction §5
freezes (spy_trend, realized_vol, macro_2s10s; fear_greed abstains for the whole
replay), disclosed as a different instrument from the live four-signal desk.
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import statistics
import time
from pathlib import Path

import pandas as pd

from app.config import Settings
from app.discovery.selector_bakeoff import (
    DEFAULT_HORIZON_DAYS,
    SelectorGrade,
    _benjamini_hochberg,
    _grade_trials,
    _replay_one_selector,
)
from app.discovery.stats import stationary_bootstrap_p
from app.discovery.workflow_selectors import SELECTOR_IDS
from app.market import store as market_store
from app.market.models import Interval
from app.workflow import pipeline as pipeline_mod
from app.workflow import regime as regime_mod
from app.workflow.regime import RegimeMarketData

CONTROLS: tuple[str, ...] = ("control_card_universe", "control_week_rotation")
ENTRANTS: tuple[str, ...] = tuple(s for s in SELECTOR_IDS if s not in CONTROLS)

_BLOCK = 21.0
_SEED = 33
_REGIME_MAP_PATH = Path("backend/app/workflow/regime_map.json")
_T10Y2Y_PATH = Path("data/round33/t10y2y.json")

# §6 walk-forward windows, frozen.
_BURN_IN_START = dt.date(2003, 1, 2)
_BURN_IN_SESSIONS = 500
_IN_SAMPLE_END = dt.date(2017, 12, 29)
_HOLDOUT_START = dt.date(2018, 1, 2)
_HOLDOUT_END = dt.date(2026, 8, 18)


class Recon:
    """The §5 regime reconstruction and the session calendar, all off local disk."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        spy = market_store.read_frame("SPY", Interval.DAY, settings=settings)
        if spy is None or spy.empty:
            raise SystemExit("SPY daily bars are not in the store; cannot run Phase A.")
        spy = spy.copy()
        spy["d"] = spy["ts"].dt.date
        self._spy = spy
        self._session_dates: list[dt.date] = list(spy["d"])

        pts = json.loads(_T10Y2Y_PATH.read_text())
        self._t10_dates: list[dt.date] = [dt.date.fromisoformat(d) for d, _ in pts]
        self._t10_vals: list[float] = [float(v) for _, v in pts]

        self._regime_map: dict[str, list[str]] = {
            k: v for k, v in json.loads(_REGIME_MAP_PATH.read_text()).items()
            if isinstance(v, list)
        }
        self._regime_cache: dict[dt.date, str] = {}
        self._card_universe: dict[str, tuple[str, ...]] = {}

    # -- session calendar ---------------------------------------------------
    def sessions_in(self, start: dt.date, end: dt.date) -> tuple[dt.date, ...]:
        return tuple(d for d in self._session_dates if start <= d <= end)

    def in_sample_start(self) -> dt.date:
        after = [d for d in self._session_dates if d >= _BURN_IN_START]
        if len(after) <= _BURN_IN_SESSIONS:
            raise SystemExit("Not enough sessions after burn-in start for an in-sample slice.")
        return after[_BURN_IN_SESSIONS]  # session 501 (0-indexed 500)

    # -- §5 regime reconstruction ------------------------------------------
    def _macro_2s10s(self, as_of: dt.date) -> float | None:
        # Release-lagged by one session: the latest observation strictly before as_of.
        i = bisect.bisect_left(self._t10_dates, as_of)
        return self._t10_vals[i - 1] if i > 0 else None

    def _spy_bars_through(self, as_of: dt.date) -> pd.DataFrame | None:
        sub = self._spy[self._spy["d"] <= as_of]
        return sub if not sub.empty else None

    def regime_for(self, settings: Settings, as_of: dt.date) -> str:
        cached = self._regime_cache.get(as_of)
        if cached is not None:
            return cached
        data = RegimeMarketData(
            spy_bars=self._spy_bars_through(as_of),
            fear_greed_components=(),  # §5: abstains for the whole replay
            macro_2s10s_pct=self._macro_2s10s(as_of),
        )
        label = regime_mod.classify(settings=settings, as_of=as_of, market=data).label
        self._regime_cache[as_of] = label
        return label

    def card_universe_for(self, as_of: dt.date) -> tuple[str, ...]:
        label = self.regime_for(self.settings, as_of)
        ids = self._regime_map.get(label, [])
        if not ids:
            return ()
        agent_id = ids[0]  # §7: index 0, no production fallback
        if agent_id not in self._card_universe:
            card = pipeline_mod._load_card(agent_id, settings=self.settings)
            self._card_universe[agent_id] = tuple(card.universe) if card is not None else ()
        return self._card_universe[agent_id]


# One Recon per worker process, built once by the pool initializer and reused across
# every selector that worker grades (rebuilding it per task would re-read SPY + T10Y2Y each time).
_WORKER: dict[str, Recon] = {}


def _init_worker() -> None:
    _WORKER["recon"] = Recon(Settings())


def _grade_one_selector(
    sid: str, dates: tuple[dt.date, ...]
) -> tuple[str, SelectorGrade, list[tuple[dt.date, float | None]]]:
    """Replay and grade ONE selector over `dates` (a whole slice, so hysteresis is intact).

    Runs in a worker process; parallel-by-selector is exact — each selector's date sequence and
    prior_picks carry is identical to the serial path, and the only cross-selector step (BH across
    p-values) happens back in the parent after every selector returns.
    """
    recon = _WORKER["recon"]
    trials = _replay_one_selector(
        sid,
        dates,
        settings=recon.settings,
        regime_for=recon.regime_for,
        card_universe_for=recon.card_universe_for,
        horizon_days=DEFAULT_HORIZON_DAYS,
    )
    return sid, _grade_trials(sid, trials), [(t.as_of, t.ic) for t in trials]


def _replay_slice(
    dates: tuple[dt.date, ...], *, workers: int
) -> tuple[dict[str, SelectorGrade], dict[str, list[tuple[dt.date, float | None]]]]:
    """Grade every selector over `dates` in parallel (one process per selector), keeping the
    per-session IC series for §7. Identical results to a serial replay."""
    from concurrent.futures import ProcessPoolExecutor
    from dataclasses import replace

    grades: dict[str, SelectorGrade] = {}
    ic_series: dict[str, list[tuple[dt.date, float | None]]] = {}
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        futures = [pool.submit(_grade_one_selector, sid, dates) for sid in SELECTOR_IDS]
        for fut in futures:
            sid, grade, ics = fut.result()
            grades[sid] = grade
            ic_series[sid] = ics

    p_values = {sid: grades[sid].bootstrap_p for sid in SELECTOR_IDS}
    q_values = _benjamini_hochberg(p_values, m=len(SELECTOR_IDS))
    grades = {sid: replace(grades[sid], bh_q=q_values[sid]) for sid in SELECTOR_IDS}
    return grades, ic_series


def _paired_worse_than(
    entrant: str, control: str, ic_series: dict[str, list[tuple[dt.date, float | None]]]
) -> bool:
    """§7 branch (2): is `entrant` statistically WORSE than `control`?

    One-sided from the two-sided stationary bootstrap: reject "equal" at p<=0.10 AND the
    observed paired mean difference is negative (entrant below control).
    """
    e = dict(ic_series[entrant])
    c = dict(ic_series[control])
    diffs = [e[d] - c[d] for d in e if e[d] is not None and c.get(d) is not None]
    if len(diffs) < 3:
        return False
    mean_d = statistics.fmean(diffs)
    p = stationary_bootstrap_p(diffs, block=_BLOCK, seed=_SEED)
    return p is not None and p <= 0.10 and mean_d < 0.0


def _tiebreak_key(sid: str, grades: dict[str, SelectorGrade]) -> tuple[float, str]:
    g = grades[sid]
    dollars = g.implied_dollars_per_day if g.implied_dollars_per_day is not None else float("inf")
    return (dollars, sid)


def apply_gate(
    grades: dict[str, SelectorGrade], ic_series: dict[str, list[tuple[dt.date, float | None]]]
) -> tuple[str, str, str]:
    """The §7 mechanical rule on the in-sample slice. Returns (winner, branch, why)."""
    ctrl_mean = {c: grades[c].mean_ic for c in CONTROLS}

    # Branch (1): a real IC edge over both controls.
    branch1 = [
        e for e in ENTRANTS
        if grades[e].bootstrap_p is not None and grades[e].bootstrap_p <= 0.10
        and grades[e].mean_ic is not None
        and all(ctrl_mean[c] is not None and grades[e].mean_ic > ctrl_mean[c] for c in CONTROLS)
    ]
    if branch1:
        winner = min(
            branch1,
            key=lambda e: (-(grades[e].mean_ic or float("-inf")), *_tiebreak_key(e, grades)),
        )
        return winner, "1", (
            f"cleared bootstrap_p<=0.10 (p={grades[winner].bootstrap_p:.3f}) and beat both "
            f"controls' mean IC; highest mean IC among such entrants ({grades[winner].mean_ic:+.4f})."
        )

    # Branch (2): lowest-churn entrant not statistically worse than either control.
    eligible = [
        e for e in ENTRANTS
        if not _paired_worse_than(e, CONTROLS[0], ic_series)
        and not _paired_worse_than(e, CONTROLS[1], ic_series)
    ]
    pool = eligible if eligible else list(CONTROLS)

    def churn_key(sid: str) -> tuple[float, float, str]:
        g = grades[sid]
        churn = float(g.mean_churn) if g.mean_churn is not None else float("inf")
        return (churn, *_tiebreak_key(sid, grades))

    winner = min(pool, key=churn_key)
    note = "no entrant cleared both controls; controls compared on churn" if not eligible else (
        f"{len(eligible)} entrant(s) not worse than either control; lowest mean churn wins"
    )
    churn_str = "n/a" if grades[winner].mean_churn is None else f"{float(grades[winner].mean_churn):.3f}"
    return winner, "2", f"{note}; winner mean churn {churn_str}."


def _grade_row(g: SelectorGrade) -> dict[str, object]:
    return {
        "selector_id": g.selector_id,
        "n_dates": g.n_dates,
        "n_scored": g.n_scored,
        "mean_ic": g.mean_ic,
        "bootstrap_p": g.bootstrap_p,
        "bh_q": g.bh_q,
        "hit_rate": g.hit_rate,
        "binomial_p": g.binomial_p,
        "mean_churn": None if g.mean_churn is None else float(g.mean_churn),
        "implied_dollars_per_day": g.implied_dollars_per_day,
    }


def _fmt_table(grades: dict[str, SelectorGrade]) -> str:
    head = "| selector | n | mean IC | boot p | BH q | hit | churn | $/day |\n|---|--:|--:|--:|--:|--:|--:|--:|"
    rows = []
    for sid in SELECTOR_IDS:
        g = grades[sid]
        def f(x: float | None, nd: int = 4) -> str:
            return "—" if x is None else f"{x:.{nd}f}"
        churn = "—" if g.mean_churn is None else f"{float(g.mean_churn):.3f}"
        rows.append(
            f"| {sid} | {g.n_scored} | {f(g.mean_ic)} | {f(g.bootstrap_p, 3)} | {f(g.bh_q, 3)} | "
            f"{f(g.hit_rate, 3)} | {churn} | {f(g.implied_dollars_per_day, 2)} |"
        )
    return head + "\n" + "\n".join(rows)


def main() -> None:
    import os

    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="tiny recent window, timing only")
    parser.add_argument("--workers", type=int, default=min(8, (os.cpu_count() or 2)),
                        help="parallel worker processes (default: min(8, cpu count))")
    args = parser.parse_args()

    settings = Settings()
    recon = Recon(settings)
    workers = max(1, args.workers)

    if args.smoke:
        sessions = recon.sessions_in(dt.date(2016, 10, 1), dt.date(2016, 12, 31))
        t0 = time.time()
        grades, _ = _replay_slice(sessions, workers=workers)
        dt_s = time.time() - t0
        n = len(sessions)
        print(f"smoke: {n} sessions x {len(SELECTOR_IDS)} selectors in {dt_s:.1f}s "
              f"({dt_s / max(n, 1):.3f}s/session, {workers} workers)")
        print(_fmt_table(grades))
        return

    in_start = recon.in_sample_start()
    in_dates = recon.sessions_in(in_start, _IN_SAMPLE_END)
    out_dates = recon.sessions_in(_HOLDOUT_START, _HOLDOUT_END)
    print(f"in-sample: {in_start} .. {_IN_SAMPLE_END}  ({len(in_dates)} sessions)")
    print(f"held-out:  {_HOLDOUT_START} .. {_HOLDOUT_END}  ({len(out_dates)} sessions)")
    print(f"workers: {workers}", flush=True)

    out_dir = Path("data/rounds/r33-2026-08")
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    in_grades, in_ic = _replay_slice(in_dates, workers=workers)
    print(f"in-sample graded in {(time.time() - t0) / 60:.1f} min", flush=True)
    winner, branch, why = apply_gate(in_grades, in_ic)

    # Checkpoint: the §7 gate decision depends on the in-sample slice ALONE, so persist it (and the
    # in-sample table) before the multi-hour held-out replay — a holdout crash must not lose the
    # promotion decision this whole run exists to produce.
    (out_dir / "phase-a-in-sample.json").write_text(json.dumps({
        "in_sample": {"start": in_start.isoformat(), "end": _IN_SAMPLE_END.isoformat(),
                      "sessions": len(in_dates),
                      "grades": [_grade_row(in_grades[s]) for s in SELECTOR_IDS]},
        "gate": {"promoted_selector": winner, "branch": branch, "why": why},
    }, indent=2), encoding="utf-8")
    print(f"CHECKPOINT: promoted={winner} (branch {branch}) - {why}", flush=True)

    t1 = time.time()
    out_grades, _ = _replay_slice(out_dates, workers=workers)
    print(f"held-out graded in {(time.time() - t1) / 60:.1f} min", flush=True)
    result = {
        "round": 33,
        "regime_instrument": "3-signal (spy_trend, realized_vol, macro_2s10s); fear_greed abstains",
        "in_sample": {"start": in_start.isoformat(), "end": _IN_SAMPLE_END.isoformat(),
                      "sessions": len(in_dates), "grades": [_grade_row(in_grades[s]) for s in SELECTOR_IDS]},
        "holdout": {"start": _HOLDOUT_START.isoformat(), "end": _HOLDOUT_END.isoformat(),
                    "sessions": len(out_dates), "grades": [_grade_row(out_grades[s]) for s in SELECTOR_IDS]},
        "gate": {"promoted_selector": winner, "branch": branch, "why": why},
    }
    (out_dir / "phase-a-bakeoff.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

    report = (
        f"# Round 33 Phase A — selector bake-off results\n\n"
        f"Regime instrument: 3-signal reconstruction (§5); fear_greed abstains for the whole replay.\n\n"
        f"## In-sample ({in_start} .. {_IN_SAMPLE_END}, {len(in_dates)} sessions)\n\n"
        f"{_fmt_table(in_grades)}\n\n"
        f"## Held-out ({_HOLDOUT_START} .. {_HOLDOUT_END}, {len(out_dates)} sessions)\n\n"
        f"{_fmt_table(out_grades)}\n\n"
        f"## §7 gate\n\n**Promoted selector: `{winner}`** (branch {branch}).\n\n{why}\n"
    )
    (out_dir / "PHASE-A-REPORT.md").write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\nwrote {out_dir / 'phase-a-bakeoff.json'} and {out_dir / 'PHASE-A-REPORT.md'}")


if __name__ == "__main__":
    main()
