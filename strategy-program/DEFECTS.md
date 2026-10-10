# Defects found by the program

Defects in the application's backtest engine, found while running competition rounds.

**The program never fixes application source during a round.** A round is a measurement, and changing
the instrument partway through invalidates it. A defect found mid-round is recorded here with a
reproduction, and worked around in `strategy-program/tools/score.py` so the round can be scored
correctly without touching `backend/`.

**Between rounds, the fix is taken properly.** D1 and D2 below were found during round 1, worked
around for round 1's scoring, and fixed in the engine before round 2 ran.

Where a workaround exists it is **kept after the fix**, not deleted. `score.py` derives its return
from `ending_equity`/`starting_equity` and its exposure from the trade log — quantities that are
correct under both the old and the new engine. That is what keeps round 1's numbers comparable with
round 2's for the two-consecutive-rounds promotion rule, and it leaves an independent check against
the engine's own figures.

---

## D1 — `total_return` is rebased to the first session's close, not to starting equity

**Found:** round 1, 2026-08-20, by an agent reconciling `total_return` against `ending_equity`.
**Status:** **FIXED** between rounds 1 and 2. The workaround in `score.py` is retained deliberately —
it computes the same quantity from `ending_equity`/`starting_equity`, which is correct under both the
old and new engine, so round-1 and round-2 numbers stay comparable for the two-round promotion rule.
**Severity:** material. It changed the sign of reported returns for cards that fill on session one.

`app.backtest.metrics.compute` computes:

```python
total_return = jsonable_float(float(equity[-1] / equity[0] - 1.0))
```

and its docstring states the contract: *"Summarise one equity curve, `equity[0]` normalised to
`1.0`."*

`app.tournament.runner` builds the array it passes:

```python
equity_array = np.array([float(e / starting_equity) for e in equity_curve], dtype=np.float64)
```

`equity_curve[0]` is the mark at the **first session's close**, which differs from `starting_equity`
whenever a fill happened on that session. Dividing every element by the constant `starting_equity`
does not satisfy `compute`'s contract — and, because the constant cancels out of the ratio
`equity[-1] / equity[0]`, it has no effect on `total_return` at all. The result is rebased to
`equity_curve[0]`.

The runner's own comment on those lines says this must not happen:

> Normalised to `starting_equity`, not to `equity_curve[0]`: the first session's own decision was
> made on the design window's last close, so a fill -- and therefore a mark different from
> `starting_equity` -- can legitimately happen on the very first session. Rebasing to
> `equity_curve[0]` instead would silently hide exactly that first day's effect from `total_return`.

The intent is correct and stated plainly. The code does the opposite.

**Reproduction.** Across round 1's three complete windows, 14 card-window pairs differ from
`ending_equity / starting_equity - 1` by more than 0.05pp:

| card | window | reported | true | gap |
|---|---|---|---|---|
| A1-alpha-order | covid | −0.972% | **+1.099%** | +2.071 |
| A2-cash-headroom | covid | +4.356% | +6.227% | +1.871 |
| A-rotation | covid | −0.652% | **+0.465%** | +1.117 |
| A4-tight-stop | covid | −2.169% | −1.069% | +1.100 |
| A3-no-target | covid | −3.460% | −2.374% | +1.085 |
| A2-cash-headroom | bear-2022 | −29.258% | −28.579% | +0.679 |
| A1-alpha-order | bear-2022 | −36.231% | −35.651% | +0.580 |
| c04-riskmanaged | gfc | +0.803% | +1.381% | +0.578 |
| A-rotation | bear-2022 | −33.795% | −33.275% | +0.521 |
| A3-no-target | bear-2022 | −33.795% | −33.275% | +0.521 |
| A4-tight-stop | bear-2022 | −34.131% | −33.613% | +0.518 |
| c04-riskmanaged | bear-2022 | −6.231% | −6.583% | −0.352 |
| c04-riskmanaged | covid | −1.503% | −1.322% | +0.181 |
| H-trend-diversified | bear-2022 | −3.206% | −3.111% | +0.096 |

Two of these change sign. The A-family is hit hardest because a rotation card that is always looking
for a fill generally gets one on session one.

**Scope.** Only `total_return` and `cagr` are affected. `max_drawdown`, `volatility` and the per-bar
returns series are computed from ratios in which the constant cancels harmlessly, and are correct as
reported — though `max_drawdown` is measured from `equity_curve[0]` and so cannot see a drawdown
that began on the first session.

**This affects the previous tournament's published numbers too**, by the same mechanism, and to a
degree that depends on each card's first-session fill.

**Fix as taken:** `runner.py` now prepends the starting-equity point so the curve genuinely begins
at 1.0, with a matching leading `False` in `in_position`. `compute` was left alone — its contract is
reasonable and `app/backtest/strategy.py` already satisfies it.

Three consequences, all intended and none of them cosmetic. `max_drawdown` can now see a drawdown
that began on session one, which it structurally could not before. `sharpe`, `sortino` and
`volatility` gain one genuine return observation — the first session's own move — that was previously
invisible to them. And the alignment point silently entered `exposure`'s denominator, turning a card
held on all 250 sessions into 250/251; that is rescaled back out in `_undilute_exposure`, pinned by a
test asserting `exposure * sessions` is a whole number.

