# The competition protocol

Version 1. Amended only between rounds, never during one, and every amendment is recorded in
§9 with the round it took effect.

This document defines a loop. A round runs, produces a report, promotes and demotes strategies in
the library, and hands the next round a slightly better field and a slightly harder test. Nothing
here depends on a human deciding what to try next — the promotion rules in §6 do that.

## 1. What the program is for

To find trading rules that keep working, and to avoid being fooled by ones that only worked once.

The second half is the hard part. The tournament that preceded this program ran 26 strategies over
127 sessions, ranked them, and then re-ran the identical cards over three years. The rank correlation
between how a card did on the data its author studied and how it did on data nobody had seen was
**Spearman ρ = 0.162**. A card placed 13th of 26 over six months and 3rd of 24 over three years. The
ranking was very nearly noise.

Everything structural in this protocol exists to attack that specific failure.

## 2. The loop

A round has seven phases, and phases 3–5 are strictly serial.

| # | phase | who | output |
|---|---|---|---|
| 0 | **Open the round** | orchestrator | `rounds/<tag>/BRIEF.md`, the window matrix, the design cutoff |
| 1 | **Design** | N analyst agents, in parallel, one card each | `rounds/<tag>/cards/*.json`, `rounds/<tag>/memos/*.md` |
| 2 | **Freeze** | orchestrator | cards are committed before any backtest runs; from here they are immutable |
| 3 | **Eligibility** | orchestrator | which cards can legally run in which windows, and why not where not |
| 4 | **Run** | orchestrator, **serially** | `rounds/<tag>/results/<window>/runs/*.json` — one trade log per card per window |
| 5 | **Score** | orchestrator | the scorecard, from `tools/score.py` |
| 6 | **Report** | one agent per card, in parallel, each reading only its own trade logs | `rounds/<tag>/reports/*.md` |
| 7 | **Promote** | orchestrator | library changes per §6, and `rounds/<tag>/REPORT.md` |

**Phase 2 is the integrity boundary.** A card edited after any result exists is not a strategy, it is
a memory of one. Cards are committed to git at the end of phase 1, and the commit hash is quoted in
the round report.

**Phase 6 gives each card its own advocate.** The per-card reporter sees that card's trade logs and
its author's pre-registered failure regime, and nothing about how any other card did. This keeps the
individual reports honest about their own card rather than written to a ranking.

## 3. The anti-overfitting constitution

These rules bind analysts and orchestrator alike. They are the reason to trust a result from this
program more than a backtest.

1. **One submission per analyst per round.** No revision after seeing any result. There is no
   leaderboard to climb during a round.
2. **Design cutoff enforced by type.** `StrategyCard` rejects a `designed_through` past the round's
   cutoff. Analysts bound every data read to it.
3. **Parameter budget.** Ten free numbers per card, counted across `entry`, `exit`, the two brackets,
   the hold cap, slot count and position size. Reported in every memo.
4. **No grid search.** Sensitivity is tested to show a rule is *insensitive*. A rule that works at one
   parameter setting and breaks one notch away is a fitted rule and must be reported as such.
5. **Pre-registered failure regime.** Every analyst names the regime their strategy hates, before it
   trades. The report prints the prediction beside the outcome.
6. **Information quarantine.** Analysts may not read prior rounds' results. Whatever is
   methodologically useful in them is extracted into the brief instead.
7. **The regime gate.** A card eligible in fewer than **five** of the eight main windows is
   **unranked** — its numbers are published, and it is excluded from the ranking rather than sorted to
   the bottom.

   *Text corrected 2026-08-29, not a rule change.* This clause read "fewer than three" from round 1,
   when the matrix had five windows. §9's own r2 amendment raised the gate to "five of eight, the same
   60% proportion" and `MIN_ELIGIBLE_MAIN_WINDOWS = 5` (`app.tournament.jobs`) has enforced that in
   every round since — so this sentence contradicted both the amendment log two sections below it and
   the code every round actually ran against. Found while pre-registering the macro round
   (`ROUND-21-PLAN.md`), which had to pick a number and discovered the constitution gave two.
