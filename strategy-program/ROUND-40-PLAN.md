# Round 40 — does an added confirmation conjunct pay for itself?

Pre-registered 2026-09-09, before any card in this round has been run. Nothing below was written with
sight of a backtest result. The reachability figures in §3 are firing counts over price-only bars, not
returns; they were measured to range-check the field, not to select it.

Not investment advice. Price-only bars, no dividends. The round has **not** been run.

---

## 1. The question, and whose claim it tests

**Hold one base entry fixed and vary only the confirmation term conjoined to it. Does the extra
conjunct earn back the trades and exposure it costs?**

The hypothesis under test is the influencer persona **creator-e**'s claim that *"a signal is
only valid with a confirmation term."* That persona's corpus is **partly Korean-language and
machine-summarised** — a provenance caveat that belongs in the record: this round gives the claim a
fair, pre-registered test, and it is **not** an endorsement of the persona or the claim.

Rounds 17 and 18 isolated *form* and *exit*; this round isolates the **confirmation conjunct** on the
taxable `trading` book, holding the base entry and the exit identical so a difference can be attributed
to the conjunct alone.

## 2. The field — 1 base entry × 4 confirmation arms × 2 slot caps, 8 cells

Authored by `strategy-program/tools/round40.py`. **Every arm's entry is composed by string
construction** from a single `BASE_ENTRY`: the control is the bare base, and each other arm is
`BASE_ENTRY + " and " + <conjunct>`. The base is written down exactly once; no arm retypes it.
`tests/test_round40_field.py` asserts this by construction.

**Base entry (fixed, all cells):** `close crosses_above bb_mid(20, 2)` — the high-firing base (§3), so
the confirmation arms have room to filter.

**Exit (fixed, all cells):** `close crosses_below bb_mid(20, 2)` — a symmetric `bb_mid` crossback. The
only thing that varies within a slot cap is the entry conjunct.

| arm | conjunct added to the base | kind |
|---|---|---|
| `none` | — (bare base) | control |
| `swing-structure` | `close > swing_high(10)` | treatment |
| `rsi-confirm` | `rsi(14) > rsi_at_swing_high(14, 10)` | treatment |
| `divergence-proxy-negative-control` | `rsi_at_swing_low(14, 10) < rsi(14)` | negative control |

The fourth arm is the brief's "divergence proxy". It is **not a treatment**: the reachability study (§3)
shows it retains ~93% of the base's firing sessions — it barely filters. It is carried as a
**negative control** the round predicts will be indistinguishable from `none`, and it is labelled as
such in its own card thesis and falsification.

**Two slot caps: {3, 6}**, with `position_pct` {0.25, 0.125}. Both commit ≈0.75 of capital, so the cap
varies **breadth of book, not gross exposure** — exposure stays comparable so `adjusted_excess` reads
across the two caps.

