# Round 15 candidates — five new `AllocationCard`s, three purposes

**Not investment advice.**

Authored and frozen against `ROUND-15-PLAN.md` section 4, `ALLOCATION-FAMILY.md` and
`backend/app/tournament/allocation.py`'s `AllocationCard`/`TiltRule` models. Every card below
validates against `AllocationCard.model_validate_json` and `designed_through` is `2026-02-13` — the
same design cutoff the four already-frozen cards use, since no calendar time has passed for round 15
to advance it. Full theses live in each card's own `thesis` field; this document summarises them and
states what each is meant to discriminate against.

## Why five cards, and why this shape

Round 15's own question is whether funding shape (lump sum vs. monthly vs. annual contributions)
changes which strategy should sit in an account. Answering that well needs, for each purpose, a card
that carries a conditional rule and a matched control that carries none — otherwise a purpose's
ranking cannot separate "this mechanism earns its complexity under this funding shape" from "this
symbol set happened to do well." Savings already had exactly that pair by accident
(`qld-schd-sgov` and `spy-schd-agg-gld-bil-atr-tilt` are two different mechanisms on different
symbols, not a tilt/no-tilt pair). This round gives every purpose a genuine tilt-vs-static pair on
the *same* symbols, plus a no-tilt control for the savings arm's existing tilted card:

| purpose | new cards | existing cards entering as-is |
|---|---|---|
| savings | `spy-schd-agg-gld-bil-static` | `qld-schd-sgov`, `spy-schd-agg-gld-bil-atr-tilt` |
| trading | `qqq-ief-gld-atr-tilt`, `qqq-ief-gld-static` | `ladder-qld-schd` |
| roth | `sso-vig-bnd-mean-reversion`, `sso-vig-bnd-static` | `ladder-sso-vig-bnd` |

## The five cards

### 1. `spy-schd-agg-gld-bil-static` — savings

- **Holds**: SPY 40% / SCHD 20% / AGG 20% / GLD 10% / BIL 10%, band 5%, no rules.
- **Thesis in brief**: the identical sleeves and weights as `spy-schd-agg-gld-bil-atr-tilt`, with its
  two ATR rules removed. `ALLOCATION-FAMILY.md` found, under a single lump-sum run, that the tilt's
  15.4x turnover bought a MAR improvement of only 0.38→0.40 and *lost* on MAR in the CRISIS window
  (0.02 vs 0.01) despite a shallower drawdown. This card lets the savings arm ask the same question
  under a $20,000-seed-plus-$1,000/month drip, a genuinely different funding shape from the one that
  finding was measured under.
- **Parameter count**: 4 free weights + 1 band = **5 of 10**.
- **Expected eligible windows**: bound by SCHD's 2011-10-20 start — all five long windows
  (`h10y-1`, `h10y-2`, `h5y-1`, `h5y-2`, `h5y-3`), and the full main-window matrix back to late 2011.
- **Discriminates against**: `spy-schd-agg-gld-bil-atr-tilt` (tilt vs. no tilt, isolating exactly one
  decision per `PROTOCOL.md` §7) and, more loosely, `qld-schd-sgov` (diversified, unlevered vs.
  concentrated, levered).

### 2. `qqq-ief-gld-atr-tilt` — trading

- **Holds**: QQQ 55% / IEF 25% / GLD 20%, band 5%, one rule: when QQQ's own ATR(14) exceeds 2.8% of
  its own close (QQQ's own historical ATR/close ratio measured off stored bars: median ≈1.61%, 75th
  ≈2.44%, so 2.8% sits just above the 80th percentile — read off the instrument's own distribution,
  not a round number, the same discipline `ALLOCATION-FAMILY.md` used for SPY), shift 10 points from
  QQQ into IEF.
- **Thesis in brief**: unleveraged, single-index Nasdaq-100 core for the one purpose (trading) with no
  contribution stream to dilute a concentrated bet and no horizon ceiling. Tests round 15's own
  prediction 4 ("no candidate will beat QQQ buy-and-hold on raw return") by making QQQ itself the
  core, at the cost of losing SPY's whole-market breadth. Falsified if QQQ's ATR spikes are
  systematically followed by strength rather than weakness (the rule sells the entry point) or if the
  rule's turnover cost exceeds the drawdown reduction it buys.
- **Parameter count**: 2 free weights + 1 band + 2 rule params (0.028 threshold, 0.10 shift) =
  **5 of 10**.
- **Expected eligible windows**: bound by GLD's 2004-11-18 start — full main-window matrix back to
  late 2004 and all five long windows (not gated by the ≥3-window rule, which binds only the
  contribution-funded arms).
- **Discriminates against**: `qqq-ief-gld-static` (tilt vs. no tilt), `spy-schd-agg-gld-bil-atr-tilt`
  (QQQ core vs. SPY core, same tilt idea), `ladder-qld-schd` (continuous unlevered core vs. a
  drawdown-gated leveraged rung structure, both trading purpose).

### 3. `qqq-ief-gld-static` — trading

- **Holds**: identical sleeves/weights to card 2, no rules.
- **Thesis in brief**: the trading arm's only plain constant-weight blend — `ladder-qld-schd` is a
  state machine, so nothing in that purpose previously answered whether *any* conditional machinery
  earns its complexity against a $100,000 lump sum.
- **Parameter count**: 2 free weights + 1 band = **3 of 10**.
- **Expected eligible windows**: identical to card 2.
- **Discriminates against**: `qqq-ief-gld-atr-tilt` (tilt vs. no tilt).

### 4. `sso-vig-bnd-mean-reversion` — roth