8. **Correction across everything tried.** Any multiple-comparison correction uses a denominator of
   every card run in the comparison, never a subgroup. A correction over 8 when 16 were run is the
   exact failure the correction exists to prevent, and this project has made it once already.

## 4. Scoring

The ranking key is the **median exposure-adjusted excess return across a card's eligible main
windows**:

```
excess          = strategy_return - benchmark_return          # per window, that window's own benchmark
adjusted_excess = strategy_return - capital_exposure * benchmark_return
rank_key        = median(adjusted_excess over eligible main windows)
```

`adjusted_excess` asks whether the *rules* beat being invested the same fraction of the time.
Without it, exposure dominates: the prior tournament measured Spearman **ρ = 0.648 between exposure
and three-year return**, and its top card was invested 90% of the time in a window where the
benchmark rose 75%.

**Which exposure, and why it matters — found the hard way in round 1.** The runner's own `exposure`
field is the fraction of *sessions on which the card held at least one position*
(`runner.py` records `bool(open_lots)` per session; `metrics.py` averages it). It is **not** the
fraction of capital deployed. A four-slot card holding a single slot every session reports
`exposure = 1.0` with a quarter of its capital at risk.

Using it in `adjusted_excess` over-credits precisely the cards that hold few slots, and it does so
worst in a falling window, where the term being subtracted is negative. Round 1 found this partway
through: a card showed +55.45% adjusted excess against a −56.23% benchmark on a raw exposure of
97.19%, while its own author had estimated 45% capital deployment. Both numbers were correct
measurements of different things.

**`capital_exposure` is therefore reconstructed from the trade log** — for each session, the summed
entry notional of open positions over starting equity, averaged across sessions — and it is the term
`adjusted_excess` uses. `session_exposure` is still reported beside it, because "how often was this
card in the market at all" is a real question; it is just a different one. Any row where the two
diverge by more than 20 points is flagged, because that gap is where the naive metric misleads most.

Reported beside the rank key, never below it in importance:

- **worst window** — the generalisation test, and the number that decides ties
- **hit rate** — fraction of windows with positive adjusted excess
- **IQR across windows** — fragility; a wide spread means the median is not a description of anything
- **exposure, drawdown and trade count per window** — a card that beat a benchmark on four trades has
  demonstrated less than one that did it on ninety
- **realised P&L, in currency** — the plain dollar outcome, so the decomposition below is visible
  without hand computation
- **excess per unit of capital deployed** — `adjusted_excess / capital_exposure`, the scale-free view

**Two biases in this scheme, measured in round 2, pulling opposite ways.** Neither invalidates the
metric; both change how a table should be read.

*`adjusted_excess` scales with exposure.* Against a large negative benchmark the exposure term is a
credit proportional to how much capital was at risk, so a 44% book can reach +24.7 in a window where a
7.5% book is arithmetically capped near +5.6. Capital exposure correlated with GFC adjusted excess at
**Pearson r = +0.797** across ten cards. Each card's figure is a correct statement about itself —
measured against a passive position of its own size — but the figures are not commensurable across
cards, and a single ranking axis treats them as if they were. Any card whose exposure differs from the
field median by more than **2×** is therefore flagged, and `excess-per-exposure` is available as an
alternative ranking.

*The worst-window criterion favours small books.* A card holding 7.5% of capital structurally cannot
have a deep worst window. Frontier membership earned mainly on that axis must be read with the card's
exposure in view.

The two do not cancel. Round 2 measured the aggregate effect as small — ranking by excess-per-exposure
against ranking by median gives Spearman **ρ = 0.922**, so the median already suppresses most of it —
but **single-window comparisons invert**: per unit at risk in the GFC, the two smallest books were the
best in the field, the reverse of the raw column. Quote a single window's adjusted excess only beside
its exposure.

Never rank on a single window. Never compare a return from one window against another window's
benchmark.

**A note on p-values, carried forward.** The binomial test available here is two-sided against a fair
coin. It flags a win rate far below 50% exactly as strongly as one far above, and a long-only book in
a rising market clears or fails it for reasons unrelated to skill. In the prior tournament the card
with the most significant q-value achieved it with a **13% win rate**. q-values here are not evidence
of skill and are not used for ranking.

