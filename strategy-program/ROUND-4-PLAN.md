# Round 4 — plan, and the field it runs

Three rounds have run. The field has grown to 35 distinct cards, most of which have been measured
enough to say something about. This plan trims it, records **why** each card is dropped, and states
what round 4 is actually for.

## 1. The finding this plan is built on: combine, don't diversify inside

The question that prompted it: is 5–6 tickers too concentrated for a whole book?

Measured on what the desks actually hold: **yes, and worse than the count suggests.**

| desk | held | share of equity | mean pairwise ρ |
|---|---|---|---|
| `C-trend` | NVDA, AVGO, TSM, SOXX | **73.6%** | **0.765** |
| `B-momentum` | MSFT, AMZN, NVDA, AVGO, TSM | 75.1% | 0.586 |

`SOXX` is a semiconductor ETF holding NVDA, AVGO and TSM — so one of C-trend's four positions is a
basket of the other three. At ρ = 0.77 those four names are close to one bet carrying three quarters
of the book. Neither universe fixes this: B-momentum's whole 12-name universe averages ρ = 0.488,
C-trend's nine average 0.523. **More slots would buy more of the same trade**, which is why the
position cap is not the lever — and measurably so: across 55 sessions neither book ever filled its
last slot, and not one entry signal was ever turned away for lack of room.

**But diversifying inside a card did not work either.** Round 3 tested it directly. `c16-dispersion-wide`
was built for breadth — one name per sector, ρ = 0.245, less than half these books — and finished
7th of 10 on adjusted excess with a −9.6% worst window. Meanwhile `c14-riskmanaged-wide`, holding
**four** names, took the round's best worst-window (−1.0%) and best hit rate (75%).

The difference is not count. It is payoff. `c14` holds TLT, IEF, GLD, LQD — instruments that rise
when equities fall.

### Combining the three desks, measured

Equal thirds, rebalanced per window, a card that cannot run its window held as cash:

| window | SPY | B-momentum | C-trend | c14 | ⅓ each | excess |
|---|---|---|---|---|---|---|
| `gfc` | −56.2% | *ineligible* | *ineligible* | −3.4% | −1.1% | +55.1% |
| `covid` | −8.7% | +22.9% | +15.9% | +2.3% | +13.7% | +22.4% |
| `bear-2022` | −25.1% | −6.8% | −7.0% | +0.6% | −4.4% | +20.8% |
| `q4-2018` | −20.0% | −0.9% | −1.8% | +0.0% | −0.9% | +19.1% |
| `chop-2011` | −0.0% | *ineligible* | *ineligible* | +2.7% | +0.9% | +0.9% |
| `chop-2015` | −0.0% | +24.6% | +11.0% | −1.0% | +11.5% | +11.6% |
| `bull-2024` | +14.0% | +15.2% | +22.8% | +3.4% | +13.8% | −0.2% |
| `recent` | +20.6% | +24.3% | −2.2% | +6.6% | +9.5% | −11.1% |

**Combined: median excess +15.4%, worst window −11.1%, hit rate 75%, and it runs all eight windows.**

Two things that matters for, and one caveat that guts part of it.

**It halves the worst case.** `C-trend` alone posts a −22.9% worst window; the combination is −11.1%.
The per-window return correlations explain why: `C-trend` vs `c14` is **ρ = +0.04** — effectively
uncorrelated — while `B` vs `C` is +0.57, two versions of the same trade.

**It restores crisis coverage.** `B-momentum` and `C-trend` hold META (2012) and AVGO (2009) and are
structurally ineligible for `gfc` and `chop-2011`. `c14` is not. The portfolio can be measured in the
crisis; neither base strategy can.

**The caveat: the crisis excess is mostly non-participation.** In `gfc` the combined book is two
thirds cash by construction, so +55.1% "excess" is overwhelmingly the D2 artifact this programme has
now hit three times. Read the bear-market columns as *"did not lose"*, not as *"made money"*. The
combination's honest claim is a halved worst window and eight-window coverage — not crisis alpha.

**The portfolio question is now the open one.** Every round so far has scored cards individually.
The strongest result available is that an uncorrelated pairing beats either leg on worst-window, and
nothing in the protocol scores that.

## 2. What round 4 is for

1. **Score the portfolio, not just the cards.** Add a combined-book measurement to the scorer: for a
   named set of cards, the equal-weight (and exposure-weighted) per-window result, its worst window,
   and the pairwise correlation matrix that explains it. This is the first genuinely new question
   since round 1.
2. **Settle `B2-hold-90`.** It has beaten its own base on adjusted excess (+16.3% vs +12.2%) and is
   the only variant that has. §6 needs a second round on *new* windows before it can replace B.
3. **Give the base strategies crisis coverage.** Both bases fail the two hardest windows on universe
   history alone. A `B`/`C` re-cut whose universe reaches 2004 is worth one pre-registered attempt —
   `B-wide` and `C-wide` were exactly that and ran all eight, so the mechanism is proven; what is not
   settled is whether a re-cut on *thesis* rather than on dollar volume does better.
4. **Confirm `c14`.** One round, on the frontier. §6 requires two on differing windows.

## 3. The field: 10 returning cards, not 35

### Kept, and why