A regression test was added first and confirmed to fail against the unfixed code
(`AssertionError: assert Decimal('0.0') == Decimal('0.10000000000000009')`). The absence of any such
test is what let this ship: the one test touching the path used a card that never fills, where the
buggy and correct formulas coincide.

---

## D2 — `exposure` measures session presence, not capital at risk

**Found:** round 1, 2026-08-20, chasing a 52-point gap between a card's author's own estimate and the
runner's figure.
**Status:** **FIXED** between rounds 1 and 2 by adding `AgentResult.capital_exposure` alongside the
existing field rather than redefining it — `report_pdf.py` renders `exposure` and it is a real
measurement, just not the one the name suggests. `score.py`'s trade-log reconstruction is retained as
an independent check; the two should agree closely, and a divergence means one of them is wrong.

`runner.py` records, per session:

```python
in_position_flags.append(bool(open_lots))
```

and `metrics.py` reduces it:

```python
exposure=jsonable_float(float(np.mean(in_position))) if in_position.size else None,
```

So `exposure` is **the fraction of sessions on which the card held at least one position**. A card
with four slots that holds a single slot on every session reports `exposure = 1.0` with a quarter of
its capital deployed.

This is a defensible measurement of a real quantity. It is simply not the quantity the name
suggests, and it is actively misleading in any calculation that multiplies it by a benchmark return.

**Reproduction.** `c04-riskmanaged` in the `gfc` window reports `exposure = 0.9719`. Its capital-
weighted exposure, reconstructed from its own trade log, is **43.83%** — matching its author's
independent design-time estimate of ~45%. Using the raw figure in
`total_return - exposure * benchmark_return` against a −56.23% benchmark produced an adjusted excess
of **+55.45%**; the capital-weighted figure gives **+25.45%**.

`H-trend-diversified` in `bear-2022` moves from **+17.32% to +0.71%** under the same correction: its
"82% exposure" was one small commodity position held for a long time, not a filled book.
`c03-breakout` in `gfc` changes sign, from +13.43% to −1.71%.

**Workaround.** `score.py` reconstructs `capital_exposure` from the trade log as
`Σ(quantity × entry_price × bars_held) / (sessions × starting_equity)` and uses it for
`adjusted_excess`, reporting the raw figure as `session_exposure` beside it.

**Fix as taken:** `AgentResult.capital_exposure` is computed inside the engine, where the
per-session open-lot values are known exactly, as the mean over sessions of summed entry notional
over starting equity. The existing `exposure` keeps its name and meaning, with a docstring that now
says plainly it is session presence.

---

## D3 — a concurrent reader is reported as a card failure

**Found:** during round 1 setup, when a DSL probe run alongside a backtest killed a card.
**Status:** **FIXED.** `store.read_frame` and the module's two other pure-read call sites now use an
in-memory DuckDB connection, which touches the physical store file not at all. Verified: three
concurrent processes reading through `read_frame` all succeed, where before any two collided. The
tournament runner reads through this path, so the failure mode is gone at source rather than mitigated
by procedure.

The bar store is a single DuckDB file and `app.market.store.read_frame` opens it **read-write** even
though it only reads. A second process touching it raises an `IOException` which the tournament
runner catches per-card, records as `FAILED`, and walks past.

Walking past a failed card is correct — losing twenty-five completed runs because the twenty-sixth
raised would be a poor trade. But it means store contention produces a report that **looks complete
and is silently missing cards**, and the failure text resembles an honest guard failure closely
enough to be missed.

**Reproduction.** Running any script that opens `analytics.duckdb` without `read_only=True` during a
tournament run. Observed: `B-momentum: FAILED IOException: ... The process cannot access the file
because it is being used by another process.`

Verified as part of the same investigation: **concurrent `read_only=True` connections are safe**, and
any number of readers may share the store. It is only the default read-write connection that
collides.

**It recurred in round 2, and cost the whole first attempt.** A run was launched detached with
`nohup ... &`, which meant no completion notification and no log to watch. Realising that, the run
was killed with `taskkill /IM python.exe` — which killed the *python* process but not the **bash
loop driving it**. The loop simply moved on and spawned python for the next window. A second run was
then started, and the two fought over the store for five consecutive windows: **135 card-runs, every
one failing with this IOException, zero results written.**

Two things made it worse than it should have been. The reconciliation line reported
`0 run files, 27 FAILED lines` for each window, which is exactly what a legitimately ineligible field
would look like at a glance. And the per-card message is formatted identically to an honest
`GuardFailed`, so scrolling the log gives no visual cue that anything is wrong. Only
`Get-CimInstance Win32_Process` naming two live `run_round.sh` processes made the cause visible.

**Mitigation.** `run_round.sh` now **refuses to start** when any `app.tournament` process is already
running, which converts a silent five-window loss into an immediate error on line one. It also still
reconciles run-file counts against `FAILED` lines after every window, and the protocol requires
research reads to pass `read_only=True`.

Two operational rules earned the hard way: never launch a round detached — use a tracked background
task so there is a log and a completion signal — and never kill a run by killing `python.exe`, because
the shell loop above it will just start another. Kill the driving process, then verify with
`Get-CimInstance` that nothing named `app.tournament` survives.