## 5. Windows

Defined in `WINDOWS.md` and implemented in `tools/windows.py`. Two rules govern how the matrix
changes between rounds:

- **Windows are added, never removed or re-cut to flatter a result.** Re-cutting a window after
  seeing returns is the purest form of the thing this program exists to prevent.
- **Each round adds the elapsed time since the last round as a new window**, and advances the design
  cutoff to the previous round's end. This is the walk-forward: every round, the previous round's
  newest window becomes a genuinely out-of-sample record for the cards that were designed before it,
  and those cards are re-run without modification.

Cards derived from point-in-time external data — 13F filings above all — may only trade windows that
begin **after the filing date the data was derived from**. The lookahead guard does not enforce this
and cannot: it verifies that an indicator is causal on symbols already chosen, and has no way to know
when the *basket* became knowable. This is enforced by whoever configures the run. See `CONSTRAINTS.md`.

## 6. Promotion and demotion — how the library evolves

The library is `base/`, `variants/`, `candidates/` and `retired/` under
**`backend/app/paper/library/`** — inside the application rather than in this directory, because the
application trades from it (see `README.md`). Movement between the tiers is mechanical, decided by the
scorecard rather than by argument, and a promotion is a file move plus a line in §9.

| move | condition |
|---|---|
| challenger → `candidates/` | clears the regime gate and posts a positive median adjusted excess |
| `candidates/` → `base/` | clears the gate with positive median in **two consecutive rounds**, on window sets that differ |
| variant replaces its base | beats its base on median adjusted excess in **two consecutive rounds** |
| `base/` → `candidates/` | fails the gate, or posts negative median, in two consecutive rounds |
| anything → retired | takes zero trades in every window of two consecutive rounds |

Two consecutive rounds, everywhere, because one round is one draw. A card promoted on a single
result is a card promoted on noise, which is how the prior tournament's ranking came apart.

**Two conditions, added after round 2 showed the rule above is not sufficient on its own.**

**(a) The second round must bring new windows.** Cards are frozen, windows are fixed date ranges, and
the engine is deterministic — so re-running a card on a window it has already been run on does not
sample anything, it recomputes the same number. Round 2 verified this on twenty of twenty pairs:
`A-rotation` returned +95.2786% in `recent` in both rounds, to four decimal places, on the same 47
trades. A "positive median in two consecutive rounds" built on overlapping windows is **one
measurement counted twice**.

So a promotion must rest on a positive median **over the windows the previous round did not have**,
not over a re-scored superset. The same applies to demotion: two negative medians on shared windows
are one negative result, not two.

**(b) Every margin must clear the noise floor.** §7's floor binds here too. Round 2 found that the
rule as written would have replaced Strategy B with `B2-hold-90` on margins of 5.62 and 4.15 points —
comfortably inside the ordering artifact, which round 1 measured at up to 12.5 points in a single
window against an earlier study's σ = 21.2. A rule that promotes on a margin the same document calls
meaningless is a rule that launders noise into the library. No promotion, in either direction, on a
margin inside the floor.

**A directed promotion is not a scorecard promotion, and this library now contains one.** On
2026-08-21 the program's owner set `B-momentum` and `C-trend` as the two primary strategies and closed
the research phase. `B-momentum` was already in `base/`. **`C-trend` was not promoted by the rule
above** — it is a round-1 candidate with one round's evidence, and the two-consecutive-rounds
requirement, together with condition (a), is precisely what it has not met. `A-rotation` moved the
other way, to `candidates/`, and it did not fail the rule either.

Both moves are recorded here as what they are: a decision by the owner of the program, taken with the
scorecard in view and overriding it. The rule is not amended and no exception is carved into it — the
next card that wants `base/` still has to earn it on two rounds and new windows. What this note buys
is that a later reader cannot mistake `C-trend`'s presence in `base/` for evidence it does not have.
`C-trend`'s standing rests on: a top-of-field round-1 result, a positive median across round 2's eight
windows, and the owner's judgement that its trend thesis complements `B-momentum`'s momentum tempo.
That is a reasonable basis for putting real money's attention on it. It is not two rounds.