| card | tier | median adj. excess | worst | hit | why it stays |
|---|---|---|---|---|---|
| `B-momentum` | base | +12.2% | −5.1% | 67% | Incumbent. Best median in the field on the windows it can run. |
| `C-trend` | base | +5.0% | −7.3% | 50% | Incumbent, and the leg `c14` is uncorrelated with (ρ = +0.04). |
| `B2-hold-90` | variant | **+16.3%** | −5.1% | 67% | The only variant to beat its base. Needs round two to promote. |
| `B3-concentrated` | variant | +13.9% | −7.8% | 67% | Tests the concentration axis directly — the live question. |
| `B4-tight-stop` | variant | +11.1% | **−4.0%** | 67% | Best worst-window of the B family. |
| `c14-riskmanaged-wide` | candidate | +2.3% | **−1.0%** | **75%** | Pareto frontier. The uncorrelated leg. Confirmation round. |
| `c09-convex` | candidate | +1.2% | −3.3% | 75% | Convex payoff, low exposure (0.08). A different shape from everything else. |
| `c07-chop` | candidate | +2.7% | −15.6% | 62% | Best median of the non-B candidates; the sideways-regime specialist. |
| `c11-breakout` | candidate | +2.0% | −4.7% | 62% | 37 trades across 8 windows — the most selective card that still ranks. |
| `H-trend-diversified` | candidate | +3.1% | −8.8% | 67% | The cross-asset trend book, at 0.18 exposure. Same family of idea as `c14` — trend applied off the equity complex — and §1 makes that family the round's central question. |

Plus **4–6 fresh analyst cards**, briefed on the portfolio question rather than on standalone median.
Target field: **14–16**, against round 2's 26.

### Dropped, with the reason for each

Every drop below rests on **two rounds** of measurement or on a structural fact, never on one bad
window. Cards move to `library/retired/` and stay on disk; the reasoning is logged in
`library/retired/README.md`.

**The A family — 5 cards, retired together.**
`A-rotation` (−7.2%), `A1-alpha-order` (−4.8%), `A2-cash-headroom` (−9.2%), `A3-no-target` (−2.9%),
`A4-tight-stop` (−7.3%). Every one posts a **negative median adjusted excess**, a worst window
between −22.8% and −30.0%, a 43% hit rate, and the **highest capital exposure in the field** (≈0.48).
That combination is the specific thing this programme was built to detect: they look acceptable on
raw return because they are heavily invested in a rising market, and they lose once that exposure is
paid for. The four variants exist to attribute one decision each against `A-rotation`; with the base
itself demoted and negative, there is no longer a baseline for them to attribute to.

**Negative after exposure correction, two rounds:**
- `c02-volatility` (−1.3%, hit **12%** — positive in one window of eight)
- `c03-breakout` (−3.1%, hit 25%)
- `c04-riskmanaged` (−1.5%, hit 25%, exposure 0.45 — the name promises risk management the numbers do not show)
- `c08-generalist` (−0.6%, exposure **0.59**, the highest in the field)
- `c15-volatility-wide` (−1.2%, worst −20.8%) — and its thesis was **falsified**: its memo predicted `gfc` as its worst window and it came back its best, which round 3 showed was survivorship, not skill
- `c17-defensive-trend-wide` (−0.6%, hit 38%)

**Not a strategy, a spectator:** `c12-meanrev-wide` (−0.1%, **17 trades across eight windows**, mean
exposure **0.02**). A book that is 2% invested is not being tested; whatever it does is noise around
cash, and its +55.3% raw `gfc` excess on a single trade is the clearest illustration in the project
of why raw excess is the wrong headline.

**Dominated within its own family:** `B1-with-target` (+4.6%, hit 50%) — beaten by `B2`, `B3` and
`B4` on median *and* hit rate, having tested the take-profit decision that `B-momentum`'s own memo
already argued against with pre-registered evidence. The question is answered.

**Near-zero and dominated:** `c01-meanrev` (+0.4%), `c05-trend` (+0.2%), `c10-momentum` (+0.4%),
`c16-dispersion-wide` (+0.3%). None is broken; each is beaten on all three axes by a card already
kept in the same discipline. `c16` is the painful one — it was the deliberate breadth experiment and
it answered its question in the negative, which is a finding worth keeping in the report even though
the card is not worth another slot.

**Structurally unrankable:** `E-asymmetric` (1 window), `F-fastrev` (2), `G-volatility` (3). All
below the 5-of-8 eligibility gate, and their universes are fixed, so no amount of re-running changes
that. `G-volatility`'s +12.6% over three windows is genuinely interesting and genuinely unrankable;
it is retired **as written**, with an explicit invitation to resubmit a re-cut whose universe reaches
2004. The store now has 380 symbols that do, against 86 when it was designed.

**Provenance-constrained:** `c06-13f-momentum` is legal only in `13f-legal`, so it can never clear a
gate defined over the eight regime windows. It stays retired and is the standing worked example for
the provenance rule.

**Not carried:** `B-wide`, `C-wide`, `c13-breakout-wide`. These were round 3's controlled arm and its
breakout entry; they did their job — establishing that a mechanically-widened universe changes
nothing detectable — and are not strategies anyone proposed keeping. Their result is recorded in
round 3's report.

## 4. What has to change in the harness first

- **The scorer needs a portfolio mode.** Nothing currently computes a combined book. §1's table was
  produced by hand; it should be a function in `tools/score.py` with the correlation matrix beside it.
- **Ranking must compare like with like.** `B-momentum`'s +12.2% is over six windows and `c14`'s
  +2.3% is over eight, including the two hardest. Round 3's report flagged this; round 4 should score
  a common-window column explicitly rather than leave the caveat in prose.
- **Adjusted excess becomes the headline.** Three rounds running, raw excess has told a flattering
  story that exposure correction dissolved. The `/competition` leaderboard still ranks on plain
  excess by default.
