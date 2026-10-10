# Round 21 — the first round whose cards could read a non-price field, and it could not be tested

**Not investment advice.** Price-only bars plus one macro scalar, no dividends, no promotion.

Pre-registration: [`strategy-program/ROUND-21-PLAN.md`](../../../strategy-program/ROUND-21-PLAN.md).
Cards frozen at **`a49ab48`**, before any backtest ran, per PROTOCOL §2.
Amendment 1 recorded at **`d9dfead`**, before any cell was scored.

---

## 1. The headline

**This round did not measure whether a macro regime overlay changes a result. It measured that this
window matrix cannot ask the question.** Those are different findings and only the second is
supported.

`macro(T10Y2Y) > 0` blocks **81 of 1,716 eligible sessions** across the eight main windows, and in
only two of them. **24 of 32 (form, window) pairs came back byte-identical** between the gate-on and
gate-off halves. The mean gate marginal is **+0.044pp** — a number produced by six identical pairs
and two that differ, not by macro data being uninformative.

Reporting that as "a macro gate does not change a result" would be the `DEFECTS.md` D5 failure in its
purest form: a complete-looking table measuring something other than what it says.

## 2. What ran

8 cells (4 forms × gate on/off) × 8 main windows = **64 runs, 0 failures**. Every cell ran 8 of 8
eligible windows and every cell was ranked; none fell to the 5-of-8 gate.

| form | median off | median on | **gate marginal** | trades off/on | windows differing |
|---|---|---|---|---|---|
| ma-crossover | +0.17% | +0.17% | **+0.000pp** | 155 / 148 | bear-2022, bull-2024 |
| rsi-pullback | +0.20% | +0.20% | **+0.000pp** | 160 / 156 | bear-2022, bull-2024 |
| channel-breakout | −2.30% | −2.30% | **+0.004pp** | 104 / 101 | bear-2022, bull-2024 |
| vol-compression | −5.14% | −4.97% | **+0.172pp** | 187 / 177 | bear-2022, bull-2024 |

Mean gate marginal **+0.044pp**; largest of any form **0.172pp**. The whole eight-cell field spans
**5.35pp**, which is the *form* effect and is consistent with round 17's 7.56pp on a wider field.

**The same two windows for all four forms**, and they are exactly the two where the curve inverts at
all. That coincidence is the finding.

## 3. Why the design could not work

The eight main windows were selected on **equity** regimes — a crash, two chops, a bull, a recent
slice, the GFC. Nothing in that selection considered the curve. The curve inverted in 2006–07, 2019
and 2022–24; the matrix begins its GFC window on 2007-10-09, *after* the first inversion ended, misses
2019 entirely, and catches the third only in `bear-2022` and the tail of `bull-2024`.

§3 of the plan argued for `T10Y2Y` over the three price indices because it is a spread rather than a
trending level. That reasoning was right and is not what failed. What was never checked is whether the
spread **crosses its threshold inside the windows it would be scored on**. That check cost one query
and was not made until a smoke run forced it.

## 4. The §4c diagnostic fails the same way, from the other direction

The diagnostic gated `ma-crossover` on `macro(CPILFESL) > 300` and ran it twice — release-date bound,
and naively bound at the reference date — to measure the causality trap directly.

**The two bindings produced identical results in all eight windows: a gap of 0.000pp.**

Not because the trap is harmless. Because core CPI crossed 300 in mid-2022 and **no window straddles
that crossing**: the card made **zero trades in six of eight windows** (the index sat below 300
throughout), and in the two where it traded the index was far above 300 throughout, so a 45-day shift
in when the value became visible changed nothing. The plan predicted this shape for the price indices
in §3 and then used one in §4c anyway.

The naive binding is simulated honestly rather than by disabling the guard: its pin carries every
reference date shifted back by the 45-day lag, so release-date binding on *that* pin reproduces
exactly what a reference-date join would have shown on the real one. The guard's per-session check
passes for both, because in each case the configured lag was respected relative to the pin it was
given.

## 5. Predictions, scored

| # | prediction | outcome |
|---|---|---|
| 1 | gate marginal will not exceed the circular-shift null's 95th percentile | **untested** — the null was not run (Amendment 1); a null for a factor varying on 81 of 1,716 sessions measures nothing precisely, at 6,400 runs |
| 2 | gate-on reduces trade count in every cell-window | **untested** — checked per cell-window: **0 traded more, 25 identical, 7 fewer.** The direction never reverses, so the binding is not backwards; but the prediction was "reduces in every one of 32", and it reduced in 7. The other 25 are vacuous, not confirmations |
| 3 | at least one of the 8 cells falls short of the 5-of-8 eligibility gate | **refuted, uninformatively** — all 8 cells ran 8/8. `vol-compression` was predicted to fail under a stacked filter; nothing stacked, because the gate barely fires |
| 4 | naive binding strictly more favourable than release-date binding on average | **untested** — the gap is exactly 0.000pp in every window (see §4) |
| 5 | the naive-vs-release gap is smaller than the 21.2pp floor | **held vacuously** — 0.000pp is smaller than 21.2pp, and means nothing |

One refutation, uninformative; four untested. **A round that scores 4 of 5 predictions "untested" is
telling you its design did not engage its subject**, and that is the honest summary.

## 6. What the round did establish

**The instrument is verified stable across the engine change.** `r21-ma-crossover-off` is identical in
construction to round 17's `r17-ma-crossover-on-none` and **reproduces its committed figures to the
digit** — median, worst, hit rate and trade count. A new AST node, a new binding layer, a new pin
format and a new guard check were added between the two rounds and moved no existing number. That is
the check round 18 ran against round 17 and it is why any between-round comparison here can be read
at all.

**The class is now reachable.** `docs/research/programme/00-EVERYTHING-TESTED.md` §3b listed FRED
macro series as "collected, displayed, **unreachable by any card**". That is no longer true: a card
can name one, the guard verifies per session that no value was read before it was published, and the
round's data is pinned and digest-verified so the run reproduces. That was recommendation #4 and it is
done, independently of this round finding nothing.

**And the honest prior held.** The plan predicted this finds nothing, on a base rate of ~50 concepts
and near-zero survivors. It found nothing — though for a reason the plan did not anticipate, which is
worse than finding nothing for the expected reason.

## 7. Promotion

**None.** Like rounds 15–18 this is a measurement study; nothing here is promotable. The r21 amendment
to `PROTOCOL.md` §9 additionally removes §6's promotion rule from the `trading` purpose entirely, so
no path to a seat exists from this field regardless of what it had shown.

## 8. What a successor round needs

A window matrix sampling **curve** regimes rather than equity ones — at minimum 2006-01 → 2007-06
(sustained inversion), 2019-05 → 2019-10, and 2022-07 → 2024-08. All three sit inside the nine sector
SPDRs' history, which begins 1998-12-21, so the universe need not change.

That is a **new pre-registration**, written before its data is seen. Adding those windows to this
round retroactively would be selecting windows on the outcome variable — the failure round 4 exists to
document — and would convert an honest null into a fitted one.

**Two smaller items this round leaves open**, both named in the plan and neither closed here: the
45-day monthly lag is a conservative placeholder rather than the BLS and BEA release calendars, and
the revision leak stays open — a pin freezes *which* revision was used, not what was on the wire on
each historical date, which needs FRED's ALFRED vintage archive.
