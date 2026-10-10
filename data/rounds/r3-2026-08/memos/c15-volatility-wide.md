# c15-volatility-wide — Volatility Shock Reversal: leveraged financials & cyclicals

## 1. Mechanism, and who is on the other side

The entry is `high - low > atr(14) * 1.5 and close < open and rsi(14) < 30`: a single-name true-range
day at least 1.5x that name's own trailing ATR(14), closing down, in a name that is already
short-term oversold. That is a **volatility shock**, defined purely by the size of the move relative
to the stock's own recent normal range — not a trend signal, not a level (RSI alone would just be
"the stock went down a lot over two weeks"; requiring the *range* to blow out on top of that isolates
the sessions where something acute happened).

The bet is that a single day's panic usually overshoots the news that caused it, because the sellers
on that day are frequently not pricing the business — they are meeting a constraint:

- margin-called or stop-out leveraged longs, forced to sell into the print regardless of price,
- vol-targeting and risk-parity strategies cutting gross exposure mechanically as realized volatility
  jumps, which is itself a function of the shock day and therefore lags it by design,
- short covering that adds to the down-move, then air-pockets once it's done.

None of those three is doing valuation work. I am buying at the next session's open (the broker's
fill convention: decisions on today's close execute at tomorrow's open, so there is no lookahead) from
whoever was forced to sell, and selling into the reflex bounce — `close crosses_above sma(10)`, an 8%
stop, or a 10-session time cap, whichever comes first.

**This is a short-horizon reversal, not a fundamental dip-buy**, and it is explicitly *not* the same
claim as post-earnings-announcement drift (which argues large surprises keep drifting for weeks and
is a continuation thesis, used by the round-2 `G-volatility` card). My entry gate is the shock's
*magnitude*, not its direction of continuation — a volatility-discipline trade, not a momentum one.

## 2. Selection argument — explicitly not index-derived

**This universe is not drawn from `data/universe/index-constituents.json`, and I did not select it
because these are today's S&P 500 members.** I chose money-center banks (C, BAC, WFC, JPM), a
broker-dealer pair (MS, GS), a large regional/monoline lender (COF), an insurer (AIG), an auto
manufacturer (F) and a miner (FCX) because balance-sheet leverage and commodity/operating cyclicality
are structural, multi-decade properties of these business types — a levered bank's equity is a
leveraged claim on its assets, so its equity volatility is structurally higher than an unlevered
industrial's in any decade, not only in 2008. That is a mechanism argument, not a lookback at which
names happened to crash hardest.

Before looking at any trading-window return I required, from the 15-name financial/cyclical shortlist
below, only two things: (a) price history reaching back before 2005, so the card can actually be
judged in `gfc`, `covid`, `q4-2018` and both `chop` windows, and (b) a trailing-year ATR/price ratio,
measured through 2026-02-13, tight enough that one stop-loss and one position size are a defensible
approximation across the whole book — the same non-window-scanning selection method the round-2
`G-volatility` card used for its semiconductor book, applied here to a sector nobody in this round's
field has touched.

Shortlist scored (ATR(14)/close, trailing 252 sessions to 2026-02-13; first available bar):

| symbol | ATR/px % | first bar |
|---|---|---|
| C | 2.68 | 1977-01-03 |
| BAC | 2.25 | 1973-02-21 |
| MS | 2.55 | 1993-02-23 |
| GS | 2.66 | 1999-05-04 |
| AIG | 2.14 | 1973-01-02 |
| WFC | 2.53 | 1972-06-01 |
| F | 2.60 | 1972-06-01 |
| JPM | 2.20 | 1980-03-17 |
| COF | 3.00 | 1994-11-16 |
| FCX | 3.82 | 1995-07-10 |
| OXY | 3.00 | 1981-12-31 |
| SLB | 3.11 | 1981-12-31 |
| BIIB | 3.05 | 1991-09-17 |
| REGN | 3.26 | 1991-04-02 |
| MRVL | 5.45 | 2000-06-30 |

