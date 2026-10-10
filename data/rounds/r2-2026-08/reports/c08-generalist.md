# c08-generalist -- Cross-Asset Trend Filter -- round 2 report

Agent: `c08-generalist` | Discipline: `trend` | Mandate: consistency -- positive adjusted excess in
as many windows as possible | Eligible: 8/8 main windows (`results/eligibility.json`)

## 1. What the card is

A five-symbol cross-asset "golden cross" filter: `SPY QQQ XLU TLT GLD`, entered on
`close > sma(200) and sma(50) > sma(200)`, exited on `close < sma(200)`, 4 of 5 slots at 25% each, a
15% stop that is a backstop rather than the working risk control. The mechanism is the standard
trend-following claim -- once enough participants agree a trend is confirmed, lagging institutional
flow (pension rebalancing, CTA/risk-parity books, 401k contribution timing) continues pushing in the
confirmed direction, funded by mean-reversion and stale-anchor traders who get run over by
continuation. The design bet is cross-asset, not single-symbol: SPY and QQQ carry equity beta, XLU
a defensive equity proxy, TLT duration, GLD a monetary hedge, so that when equities are
trend-negative some other symbol in the same universe is trend-positive (flight-to-quality). Seven
parameters of the 10 available were spent; three were left unused deliberately.

**Verification.** `total_return` matches `ending_equity / starting_equity - 1` exactly in all 170
run files under `results/*/runs/*.json`, and `capital_exposure` is populated on every result,
including all eight of this card's. Figures below use each window's full-precision
`benchmark_return` from `results/<window>/tournament.json` rather than the two-decimal figures
quoted in the brief, which accounts for sub-point differences from the headline table.

## 2. Eight-window results

| window | trades | return | benchmark | excess | adj. excess | capital exp. | session exp. | max DD | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| q4-2018   |  8 |  -6.73% | -20.05% | +13.31% |  **+1.55%** | 41.33% | 100.00% |  -6.83% |  0.00% |
| covid     | 11 |  -6.11% |  -8.71% |  +2.60% |  **-0.10%** | 68.95% | 100.00% | -16.93% |  0.00% |
| bear-2022 | 24 | -10.82% | -25.14% | +14.32% |  **-1.89%** | 35.52% |  85.20% | -11.03% | 16.67% |
| chop-2015 | 14 |  -5.64% |  -0.04% |  -5.61% |  **-5.63%** | 37.01% |  73.08% |  -8.64% |  0.00% |
| chop-2011 | 14 |  +2.68% |  -0.05% |  +2.72% |  **+2.72%** | 80.97% | 100.00% |  -4.93% | 18.18% |
| bull-2024 | 12 |  +7.72% | +14.00% |  -6.27% |  **-3.59%** | 80.83% | 100.00% |  -6.88% | 25.00% |
| recent    | 10 | +15.87% | +20.62% |  -4.74% |  **-1.07%** | 82.21% | 100.00% |  -8.34% | 75.00% |
| gfc       | 15 |  -4.25% | -56.23% | +51.97% | **+19.20%** | 41.71% |  91.29% |  -8.13% | 30.77% |

