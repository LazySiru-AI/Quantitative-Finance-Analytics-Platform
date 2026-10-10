# Round 19 — quantifying the contribution harness's optimism

Run 2026-08-30. Not investment advice.

**On the pre-registration.** This round tests a prediction that was already committed, by round 16, in
its own follow-up: *"give `contributions.simulate` a settlement lag, not just a cash cap, and re-run
this comparison. The prediction to write down first is that the gap closes materially."* That
sentence is the pre-registration, it predates this measurement, and it is in the committed record at
`data/rounds/r16-2026-08/SELECTION.md`. **I did not add a further prediction of my own before
running** — the honest description is that I built the instrument round 16 specified and ran round
16's test, not that I designed a new one.

---

## 1. The question, and why it was the top of the list

Round 15 stamped every savings and Roth figure `cash_constraint_modelled: false`, on the argument that
the harness affords rebalances a real account sometimes cannot. It called those figures
"systematically optimistic" and no document quantified by how much. That caveat has ridden on roughly
a dozen strategy concepts — all of `SAVINGS-FAMILY`, `ROTH-MOMENTUM` and `ROTH-VOLTARGET` — ever
since, and it was named in the repository itself as "the single highest-value follow-up".

Round 16 built a cash constraint and measured it as worth **nothing**: zero underfunded buys across
all 31 contribution cells, mean drag +0.000pp. Its follow-up established why — the constraint it built
executes every sell before any buy and lets the proceeds fund them in the same session, so it is
settlement-free by construction and can never bind. Meanwhile the real engine rejected **59** orders
on the same card, all `insufficient_cash`, with fractional shares enabled and every friction zeroed.

So the outstanding question was never "does a cash cap matter" — round 16 answered that. It was
whether **settlement** is the term that separates the harness from the engine.

## 2. What was built

`contributions.simulate` gains `settlement_days`, defaulting to `0`, which is a true no-op.

A sale still credits `cash` — the money exists — but is recorded as unsettled until its settlement
date, and **every buy, the contribution pre-buy as well as the breach rebalance, is capped at settled
cash**. A deposit is settled on arrival; only proceeds wait.

The settlement date comes from `app.paper.paperbroker._add_business_days`, **imported rather than
reimplemented**. The two modules must agree on when a sale settles or a comparison between them
measures two settlement calendars instead of the thing under test. It is a private name and importing
it is a deliberate coupling — the alternative is a copy that drifts silently, which is precisely the
class of failure this round exists to close.

Tests: `tests/test_contributions.py`, 30 passing (25 existing untouched, 5 new). Two of the new ones
are about the scenario rather than the mechanism: a synthetic series whose sleeves drift gently is
funded entirely from deposits and reports zero underfunded buys at any lag, which looks like a passing
test and proves nothing — so the binding test forces a genuine sell-to-buy rebalance and asserts that
the same-session cap does *not* bind while T+1 does.

## 3. The result — round 16's prediction is refuted

Same card, window, capital and zeroed frictions as `r16_fill_lag.py`. The engine runs at
`default_mandate`'s `settlement_days=1`.

