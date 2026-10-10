# The disjoint sector family — sector rotation off the taxable book

Hub document for rounds 34, 35 and 36. **Not investment advice.** Simulated results on stored price
history. I am not a licensed financial adviser and none of this is a recommendation about real
capital.

Gate: `strategy-program/tools/disjoint_field.py`. See its module docstring for the three checks it
runs and §6 below for how to run it as part of a round.

---

## 1. What this family is

The owner asked for more strategies "like round sector" that do not intersect the taxable research.
The programme's sector work so far is round 17/18 (eight rule forms tested on the nine sector SPDRs
— `XLB XLE XLF XLI XLK XLP XLU XLV XLY` — every marginal inside the 21.2pp ordering-noise floor,
`strategy-program/ROUND-17-PLAN.md`, `ROUND-18-PLAN.md`) and the `c20-rotation` candidate card. Every
one of those tickers is claimed by a `savings`- or `trading`-purpose card already on the taxable
shelf (see §3). None of it can be re-expressed as a Roth card without colliding.

This family moves the same sector-rotation questions — does a rule form beat the alternative, does
rotating by rank beat holding the basket, does the ordering-noise floor swallow the result again — onto
tickers no taxable card touches, authored as `purpose = roth` cards so
`app.tournament.purposes.find_disjointness_violations` actually binds on them. It is not a new research
question; it is the same questions, re-run on a universe the Roth book is legally allowed to hold.

## 2. The constraint, precisely

Every card in this family must be:

* ticker-disjoint from every `savings`- or `trading`-purpose card in `backend/app/paper/library` (all
  four tiers — `base`, `variants`, `candidates`, `retired`), checked by
  `strategy-program/tools/disjoint_field.py`;
* aware that ticker disjointness is **necessary, not sufficient** for tax safety — IRC §1091 turns on
  securities being *substantially identical*, not on ticker symbols matching, and Rev. Rul. 2008-5
  makes the stakes of getting this wrong inside an IRA higher than an ordinary wash sale: a
  replacement purchased inside the IRA within the 61-day window does not defer the disallowed loss
  into a later basis, it destroys it with no basis adjustment anywhere. See
  `backend/app/tax/washsale.py`'s module docstring and `strategy-program/ROTH-DISJOINT-LADDER.md` §2
  for the fuller argument; neither this document nor the gate tool settles that question, both only
  check the mechanical, cheap thing;
* read-only against the bar store. A card in this family reads `backend/app/paper/library`'s Parquet/
  DuckDB history through the ordinary tournament runner and nothing else — it never reads
  `data/accounts.toml`, `data/sectors.toml`, `data/store/ledger.sqlite` or anything in `app.tax`. The
  taxable holdings ledger and this family's cards have no data dependency on each other in either
  direction; the only relationship between them is the disjointness constraint itself.

## 3. The taxable-claimed set as of 2026-09-08

**84 tickers**, verified directly against the library on 2026-09-08 rather than taken on trust: 79 come
from every `savings`- and `trading`-purpose `StrategyCard` across the four tiers
`app.tournament.results.load_library` walks, and the remaining five — `AGG BIL QLD SCHD SGOV` — are
claimed only by the allocation and ladder cards under `backend/app/paper/library/allocation/` and
`backend/app/paper/library/ladder/` (`qld-schd-sgov.json`, `spy-schd-agg-gld-bil-atr-tilt.json`,
`qld-schd-ief.json`), two tiers `load_library` does not scan. `disjoint_field.py` and each round tool
(`round34.py`, `round35.py`, `round36.py`) therefore walk all six tiers themselves, the same way
`app.evolution.promotion._library_cards` does at promotion time, so the automated check sees all 84:

