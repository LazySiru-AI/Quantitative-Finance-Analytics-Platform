# c19-volatility — Panic-Bid: financials/energy shock reversion

Written before any backtest result exists, against data through 2026-02-13 only.

## 1. Mechanism, and who is on the other side

The entry requires three independent confirmations on the same close: price below the 20-day,
2-sigma Bollinger lower band (a statistical extreme relative to its own recent distribution),
RSI(14) under 30 (momentum exhaustion), and the day's true range exceeding its own 14-day ATR (the
move is an acceleration, not a slow grind to an oversold reading). Requiring all three is what
makes this a *volatility*-discipline entry rather than a plain mean-reversion rule wearing a vol
label — the ATR-relative range condition specifically selects for days the market is repricing
fast, which a bare RSI/Bollinger combination does not.

In financials and energy, the single-day moves large enough to trip all three filters are
disproportionately forced selling rather than a genuine revision of ten-year cash-flow
expectations for a bank or an integrated oil major: risk desks cutting into a VaR breach,
index/ETF-driven de-grossing, and retail panic on a headline that gets digested within days. The
counterparty on my buy is that forced seller — selling because a limit requires it that day, not
because they have re-underwritten JPMorgan or Exxon. The person I hand the position to on the exit
side is whoever is chasing the bounce once the panic is visibly over (the crossing of the 20-day
mean back above from below).

This is a **mean-reversion / short-vol payoff, not a convex one**, and I want that on the record
before any number exists: it harvests a moderate, capped reversion after each shock (exit at the
20-day mean, not at a fixed large target), and the downside is nominally capped by a 10% stop —
but the engine checks stops against the **prior close, not the intraday low**, so a shock that
turns out to be the start of a structural decline rather than a one-day panic can gap through that
stop before it is caught. That is this strategy's real tail risk, not a hedge-my-bets footnote
added after seeing a result.

## 2. Why these names

**Selected on sector volatility-characteristics and long listed history, not on today's index
membership.** Financials and energy are the two S&P sectors that have produced repeated,
large-magnitude forced-selling events across multiple decades and multiple distinct causes (S&L
stress, LTCM 1998, the 2008 financial crisis, the 2014-16 oil crash, 2020, the March 2023 regional
banking stress) — a structural reason to expect the mechanism above to recur, not a single episode
I am fitting to. Within those two sectors I chose the largest, most liquid names plus two sector
ETFs (`XLF`, `XLE`) and the regional-bank ETF (`KRE`, the direct proxy for the `banks-2023` window)
rather than the single most volatile small names, because liquidity and continuous multi-decade
history — not membership in the *current* S&P 500/Nasdaq-100 list — is the selection criterion.
Every name's first stored bar is well before 2006, except `KRE` (2006-06-21), which is still
roughly three years before the earliest round-4 window start (`recovery-2009`, 2009-03-10) and
seven years before `taper-2013` (2013-05-22). **This universe does not inherit
`universe_knowable_from = 2026-03-31`** — it is eligible on listed history in all six windows, not
gated at the 4-of-6 threshold at all.

**On `c15`'s trap, honestly.** `c15-volatility-wide` pre-registered the financial crisis as its
worst window and got its best because the specific 2008 failures — Lehman, Bear Stearns, WaMu,
Countrywide — are absent from a present-day-derived universe. My universe has the same structural
feature: `JPM`, `BAC`, `WFC`, `C`, `USB` all survived 2008 and are still trading, which is a form
of survivorship for *any* single-name financials exposure, current-index-derived or not — a
universe built from "financial institutions that existed in 2007" would necessarily include the
ones that later failed only by including names I could not have picked without knowing which ones
would fail, which is its own kind of hindsight. I mitigate this two ways rather than deny it:
first, none of round 4's six windows *is* the 2008 crash itself — `recovery-2009` starts
2009-03-10, four sessions after the actual market low (2009-03-06), so it tests the strategy on
the recovery rally, not the failure event, and the firing-frequency data in §3 shows the strategy
is nearly silent there for exactly that reason (the panic that would trip these filters had already
happened before the window opens). Second, `banks-2023` is a real, in-sample-eligible test of
"forced selling in financials" that does *not* depend on any name that failed — SVB, Signature and
First Republic are not in this universe, and the entry fires on how `JPM`/`USB`/`WFC`/`KRE`/`XLF`
traded through contagion fear, which is the honest version of the question `c15` could not answer.

## 3. What I measured through 2026-02-13

**ATR/price, trailing 252 sessions through 2026-02-13** (mean, [min, max]) — this is the dispersion
check `G-volatility`'s memo ran, to confirm one stop size is a defensible approximation across the
universe rather than the ~260x mismatch that card flagged and did not resolve:

