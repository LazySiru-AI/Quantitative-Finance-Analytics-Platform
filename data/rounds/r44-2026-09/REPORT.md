# Round 44 — report: no thematic basket or profit-trim clears the floor; the one positive is utilities' defensive beta, not a theme

Run 2026-09-09, eight main windows, 10 cards (5 baskets × 2 arms), 80 runs, zero `FAILED` lines.
Pre-registration: `strategy-program/ROUND-44-PLAN.md` (2026-09-09, frozen in commit `628b5e3` before
the run). Computed tables: `ANALYSIS.md`, from `strategy-program/tools/round44_report.py`, mirrored in
`analysis.json`. Scorecard: `scorecard.json` (`score.py --pin-store`). All cards `purpose = roth`,
universe disjoint from the taxable book (`disjoint_field.py`: 10/10, eligible 8/8). The run used a copy
of `run_round.sh` whose only change was a stricter process-liveness guard (the original tripped on two
orphaned shells from another session whose command text mentioned a tournament module).

**Not investment advice.** Price-only bars, no dividends — which understates every utility and defense
name here, all high payers — SPY benchmark for a Roth book, a synthetic paper book. The baskets are
this programme's proxies for themes voiced in the persona discussion
(`strategy-program/PERSONA-DISCUSSION-2026-09-09.md` §3: Creator A's power-bottleneck and defense
themes, Creator D's electricity-infrastructure and memory-semiconductor themes, Creator C's
semiconductor super-cycle, Creator B's EM/energy/commodities rotation and his trim-the-winners
discipline); none of the personas named these exact tickers as a basket, and no influencer is endorsed.

---

## 1. Result — null on both pre-registered questions

**Question 1, basket:** basket-passive minus control-passive (`VTV SPYG RSP MDY`, held passively).

| basket | 8-window median diff | six fair windows (≤2022-10) | two hindsight windows (2024-26) | windows basket>control | p (sign-flip) | BH q (m=10) |
|---|---|---|---|---|---|---|
| power (NEE DUK SO CCJ) | **+8.01pp** | **+9.40pp** | +0.03pp | 6/8 | 0.086 | 0.43 |
| defense (LMT NOC GD RTX) | +0.33pp | −0.40pp | +1.12pp | 4/8 | 0.68 | 1.00 |
| semicap (AMAT KLAC LRCX ASML) | −0.23pp | +0.39pp | **+68.68pp** | 4/8 | 0.69 | 1.00 |
| realassets (XOP XME EWY VWO) | −4.13pp | −5.39pp | +20.38pp | 2/8 | 0.97 | 1.00 |

**Question 2, rule:** trim (`exit when close > sma(200) × 1.15`) minus passive, within basket.

| basket | 8-window median diff | six fair windows | two hindsight windows | windows trim>passive | p (sign-flip) |
|---|---|---|---|---|---|
| power | +2.36pp | +4.69pp | +0.33pp | 6/8 | 0.031 |
| defense | +0.76pp | +0.83pp | +0.38pp | 4/8 | 0.125 |
| semicap | +0.36pp | +1.55pp | **−66.85pp** | 5/8 | 0.94 |
| realassets | +0.73pp | +0.00pp | −16.09pp | 2/8 | 0.34 |
| control | +0.00pp | +0.00pp | +0.81pp | 1/8 | 1.00 |

Minimum BH q over all 10 cells against `r44-control-passive`: **0.39** (`r44-power-trim`, median diff
+10.37pp, p 0.039). **Decision rule (plan §4), applied:** an edge required a margin above the 21.2pp
floor AND BH q<0.10. No cell meets either half. **The null is the result on both axes.** Nothing is
promoted; §6's two-round rule was never in reach and the plan pre-registered that nothing would move.

## 2. What the numbers do say, short of a finding

1. **The power basket is the only consistent positive, and it is a beta story.** +8.0pp over the
   control, 6 of 8 windows, and — the part that matters — **+9.4pp on the six fair windows** with
   essentially nothing (+0.03pp) in the two hindsight windows. So it is not the 2024-25 "AI power"
   trade the personas were describing; that trade did not show up at all in `bull-2024`/`recent`
   (power-passive posted −9.29pp in `recent`). What did show up is `q4-2018` +22.5pp, `gfc` +14.4pp,
   `bear-2022` +12.2pp: regulated utilities fall less than SPY in selloffs, and `adjusted_excess`
   credits a near-fully-invested low-beta book in exactly those windows (PROTOCOL §4's exposure
   caveat, with exposure 0.99). That is the same thing round 29 found as its sole "survivor" — an asset
   class's beta, not a rule — and it argues for nothing except that utilities are utilities. At q=0.43
   it does not survive the correction either.
