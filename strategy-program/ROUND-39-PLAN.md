# Round 39 — does a style tilt survive where a sector tilt did not?

**Pre-registered 2026-09-09, before any card in this round has been run. Nothing below was written
with sight of a result. As of this writing the round has NOT been run: no card in
`data/rounds/r39-2026-09/cards/` has produced a single run file, and there is no
`data/rounds/r39-2026-09/results/` and no scorecard.**

Not investment advice. Every number this round will produce is a backtest on price-only bars with no
dividends and no coupons, measured against a US large-cap benchmark, on a universe of index-provider
bundles whose construction rules this round does not control. The honest prior is in §6: the most
likely outcome is that every tilt-minus-control margin, and the style spread itself, land inside the
21.2pp noise floor.

---

## 1. The question, and why it is not a re-run of anything

**Does a *style* tilt — value, equal-weight and mid-cap against growth — carry information where a
*sector* tilt did not?**

This programme has run the same question along four axes and returned the null every time:

| round(s) | what was varied | measured marginal | floor | verdict |
|---|---|---|---|---|
| 17, 18 | rule form, regime filter, bracket policy, on nine sector SPDRs | every marginal inside the floor | 21.2pp | null |
| 34 | rule form on eight disjoint **industry** ETFs | **4.21pp** form marginal, 0.88pp regime marginal | 21.2pp | null — and *tighter* than round 17's own slice |
| 35 | rotation on eight disjoint **country** ETFs, against a passive control | **+0.08pp** best cell minus control | 21.2pp | null |
| 36 | `rank_by` — which name takes a scarce slot | **+1.22pp / +1.01pp** | 21.2pp | null; q 0.40 / 0.52 |

(Source: `strategy-program/DISJOINT-SECTOR-FAMILY.md` §5a. Minimum BH q anywhere in that family: 0.40.)

Every one of those varied the **rotation mechanism**: which rule fires, whether a regime filter gates
it, how many slots there are, which qualifying name takes one. **No round in this programme has ever
varied the style/factor axis of the basket itself.** Nor have the Roth studies: `ROTH-MOMENTUM.md`
varies timing rules (absolute momentum, dual momentum, MA regime, confirmed regime) on a fixed
QLD/SCHD/IEF/GLD sleeve set; `ROTH-VOLTARGET.md` varies *sizing* rules (vol targeting, inverse vol,
circuit breaker, risk-budgeted core) on the same sleeves; `ROTH-DISJOINT-LADDER.md` varies *which
tickers express one fixed ladder* and reports the cost of the substitution. All three hold the style
of the book constant and vary the rule. **This round is the mirror image: it holds the rule constant
and varies the style of the book.** That is what makes it a new measurement rather than round 34
under a different name.

**Round 34's verdict is the honest prior, and it is stated here before the run.** The same eight rule
forms produced a 4.21pp form marginal on industry ETFs — *tighter* than on sectors, not wider — and
every margin in rounds 34–36 sat inside the 21.2pp floor. The default expectation for round 39 is the
same null.

**Why this axis might nonetheless differ.** Sector leadership rotates on a business cycle: energy
leads for eighteen months, then technology, then staples. Style spreads do not behave that way —
value's underperformance against growth ran, on the common telling, for most of a decade without
mean-reverting. A slow-moving spread is a different kind of object from a fast-rotating one, and a
tilt held across it is a different bet from a rotation through it. That is the one structural reason
to expect a different answer here, and it is why this round measures the tilt **passively** (§3b)
rather than only through a rule: if the style spread is real and persistent, it shows up in a
buy-and-hold of one slice against a buy-and-hold of another, with no rule involved at all.

**The second reason this round exists on this universe is legal.** These cards carry
`purpose = Purpose.ROTH`, and §6 of `THREE-PURPOSES-PLAN.md` requires that no symbol traded by a
roth-purpose card appear in the universe of any `savings`- or `trading`-purpose card. That is not
tidiness: Rev. Rul. 2008-5 does not *defer* a wash-sale loss when the replacement is bought inside an
IRA, it **destroys** it outright, with no basis adjustment anywhere. Broad factor and style ETFs are
one of the few liquid groups still fully unclaimed by the taxable book, and this round joins the
disjoint family (`DISJOINT-SECTOR-FAMILY.md`) as its "Factor / broad" branch.

## 2. The universe, pinned before anything was measured

The pinned pool is **eight** names:

`VTV SPYG RSP MDY VTI IBB TIP IAU` — Vanguard Value, S&P 500 Growth, S&P 500 Equal Weight, S&P
MidCap 400, Vanguard Total Stock Market, Nasdaq Biotech, iShares TIPS, iShares Gold.

**Seven are traded. `IAU` is held out of every card — see §2b.**

First stored daily bars, as reported by `strategy-program/tools/windows.py` against the live store on
2026-09-09: `MDY` 1995-05-04, `SPYG` 2000-10-02, `IBB` 2001-02-12, `VTI` 2001-06-15, `RSP`
2003-05-01, `TIP` 2003-12-05, `VTV` 2004-01-30, `IAU` 2005-01-28. `VTV` is the binding symbol among
the traded seven and it clears the `gfc` window (2007-10-09) with a 200-day indicator by more than
three years. **Verified, not asserted:** `windows.py --cards` reports all eight cards eligible in
**8 of 8** main windows (§8).

Selection criteria, both applied before any result existed and neither of them a return:

1. **Enough stored history to clear every main window**, `gfc` included — the eligibility gate of
   `WINDOWS.md`. This is why `MTUM`, `QUAL`, `VLUE`, `USMV` and `SPLV` — the obvious pure-factor ETFs
   — are absent: every one of them launched after 2010 and holds zero bars in `gfc` and both chop
   windows (`DISJOINT-SECTOR-FAMILY.md` §4 lists them under "too young"). A zero-bar symbol does not
   merely contribute nothing, it fails the whole card (round 17's amendment 1). The style axis
   therefore has to be expressed through older, blunter instruments, and it is.
2. **Total absence from the taxable book.** `strategy-program/tools/round39.py` recomputes the
   claimed set from the live library on every run, through
   `app.evolution.promotion._library_cards(get_settings())` — the same function the application uses
   at promotion time, which walks all six tiers including the `allocation/` and `ladder/`
   directories `app.tournament.results.load_library` does not, and where five taxable tickers
   (`AGG`, `BIL`, `QLD`, `SCHD`, `SGOV`) live exclusively. As of 2026-09-09 that set is **84 tickers
   across 39 savings/trading cards**, and the tool **refuses `--write`** if any of them intersects
   this round's traded names or if `find_disjointness_violations` returns anything naming one of this
   round's cards.

### 2a. Where the hypothesis came from, and what it is not

The app's influencer vault (`data/vault/influencers/`, models in `backend/app/personas/models.py`)
carries a persona, `creator-b` ("Creator B의 과학적 투자", 40 notes). Its consolidated profile
(`data/vault/influencers/creator-b/profile.md`) states two theses repeatedly. Under *Methodology*:
"Using relative valuation methodology with comparable company multiples such as P/E and P/B ratios to
determine fair value and establish appropriate safety margins for entry decisions." Under *Beliefs*:
"Ten years of US equity stagnation similar to the 1966-1982 Dow period is likely, driven by
structural reversal of four post-1982 tailwinds: deregulation reversed to regulation, hawkish Fed
replaced by accommodative Fed, globalization reversed to de-globalization, and aging demographics
straining fiscal capacity." Its *Regime* summary names "Rotation from expensive mega-cap technology
toward commodities, emerging markets, semiconductor infrastructure, and energy."

**Neither thesis is expressible as stated, and this round does not pretend otherwise.**

- **The valuation method is unreachable.** This repository has no fundamentals store. There is no
  P/E, no P/B, no book value, no earnings, and no mechanism for normalising a one-off restructuring
  charge anywhere in the bar store. A round here reads OHLCV and nothing else. No design in this
  programme can test a relative-valuation claim, and none is attempted.
- **What is expressible is the portfolio expression of the second thesis** — a value / equal-weight /
  mid-cap tilt measured against a growth tilt, plus an inflation-linked sleeve. **That is a proxy for
  a fundamental claim, not a test of it.** A null here would not refute the persona's method; it
  would say that the cheapest long-only portfolio expression of one limb of it carried no measurable
  information on these eight funds over these eight windows.
- **A factor ETF is a bundle whose construction rules this round does not control.** `VTV` is "value"
  because an index provider's screen says so; `SPYG` is "growth" because S&P's growth screen says so;
  `RSP` is equal-weight by rule and `MDY` is mid-cap by a size cutoff. Every one of those definitions
  was set elsewhere, is revised on a schedule invisible in these bars, and can drift under a fixed
  ticker. A result here is a result about *these funds*, not about the value premium.
- **The corpus supplied the hypothesis; no influencer is endorsed.** The persona's own stated
  positioning disagrees with parts of this field: its profile lists "Bonds and fixed income (negative
  real rates, financial repression)" under `sectors_avoided`, which is an argument against the `TIP`
  sleeve this round nonetheless carries, and it simultaneously expects roughly 40% of further AI-led
  upside over two years, which is an argument against the growth-loses framing over any short window.
  The round tests the ten-year structural-stagnation limb as a portfolio, not the persona's book.

