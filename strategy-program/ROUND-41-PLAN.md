# Round 41 — confirmation stacking: is an RSI-divergence gate worth anything on top of a mean-reversion entry?

Pre-registered 2026-09-09, before any card in this round has been run. Nothing below was written with
sight of a result. The field is authored by `strategy-program/tools/round41.py` and frozen in
`data/rounds/r41-2026-09/cards/`.

Not investment advice. Price-only bars, no dividends. Nothing in this round will be promoted —
`PROTOCOL.md` §9's r21 amendment removed §6's promotion rule from the `trading` purpose entirely, and
every card here is `purpose = trading`.

> **Numbering note.** This round was briefed and authored as **round 38**. A concurrent session was
> briefed with the same number and authored a macro real-yield allocation round under
> `strategy-program/tools/round38.py`, `strategy-program/ROUND-38-PLAN.md` and
> `data/rounds/r38-2026-09/cards/` (seven `AllocationCard`s, `purpose = savings`). That work is
> untouched; this round moved to the next free number instead — 37, 39 and 40 were already claimed by
> other concurrent work. The move also avoids an `agent_id` collision that would otherwise have put
> two different `r38-control` cards in one scorecard namespace. **The number is the only thing that
> changed.** Every design decision below was fixed before the collision was discovered, and the
> manager should renumber whichever of the two rounds they prefer rather than treat 41 as meaningful.

---

## 1. Where the hypothesis comes from

This programme ingests investing YouTubers into persona notes under
`data/vault/influencers/<slug>/notes/*.md` (loader: `app.personas.service.list_personas` /
`list_notes`). Two personas make the same structural claim, independently, and neither is arguing for
a particular indicator — both are arguing about **how many conditions have to agree**.

**`creator-e` ("Creator E").** Note `3pLtQ_82nSM` (Korean, ingested 2026-09-08, untitled) is
a list of six mistakes that keep traders from their first $100,000, and the first one is RSI
divergence used alone. Its theme line names the failure directly — indicators "commonly misused by
traders relying on single signals without confirmation" — and its summary specifies the fix:
confirming divergence "with support/resistance and candle patterns rather than relying on divergence
alone". The quotes are blunt about it:

> "Divergence. Showing up does not mean a trend reversal is guaranteed."
> — `creator-e`, note `3pLtQ_82nSM`

> "don't trust one ma treat the overlapping MAs as support and resistance"
> — same note

Note `AUq4h-VPi-k` ("I Tested TradingView's Top 5 Indicators (The Real #1 Will Surprise You)", English)
grades five popular indicators and lists as a theme "Filtering out false signals using time frames,
market sessions, and divergence" — divergence again in the role of a filter, never a trigger. Its
opening claim is the same idea in one line:

> "Even a famous indicator needs its own method to turn signals into real profit."
> — `creator-e`, note `AUq4h-VPi-k`

**`creator-c`.** A Korean chart technician who stacks conditions before entering. Note
`U-I4NfBUJzo` ("How to Read Moving Averages: You Only Need to Know These 2 Things") is an entire
tutorial on moving-average alignment (정배열 / 역배열) whose central teaching, in its own summary, is
that MA structure "must always be combined with fundamental analysis and news events":

> "펀더멘탈이랑 이평선, 차트 이런 걸 같이 봐야 돼" — "you have to look at the fundamentals, the moving
> average and the chart together." — `creator-c`, note `U-I4NfBUJzo`

Note `cy8Zq8eDgYA` ("NASDAQ Full Buy Conditions") lists as a theme "Technical entry discipline: uses
chart support/resistance, Fibonacci extensions, and 20/27-day moving averages to define base cases …
waits for macro confirmation before adding exposure" — four conditions before a buy. Note
`a36554erw7o` shows the same shape on a single name: a 20-week MA held on a closing basis for 70 days,
**plus** a reverse head-and-shoulders setup, **plus** a 3% stop against a 6% target, before an entry
is considered.

**Why this is a hypothesis this programme has not tested.** Rounds 17, 18 and 34 tested *form*
exhaustively — eight entry forms, eight exit forms, a 200-day regime filter, three bracket policies,
across two disjoint universes — and every marginal landed inside the 21.2pp noise floor (round 17
form 7.56pp, brackets 0.14pp; round 34 form 4.21pp). Every one of those cells varied **which single
rule fires**. Not one of them tested **whether requiring two independent conditions to agree changes
anything**, which is precisely and only what both personas are claiming. That is the gap this round
fills.

