# The window matrix

One window is one draw. A strategy that wins one window has won one coin toss. The program ranks on
the **distribution across windows**, and the windows are chosen for **regime diversity**, not for
recency.

**The benchmark is SPY in every window, price-only, bought at the window's first open and held to its
last close** — the identical entry and exit convention every strategy gets. Each window carries its
own benchmark, computed by the runner over that window's own sessions. Never compare a return from
one window to a benchmark from another.

## The current matrix — round 2

Eight windows, 1,729 sessions. Ordered here as they are run: cheapest first, so a run that has to be
cut short still yields the widest regime coverage.

| tag | window | sessions | SPY | ann. vol | max DD | regime |
|---|---|---|---|---|---|---|
| `q4-2018` | 2018-09-21 → 2018-12-24 | 65 | −20.05% | 20.8% | −19.74% | sharp quarter-long selloff |
| `covid` | 2020-02-19 → 2020-06-30 | 93 | −8.71% | 51.5% | −34.10% | fastest crash on record, then a violent snapback |
| `bear-2022` | 2022-01-03 → 2022-10-12 | 196 | −25.14% | 24.2% | −25.36% | grinding rate-driven decline, no shock |
| `chop-2015` | 2015-04-07 → 2016-04-15 | 260 | **−0.04%** | 16.6% | −14.35% | **sideways** — a year of motion arriving nowhere |
| `chop-2011` | 2011-05-26 → 2012-06-06 | 260 | **−0.05%** | 22.9% | −18.79% | **sideways**, at higher volatility |
| `bull-2024` | 2024-08-21 → 2025-08-20 | 250 | +14.00% | 19.7% | −19.00% | ordinary good year |
| `recent` | 2025-08-21 → 2026-08-18 | 249 | +20.62% | 12.9% | −9.13% | most recent twelve months |
| `gfc` | 2007-10-09 → 2009-03-09 | 356 | −56.23% | 38.0% | −56.47% | the deepest drawdown available |

**The two `chop` windows are round 2's most important addition.** Round 1 held two bears, one crash
and two bulls, and no directionless market at all — yet several analysts pre-registered whipsaw as
the regime they feared most, `c04-riskmanaged` naming it first. A prediction the matrix cannot
evaluate is a prediction nobody scored.

These are not corrections relabelled as chop. Both were found by scanning 30 years of SPY for windows
where the index goes **nowhere** while moving constantly: `chop-2015` returns −0.04% across 260
sessions at 16.6% volatility, `chop-2011` returns −0.05% at 22.9%. A trend rule cannot make money in
either without threading the reversals, and a stop-based rule will be tested on how often it is
whipsawed out.

Round 1 used five of these windows — `gfc`, `covid`, `bear-2022`, `bull-2024`, `recent` — with
identical dates, so any card run in both rounds is directly comparable on them.

### The special-case window

| tag | window | sessions | SPY | why it exists |
|---|---|---|---|---|
| `13f-legal` | 2025-11-17 → 2026-08-18 | 188 | +14.60% | The only window a 13F-derived universe may legally trade, given filings knowable from 2025-11-14. Not part of the main matrix and never counted toward the gate. |

## Eligibility, and why it is the anti-overfitting mechanism

A card can only run in a window where **every symbol in its universe** has enough history before the
window starts — the indicator's warmup plus the 40 post-warmup bars the lookahead guard needs to
demonstrate causality. A card holding a 2024 IPO cannot be run against the GFC. The guard raises
`GuardFailed` rather than running on partial data.

> **The gate: a card eligible in fewer than five of the eight main windows is reported as unranked.**
> Not last — unranked, with its numbers shown and excluded from the ranking.

Five of eight is the same 60% proportion round 1 required at three of five. It binds harder now
because there are more windows to be absent from, and that is intended: round 1 established that a
card's universe decides which history it can be judged against, and the field should feel that.

**This is the mechanism that ties universe choice to generalisation.** Nobody is told which symbols
to pick. But a universe assembled from recent high-momentum names can only be tested in recent
high-momentum windows, and a card testable in few regimes cannot be ranked. An analyst who wants a
rankable card has to choose names that existed through something bad. That is a cost the analyst
chooses to pay or not, with the consequence stated in advance rather than discovered afterwards.

Round 1 proved the point before a single trade was simulated: **not one inherited card could run the
GFC**, because the entire legacy field was built on a semiconductor and AI universe that did not
exist in 2008.

### Provenance — a second, independent eligibility test

History is not the only thing that makes a window illegal. A card whose universe was **selected from
a point-in-time document** may only trade windows beginning after that document was public.

A card may declare `universe_knowable_from`. Any window starting before that date is ineligible,
whatever the price history says. This exists because round 1's scorer ranked a 13F-derived card on
four windows that all predated its own filings — the guard passed it, because the guard checks
whether an *indicator* is causal on symbols already chosen and cannot know when the *basket* became
knowable. That was caught by a human reader, which is not a control.

#### Index membership is a point-in-time document too

The store now carries every current S&P 500 and Nasdaq-100 constituent, pulled from the N-PORT
holdings that `IVV` and `QQQ` file with the SEC. That is a large increase in what an analyst may
choose from, and it comes with a trap that is easy to walk into and invisible in the results.

**Today's index is not 2008's index.** The S&P 500 as it stands contains no Lehman Brothers, no Bear
Stearns, no Washington Mutual, no Countrywide, no General Motors — every one of them was removed
*because it collapsed*. A card whose universe is drawn from the current list and then run over the
`gfc` window is not testing a strategy against the financial crisis. It is testing a strategy against
the subset of the crisis's participants that survived it, which is a different and much kinder
experiment. The same holds in weaker form for `covid` and `bear-2022`.

