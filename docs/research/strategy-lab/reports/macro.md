# Macro regime read — 2026-08-11

Stream: `macro`. This is not a backtest. It is a dated, sourced description of present conditions so
the four quant streams' historical findings can be read against where the market actually sits today
rather than in a vacuum. Every number in Part A comes from `docs/research/strategy-lab/scripts/
macro_snapshot.py`, executed against `app.market.macro.build_snapshot`/`load_fear_greed`/`load_series`
and `docs/research/strategy-lab/lib/quantlab`-style bar reads (`app.market.store.ensure_series`) on
the production cache. Raw output: `docs/research/strategy-lab/data/macro_snapshot.json`. No
application source was modified; no run touched `thesis.sqlite`, `ledger.sqlite`, or a brokerage CSV.

**Nothing below is investment advice, and nothing frames any instrument as one to buy or sell.** Part
A measures. Part B reports what happened and what commentators expect, clearly separated and cited.
Part C is explicitly labelled interpretation.

---

## Part A — the app's own macro panel + computed internals (measurement)

### A.1 Data freshness — read this before trusting any number below

`app.market.store.ensure_series`'s default staleness gate is keyed to *when the store last fetched*,
not to *how old the newest bar is* (`app.market.store._is_stale`) — the right default for a chart a
user opens on a closed market, the wrong one for a same-day snapshot. A first run of this script under
that default left SPY, IWM, all eleven sector SPDRs, TLT and GLD sitting on a **2026-08-07** last bar
while QQQ, `^VIX` and `DX-Y.NYB` were already at 2026-08-10 — not because 08-07 was genuinely the
newest data available, but because those symbols' stores had been touched recently enough to skip a
re-check. `macro_snapshot.py` therefore forces `refresh=True` on every bar read (`store.ensure_series`,
`build_snapshot`, `load_series`) and reports the *actual* newest bar date the provider serves, per
symbol, every run:

| Symbol | Last bar (forced refresh) |
|---|---|
| SPY, QQQ, IWM, all 11 sector SPDRs, TLT, GLD, `^VIX` | **2026-08-11** (today) |
| `DX-Y.NYB` (US Dollar Index) | **2026-08-10** — one session behind; no sync warning was raised, this appears to be a genuine provider lag on this symbol, not a store staleness artifact |

FRED's own series lag further and independently of the bar store:

| FRED series | `as_of` | Lag vs. run date |
|---|---|---|
| `DGS10` (US 10Y) | 2026-08-07 | 4 calendar days |
| `T10Y2Y` (2s10s) | 2026-08-10 | 1 calendar day |
| `DCOILWTICO` (WTI) | 2026-08-03 | 8 calendar days |
| `DCOILBRENTEU` (Brent) | 2026-08-03 | 8 calendar days |