Retired cards stay on disk with a note recording what retired them. `a08-slowtrend` is the worked
example: its `ema(300)` gate never opened in any window ever tested, over two universes and two
horizons, so it has never taken a single trade. It is retired, not deleted, and not in the library.

## 7. Variants — how a base strategy is developed

A variant isolates **exactly one** decision against its base. Not two. The point is to attribute a
difference to a cause, and a variant that changes three things at once cannot do that whatever it
returns.

Variants are written down **before** they run, which makes each one a pre-registered hypothesis
rather than a search result. The current set and the question each asks is in `backend/app/paper/library/README.md`.

**The ordering caveat applies to every variant comparison.** When more symbols qualify than there are
slots, something has to choose between them. For a card that leaves `rank_by` unset — which is every
card frozen before that field existed, and therefore every result this programme has published to
date — that chooser is the order the universe array is written in. Re-running one identical card
under twelve orderings moved its three-year return across a **53.9-point spread, σ = 21.2 points**.
Any variant comparison whose margin is inside that band has demonstrated nothing. State the margin
against that floor explicitly, every time.

**A card may now name the chooser instead** (`StrategyCard.rank_by`, see `CONSTRAINTS.md` "Structural
limits of the engine"). That replaces an arbitrary tiebreak with a stated one; it does **not** make
the spread above disappear, and it is not itself evidence of an improvement — the one measurement of
relative-strength ordering against random orderings of the same card put it 9th of 10, inside the
noise. Two cards differing only in `rank_by` is a legitimate variant pair under §7's one-decision
rule, and the margin between them is subject to the same floor as any other.

## 8. Operational rules the harness imposes

- **The store lock is fixed; the memory limit is not.** This rule used to read "backtests run
  serially, one process at a time", because `app.market.store` opened the DuckDB catalog read-write
  for pure reads and any second process collided. That is closed at source (`DEFECTS.md` D3): all
  three read call sites now use an in-memory connection and touch the file not at all. What still
  binds is the host — 16 GB physical — and running several bar-loading processes alongside a round
  has exhausted it. Concurrency is now a resource decision, not a correctness one.
- **Reconcile run files against `FAILED` lines after every window, regardless.** The runner walks past
  a failed card by design, so a shortfall is silent and a contended or broken round produces a report
  that looks complete. This survives the fix because the failure mode it guards is not only contention.
- **Never launch a round detached, and never kill one by killing `python.exe`.** The shell loop above
  the process survives and spawns a replacement for the next window. Getting this wrong cost round 2's
  entire first attempt: 135 card-runs, zero results. `tools/run_round.sh` now refuses to start when
  another tournament process is alive, and `app.tournament.jobs` — the in-process runner behind
  `/api/competition/jobs` — has no shell loop to orphan and holds a single-slot lock for the same
  reason.
- Runs are deterministic. Same cards, same persona, same window, same store gives byte-identical
  results. Slippage is deterministic and always adverse by design.
- The runner does not stop on a failed card, which is correct — losing twenty-five completed runs
  because the twenty-sixth raised would be a poor trade — but it makes the reconciliation above
  mandatory rather than optional.

## 9. Amendments

| round | change |
|---|---|
| r1-2026-08 | Protocol established. Regime matrix replaces the single recent window; exposure-adjusted excess replaces raw return as the ranking key; the regime gate, the parameter budget and the information quarantine introduced. |
| r2-2026-08 | **The matrix grows to eight windows**, adding `q4-2018` and two genuinely sideways markets, `chop-2015` and `chop-2011`. Round 1 had no directionless regime while several analysts had pre-registered whipsaw as their worst case, so those predictions went unscored. The gate rises to **five of eight**, the same 60% proportion. |
| r2-2026-08 | **The ranking becomes a dominance view.** Median alone placed a convex payoff 17th of 18 while it was the best card in the crisis by seventeen points. Cards are now ranked on median, worst window and hit rate together, with a Borda composite and an explicit **Pareto frontier** — the set no other card beats on all three at once. A card on that frontier is a defensible choice even with a poor median, which makes a deliberately convex strategy a viable submission for the first time. |
| r2-2026-08 | **Provenance is enforced by code.** A card may declare `universe_knowable_from`; any window starting before it is ineligible, and a run file for such a window forces the card unranked. Round 1 ranked a 13F-derived card on four windows predating its own filings — caught by a reader, not a tool, because the eligibility check asks whether a card's *symbols* have history and nothing asked whether its *basket* was knowable. |
| r2-2026-08 | **D1 and D2 fixed in the engine** (see `DEFECTS.md`), between rounds rather than during one. The scorer's workarounds are kept, because they derive from quantities correct under both the old and new engine and so keep the two rounds comparable for the two-consecutive-rounds rule. |
| r2-2026-08 | **Not a walk-forward round.** No calendar time passed between rounds 1 and 2, so the design cutoff could not advance and no genuinely unseen data exists. Round 2 widens the regimes tested; it does not add new data. The walk-forward in §5 begins when real time has elapsed. |
| r2-2026-08 | **Research phase closed, and the library reduced to two primaries.** `B-momentum` and `C-trend` are the base strategies; `A-rotation` moved to `candidates/`. This was directed, not scored — see §6's note on directed promotions. The competition loop is not retired: it is now reachable from the application at `/competition`, and a round can be launched, watched and cancelled from there rather than from a shell script. |
| r2-2026-08 | **The program stopped being read-only with respect to the application.** `README.md` used to say this program "writes nothing the application reads". That is no longer true — `backend/app/tournament/results.py` reads the library and `rounds/` to serve `/api/competition`, and `app.paperdesk` trades the base tier live. The directory layout became a published interface, so renaming `results/<window>/runs/` breaks a page. |
| r2-2026-08 | **The library and the mandate moved into the application.** Cards now live in `backend/app/paper/library/` and the trading mandate in `backend/app/paper/mandate.py`, rather than in `strategy-program/library/` and `uat/personas/pro-investor-01.setup.json`. The served app was reading its production constraints out of a UAT fixture and its tradeable strategies out of a research directory, which forced both trees into the Docker image and made a test harness load-bearing for a running server. `rounds/` deliberately did **not** move — see `README.md`. `tests/test_paper_mandate.py` asserts the application's mandate still equals the persona's number for number, because every result committed under `rounds/` was measured with those figures and silent drift would make a new round incomparable with an old one under §6's two-round rule. |
| r2-2026-08 | **The round records moved to `data/rounds/`.** The last path the served application resolved into this directory is gone: `app.tournament.results` reads round results through `Settings.rounds_dir` and `app.tournament.jobs` writes new rounds there. A round is generated output that grows, so it belongs in the application's data directory rather than inside the installed package where the library sits — different kind of artifact, different home. `data/rounds/` is tracked in git, and `.gitignore` carries an explicit note saying so, because `data/` otherwise reads as a never-commit area and a blanket rule there would silently drop the research record. What remains in `strategy-program/` is the programme: this protocol, the window matrix, the constraints, the engine defects, and the offline tools. |
| r21-2026-08 | **§6's promotion rule stops applying to the `trading` purpose, and no replacement gate is built.** The owner bounded the trading mandate at six months on 2026-08-29 (`app.tournament.purposes.PurposeSpec.horizon_months_max`). Gate A requires a positive median at round 5's **5-year and 10-year rungs** (`selection.RUNGS_5Y`, `RUNGS_10Y`), which a card capped at six months cannot satisfy without being forced to hold past its own mandate — the `DEFECTS.md` D5 shape, a table that looks complete and measures something other than what it says. The replacement was considered and **deliberately not built**: at six months the per-window sampling error is roughly **20×** a ten-year window's (`ROUND-5-PLAN.md` §5), while the ~26 non-overlapping six-month windows the common history supports buy only **√6.5 ≈ 2.5×** against Gate A's effective N of ~4 — and adjacent slices share regime, so even that is optimistic. A shorter mandate is **harder** to prove an edge in, not easier, and the multiple-comparison denominator rises from ~10 per card to ~780 across the field under §3 rule 8. A gate known in advance to lack discriminating power would launder noise into the library, which §6 already forbids in as many words. **What replaces it:** Gate L (liveness) and Gate C survive unchanged and stay as floors; a card stays seated on the owner's judgment plus those floors, the way §6 already records the `C-trend` directed promotion; and the six-month medians are **reported and never promoted on**, the same posture §4 already takes toward q-values. **Non-retroactive** — no figure, ranking or promotion in rounds 1–19 is restated, and this changes nothing for the `savings` and `roth` purposes, whose horizons are unchanged. Round 17's measured ~1pp ordering noise must **not** be borrowed to argue the floor is lower here: that finding is about universe breadth, not horizon. |
| r34-2026-09 | **A directed promotion, the second in this library.** Rounds 34, 35 and 36 (`strategy-program/DISJOINT-SECTOR-FAMILY.md`) were pre-registered as measurement studies from which nothing would be promoted, and all three returned the null: form marginal 4.21pp, country-rotation-minus-control at best +0.08pp, strong-minus-weak `rank_by` +1.2pp — every margin inside the 21.2pp floor, minimum BH q 0.40 across the family. On 2026-09-09 the owner directed that a card from the family be promoted anyway. **`r34-ma-crossover-on` moved to `candidates/`** — the family's best cell (median adjusted excess +1.24pp, hit rate 5 of 8, worst window −9.95pp, Pareto frontier, 8 of 8 windows, `purpose = roth`, universe `XME XRT XHB XSD XOP XBI ITA VNQ` disjoint from every savings/trading card). It satisfies the *letter* of §6's challenger → `candidates/` line (clears the gate, positive median) and **fails condition (b)**: its margin is inside the floor by a factor of seventeen, and its own plan said nothing would be promoted. As with `C-trend`, the rule is not amended and no exception is carved into it. This card's standing in `candidates/` rests on the owner's decision, not on the scorecard, and a reader must not mistake its presence there for evidence it does not have. It advances to `base/` only by the rule: two consecutive qualifying rounds on window sets that differ, margins outside the floor. The frozen round card in `data/rounds/r34-2026-09/cards/` is unchanged; the library copy is verbatim. **Seated the same day, also by direction**, on the Roth paper book (`app.paperdesk.desk.ROTH_AGENT_IDS`), with the desk's candidate disclosure naming it as seated by decision. |
| r38-40-2026-09 | **The persona-corpus rounds (37-41) all returned the null, and one card was promoted to `candidates/` only.** Rounds 38 (savings real-yield tilt), 39 (Roth style tilt) and 40 (trading confirmation conjunct) were pre-registered from the influencer note corpus (`strategy-program/PERSONA-HYPOTHESES.md`) and run 2026-09-09; every margin sits inside the 21.2pp floor (round 38: the real-yield tilt shifts drawdown +0.37pp and is beaten by a price-only placebo at +0.94pp; round 39: every rule arm loses to its passive control, style spread −5.43pp; round 40: best arm-minus-control +7.82pp). By §6 nothing qualifies. **`r40-rsi-confirm-slots6` was promoted to `candidates/` by direction** — round 40's sole positive cell (arm-minus-control +4.82pp at 6 slots), under observation, not seated on any book. Its live-desk seat is left as an explicit owner decision because it is inside the floor, carries a −17.2pp worst window, and §6's promotion rule does not apply to the `trading` purpose (see the r21 amendment above — trading seating is owner judgment). Nothing from rounds 38 or 39 was promoted; their results argue against it. Rounds 37 and 41 belong to other sessions. |
| r40-2026-09 | **`r40-rsi-confirm-slots6` seated on the trading paper book by direction (2026-09-09).** The owner directed the live-desk seat the entry above had left open. It joins `app.paperdesk.desk.AGENT_IDS` (the trading roster) as the third directed seat on that book beside `C-trend` and `I-13f-duquesne-2026q2`, with the desk's candidate disclosure (`_CANDIDATE_AGENT_IDS`) naming it as seated by decision, inside the floor, from a round that concluded the conjunct does not pay for itself, and flagging its −17.2pp worst window. The `candidates/` copy is unchanged; the frozen round card in `data/rounds/r40-2026-09/cards/` is unchanged. |
| r42-44-2026-09 | **The discussion rounds (42, 43, 44) all returned the null; nothing was promoted or seated.** Rather than re-read the corpus, the five persona agents were asked directly through the grounded chat (`strategy-program/PERSONA-DISCUSSION-2026-09-09.md`: 15 turns, none degraded) what they would test next on each book; two gave daily-bar rules, three declined and offered themes. Round 42 (trading: Creator E's wick-rejection reclaim, Creator C's 0.25-range breakout confirmation) — every arm-minus-own-control margin between −5.87pp and +1.00pp, min BH q 1.0. Round 43 (savings: the bond sleeve's own 200-day trend moving 10 points AGG→BIL/GLD) — drawdown margins −0.4 to +1.3pp, the primary beating round 38's SPY placebo by 0.67pp, and the point of effect concentrated in the 2022 windows the plan pre-declared in-sample to the hypothesis. Round 44 (roth: power/defense/semicap/real-asset baskets held passively vs a broad passive control, each with a creator-b profit-trim arm) — best basket +8.0pp (utilities' defensive beta, q 0.43), best trim +2.4pp; the semicap basket's +152.6pp in `recent` alone against +0.4pp on the six pre-2023 windows is the pre-registered hindsight split holding in its most extreme form. Every margin inside the 21.2pp floor; §6 untouched; no directed promotion was requested or made. The persona line is now measured-null on all three books and both card shapes (rounds 37-44). |
| r45-48-2026-09 | **The mix-and-match rounds (45-48) all returned the null on their decision rules; three directed promotions to the shelf, no seating change.** `strategy-program/MIX-AND-MATCH-PLAN.md` crossed persona components with each other and with measured forms as pre-registered factorials. Round 45 (trading: three persona method cards × four cross-persona enhancements, 14 cells) — every enhancement marginal between −1.37 and +0.21pp, min BH q 1.0; the 5:1 bracket fired on 0-2.5% of exits. Round 46 (savings: the SPY-trend and AGG-trend de-risks stacked) — additive within tolerance (`both − (spy + agg)` = +0.25pp), `both` +2.45pp of drawdown margin at −0.54pp CAGR; the two three-rule cells exceed §3's parameter budget (11 and 12 free numbers) and were reported as supplementary only. Round 47 (roth: dip entry × trim exit on round 44's baskets, 12 cells) — best arm-minus-passive +2.36pp, min q 0.17; the combination lost to the better of its parts in 2 of 3 baskets. Round 48 (trading: 1%-risk sizing on the five seated roster cards) — marginal −4.42pp; worst windows and IQRs roughly halved on 4 of 5 bases with realised P&L roughly halved alongside — a risk dial, not an edge. **On the owner's instruction of 2026-09-09 to promote according to the rounds' results, three cards were copied verbatim to the library: `r44-power-trim` → `candidates/` (roth; median +9.16pp, 7/8 hit, 8/8 windows; inside the floor by a factor of nine for its basket-minus-control margin and its positive is utilities' defensive beta), `r45-kim-risk1pct` → `variants/` (trading; the one-decision 1%-risk variant of the seated `r40-rsi-confirm-slots6`, to be tracked against its base under §7), and `r46-both` → `allocation/` (savings; +2.45pp drawdown margin, MAR +0.009, the best within-budget savings cell of rounds 38-46).** Each satisfies at most the letter of §6 and none its condition (b); as with `C-trend`, `r34-ma-crossover-on` and `r40-rsi-confirm-slots6`, their standing rests on the owner's decision, not the scorecard, and a reader must not mistake their presence for evidence they do not have. **No desk roster changed**: `AGENT_IDS`, `SAVINGS_AGENT_IDS` and `ROTH_AGENT_IDS` are as before; seating any of the three, or resizing the seated trading cards per round 48, is an explicit owner decision the rounds inform but do not make. |