Median adjusted excess **-0.59%** (average of the two middle values, covid -0.10% and recent
-1.07%; the brief's headline table gives -0.60%). Worst window **chop-2015, -5.63%**. Hit rate
**3 of 8 (37.5%)** overall, positive in q4-2018, chop-2011, gfc -- and **1 of 6 (16.7%)** on the
`scorecard-common6.json` window set, matching that file's own computed `hit_rate: 0.1667` for this
card exactly.

**The mandate -- positive adjusted excess in as many windows as possible -- failed plainly.** 5 of 8
windows are negative, the median is negative, and on the six-window common set used to compare
against round 1's field this card clears only one window. A consistency-mandated card posting a
negative median and a 3/8 hit rate has not delivered what it was asked to deliver, whatever else it
did well.

## 3. Pre-registered worst window vs actual

Memo, §6: *"bull-2024... a rule that requires both conditions to already be true cannot buy the
first leg of a smooth, low-volatility rally... Measured design-window adjusted excess: -5.65pp, the
worst of the eight. chop-2015 is a close second (-5.00) for essentially the same reason without a
confirmed trend ever forming."* And §7: *"I would not be surprised if chop-2015 joins it [as a
losing window] -- both are robust negatives across every parameter variant I tried."*

**Actual worst window: chop-2015, -5.63%.** bull-2024 came in second-worst at -3.59%. The
pre-registration named the wrong window as worst -- by the letter of "name the regime you expect to
lose in," this is a miss. But it is a narrow one and a disclosed one: the memo identified exactly
these two windows as its weakest pair before any run, ranked them in the wrong order relative to
each other (design-window bull-2024 -5.65 vs chop-2015 -5.00; actual chop-2015 -5.63 vs bull-2024
-3.59), and gave the same underlying reason for both -- no confirmed trend ever forms, so the entry
either never fires or fires late and pays whipsaw on the way in. That reason held for both windows
in the scored data; only the ranking between the pair flipped. This is a materially better outcome
than predicting a window that turned out fine, but it is not the correct call the protocol scores
for, and the report should say so plainly rather than crediting a near-miss as a hit.

## 4. Exit-reason distribution and the stop-loss gap

| window | rule | stop | open at end | trades |
|---|---:|---:|---:|---:|
| q4-2018   |  7 | 0 | 1 |  8 |
| covid     |  7 | 1 | 3 | 11 |
| bear-2022 | 24 | 0 | 0 | 24 |
| chop-2015 | 11 | 0 | 3 | 14 |
| chop-2011 | 11 | 0 | 3 | 14 |
| bull-2024 |  8 | 0 | 4 | 12 |
| recent    |  8 | 0 | 2 | 10 |
| gfc       | 13 | 0 | 2 | 15 |

The 15% stop bound exactly **once** across all eight windows and 108 trades: QQQ in covid, entered
2020-02-19 at 236.25, exited 2020-03-10 at 201.01, a realised loss of -14.92% against a nominal 15%
-- a gap of **-0.08pp**, i.e. essentially no slippage past nominal on the one occasion the stop
fired. Every other exit is the trend rule itself (`close < sma(200)`) or the window ending with a
position still open. This confirms the memo's own §5 sensitivity claim in full: the stop is not a
load-bearing lever anywhere in the scored data, and its near-total silence means the previous-close
evaluation and next-open fill mechanics that materially hurt other cards' stops this round (see
c07-chop's 36 stop-outs averaging 2.4pp worse than nominal) simply never had the chance to matter
here. The real risk control in this card is entirely the trend exit, not the stop.

## 5. Defended, or merely absent?

**Mostly defended, and demonstrably not absent.** Session exposure is 100% in five of eight windows
and never below 73% in any window; capital exposure ranges 35-82%, well above c07-chop's 4-23% band.
This card is close to fully invested most of the time by design (4 of 5 symbols at 25% each), which
is the opposite posture from "scored well because it could not enter." Where it defends is in the
*exit*: in gfc, the window with by far the best result (+19.20% adjusted excess), the card was
invested on 91.29% of sessions yet still held its own drawdown to -8.13% against a benchmark
drawdown of roughly -56% and a raw return of -4.25% against -56.23% -- a defence built entirely on
`close < sma(200)` cutting exposure before the deepest legs of the crisis, not on staying out of the
market. The same pattern holds, more weakly, in covid (69% capital exposure, -6.11% return against
-8.71% benchmark).

The three all-zero-win-rate windows (q4-2018, covid, chop-2015) are the sharper test of this
question. In q4-2018 every one of 7 closed trades lost money, yet the window still posted +1.55%
adjusted excess -- the card was fully invested (100% session exposure) and still lost on every
trade, but it lost less, in aggregate, than the exposure-scaled benchmark decline. That is a real
answer to "defended or absent": this is neither -- it is a card that traded, lost on every closed
position, and still beat its adjusted bogey because the bogey itself was falling faster. chop-2015
is the same mechanism working in reverse: fully invested (73% capital exposure), zero win rate, and
this time the benchmark was flat rather than falling, so there was no falling bogey to hide behind,
and the whipsaw cost shows up nakedly as -5.63% adjusted excess. The trend exit is doing real work
in both cases; whether that work nets out positive depends entirely on whether the benchmark it is
being compared against was falling hard enough to absorb the whipsaw cost.

## 6. Is the consistency mandate achievable, and the parameter-instability finding

The memo disclosed, before any scored run, that perturbing only the SMA periods -- 40/180 and
60/220 against the chosen 50/200, none of them searched, all three defensible conventions -- moved
its own design-window hit-rate estimate across the range **3/8 to 5/8**: "the *hit-rate count* is
not [stable]: 40/180 scored 3/8, 60/220 scored 4/8, and chop-2011 in particular flips sign under
both perturbations... 50/200 is not the best-scoring choice among the three I tried, and I kept it
anyway because it is the conventional pair, not a fitted one." This was reported as a footnote in
the memo's "tried and abandoned" section; it should not be treated as one. The scored result landed
at **3/8** -- the pessimistic edge of that self-disclosed range, not the 5/8 the chosen (and
unfitted) 50/200 pair actually measured in-sample. A parameter choice that the author defends
precisely *because* it wasn't picked to win, and which then delivers the worst outcome in its own
declared instability band, is exactly the situation §2 of the brief warns about: even a
conventional, undisputed choice can carry enough estimation noise to flip 2-3 windows' sign, and the
consistency mandate lives or dies inside that noise band.

Whether the mandate is achievable at all is a harder question than whether this card achieved it.
Two structural points push toward "not with this instrument, and maybe not with any single-rule
long-only trend filter under this DSL." First, the DSL offers no cross-sectional signal and no
per-symbol volatility sizing (per `BRIEF.md` §1/§7) -- the card's actual bet is that flight-to-quality
correlation across five symbols will show up when needed, and it is real but narrow: it shows up in
gfc and, weakly, covid, and it does not show up in bear-2022 (the memo's own disclosed weakest
assumption, "the one window where nothing... trended cleanly," result -1.89%), and it cannot show up
at all in a window with no macro divergence between equities, bonds and gold to exploit, such as
chop-2015. Second, and more directly: 3 positive windows out of 8 came from three regimes that share
very little in common with each other structurally (a slow selloff, a grinding sideways market, and
the deepest crash in the matrix) while 5 negative windows include both chop windows' near-twin,
bull-2024, and the two other crisis-adjacent windows (covid, bear-2022) landing negative despite the
crisis-hedge thesis. A hit rate built from three largely uncorrelated wins against five losses,
where the same conventional-parameter perturbation that produced the design estimate can itself swing
the count by two windows in either direction, is better described as sitting inside sampling noise
than as a demonstrated edge. This round is evidence that a defensible, unfitted single-rule trend
filter cannot reliably clear even half the matrix -- not proof that no card ever could, but a
genuine data point against the mandate being achievable cheaply, and the card's own pre-registered
instability said as much before the fact.

## 7. Verdict and promotion recommendation

The card is exactly what it claims to be: a trend filter that is very good at surviving the two
deepest crises in the matrix (gfc +19.20%, second-best in the field behind c04-riskmanaged's
+26.10%; covid a near-flat -0.10%) by staying mostly invested and exiting on a lagging but real
signal, and correspondingly bad at anything resembling a smooth trend or a directionless grind
(chop-2015 -5.63%, bull-2024 -3.59%, bear-2022 -1.89%). The consistency mandate was not met: median
adjusted excess is negative, hit rate is 3/8 overall and 1/6 on the common set, and the
pre-registered worst window, while close, named the wrong one of its own two flagged candidates.

**Median adjusted excess is negative (-0.59%).** Per `PROTOCOL.md` §6, `challenger -> candidates/`
requires clearing the regime gate *and* posting a positive median adjusted excess; this card clears
the gate (8/8) but does not clear the median bar. Recommendation: **do not promote.** The card
remains a challenger. Its crisis-window performance (gfc, covid) is worth carrying forward as a
data point -- particularly since it is genuinely defended rather than merely absent in those two
windows -- but the disclosed parameter instability around the 50/200 choice, now confirmed by a
scored outcome at the pessimistic end of that instability's own range, means a second round's result
under an unchanged card would be informative before any promotion case is made, not a formality.

## 8. Attribution: what moved the number

Source: `analysis/attribution.md` / `results/attribution.json`
(`strategy-program/tools/attribution.py`). Contribution is exact -- `pnl / starting_equity` per
trade, summing to the card's own scored return. Trades below 1% of the book are folded into prose
rather than tabulated individually.

### `q4-2018`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| QQQ | 2018-09-21 | 2018-10-12 | 15 | rule | -6.06% | -146 | -1.46% |
| SPY | 2018-09-21 | 2018-10-12 | 15 | rule | -5.67% | -133 | -1.33% |
| SPY | 2018-12-04 | 2018-12-06 | 1 | rule | -4.57% | -102 | -1.02% |

**Every one of this window's 8 trades lost money** -- there is no winning trade to attribute at all
(the attribution tool returns no top-3-winners figure because gross winning P&L is zero). QQQ and
SPY entered together on 2018-09-21 into the same 200-day-MA breakdown and both took the same 15-bar
loss; the rest is a scatter of smaller losing rule exits on QQQ, SPY and XLU through October and
November, plus one still-open XLU position marked at -2.31% (-0.57% of the card's return, per §2's
unrealised figure). The window's positive **+13.31% excess / +1.55% adjusted excess** is not evidence
any trade worked -- it is the -6.73% raw loss being smaller than SPY's own -20.05%, scaled by 41.33%
capital exposure. Attributed honestly: this is a card that traded, lost on every single position, and
still cleared its adjusted bogey purely because the bogey fell faster.

### `covid`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| QQQ | 2020-04-09 | _open_ | 56 | **open_at_end** | +22.30% | +542 | +5.42% |
| QQQ | 2020-02-19 | 2020-03-10 | 14 | stop | -14.92% | -352 | -3.52% |
| SPY | 2020-02-19 | 2020-02-28 | 7 | rule | -14.62% | -346 | -3.46% |
| TLT | 2020-02-19 | _open_ | 92 | **open_at_end** | +12.91% | +319 | +3.19% |
| XLU | 2020-02-19 | 2020-03-02 | 8 | rule | -11.71% | -290 | -2.90% |
| GLD | 2020-03-24 | _open_ | 68 | **open_at_end** | +8.98% | +234 | +2.34% |
| XLU | 2020-03-09 | 2020-03-12 | 3 | rule | -9.60% | -226 | -2.26% |
| QQQ | 2020-03-11 | 2020-03-12 | 1 | rule | -8.75% | -209 | -2.09% |
| GLD | 2020-03-13 | 2020-03-19 | 4 | rule | -7.01% | -168 | -1.68% |

All five symbols entered within the same three weeks (Feb 19-Mar 24, 2020) as the trend filter's
200-day MA condition triggered or broke across the whole universe simultaneously. Every realised loss
is a rule or stop exit taken during the crash itself (QQQ, SPY, XLU all cut in the first two weeks);
the card's near-flat -6.11% result rests on three positions still open and marked positive at the
window's close (QQQ +5.42%, TLT +3.19%, GLD +2.34% -- **+10.95% of the return is unrealised**, more
than offsetting the realised losses). This is the flight-to-quality thesis working in the direction
intended (TLT, GLD both catch the rotation), but the number is a mark against the last close, not
money banked.