- **Holds**: SSO 35% / VIG 40% / BND 25%, band 5%, two rules mirroring `qld-schd-sgov`'s own mechanics
  on Roth-safe tickers: (1) SSO below its own 150-day SMA → shift 8 points VIG→SSO; (2) SSO above its
  own 20-day/2σ upper Bollinger band → shift 8 points SSO→BND.
- **Thesis in brief**: a direct ticker-swap re-expression of `qld-schd-sgov` (QLD→SSO, SCHD→VIG,
  SGOV→BND — SGOV itself is disqualified on coverage grounds, see below), the same substitution
  discipline `ladder-sso-vig-bnd` already applied to the ladder shape. Explicitly **not** a claim that
  the substitutes are "not substantially identical" under IRC §1091 — that is unsettled and stays
  labelled as an argument, not a ruling. Falsified by a sustained one-way trend in the S&P 500 in
  either direction, the identical failure mode `qld-schd-sgov`'s own thesis states for QLD.
- **Parameter count**: 2 free weights + 1 band + rule 1 (SMA period, shift = 2) + rule 2 (BB period +
  σ, shift = 3) = **8 of 10**.
- **Expected eligible windows**: bound by BND's 2007-04-10 start — all five long windows.
- **Discriminates against**: `qld-schd-sgov` (same mechanism, taxable vs. Roth-safe tickers, lump sum
  vs. annual-contribution funding shape) and `ladder-sso-vig-bnd` (same disjoint tickers, continuous
  tilt vs. discrete armed-rung ladder — tickers held fixed, mechanism as the one free variable, which
  no prior round could measure).

### 5. `sso-vig-bnd-static` — roth

- **Holds**: identical sleeves/weights to card 4, no rules.
- **Thesis in brief**: the Roth arm's only pure buy-and-hold-with-rebalancing entrant, completing a
  three-way Roth comparison (ladder / continuous tilt / no conditional logic at all) that did not
  exist before this round.
- **Parameter count**: 2 free weights + 1 band = **3 of 10**.
- **Expected eligible windows**: identical to card 4.
- **Discriminates against**: `sso-vig-bnd-mean-reversion` (tilt vs. no tilt) and, jointly with card 4,
  `ladder-sso-vig-bnd`.

## Why SGOV is absent from every new card

`SGOV`'s stored coverage starts 2020-06-01, after all but one (`h5y-3`, 2021-02-16 onward) of round
15's five long windows already begin. A card holding SGOV can reach only that one window, which is
below the round's own ≥3-window minimum for a contribution-funded arm (`ROUND-15-PLAN.md` §5) —
such a card would be published and **unranked**, contributing nothing to the purpose-fit question
this round exists to answer. `qld-schd-sgov` already carries this cost as an existing frozen card;
no new card repeats it by choice.

## The vol-targeting / risk-parity expressibility gap (a finding, not an attempt)

`ALLOCATION-FAMILY.md` measured two variants that `AllocationCard` cannot express at all:

- **Continuous vol-targeting** — `SPY_weight = min(1.0, target_vol / realized_vol(SPY, lookback))`,
  with the residual split fixed 50/50 between IEF and GLD. At a 12% target and 60-session lookback
  this was the single best risk-adjusted number in that whole study (FULL-window MAR 0.34, beating
  both SPY and QQQ buy-and-hold), and the same study showed a 20% target reproducing the "leverage
  trap" on an entirely unlevered instrument — worse than the plain static blend in the 2008 slice.
- **Continuous inverse-volatility risk parity** — `weight_i = (1/vol_i) / sum(1/vol_j)` across SPY,
  IEF, GLD, recomputed every session with no privileged "core" sleeve.

Neither is attempted here, nor approximated by a staircase of boolean `TiltRule`s stepping through
several fixed thresholds — `ROUND-15-PLAN.md` §4 names that staircase explicitly as the smuggling
this round's design discipline exists to prevent, because a discrete multi-rung approximation of a
continuous function is still a fitted shape whose rung count and thresholds nobody pre-registered
from a thesis; the fact that it *could* be made to track a continuous curve closely with enough rungs
is exactly what makes it indistinguishable from a grid search dressed as a design choice.

**Why `TiltRule` cannot express either, precisely**: `shift_pct` is a `Decimal` declared once on the
card — a fixed number of percentage points, identical whether the triggering condition is barely true
or wildly true. Vol-targeting's core weight is a continuous function of a real number (the ratio of a
target to a realised volatility) that can sit anywhere between 0 and 1.0 and changes by a different
amount on two sessions where realised vol differs. Risk parity's weights are not a shift *between* two
named sleeves at all — they are a full re-derivation of every sleeve's weight from every other
sleeve's current risk, every session, with no "from"/"to" pair to name.

**What would have to change to close the gap** (from `ALLOCATION-FAMILY.md`, restated here because it
still holds and this round does not act on it):

1. **A new field type on `TiltRule`** — a formula, or a reference to a computed quantity
   (`weight = f(indicator_value)`), replacing the fixed `shift_pct` — a materially larger change to a
   model this task (and `ROUND-15-PLAN.md` §8) explicitly scopes as read-only, not a small addition.
2. **A fourth card type**, sized the way `LadderCard` was built as a third shape when `AllocationCard`
   turned out not to fit a state-machine strategy — a `VolTargetCard` or `RiskParityCard` with its own
   `run_*` engine, following the "why a new module, not new fields" argument `allocation.py`'s and
   `ladder.py`'s own docstrings already make twice.

Neither is done in this round. This is reported as a finding, exactly as `ROUND-15-PLAN.md` §8
pre-registers: "It does not add a fourth card type. Vol-targeting and risk parity stay inexpressible
and stay recorded as such."

---

**Not investment advice.**
