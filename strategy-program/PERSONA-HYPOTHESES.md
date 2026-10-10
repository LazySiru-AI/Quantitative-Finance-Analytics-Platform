# Persona hypotheses — the provenance register

Written 2026-09-09. **Not investment advice.** Nothing below is a recommendation about real capital,
and no influencer named in this document is endorsed. I am not a licensed financial adviser.

This is an audit trail, not a research finding. It links the influencer-note corpus the app has
ingested to the research rounds it has, or has not, justified, so a later reader can check that a
round's hypothesis came from evidence rather than from an agent's imagination, and so nobody re-tests
a question this programme has already answered. It does not itself run anything: no backtest, no
card, no score.

---

## 1. What this is and what it is not

The corpus is five people's opinions on YouTube, transcribed and summarised by a model. A claim's
presence in this document is evidence that *someone said it, repeatedly, on a public channel* — it is
not evidence that the claim is true, and it is not this programme's endorsement of it. Some of the
claims below belong to guests the personas themselves are reporting on (Stanley Druckenmiller, Zoltan
Pozsar, Tom Lee, Warren Buffett via 13F) rather than to the channel owner directly; each claim below
says which is which.

**Provenance caveat.** 11 of the corpus's 162 notes (5 from `creator-e`, 6 from `creator-a`)
carry `summary_source="external"` — the summary was produced outside this repo by a different model,
pasted back through `app.personas.ingest_backfill_results` and validated for ticker syntax, but never
numerically grounded by this repo's own grounding gate the way an internally-generated summary is
(`docs/BACKFILL-EXTERNAL-AGENT-RUNBOOK.md`). A claim sourced from one of those 11 notes carries one
extra layer of unverified transcription and is flagged where it matters below; none of the claims
actually used in §3 or §6 come from an external-sourced note, checked directly against each note's
`summary_source` field before writing this document.

**Not investment advice**, restated because it needs to survive being read out of context: nothing in
this corpus, and nothing derived from it in this programme, is a recommendation to buy, sell, or hold
anything.

---

## 2. The corpus, measured

Query run against the live vault, not the file tree, per the brief:

```python
from app.config import get_settings
from app.personas.service import list_personas, list_notes
settings = get_settings()
personas = list_personas(settings)
notes = {p.slug: list_notes(settings, p.slug) for p in personas}
```

**Total: 162 notes across five personas, matching the brief's figure exactly.** Per-persona counts,
languages, distinct mentioned tickers, and external-sourced counts also match the brief; nothing here
needed correcting on those axes.

| slug | display name (romanised) | notes | language(s) | distinct tickers | external-sourced |
|---|---|---:|---|---:|---:|
| `creator-c` | Creator C | 39 | ko | 68 | 0 |
| `creator-e` | Creator E | 20 | en, ko | 13 | 5 |
| `creator-a` | Creator A | 25 | ko | 107 | 6 |
| `creator-d` | Creator D | 38 | ko | 70 | 0 |
| `creator-b` | Creator B | 40 | ko | 116 | 0 |

**One thing in the brief this measurement corrects, and it matters for §7: `published` is `null` on
all 162 notes, with no exceptions.** The brief asked for a "date range of `published`" per persona;
there is none to report — checked directly (`n.published for n in notes` returns `None` for every one
of the 162, across all five personas, confirmed by a second pass counting non-null values: zero).
`docs/INFLUENCER-CONTRACT.md`'s own verified-facts section explains why: `yt-dlp`'s flat playlist
listing (what backfill actually uses) carries no upload date at all, and only a slower per-video
non-flat extract can sometimes recover one — that fallback evidently has not populated a single one of
these 162 notes. The only timestamp on any note is `ingested_at`, a crawl-time stamp (all 162 fall
between 2026-09-06 22:00 UTC and 2026-09-08 05:12 UTC — this corpus was backfilled in a two-day window
this past week), which says when the app fetched the video, not when the influencer said what it
contains. This is not a minor gap; see §7.