### `bear-2022`

24 trades, 4 winners, 20 losers. Material trades:

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| QQQ | 2022-01-03 | 2022-01-21 | 13 | rule | -10.01% | -240 | -2.40% |
| SPY | 2022-01-03 | 2022-01-24 | 14 | rule | -9.39% | -224 | -2.24% |
| XLU | 2022-01-03 | 2022-01-27 | 17 | rule | -6.21% | -153 | -1.53% |

QQQ and SPY both entered on the year's first session and were both cut within three weeks as the
200-day trend broke early in the bear market -- together -4.64 points of the window's -10.82%. The
remaining 21 trades are all sub-1% individually (mostly XLU and GLD round-trips under 2 weeks), and
only 4 of the 24 ever turned a profit. Without the 3 largest (all losers, not winners -- there is no
winner large enough to reach the 1% cutoff) the card would sit at -11.30%, barely different from the
headline -10.82%: this window's result is a broad scatter of small losses, not one or two trades.

### `chop-2015`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| QQQ | 2015-04-07 | 2015-08-24 | 97 | rule | -11.13% | -271 | -2.71% |
| TLT | 2015-04-07 | 2015-05-05 | 20 | rule | -5.76% | -143 | -1.43% |
| QQQ | 2015-11-18 | 2016-01-07 | 33 | rule | -5.45% | -134 | -1.34% |
| XLU | 2016-02-08 | _open_ | 47 | **open_at_end** | +5.14% | +128 | +1.28% |
| TLT | 2016-01-25 | _open_ | 57 | **open_at_end** | +4.66% | +112 | +1.12% |