| symbol | mean | range |
|---|---|---|
| XLF | 1.50% | 0.98% – 3.87% |
| JPM | 2.20% | 1.54% – 4.75% |
| BAC | 2.25% | 1.54% – 5.53% |
| WFC | 2.53% | 1.72% – 5.65% |
| C | 2.68% | 1.75% – 6.26% |
| USB | 2.22% | 1.42% – 5.17% |
| KRE | 2.30% | 1.52% – 5.40% |
| XLE | 2.02% | 1.42% – 4.79% |
| XOM | 2.09% | 1.54% – 4.14% |
| CVX | 2.07% | 1.37% – 4.46% |
| SLB | 3.11% | 2.30% – 6.59% |
| OXY | 3.00% | 2.16% – 6.71% |

Mean ATR/price spans 1.50%–3.11% (~2.1x, versus `G-volatility`'s ~260x across a mixed-sector,
mixed-cap universe) — close enough that a single 10% stop is a reasonable approximation for every
name here, tightest relative to `XLF` (a diversified sector fund, where 10% is a wide stop rarely
hit by the underlying entry condition) and loosest relative to `SLB`/`OXY` (where daily ranges of
6%+ are not unusual on the entry day itself).

**Entry firing frequency per window** (count of entry=True days across the 12-symbol universe,
computed directly against the rule as written — this is a signal count, not a backtest; no P&L,
fills, or exits were simulated):

| window | sessions | total entry signals | symbols that fired |
|---|---|---|---|
| `oil-2014` | 163 | 34 | JPM, BAC, WFC, C, USB, XLE, XOM, CVX, SLB, OXY |
| `volmageddon-2018` | 45 | 26 | XLF, BAC, WFC, C, USB, XLE, XOM, CVX, SLB, OXY |
| `taper-2013` | 74 | 1 | JPM |
| `recovery-2009` | 284 | 5 | JPM, C, XOM |
| `inflation-2021` | 252 | 10 | C, USB, XLE, XOM, CVX, SLB, OXY |
| `banks-2023` | 64 | 30 | XLF, BAC, WFC, C, USB, KRE, XLE, XOM, SLB |

Every window fires at least once — this card does not go silent in any of the six — but
`taper-2013` and `recovery-2009` are thin (1 and 5 signals respectively, against a 12-symbol
universe). Both are honestly explained rather than concerning: `taper-2013` was a rates/duration
event (the 10-year yield spiked on Fed taper language), not a financials/energy forced-selling
event, so a rule keyed to sector-specific panic days should and does stay mostly quiet there. And
as noted in §2, `recovery-2009`'s window opens *after* the crash trough, so the acute panic days
this rule is built to catch mostly happened before the window starts — this is a strategy that
trades the shock, not the rally that follows it, and the low count is the rule working as
designed, not a defect. `oil-2014`, `volmageddon-2018` and `banks-2023` — the three windows that
are or contain genuine sector-specific shocks — fire 26-34 times each, comfortably testable.

**Expected capital exposure**: with `max_positions=4` and `position_pct=0.20` (80% of book at full
stack), and entries clustering on shock days when several correlated names fire together (financials
and energy both showed multiple simultaneous fires above), I expect exposure to be bursty rather
than steady: near-zero for long stretches (most of `taper-2013`, most of `recovery-2009`), spiking
toward 40-80% during an active multi-week shock (`banks-2023`, the acute weeks of `oil-2014` and
`volmageddon-2018`) as multiple positions open together and are each held up to 15 sessions. Average
capital exposure across a full window is likely modest — a rough estimate of 15-30% in the three
active windows and under 10% in `taper-2013`/`recovery-2009` — because `capital_exposure` averages
notional-at-risk over the *whole* window including the quiet stretches between shocks, and this
strategy is quiet more often than it is loaded. This matters directly for the adjusted-excess metric
(`total_return − capital_exposure × benchmark_return`): a book that is mostly in cash should not, and
under this metric will not, get credit for "beating" a rising benchmark it mostly sat out of.

## 4. Every parameter, and why

- **`bb_lower(20,2)` / `bb_mid(20,2)`** — the standard Bollinger configuration (20-day SMA, 2
  population-sigma bands); not tuned, chosen because it is the textbook definition and any deviation
  would need its own justification I don't have.
- **`rsi(14) < 30`** — the standard Wilder oversold threshold at the standard 14-day period, for the
  same reason.