The 10 finalists (C, BAC, MS, GS, AIG, WFC, F, JPM, COF, FCX) are the subset clustering 2.14%–3.82%
ATR/price (1.8x spread), all with history to at least 1999 (well before `gfc`). OXY/SLB were dropped
for zero shock-fires in `gfc` in my own measurement below (see §3) despite qualifying on dispersion —
that is a firing-frequency check, not a return check, and I report it rather than silently swap them
in. BIIB, REGN and MRVL were dropped for being outside the tight cluster or (MRVL) far outside it.

I did **not** rank this shortlist by which names had the biggest 2008 drawdown — the shortlist itself
is a structural sector list (leveraged financials + cyclicals with long history), scored only on
ATR/price and history length, both computable at any date and neither a function of window returns.

## 3. What I measured through 2026-02-13

Using Wilder ATR(14), Wilder RSI(14), and a 10-session SMA computed from the store's own OHLC bars
(no data past 2026-02-13 read at any point):

**Combined entry-firing frequency, 10-symbol book, atr_mult=1.5 / rsi_th=30 / close<open:**
622 fires across the full available history of the 10 symbols (oldest name back to 1972), 13.9 fires
per year combined, or roughly **7 fires expected across a 127-session (~6-month) window** — a usable
frequency, not a dead gate, though a single symbol alone fires only 0.5–0.9x/year.

**Fires by regime window (pre-cutoff portion only, since the store stops at 2026-02-13):**

| window | fires (10-symbol book) |
|---|---|
| gfc | 48 |
| covid | 39 |
| chop-2015 | 34 |
| chop-2011 | 33 |
| q4-2018 | 26 |
| bull-2024 | 7 |
| recent (partial, only ~half observable pre-cutoff) | 3 |
| bear-2022 | **0** |

The entry fires far more often in volatile/crisis regimes (gfc, covid, both chops, q4-2018) than in
calm bull markets — expected, since the gate requires an ATR-relative shock. **`bear-2022` produced
zero qualifying signals in this book through the design cutoff.** `bear-2022` is characterized in
`strategy-program/WINDOWS.md` as "grinding rate-driven decline, no shock" — precisely the regime this
entry cannot see, because there is no single acute range-expansion day to trigger on. I am reporting
this now, before any trading-window result exists, rather than discovering it afterward: I expect the
card to sit near-fully in cash through `bear-2022`, which given SPY fell ~25% in that window would
show as a *large positive excess return* that reflects being out of the market, not a working edge.
A reader should discount that number accordingly rather than read it as the thesis validated.

I did not scan trading-window returns to pick `1.5` or `30` — I scored `(1.8, 30)`, `(1.5, 35)`,
`(1.3, 35)` and `(1.5, 30)` purely on firing frequency (not on any return), and chose `(1.5, 30)`
because it sits between a too-rare gate (`1.8/30`: 3.5 fires per 6-month window, real risk of a
"never fires" report in a quiet window) and a too-loose one (`1.3/35`: ~20 fires per 6-month window,
which stops being "a shock" and starts being "any down day," diluting the whole thesis).

## 4. Every parameter, and why

- **`atr(14)` window = 14** — Wilder's own default and the same window used by every other ATR-based
  card in this repo (`G-volatility`); no reason to deviate, and changing it without a reason is
  exactly the kind of free parameter this programme is designed to punish.
- **`1.5` ATR multiple** — chosen on firing-frequency grounds alone (§3), not on return.
- **`close < open`** — restricts the shock to a down day, since the mechanism is specifically "forced
  selling," not "any large range."
- **`rsi(14) < 30`** — the conventional oversold threshold; confirms the down-day is part of a
  short-term exhaustion move rather than the first day of a fresh decline from a neutral level.
- **`sma(10)` exit** — a 10-session average is roughly two trading weeks, long enough to filter
  single-day noise in the exit signal, short enough to actually capture a reflex bounce before it
  fades; this is the same rough horizon as the 10-day time cap below, deliberately, so the exit rule
  and the time stop are consistent about what "the bounce" means.