Only 2 of 14 trades were winners, and both are still open at the window's close -- XLU and TLT,
entered late January/early February 2016, supply **100% of gross winning P&L** and **+2.29% of the
return is unrealised**. Strip those 2 winners and the card would have returned -8.04% instead of
-5.64% -- a window where the "recovery" the headline shows is entirely a paper mark on two positions
not yet closed.

### `chop-2011`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| XLU | 2011-08-16 | _open_ | 203 | **open_at_end** | +12.05% | +298 | +2.98% |
| QQQ | 2012-01-04 | _open_ | 106 | **open_at_end** | +9.99% | +244 | +2.44% |
| SPY | 2012-03-16 | 2012-06-04 | 54 | rule | -8.62% | -206 | -2.06% |
| TLT | 2012-04-10 | _open_ | 40 | **open_at_end** | +7.79% | +190 | +1.90% |
| TLT | 2011-08-05 | 2012-03-15 | 153 | rule | +7.10% | +169 | +1.69% |

The window's positive +2.68% return rests on three positions still open at the close (XLU, QQQ, TLT
-- **+7.32% unrealised**, exceeding the total return) offsetting one closed TLT winner (+1.69%) and a
closed SPY loser (-2.06%). Without the 3 largest winners the card would have returned -4.64%: same
pattern as chop-2015, a headline recovery resting mostly on marks, not closed trades.