**Top 20 tickers by mention count, corpus-wide** (also matching the brief's figures exactly, checked
symbol-by-symbol): NVDA 49, BTC 35, AAPL 32, MSFT 30, GOOGL 29, MU 27, META 22, TSLA 22, AMZN 17,
SSNLF 16, SNDK 14, PLTR 13, AVGO 9, SPX 9, AMD 9, INTC 9, CL 9, NDX 8, TSM 8, QQQ 8.

---

## 3. The claims, by persona

Quotes are verbatim in the source language, at most 15 words, attributed to the speaker. A quote
attributed to a guest the persona is reporting on (Druckenmiller, Pozsar, Tom Lee) says so explicitly
— it is not the channel owner's own claim, only their choice to repeat it.

### Creator E (`creator-e`) — English, intraday NASDAQ/gold/BTC scalper

| claim | mechanism | tickers | numeric rule | horizon | book |
|---|---|---|---|---|---|
| "Double B" entry system | Two Bollinger Bands (lengths 20 and 4) stacked as the only signal; claims 55% win rate on a single band vs 78% on the pair, from a self-reported 1,000+ signal backtest | NQ, GC, BTC | BB(20), BB(4) | intraday (1-minute) | trading |
| RSI divergence as confirmation only | Divergence is explicitly *not* a standalone reversal signal — it must be confirmed by support/resistance and candle patterns before acting | general (NQ/ES) | RSI (period unstated) | intraday/swing | trading |
| Multi-timeframe agreement required | A higher timeframe must confirm before a lower-timeframe signal is taken, to avoid whipsaw on noise | general | none stated | intraday | trading |
| Fixed 1% risk per trade | Position sizing, not market timing — survival ("staying in the game") is valued over optimizing any one trade's edge | general | 1% of account | account-level | trading |
| Stop-hunting at prior highs/lows | Institutional order flow is claimed to deliberately trigger stops above/below visible support and resistance before reversing | general | none stated | intraday | trading |

Quote: "Divergence. Showing up does not mean a trend reversal is guaranteed." (Creator E)

### Creator D (`creator-d`) — Korean AI-capex/macro commentator

| claim | mechanism | tickers | numeric rule | horizon | book |
|---|---|---|---|---|---|
| Long-term yields drive semiconductor selloffs | Rising bond yields raise big-tech capex financing costs, which he links directly to memory/foundry weakness | MU, SNDK, SKM, GOOGL, META, AMZN | none precise (referenced 30Y at 5.302%, "highest since 2007") | days–weeks | trading |
| Fed communication surprise moves risk assets | A dovish or hawkish surprise at an FOMC/Jackson Hole event moves BTC/ETH and the Nasdaq same-session | BTC, ETH, NDX, SPX | none stated (event-triggered) | intraday/days | trading |
| GPU/AI-infrastructure supply constraint as bullish catalyst | Persistent GPU scarcity and benchmark leadership (citing Grok) support continued infrastructure capex | NVDA, AVGO, MRVL | none stated | months | trading/roth |
| Won strength hurts Samsung/SK export competitiveness | KRW appreciation against USD compresses export margins for Korean chipmakers | SSNLF | none stated | months | n/a (FX-dependent) |
| Pension-fund shortfall forces continued S&P support | State/local pension underfunding ($0.7–4.4T) is claimed to structurally compel policy support for equity appreciation | SPX | none stated | multi-year | n/a (policy-dependent) |

Quote: "반도체들 왜 이렇게 떨어졌는가? 금리 때문입니다." — "Why did semiconductors fall this much? Because of rates." (Creator D)

### Creator A (`creator-a`) — Korean macro/13F commentator