**Held identical across all 8 cells:** the universe (below), the exit, `stop_loss_pct = 0.12`, no
take-profit, `max_hold_days = 150`, `rank_by` unset, `purpose = TRADING`, `designed_through =
2026-02-13` (the programme's `DESIGN_THROUGH`), and the eight-window main matrix.

- **`max_hold_days = 150`** is a backstop, well under the `trading` mandate's nine-month / ≈189-session
  ceiling (`app.tournament.purposes`, `horizon_months_max = 9`) with a ~39-session margin. The `bb_mid`
  crossback exit reaches almost every hold first, so 150 caps the tail rather than defining the horizon.
- **`rank_by` is left unset.** Round 36 settled that spending a free number on `rank_by` buys tidiness,
  not return (its relative-strength ordering placed 9th of 10, inside the noise). Leaving it unset keeps
  universe-order fills identical across every cell, so the conjunct (and slot cap) is the only thing that
  moves. This is held identical across all arms, satisfying §7's one-decision rule for the conjunct axis.

### The universe, and its known limitation

`NVDA TSM MU AMD QCOM MSFT GOOGL AMZN NFLX ORCL INTC TXN` — the 12-name `_TAXABLE_GROWTH` pool, taken
**verbatim** from `backend/app/evolution/universe.py`. It is **mechanically defined by the pool, not
chosen for this round**. It is large-cap tech / semiconductors and is therefore **not
survivorship-free** — the honest counterpart to round 34's note that its ETF universe was, by contrast,
mechanically defined. `round40.py` recomputes the live **roth union** (21 tickers) from
`app.evolution.promotion._library_cards` and **refuses to write** if the taxable universe intersects it;
it does not (taxable-to-taxable overlap is legal, roth-to-taxable is not).

### The parameter budget (`PROTOCOL.md` §3 rule 3 — ten free numbers per card)

Counted by `round40.free_numbers`, the same convention as round 35/36 (distinct numeric values across
the expressions, + one per present bracket, + two for slot count and position size), and asserted by the
test. The most expensive cell carries **8**, under the budget of ten:

| arm | entry numbers (distinct) | + brackets (stop, hold) | + slots, pos | total |
|---|---|---|---|---|
| `none` | 20, 2 | 2 | 2 | 6 |
| `swing-structure` | 20, 2, 10 | 2 | 2 | 7 |
| `rsi-confirm` | 20, 2, 14, 10 | 2 | 2 | 8 |
| `divergence-proxy-negative-control` | 20, 2, 14, 10 | 2 | 2 | 8 |

## 3. The reachability gate — this round's central methodological contribution

A parallel round tried `close crosses_above bb_upper(4, 4)`: a 4-period Bollinger band at 4σ. With the
population standard deviation this codebase uses (`backend/app/indicators/volatility.py`, `ddof=0`), the
largest z-score any close can reach inside its own n-bar window is √(n−1); at n=4 that is √3 ≈ **1.7321**,
so a 4σ threshold **can never be crossed**. It fired **0 times over 108,465 symbol-sessions** — and every
pre-flight gate passed it (`windows.py` eligibility, pytest, ruff, a parameter-range check), because
eligibility asks whether an indicator can *warm up*, never whether a rule can ever be *true*.

**So `round40.py --write` measures every distinct entry and the exit against the actual bar store**
(bounded to `DESIGN_THROUGH`) with `app.market.store.read_frame` (an in-memory DuckDB connection — no
file lock, safe alongside other readers) and the real evaluator (`app.rules.grammar.parse` +
`app.rules.evaluate.evaluate`, so a "fire" is a session on which the entry expression is True — the DSL
computation, not a re-derived pandas one). It **refuses to write** if any expression fires 0 times, or if
a **treatment** arm retains **>95%** (a no-op) or **<2%** (a near-off-switch) of the base's firing
sessions. The reachability table prints on both the dry run and the write.

**Measured 2026-09-09, bounded to `DESIGN_THROUGH` (2026-02-13), over the 12-name universe
(108,465 symbol-sessions):**

| expression | kind | fires | retention vs base |
|---|---|---|---|
| `close crosses_above bb_mid(20, 2)` (base) | control | 6,297 (58.1 / 1000) | — |
| `… and close > swing_high(10)` | treatment | 705 | **11.20%** |
| `… and rsi(14) > rsi_at_swing_high(14, 10)` | treatment | 881 | **13.99%** |
| `… and rsi_at_swing_low(14, 10) < rsi(14)` | negative control | 5,873 | **93.27%** |
| `close crosses_below bb_mid(20, 2)` (exit) | exit | 6,304 | — |

Every expression fires; both treatments sit inside [2%, 95%]; the negative control retains 93.27%, a
near-no-op by design. The field is reachable and the gate passes.

**Drift from the brief's stated facts — mine wins, and I say so (per the brief's instruction):**

- The base `bb_mid(20, 2)` fires **58.1 / 1000**, not the brief's ~35 / 1000.
- `close > swing_high(10)` retains **11.20%**, not the brief's ~65%. It still *binds* (well inside the
  gate band) and is a legitimate treatment, but the retention is far lower than stated. This changes no
  design decision — the arm remains a valid, well-filtering treatment.
- `rsi(14) > rsi_at_swing_high(14, 10)` retains **13.99%** ≈ the brief's ~14% (mid base). Matches.
- `rsi_at_swing_low(14, 10) < rsi(14)` retains **93.27%** ≈ the brief's 93% (mid base). Matches.

The two matching numbers and two drifted ones suggest the brief's base/swing figures came from a
different store snapshot or universe; the figures above are what this store returns today and are what
the field was range-checked against. The `bb_upper(4, 4)` / `bb_lower(4, 4)` dead expressions are never
used here. Only the **high-firing `bb_mid` base** is used (the low-firing `bb_upper` base is not part of
this field), so its drift is immaterial to what runs.

## 4. Windows, metric, decision rule