| | ending | underfunded | gap to engine |
|---|---:|---:|---:|
| `run_allocation` (engine), 59 rejections | 86,547.09 | — | — |
| harness, settlement off *(round 16's number)* | 85,942.19 | 0 | −0.6989% |
| harness, `cash_constrained` only | 85,942.19 | 0 | −0.6989% |
| **harness + T+1 settlement** | **85,797.47** | **2** | **−0.8661%** |
| harness + T+2 settlement | 85,818.21 | 4 | −0.8422% |

**Settlement binds — and moves the harness 23.9% further from the engine, not closer.** The mechanism
is real (2 underfunded buys at T+1, 4 at T+2, against 0 for the same-session cap, exactly as round
16's diagnosis predicted it would behave) and it is *not* the term that explains the gap.

**The instrument is verified.** The engine reproduces round 16's `86,547.09` and the settlement-off
harness its `85,942.19`, both to the cent, asserted in `round19.py` rather than eyeballed. So this is
a refutation of the prediction, not a measurement of drift between the rounds.

## 4. The quantified answer, and it inverts the caveat

Taking the two candidate mechanisms together, on the one cell where the harness can be checked against
the real engine at all:

| term | worth |
|---|---|
| the cash cap | **0.000pp** across 31 cells (round 16) |
| settlement, T+1 | **−0.17pp** on this cell — and in the wrong direction |
| the residual harness/engine gap | **−0.70%**, unexplained |

**The harness ends 0.70% *below* the engine, not above it.** On this card and window it is not
optimistic at all; it is pessimistic, and the two mechanisms nominated to explain its optimism account
for none of the gap and one of them makes it worse.

**The reason matters more than the number.** The window is 2022-08-23 to 2022-12-30 — a falling
market. The rebalances the harness could afford *lost money*, so being able to afford them hurt, and
the engine's 59 rejections helped it. Round 15's caveat assumed the bias had a direction. It does not:
**the sign of the bias depends on whether rebalancing paid in that window**, which is a property of
the regime, not of the harness.

That is a materially different caveat from the one carried since round 15, and it is the answer to the
question that was asked.

## 5. What this does not settle

- **One card, one window.** Round 15's claim covers roughly a dozen concepts across three families;
  this measures one allocation card over 91 sessions. It is the only cell with a validated
  engine-side counterpart, which is why it is the one measured — but "the harness is pessimistic" is
  established here for this cell and nowhere else. The regime-dependence argument in §4 predicts the
  sign should flip in a rising window, and that is testable and untested.
- **The residual is still unexplained.** Two suspects are now eliminated by measurement rather than
  argument: the fill convention (round 16, made the gap 1.9% worse) and settlement (this round, 23.9%
  worse). Both were the leading candidate when nominated.
- **The next suspect, with the evidence that nominates it: turnover.** The engine rejects 59 orders
  across 91 sessions; the harness performs **2** rebalances in the same window. Those are not two
  implementations of one process differing at the margin — they are two processes trading at
  completely different frequencies. A band-breach harness rebalancing twice cannot be reconciled with
  an engine attempting orders on most sessions by adjusting a cash rule, and no further refinement of
  the funding model is likely to close a gap that turnover explains. That is where the next
  measurement should go.

## 6. What changes in the record

Nothing measured is restated. `settlement_days` defaults to `0` and every round-15 and round-16 figure
reproduces exactly, asserted field-by-field in the tests and to the cent in `round19.py`.

What changes is the **caveat**. `cash_constraint_modelled: false` remains literally true, but the
gloss it has carried — that the savings and Roth figures are therefore biased optimistic — is not
supported. On the only cell where it can be checked, the bias runs the other way, and its sign appears
to be a property of the window rather than of the harness.

---

## 7. Amendment, 2026-08-30 — this round's refutation was measuring a defective engine

§5 nominated turnover as the next suspect: 59 engine rejections across 91 sessions against 2 harness
rebalances. Reconciling that found `DEFECTS.md` **D8** — `_rebalance_moves` could emit a
band-breaching buy with nothing sold to fund it, so the engine submitted orders it could not pay for
and resubmitted them every session. The 59 rejections were two rebalance episodes retried, not 59
events, and the engine had effectively stopped rebalancing.

With D8 fixed under `ROUND-20-PLAN.md`, the same comparison reads:

| | before the D8 fix | after |
|---|---:|---:|
| engine rejections | 59 | **3** |
| engine ending | 86,547.09 | **85,746.40** |
| harness vs engine, settlement off | −0.6989% | +0.2283% |
| **harness vs engine, both at T+1** | **−0.8661%** | **+0.0596%** |

**§3's headline is withdrawn.** This round reported that settlement made the gap 23.9% worse and
concluded settlement "is not the term". Against a fixed engine, T+1 settlement closes **73.9%** of the
gap — settlement *is* a material term, and round 16's original prediction was right. This round
measured correctly and concluded wrongly, because the engine it measured against could not rebalance.

**§4's headline survives, with its magnitude cut.** The harness is no longer 0.70% pessimistic; it is
**0.06% optimistic**, which is the direction round 15 claimed and a magnitude far too small to be the
"systematically optimistic" bias that caveat implied. The regime-dependence argument stands and is
still untested in a rising window.

Nothing in §2 changes: `settlement_days` remains a no-op at `0`, and the harness figure is unchanged
at 85,942.19 — asserted, because the D8 fix does not touch `contributions.simulate`.