---

## 2. The field — one factor, six cells

**One factor varies: the confirmation gate.** Every other field is
`backend/app/paper/library/candidates/c18-meanrev.json`'s, character for character.

| agent_id | gate ANDed onto c18's entry | free numbers |
|---|---|---|
| `r41-control` | *(none)* | 8 |
| `r41-struct-lb10` | `low < swing_low(10)` | 9 |
| `r41-mom-lb10` | `rsi(14) > rsi_at_swing_low(14, 10)` | 10 |
| `r41-div-lb5` | `low < swing_low(5) and rsi(14) > rsi_at_swing_low(14, 5)` | 10 |
| `r41-div-lb10` | `low < swing_low(10) and rsi(14) > rsi_at_swing_low(14, 10)` | 10 |
| `r41-div-lb20` | `low < swing_low(20) and rsi(14) > rsi_at_swing_low(14, 20)` | 10 |

**Held identical across all six:** entry base `rsi(2) < 10 and close > sma(200)`, exit
`close > sma(5)`, `stop_loss_pct` 0.08, `take_profit_pct` null, `max_hold_days` 10, `max_positions` 6,
`position_pct` 0.15, `rank_by` unset, `designed_through` 2026-02-13, `purpose = trading`, and the
universe `JNJ MRK PG KO PEP CL XOM CVX MMM WMT` **in c18's own write order**.

### 2a. The base is c18's, and it is *proved* to be c18's

`round41.py::check_base_matches_c18` reads the live `c18-meanrev.json` at build time and compares
entry, exit, both brackets, hold cap, slot count, position size, universe **including order**,
`rank_by` and `purpose`. Any difference refuses `--write`. Hardcoding alone would let the two drift
silently; reading alone would hide what the round runs behind a file read. Both, so that the control
cell is a restatement of c18 that cannot quietly stop being one.

The order matters as much as the membership. `rank_by` is unset on c18 and on every card here, so the
`universe` write order is the slot tie-break, and `PROTOCOL.md` §7 prices that accident at a 53.9-point
spread, σ = 21.2 points. Re-alphabetising the universe would make the control a different card from
the one it is meant to reproduce.

### 2b. The divergence primitive, and the identifier that selects it

`app.indicators.swing` is the only place in this DSL that can ask "how does now compare to the last
time price turned". A swing low is a *local* minimum over `2·lookback + 1` bars centred on it, so it
cannot be recognised until `lookback` bars have formed on its right — and the module publishes it at
`j + lookback`, the first bar a live observer could have known it. That lag is the entire causality
argument, and `app.backtest.guards` verifies it by truncation.

`app.rules.grammar._resolve_indicator_ident` resolves an identifier whole first, then peels a suffix
off the **last** underscore if no indicator is registered under the whole name. So:

- `swing_low(10)` → `IndicatorRef(name="swing", output="low")` — the price at the last confirmed swing low.
- `rsi_at_swing_low(14, 10)` → `IndicatorRef(name="rsi_at_swing", output="low")` — RSI *read at the bar
  price turned*, not at RSI's own extremum. That anchoring to the **price** pivot is what makes the two
  halves of a divergence refer to the same instant.

A bullish divergence is therefore `low < swing_low(n) and rsi(14) > rsi_at_swing_low(14, n)`: price
prints a lower low than the last confirmed swing low, while RSI reads higher than it did at that swing.
Verified by `grammar.parse` and by `guards.check` against **real stored bars** — see §6.

### 2c. Why three lookbacks, and why no slot-cap factor

**Three divergence lookbacks — 5, 10, 20.** 10 is the headline arm, fixed before any measurement; 5 is
`app.indicators.swing`'s own registry default; 20 flanks it on the other side. `PROTOCOL.md` §3 rule 4
forbids grid search and requires sensitivity that demonstrates *insensitivity*: three pre-registered
levels of one parameter, all reported, is that and not a search. It also forecloses the one interesting
objection to a sparse or null result — "you picked a bad lookback" — because the answer holds at all
three.