| claim | mechanism | tickers | numeric rule | horizon | book |
|---|---|---|---|---|---|
| Named-strategist year-end index targets | Repeats a specific forecaster's (Tom Lee) directional S&P call, citing his prior-year accuracy as the reason to trust the new one | SPX | none mechanical (a discretionary point forecast) | 1 year | n/a |
| Buffett/Berkshire 13F rotation as a signal | Berkshire's shift away from financials/broad ETFs into defensive consumer names read as late-cycle caution | BRK, AAPL, KO, AXP, MCO | none stated | quarters | n/a (needs 13F) |
| Physical precious-metals demand surge | 20x gold and 15x silver *physical* demand increase cited as a safe-haven/inflation-hedge signal | GLD-adjacent (gold, silver, not equities) | 20x / 15x (demand, not price) | months | n/a (needs demand data) |
| Macro investors exiting mega-cap AI longs | Druckenmiller's near-complete NVDA/META exit despite a broadly bullish AI stance, read as a crowded-trade warning | NVDA, META | none stated | quarters | n/a (needs 13F) |
| AI power/interconnect bottleneck as structural tailwind | Physical infrastructure (power, LNG, nuclear) named as the multi-year capacity constraint behind AI capex | power/nuclear names (not in top-20) | none stated | years | roth (momentum proxy testable; the supply story is not) |

Quote: "2년 연속 적중한 인물이 한 사람 있습니다" — "There is one person who has been right two years running." (Creator A, of Tom Lee)

### Creator C 투자일기 (`creator-c`) — Korean chart technician

| claim | mechanism | tickers | numeric rule | horizon | book |
|---|---|---|---|---|---|
| 20-week moving average as the trend line | Price holding above the 20-week (~100-session) MA is read as bull continuation; a confirmed close below signals a deeper correction | NDX, individual large caps | 20-week (~100-session) SMA | weeks | trading |
| Fibonacci 0.25 breakout confirmation | A 0.25 retracement ratio distinguishes a genuine triangle/convergence breakout from a false one | NDX, KOSDAQ names | Fibonacci ratio 0.25 | weeks | n/a (no Fibonacci primitive) |
| Repeated-touch levels signal an eventual break | A support or resistance line tested many times (cited: five) is read as increasingly likely to break, not increasingly strong | NDX | touch count (5) | weeks | n/a (no counting primitive) |
| Bollinger-band/trend-line convergence as a downside target | Where a broken trend line and the lower Bollinger band converge is read as the technical downside target | NDX, KOSDAQ | BB(30, 2) | weeks | trading |
| Dollar weakness supports EM rallies | A DXY breakdown is read as directly supportive of emerging-market equity rallies | EM equities (not top-20) | none stated | weeks | n/a (needs FX/DXY) |
| Chart-pattern recognition (head-and-shoulders, cup-and-handle) | Named reversal/continuation patterns in Korean equities used as entry/exit triggers | KOSPI names | none mechanical | weeks | n/a (no pattern primitive) |

Quote: "20주 이평을 계속 종가로 지켜주고 있거든요." — "It keeps holding the 20-week average on a closing basis." (Creator C)

### Creator B (`creator-b`) — Korean fundamentals/macro-constraint analyst

| claim | mechanism | tickers | numeric rule | horizon | book |
|---|---|---|---|---|---|
| Trim after "exceptional gains" | Systematic profit-taking discipline after a large run-up in an overheated sector (semiconductors named) | AI-infra chip names | none precise | months | roth (a price-extension proxy is testable; the "overheated" judgement is not) |
| Relative valuation (P/E, P/B vs comparables) | Fair value derived by comparing a company's multiples to a peer set, then buy/sell timed off the gap | NKE (worked example), general | multiples (unspecified) | months | n/a (needs fundamentals) |
| 13F as a discovery tool, not a signal | Explicit caution against copying a manager's disclosed position without cross-referencing the manager's own stated reasoning | general | none | quarters | n/a (needs 13F; also an argument against building the naive version) |
| Long-term yields are a supply/term-premium story, not a Fed-credibility one | 30-year yield rise attributed to structural bond-supply pressure and a Druckenmiller-reported bearish-bonds, structurally-stagnant (1966–1982 parallel) macro regime | general, TLT-adjacent | none precise | years | savings (the raw rate level is expressible; "structural stagnation" is not) |
| Physical infrastructure as AI's binding constraint | Power generation, cooling and compute density named as the real capacity limit, favoring industrial/power names over fabless chip designers | industrial/power names (not top-20) | none stated | years | roth (rotation momentum testable; the "binding constraint" causal story is not) |

