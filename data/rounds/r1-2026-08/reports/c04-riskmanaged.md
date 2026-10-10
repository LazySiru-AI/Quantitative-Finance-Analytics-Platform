# c04-riskmanaged — competition report

`c04-riskmanaged`, "All-Weather Trend Sleeve" (discipline: `risk-managed`), ranked **17th of 18**
ranked cards on median `adjusted_excess` (**−2.44%**), and this report exists mainly to explain why
that rank is a poor summary of what the card did.

## 1. What the card was

Four independent legs — `SPY`, `EFA`, `TLT`, `GLD` — each held while `close > sma(200)` and exited
when `close < sma(200)`, no cross-asset logic, no rebalancing rule, one stop (`stop_loss_pct = 0.12`)
as a shock backstop. Five parameters against the round's budget of ten: the two `sma(200)` literals
(entry and exit mirror each other), the stop, `max_positions = 4`, `position_pct = 0.25`. No
`take_profit_pct`, no `max_hold_days` — among the simplest cards submitted this round.

The thesis is a forced-seller mechanism, not a predictive claim about the average itself: price below
its own 200-day average is a proxy for pensions, mandate-bound funds, and levered holders being
compelled to keep supplying stock (or bonds) into a market that has already fallen for months: the
"risk-managed" part of the design is applying that filter to four legs whose crisis behaviour differs
(measured pairwise correlation `SPY`/`EFA` 0.86, `SPY`/`TLT` −0.31, `GLD`/`SPY` 0.05, full history —
memo, §"Correlation matrix"), so that one leg's trend break rotates the book toward another trending
leg rather than to cash.

## 2. Results across all five windows

| window | trades | corrected return | benchmark | excess | adj. excess | capital exposure | session exposure | max drawdown | win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gfc | 28 | +1.38% | −56.23% | +57.61% | **+26.03%** | 43.83% | 97.19% | −8.81% | 19.23% |
| covid | 10 | −1.32% | −8.71% | +7.39% | **+3.71%** | 57.76% | 100.00% | −8.01% | 28.57% |
| bear-2022 | 18 | −6.58% | −25.14% | +18.56% | **−2.44%** | 16.49% | 52.55% | −6.27% | 11.11% |
| bull-2024 | 17 | +6.49% | +14.00% | −7.50% | **−2.59%** | 64.90% | 100.00% | −5.58% | 7.14% |
| recent | 10 | +12.05% | +20.62% | −8.57% | **−2.63%** | 71.19% | 100.00% | −9.51% | 37.50% |

Corrected return uses `ending_equity / starting_equity − 1` per DEFECTS.md D1 (the runner's own
`total_return` field is rebased to the first session's mark and is not used here). `capital_exposure`
is `Σ(quantity × entry_price × bars_held) / (sessions × starting_equity)`, reconstructed from the
trade log per D2; `session_exposure` is the runner's raw `exposure` field, kept alongside it because
the gap between the two — 97% vs. 44% in `gfc`, 100% vs. 58% in `covid` — is itself informative about
how thin the capital actually deployed was relative to how often *some* slot was filled.

**Median adjusted excess −2.44%, IQR 6.30 points, hit rate 40% (2 of 5 windows positive), 83 trades
total.** The five values cluster tightly except for one: gfc, covid, and the "ordinary" trio
(bear-2022, bull-2024, recent) sit within about a point of each other at roughly −2.4% to −2.6% —
except gfc, which is 28 points away from that cluster in the other direction.

## 3. Pre-registered failure regime versus outcome

The memo pre-registered two failure regimes, in this order:

> "a sideways, choppy, low-trend market has no edge for this filter and pays repeated whipsaw
> entries/stop-outs against a benchmark that simply sits still" (primary)
>
> "a regime where every asset class de-rates together (a simultaneous equity-and-bond bear, e.g. a
> rate shock) removes nearly the whole book to cash-like exposure at once, leaving the strategy flat
> while a buy-and-hold benchmark may partially recover before the filter re-engages" (secondary,
> concretely: `bear-2022`, with a measured pre-trade estimate of "~17%" blended exposure)

**Primary regime: untested this round.** None of the five windows is a genuinely sideways, low-trend
market — three are crises (gfc, covid, bear-2022) and two are one-directional bull runs (bull-2024,
recent). This prediction cannot be confirmed or refuted by this round's window set; it is neither
called nor missed, it is simply absent from the sample.

**Secondary regime: called, both directionally and quantitatively.** `bear-2022` produced
`capital_exposure = 16.49%`, matching the memo's own pre-trade estimate of "~17%" almost exactly —
the four-leg rotation did collapse toward cash-like exposure exactly as predicted, because 2022 was
the one window in the sample where equities and bonds fell together and there was genuinely little
trending to hold. The adjusted excess in that window, −2.44%, is a modest drag rather than the sharp
loss "removes nearly the whole book" might suggest read alone — and notably, it is not meaningfully
worse than the two *ordinary bull* windows (−2.59%, −2.63%) that were never pre-registered as failure
cases at all. The mechanism did what the memo said it would do; the cost of it doing so was small and
in the same range as the card's ordinary cost of running at all.

One thing the memo did not predict and could not have, since it never queried `gfc`: `gfc` produced
the card's best result by a wide margin, not a neutral or losing one. That is not a failure of
pre-registration — nothing in BRIEF.md asked analysts to forecast their best case — but it is worth
recording plainly that the single most consequential number in this report was outside the scope of
what was pre-registered either way.

## 4. Trade-level detail

**Exit-reason distribution, per window:**