### `bull-2024`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2024-10-14 | _open_ | 212 | **open_at_end** | +25.72% | +631 | +6.31% |
| XLU | 2025-04-23 | _open_ | 82 | **open_at_end** | +9.35% | +236 | +2.36% |
| TLT | 2024-08-21 | 2024-10-11 | 36 | rule | -5.36% | -132 | -1.32% |
| XLU | 2025-03-10 | 2025-04-07 | 20 | rule | -4.80% | -118 | -1.18% |

**All four material trades are either a still-open position or a closed loser.** Four positions were
open at the window's close (GLD, XLU, plus two smaller sub-1% QQQ and SPY marks not tabulated), and
together they supply **+10.43% of the +7.72% return -- more than the entire result.** The eight closed
trades net to roughly -2.7% on their own. This is the clearest single finding in this card's
attribution: its one genuinely positive window against a strong benchmark (+7.72% vs SPY's +14.00%,
still a -6.27% excess) would show a small net loss on realised trades alone if the open GLD and XLU
marks were struck to zero instead of the last close.

### `gfc`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| QQQ | 2007-10-09 | 2008-01-07 | 61 | rule | -9.23% | -231 | -2.31% |
| TLT | 2008-11-05 | _open_ | 83 | **open_at_end** | +9.17% | +226 | +2.26% |
| TLT | 2008-09-17 | 2008-11-03 | 33 | rule | -6.37% | -158 | -1.58% |
| SPY | 2007-10-09 | 2007-11-08 | 22 | rule | -4.99% | -124 | -1.24% |