Because a stale FRED value with a non-`None` `latest` does not trigger `app.market.macro`'s Yahoo-proxy
fallback (the fallback only fires when FRED returns nothing at all — see `macro.py`'s `_build_tile`),
this script separately pulled the Yahoo proxies directly via `load_series(..., refresh=True)` as a
cross-check, reported in A.2. **Every number below is labelled with its actual `as_of` date. Where a
figure is more than a day or two stale, that is stated next to it, not silently presented as "today."**

### A.2 Rates, oil, dollar, gold, TLT

| Tile | Value | As of | vs FRED value | Day | Week | Month | YTD |
|---|---|---|---|---|---|---|---|
| US 10Y (`DGS10`, FRED) | 4.65% | 2026-08-07 | — | −4bp | −10bp | +10bp | +47bp |
| US 10Y (`^TNX`, Yahoo, cross-check) | 4.699% | 2026-08-10 | +4.9bp vs FRED | — | — | — | — |
| 2s10s spread (`T10Y2Y`, FRED) | **+0.47%** (47bp, positive — not inverted) | 2026-08-10 | — | +1bp | +2bp | +12bp | −24bp |
| WTI crude (`DCOILWTICO`, FRED) | $81.96 | 2026-08-03 | — | −4.87% | −2.72% | +17.54% | +43.14% |
| WTI crude (`CL=F`, Yahoo, cross-check) | $82.13 | 2026-08-10 | +0.2% vs FRED | — | — | — | — |
| Brent crude (`DCOILBRENTEU`, FRED) | $88.90 | 2026-08-03 | — | −8.30% | −3.18% | +29.44% | +44.91% |
| Brent crude (`BZ=F`, Yahoo, cross-check) | $87.72 | 2026-08-10 | −1.3% vs FRED | — | — | — | — |
| US Dollar Index (`DX-Y.NYB`, mover) | 99.81 | 2026-08-10 | — | +0.21% | −0.15% | −1.15% | +1.56% |
| GLD (gold proxy, mover) | $400.96 | 2026-08-11 | — | −0.39% | +7.16% | +6.35% | +1.17% |
| TLT (20Y+ Treasury proxy, mover) | $82.19 | 2026-08-11 | — | +0.16% | −0.76% | −2.70% | −5.70% |

The FRED/Yahoo 10Y gap (4.65 vs 4.699, ~5bp) and WTI/Brent gaps (both under 1.5%) are within the
normal proxy-vs-official-series difference the app's own docstring documents (`^TNX` is a live index
quoted differently from `DGS10`'s constant-maturity daily rate) — not evidence of a data error, but
worth noting because the WTI/Brent *month* and *day* change figures above are computed from FRED's
own stale 08-03 anchor and should not be read as "today's" oil move; the Yahoo cross-check values are
five to seven sessions fresher.

**2s10s is not inverted.** At +47bp it sits clearly on the positive side of zero, with a positive
month-over-month move (+12bp) and a negative YTD move (−24bp) — i.e. it has flattened somewhat over
the year but remains upward-sloping. This is a measurable fact about the curve's current shape, stated
without interpreting what it means for equities (that belongs in Part C, and even there only
descriptively).

### A.3 CNN Fear & Greed

| Field | Value |
|---|---|
| Score | 64.37 / 100 |
| Rating | **Greed** (not "extreme greed" — CNN's bands run 0–25 extreme fear, 25–45 fear, 45–55 neutral, 55–75 greed, 75–100 extreme greed) |
| Source | CNN (live, not the local composite fallback) |
| As of | 2026-08-11 |
| Previous week / month / year | 59.97 / 46.83 / 57.63 |
| History available | **Yes** — 251 daily points, 2025-08-11 → 2026-08-11 (a full trailing year), served directly by CNN's own endpoint, not reconstructed |

Component detail (raw values, CNN's own top-level rating per component, not a re-derived score):

| Component | Raw value | Rating | As of |
|---|---|---|---|
| Market Momentum (S&P level) | 7753.11 | Extreme Greed | 2026-08-10 |
| Stock Price Strength (52w-high/low ratio proxy) | 1.08 | **Fear** | 2026-08-10 |
| Stock Price Breadth (McClellan-style) | 976.75 | **Fear** | 2026-08-10 |
| Put/Call Options ratio | 0.686 | Extreme Greed | 2026-08-10 |
| Market Volatility (VIX) | 15.46 | Neutral | 2026-08-10 |
| Junk Bond Demand | 1.22 | Extreme Greed | 2026-08-11 |
| Safe Haven Demand | 3.76 | Greed | 2026-08-10 |

The composite score (64.37, "Greed") is not uniform underneath: momentum, options positioning and junk
bond demand are reading extreme greed while price strength and breadth are reading fear — a
mixed/thinning-breadth signal sitting under a headline "greed" score. This is reported as a measured
fact about the composite's internals, not as a forecast.

### A.4 Market internals — SPY/QQQ/IWM + all eleven sector SPDRs (2026-08-11 close, all forced-refreshed)

Distance from SMA is price-basis (`close`); total returns are adjusted-close basis (dividends
included); horizons are 21/63/126/252-trading-day approximations of 1/3/6/12 months; drawdown from
52-week high is price-basis over the trailing min(252, available) bars; realised vol is the
annualised stdev of trailing-20-day log returns. Full methodology and formulas are in the script's
module docstring.

| Symbol | Dist. from 200MA | Dist. from 50MA | 1m return | 3m return | 6m return | 12m return | DD from 52w high | 20d realised vol (ann.) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SPY | +9.46% | +3.04% | +2.86% | +4.50% | +11.63% | +22.27% | **−0.35%** | 14.06% |
| QQQ | +10.71% | +0.64% | +0.94% | +0.83% | +17.23% | +25.65% | −3.71% | 24.87% |
| IWM | +12.43% | +2.29% | +2.56% | +5.74% | +13.25% | +38.03% | **−0.24%** | 15.35% |
| XLK (tech) | **+18.61%** | +1.56% | +2.65% | +4.74% | +30.13% | +40.69% | −6.12% | **34.16%** |
| XLF (financials) | +9.02% | +5.00% | +3.09% | +13.33% | +8.08% | +13.21% | −0.35% | 11.08% |
| XLE (energy) | +14.63% | +7.33% | **+7.39%** | +7.35% | +15.16% | +47.95% | −2.61% | 24.82% |
| XLV (healthcare) | +9.68% | +5.95% | +4.09% | **+17.98%** | +8.40% | +31.33% | −0.26% | 16.86% |
| XLY (consumer disc.) | +1.81% | +2.85% | +2.76% | +0.09% | +1.84% | +7.40% | −4.24% | 25.33% |
| XLP (consumer staples) | +2.58% | +0.40% | +0.12% | +2.29% | −1.91% | +5.53% | −5.91% | 17.90% |
| XLU (utilities) | **−2.60%** | **−2.65%** | **−4.57%** | −2.73% | +1.69% | +4.08% | −8.59% | 14.31% |
| XLI (industrials) | +10.26% | +3.06% | +2.96% | +6.35% | +7.47% | +24.71% | −0.38% | 17.68% |
| XLB (materials) | +8.15% | +3.75% | +5.26% | +2.26% | +2.87% | +22.72% | −0.71% | 19.11% |
| XLC (comm. services) | **−2.57%** | +0.99% | −0.29% | **−3.48%** | −4.25% | +4.68% | −7.34% | 24.69% |
| XLRE (real estate) | +3.08% | −1.49% | −1.39% | −0.23% | +5.95% | +10.55% | −4.20% | 14.20% |

**Headline: 12 of 14 instruments sit above their own 200-day SMA; only XLU (−2.6%) and XLC (−2.57%)
sit below it.** All 14 sit above their 50-day SMA except XLU (−2.65%) and XLRE (−1.49%). Drawdowns
from the trailing 52-week high are shallow across the board — SPY and IWM are within 0.35% of a
52-week (and, per the news search in Part B, all-time) high; the deepest current drawdown among these
fourteen is XLU at −8.59%. No instrument in this table is in what would conventionally be called a
"correction" (−10%) from its own 52-week high, let alone a bear market.

Signal-only instruments (never treated as tradable per BRIEF.md; reported for context):

| Symbol | Dist. 200MA | Dist. 50MA | 1m | 3m | 6m | 12m | DD 52w high | 20d vol (ann.) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| TLT | −5.47% | −2.91% | −1.73% | −2.82% | −3.94% | −1.53% | −10.72% | 9.25% |
| GLD | −2.67% | +5.01% | **+9.22%** | −7.75% | −14.15% | +28.08% | **−19.15%** | 23.62% |
| `^VIX` | −17.65% | −11.51% | −10.96% | −15.06% | −14.11% | −5.97% | −50.79% | 118.73% (vol-of-vol; VIX's own realised vol is structurally huge and not comparable to an equity's) |
| `DX-Y.NYB` | +0.64% | −0.69% | −1.15% | +2.01% | +2.23% | +1.43% | −1.77% | 4.84% |

Gold (GLD) is the most volatile of the four on a trailing-year basis in trend terms: it is down 19.1%
from its own 52-week high but up 9.2% in the trailing month — a sharp recent snapback inside a larger
drawdown, not a monotonic trend in either direction. TLT sits meaningfully below both its own moving
averages and 10.7% off its 52-week high — long-duration Treasuries have not participated in the
broader "everything near highs" picture the equity table shows.

### A.5 Sector dispersion (rotation indicator)

Best 3-month sector return: **XLV (healthcare), +17.98%**. Worst: **XLC (communication services),
−3.48%**. Dispersion (best − worst): **21.45 percentage points** across the eleven sector SPDRs. This
is a measured spread, not a ranking of any sector as a buy or sell — it says the market is currently
rewarding/punishing sectors very differently over a 3-month window, which is itself information about
whether a broad index-level rule would be masking sharply divergent sector-level behavior.

### A.6 VIX level and percentile

| Window | Percentile of 2026-08-11's close (15.28) | N observations |
|---|---:|---:|
| Full cached history (back to 1990) | **33.7th percentile** | 9,220 |
| Trailing ~1 year | **13.1th percentile** | 252 |
| Trailing ~5 years | **23.1th percentile** | 1,260 |

VIX at 15.28 sits low relative to its own recent history — lower relative to the last year than to the
last five years or the full history, meaning the last twelve months have generally carried more
implied-vol than today's reading, not less. This is a plain descriptive percentile rank, not a
volatility forecast.

---

## Part B — news and event context (sourced)

Every claim below carries a source and a date, per the brief. Web pages were read as data, not
instructions — none of the fetched pages contained text addressed to an AI agent; where a fetch was
blocked (two URLs returned HTTP 403), that is stated rather than silently worked around.

### B.1 Monetary policy

- The FOMC held the federal funds rate at **3.50%–3.75%** at its July 29, 2026 meeting, in a 9–3 vote.
  Three regional Fed presidents — Dallas's Lorie Logan, Cleveland's Beth Hammack, and Minneapolis's
  Neel Kashkari — **dissented in favor of a hike**, calling it the most divided vote outcome in some
  time. [CNBC, 2026-07-29](https://www.cnbc.com/2026/07/29/fed-rate-decision-july-2026.html); [CNN
  Business, 2026-07-29](https://www.cnn.com/2026/07/29/business/live-news/federal-reserve-interest-rate-07-29-26);
  [CBS News, 2026-07-29](https://www.cbsnews.com/news/federal-reserve-interest-rates-kevin-warsh-july-206/);
  [Bloomberg, 2026-07-29](https://www.bloomberg.com/news/articles/2026-07-29/fed-holds-rates-steady-three-officials-dissent-favoring-a-hike).
- Fed Chair **Kevin Warsh** was confirmed by the Senate 54–45 on May 13, 2026 (the narrowest
  confirmation vote for the position in US history), sworn in May 22, 2026, and unanimously elected
  FOMC chairman by the committee that day. [CNBC,
  2026-05-13](https://www.cnbc.com/2026/05/13/kevin-warsh-wins-senate-confirmation-as-the-next-federal-reserve-chair.html);
  [Federal Reserve press release,
  2026-05-22](https://www.federalreserve.gov/newsevents/pressreleases/other20260522a.htm).
- At his July 29 press conference Warsh said he would not characterize the hold as a "pause" but as "a
  rigorous review of the economic situation." [CNBC,
  2026-07-29](https://www.cnbc.com/2026/07/29/fed-rate-decision-july-2026.html) (paraphrase from
  search result; direct quote attribution per that source).
- The next scheduled FOMC decision is **September 16, 2026** (meeting September 15–16). [CNBC,
  2026-08-07](https://www.cnbc.com/2026/08/07/odds-the-fed-hikes-in-september-tumble-following-big-july-jobs-miss.html).

**What commentators expect (opinion, attributed) — and where it has moved, with dates:**
- As of **July 29, 2026** (immediately post-FOMC), Forbes reported markets had shifted toward pricing a
  September hike as "the most likely outcome." [Forbes,
  2026-07-29](https://www.forbes.com/sites/simonmoore/2026/07/29/september-rate-hike-becomes-most-likely-outcome-according-to-markets/)
- As of **August 4, 2026**, search-result summaries put the priced probability of a 25bp September hike
  at roughly 61.9%. (Source: CNBC coverage referenced within the August 7 article below; treat this
  specific number as secondhand via that article, not independently verified against the primary CME
  FedWatch page.)
- J.P. Morgan Wealth Management strategists, in coverage dated on or before early August 2026, shifted
  their base case to expect a 25bp hike at the September meeting, reversing a prior no-change base
  case — reasoning cited: energy-driven inflation from the Iran conflict and doubt about the Fed's
  resolve after the July hold. [Chase/Warsh Fed commentary,
  n.d., accessed 2026-08-11](https://www.chase.com/personal/investments/learning-and-insights/article/september-2026-rate-hike-now-expected-amid-energy-shocks)
- By **August 7, 2026**, following the weak July jobs report (below), CNBC reported the priced odds of
  a hold had risen back to 60% (i.e., hike odds fell to roughly 40%), up sharply from 45% the day
  before and "one-in-three" [hold probability implied, i.e. ~67% hike odds] a week earlier. [CNBC,
  2026-08-07](https://www.cnbc.com/2026/08/07/odds-the-fed-hikes-in-september-tumble-following-big-july-jobs-miss.html)
- By **August 11, 2026** (today), a Bloomberg market-open piece stated stocks were trading cautiously
  ahead of tomorrow's CPI print "after multiple FOMC members signaled a possible hike next month" —
  i.e., hawkish rhetoric persisting even after the odds swing described above. [Bloomberg,
  2026-08-11](https://www.bloomberg.com/news/articles/2026-08-11/us-stock-futures-rise-as-oil-erases-gains-on-iran-optimism)
  (direct fetch of this URL returned HTTP 403; this claim is sourced from the WebSearch result snippet
  of that article, not a full-text read — flagged as a lower-confidence citation accordingly).

**This is a genuinely moving target, not a settled fact**, and it is presented above with the dated
sequence rather than a single number: hike-favored (Jul 29) → hike more strongly priced (Aug 4, ~62%)
→ hike odds fall sharply on a weak jobs print (Aug 7, ~40%) → hawkish Fed rhetoric reported again the
day before this report was written (Aug 11). Anyone reading a single snapshot of "the market prices an
X% chance of a hike" without a date attached is reading a number that has already moved.

### B.2 Inflation

- **Core PCE** (the Fed's preferred gauge) was **3.3% year-over-year in June 2026**, down slightly from
  May; headline PCE was 3.7% y/y (declined 0.1% m/m). Both remain well above the Fed's 2% target — core
  PCE roughly 130bp above target. [CNN Business,
  2026-07-30](https://www.cnn.com/2026/07/30/economy/us-pce-inflation-consumer-spending-june);
  [Advisor Perspectives / dshort,
  2026-07-30](https://www.advisorperspectives.com/dshort/updates/2026/07/30/core-pce-inflation-at-3-3-in-june-edging-down-from-may);
  [qz.com, 2026-07-30](https://qz.com/june-2026-pce-consumer-spending-personal-income-073026).
- At its June 2026 meeting the Fed itself raised its own inflation projections to 3.6% headline / 3.3%
  core PCE for the year — i.e., the Fed's own forecast, not just the latest print, sits well above
  target. [Advisor Perspectives / dshort,
  2026-07-30](https://www.advisorperspectives.com/dshort/updates/2026/07/30/core-pce-inflation-at-3-3-in-june-edging-down-from-may).
- The July CPI print (for July 2026) is scheduled for **tomorrow, August 12, 2026, 8:30am ET** — after
  this report's data cutoff. [Kiplinger, accessed
  2026-08-11](https://www.kiplinger.com/investing/economy/cpi-report-july-2026-what-to-expect); [BLS
  CPI archive index](https://www.bls.gov/news.release/archives/cpi_07142026.htm) (June data, confirming
  the monthly cadence).
- July PPI is scheduled for **August 13, 2026, 8:30am ET**. [BLS PPI news release
  index](https://www.bls.gov/news.release/ppi.nr0.htm); [BLS PPI archive for June
  data](https://www.bls.gov/news.release/archives/ppi_07152026.htm) (confirms the monthly release
  pattern this date was inferred from).

The hawks' dissent case (per B.1) and the persistent above-target core PCE print are consistent with
each other as reported facts; whether that combination *justifies* a hike is commentary/opinion and is
not adjudicated here.

### B.3 Labor market

- **July 2026 nonfarm payrolls fell by 23,000** (an unexpected decline), driven by a 53,000 drop in
  government jobs and softness in retail, leisure/hospitality, and slower healthcare growth. The
  unemployment rate edged down to **4.1%**, but largely because of a further decline in labor-force
  participation (fewer people working or looking), not stronger hiring. Average hourly earnings growth
  slowed to **3.2% y/y**, the lowest since May 2021. [CNBC,
  2026-08-07](https://www.cnbc.com/2026/08/07/jobs-report-july-2026.html).
- The August 2026 jobs report is scheduled for **Friday, September 4, 2026, 8:30am ET** — it has not
  yet been released as of this report's run date. [CNBC,
  2026-08-07](https://www.cnbc.com/2026/08/07/odds-the-fed-hikes-in-september-tumble-following-big-july-jobs-miss.html)
  (article notes the next release date in the course of discussing the July print's market impact).

### B.4 Earnings season

- As of **August 7, 2026**, 88% of S&P 500 companies had reported Q2 2026 results; 86% beat EPS
  estimates (above the 5-year average of 78% and 10-year average of 76%). [FactSet,
  2026-08-07](https://insight.factset.com/sp-500-earnings-season-update-august-7-2026).
- Blended Q2 earnings growth for the index was reported at a very high rate, but FactSet flags that
  **excluding Alphabet and Amazon it would fall to 32.0% from 50.4%** — still the second consecutive
  quarter of >20% growth and the seventh straight quarter of double-digit growth, but the headline
  number is materially inflated by two companies' one-time items: FactSet attributes Alphabet's
  outsized contribution to a $98 billion gain and Amazon's to a $53.4 billion gain "primarily due to
  investments in Anthropic." Companies overall reported earnings 29.2% above estimates — the highest
  surprise percentage FactSet has recorded since it began tracking the metric in 2008, again mainly
  attributable to the same two names. [FactSet,
  2026-08-07](https://insight.factset.com/sp-500-earnings-season-update-august-7-2026).
- Ten of eleven sectors are reporting y/y earnings growth; eight are reporting double-digit growth, led
  by Energy, Communication Services, Consumer Discretionary, Information Technology and Materials.
  [FactSet, 2026-08-07](https://insight.factset.com/sp-500-earnings-season-update-august-7-2026).
- **This report's own sector-level price data (A.4/A.5) does not straightforwardly match that
  earnings-growth ranking** — e.g. FactSet lists Communication Services among the double-digit
  y/y-earnings-growth sectors, while XLC is this report's *worst*-performing sector on 3-month price
  return (−3.48%) and one of only two sectors below its own 200-day SMA. That is a genuine and
  unresolved divergence between reported earnings growth and realised price action for that sector as
  of this run; this report does not attempt to reconcile it (a plausible reading — market pricing in
  the two supersized one-off gains as non-recurring rather than durable EPS growth — would be
  commentary, not measurement, and is flagged rather than asserted).

### B.5 Dominant market narrative

- The S&P 500 closed at a fresh **record high on August 4, 2026** (7,737, surpassing the prior
  June 2 record of 7,620.90) after a reported four-day, $3.7 trillion rally attributed to corporate
  earnings and a pullback in oil prices; the index has closed at a record 25 times in 2026 per that
  report. The Dow closed above 54,000 for the first time the same day. [CNN Business,
  2026-08-04](https://www.cnn.com/2026/08/04/investing/us-stock-market).
- 24/7 Wall St. attributes much of the 2026 rally specifically to **Nvidia and Micron**. [24/7 Wall
  St., 2026-08-09](https://247wallst.com/investing/2026/08/09/nvidia-and-micron-have-driven-the-sp-500s-2026-rally-to-record-highs-history-says-its-not-over/)
  — the "history says it's not over" framing in that headline is the outlet's own forward-looking
  opinion, not a fact, and is noted here only as attributed commentary.
- On **August 11, 2026** (today), major indices were reported modestly lower intraday ahead of
  tomorrow's CPI print (Dow −0.06% to −0.34% depending on the source/time of the snapshot, S&P 500
  roughly −0.10%, Nasdaq Composite −0.39% to −0.67%), while the Russell 2000 (small caps) bucked the
  trend, **up about 0.4%**. Reported driver: oil prices rising on continued disruption to the Strait of
  Hormuz, with US crude "topping $83" intraday as Iran reiterated it would keep the waterway closed
  until its demands were met; a separate report the same day described futures as recovering somewhat
  on "Iran optimism." [Zacks/CNBC via search,
  2026-08-11](https://www.zacks.com/stock/news/2972437/stock-market-news-for-aug-11-2026); [TheStreet,
  2026-08-11](https://www.thestreet.com/stock-market-today/stock-market-today-dow-jones-sp-500-nasdaq-updates-aug-11-2026);
  [Bloomberg, 2026-08-11](https://www.bloomberg.com/news/articles/2026-08-11/us-stock-futures-rise-as-oil-erases-gains-on-iran-optimism)
  (this last URL 403'd on direct fetch; cited via its WebSearch snippet only).
- Notable single-name move reported the same day: **Nvidia +1.5%** after reportedly arranging $500
  billion in private bank financing for further AI-infrastructure buildout; **Intel −1.5%** (extending
  a 4% slide from the prior day) after raising its planned stock sale by $5 billion to $20 billion.
  [Zacks/Bloomberg via search, 2026-08-11] (same sources as above).
- **The dominant background narrative is a live regional war.** The **2026 Strait of Hormuz
  crisis/Iran war fuel crisis** began February 28, 2026 with a US-Israel air campaign against Iran; by
  early August, roughly five months of intermittent attacks on shipping and retaliatory strikes had
  disrupted a strait that normally carries about 20.3 million barrels/day (~25% of seaborne oil trade).
  Strait traffic was reported to have partially recovered in the week of July 27–August 2 (84 transits,
  up from 45 the prior week), but the situation was described as ongoing and unresolved as of early
  August. [Discovery Alert, accessed
  2026-08-11](https://discoveryalert.com.au/iran-war-strait-hormuz-oil-prices-shipping-crisis-2026/);
  [Wikipedia, "2026 Strait of Hormuz
  crisis," accessed 2026-08-11](https://en.wikipedia.org/wiki/2026_Strait_of_Hormuz_crisis); [Lloyd's
  List Intelligence, 2026-08-05](https://www.lloydslistintelligence.com/resources/blog/strait-of-hormuz-brief-5-august-2026).
  (Wikipedia is used here only for the general shape/dates of an unfolding news event, corroborated by
  the trade-press and mainstream-outlet sources cited elsewhere in this section; it is not relied on
  for any market-data figure.)

### B.6 Calendar for the next 4–8 weeks (from 2026-08-11)

| Date | Event | Source |
|---|---|---|
| 2026-08-12 | **July CPI** (BLS, 8:30am ET) | [Kiplinger](https://www.kiplinger.com/investing/economy/cpi-report-july-2026-what-to-expect) |
| 2026-08-13 | **July PPI** (BLS, 8:30am ET) | [BLS PPI release index](https://www.bls.gov/news.release/ppi.nr0.htm) |
| 2026-08-14 | July advance retail sales (Census Bureau, 8:30am ET) | [Census Bureau Advance Monthly Retail report schedule, via WebSearch summary] |
| 2026-08-18 | Home Depot Q2 FY2026 earnings (BMO) | [Barchart](https://www.barchart.com/story/news/3736265/dear-home-depot-stock-fans-mark-your-calendars-for-august-18) |
| 2026-08-20 | Walmart Q2 FY2027 earnings (before open, ~6am CT materials / 7am CT call) | [MarketBeat](https://www.marketbeat.com/earnings/reports/2026-8-20-walmart-inc-stock/) |
| 2026-08-26 | **Nvidia Q2 FY2027 earnings** (call ~5pm ET) | [Investing.com](https://www.investing.com/news/assorted/nvidia-schedules-q2-fiscal-2027-earnings-call-for-432SI-4821803) |
| 2026-08-27 to 2026-08-29 | **Jackson Hole Economic Policy Symposium** ("Financial Innovation: Implications for Payments and Policy") — Chair Warsh's first Jackson Hole as chair | [Finance Calendar](https://www.financecalendar.com/event/jackson-hole-economic-symposium-2026/) |
| 2026-09-04 | **August jobs report** (nonfarm payrolls, BLS, 8:30am ET) | [CNBC, 2026-08-07](https://www.cnbc.com/2026/08/07/odds-the-fed-hikes-in-september-tumble-following-big-july-jobs-miss.html) |
| 2026-09-11 | **August CPI** (BLS, 8:30am ET) — explicitly reported as the last CPI print before the Sept 16 FOMC decision | [Morningstar](https://www.morningstar.com/economy/august-cpi-report-forecasts-point-sticky-inflation-tariff-pressures) |
| 2026-09-15 to 2026-09-16 | **FOMC meeting**, decision 2026-09-16 — the pivotal near-term event given the live hike/hold debate in B.1 | [CNBC, 2026-08-07](https://www.cnbc.com/2026/08/07/odds-the-fed-hikes-in-september-tumble-following-big-july-jobs-miss.html) |
| ~mid-to-late September 2026 (date not pinned down) | August advance retail sales | [Census Bureau release-schedule search summary — low confidence, see note below] |
| 2026-10-02 (edge of the 8-week window) | September jobs report | [CNBC, 2026-08-07](https://www.cnbc.com/2026/08/07/odds-the-fed-hikes-in-september-tumble-following-big-july-jobs-miss.html) |

The August retail sales date could not be pinned to a specific day from available sources — Census's
own release-schedule material only confirms the July print (2026-08-14, included above) and a separate
September 28 date for a *revision* to an earlier estimate, not the August advance estimate's own
release date. It is included in the calendar only as an approximate "expect it in this window" note,
explicitly flagged as lower-confidence than every other row in this table, which are each pinned to a
specific confirmed date.

### B.7 Where sources conflicted, or could not be verified

- **Fed hike odds are the clearest case of genuine, dated disagreement across time**, not sources
  disagreeing about the same moment — see the sequence in B.1. This is not a "sources conflict" problem
  so much as "the number is real but has a very short half-life"; it is presented as a timeline rather
  than a single figure for that reason.
- Two URLs (the Bloomberg 2026-08-11 futures article and a CNBC 2026-08-07 article) returned HTTP 403
  on direct `WebFetch` and could only be sourced via their WebSearch result snippets. Both are cited
  above with that caveat; nothing in this report treats a snippet-only citation with the same
  confidence as a fully-read primary source.
- An early search result surfaced a claim attributed to Treasury Secretary Bessent that the Fed "could
  cut by September" — on inspection this was dated **2025-07-02**, over a year stale and referring to a
  different rate-path debate entirely (tariff-driven, pre-Warsh). It is **not** included above as a
  current data point; it is noted here only to record that it was found and discarded rather than
  silently omitted.
- No page fetched in the course of this research contained text addressed to an AI agent or an
  instruction to take an action; there is nothing to flag on that front.

---

## Part C — synthesis (interpretation, not measurement)

**Everything in this section is a reading of the Part A/B evidence, not a new measurement, and none of
it is a recommendation to buy, sell, or hold anything.** The study's six regime windows are: dot-com
bust (2000–02), 2003–07 bull, GFC, 2009–19 QE bull, COVID (2020–21), 2022 bear, and recent 2023+.

**On the measurable dimensions, the present most resembles a mid-cycle bull market with a hawkish
central bank** — closest, on the specific combination of (a) broad indices sitting a moderate,
single-digit-to-low-double-digit percentage above their own 200-day SMA rather than either barely above
it or extended 30%+ above it, (b) shallow drawdowns from 52-week highs (SPY −0.35%, IWM −0.24%), and
(c) a Fed that is *raising or debating raising* rates rather than cutting into weakness — to the
**2003–07 bull window**, where the Fed spent 2004–06 methodically raising rates through a rising equity
market (a genuinely comparable "hiking cycle bull market" shape). It also has surface similarity to the
**2009–19 QE bull** on the "broad participation, low realised vol, shallow drawdowns" dimension (12 of
14 instruments in the A.4 table are above their 200-day SMA), though that window's defining feature —
a Fed holding rates near zero and expanding its balance sheet — is the opposite of the current setup.

**Where it does not resemble any of the six windows at all:** none of them combine a live regional war
disrupting ~20–25% of global seaborne oil trade (the Strait of Hormuz crisis, B.5) with equities at
record highs and a Fed weighing a *hike* rather than a cut. The 2022 bear had rate hikes into weakness,
not into strength; the GFC and COVID windows had elevated, not muted, VIX (this snapshot's VIX sits at
its 13th percentile over the trailing year — A.6); the dot-com bust had a single-sector valuation
collapse, not a commodity-driven geopolitical shock. Persistent core PCE at ~3.3% y/y for an extended
period (B.2) with the Fed's own forecast still above target is also not well matched by any of the six
windows — the 2003–07 and QE-bull windows both ran with inflation closer to or below the Fed's target,
which is precisely why 2003–07's Fed-hiking-into-strength shape is only a partial analogue: it wasn't
also fighting a war-driven supply shock to keep inflation from re-accelerating.

**The sector picture (A.4/A.5) is itself internally inconsistent with a single clean narrative.**
Energy (XLE) is near the top of the 200-day-distance table and has the largest 1-month return (+7.4%)
in the internals table — directly explainable by the oil shock in B.5 — while Healthcare (XLV) is the
single best 3-month performer (+17.98%) for reasons this report's price/technicals data cannot itself
explain (no defensive-rotation news narrative was surfaced in Part B to account for it), and
Communication Services (XLC) is simultaneously one of FactSet's cited double-digit *earnings*-growth
sectors and this report's worst 3-month *price* performer (B.4's flagged, unresolved divergence). A
reader looking for "growth leads, defensives lag" or the reverse will not find a clean version of
either story in this data.

**Trend-following vs. mean-reversion relevance, stated descriptively:**

- The conditions in A.4/A.6 — broad indices modestly (not extremely) above both moving averages,
  shallow current drawdowns, and realised/implied volatility sitting in the bottom third of its own
  recent history — are, on their face, the kind of condition under which the study's trend-following
  family (moving-average alignment, MA-crossover rules) has the most *room to be tested meaningfully*:
  there is an established, still-intact uptrend to potentially follow, and low current volatility means
  a trend rule is not being whipsawed by day-to-day noise right now. Whether such rules actually showed
  an edge historically under comparable conditions is exactly what the primary-family quant streams are
  testing on the historical windows — this section only describes that the *present* conditions are the
  kind those rules are meant to operate in, not that they will work.
- The same conditions are close to the opposite of what a mean-reversion/oversold-bounce family is
  built for: nothing in the A.4 table is oversold, no sector is meaningfully below its 200-day SMA
  except XLU and XLC at roughly −2.6% each (a mild, not extreme, condition), and VIX sitting at a low
  percentile means Bollinger-band-width-style contraction/expansion setups have less room to have
  fired recently. A reader applying a mean-reversion rule's historical hit rate to *today's* market
  should note the entry conditions those rules require are largely absent right now.
- **This could change quickly and the calendar in B.6 is exactly where.** The September 16 FOMC
  decision, tomorrow's CPI print, and the ongoing Strait of Hormuz situation are all plausible sources
  of a volatility spike from today's low base (13th percentile over the trailing year — A.6). If any
  of them produce one, the entry conditions for a mean-reversion family (oversold RSI, band-width
  contraction) become more present than they are today, while a trend-following rule already in
  position would be tested precisely in the kind of regime break it is designed to survive (or not) —
  which is what the regime-breakdown sections of the quant streams' reports should be read against.

---

## What this cannot tell you

- **This is a single point-in-time snapshot, generated 2026-08-11.** By the time this is read, the
  CPI print (tomorrow), the PPI print (the day after), and ordinary daily price action will have moved
  several of the numbers in Part A, and the Fed-hike-odds figures in Part B were already shown to move
  by double-digit percentage points within a single week (B.1). Nothing here is current beyond the
  dates attached to each figure.
- **Distance from a moving average and drawdown-from-high are price technicals, not valuation or
  fundamentals.** A sector sitting comfortably above its 200-day SMA says nothing here about whether
  its constituent companies are cheap, expensive, or fairly priced, and this report makes no attempt to
  assess that.
- **The CNN Fear & Greed composite's exact scoring methodology is undocumented** (per `app.market.
  providers.cnn`'s own module docstring) — the score and component ratings are CNN's own numbers,
  reproduced faithfully, but CNN can and does revise the underlying methodology without notice, and the
  0–100 score's precise construction from the seven components is not something this codebase (or this
  report) can independently verify.
- **The six regime windows in Part C are qualitative labels chosen by the study, not the output of a
  statistical regime-detection model.** No clustering or change-point algorithm was run to classify
  "today" against history; Part C's synthesis is a reasoned reading of the same measured numbers a
  human analyst would look at, and a different analyst could weigh the same evidence differently. It is
  explicitly interpretation, not a fourth measurement layer.
- **The Strait of Hormuz situation is an active, evolving news event**, not a settled historical fact
  like the study's other regime windows. Every oil price, energy-sector figure, and inflation-adjacent
  claim tied to it in this report can be stale within days, in either direction (further escalation or
  resolution), in a way none of the study's closed historical windows can be.
- **FRED-vs-Yahoo proxy differences are real and small but nonzero** (10Y: 4.65% FRED as of 08-07 vs.
  4.699% Yahoo `^TNX` as of 08-10 — about 5bp apart on top of the multi-day lag). Which source a reader
  treats as "the" 10-year yield changes the exact number, if not the broad picture.
- **Web-search-derived facts are only as good as what was indexed by the time of this run** (2026-08-11
  afternoon Pacific). Some Part B figures (exact CME FedWatch percentages in particular) are explicitly
  moving targets captured at one search timestamp, not a live feed; this report says so at each such
  point rather than presenting them as fixed.
- **None of this predicts what any instrument will do next.** Sector dispersion, VIX percentile,
  distance from a moving average, and a sourced news calendar describe where things stand and what is
  scheduled; they are not a forecast, and this report does not offer one.