This is all procedure, and procedure is weaker than a fix.

**Fix as taken — and it was not `read_only=True`.** Two things came out of auditing the module rather
than patching the one named line.

First, **three call sites had the defect, not one**: `read_frame`, `_read_many` (behind `latest_bars`),
and `sync_bars`' pre-fetch read. Only `sync_bars`' merge step genuinely writes, and it still opens
read-write.

Second, `read_only=True` would have been the wrong fix anyway. `duck.read_bars` runs `read_parquet()`
directly and `duck.write_bars` runs `COPY ... TO` directly — **neither creates or reads a persistent
table, so the `analytics.duckdb` catalog is vestigial for this module**. A read-only connection would
also refuse to open a store that has never been synced, which is a case the existing tests exercise.
The three read paths now use an **in-memory** connection: it needs neither the file to exist nor
coordination with anything holding it, because it never touches the file. `app.tournament.roster`
already did this, on the reasoning that "a read path has no business creating it."

**Verified.** Three concurrent processes reading through `store.read_frame` all succeed. Re-running two
cards through the tournament produced **bit-identical** results to the committed round-2 output — same
returns, same trade counts, same capital exposure — so the change is behaviour-preserving. Full suite:
2197 passed, 1 skipped. Two regression tests were added and confirmed to fail against the unfixed code:
one holds a real read-only connection while calling `read_frame`, the other asserts a read never
creates `analytics.duckdb` as a side effect.

A third candidate test was written and then **discarded for being misleading** — holding a second
read-write connection *in the same process* passes even against the unfixed code, because DuckDB shares
one database instance across same-config connections within a process. It never exercised the file
lock. Worth recording, because it is the test one would naturally write first.

A prior study in this repository lost four symbols to this defect and reported it; round 1 lost a card;
round 2 lost an entire first attempt. It is now closed.

---

## D4 — indicator values depend on an arbitrary 400-day lookback, and it can flip a signal

**Found:** 2026-08-21, while trying to make the rule engine faster. Not by reading the code — by
attempting an optimisation and having a byte-for-byte reproduction of every committed round refuse
it.
**Status:** **FIXED**, and every round restated. `AsOfMarket.history` gained
`lookback_days=None`, meaning every stored bar up to `as_of`; `runner._rule_fires` and the paper
desk's signal evaluation both pass it, so a recursive indicator is now seeded from the start of the
data rather than from an arbitrary constant. See "Fix as taken" at the end of this entry.
**Severity:** low in magnitude, awkward in kind. It moves crossover timing by at most a session, on
knife-edge crossings only — but it means every backtest in this repository is a function of a
constant nobody chose deliberately.

`app.tournament.runner._rule_fires` evaluates a card's rule like this:

```python
bars = market.history(symbol)          # AsOfMarket.history(..., lookback_days=400)
signal = rule_evaluate.evaluate(tree, bars, interval=Interval.DAY)
return bool(signal.fillna(False).iloc[-1])
```

`lookback_days=400` is a **default parameter value**, and it is load-bearing in a way nothing
documents. Roughly 275 trading bars reach the evaluation. For a windowed indicator (`sma`, and the
rolling parts of `atr`) that is harmless: 275 bars is more than `sma(200)` needs and the value is
exact. For a **recursive** one it is not. `ema` and Wilder `rsi` are exponential recursions whose
value at any date carries a decaying contribution from wherever the series began, so an `ema(50)`
seeded 275 bars back differs from the same `ema(50)` seeded on the full history by a relative error
of order `(1 - 2/51)**275`, about **1.8e-5**.

That is small, and it is not always small enough.

**Reproduction.** Evaluating each card's rule once over a long frame and indexing per session --
instead of re-evaluating per session over the trailing 400 days -- reproduced **244 of 246** round-2
and round-3 runs byte-for-byte. The two that differed were the same card in the same window:

```
r2-2026-08/covid/C-trend   ending_equity 11583.33 -> 11589.84   trades 7 -> 6
r3-2026-08/covid/C-trend   identical divergence
```

One signal flipped, and only one, across the whole comparison:

```
2020-05-14  TSM   per-session (400-day frame): entry fires   long frame: does not
```

`C-trend`'s entry is `close > sma(200) and ema(20) crosses_above ema(50)`. On 2020-05-14 those two
EMAs are crossing, so a 1e-5 difference decides which side of the other they are on. The card loses
a TSM re-entry and its 7 trades become 6.

**Why this is a defect and not a curiosity.** The number 400 has no justification in the codebase. It
is not derived from the longest indicator period a card declares -- `max_indicator_period` exists in
`strategy-program/tools/windows.py` and is not consulted here -- and no test pins it. Change it to
500 and some results change; a card using `ema(200)` would be materially mis-seeded at 275 bars and
nothing would say so. Every published figure in `data/rounds/` is conditional on it.

**Why nothing was changed.** Fixing it means computing recursive indicators over full history, which
is more accurate and also **shifts published results** -- the two runs above, and an unknown number
in round 1, which was not re-checked because its files predate `capital_exposure` and differ on that
field anyway. Three rounds of cross-round comparability, and `PROTOCOL.md` §6's two-consecutive-rounds
promotion rule, currently rest on those numbers. Correcting the engine and re-baselining every round
is a decision for the programme's owner, not a side effect of a performance change.