This is the window the brief singles out: the card **lost $425.50 outright** (-4.25% on the $10,000
book) and still posted **+19.20% adjusted excess**, the round's second-best crisis result behind
c04-riskmanaged. Attributed honestly, both halves are real. The loss side: QQQ, entered 2007-10-09 at
the market's own top and held 61 sessions before the trend rule cut it, is the single largest trade in
either direction (-2.31%); a second TLT round-trip and an SPY position add another -2.82pp of closed
losses. The credit side: one TLT position, opened 2008-11-05 in the post-Lehman flight to duration and
still open at the window's close, is marked +2.26% and is the largest winner; a second TLT trade
closed earlier in the window for +0.69%. Net of the small GLD open position (-0.68%), **+1.58% of the
-4.25% return is unrealised** -- a modest share, most of this window's result is closed. The +19.20%
adjusted excess itself is the -4.25% raw loss plus 41.71% capital exposure credited against SPY's
-56.23% (+23.45pp) -- a real dollar loss, genuinely offset by real capital committed through a
benchmark that fell far harder, not an absence dressed as defence: session exposure was 91.29%.

### `recent`

| symbol | entry | exit | bars | exit reason | trade return | P&L | share of return |
|---|---|---|---|---|---|---|---|
| GLD | 2025-08-21 | 2026-06-08 | 199 | rule | +28.99% | +714 | +7.14% |
| QQQ | 2026-04-09 | _open_ | 90 | **open_at_end** | +18.36% | +445 | +4.45% |
| SPY | 2026-04-09 | _open_ | 90 | **open_at_end** | +13.67% | +277 | +2.77% |
| QQQ | 2025-08-21 | 2026-03-23 | 146 | rule | +4.53% | +102 | +1.02% |

One closed GLD trend trade, held 199 sessions to a clean rule exit, supplies +7.14 of the card's
+15.87% return -- close to half. Two further positions (QQQ, SPY) opened the same session
(2026-04-09) and remain open at the close, contributing another +7.22% unrealised. Real gains, mostly
realised (GLD, the largest single trade, is fully closed), but the window still trails SPY's +20.62%
by 4.74 points even with a genuine trend-following winner at its core.

## 9. Concentration and unrealised marks

| window | top-3 share of gross wins | return w/o top-3 winners | unrealised share |
|---|---:|---:|---:|
| q4-2018 | n/a (no winners) | -6.73% | -0.57% |
| covid | 100% | -17.06% | +10.95% |
| bear-2022 | 92% | -11.30% | -- |
| chop-2015 | 100% | -8.04% | +2.29% |
| chop-2011 | 73% | -4.64% | +7.32% |
| bull-2024 | 87% | -1.88% | +10.43% |
| gfc | 96% | -7.46% | +1.58% |
| recent | 84% | +1.51% | +7.22% |

The pattern across all eight windows is consistent and worth stating plainly: **in five of the six
windows carrying a material unrealised component (covid, chop-2015, chop-2011, bull-2024, recent),
the unrealised share is a meaningful-to-dominant fraction of the total return, and in two of them
(bull-2024, chop-2015 combined with chop-2011) it exceeds the return outright** -- meaning the closed,
realised book alone would show a loss. This is the mechanical consequence of a trend-following exit
that only fires on `close < sma(200)`: whenever a window ends mid-trend, the position is still open,
and the mark is doing real work in the headline number. It is not evidence of bad faith or a
mismeasured return (every `total_return` figure ties out to `ending_equity` exactly, per §1's
verification), but a reader relying on this card's positive windows as proof of a working edge should
know that three of its four positive-or-near-flat windows (covid, chop-2011, bull-2024) rest more on
open marks than on closed trades. q4-2018 sits at the other extreme: zero winners at all, and its
positive excess is entirely a benchmark-relative artifact. gfc and recent are the two windows where a
closed trade is doing the largest single share of the work -- gfc's biggest mover is a closed loss
(QQQ, -2.31%) offset partly by an unrealised TLT gain, a real dollar loss defended by exposure, not an
open mark; recent's biggest mover is a closed GLD winner (+7.14% of +15.87%), with unrealised QQQ/SPY
marks (+7.22%) adding to rather than manufacturing the result.