```
AGG BIL GLD QLD SCHD SGOV SPY AMD AMZN APLD AVGO BAC BE C CL COIN CRDO CVX DBC DELL DIA DVY EEM EQIX
EWZ FXI GDX GOOGL IEF INDA INTC IREN IWM JNJ JPM KO KRE LITE LLY LQD META MMM MRK MRVL MSFT MU NBIS
NET NFLX NOW NVDA OKLO ORCL OXY PEP PG PLTR QCOM QQQ RDDT SLB SLV SMH SNDK SNOW SOXX TLT TSLA TSM TXN
USB USO WFC WMT XLB XLE XLF XLI XLK XLP XLU XLV XLY XOM
```

**This list is a snapshot, not a constant.** The library changes under active rounds in this
programme, in both directions — a candidate is promoted or retired, an evolution genome is seated.
`disjoint_field.py` never reads this list; it recomputes the taxable set from
`app.tournament.results.load_library()` on every invocation, so a card that clears the gate today is
checked against whatever the library actually holds when the gate next runs, not against this
paragraph.

**Existing Roth tickers** (already `purpose = roth`, and so already disjoint by construction — every
one of them is a name this family's new cards must also avoid re-claiming from a different taxable
card, though none of them collides today): `AAPL ADBE AMAT CRM CSCO IGV INTU KLAC LRCX VUG SSO VIG
BND`.

## 4. The disjoint, GFC-eligible ETF pool