The bias is in the *selection*, not in the data: the bar store holding 600 symbols is neutral, and
adding history for a company that later failed would if anything reduce the problem. What creates the
bias is choosing names from a list whose membership was determined after the window being tested.

So **`data/universe/index-constituents.json` carries a `knowable_from` date — the N-PORT period the
membership was read from — and a card that *selects its universe from that file* inherits it.** The
provenance gate above then does the rest, exactly as it does for a 13F basket: windows starting before
that date are ineligible, and a run file for one forces the card unranked.

**The gate is scoped to the selection, not to the store, and the distinction is the whole rule.**
Written as a blanket condition it swallows everything: every window in the matrix begins before
2026-03-31, including `recent`, so a rule of "anything touching index-listed symbols is gated" leaves
a round with nothing rankable at all — which is not rigour, it is a rule that has stopped discriminating.
What actually creates the bias is *choosing names from a list whose membership was decided after the
window being tested*. An analyst who picks twelve semiconductor names on a liquidity and thesis
argument has not done that, even though those names are also in the index; an analyst who writes "I
took the largest constituents of the S&P 500" has.

So the rule is:

- **A card that declares an index-derived selection inherits `knowable_from` and is gated.** Round 3's
  `B-wide` and `C-wide` are exactly this case and carry the sidecar to prove it.
- **A card that selects on its own reasoning is not gated**, and instead states its selection argument
  in its thesis, where a reader can judge it.
- **Survivorship is reported per window in either case, sized rather than asserted.** Index turnover
  runs a few percent a year, so a twelve-month window carries a small distortion and an eighteen-year
  one carries a large one. A round report that says "the GFC number is flattered by an unknown amount"
  has told the reader something; one that silently blocks the window has told them nothing.

None of this makes an index-derived GFC result trustworthy. It makes the untrustworthiness *legible*,
which is the more useful of the two, and it keeps the eight windows available to the cards that earned
them. `strategy-program/PROTOCOL.md` §3's point stands: the universe choice is the analyst's own
trade-off, and now so is the disclosure that comes with it.

## Symbol history tiers

The symbol count below is **stale as of 2026-08-21** and is kept because the tiering it describes is
still the right way to read the constraint. The store has since been expanded from 173 symbols to the
full current S&P 500 and Nasdaq-100 membership — see `data/universe/index-constituents.json` for the
list and the date it was read, and the survivorship note above before selecting from it. The tiers
themselves are unchanged in kind: a symbol still reaches only the windows its own history covers, and
most newly added constituents are long-listed large caps that reach every window.

173 symbols have readable daily bars. First-bar dates group as follows.

**Reaches every window including the GFC — first bar ≤ 2004 (86 symbols)**
`BA CAT DIS GE HON JNJ KO PG XOM ^TNX DX-Y.NYB DE ETN PEP PFE TXN WMT BAC NEE AMD DUK INTC JPM SHW
TMO AAPL HD SO T MU UNH ORCL MSFT ADBE ^VIX CSCO QCOM LIN SPY MDY EWC EWG EWJ EWU BRK.B AMZN TSM DIA
XLB XLE XLF XLI XLK XLP XLU XLV XLY NVDA QQQ EWY IWM SMH MRVL EWZ IBB VTI SOXX IGV ACN EFA NFLX IEF
LQD SHY TLT EEM RSP AGG DVY TIP VTV VUG GOOG GOOGL FXI GLD`

**First bar 2005–2009 (26)** — reaches `chop-2011` onward; GFC only at the margin
`VWO DBC XBI XHB USO SLV VIG ITA GDX MA QLD SSO KRE XRT BND HYG BIL VEA NLR MUB V TAN ICLN UPRO AVGO
GDXJ`

**First bar 2010–2014 (25)** — reaches `chop-2015` onward
`PPLT SQQQ TQQQ SOXL SOXS TSLA VOO URA NUGT SPLV SCHD USMV CPER INDA META NOW PANW ABBV KORU MTUM
VLUE QUAL ARKW ARKG ARKK`

**First bar 2015–2019 (8)** — reaches `q4-2018` or `covid` onward
`JETS LABU LITE XLRE DELL XLC BE NET`

**First bar 2020–2022 (14)** — `bear-2022` at best, most only `bull-2024` onward
`SGOV SNOW PLTR QQQM DTCR SOFI RBLX COIN OKLO IREN CRDO APLD TSLL GGLL`

**First bar 2023 or later (14)** — `recent` only, cannot clear the gate
`MSTZ MUD NBIS SNDK CRCL KOID HUMN FIG TSSD DRAM FOTO SPCX IQQ SKHY`

Leveraged and inverse instruments are present (`TQQQ SQQQ SOXL SOXS UPRO SSO QLD LABU NUGT TSLL GGLL
MSTZ`). They are not excluded by the harness, but a daily-rebalanced leveraged ETF held for months is
a decay instrument, not a leveraged position, and no card should hold one across a multi-month window
without saying why.

## Data access rule

The bar store is a single DuckDB file and the default connection takes a **write lock**. Two
processes reading it concurrently fail with an `IOException` that surfaces as a per-symbol data
refusal — indistinguishable from a nonexistent ticker. This has cost this project real work twice.

- **Research** (any number of concurrent agents): `duck.connect(path, read_only=True)`. Verified
  concurrent-safe.
- **Backtests**: exclusive. The runner takes a write lock. Nothing else may touch the store while a
  round is running.