### 2b. `IAU` is in the pool and is traded by nothing — the call, and what it costs

**Decision: `IAU` is held out of every card in this round.**

`IAU` is physical gold. The taxable book holds `GLD`, which is also physical gold. Different ticker,
different sponsor, different expense ratio — and the same underlying asset. In the plain terms
`ROTH-DISJOINT-LADDER.md` §2 uses: *"Two different tickers can still be substantially identical — a
fund and a share class of the same fund, or arguably two 2× funds tracking the same index under
different names."* Two grantor trusts each holding allocated bullion are a closer pair than either of
those examples. This is the textbook case, and ticker disjointness does not reach it.

Three reasons the hold-out is the right call rather than the cautious one:

1. **The family already made this call in writing.** `DISJOINT-SECTOR-FAMILY.md` §4 excludes `IAU`
   from the family's ETF pool by name — "`IAU` is physical gold, the same underlying as taxable
   `GLD` — the textbook substantially-identical pair — and is EXCLUDED from this pool" — on the
   grounds that "a family whose whole premise is avoiding §1091 exposure should not open with its
   cleanest example of it". Trading it here would put this round in direct contradiction with the hub
   document of the family it joins.
2. **These rosters get seated.** Round 34's card was promoted to `candidates/` and seated on the live
   Roth paper book on 2026-09-09, the same day it was measured (`PROTOCOL.md` §9). A roster authored
   in this family is a roster that can end up holding real attention, so "it is only a backtest" is
   not available as a defence.
3. **The mechanical harm is asymmetric.** If the two funds are not substantially identical, holding
   `IAU` buys this round one more sleeve. If they are, a `GLD` loss harvested in the taxable book
   inside a 61-day window of an `IAU` purchase in the Roth is *destroyed outright*, with no basis
   adjustment anywhere. A small upside against an unrecoverable downside is not a close call.

**What it costs, stated rather than hidden: this round carries no hard-asset sleeve, so the
commodity/gold limb of §2a's hypothesis is not tested at all.** Only the style limb is, plus a single
inflation-linked instrument (`TIP`) that is a much weaker expression of "inflation is inevitable"
than gold would have been — and one whose price-only bars strip the coupon and the inflation accrual
that are most of what a TIPS fund actually pays (§7). The round's title question is about style, and
that is the question it can answer; the hard-asset question is left open for a round that can find a
GFC-eligible, taxable-disjoint hard-asset instrument that is not gold.

**Nothing here is a §1091-safety claim.** Ticker disjointness is *necessary, not sufficient*, exactly
as `app.tournament.purposes` says in its own docstring. What the disjoint roster guarantees is that
no *identical* security is ever repurchased across the two books — the failure mode that is both
mechanical and catastrophic. Whether any particular pair is "substantially identical" is a question
about holdings and a matter for a tax adviser, not for this document.

### 2c. Three names that overlap the S&P 500 the taxable book trades