**Windows:** the standard eight-window main matrix (`WINDOWS.md`): `q4-2018`, `covid`, `bear-2022`,
`chop-2015`, `chop-2011`, `bull-2024`, `recent`, `gfc`. All 12 names begin no later than 1998 (INTC 1980,
TXN 1972, NVDA/AMD earliest 1999–2002 — see below), so eligibility is expected at 8 of 8. `13f-legal` is
card-filtered to a provenance this round does not carry and will not run.

**Metric:** median exposure-adjusted excess across a card's eligible main windows,
`adjusted_excess = strategy_return − capital_exposure × benchmark_return` (`score.py`'s primary key,
benchmark SPY). **Reported as arm-minus-control, never arm-vs-SPY.** A conjunct can only *reduce*
firings, so treatment arms take fewer trades and carry lower exposure than the control; raw return would
credit the control merely for being invested more, which is exactly what `adjusted_excess` exists to
strip out. Scored with `--pin-store`.

**Decision rule, pre-registered.** A conjunct "pays for itself" only if its **arm-minus-control median
adjusted excess exceeds 21.2pp** (`PROTOCOL.md` §7 noise floor) **AND** survives **BH q < 0.10** with the
denominator = **every cell run** (8), per §3 rule 8. Marginals over the two slot caps are read together;
no single window is ranked (`PROTOCOL.md` §4).

**The degenerate outcome is distinguished from the null in advance.** A treatment that filters so hard it
takes ≈0 trades — or fails the 5-of-8 regime gate in some windows and is **unranked** — has been
**switched off**; that is **not** the same finding as "the conjunct did not help." This programme's
standing lesson: a card that takes no trades measured nothing, and its silence must not be read as
evidence either way.

**Honest prior: the null.** Rounds 17, 18 and 34 put form, exit and rotation all inside the 21.2pp floor
(minimum BH q 0.40 across the round-34 family). The likeliest outcome is that no conjunct clears the
floor, which would put a number on what a confirmation term is worth on this book: little.

## 5. Falsifiable predictions

Each card carries these in its `falsification` field; the per-card reporter prints prediction beside
outcome.

1. **No treatment arm beats the control by >21.2pp** on median adjusted excess AND survives BH q<0.10. If
   one does, a confirmation conjunct pays for itself on this book — the result that would change the
   programme's direction. *Failure regime: a treatment clears the floor only in trending windows and the
   median is dragged under it by chop.*
2. **The divergence-proxy negative control is indistinguishable from `none`** (|arm−control| < 21.2pp),
   because it retains 93.27% of the base's firings. If it separates, the metric or the store moved, not
   the strategy.
3. **Both treatments take materially fewer trades and lower exposure than the control** (they retain
   ~11–14% of firings). If a treatment's trade count is not below the control's, the conjunct did not
   bind and the reachability figure is stale.
4. **The sign of arm−control flips by regime**: in a strong trend (`recent`, `bull-2024`) a confirmation
   delays entry and gives back early upside; in chop (`chop-2015`, `chop-2011`) it avoids false starts. So
   any single-window arm−control read is unsafe; only the eight-window median is interpreted.
5. **Degenerate guard:** a heavily filtered treatment at slot cap 6 may fail the 5-of-8 regime gate in one
   or more windows and be unranked — "switched off", not "did not help".

## 6. What this round cannot settle

- **It is one universe, and not a survivorship-free one.** Twelve large-cap tech/semiconductor names,
  mechanically defined by the pool but selected long ago for what they *are*. A conjunct that suits these
  twelve need not suit anything else, and the universe carries survivorship bias the sector-ETF rounds do
  not.
- **It is price-only and dividend-free**, like every backtest in this programme.
- **It cannot promote anything.** It is a measurement study; two consecutive qualifying rounds on
  differing window sets, margins outside the floor, would be required before any cell became a candidate.
- **It says nothing about confirmation terms the DSL cannot express** — multi-symbol confirmation,
  cross-sectional strength, volume regimes gated on non-price data.
- **It tests four conjuncts, not "confirmation" in general.** A null here refutes *these* terms on *this*
  book, not the persona's claim in full generality.

## 7. Run recipe (to execute after freeze — not run by this document)

```
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round40.py --write
bash strategy-program/tools/run_round.sh data/rounds/r40-2026-09/cards data/rounds/r40-2026-09/results
PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/score.py \
    --results data/rounds/r40-2026-09/results --json data/rounds/r40-2026-09/scorecard.json --pin-store
```