- **`high - low > atr(14)`** — the day's own true range exceeding its own trailing-14-day average is
  the loosest possible statement of "this is an above-average-range day," i.e., a volatility
  expansion. I deliberately did not use a multiplier above 1.0x: an earlier pass with `1.3x` produced
  zero fires in both `taper-2013` and `recovery-2009`, which read as overfitting risk (stacking three
  already-selective filters at maximum strictness) rather than a considered choice, so I relaxed it to
  the plainest form of the condition and re-measured (§3 reports the result of that relaxed version,
  not the stricter one).
- **`stop_loss_pct = 0.10`** — sits inside or just outside one trailing-year ATR for every name in
  the universe (Table in §3: max daily ATR/price up to 6.7% on `OXY`), wide enough not to be routine
  noise, tight enough to cap a failed-reversion trade before it compounds. A single number across the
  universe is defensible here specifically because the ATR/price dispersion is ~2x, not the ~260x
  `G-volatility` flagged.
- **`max_hold_days = 15`** — a time backstop distinct from the exit rule. Mean reversion into a
  20-day moving average should resolve, if it is going to, within two to three weeks; a position still
  open past that has more likely entered a structural decline than a normal shock-and-recover, which
  is exactly the failure mode described in §1 and is why the backstop is short rather than the 120-180
  days the incumbent trend cards use.
- **`max_positions = 4`, `position_pct = 0.20`** (80% of book at full stack) — sized to let a genuine
  multi-name sector shock (several banks or several energy names firing together, as `banks-2023` and
  `oil-2014` both show in §3) actually get represented in the book, while leaving 20% of capital as a
  buffer the broker won't reject as insufficient cash.

## 5. What would falsify the thesis

- If the median adjusted excess across windows is negative and the hit rate is at or below the
  binomial-noise level (~50% for a two-outcome exit-vs-stop structure), the mechanism (forced-seller
  overreaction, genuine mean reversion) is not present in this universe/period combination.
- If `oil-2014` specifically produces a large negative adjusted excess driven by repeated stop-outs
  rather than one or two, that falsifies the "shock reverts" assumption directly for a sustained
  structural decline — see §6, this is my predicted worst case and I am pre-registering the specific
  failure mode (repeated failed dip-buys, not one bad trade) rather than only the direction.
- If realized losses on stopped-out trades are systematically and substantially worse than 10% (the
  fill-delay effect described in §6), that falsifies the assumption that a prior-close stop is an
  adequate risk control for this kind of gap-prone, event-driven entry.
- If the correlation to `B-momentum`'s realized returns turns out high and positive rather than low,
  that falsifies the sector/mechanism diversification claim in §6 and this card adds concentration
  risk to the combined book rather than reducing it.

## 6. Predictions, all scored

- **Worst window: `oil-2014`, roughly −8% to −15% adjusted excess.** This window is a sustained,
  multi-month structural decline in oil, not a single panic that reverts — the entry will likely
  re-fire on energy names multiple times as the price grinds lower, and each dip-buy risks being a
  falling knife stopped out near −10-18% (worse than the nominal 10% stop on a gap-through day) rather
  than a genuine one-day shock that reverts. This is the clearest case where "forced selling
  overreacts" is the wrong read of what's happening, and I expect the data to show it.
- **Best window: `banks-2023`, roughly +5% to +10% adjusted excess.** A genuine, contained,
  sector-specific panic (regional-bank contagion fear) in names that did not themselves fail —
  exactly the shock-and-recover shape the mechanism is built for, with the highest signal density
  of any window in §3 and direct sector alignment (`KRE`, `XLF`, and the large banks) to the event.
- **Correlation to `B-momentum`: low, roughly 0.1-0.2, possibly near zero or slightly negative in
  acute-stress sub-periods.** Different sectors (financials/energy vs. AI/semiconductor), different
  mechanism (contrarian entry on weakness vs. trend-following entry on strength), different holding
  period (up to 15 sessions vs. up to 180). In a systemic risk-off event both books can show red marks
  the same week, but `B-momentum` would be getting stopped out of strength-based positions while this
  card is only beginning to enter into the same weakness — the two are more likely offset in timing
  than aligned, which is what the round's combined-book scoring is asking for.
- **Payoff shape: short-vol / mean-reversion, explicitly not convex** (restated from §1). Wins are
  capped near the distance from the shock low back to the 20-day mean; losses are nominally capped at
  10% but the prior-close stop check means a genuine gap day can realize a worse loss before the stop
  catches it. I expect the fill-delay effect (next-open fills, prior-close stops) costs on the order
  of 1-3% of edge on an ordinary reverting trade (entering a day late into the bounce, exiting a day
  late out of it) and can turn a nominal 10% stop into something closer to 12-18% realized on the
  minority of trades where the shock gaps through overnight — `oil-2014` is where I expect that tail
  to show up most.