- **`stop_loss_pct = 0.08`** — sized to this book's own ATR/price cluster (2.1%–3.8%, so 8% is
  roughly 2.5–3.5x a typical day's true range), wide enough not to be stopped out by ordinary
  post-shock chop, tight enough to cap the falling-knife case named in §5. Note the engine checks
  stops against the **prior close**, not the intraday low, so this is somewhat more forgiving of a
  single bad intraday print than a real broker's stop would be.
- **`max_hold_days = 10`** — if the bounce hasn't arrived in two weeks, the "shock was noise" thesis
  has failed for that trade; consistent with the `sma(10)` exit horizon above.
- **`take_profit_pct = null`** — the exit rule and the time cap are the two ways this closes on
  purpose; a fixed percentage target would just clip the upside tail on the exact trades (the biggest
  V-shaped snapbacks) where the mechanism is working best.
- **`max_positions = 4`, `position_pct = 0.20`** (80% max committed) — the book is
  sector-concentrated (financials/cyclicals), and shock days cluster: in a real market stress episode
  several of these 10 names gap on the same day, so 4 slots deliberately caps single-episode
  concentration risk rather than sizing for the (rarer) case of 10 independent, uncorrelated signals.

## 5. What would falsify this

If the shock is not noise but newly, correctly-priced information — a name is actually insolvent,
guidance is durably impaired, the business model itself broke — there is no reflex bounce to sell
into, and the strategy has simply bought a falling knife on the way to a much larger loss, repeatedly,
because the entry re-fires on every subsequent shock day of the same ongoing decline. The clean
falsification test is: **does the exit-or-stop win rate collapse specifically in a sustained,
fundamentally-driven decline, while holding up in sharp-but-temporary panics?** If the strategy loses
money at roughly the same rate in `gfc` as in `covid` and `q4-2018`, the "temporary vs. fundamental"
distinction I'm relying on isn't real and the edge is just short-term reversal with no additional
information content over a generic oversold-bounce rule.

## 6. Prediction

**Worst window: `gfc`.** Several of this exact book's names (C, BAC, AIG, MS, GS, WFC) had genuinely
impaired balance sheets in 2007–09, not merely a liquidity air-pocket — AIG required a federal
rescue, Citigroup and Bank of America both took multiple rounds of forced capital. That is precisely
the falsification case in §5: the entry fires 48 times in `gfc` (the most of any window), and I
expect a meaningfully worse-than-usual share of those trades to run through the stop rather than the
`sma(10)` exit, because the "shock" days it is buying are not overreactions, they are correct
markdowns of insolvency risk arriving in real time. I expect `gfc` to be this card's clearly worst
window, both on excess return and on hit rate.

**Best window: `covid`.** The Feb–Mar 2020 crash was fast and fundamentally temporary — a forced,
liquidity-driven deleveraging followed by a policy-driven V-shaped snapback within weeks, which is
exactly the shape this mechanism is built to harvest, and the entry fired 39 times in the pre-cutoff
portion of that window alone. I'd also expect solid, steadier (if less dramatic) performance in both
`chop` windows, where a directionless market with no trend to fight is close to the ideal environment
for a pure mean-reversion exit.

**Is this a convex payoff by design? No.** This card is closer to a **short-volatility / mean-
reversion payoff shape**: it aims to harvest small, frequent wins from overreaction in normal-to-choppy
markets, and its tail risk is concentrated in the one regime — a sustained, fundamentally-driven
decline — where the thing it's buying keeps being sold for a reason. The one place it could look
locally convex is a violent, V-shaped snapback like `covid`, where being long into the worst of the
panic and catching the whole reflex bounce could produce an outsized single-window win — but I am not
selecting for that shape the way a long-vol card would; it's a byproduct of the mechanism working as
intended in a good-case regime, not the design goal. `bear-2022`, per §3, is a separate case again: I
expect near-zero activity there rather than either a good or a bad outcome, because the entry gate
simply does not see a grinding, shock-free decline.