Quote: "돈은 찍어낼 수 있지만 석유는 찍어낼 수 없다." — "Money can be printed, oil cannot." (Creator B, reporting Zoltan Pozsar's framework, not his own claim)

---

## 4. Testability triage

Checked directly against `backend/app/rules/grammar.py` and `backend/app/rules/nodes.py`. The grammar
exposes indicators `sma, ema, rsi, bb, atr, macd, swing, vwap, rsi_at_swing, macd_at_swing`, the price
fields `open/high/low/close/volume`, boolean `and/or/not`, comparisons, `crosses_above`/
`crosses_below`, arithmetic (`+ - * /`), and a numeric `rank_by` — the engine's one cross-symbol
operator (`StrategyCard.rank_by`). `MacroField` is confirmed closed at exactly seven members in
`nodes.py`: `DGS10 T10Y2Y T10YIE DCOILWTICO PCEPI PCEPILFE CPILFESL`.

**One nuance the enum's own docstring states and this triage inherits:** an indicator (`sma`, `ema`,
…) cannot be wrapped around a `MacroRef` — the docstring names `sma(macro(CPILFESL), 12)` as the thing
a year-over-year or trailing-mean transform of a macro series would need, and says plainly "this
change deliberately does not build" that wiring. A macro series can appear as a bare current-level
leaf inside an `Arith`/`Comparison` (`macro(DGS10) - macro(T10YIE) > 1.5` is valid today — two
`MacroRef`s combined arithmetically, no indicator involved) but a macro series **cannot** be smoothed,
lagged, or turned into a rate-of-change *by a card*. Rounds 31/32's CPI year-over-year and
60-month-trailing-mean work was done by bespoke non-card tooling outside the engine for exactly this
reason (round 32's own text: "no card, no engine, no backtest, nothing promotable").

### (a) Expressible today as a daily-bar rule in the DSL
- Creator E: Double-B (two Bollinger Bands) entry system — `bb(20,2)` and `bb(4,2)`, or another
  pair of periods.
- Creator E: multi-timeframe / regime confirmation — already the shape of round 17/18's regime
  filter (`close > sma(200)`).
- Creator C: 20-week (~100-session) moving-average trend/break rule — `close crosses_below
  sma(100)`.
- Creator C: Bollinger-band convergence as a downside target — `bb_lower(30,2)` comparisons.
- Creator B / Creator A: price-extension-after-a-run-up as a proxy for "trim after exceptional gains" —
  `rsi(14)` or distance from `sma(N)`, though this only proxies the valuation judgement, it does not
  test it.
- Creator A / creator-b: AI-infrastructure sector rotation as price momentum — `rank_by` across a named
  universe, though this only proxies the supply-constraint story, it does not test it.

### (b) Needs a macro series the store actually has (the closed seven-field enum)
- Creator B / Creator D: long-term-rate level as a driver of semiconductor/equity weakness —
  `macro(DGS10)`, already tested individually in round 30 (null, see §5).
- Creator B: **real yield, nominal minus breakeven inflation, as a savings-book tilt —
  `macro(DGS10) - macro(T10YIE)`, a raw-level `Arith` of two enum members, no indicator wrapping
  needed.** Verified against round 30's own field: round 30 tested `DGS10`, `DCOILWTICO`, and
  `T10YIE` **individually**, never this combination — so this specific construction has genuinely not
  been run by any round, even though both of its inputs have each been tested alone and found null.
  This is the basis for Round 38 (§6).

### (c) Needs data this repository does not hold — the important bucket
Every claim below repeats across at least two personas and none of them is testable here, for the
reason stated:

- **13F/institutional filings** (Creator A's Buffett-rotation and Druckenmiller-exit claims, creator-b's
  13F-as-discovery-tool claim, Creator D's coverage of the same). Needs quarterly 13F holdings data;
  `00-EVERYTHING-TESTED.md` §2 already names 13F as the one external-data class this programme has
  ever touched, and only through manual universe selection, never a guarded statistical engine.
- **Fundamentals — P/E, P/B, and other multiples** (creator-b's relative-valuation methodology). Needs
  per-company financial statement data; the store carries OHLCV bars only.
- **FX rates, including KRW/USD and a dollar index** (Creator D's won-strength/export-competitiveness
  claim, Creator C's DXY-breakdown/EM-rally claim, creator-b's coverage of the Treasury's euro-for-yen
  intervention). Needs currency pair data; not in the store and not in `MacroField`.
- **Physical-commodity demand** (Creator A's 20x-gold/15x-silver physical demand surge). Needs
  physical demand/flow data, distinct from the price series the store already holds for gold-adjacent
  tickers.
- **Geopolitical/electoral calendars and discretionary policy events** (Creator D's Fed-surprise
  reaction claim, creator-b's tariff/trade-war and pension-shortfall claims). Needs an event calendar; the
  DSL has no scheduled-event primitive, only continuous price and macro-level fields.
- **Named-forecaster track record and discretionary point targets** (Creator A's Tom Lee coverage).
  Not a mechanism at all — a specific person's proprietary call, with no stated rule to encode.
- **Chart-pattern recognition** — Fibonacci retracement ratios, head-and-shoulders, cup-and-handle,
  multi-touch counting (Creator C's four pattern-based claims). The grammar has swing-high/low and
  Bollinger/moving-average primitives but no retracement, pattern-template, or touch-counting
  construct.
- **Intraday session-time filters** (Creator E's "first two hours of a session open" rule, embedded
  in several of his notes though not elevated to a top-5 claim above). The engine evaluates daily
  bars; there is no intraday session clock in the grammar at all.

---

## 5. Already answered by the programme

Read directly from each named document before writing this row, per the brief's instruction, not
copied from the digest.

| corpus claim | already-run round(s) | verdict, quoted |
|---|---|---|
| MA-trend / moving-average filters (Creator C's 20-week rule, Creator E's multi-timeframe confirmation) | Round 17 (8-form factorial), Round 18 (16-cell exit discrimination), the seated `C-trend` card | Round 17: "every marginal inside the [21.2pp] floor" (`00-EVERYTHING-TESTED.md`). Round 18: exit marginal **3.58pp**, inside the floor (same source). Bracket policy (`none`/`stop`/`stop-tp`) marginal **0.14pp** (`ROUND-18-PLAN.md` §1, reproducing `ROUND-17-PLAN.md`'s finding). **Flagged discrepancy, not adjudicated here:** round 17's own form marginal is quoted as **7.56pp** in `ROUND-18-PLAN.md` §4 and as a "**9.47pp** slice" in `DISJOINT-SECTOR-FAMILY.md` §5a — the two documents do not agree on this number and this register does not pick a winner between them; a manager should reconcile it. |
| Exit / stop-target policy | Round 18 | Exit marginal **3.58pp**, bracket marginal **0.14pp** — both inside the 21.2pp floor (`00-EVERYTHING-TESTED.md`, `ROUND-18-PLAN.md`) |
| Sector / industry rotation | Round 34 | Form marginal **4.21pp**, regime-filter marginal **0.88pp**, both null; "the field is *tighter* than round 17's [form marginal]" (`DISJOINT-SECTOR-FAMILY.md` §5a) |
| Country / EM rotation (Creator C's dollar-weakness/EM-rally claim, insofar as it is a rotation-form question rather than an FX question) | Round 35 | Best rotation cell minus passive control **+0.08pp**; "every rotation cell negative vs SPY; control −2.28pp is the asset-class/FX gap" (`DISJOINT-SECTOR-FAMILY.md` §5a) |
| Relative-strength / slot ordering (`rank_by`) | Round 36 | Strong-minus-weak **+1.22pp / +1.01pp** (k2/k4); measured ordering noise on this universe **0.13–0.26pp** (`DISJOINT-SECTOR-FAMILY.md` §5a) |
| Rate / curve / inflation macro gates (Creator D's and creator-b's rate-level claims, at the level of "does the rate level alone predict forward returns") | Rounds 21–25, 30–32 | Rounds 21–25 close the yield-curve line as gate, sizing term and rate-of-change, "0 — inside the null in 3 of 3" repeated across rounds 22/23/25 (`00-EVERYTHING-TESTED.md`). Round 30 (level/roc on `DGS10`, `DCOILWTICO`, `T10YIE` individually): "0 — none survives BH". Round 31 (monthly inflation indices): "0 — none clears BH (min q=0.139)", but a genuine near-miss on core CPI level. Round 32 (the near-miss's dedicated OOS test): "0 — passes the rule by the letter, but collapses to p=0.51 out-of-sample; no card" (all quotes `00-EVERYTHING-TESTED.md`). **This closes the rate-level and inflation-level lines specifically — it does not close the real-yield *spread* construction (§4(b)), which none of these rounds tested.** |
| DCA / savings allocation (Creator C's, creator-b's and Creator A's defensive-rotation and diversification themes, generically) | `SAVINGS-FAMILY.md` | Best candidate "Variant 2, Diversified Multi-Asset Core" (SPY/SCHD/AGG/GLD), best MAR in every window at both contribution rates tested (0.21 DIVERSIFIED-FULL, 0.38–0.39 DIVERSIFIED-PRIMARY); "beats the 60/40 benchmark on every headline number... and the entire reason is that it holds more equity" is stated of the *simpler* Variant 1, not Variant 2. **Caveat that must travel with this row:** `SAVINGS-FAMILY.md` scores a **monthly-contribution-funded** account ($1,000 or $500/month plus a $20,000 seed). `backend/app/tournament/purposes.py`'s live `PurposeSpec` for `SAVINGS` moved to **lump-sum funding, $100,000 seed, 10–20 year horizon** on 2026-08-29 — checked directly in the source, not assumed. The document's *finding* (a fixed diversified blend structurally cuts drawdown without a rule) is still evidence against re-testing that question; its exact MAR figures describe a funding shape the current mandate no longer uses. |
| Roth momentum / vol-targeting (Creator B's and Creator D's rate/regime themes, insofar as they are trend-following claims rather than data-unavailable macro claims) | `ROTH-MOMENTUM.md`, `ROTH-VOLTARGET.md` | Momentum: "The moving-average regime switch... is decisively the best performer in the window this report's own brief says matters most: `gfc-2006-2011`", MAR **0.48**. Vol-target: "Best candidate: vol-target 12%, lookback 20 sessions... its worst-case number (0.34) is the best worst-case in the entire table." **Same funding-shape caveat as above** — both documents score annual-contribution-funded Roth accounts; the live `ROTH` `PurposeSpec` also moved to lump-sum, $30,000, on 2026-08-29. |
| Buy-the-dip / drawdown-trigger ladders (adjacent to, not identical to, Creator C's repeated-touch-level and Creator A's precious-metals-as-hedge claims) | `DRAWDOWN-LADDER.md`, `ROTH-DISJOINT-LADDER.md` | As specified, the ladder "reaches a −72.7% drawdown through 2008 — worse than buy-and-hold". With a reserve sleeve: "MAR 0.06 → 0.25, drawdown −72.7% → −55.0%" (`DRAWDOWN-LADDER.md`). Re-expressed on Roth-disjoint tickers: "**−1.10 percentage points deeper**" drawdown, "MAR **−0.09**" versus the taxable original (`ROTH-DISJOINT-LADDER.md`) |

---

## 6. What earned a round, and what did not

Three rounds were designed 2026-09-09 from this corpus by concurrent workers. This register does not
depend on their plan files existing and does not restate their cell counts, universes, thresholds, or
predictions — see each round's own `ROUND-3N-PLAN.md` for the pre-registration.

**Round 37 — a confirmation conjunct on the taxable trading book.** Claim: Creator E's Double-B
(two-Bollinger-Band) entry combined with RSI divergence used strictly as a *confirming* condition
rather than a standalone signal. Not already answered — round 17/18 tested single-band and
single-indicator forms and their regime filter, never a two-Bollinger-Band stack, and no round in
this programme has tested divergence-as-confirmation specifically (bucket (a) in §4). It sits on the
`trading` book, the only one of the three whose ≤9-month horizon (`PurposeSpec.horizon_months_max=9`,
checked directly) matches the horizon this claim was actually made at. See `ROUND-37-PLAN.md` for the
pre-registration, predictions and decision rule.

**Round 38 — real yield as a tilt on the savings book.** Claim: creator-b's and Creator D's rate theses,
specifically the real-yield construction `macro(DGS10) - macro(T10YIE)` rather than either series'
raw level. Not already answered — §4(b) and §5 verify directly that round 30 tested `DGS10` and
`T10YIE` each alone, never combined, and rounds 21–25/31/32 test the yield curve and CPI-based
inflation, neither of which is this spread. It is the programme's first macro-conditioned `savings`
round: `SAVINGS-FAMILY.md`'s own four variants carry no macro gate of any kind. See
`ROUND-38-PLAN.md` for the pre-registration, predictions and decision rule.

**Round 39 — a style/factor tilt on the Roth book.** Claim: creator-b's relative-valuation methodology and
his coverage of Druckenmiller's structural-stagnation thesis (the 1966–1982 parallel), re-expressed as
a factor tilt rather than the un-testable fundamentals/valuation claim itself. Not already answered —
this programme's Roth work (`ROTH-MOMENTUM.md`, `ROTH-VOLTARGET.md`) tests trend and volatility
signals, never a value/quality style tilt, and `symbols_must_be_disjoint=True` on the `ROTH`
`PurposeSpec` (checked directly) means it must clear the same disjointness gate the round-34/35/36
family used. See `ROUND-39-PLAN.md` for the pre-registration, predictions and decision rule.

**What did not earn a round, and why:**

- Creator E's fixed 1%-risk-per-trade and multi-timeframe-agreement claims — the first is
  account-level money management, not a market-timing rule the engine scores; the second is the same
  shape as round 17/18's already-null regime filter.
- Creator D's Fed-surprise, won-strength, and pension-shortfall claims — all bucket (c) in §4 (event
  calendar, FX, and institutional-funding data respectively), none buildable on this store.
- Creator A's Tom-Lee-forecast, Buffett-13F, precious-metals-demand, and Druckenmiller-exit claims —
  all bucket (c) (discretionary forecaster call, 13F, physical demand data, 13F again).
- Creator C's Fibonacci-ratio, repeated-touch-count, dollar-weakness/EM, and chart-pattern claims —
  all bucket (c) (no retracement, counting, FX, or pattern-recognition primitive exists in the
  grammar); only his 20-week-MA and Bollinger-convergence claims are bucket (a), and both are already
  answered by rounds 17/18/34 (§5) rather than novel.
- Creator B's relative-valuation-multiples and 13F-as-discovery-tool claims on their own — bucket (c)
  (fundamentals, 13F); the valuation *theme* survives into Round 39 only as a re-expressed factor
  tilt, not as the literal P/E-comparison rule stated in the note.

---

## 7. Honest limits of this exercise

**Selection.** Five channels one person chose to follow. Nothing about their prominence, track record,
or representativeness of "influencer opinion" generally was measured; they are simply the five
channels ingested.

**Hindsight — the sharpest caveat, and sharper than expected.** §2 already states it: **every one of
the 162 notes has `published = null`.** A card's `designed_through` field is meant to bound what a
rule's author could have known when the rule was written; nothing in this corpus carries an equivalent
bound at all. A note ingested this week about the 2008 financial crisis, a 2024 Fed decision, or a
2025 tariff announcement is indistinguishable, on this data alone, from a note made contemporaneously
with the event it describes — there is no publication timestamp to check either way, only the crawl
date. A round built from a claim in this corpus is not out-of-sample for whatever historical episode
that claim references, and this document cannot certify otherwise for a single one of the 162 notes.

**Translation.** Four of five personas publish in Korean, and every note here is a model-produced
summary of a transcript, not the transcript itself. Nuance, hedging, and qualification a fluent
listener would catch are compressed by that pipeline; the claims in §3 are read off the summaries and
quotes the vault already produced, not re-derived from raw audio.

**Survivorship.** An influencer with an active public channel in 2026 is, by construction, one whose
public calls did not end the channel. Nothing in this corpus can see the calls, or the channels, that
did not survive to be followed.

**The standing programme result.** 36 rounds, no durable edge found on price-only OHLCV data, is the
prior every hypothesis in this corpus starts from — not the persona's own confidence, however
frequently or emphatically a claim recurs across their notes. §6's three rounds earned a test because
each survives an argument against that record stated in this document; every claim in §5 and the
un-promoted list at the end of §6 did not.

---

## Sources consulted

`strategy-program/DISJOINT-SECTOR-FAMILY.md`, `strategy-program/ROUND-32-PLAN.md`,
`strategy-program/ROUND-17-PLAN.md`, `strategy-program/ROUND-18-PLAN.md`,
`strategy-program/ROUND-30-PLAN.md`, `strategy-program/SAVINGS-FAMILY.md`,
`strategy-program/ROTH-MOMENTUM.md`, `strategy-program/ROTH-VOLTARGET.md` (verdict section only),
`strategy-program/DRAWDOWN-LADDER.md`, `strategy-program/ROTH-DISJOINT-LADDER.md`,
`docs/research/programme/00-EVERYTHING-TESTED.md`, `docs/INFLUENCER-CONTRACT.md`,
`backend/app/rules/nodes.py`, `backend/app/rules/grammar.py`, `backend/app/tournament/purposes.py`,
`backend/app/personas/service.py`, `backend/app/personas/models.py`, and the live persona vault via
`app.personas.service.list_personas`/`list_notes`.

---

## 8. Addendum, 2026-09-09 (later the same day) — the discussion rounds

Rounds 38-40 ran and returned the null (`PROTOCOL.md` §9). Rather than re-read the same 162 notes, the
five personas were then asked directly, in character, through the app's grounded chat what they would
test next on each book — `strategy-program/PERSONA-DISCUSSION-2026-09-09.md` holds the verbatim
questions, answers, citations and triage. Two personas offered a daily-bar rule (Creator E: wick
rejection at prior support; Creator C: 0.25-range breakout confirmation), three declined to invent
thresholds and offered themes (bond-market stress; power/defense/semiconductor baskets; trim the
winners). Rounds **42** (trading), **43** (savings) and **44** (roth) were pre-registered from that and
run the same day: all three null, every margin inside the floor, nothing promoted — see each round's
`REPORT.md` under `data/rounds/`. The hindsight caveat in §7 bit exactly as written: round 43's only
point of drawdown effect sits in the 2022 windows the plan pre-declared in-sample, and round 44's
semiconductor basket posts +152.6pp in the one 2025-26 window against +0.4pp on the six pre-2023
windows. Across rounds 37-44 the corpus has now supplied eight rounds of hypotheses and zero findings;
the standing programme result in §7 is unchanged.
