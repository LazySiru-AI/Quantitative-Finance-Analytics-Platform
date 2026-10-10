# Mix-and-match rounds 45-47 — persona components crossed with each other and with measured forms

Written 2026-09-09, before any of the three rounds ran. **Not investment advice.** Every figure these
rounds will produce is a backtest on price-only daily bars with no dividends; no influencer is
endorsed, and the honest prior for every cell is the programme's null record (rounds 1-44).

## 1. What "mix and match" means here, and what it must not become

The owner asked for rounds that combine the influencers' methods with each other and with what the
programme has already measured. The danger is obvious: a combinatorial search over components is the
exact activity `PROTOCOL.md` §3 forbids ("no grid search"), and the more cells a field has the more
§3 rule 8's correction costs every one of them. So each round below is a **pre-registered factorial
with a control in every stratum**, one decision per arm against its own base, every cell run and
counted in the BH denominator, and a decision rule fixed before any result exists. Nothing is promoted
from any of the three whatever it returns; they are measurement rounds.

## 2. The component inventory — what the vault supplies, and what is already measured

**Persona components, from the vault** (`PERSONA-HYPOTHESES.md` §3, `PERSONA-DISCUSSION-2026-09-09.md`
§3-§4, the consolidated profiles, and the two strategy-card drafts the vault produced 2026-09-09 via
`app.personas.strategy.draft_strategy_card`, saved under `data/vault/influencers/<slug>/strategy/1.json`):

| persona | component | expressible form | measured so far |
|---|---|---|---|
| Creator E | confirmation conjunct | `rsi(14) > rsi_at_swing_high(14, 10)` on a `bb_mid` cross | r40: the one positive persona cell (+7.8/+4.8pp, inside floor); seated by direction as `r40-rsi-confirm-slots6` |
| Creator E | 1% risk per trade | `position_pct = 0.01 / stop_loss_pct` | never — sizing has only been varied as slot count (B3, r40) or vol-target (ROTH-VOLTARGET) |
| Creator E | wick reclaim | `low < swing_low(20) and close > swing_low(20)` | r42: null |
| Creator C | 20-week trend filter | `close > sma(100)` | r17/r34 tested `sma(200)`; the vault draft (`ma-crossover`, `close > sma(100) and ema(12) crosses_above ema(50)`) carries it |
| Creator C | 0.25-range breakout confirmation | `close crosses_above swing_high(20) + 0.25*(…)` | r42: null |
| Creator C | accumulate on dips inside an uptrend | `close < sma(50) and close > sma(200)` entry | never as a held-basket entry |
| Creator A | buy weakness in conviction themes; metals in stress | dip entry; `GLD` destination | DRAWDOWN-LADDER (leveraged sleeve, seated with reserve); r43 `AGG→GLD` arm null |
| Creator D | bond-market stress | `AGG close < sma(200)` | r43: +1.3pp drawdown, mostly 2022 |
| Creator B | risk-first, max loss ≤ 1/5 of gain | `take_profit_pct = 5 × stop_loss_pct` | r17/r18 brackets marginal 0.14pp — but never a 5:1 asymmetric bracket |
| Creator B | trim after exceptional gains | exit `close > sma(200) * 1.15` | r44 trim arm: +0.4 to +2.4pp, null |
| Creator B | fundamentals/valuation | vault draft `band-reversion` proxy: `close > sma(200) and close < bb_lower(26, 2)` | the proxy itself never run |

**Enhancements the programme has measured on its own forms:** regime filter `sma(200)` (r17/r34),
exit form (r18), brackets (r17/r18), hold caps (r24), `rank_by` (r36), slot cap (r40), confirmation
conjuncts (r40/r41), ATR and vol tilts on the savings book (ALLOCATION-FAMILY, SAVINGS-FAMILY), macro
tilts (r38), bond-sleeve tilt (r43), thematic passive baskets (r44).

**What the vault drafts are, honestly.** `draft_strategy_card` maps a persona's *described*
methodology onto one of the evolution loop's eight rule shapes by a model call and the draft carries a
fixed caveat: "inspired by, not a faithful reproduction". Two personas mapped (Creator C →
`ma-crossover`, fidelity 0.38; Creator B → `band-reversion`, fidelity 0.0 — his method is
fundamentals and the draft says so). Creator E's draft was refused because his only current
bullish ticker is a gold future (`GC`); his base below is therefore his best *measured* card. Creator D
and Creator A have no consolidated methodology to map and contribute components, not bases. **The
drafts' universes are not used**: they are today's bullish tickers, several of them 2022-25 listings
(APLD, ARM, CRCL, CRDO, CRML, CORZ, BE, DDOG, CLSK) that fail window eligibility everywhere and one
(AMAT) that the Roth book already claims; every round-45 cell runs the rule on the programme's
12-name `_TAXABLE_GROWTH` pool instead, which is what makes the three bases comparable on their
enhancements and is disclosed as a substitution.

## 3. The three rounds

### Round 45 — trading: persona method cards × cross-persona enhancements (14 cells)

Three bases, each another persona's method rendered as a rule, each carrying four enhancements
borrowed from the *other* personas, one decision per arm:

| base | rule | source |
|---|---|---|
| `kim` | `close crosses_above bb_mid(20, 2) and rsi(14) > rsi_at_swing_high(14, 10)` / exit `close crosses_below bb_mid(20, 2)`, stop 0.12, hold 150, 6 × 0.125 | `r40-rsi-confirm-slots6`, verbatim |
| `bee` | `close > sma(100) and ema(12) crosses_above ema(50)` / exit `ema(12) crosses_below ema(50)`, stop 0.08, tp 0.16, hold 30, 5 × 0.15 | vault draft `creator-c/strategy/1.json`, rule verbatim |
| `creator-b` | `close > sma(200) and close < bb_lower(26, 2)` / exit `close crosses_above bb_mid(26, 2)`, stop 0.12, hold 150 (draft said 252; capped to the 9-month mandate), 4 × 0.20 | vault draft `wsaj/strategy/1.json`, rule verbatim |

| arm | change vs base | whose component |
|---|---|---|
| `base` | none | — |
| `trend100` | entry `+ " and close > sma(100)"` (omitted for `bee`, which already carries it) | Creator C |
| `rr5` | `take_profit_pct = 5 × stop_loss_pct` | Creator B |
| `risk1pct` | `position_pct = 0.01 / stop_loss_pct` (slots unchanged) | Creator E |
| `trim115` | exit `+ " or close > sma(200) * 1.15"` | Creator B |

Decision rule: an enhancement earns something only if its marginal — the mean over bases of (arm −
base) on median adjusted excess — exceeds 21.2pp AND the arm cells survive BH q<0.10 with m = 14.
`trading` purpose: nothing is promotable (r21 amendment). Pre-registration: `ROUND-45-PLAN.md`.

### Round 46 — savings: do two independent de-risking reads stack? (7 cards)

Same base as rounds 38/43 (SPY 0.30 / AGG 0.50 / GLD 0.10 / BIL 0.10, band 0.05, every shift 0.10):
`control`; `spy-derisk` (r38/r43 placebo verbatim); `agg-derisk` (r43 primary verbatim); `both`;
`both-gld` (both + r43's `GLD > sma(200) → AGG→GLD`); `trim-high` (`SPY > sma(200) * 1.15 → SPY→BIL`,
Creator B's trim on the equity sleeve); `both-trim`. The question is additivity: each single
read moved drawdown by about a point in its own round; a stack that moves it by the sum is two
independent signals, one that moves it by less is the same signal read twice. Ranked on drawdown
margin, MAR joint, CAGR reported; 2022 bear windows pre-declared in-sample (as r43). Pre-registration:
`ROUND-46-PLAN.md`, harness `tools/round46_run.py`.

### Round 47 — roth: buy weakness × sell strength on held baskets (12 cells)

Three of round 44's baskets (`control` VTV SPYG RSP MDY, `power` NEE DUK SO CCJ, `defense` LMT NOC
GD RTX) × four arms: `passive` (r44 verbatim); `dip` (enter `close < sma(50) and close > sma(200)`,
never exit — Creator A's and Creator C's "accumulate on pullbacks inside an uptrend", then hold);
`trim` (r44 verbatim, Creator B); `dip-trim` (dip entry, trim exit — buy weakness, sell
strength, the two personas' disciplines combined). Arm − passive within basket > 21.2pp AND BH
q<0.10 (m = 12); hindsight split as in round 44 (six fair windows ending by 2022-10 vs `bull-2024`
and `recent`). Pre-registration: `ROUND-47-PLAN.md`.

## 4. Predictions common to all three (each plan sharpens its own)

1. The null, in every stratum. Forty-four rounds have not found a margin outside the floor, and
   combining two null components is the programme's prior for a third null, not for an edge.
2. Enhancements that *filter* (trend100, dip) reduce trades and exposure; enhancements that *exit*
   (trim115, trim) give back upside in `bull-2024`/`recent` and may shallow `gfc`/`bear-2022`;
   the 5:1 bracket rarely binds (r17/r18: 0.14pp), so `rr5` cells are predicted near-identical to
   their bases and the report must count how often the target actually fired.
3. In round 46, `both` ≈ `spy-derisk` + `agg-derisk` within half a point if the two reads are
   independent; materially less if they fire on the same sessions.
4. Hindsight is unbounded (every corpus note has `published = null`); rounds 46 and 47 report the
   pre-declared contaminated windows separately, as rounds 43 and 44 did.

## 5. Run order and what is committed when

Fields are authored by `tools/round45.py`, `tools/round46.py`, `tools/round47.py`, frozen in one
commit before any run, then run **serially** (the host binds on memory): 45 and 47 through
`run_round.sh` + `score.py --pin-store` + their own report tools, 46 through `round46_run.py`. Each
round's `REPORT.md` scores its plan's predictions beside outcomes; `PROTOCOL.md` §9 gets one row for
the three.

## 6. Outcome (added after the runs, 2026-09-09)

All four rounds ran the same day (45: commit `d400a4c`; 46: `f755f5c`; 47: `5baac42`; 48: `01487ac`,
each frozen before its run) and all four returned the null on their pre-registered decision rules —
see each `data/rounds/r4N-2026-09/REPORT.md`. Two things survived as *measurements*, not edges:
round 46's two de-risking reads add (+2.45pp of drawdown on the savings book for −0.54pp of CAGR),
and round 48's 1%-risk sizing halves every seated trading card's worst window and realised P&L
together. Three cards went to the library shelf by the owner's direction (`PROTOCOL.md` §9,
r45-48 row); no desk roster changed. The feedback loop is closed: every prediction in the four plans
is scored beside its outcome, and no unresolved candidate margin remains that a further round could
sharpen without a new hypothesis.