**The two halves are the literal conjuncts of `divergence(10)`**, derived in code from the same
helpers, not two rules that merely resemble them. The personas' claim is specifically that the
*conjunction* is worth something the parts are not, so the decomposition has to be exact.

**No slot-cap factor, and that is a measured decision rather than a shrug.** Round 36 crossed its arms
with two slot caps. Here the gate arms cut simultaneous qualifiers to about 1% of the control's
(§5's table), so `max_positions = 6` over ten names cannot bind in them; a second cap arm would spend
runtime on a factor already known to be inert in half the field. The cost is stated rather than
hidden: **this round says nothing about how a confirmation gate interacts with a harder-binding cap.**

### 2d. The parameter budget

`PROTOCOL.md` §3 rule 3 budgets ten free numbers per card. The eight base numbers are c18's, frozen in
that card before this round was conceived: `rsi` period 2, threshold 10, `sma` period 200 (entry),
`sma` period 5 (exit), stop 0.08, hold cap 10, six slots, 15% each. A gate adds at most two: one swing
lookback (one decision even though both conjuncts spell it — they *must* reference the same pivot or
the expression does not mean what it appears to mean) and the RSI period 14. Maximum spend is
therefore exactly 10, at the budget and not over it, counted by `free_number_count` and asserted by
`tests/test_round41_field.py`.

RSI 14 is deliberately **not** c18's `rsi(2)`: a 2-period RSI sampled at a swing pivot is a different
statistic from the one either persona describes, and reusing c18's number would be a coincidence of
spelling rather than a choice.

---

## 3. The binding constraint — no ticker a Roth card holds

Every card here is `purpose = trading`, so the constraint runs the opposite way from rounds 34 and 36:
those authored Roth cards that had to avoid the taxable book; this authors taxable cards that must
avoid the **Roth** book. Same invariant, same function.

`round41.py` recomputes the Roth union from the live library on every run — `load_library()`'s four
tiers **plus** `library/allocation/` and `library/ladder/`, which hold `AllocationCard`s and
`LadderCard`s that `load_library` does not walk — and then runs
`app.tournament.purposes.find_disjointness_violations` over the library and this round's cards
together. Any violation naming an `r41-` card, or any intersection between this universe and the Roth
union, refuses `--write`.

Measured at freeze time: 62 purposed cards, 21 tickers held by Roth cards
(`AAPL ADBE AMAT BND CRM CSCO IGV INTU ITA KLAC LRCX SSO VIG VNQ VUG XBI XHB XME XOP XRT XSD`),
intersection with this round's universe **none**, violations naming an `r41-` card **0**.

Why it matters: Rev. Rul. 2008-5 holds that a loss realised in a taxable account and replaced inside an
IRA within 30 days is disallowed **outright**, with no basis adjustment anywhere — strictly worse than
an ordinary wash sale, which only defers. `backend/app/tax/washsale.py` models what that prevents.

**Ticker disjointness is necessary, not sufficient.** IRC §1091's substantially-identical test is about
the securities, not the symbols, and nothing here is a legal opinion. What the check buys is that the
one mechanical thing that is cheap to verify did not fire.

---

## 4. Windows and metric

The eight-window matrix in `WINDOWS.md`, unchanged: `q4-2018`, `covid`, `bear-2022`, `chop-2015`,
`chop-2011`, `bull-2024`, `recent`, `gfc`. Ranked on `median_adjusted_excess` across eligible main
windows, per `PROTOCOL.md` §4, with worst window, hit rate, IQR, exposure, drawdown, trade count and
realised P&L reported beside it.

All ten universe names have first stored daily bars before 1990, so the 200-day warmup plus the 40
post-warmup causality bars clear every window including `gfc`. **All six cards are expected eligible
8 of 8** — verified with `strategy-program/tools/windows.py --cards data/rounds/r41-2026-09/cards`
before the field was frozen, not assumed. Round 17's Amendment 1 is the reason that check is run
rather than reasoned about: there, two ETFs with no bars in a window did not merely contribute
nothing, they failed the whole card and the round lost three windows.

---

## 5. The structural finding that shapes this round, measured before it was frozen

`round41.py::signal_density` counts, on the real bars and bounded at the design cutoff, how many bars
each arm's entry is **true** on. This is arithmetic about the rules, not a return. It was run before
the field was frozen and it is the most important thing in this document.

| arm | q4-2018 | covid | bear-2022 | chop-2015 | chop-2011 | bull-2024 | recent\* | gfc | full history |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `control` | 43 | 31 | 121 | 50 | 172 | 125 | 63 | 117 | 8,218 |
| `struct-lb10` | 10 | 6 | 14 | 10 | 34 | 18 | 5 | 19 | 1,341 |
| `mom-lb10` | 16 | 16 | 65 | 34 | 105 | 53 | 32 | 55 | 4,147 |
| `div-lb5` | 2 | **0** | **0** | 1 | 4 | 2 | **0** | **0** | 97 |
| `div-lb10` | **0** | **0** | **0** | **0** | 6 | 1 | **0** | **0** | 76 |
| `div-lb20` | **0** | **0** | **0** | **0** | 4 | 1 | 2 | **0** | 48 |

\* `recent` runs to 2026-08-18; it is counted only to the design cutoff 2026-02-13, so that column
understates the full window. Every other column is complete. Counts are summed over all ten symbols.

**The divergence conjunction fires on about 1% of the bars the control fires on, and on exactly zero
bars in most windows.** A signal bar is not a trade — the slot cap, an already-open lot and the hold
cap all sit between them — but zero signal bars in a window is exactly zero trades in that window.

**Three consequences, all pre-registered here rather than discovered in the report.**

1. **A zero-trade window is not "no data" to the scorer.** `tools/score.py::adjusted_excess` falls
   back to the session-presence exposure when a card takes no trades, where both are zero, so the
   window scores **exactly 0.00** and enters the median like any other figure. A gate that never fires
   can therefore *beat a losing control* by not trading. `score.py` only marks a card unranked when it
   takes zero trades in **every** window run, which `div-lb10` (6 trades in `chop-2011`, 1 in
   `bull-2024`) would not do.
2. **So the round needs a measurability gate before its decision rule**, and §6 states one.
3. **The sparsity is not a lookback artifact.** It holds at 5, 10 and 20, which is exactly what the
   three-level sensitivity in §2c exists to establish.

**Why the conjunction is this rare is mechanical, not mysterious.** c18's base already demands a
2-period RSI below 10 inside an intact 200-day uptrend — roughly a 1-in-17 bar. Requiring, on that same
bar, both a lower low than the last confirmed swing low (16.3% of those bars) *and* RSI(14) above where
it was at that swing (5.7% of those) leaves almost nothing. Stacking two conditions on an entry that is
already an extreme is arithmetically close to stacking two conditions on nothing.

**This does not make the round pointless, and it does change what it can answer.** The two single-condition
gates are measurable — `struct-lb10` fires 5–34 times per window and `mom-lb10` 16–105, never zero in
any window — so the round still measures, on real data and against a reproduced control, whether *a*
confirmation gate changes a mean-reversion result. The divergence arms answer the sharper question and
will most likely answer "cannot fire on this base", which is a real finding about the personas' claim
transplanted to daily bars, stated in advance rather than dressed up afterwards.

---

## 6. The decision rule, pre-registered

**Gate 0 — measurability, and it runs first.** An arm taking **fewer than 20 trades across the eight
windows** is reported as **UNMEASURED**, never as a null and never as a winner, and its median is
printed with that label attached. `PROTOCOL.md` §4 already says a card that beat a benchmark on four
trades has demonstrated less than one that did it on ninety; this is that sentence given a number
before the fact. On §5's counts, all three divergence arms are expected to fail Gate 0.

**The instrument check.** `r41-control` must reproduce `c18-meanrev` **to the digit** in any window
both are run in — same trades, same P&L, same adjusted excess. The engine is deterministic (`PROTOCOL.md`
§8), the two cards differ only in `agent_id`, `display_name`, `thesis` and `falsification`, and none of
those reaches the runner. **This requires the orchestrator to include the library's `c18-meanrev` in
round 41's field**, which costs one card-run per window and is the cheapest regression test available
on the instrument. If the two logs differ, something moved in the engine and no contrast in this round
is interpretable.

**The main rule.** A confirmation gate "carries information" if and only if **all four** hold:

1. `gate − control` on median adjusted excess across the eight windows **exceeds 21.2pp**;
2. the difference has the **same sign in at least 5 of the 8 windows**;
3. the contrast survives **Benjamini–Hochberg over all six cells run** (`PROTOCOL.md` §3 rule 8: the
   denominator is every cell in the comparison, never a subgroup);
4. the divergence arm **exceeds both of its own halves** (`struct-lb10` and `mom-lb10`) by more than
   the floor.

Condition 4 is the one that makes this a test of *stacking* rather than of *any extra filter*. A
divergence that beats the control but not its halves has demonstrated that one of its two conjuncts is
doing the work, which is the opposite of the personas' claim.

**Anything less is the null**, and the null here is a strong prior: eighteen-plus rounds of this
programme have found no durable edge, and every entry-form marginal ever measured has landed inside the
21.2pp floor.

**The floor is not lowered.** Round 17's ~1pp ordering replication was measured on a different universe
with a different cap, and `PROTOCOL.md` §7's spread stands. With `rank_by` unset and a 6-of-10 cap that
binds in the control far more often than in the gate arms, the *control* carries more ordering exposure
than the gate arms do — which cuts against reading a small control-versus-gate difference as anything.

---

## 7. Falsifiable predictions

Six, all stated before any card has run, all settleable by someone other than the author from the
round's own trade logs.

1. **Mechanical:** every gate arm takes strictly fewer trades than `r41-control` in every window in
   which the control takes a trade. An AND narrows a condition; if any gate arm out-trades the
   control, the field was not built the way this document says.
2. **Structural, with exact numbers:** `div-lb10` takes **zero trades in exactly 6 of 8 windows**
   (all but `chop-2011` and `bull-2024`); `div-lb20` in **at least 5 of 8**; `div-lb5` in **at least 3
   of 8** (`covid`, `bear-2022`, `gfc`; `recent` is truncated at the cutoff so it is not counted here).
   All three fail Gate 0. Falsified if any divergence arm clears 20 trades across the matrix.
3. **The null:** each gate arm's median adjusted excess differs from the control's by **less than
   21.2pp**. This is the round's central claim and the one most worth being wrong about.
4. **Neither divergence arm beats both of its halves by more than the floor.** Stated separately from
   3 because "differs from the control" and "beats its own components" are different claims and could
   in principle come apart.
5. **Pre-registered failure regime.** Every cell's worst adjusted excess is in **`bear-2022` or
   `gfc`** — the grinding, sustained declines where "oversold" keeps getting more oversold and the
   200-day average has not yet rolled over. That is c18's own pre-registered failure regime, quoted
   from its thesis, and the gates are not supposed to change the mechanism. A cell whose worst window
   is elsewhere is falsified as the mean-reversion rule it claims to be. *(Arms failing Gate 0 are
   exempt: a worst window drawn from one trade is not a regime observation.)*
6. **Coverage:** all six cells are eligible and run in **8 of 8** windows, and `r41-control`
   reproduces `c18-meanrev` to the digit in every one of them.

---

## 8. What this round cannot settle

- **Daily bars against an intraday claim.** Both personas trade and teach on intraday charts;
  `creator-e` grades indicators partly on "market sessions". This round runs daily bars only.
  A divergence gate that is useless on daily bars may be perfectly good on 5-minute ones, and this
  round has no way to see that.
- **Swing-detection lag.** `app.indicators.swing` publishes a pivot `lookback` bars after it forms,
  which is what makes it causal and also what makes it late. A human chartist reading the same chart
  identifies the pivot as it forms and is, in that sense, doing something this engine deliberately
  cannot.
- **Price-only bars.** No dividends, no volume conditions, no candle patterns, no support/resistance
  levels drawn by eye — and "support/resistance structure" is the specific thing `creator-e`
  says divergence must confirm. `swing_low(n)` is a mechanical proxy for it and is not the same object.
- **One base rule.** A gate that adds nothing to a 2-period-RSI extreme might add something to a
  slower entry with more room above it. §5 shows exactly why the sparsity is a property of the
  *conjunction with this base*, not of divergence in general.
- **One slot cap** (§2c), **one universe** of ten defensive large caps, **one purpose** (`trading`,
  taxable, and unpromotable under §9's r21 amendment).
- **`c18-meanrev` has no committed figures on this matrix** — see §10. The reproduction check is
  therefore against a card re-run inside this round, not against a published number.

---

## 9. The honest prior

I expect this round to return the null, and I expect the divergence arms to fail Gate 0 rather than to
return anything at all. That is not modesty; it is what §5's table already says and what eighteen
rounds of this programme's record says. The reason to run it anyway is that "an indicator-combination
gate" is a named, unfilled hole in the record — every previous round varied *which* single rule fires
— and closing it with a measurement is worth more than closing it with an assumption.

The result I would find most interesting is prediction 3 failing on `struct-lb10` or `mom-lb10`: a
*single* extra condition moving the median by more than the floor, on a base whose control reproduces a
committed card. That would be the first entry-side marginal outside the floor this programme has
measured, and it would deserve a dedicated replication round on a disjoint universe before anyone
believed it.

---

## 10. Honesty register

**`c18-meanrev` has never been run on the eight-window main matrix.** The brief for this round assumed
committed 8-window figures existed to reproduce. They do not. Every window `c18-meanrev` has a run file
for is listed below, and none of them is a main-matrix window:

- **Round 4** (six regime windows: `recovery-2009`, `taper-2013`, `oil-2014`, `volmageddon-2018`,
  `inflation-2021`, `banks-2023`): `median_adjusted_excess −3.2367%`, worst −4.4655% (`banks-2023`),
  best −0.0479% (`taper-2013`), hit rate 0.0, 269 trades, mean exposure 19.02%, total realised P&L
  −$221.47. Ranked 14th on median, 6th on worst window.
- **Round 5** (27 horizon windows): `median_adjusted_excess −1.0706%`, worst −23.3571% (`h10y-2`),
  best +4.6610%, hit rate 40.74%, 3,785 trades, mean exposure 13.66%.
- **Rounds 10–12** (live matrices): 8th of 10 in the round-10 selection, failing Gate A in rounds 6 and
  8, and — per `data/rounds/PROGRAMME-REPORT.md` — the only card making money live at 55 sessions,
  +2.44%.
- **`data/rounds/rerun-2026-08/`** holds all eight main windows and c18 run files, but c18 was run only
  in the round-4 and round-5 window sets there, not in the main eight.

So the reproduction check in §6 is **not** "match a published number". It is "run `c18-meanrev`
alongside `r41-control` in this round and require the two logs to be identical", which is a stronger
check on the instrument (it compares full trade logs rather than one summary figure) and a weaker
check on continuity across rounds (it cannot detect an engine change that predates round 41). The
build-time field-identity assertion in §2a covers the other half: the control provably *is* c18's rule.

**The manager must decide one thing:** whether round 41's run field includes the library's
`c18-meanrev`. Without it, prediction 6's second clause is unsettleable and §6's instrument check does
not exist. With it, the field is seven card-runs per window rather than six, and the Benjamini–Hochberg
denominator in §6 condition 3 stays at **six** — `c18-meanrev` is the control's twin, not a seventh
hypothesis, and counting it would inflate the correction with a duplicate.

**Two further disclosures.** The `recent` column in §5 is truncated at the design cutoff and therefore
understates that window. And the gate arms reduce how often the 6-of-10 slot cap binds, so the control
and the gate arms are not equally exposed to the `universe`-order tie-break — the control is exposed
more, which is the direction that makes a gate-versus-control difference *easier* to manufacture from
ordering noise, not harder.

---

## 11. Determinism, scope and the run recipe

`round41.py::build()` is deterministic: `ARMS` is a fixed tuple, nothing reads a clock, a random
source or the filesystem, and two calls produce byte-identical model dumps
(`tests/test_round41_field.py::TestDeterminism`). The tool reads the library JSON (for the base
identity check and the Roth recomputation) and the bar store (for the guard rehearsal and the signal
density), and writes only `data/rounds/r41-2026-09/cards/`. Nothing here reads `data/accounts.toml`,
`data/sectors.toml`, `data/store/ledger.sqlite` or anything under `app.tax`.

```
cd "<repo root>"
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round41.py            # dry run
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round41.py --write    # freeze
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/windows.py --cards data/rounds/r41-2026-09/cards
.venv/Scripts/python.exe -m pytest tests/test_round41_field.py -q
```

Then, per `PROTOCOL.md` §2, the cards are committed **before** any backtest runs and the commit hash is
quoted in the round report. `strategy-program/tools/run_round.sh` runs the field; `score.py` scores it.