Measured directly from the bar store on 2026-09-08 (`strategy-program/tools/windows.py`'s
`symbol_first_bar`) — first stored daily bar per symbol, checked against the `gfc` window's start
(2007-10-09, `strategy-program/tools/windows.py`'s `WINDOWS["gfc"]`) so the pool below is genuinely
eligible for the deepest bear regime in the round-2/3 matrix, not merely disjoint.

**Industries** — `XHB` 2006-02-06, `XSD` 2006-02-06, `XBI` 2006-02-06, `ITA` 2006-05-05, `XME`
2006-06-22, `XRT` 2006-06-22, `XOP` 2006-06-22, `VNQ` 2004-09-29, `IBB` 2001-02-12.

**Countries** — `EWJ` 1996-03-18, `EWG` 1996-03-18, `EWU` 1996-03-18, `EWC` 1996-03-18, `EWY`
2000-05-12, `EFA` 2001-08-27, `ILF` 2001-10-26, `VWO` 2005-03-10.

**Factor / broad** — `RSP` 2003-05-01, `MDY` 1995-05-04, `VTI` 2001-06-15, `VTV` 2004-01-30, `SPYG`
2000-10-02.

**Fixed income / real assets** — `SHY` 2002-07-30, `TIP` 2003-12-05, `IAU` 2005-01-28. **`IAU` is
physical gold, the same underlying as taxable `GLD` — the textbook substantially-identical pair — and
is EXCLUDED from this pool** despite being ticker-disjoint and GFC-eligible: ticker disjointness does
not reach a case this obvious, and a family whose whole premise is avoiding §1091 exposure should not
open with its cleanest example of it.

**Too young for the `gfc` window** (first bar after 2006-10, so excluded from this pool even though
several are disjoint and would be fine for a shorter window): `VEA`, `HYG`, `MUB`, `DBA`, `GDXJ`,
`TAN`, `ICLN`, `URA`, `COPX`, `REMX`, `KWEB`, `JETS`, `XLRE`, `XLC`, `VOO`,
`MTUM`/`QUAL`/`VLUE`/`USMV`/`SPLV`, `JEPI`/`JEPQ`, `ARKK`.

## 5. The three rounds

All three designed 2026-09-08 and **run 2026-09-09** (results in §5a below, verdicts in each round's
`REPORT.md`). The frozen fields are 16 cards (round 34), 9 (round 35) and 10 (round 36) — 35 cards,
every one `purpose = roth`, zero taxable hits and 8/8 main windows eligible under `disjoint_field.py`.
Each round's predictions and decision rule are pre-registered in its own plan file, which is the place
that question gets answered.
Rounds 34 and 36 share a universe, not a book: 34 sizes 4 slots × 0.20, 36 equalises a 50% ceiling
across 2 × 0.25 and 4 × 0.125 arms, so their comparisons are within-round only.

**Round 34 — industry rotation.** One level below the sector on `XME XRT XHB XSD XOP XBI ITA VNQ`:
does round 17's "form doesn't matter, every marginal drowns in the 21.2pp ordering-noise floor" null
replicate out-of-sample on a higher-dispersion, disjoint universe, or was that null specific to the
nine sector SPDRs' own correlation structure? See `ROUND-34-PLAN.md`, `tools/round34.py`,
`data/rounds/r34-2026-09/` for the pre-registration.

**Round 35 — country rotation.** The same rotation question on `EWJ EWG EWU EWC EWY ILF EFA VWO`,
with the SPY/USD benchmark confound pre-registered up front — a country-ETF rotation strategy's
"excess return" over a USD benchmark is partly a currency bet the rules never intended to make, and
round 35 states how it separates the two before running rather than noticing it after. See
`ROUND-35-PLAN.md`, `tools/round35.py`, `data/rounds/r35-2026-09/`.

**Round 36 — does ranking move the needle.** `StrategyCard.rank_by` is the engine's one cross-symbol
operator — a highest-first ranking key that decides which qualifying names take the scarce slots when
more names satisfy `entry` than `max_positions` allows. Round 36 asks whether setting it moves a
result beyond the 21.2pp ordering-noise floor, on the same industry universe round 34 uses, so the two
rounds' baselines are comparable. See `ROUND-36-PLAN.md`, `tools/round36.py`,
`data/rounds/r36-2026-09/`.

### 5a. Results, 2026-09-09 — three nulls, one directed promotion

All 35 cards ran 8 of 8 main windows with zero `FAILED` lines (280 run files). The instrument check
pre-registered by round 34 — re-running the frozen `r17-ma-crossover-on-stop` — reproduced round 17's
committed figures to the digit before any card in the family ran (`data/rounds/r34-2026-09/repro-r17/`).
Tables: `data/rounds/r3{4,5,6}-2026-09/ANALYSIS.md`, from `tools/round34_36_report.py`.

| round | the pre-registered quantity | measured | floor | verdict |
|---|---|---|---|---|
| 34 | form marginal spread (8 forms) | **4.21pp** | 21.2pp | null; round 17 replicates — and the field is *tighter* than round 17's 9.47pp slice |
| 34 | regime-filter marginal | 0.88pp | 21.2pp | null |
| 35 | best rotation cell minus passive control | **+0.08pp** | 21.2pp | null; every rotation cell negative vs SPY; control −2.28pp is the asset-class/FX gap |
| 36 | strongest-first − weakest-first (`rank_by`) | **+1.22pp / +1.01pp** (k2 / k4) | 21.2pp | null; q 0.40 / 0.52 over all 10 cells |
| 36 | canonical − reversed order (ordering noise on this universe) | **0.13pp / 0.26pp** | — | third datapoint beside round 17's ~1pp and the 21.2pp floor; the floor is not lowered |

Minimum BH q anywhere in the family: 0.40. Positive-median cells: `r34-ma-crossover-on` +1.24pp,
`r34-macd-cross-on` +0.80pp, `r36-volunits-k4` +0.36pp — all inside the floor by more than an order of
magnitude.

**Promotion.** Every plan pre-registered "nothing promoted", and by `PROTOCOL.md` §6 nothing qualifies:
condition (b) forbids a promotion on a margin inside the floor. On 2026-09-09 the owner directed that the
family's best card be promoted regardless. **`r34-ma-crossover-on` is now in
`backend/app/paper/library/candidates/`**, verbatim, `purpose = roth`. `PROTOCOL.md` §9 records it as the
library's second directed promotion beside `C-trend`, and every document in this family says the same
thing about it: it is the owner's decision, not the scorecard's finding. The whole six-tier library was
re-checked with `find_disjointness_violations` after the copy.

**Seated, the same day.** The owner then directed that the card be seated on the paper desk. It is on
the **Roth book** (`app.paperdesk.desk.ROTH_AGENT_IDS`, beside `ladder-sso-vig-bnd`) — the only book
its `purpose` allows, and the first rules-shaped card that book has run. The desk discloses it as a
candidate seated by decision (`_CANDIDATE_AGENT_IDS`), and the forward record starts from the desk's
inception, so nothing it shows is evidence about anything for months.

## 6. How to run a round in this family

The guard first, then the serial runner, then the scorer — in that order, every time:

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/disjoint_field.py --cards data/rounds/r34-2026-09/cards
bash strategy-program/tools/run_round.sh data/rounds/r34-2026-09/cards data/rounds/r34-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py --results data/rounds/r34-2026-09/results --json data/rounds/r34-2026-09/scorecard.json
```

Substitute `r35-2026-09` / `r36-2026-09` for the other two rounds. `disjoint_field.py` exits non-zero
on any failure and is meant to be run again after every edit to a round's `cards/` directory, not just
once before the first submission — a card added, retired or edited mid-round can silently reopen a
collision the first run cleared.

**`run_round.sh`'s own warnings, restated because they bind on this family too.** The bar store is a
single DuckDB file whose default connection takes a write lock; `run_round.sh` is a **single-writer**
script and refuses to start if another `app.tournament` process is already running against the store
(`strategy-program/DEFECTS.md` D3) — never run two rounds, or a round and an ad-hoc backtest,
concurrently. A round takes hours, not minutes; budget for that before starting one.

**Nothing here is promoted by being authored.** `PROTOCOL.md` §6 governs promotion: a card enters
`candidates/` only after clearing the gate (`MIN_ELIGIBLE_MAIN_WINDOWS` main windows) with a positive
median. Writing a card into this family's `cards/` directory and clearing `disjoint_field.py` proves
the card is *eligible to be measured* as a member of this family — it proves nothing about whether the
strategy it describes is any good. That is what rounds 34-36 exist to find out.

## 7. What the family cannot settle

* **Survivorship of a hand-picked ETF roster**, mitigated but not eliminated: every symbol in §4 comes
  from a mechanically defined index family (a sector-industry SPDR, an MSCI/FTSE single-country fund,
  a broad factor ETF) rather than a name chosen after seeing its own return, and every one predates
  the GFC — but the *set of index families that survived to be tradeable ETFs at all* is itself a
  survivorship filter this family does not correct for.
* **Price-only bars.** The same limitation every round in this programme carries: no fundamentals, no
  flows, no options-implied information, just OHLCV.
* **SPY as the benchmark for a Roth book.** `app.tournament.purposes.PURPOSE_SPECS[Purpose.ROTH]`
  names `"spy"` — a judgement call recorded, not backtested, in that module's own docstring — for a
  family whose whole premise is trading names *other than* the ones a broad-market benchmark holds.
  A rotation strategy across country or industry ETFs is being measured against a benchmark it was
  deliberately built to differ from.
* **The ordering-noise floor.** Re-running one identical card under twelve `universe`-orderings moved
  its three-year return across a 53.9-point spread, sigma 21.2 points
  (`strategy-program/PROTOCOL.md` §7). Round 17/18 found every sector-rotation marginal smaller than
  that floor; nothing about moving to a different ticker universe raises the floor itself, and rounds
  34-36 are measured against it explicitly rather than pretending a wider universe makes the noise go
  away.
* **§1091 substantial identity.** Restated one more time because it is the constraint the whole family
  is named after: ticker disjointness is mechanical, cheap, and checked; substantial identity is a
  legal judgement neither this document nor `disjoint_field.py` makes. §4's exclusion of `IAU` against
  taxable `GLD` is the one case in this family clear enough to call outright; nothing rules out a
  subtler pair existing among the rest of the pool.