**If it is taken, the order matters:** fix the seeding, re-run r1, r2 and r3 in full, re-score, and
note in each round's REPORT.md that its numbers were restated and why. The reproduction harness that
found this makes the re-run verifiable rather than hopeful.

**The performance motivation, recorded so it is not re-derived.** A profile of the desk's cold load
puts effectively all of it in this same path: for every session, for every symbol, the engine
recomputes each indicator across the whole visible history and then reads one trailing value -- 1,378
full `sma`/`ema`/`rsi` passes for a three-card, 55-session window, discarding 274 of every 275
elements it computes. Evaluating once per symbol took the desk from 15s to 3.3s, a 4.5x saving, and
would speed up competition rounds by a similar factor. That saving is available the moment the
seeding question is settled. Until then the desk's cold cost is avoided rather than removed, by the
disk cache in `app.paperdesk.desk`.

**Fix as taken.** `AsOfMarket.history(symbol, lookback_days=None)` returns every stored bar up to
`as_of`. `runner._rule_fires` and `app.paperdesk.desk`'s signal evaluation both use it. The bounded
default stays for callers that genuinely want a recent slice and nothing more -- `close` asks for 30
days, the desk's last-price read for 10 -- because a rolling mean forgets and a recursion does not,
and the distinction is now stated in `history`'s own docstring rather than left implicit.

This does not make the seeding arbitrary-free by magic. It moves the arbitrary choice from a default
argument nobody picked to the beginning of the stored data, which is at least a fact about the world.

**Restatement.** All 330 committed run files across r1, r2 and r3 were re-run through the corrected
engine and overwritten, driven from each file's own embedded `StrategyCard` so the restated field is
provably the field that was originally run. The scoring aggregates were regenerated with them.

**3 of 330 results moved**, all the same card in the same window -- `C-trend` in `covid`, present in
all three rounds -- by **0.065 percentage points** of starting equity. Exactly one signal flipped
across the entire programme: `TSM` on 2020-05-14, where `ema(20)` and `ema(50)` were crossing.
`C-trend` gains back a trade it had lost, 6 becoming 7, and its covid excess moves +24.5% -> +24.6%.
No median, ranking, Pareto frontier, promotion or conclusion in any round report changes.

That is a reassuring blast radius, and it is worth saying why it is not a reason to have skipped the
fix: the defect's *size* was always ~1e-5, and its *effect* was always going to be all-or-nothing at
whichever crossings happened to fall inside the error band. Three moved here. A different window, or
a card with more knife-edge crossings, would move more, and nothing about the old code bounded that.

**The speedup this unblocked.** With both the per-session path and `runner._SignalTable` reading the
same full-history frame, evaluating each rule once per symbol and indexing per session became exactly
equivalent -- which it was not before, and the failed first attempt is recorded in that class's own
docstring. The desk's cold compute went from ~15s to ~4s; competition rounds gain similarly.
`tests/test_tournament_runner.py::TestSignalTableMatchesPerSessionEvaluation` pins the equivalence,
deliberately using an expression built from recursive indicators that actually cross, so it cannot
pass vacuously.

---

## D5 — cutting a live period into independent sub-window runs resets the book at every boundary

**Not an engine defect. A defect in a measurement this program designed**, recorded here because the
consequence is the same — a table of numbers that looks complete and measures something other than
what it says.

**Found:** round 11, 2026-08-22, before any of the affected numbers were used to seat a card.
**Status:** instrument replaced; the invalid output is kept as evidence at
`data/rounds/r11-2026-08/results-independent-INVALID/`.

### What was built

Round 11 implements "fix 4" — rank cards on the live out-of-sample record rather than on backtests.
One 127-session window is a single draw, so `ROUND-11-PLAN.md` §2 pre-registered cutting it into six
contiguous sub-windows and scoring them the way every other matrix in this programme is scored, to get
a hit rate and a median instead of one number.

The first implementation ran **each sub-window as its own tournament**: one starting 2026-02-17, the
next 2026-03-19, and so on.

### The defect

**Every one of those runs starts with a flat book.** A card that entered positions in March and held
them into August was made to liquidate at each boundary and re-enter from a standing start, inside a
window too short for many entry rules to re-fire at all.

`B-momentum` is the clearest case. Over the full window it takes 11 trades at 56.9% capital exposure
and returns +31.97%. Cut into six independent runs:

| sub-window | sessions | trades | capital exposure | return |
|---|---|---|---|---|
| `live-1` | 22 | 1 | 4.1% | −0.96% |
| `live-2` | 21 | 6 | 18.5% | +4.72% |
| **`live-3`** | 21 | **0** | **0.0%** | **0.00%** |
| **`live-4`** | 21 | **0** | **0.0%** | **0.00%** |
| `live-5` | 21 | 2 | 4.6% | −0.85% |
| `live-6` | 21 | 5 | 29.0% | −2.50% |

Two entire sub-windows at zero exposure and zero trades — **not because the card was in cash**, but
because its confirmed-acceleration rule needs a lookback it cannot accumulate in 21 sessions from
flat. In reality it held positions throughout both.