`VTI` (total US market), `RSP` (S&P 500 equal-weight) and `SPYG` (the S&P 500's growth half) all
hold, in large part, the same companies as `SPY` — which the taxable book trades. **Economically
close, mechanically disjoint**, and stated here rather than left to be noticed.

The three differ from `SPY` in ways that are real and not cosmetic: `VTI` holds roughly four times as
many securities including the entire small-cap tail; `RSP` holds the same 500 names at 0.2% each,
which is a different portfolio from the same names at cap weight and behaves differently enough that
the industry treats it as a distinct factor exposure; `SPYG` holds roughly half the index by count.
None is a share class of `SPY` and none tracks `SPY`'s index. That is the argument, and it is weaker
than the `IAU`/`GLD` case is strong — which is precisely why §2b resolves the clear case by exclusion
and this section resolves the unclear ones by disclosure. A reader who concludes that `RSP` and `SPY`
are substantially identical should read every figure in this round as inapplicable to a Roth book
that sits beside a taxable `SPY` position, and should take that question to a tax adviser rather than
to this file.

`IBB` is also already a `roth`-purpose ticker elsewhere in the library's disjoint pool, and `VUG`
(Vanguard Growth) sits in the existing roth union beside `SPYG`. Roth-to-Roth overlap is legal and
creates no wash-sale exposure of this kind; only the roth-versus-taxable boundary binds.

### 2d. The slices are not independent bets

`VTI` contains, by construction, every name in `VTV`, `SPYG`, `RSP` and `MDY`. `RSP` and `SPYG` hold
the same 500 companies as each other at different weights. `IBB`'s largest constituents appear in
`VTI`. So this field is being run over a roster with heavy internal redundancy, and the four slices
overlap each other rather than partitioning anything.

**How that is handled: it counts against the field and nothing is added to compensate.**
Benjamini-Hochberg correction runs over **every cell this round runs** (`PROTOCOL.md` §3 rule 8 — the
denominator is everything tried, never a subgroup), and correlated cells spend denominator while
buying no extra evidence. The wrong response would be to add cells or names to "cover" the
redundancy; the field stays at eight, and the redundancy is reported as a reason any surviving margin
should be read smaller than it looks.

## 3. The field — 4 universe slices × 2 arms = 8 cells

Authored by `strategy-program/tools/round39.py`. **No grid search**: exactly one rule is used, at
periods transplanted from a module frozen before this round was conceived, and nothing in this field
was chosen by looking at an outcome.

**The one fixed rule**, rendered by `app.evolution.ruleforms.render("ma-crossover", fast=10, slow=30,
regime_ma=200)` rather than typed into the tool, so the round uses the evolution loop's own
vocabulary rather than a second, drifting copy of it:

```
entry: close > sma(200) and ema(10) crosses_above ema(30)
exit:  ema(10) crosses_below ema(30)
```

This is the loop's most-evidenced form — generations 1–1915 ran this one template and all 28 of the
loop's promotions came from it — at the periods rounds 17, 18, 34 and 35 all used.
`ruleforms.classify` reads it as `trend`, and that derived label is what each card carries.

**The four slices.** Every ticker is classified once, on what the fund *is*, and no ticker is
stretched to balance the arms:

| slice | names | what it is |
|---|---|---|
| `value` | `VTV RSP MDY` | large-cap value, the S&P 500 equal-weighted away from its mega-cap concentration, and the S&P MidCap 400 — the long side of the structural-stagnation claim |
| `growth` | `SPYG IBB` | the S&P 500's own growth half and Nasdaq biotech, the longest-duration equity sleeve in the pool — the side the thesis says loses |
| `core` | `VTI TIP` | the cap-weighted total US market (the neutral position a tilt is a tilt *away from*) and inflation-linked Treasuries (the "inflation is inevitable" limb) |
| `full` | all seven | the undivided book |

**The two arms.** For each slice, one **tilt** card running the fixed rule, and one **passive
control** running `close > 0` / `close < 0`. Both arms hold **every name in their slice**
(`max_positions = len(slice)`), at the same size, with the **same brackets — none** (§3c). The two
arms therefore differ in **exactly one thing**: whether the timing rule is applied. That is
`PROTOCOL.md` §7's one-decision requirement, applied strictly.

**Sizing: every card in the field targets the same 84% maximum deployed capital.** `value` 3 × 0.28,
`growth` and `core` 2 × 0.42, `full` 7 × 0.12. 0.84 is the one budget below 1.0 that divides exactly
by all three slice sizes, so no cell is rounded to a different book size than its neighbours. This is
what makes a cross-slice comparison a question about *style* rather than about how much money is in
the market, and it keeps every cell clear of `PROTOCOL.md` §4's 2× exposure-divergence flag by
construction rather than by luck.

**This field has no slot contention anywhere.** Every card has a slot for every name it holds, so
`rank_by` is unset on all eight cards, no name is ever chosen over another, and the ordering artifact
`PROTOCOL.md` §7 measures at σ = 21.2 points **cannot operate in this round at all**. That is a
deliberate simplification: round 36 already measured `rank_by` on the industry universe and found
+1.2pp, inside the floor, so re-testing it here would spend denominator on a settled question. It
does **not** lower the floor — the floor is the programme's stated threshold for what counts as a
finding, one round cannot relitigate it, and every margin below is measured against 21.2pp.

### 3a. The slice asymmetry, and why it is left in

`value` holds three names and `growth` holds two. That asymmetry is real. It is left in rather than
papered over by promoting `VTI` to the growth arm, because calling the cap-weighted total US market
"growth" would confound the style axis with plain market beta — the thing every slice already has —
and would make the one comparison this round exists to draw uninterpretable. Likewise `TIP` is not
put on either tilt arm: it is not a style, and placing it on one side would confound style with asset
class.

The cost of leaving it in: the `value` book is spread across three funds and the `growth` book across
two, so the growth arm is the more concentrated of the two at the same 84% budget, and any
difference between them contains a breadth component this round cannot separate from the style
component. That is a real limitation and it is in §7's list.

### 3b. The passive controls — two jobs, and the second one is the round's actual question

```
entry: close > 0        (true on every bar)
exit:  close < 0        (true on none)
no stop, no target, no time stop, one slot per name, 84% of capital
```

Round 35 ran both expressions through `app.backtest.guards.check` against real bars before authoring
its own control; **both pass**, and its nine cards then ran 8 of 8 main windows with zero `FAILED`
lines (`DISJOINT-SECTOR-FAMILY.md` §5a), which is stronger evidence the shape is viable than a fresh
guard call would be. The expressions here are those, character for character.

**Job one — against its own tilt cell, it isolates the rule.** Same names, same slots, same capital,
same (absent) brackets. `tilt − control` within a slice attributes the difference to the timing rule
and to nothing else.

**Job two — against the other three controls, it measures the style tilt itself.** This is the
quantity round 39 exists for and the one no rule-driven cell can produce:
`value-passive − growth-passive` is the **style spread**, measured on identical windows through the
identical engine. Round 35's plan §3a made the same argument for one control; this round needs four
because the style question is a *between-slice* comparison, and a single control over the full seven
names cannot answer it. `r39-full-passive` is that single all-names control and it is in the field
too, so the round reports both the within-slice rule margins and the between-slice style spread.

**They are positions, not strategies.** `StrategyCard`'s own model docstring says a card with no exit,
no target and no time stop "can hold forever, which is a position, not a strategy" — which is exactly
what these four are, and they are in the field to be subtracted, never ranked or promoted. Their
`discipline` is a forced label: `ruleforms.classify` returns `None` for a rule containing no
indicator, and the `Discipline` enum has no member meaning "passive", so `trend` is the least wrong
of seven wrong options and is not a claim about what they do.

**They are buy-and-hold proxies, not indices.** They never rebalance, so each drifts away from equal
weight across a long window, and each deploys 84% rather than 100%. Both differences are small
relative to the effect being measured and both are stated here so no reader has to infer them.

### 3c. Brackets: none on either arm, and the Roth horizon note

No card in this field carries a stop, a target or a time stop.

The reason is §3b's job one: `tilt − control` is only an attribution to the *rule* if the rule is the
only difference. A stop on the tilt arm that the control cannot have would make every margin in this
round a joint measurement of "the crossover plus a 10% stop" against "always in", and no arithmetic
here could separate the two. Round 17 measured the bracket policy as its own factor on sectors and
found what every other marginal in this programme has found; re-entangling it here would buy nothing
and cost the round its one clean attribution.

**The Roth horizon note the brief asks for, recorded because it is the road not taken.**
`PURPOSE_SPECS[Purpose.ROTH].horizon_months_max` is `None` — verified, not remembered — against
`TRADING`'s `9`. So a long `max_hold_days` is legitimate on this book in a way it is not on the
trading book: a 252-day time stop (the model's own ceiling, `StrategyCard.max_hold_days` is
`le=252`) would here be a backstop against a stuck position rather than a forced liquidation inside
the mandate, and a Roth card could carry it honestly where a nine-month trading card carrying 252
would be claiming a hold it is not allowed to complete. This round sets `None` anyway, for the
one-decision reason above; the point is that the choice was between `None` and `252`, not between
`None` and something the purpose forbids.

### 3d. Free-parameter budget (`PROTOCOL.md` §3 rule 3 — ten per card)

Counted as **distinct numeric values** across `entry`, `exit` and `rank_by`, plus one each for the
stop, the target, the hold cap, the slot count and the position size — the identical derivation
`round35.py` uses, so the two rounds' reported budgets are directly comparable. `ema(10)` appearing
in both the entry and the exit is one number an author chose once; counting it twice would inflate
the budget with a fact about text rather than about the hypothesis.

| cell | free numbers |
|---|---|
| `r39-value-ma`, `r39-growth-ma`, `r39-core-ma`, `r39-full-ma` | **5** — `{200, 10, 30}` + slot count + position size |
| `r39-value-passive`, `r39-growth-passive`, `r39-core-passive`, `r39-full-passive` | **3** — `{0}` + slot count + position size |

**The whole field's maximum is 5, half the budget.** That is a consequence of holding one rule
constant rather than a virtue, and it is reported because the budget is the constitution's check on
fitting: a round that spends five numbers has fewer ways to have fitted anything than one that spends
ten. `tests/test_round39_field.py` pins the maximum at 10 as the constitutional bound and at 5 as
this round's actual figure, so a later edit that adds a number breaks a test rather than a margin.

## 4. Windows, metric, and the confound this round is built around

**Windows.** The standard eight-window matrix, run serially by `run_round.sh`: `q4-2018`, `covid`,
`bear-2022`, `chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc`. The `13f-legal` window is
card-filtered to a card this round does not contain and will not run. All eight cards are eligible in
**8 of 8** — verified in §8, not predicted.

**Metric.** `PROTOCOL.md` §4's primary key: the median of `adjusted_excess = total_return −
capital_exposure × benchmark_return` across a card's eligible main windows, with
`worst_adjusted_excess`, `hit_rate` and the across-window IQR reported beside it.

### 4a. The known confound, pre-registered

**The benchmark is SPY.** `PURPOSE_SPECS[Purpose.ROTH].benchmark` is `"spy"` — verified in code, and
described in that module's own docstring as a judgement call recorded rather than backtested. A
value, equal-weight and mid-cap book measured against US large-cap growth over 2011–2026 inherits a
**decade of style headwind that no rule inside this engine can overcome**. `adjusted_excess`
partially controls for *exposure* — it asks whether the rules beat being invested the same fraction
of the time — but it does not control for the **style gap**, and nothing in this harness does.

This is round 35's §4a problem with a different sign: round 35 had a non-US universe against a US
benchmark and pre-registered that its SPY column would be uninformative. This round has a
*deliberately unfashionable slice of the same market* against a benchmark that is the fashionable
slice. The confound is if anything sharper, because the benchmark is not merely a different asset
class — it is, in part, the *other arm of this round's own experiment*. `SPY` is cap-weighted US
large-cap; `SPYG` is its growth half. Measuring `value` against `SPY` is measuring one arm against
something close to a blend containing the other arm.

Two further pieces of the same problem, both structural:

- **Price-only, no dividends and no coupons.** Value indices carry structurally higher dividend
  yields than growth indices, so dropping dividends penalises the `value` slice *more* than the
  `growth` slice and more than the benchmark — by an amount this round does not measure. It hits
  `TIP` hardest of all: a TIPS fund's return is mostly coupon and inflation accrual, and a price-only
  series of it is not a return series in any useful sense (§7).
- **Style definitions are not observable here.** §2a: a fund's factor identity is set by an index
  provider and revised on its schedule, invisibly to these bars.

**How the result will be read, fixed now.** The headline `adjusted_excess vs SPY` figures for the
`value` and `core` slices are expected to be negative and will be reported as **uninformative about
the tilt**. The quantities this round actually ranks on are:

1. **`tilt − control` within each slice** — does the timing rule add anything, on identical names,
   identical slots, identical capital.
2. **`value-passive − growth-passive`** — the style spread itself, which is the vault-derived claim
   stated as a number.

Any narrative built on the SPY column alone — in either direction — is out of bounds under this
pre-registration.

## 5. Falsifiable predictions, fixed before any run

Six, and each names the regime its arm is predicted to fail in (`PROTOCOL.md` §3 rule 5). The
per-arm failure regimes are carried verbatim in each card's own `falsification` field, so a per-card
reporter (§2 phase 6 of the protocol), who sees only its own card, reads the same pre-registration a
scorer does.

1. **No tilt cell beats its own passive control by more than 21.2pp on median adjusted excess.** This
   is the round's rule test. A margin inside the floor is a null whichever side of the control it
   lands on. Predicted to hold in all four slices.
2. **The style spread `value-passive − growth-passive` lands inside 21.2pp.** This is the round's
   *style* test and the vault-derived claim stated as a number. Predicted to hold — i.e. the
   structural-stagnation portfolio expression is predicted to be **unmeasurable** on this window mix.
   A spread larger than the floor *in either direction* is the result that would make this axis worth
   a second round.
3. **The `value` and `core` slices post negative median adjusted excess against SPY; the `growth`
   slice does not.** This is a prediction about §4a's style gap, not about the rules. It is the
   round's own validity check on the confound: if `growth` also posts negative against SPY, the
   benchmark gap is not behaving as §4a describes and every SPY-column reading in the report is
   suspect.
4. **Pre-registered failure regimes, per slice, named before the run:**
   - `value` — worst in **`bull-2024` and `recent`**. A value/equal-weight/mid-cap book is on the
     losing side of the mega-cap-growth leadership that dominates both windows.
   - `growth` — worst in **`bear-2022`**. A long-duration growth book is what the rate shock repriced
     hardest, and a 10/30 crossover cannot exit fast enough in its first leg.
   - `core` — worst in **`covid`**. A V-shaped crash and snapback is where a 200-day regime filter is
     slowest, and `TIP`'s price-only bars make this the least representative slice in the field.
   - `full` — worst in **`chop-2015` and `chop-2011`**. Seven names into seven slots means every
     whipsaw the crossover suffers is paid seven times over, and both chop windows were cut precisely
     to expose that.
   - Every control's worst window is **`gfc`**, trivially and by construction.
5. **The `full` tilt cell's median lands between the `value` and `growth` tilt cells' medians.** It
   holds the union of both, so if it does not, the slices are interacting through the engine in some
   way this design does not model — most plausibly through the shared 84% budget spread across seven
   names instead of two or three — and that interaction, not the style axis, is what the round
   measured.
6. **Validity check, not a hypothesis:** each control holds every name in its slice on essentially
   every session of every window (session exposure at or near 1.0, one trade per name per window). If
   any control does not, it is not the baseline it is being used as, and **every comparison drawn
   against it is void**.

## 6. The honest prior

The likeliest outcome is predictions 1 and 2 both holding: all four tilt cells land inside 21.2pp of
their own controls, the style spread lands inside 21.2pp, and the round reports that the style axis
carries no more measurable information than the sector, industry, country, form, regime-filter,
bracket and `rank_by` axes did before it. That is the programme's rounds 1–36 record reproducing on a
new axis, and it is worth one round precisely because the axis is new, the mechanism (a slow spread
rather than a fast rotation) is structurally different from everything already tested, and the roster
is legally usable by the Roth book.

The result that would change the programme's direction is **prediction 2 failing** — a style spread
outside the floor, in either direction, measured passively with no rule involved. That would be the
first time in thirty-six rounds that *the composition of the basket* rather than *the rule applied to
it* moved a number past the floor, and it would point the next round at the factor axis rather than
at another rule form. Prediction 1 failing on its own, in one slice, is one cell family out of an
eight-cell field and dies to Benjamini-Hochberg.

## 7. Decision rule, and what this round can never settle

**Decision rule, pre-registered:**

- Rank on median adjusted excess across the eight main windows, with **`tilt − control`** as the
  reported quantity for the rule question (§4a) and **`value-passive − growth-passive`** as the
  reported quantity for the style question.
- **The noise floor is 21.2pp** (`PROTOCOL.md` §7). No margin inside it is a finding, in either
  direction. This holds even though §3 removes slot contention from the field — the floor is the
  programme's stated threshold, not a per-round quantity, and one round cannot relitigate it.
- **Benjamini-Hochberg over all eight cells** — the denominator is every cell this round runs, never
  a surviving subgroup (`PROTOCOL.md` §3 rule 8). If any cell from this round is later compared
  alongside cells from another round, the denominator grows accordingly.
- **Nothing is promoted from this round.** It is a measurement study, like rounds 15, 16, 17 and
  34–36. `PROTOCOL.md` §6 requires two consecutive qualifying rounds on window sets that differ
  before any cell could become a candidate, and a single round cannot supply that by construction.

**What this round can never settle**, stated here so the report cannot quietly overclaim:

- **The valuation thesis it is a proxy for.** §2a: there is no fundamentals store, so P/E, P/B and
  normalised earnings are unreachable. A null here says nothing about relative valuation as a method.
- **Factor-ETF construction.** The style labels are index providers', not this round's; they are
  revised on schedules invisible in these bars, and a fixed ticker's factor identity can drift under
  it.
- **Survivorship.** These eight funds are survivors of the ETF launch cohort. Funds that closed are
  not in the bar store, so a style comparison measured on the ones still trading in 2026 is a kinder
  experiment than the one an investor faced in 2004. The bias is in the selection, not in the data,
  and it is not sized here.
- **Price-only bars, and they hit the slices unequally.** No dividends and no coupons. This penalises
  `value` more than `growth`, and it makes `TIP` a fundamentally misrepresented instrument: most of
  a TIPS fund's total return is coupon and principal inflation accrual, none of which is in a price
  series. `IAU` would have had the opposite property — a non-income asset whose price series *is*
  essentially its return — and it is not in the field (§2b). Any `core`-slice figure must be read with
  this in view.
- **The breadth confound between slices.** §3a: `value` holds three names and `growth` two at the
  same capital budget, so a difference between them contains a concentration component this design
  cannot separate from the style component.
- **SPY as the benchmark for a Roth book** — and, worse here than in round 35, a benchmark that
  partly contains one arm of this round's own experiment (§4a). That is the entire reason four
  controls exist.
- **Composite overlap** (§2d): `VTI` contains every name in three other slices, so this is not eight
  independent bets and no q-value here should be read as though it were.
- **§1091 substantial identity** (§2b, §2c): ticker disjointness is necessary, not sufficient. This
  round establishes that no identical security is repurchased across the two books. It establishes
  nothing about whether `RSP`, `VTI` or `SPYG` are substantially identical to the taxable book's
  `SPY`, and it is not tax advice.
- **Nothing outside the bar store.** These cards read only the Parquet/DuckDB daily bars. Nothing in
  this round touches `data/accounts.toml`, `data/sectors.toml`, `data/store/ledger.sqlite` or
  `app.tax`, and no figure produced here has any bearing on a real tax lot.

## 8. Determinism, scope, eligibility and the run recipe

**Determinism.** `round39.build()` reads no clock, no filesystem and no randomness; called twice it
returns field-identical cards, which `tests/test_round39_field.py::TestDeterminism` pins. The only
part of the tool that reads state is the disjointness check, which reads the live library on purpose
— a ticker list pasted into a constant is correct exactly until the next commit, and this repository
is edited by concurrent sessions.

**Scope.** This round owns `strategy-program/ROUND-39-PLAN.md`, `strategy-program/tools/round39.py`,
`data/rounds/r39-2026-09/cards/*.json` and `tests/test_round39_field.py`. It modifies no library
card, no shared tool, no other round and no document in this directory. Registering it in
`DISJOINT-SECTOR-FAMILY.md` as the family's factor/broad branch is an integration edit for whoever
owns that file, not for this round.

**The gate, run 2026-09-09** (`disjoint_field.py --cards data/rounds/r39-2026-09/cards`) — all three
checks, `OK`, zero taxable hits, every card 8/8:

```
card id             purpose   n tickers  taxable hits  eligible windows
-----------------------------------------------------------------------
r39-core-ma         roth              2             0  8/8
r39-core-passive    roth              2             0  8/8
r39-full-ma         roth              7             0  8/8
r39-full-passive    roth              7             0  8/8
r39-growth-ma       roth              2             0  8/8
r39-growth-passive  roth              2             0  8/8
r39-value-ma        roth              3             0  8/8
r39-value-passive   roth              3             0  8/8

check 2 (ticker disjointness): direct intersection found 0 offending line(s); find_disjointness_violations found 0
check 3 (window eligibility): 8/8 card(s) clear >= 5/8 main windows
OK
```

**Eligibility, verified 2026-09-09** (`windows.py --cards data/rounds/r39-2026-09/cards`, main-matrix
columns only):

| card | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent | gfc | main_ok |
|---|---|---|---|---|---|---|---|---|---|
| `r39-core-ma` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r39-core-passive` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r39-full-ma` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r39-full-passive` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r39-growth-ma` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r39-growth-passive` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r39-value-ma` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |
| `r39-value-passive` | OK | OK | OK | OK | OK | OK | OK | OK | 8/8 |

The only window any card fails is `inv-2000` (round 22's curve matrix, not part of this round's
gate): `VTV`'s first bar is 2004-01-30, `TIP`'s 2003-12-05 and `IBB`'s 2001-02-12, against a
1998/1999 deadline. Round 35 hit the identical single failure for the identical reason.

**The run recipe.** Not executed as part of this pre-registration — the bar store is single-writer, a
full round takes hours, and another session may hold it (`run_round.sh` refuses to start if a
tournament process is already alive, and `WINDOWS.md`'s data-access rule is why).

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round39.py --write
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/disjoint_field.py --cards data/rounds/r39-2026-09/cards
bash strategy-program/tools/run_round.sh data/rounds/r39-2026-09/cards data/rounds/r39-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r39-2026-09/results --json data/rounds/r39-2026-09/scorecard.json --pin-store
```