| window | rule | stop | open_at_end |
|---|---:|---:|---:|
| gfc | 26 | 0 | 2 |
| covid | 7 | 0 | 3 |
| bear-2022 | 18 | 0 | 0 |
| bull-2024 | 14 | 0 | 3 |
| recent | 8 | 0 | 2 |

**Zero stop-outs, in any window, across all 83 trades.** The `stop_loss_pct = 0.12` shock backstop
that the memo sized deliberately as "a shock backstop, not a volatility filter" never fired once in
five windows including a −56% and a −25% benchmark decline. Every close was either the `sma(200)`
exit rule itself or a position still open at the window boundary. For this card, in this sample, the
trend signal did all of the defending; the stop contributed nothing measurable and its cost (in
foregone tighter risk control) cannot be assessed from this evidence either way. There is accordingly
no stop-slippage table to report — the brief's warning about previous-close stop mechanics landing
worse than nominal simply never had an occasion to apply here.

**Best and worst trades:**

| window | best | worst |
|---|---|---|
| gfc | GLD, 2007-10-09→2008-08-06, +19.95% (rule) | SPY, 2007-10-09→2007-11-08, −4.99% (rule) |
| covid | TLT, 2020-02-19→open at end, +12.91% | SPY, 2020-02-19→2020-02-28, −14.62% (rule) |
| bear-2022 | GLD, 2022-02-07→2022-05-11, +1.70% (rule) | SPY, 2022-01-03→2022-01-24, −9.39% (rule) |
| bull-2024 | GLD, 2024-08-21→open at end, +33.02% | EFA, 2025-02-06→2025-04-07, −9.52% (rule) |
| recent | GLD, 2025-08-21→2026-06-08, +28.99% (rule) | TLT, 2026-01-15→2026-01-20, −2.36% (rule) |

GLD is the best trade in three of five windows, including the two largest single-trade gains in the
card's book (+33.02% in bull-2024, +28.99% in recent) — consistent with the memo's own read of gold
as "the cleanest true diversifier" rather than an accident of one window. SPY produced the worst trade
in three of five windows, including the covid worst case (−14.62%, entered the week of the index
peak, exited on `rule` as the 200dma finally rolled over — nine sessions of decline the filter simply
could not see coming inside its own logic, not a stop failure).

## 5. Defended versus abstained

Judged on capital exposure and trade count rather than the headline number: this is not a card that
produced its crisis result by sitting on the sidelines. `gfc` (43.83% capital exposure, 28 trades) and
`covid` (57.76%, 10 trades) both show real, sustained capital commitment — over four in ten dollars of
the book deployed on the average `gfc` session, and the two `insufficient_cash` rejections recorded in
that window (plus four more in `covid`) show the sleeve actively trying to add exposure and
occasionally failing to afford a fourth leg, not idling. `bear-2022`'s low 16.49% capital exposure is
the one case that reads as abstention — but per §3, that is the exact, correctly-predicted response to
a window where there was genuinely little to be exposed to, not a failure to engage. `bull-2024` and
`recent` show the highest capital exposure of any windows (64.90%, 71.19%) — fully deployed, and still
trailing a passive allocation of that same capital by roughly 2.6 points each, the closest thing in
this card's record to a genuine cost of running the rule rather than simply holding.

## 6. Verdict

**Does c04's profile indict the median-ranking metric, or the card?** Both claims in the brief's
framing are checkable, and both check out: (a) ranking on median across a window set that is three
ordinary-to-adverse windows against one genuine catastrophe will structurally punish any strategy whose
value is concentrated in the catastrophe, regardless of how sound the mechanism is — that is a property
of the ranking rule, not a discovery about this card. (b) one crisis window is one draw, and the memo's
own stated weakest assumption — that the negative `SPY`/`TLT` correlation holds — is not a standing
law; `bear-2022`, inside this very five-window sample, is direct evidence that it can and does break
down, and did so exactly where the memo said it would.

Both of those are true at once, and they point the same direction: **the metric, not the card, is the
thing to change.** The median penalizes this shape by construction; the card's crisis result, while a
single realized path and not proof of a repeatable hedge, was produced by real capital commitment
(43.83%, not the runner's misleading 97.19% session figure), was pre-registered directionally and,
where checkable, quantitatively (the bear-2022 exposure estimate landed within half a point of the
runner's own reconstruction), and cost almost nothing outside the crisis — about 2.5 points a window,
tightly clustered, with zero stop-outs across 83 trades to suggest the risk control is loose or the
rule is fragile. A card built from five unfitted, conventionally-sized parameters that behaves exactly
as its own memo said it would, in every window that memo addressed, should not be read as a failure
because the one metric computed over it cannot distinguish "costs a little, most of the time" from
"is worthless."

**Recommendation: promote — retain the card, and flag the median-based ranking (alongside the
DEFECTS.md entries) as inadequate for cards with an explicitly convex or insurance-shaped exposure
profile.** Retiring c04 on the strength of an 18th-of-19 median rank would be discarding the one card
in the field whose worst-window behaviour (`gfc`, +26.03% adjusted excess against a −56% benchmark)
is the largest single result of any kind reported this round, on the metric the program itself deems
correct, in favour of ranking logic that was never built to see it.

**Most valuable variant to test next round:** the memo's own correlation matrix shows `SPY`/`EFA` at
0.86 — a near-redundant pair, by the same logic the memo used to drop `IEF` for its 0.91 correlation
with `TLT`. Swapping `EFA` for a genuinely uncorrelated fifth exposure (a broad commodities proxy, not
already represented by `GLD` alone) would test whether the crisis payoff scales with the number of
truly independent trending legs, or whether `SPY`/`EFA` is quietly running as three effective legs
wearing four labels — without changing the parameter count, the discipline, or any of the mechanism
that performed as designed this round.