So the matrix measured *"this card, liquidated and restarted every 21 sessions"*, which is a different
strategy from the one on the desk.

### Why it is worse than a random error

**It is directionally biased toward turnover.** A card that trades often barely notices a reset; a
card that enters once and holds is destroyed by it. The two cards that cleared the round's live
consistency gate on the invalid matrix were the two highest-turnover cards in the field —
`A-rotation` (29 trades over the window, 4/6 hits) and `c18-meanrev` (56 trades, 5/6) — while all four
momentum variants and both trend cards scored 1/6. That is not a finding about those cards. It is the
instrument.

**And it pointed at the convenient answer.** The invalid matrix seated `A-rotation` alone — the same
card the desk owner had overridden round 10's rule to keep one day earlier
(`data/rounds/r10-2026-08/SELECTION.md` §7). A live-first rule producing exactly that result is what
`ROUND-11-PLAN.md` §5 warned a reader should be suspicious of, and the pre-committed expectation in
§6 that `B3-concentrated` would lead was **contradicted**. The prediction failing is what prompted
looking at the `+0.00%` cells rather than shipping the roster.

### The fix

Run six **cumulative** tournaments from one fixed start (2026-02-17 → each sub-window's end) and
recover each sub-period by differencing consecutive runs. There is only ever one entry point, so
position continuity is preserved. The differencing is exact for all three quantities the score needs,
because each is either a level or a per-session sum over a common `starting_equity`:

- **return** — `ending_equity_k / ending_equity_{k-1} − 1`
- **benchmark** — `(1 + bench_k) / (1 + bench_{k-1}) − 1`
- **capital exposure** — `capital_exposure` is `sum(session_entry_notional) / (sessions ×
  starting_equity)` (`app.tournament.runner`), so multiplying back recovers the notional total,
  differencing gives the sub-period's, and dividing by `Δsessions × ending_equity_{k-1}` expresses it
  against the equity the sub-period actually started with — the same base its return is measured
  against.

See `strategy-program/tools/run_live_matrix.sh` and `round11.py`'s `live_cells`.

### What this does not license

Changing a measurement after seeing what it produced is exactly the move this programme exists to
catch, so the distinction matters: **no threshold, gate, window boundary or ranking criterion moved.**
`ROUND-11-PLAN.md` is unamended and still committed at `dda5573`. What changed is that the sub-windows
are now slices of one continuous run instead of six separate ones — a correction with a mechanical
justification that is independent of which card it favours, and which happens to run *against* the
result that would have been convenient.

---

## D6 — a round asserts the bar store is unchanged, against a figure quoted from a previous round

**Not an engine defect. A defect in how the programme handles its own inputs**, and it invalidates a
sentence rather than a number.

**Found:** 2026-08-22, during round 12's integration.
**Status:** **FIXED 2026-08-26** -- figures were never affected; the practice was wrong and is now mechanised. See "The fix" below and "What landed" after it.

### What happened

Rounds 11 and 12 both open by asserting the evidence base is frozen. Round 11's §0 says the bar store
is *"unchanged since round 9 ran — verified, not assumed: SPY holds 8,445 rows ending 2026-08-18"*.
That was true when written.

By the end of the same working day the store held **SPY 8,448 rows ending 2026-08-21**. Round 12's
own store check caught the discrepancy and disclosed it rather than absorbing it, which is the only
reason it is written down here.

### Why it moved

`data/store/` is **gitignored** — mutable local state, not versioned evidence — and
`app.market.store.ensure_series` syncs fresh bars whenever a page asks for them. The backend was
running while the Macro page, the portfolio grid and the desk roster were being checked in a browser.

**Verifying the dashboard advanced the data the competition is scored on.** That is the whole
mechanism, and it is not exotic: any ordinary use of the application does it.

### What is and is not affected

**No figure changes.** Every computation is explicitly bounded — Gate A's rungs end 2026-02-13, the
live window is hard-coded 2026-02-17 to 2026-08-18, and the ladder windows all close on or before
2026-02-13. Appended bars cannot reach them.

**The claim is what breaks.** "The store is unchanged" was asserted by comparing against a row count
quoted in prose from an earlier document. That comparison has an expiry date nobody stated, and it
now fails while the same reassuring sentence still sits at the top of two round documents. A reader
re-running those tools tomorrow gets a different store and the identical printed claim.

**And there is now unused evidence.** The live out-of-sample record is three sessions longer than
rounds 11 and 12 measured — 130 sessions, not 127. Neither round is wrong to have used 127; both are
wrong to imply that is all there is.

### The fix

A round should **pin the store state it ran against in its own artifacts** — row count and last date
per symbol, written into the round's `scorecard.json` at run time — and later rounds should compare
against *that recorded value*, not against a number transcribed from another document's prose. A
mismatch then reports which round's evidence base differs and by how much, instead of a stale
sentence quietly becoming false.

Not implemented here: it changes what every round writes, and doing it mid-integration is the kind of
instrument change `PROTOCOL.md` refuses. Round 13's job.

### What landed — 2026-08-26

Implemented at a clean boundary rather than at round 13: the autonomous loop had stopped of its own
accord after generation 1848 (`OUTCOME.json`, `PLAN.md` and `REVIEW.json` all written, ledger entry
complete), so nothing was mid-round when the instrument changed.

`strategy-program/tools/storestate.py` captures the store as data — row count and last bar date per
symbol — and compares a later store against a recorded pin. `score.py` gained two flags:

- `--pin-store` writes the capture into the scorecard as a `store_state` key.
- `--compare-store <scorecard.json>` reports drift against an earlier round's pin.

**Pinning is opt-in, and that is what keeps `_build_json`'s existing promise.** That function
already refuses to let rounds 2–4's published JSON gain new top-level keys. A key nobody asks for is
never added, so re-scoring an already-published round reproduces it exactly; verified by running the
same command with and without the flag, where the only difference is the one added key.

**Four design decisions worth the ink:**

- **Row count and last bar, not a hash.** A partition rewritten to identical content is not a
  changed evidence base, and a hash would report it as one. `fetched_at` is excluded for the mirror
  reason: it moves on every sync, including the ones that append nothing.
- **Same count with a different last bar is reported as `rewritten`, not as unchanged.** A row count
  alone cannot see a partition rebuilt over a shifted window, and "0 rows added" would read as
  agreement — the same false reassurance this defect is about.
- **Drift is reported, never judged.** Whether drift can reach a round's own bounded windows is a
  reading of that round — round 11's ladder windows all close on or before 2026-02-13, so appended
  bars provably cannot reach them. That belongs in the round document, written by a person, not in a
  tool's exit code. `--compare-store` never fails a run.
- **A missing pin reports as missing.** Every round scored before this landed has none, and the tool
  says "records no pin … This is not 'unchanged'" rather than comparing against nothing and finding
  no difference. That specific silence is what the defect was.

**The drift was still running while this was written.** The pin taken 2026-08-26 records SPY at
**8,450 rows ending 2026-08-25**. Round 11 claimed 8,445 ending 2026-08-18; round 12 found 8,448
ending 2026-08-21. Three separate readings, three different answers, one unchanged sentence — and
`data/store/bars/interval=1d/symbol=AAPL/bars.meta.json` carried a `fetched_at` thirteen minutes old
at the time of capture, so a peer session was advancing it during the fix.

One incidental find, pinned by a test: the store holds `BZ=F`, whose partition directory is
`symbol=BZ=F`. DuckDB's `hive_partitioning = true` cannot split that into one key and one value and
fails the **entire** scan with `Binder Error: Hive partition mismatch … key "symbol" not found`, so
one futures ticker would have cost the pin all 688 symbols. `capture` groups by filename and parses
the directory name, which is what `duck.stored_symbols` already does.

Tests: `tests/test_storestate.py` (19). Capture over the whole daily store is one grouped DuckDB
scan — 688 symbols, 5,048,858 rows, 0.91s — which is what makes pinning cheap enough to do on every
round instead of only when someone remembers to.

---

## D7 — a stateful `card_weight_fn` closure reused across windows carries the previous window's state

**Found in round 16, in round 15's numbers. Corrected in round 15's own record before this entry
existed; catalogued here on 2026-08-29 because it was not.**

### What happened

`round15.py` built one `card_weight_fn` per *card* and reused it across all five long windows.

`AllocationCard`'s closure is stateless, so all 26 allocation cells are unaffected and reproduce to
the last digit. **`LadderCard`'s closure is a state machine** — it carries armed rung depth and the
cycle-starting high — so every window after the first inherited the previous window's state.

The seated `sso-vig-bnd` card's five-window figures, as published and as corrected
(`data/rounds/r15-2026-08/SELECTION.md`, reproduced in `r16-2026-08/SELECTION.md`):

| window | as published | corrected | delta | QQQ CAGR |
|---|---|---|---|---|
| h10y-1 | 8.14% | 8.14% | **+0.00** | 17.43% |
| h10y-2 | 18.53% | 10.64% | −7.90 | 19.65% |
| h5y-1 | 22.16% | **6.09%** | **−16.07** | 19.76% |
| h5y-2 | 27.36% | 11.63% | −15.73 | 27.46% |
| h5y-3 | 16.96% | 9.77% | −7.19 | 12.42% |

Round 16's direct reproduction is the cleanest statement of the mechanism there is:

```
SHARED closure  : run1 cagr=11.6330%  run2 cagr=26.5207%   same=False
FRESH closures  : run1 cagr=11.6330%  run2 cagr=11.6330%   same=True
```

### Why it is worse than an ordinary arithmetic error

**`h10y-1` is unchanged, because it ran first with a fresh closure.** The first cell of any sweep is
always right. That is the signature that confirmed the cause rather than merely fitting it — and it is
also exactly what hides this class of defect: whoever spot-checks a sweep checks the first cell, finds
it correct, and stops. Up to 16.07 points of CAGR on a card that was *seated on the paper desk*
survived that check.

It also flatters in the direction nobody questions. Every contaminated figure moved **down** on
correction, meaning the defect made a seated card look better than it was, in the windows a reader is
most likely to quote.

### The fix, and what remains true

Build a fresh closure per cell, never one reused across windows. Round 15's records were re-measured
rather than annotated; the original output is kept as evidence at
`data/rounds/r15-2026-08/contributions/roth-CONTAMINATED-INVALID/`, following this programme's rule
that a correction keeps the error visible beside it.

**No figure in the committed record remains contaminated by this.** What was missing was this entry:
the correction lived only in two rounds' `SELECTION.md` files, so a reader consulting the central
defects catalogue — the document that exists precisely to answer "what is known to have gone wrong
with this instrument" — would not have found it. A defect that is fixed but uncatalogued is one
re-read away from being rediscovered from scratch, and this one cost a seated card 16 points.

### What this does not license

It says nothing about `AllocationCard`, whose closure is stateless and which reproduced exactly. It is
also not an argument against closures — it is an argument against sharing a *stateful* one across
measurements that are supposed to be independent. Anything a worker carries between cells belongs in
explicit state a reader can see, not in a captured variable.

---

## D8 — a band breach can emit a buy with no sell to fund it, and the order then retries forever

**Found 2026-08-30, while reconciling the harness/engine turnover gap left open by round 19. Not
fixed here — see "why this is not fixed in this pass" below.**

### What happens

`_rebalance_moves` applies `card.band_pct` to each sleeve independently: a sleeve more than the band
*under* its target produces a buy, a sleeve more than the band *over* it produces a sell. That is
symmetric per sleeve and asymmetric in aggregate — **the offsetting overweight can be spread across
several sleeves that are each individually inside the band**, so a buy is emitted with nothing sold to
fund it.

The real state at `2022-09-26` on `qld-schd-sgov`, band `0.05`:

| sleeve | target | actual | deviation | |
|---|---:|---:|---:|---|
| QLD | 0.4300 | 0.3781 | **−0.0519** | **outside** |
| SCHD | 0.3200 | 0.3320 | +0.0120 | inside |
| SGOV | 0.2500 | 0.2890 | +0.0390 | inside |

→ **1 buy, 0 sells.** The overweights sum to +0.0510, offsetting QLD's −0.0519 almost exactly, and
neither crosses `0.05` on its own. The engine submits a $4,469.75 buy against **$73.69** of cash and is
rejected `insufficient_cash`.

Minimal reproduction, same card, same underweight, only the *distribution* of the offset changed:

    dev QLD -0.0519 OUTSIDE | SCHD +0.0120 inside | SGOV +0.0390 inside  ->  1 buy, 0 sells  UNFUNDABLE
    dev QLD -0.0519 OUTSIDE | SCHD +0.0519 OUTSIDE | SGOV  0.0000 inside ->  1 buy, 1 sell   fundable

### Why it is worse than one failed order

**The rejection is self-perpetuating.** A rejected buy leaves the sleeve underweight, so the band
fires again next session, submits the same unfundable order, and is rejected again. Measured over
`2022-08-23`–`2022-12-30`: **65 order attempts, 6 fills, 59 rejections on 59 distinct sessions**, in
two contiguous episodes. **59 of 61 band-firing sessions emitted buys with no sell.** The book stops
rebalancing entirely and drifts for the rest of the run, while the result reports a plausible ending
equity and a `rejections` list of bare strings with no dates.

### Why two sleeves never caught it

Every existing test of `_rebalance_moves` uses **two** sleeves, and with two sleeves the deviations are
always equal and opposite — if A is 5 points under, B is 5 points over. A buy therefore *always* has a
matching sell, and the asymmetry cannot appear. **It needs three or more sleeves to occur at all**,
which is why `TestRebalanceMovesIsolated` passes and the behaviour still ships.

### Blast radius

Two seated cards carry three or more sleeves and are exposed: `qld-schd-sgov` (3) and
`spy-schd-agg-gld-bil-atr-tilt` (5). The two ladder cards define their sleeves elsewhere and are not
affected by this path. Any allocation figure produced through `run_allocation` for a card with ≥3
sleeves is a figure for a book that may have silently stopped rebalancing.

### What this explains

It closes the chain rounds 15, 16 and 19 were following. Round 15 called the contribution harness
"systematically optimistic" for affording rebalances a real account cannot. Round 16 measured its cash
cap as worth nothing and blamed settlement. Round 19 implemented settlement and found it made the gap
*worse*. The gap was never a funding model at all: **the harness rebalances the whole book on a
breach, so its buys are funded by construction; the engine rebalances per sleeve and can issue a buy
it cannot pay for.** The harness was not being optimistic — it was doing what the engine failed to do.

### Fixed 2026-08-30, under `ROUND-20-PLAN.md`

The funding rule was pre-registered before the code was written, because "which sleeves pay for a
breaching buy, and in what order" is a strategy choice and picking it after seeing the restated
numbers would be the error this programme exists to prevent.

**The rule:** a breaching buy is funded from cash first, then by selling from *every* overweight
sleeve — not only those that individually breach — pro-rata to each sleeve's overweight, for exactly
the amount still needed. Pro-rata rather than greedy because greedy is path-dependent on sleeve
order, and this programme's own 21.2-point noise floor came from measuring exactly that kind of
ordering sensitivity. A donor is never sold past its own target, so funding one breach cannot create
the next. Rejected and named in the plan: resetting the whole book to target on any breach, which
would change what an `AllocationCard` means rather than fix what it does.

**Settlement is deliberately not worked around.** `PaperBroker` fills against settled cash and a sale
settles T+1, so a funding sell does not pay for a same-session buy — the buy fills a session or two
later. Pre-crediting unsettled proceeds would reintroduce the fiction round 19 removed from the
harness. What changed is that the retry now *terminates*.

**Measured on the same card and window:**

| | before | after |
|---|---:|---:|
| rejections | 59 | **3** |
| ending equity | 86,547.09 | **85,746.40** |
| harness/engine gap, both at T+1 | −0.6989% | **+0.0596%** |

All five of the plan's predictions held, including the two that could have gone either way: every
two-sleeve test passed unedited (so the band's meaning did not change, only its funding), and the
ending equity moved **down** — completing a rebalance into a 2× leveraged ETF during a falling window
cost money, which is why the plan declined to predict the direction.

**And it vindicates round 16.** Round 16 predicted that adding settlement to the harness would close
the gap materially; round 19 implemented settlement and found it made the gap 23.9% *worse*, and
recorded that as a refutation. With D8 fixed, settlement closes **73.9%** of the gap. Round 16 was
right; its prediction was masked by this defect. Round 19's refutation was a correct measurement of a
defective engine.

The `xfail` that pinned the intended behaviour is now un-marked and passing, and
`strategy-program/tools/round19.py` keeps *both* engine figures rather than replacing the old one, so
this instrument change stays visible on the path that would otherwise silently absorb it.

## D9 — `indicator_refs` raised on every rule containing a macro field

**Found 2026-08-30 by `mypy --strict`, not by a test. Fixed the same day in `59eaf73`.**

### What happened

`app.rules.grammar.indicator_refs` — a public export of that module — raised
`AssertionError: Expected code to be unreachable` on **any** rule containing `macro(...)`:

    indicator_refs(parse("macro(T10Y2Y) > 0"))                        -> AssertionError
    indicator_refs(parse("sma(20) > close and macro(T10Y2Y) > 0"))    -> AssertionError

The second is the one that matters: a rule whose real subject is an ordinary indicator, where a single
macro conjunct was enough to take the whole walk down.

`MacroRef` joined the `NumExpr` union in `97991d1`, which obliged every structural walk over that union
to gain an arm. Four got one — `_expect_num`/`_expect_bool`, `_render`, `app.rules.evaluate`, and
`app.backtest.guards`. `grammar._collect` did not. An unmatched leaf there is not skipped: it falls
through to `assert_never`, which raises.

### Scope — two test modules plus the warmup calculator

`indicator_refs` has three callers:

| caller | kind |
|---|---|
| `tests/test_rule_grammar.py` | test |
| `tests/test_evolution_ruleforms.py` | test |
| `strategy-program/tools/windows.py:518`, inside `max_indicator_period` | **round tooling** |

The third is the one worth naming. `windows.py` is the minimum-warmup calculator, and its own docstring
at line 488 states the dependency ("Parsed with the real grammar … `+ .indicator_refs`, not a regex").
An earlier statement of this defect's scope said "test-only callers"; that was wrong, and wrong in the
place it matters most, since warmup is what round 22's Amendment 1 turned on.

**No round is affected and nothing needs re-running.** The engine never calls this walk — the
production path is `app.backtest.guards.required_indicator_refs`, which has carried an explicit
`case MacroRef(...)` arm with its own `_ALLOWED_MACRO_FIELDS` allowlist since `97991d1` and fails
closed through `_ALLOWED_NODES` rather than through `assert_never`. That is what the runner and the
lookahead guard call, and it is what every macro round ran through. And on the one non-test path, the
failure was a **raise, not a wrong number** — a macro card reaching `max_indicator_period` would have
crashed the tool, so no round could have absorbed it and reported a warmup. Rounds 21, 22, 23 and 25
stand as reported.

Post-fix, verified directly:

    max_indicator_period("sma(200) > close and macro(T10Y2Y) > 0")  -> 199
    max_indicator_period("macro(T10Y2Y) > 0")                       ->   0
    max_indicator_period("sma(200) > close")                        -> 199

### Why nothing caught it for nine days

Not a gap in the test suite's intent — a gap in what was gated. `mypy --strict` had been reporting
`Argument 1 to "assert_never" has incompatible type "MacroRef"; expected "Never"` at that exact line
the entire time. It is a *statically provable* claim that the arm was reachable, and it was correct.

It went unread because the repository's mypy gate was already red: 56 errors across 15 files, so a real
new error had nowhere to stand out. A green suite and three completed macro rounds sat on top of a
public export that raised on the feature those rounds were about. The gate was restored in `bd0c032`
and `0c1c0ff` (55 → 0 across 213 source files); `strategy-program/` joined the lint gate in `4c29c48`.

### The fix

One match arm. `MacroRef` belongs with `PriceRef` in the collect-nothing case — a macro series is bound
from the pin by `app.rules.macro_binding`, not computed by an indicator, so this walk genuinely has
nothing to find in it. It must say so explicitly rather than by omission, which is the whole lesson:
in an `assert_never`-terminated match, *absent* and *handled-as-nothing* are opposite behaviours.

`tests/test_rule_grammar.py::TestIndicatorRefs::test_walks_past_a_macro_ref_instead_of_raising`
asserts both the bare and the mixed rule, and was verified failing before the fix by direct
reproduction rather than assumed to fail.
