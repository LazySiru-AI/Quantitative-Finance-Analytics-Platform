# Round 33 Phase A — selector bake-off results

Pre-registered in `strategy-program/ROUND-33-PLAN.md` before any measurement existed.
Run 2026-08-31 (~7.7h, 6 workers). Regime instrument: the §5 three-signal reconstruction
(`spy_trend`, `realized_vol`, `macro_2s10s` from SPY bars + release-lagged FRED T10Y2Y);
`fear_greed` abstains for the whole replay — a different, weaker instrument than the live
four-signal desk, disclosed in §0. Not investment advice.

## §7 gate outcome

**Promoted to the live `universe_select` seat: `mom12_1_hysteresis`** (branch 2).

Six entrants were not statistically worse than either control on the in-sample slice;
`mom12_1_hysteresis` has the lowest mean shortlist churn (0.037/session) and lowest implied
research spend ($0.13/day) among them, so the mechanical tiebreak selects it. This is the
"cheapest credible attention-allocator" branch the programme's record predicted would fire —
not a demonstrated IC edge (see the interpretation below).

## In-sample (2004-12-28 .. 2017-12-29, 3,276 sessions)

| selector | n scored | mean IC | boot p | BH q | hit | churn | $/day |
|---|--:|--:|--:|--:|--:|--:|--:|
| mom12_1_hysteresis | 3199 | +0.0398 | 0.016 | 0.126 | 0.570 | 0.037 | 0.13 |
| breakout_atr | 1033 | +0.0277 | 0.078 | 0.214 | 0.558 | 0.044 | 0.10 |
| meanrev_rsi | 654 | +0.0392 | 0.107 | 0.214 | 0.569 | 0.040 | 0.11 |
| trend_sticky | 3276 | +0.0201 | 0.134 | 0.214 | 0.541 | 0.067 | 0.16 |
| signal_density | 1654 | +0.0054 | 0.530 | 0.707 | 0.510 | 0.742 | 2.34 |
| divers_mom6 | 3276 | +0.0219 | 0.120 | 0.214 | 0.538 | 0.202 | 1.21 |
| control_card_universe | 0 | — | — | — | — | 0.071 | 1.15 |
| control_week_rotation | 3276 | +0.0050 | 0.710 | 0.812 | 0.491 | 0.145 | 0.87 |

## Held-out (2018-01-02 .. 2026-08-18, 2,168 sessions)

Computed after the in-sample §7 decision was fixed, never consulted in making it.

| selector | n scored | mean IC | boot p | BH q | hit | churn | $/day |
|---|--:|--:|--:|--:|--:|--:|--:|
| mom12_1_hysteresis | 2062 | +0.0284 | 0.105 | 0.839 | 0.541 | 0.060 | 0.23 |
| breakout_atr | 948 | +0.0184 | 0.268 | 0.845 | 0.515 | 0.049 | 0.11 |
| meanrev_rsi | 788 | +0.0165 | 0.363 | 0.845 | 0.528 | 0.070 | 0.18 |
| trend_sticky | 2168 | −0.0076 | 0.622 | 0.926 | 0.480 | 0.082 | 0.21 |
| signal_density | 1024 | +0.0032 | 0.730 | 0.926 | 0.501 | 0.662 | 2.10 |
| divers_mom6 | 2168 | +0.0036 | 0.810 | 0.926 | 0.516 | 0.230 | 1.39 |
| control_card_universe | 0 | — | — | — | — | 0.078 | 1.42 |
| control_week_rotation | 2168 | −0.0118 | 0.422 | 0.845 | 0.463 | 0.144 | 0.87 |

## Interpretation — read against the §8 null

The programme's record predicted essentially nothing survives correction. That prediction
mostly held, with one honest wrinkle:

- **`mom12_1_hysteresis` posts a small, individually-significant in-sample IC** (+0.0398,
  bootstrap p = 0.016). §8 prediction 2 (its in-sample IC lands in roughly [−0.03, +0.03]) is
  therefore **refuted** — it sits just outside, positive. This is a rare non-null in this
  programme, and worth recording as such.
- **But it does not survive multiple-comparison correction**: BH q = 0.126 across the eight
  entrants, above the 0.10 survivor threshold. No entrant clears BH q ≤ 0.10 on either slice.
- **And it does not replicate out of sample**: held-out mean IC decays to +0.0284 (p = 0.105,
  BH q = 0.839) — not significant, consistent with §8 prediction 6 (held-out ICs not
  systematically better than in-sample). Two entrants (`trend_sticky`, and both controls) go
  outright negative out of sample.

So the net reading is the programme's signature pattern: a marginal in-sample signal that
neither survives correction nor holds out of sample. The promotion is on the round's stated
premise — pointing costly research efficiently — not on a demonstrated edge.

### Two disclosed artifacts affecting the gate

1. **`control_card_universe` has an undefined IC** (n scored = 0 on both slices). By the frozen
   grader's design it "picks" its entire card universe each day, so its pick-vs-pool IC has no
   variance and is `None`. Because §7 branch 1 requires beating **both** controls' mean ICs, and
   one control's is `None`, **branch 1 is structurally unreachable** — the round always resolves
   on branch 2. Had the gate compared only against `control_week_rotation`, `mom12_1_hysteresis`
   (p = 0.016, IC +0.0398 > +0.0050) would have cleared branch 1. Either way it is the promoted
   selector; the branch label is the only thing affected.
2. **The regime instrument is 3-signal**, not the live desk's 4-signal (no historical fear/greed
   feed exists). Phase A regime labels are a different, weaker instrument than production, so
   Phase A and any live Phase B regime calls are not directly comparable.

## What this decides, and what it does not

Phase A names `mom12_1_hysteresis` as the selector to run in the live `universe_select` seat for
Phase B, per the mechanical §7 rule. Per PROTOCOL.md §6 / the r21 posture, actually seating it on
the live desk is an **owner decision**, not an automatic promotion — a selector search across
eight entrants is more overfit-prone than a single card, and this result explicitly did not clear
correction or replicate out of sample.