2. **The semicap basket is the cleanest hindsight demonstration this programme has produced.** On the
   six fair windows it is indistinguishable from the control (+0.39pp). In `recent` alone it posts
   **+152.63pp** adjusted excess, and the trim arm — which stepped out of names 15% above their 200-day
   mean — gave up **134.61pp** of that single window. The plan pre-registered (§5 #3) that a positive
   confined to the 2024-26 windows is the claim's own hindsight; this is that prediction holding in the
   most extreme form available. The basket's `bear-2022` print (−22.39pp) is the other side of the same
   concentration.
3. **The realassets basket is negative everywhere that is fair** (−5.39pp on the six windows, worst
   window −23.53pp, only 2 of 8 above control) and positive only in `recent` (+42.28pp). Creator B's and Creator C's rotation thesis, as a passive basket, has been a drag in every regime
   before 2025 on these four funds.
4. **Defense is a null of the plain kind**: ±1pp against the control whichever window subset is read,
   hit rate 4/8, one large window (`bear-2022` +34.1pp) offset by two large negatives (`covid` −13.3pp,
   `q4-2018` −6.9pp).
5. **The trim rule does what a trim rule does and earns nothing for it.** In every basket it lowers
   exposure (0.79–0.90 vs 0.96–0.99), raises trade count (66–87 vs 32), shallows the worst drawdown by
   1–4 points (power −40.9% vs −44.6%; semicap −64.6% vs −67.2%) and moves the 8-window median by
   +0.4 to +2.4pp — a tenth of the floor at best. Its one near-unanimous read (power, 6/8, p=0.031) is
   the same low-beta effect as item 1 with a little less exposure, and q=0.39 says so.

## 3. Predictions vs outcomes (plan §5)

| # | prediction | outcome |
|---|---|---|
| 1 | No basket beats control by >21.2pp with BH q<0.10 | **HELD** — best +8.01pp, q 0.43 |
| 2 | No trim arm beats its passive by >21.2pp with BH q<0.10 | **HELD** — best +2.36pp |
| 3 | Hindsight split: any positive confined to 2024-26 is hindsight; no basket clears the floor on the six fair windows either | **HELD, vividly** — semicap +68.7pp on the two hindsight windows vs +0.4pp fair; power's +9.4pp fair margin is inside the floor |
| 4 | Trim exposure falls most in semicap, least in power | **HALF HELD** — lowest is semicap (0.794) as predicted; highest among themed baskets is power (0.902), but the control (0.963) is higher still, which the prediction did not anticipate because the control's names are rarely 15% extended |
| 5 | In `bull-2024` and `recent` the trim arm underperforms its passive in every basket | **REFUTED** — trim lost in `bull-2024` in every themed basket but *won* in `recent` for power (+1.37pp), defense (+1.94pp) and the control (+1.97pp); it lost catastrophically in `recent` only where the run-up was extreme (semicap −134.6pp, realassets −30.2pp) |
| 6 | In `bear-2022` and `gfc` the trim arm may shallow the drawdown | **HELD for 7 of 8 basket-window pairs** — trim beat passive in `gfc` in all four themed baskets (+1.7 to +5.9pp) and in `bear-2022` in three (realassets −8.0pp the exception) |
| 7 | Validity: every passive control holds all four names on essentially every session | **HELD** — passive exposure 0.956–0.990; the control 0.965 |

## 4. Disposition

- **Nothing promoted, nothing seated.** `r34-ma-crossover-on` remains the Roth book's only
  directed-candidate seat; this round adds no candidate and its result argues against one. For the
  power basket specifically: a low-beta sector's drawdown cushion is not a strategy this programme can
  promote — it is the asset class, exactly the reading round 39 gave its passive growth/core baskets.
- Files: `cards/`, `results/<window>/runs/`, `scorecard.json`, `ANALYSIS.md`, `analysis.json`,
  `score.log`, `run.log`.

## 5. What this round cannot settle

- **No dividends.** NEE/DUK/SO and LMT/NOC/GD/RTX are high-yield names; every passive and trim return
  here is understated by the yield, and relative to a SPY benchmark that is also dividend-free the
  direction of the bias on `adjusted_excess` is not known without a total-return store.
- **Four names are not a theme.** A result about NEE/DUK/SO/CCJ is a result about those four survivors;
  the "AI power bottleneck" as the personas meant it (data-centre load growth, nuclear restarts) is
  unobservable in price bars and untested here.
- **Survivorship.** Every individual name was chosen in 2026 from among companies that still exist and
  still carry the theme; the ETF baskets (XOP XME EWY VWO, VTV SPYG RSP MDY) are mechanically defined
  and do not share this bias.
- **Hindsight is unbounded and, on the semicap basket, visibly enormous.** The six-window split was the
  pre-registered remedy and it worked as a reading aid, but it bounds nothing about the personas'
  knowledge of 2007-2022 — `published = null` on every note.
- **One trim threshold.** 1.15 was a round number chosen for reachability; the plan said so, and this
  round does not claim the trim result is insensitive to it.
- **Roth-to-roth overlap.** AMAT/KLAC/LRCX/XOP/XME are also held by other roth-purpose library cards,
  which is legal under the disjointness rule; it means this round's semicap and realassets baskets are
  not independent evidence about those names relative to the library's existing Roth cards.
