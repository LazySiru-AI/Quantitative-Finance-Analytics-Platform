# The drawdown ladder, re-expressed on Roth-disjoint tickers

**Not investment advice.** Simulated results on stored price history. I am not a licensed financial
adviser and none of this is a recommendation about real capital.

Backtester: `strategy-program/tools/roth_disjoint.py`. Reuses the settled state machine from
`strategy-program/tools/drawdown_ladder.py` and `backend/app/tournament/ladder.py`, and the
contribution-funded harness from `strategy-program/tools/contributions.py`. Card:
`backend/app/paper/library/ladder/sso-vig-bnd.json`.

---

## 1. The problem this shard answers

The drawdown ladder (`strategy-program/DRAWDOWN-LADDER.md`) trades QLD, SCHD and IEF. Those are
also exactly the tickers a taxable momentum or income strategy is most likely to want. That
collision is disqualifying for a Roth IRA, and the reason is sharper than tidiness:

An ordinary wash sale merely **defers** a disallowed loss into the replacement lot's basis — you get
it back eventually, on a later disposal. **Rev. Rul. 2008-5 makes the IRA case strictly worse**: if
the replacement is bought inside a traditional or Roth IRA within the 61-day window, the loss is
still disallowed, but there is **no basis adjustment anywhere**. It is not deferred, it is destroyed.
`backend/app/tax/washsale.py`'s own module docstring states this at length and keeps
`permanently_disallowed` separate from `deferred_disallowed` for exactly this reason — the two must
never be summed, because they are not the same kind of loss.

That machinery is **detective, not preventive**. It reports the damage after a trade already
happened. `strategy-program/THREE-PURPOSES-PLAN.md` §6 states the cheaper fix as an invariant: no
symbol a Roth card trades may appear in the universe of any taxable card. Today nothing enforces
that invariant except not colliding in the first place, and the shipped ladder collides on all three
of its traded sleeves.

This document asks one question: **can the ladder be re-expressed on tickers that satisfy that
invariant, and what does it cost to do so?**

## 2. Necessary, not sufficient — read this before the numbers

**Ticker disjointness is a necessary condition, not a sufficient one.** IRC §1091 disallows a loss
replaced by a **substantially identical** security, a term the statute does not define, and the IRS
has never ruled on ETF pairs of the kind swapped in here. Two different tickers can still be
substantially identical — a fund and a share class of the same fund, or arguably two 2× funds
tracking the *same* index under different names. Ticker disjointness is the check that is mechanical
and cheap to run; whether a given substitute is *economically* distinct enough to survive an IRS
challenge is a judgement, not a fact this backtest — or any backtest — can settle.

**This document does not establish that any substitution below is safe.** It establishes that the
tickers differ, argues why each pair is a plausible economic substitution rather than a relabelling,
and is explicit about where that argument is weakest. Section 4 states the same-index/different-index
classification for every sleeve; none of the three below is a same-index relabelling, but one (the
bond sleeve) is a narrower economic change than the other two, and that is said outright rather than
left for the reader to notice.

## 3. Verified bar coverage

Checked directly against the live store with `duck.read_bars`, not assumed:

| symbol | first session | last session | role |
|---|---|---|---|
| SPY | 1993-01-29 | 2026-08-21 | signal, both variants (read only, never traded) |
| QLD | 2006-06-21 | 2026-08-21 | leveraged, original |
| SCHD | 2011-10-20 | 2026-08-21 | defensive, original |
| IEF | 2002-07-30 | 2026-08-18 | bond, original |
| SSO | 2006-06-21 | 2026-08-11 | leveraged, disjoint substitute |
| VIG | 2006-05-02 | 2026-08-18 | defensive, disjoint substitute |
| BND | 2007-04-10 | 2026-08-18 | bond, disjoint substitute |

**Wanted and not found in the store** (all read back empty via `duck.read_bars`, so none were
usable): VYM, HDV, SPYD, SDY, NOBL, DGRO (dividend-ETF alternatives to SCHD/VIG); IEI, GOVT, VGIT,
VGLT, EDV (Treasury-duration alternatives to IEF); SPXL (a 3× S&P 500 alternative to SSO). UPRO (3×
S&P 500) does have bars, from 2009-06-25 — considered and rejected in favour of SSO purely because
SSO's 2× leverage factor matches QLD's own and its history starts three years earlier, both of which
matter more to this comparison than the extra leverage would.

**SCHD is the binding constraint on the shared comparison window.** Its 2011-10-20 start is later
than every other symbol on either side, original or substitute, so it — not any substitute ticker —
is what keeps this backtest out of 2008. See §6.

## 4. The substitution, sleeve by sleeve

| role | original | substitute | same index or different? |
|---|---|---|---|
| signal (untraded) | SPY | SPY (unchanged) | n/a — never bought or sold, carries no wash-sale exposure regardless of account |
| leveraged | QLD — 2× Nasdaq-100 (ProShares) | SSO — 2× S&P 500 (ProShares) | **different index.** Same leverage factor, same fund family, different underlying benchmark entirely — a tech-heavy growth index swapped for the broad market. This is the strongest of the three substitutions on economic-substance grounds; the weakest point of *this one* is that both funds share a sponsor (ProShares), which has no bearing on §1091 (which asks about the security, not the issuer) but is worth naming as the thing a skeptical reader would ask about first. |
| defensive | SCHD — Dow Jones U.S. Dividend 100 Index (Schwab) | VIG — S&P U.S. Dividend Growers Index (Vanguard) | **different index.** Different provider and a different selection philosophy: SCHD screens for a blend of yield and quality; VIG screens for a record of dividend *growth*, which tilts toward different constituents (more growth-oriented, historically lower current yield). This is a real strategy difference, not a spelling difference. |
| bond | IEF — ICE U.S. Treasury 7-10 Year Index (iShares) | BND — Bloomberg U.S. Aggregate Bond Index (Vanguard) | **different index, and the weakest of the three.** BND is not merely a different duration bucket of the same collateral — it adds investment-grade corporate and mortgage-backed exposure IEF does not have at all, so the two funds carry different credit risk as well as different duration. That is a genuine change of what is being held. The honest caveat: an aggregate-bond fund's duration (BND: roughly 6 years) sits closer to IEF's (roughly 7-8 years) than a genuinely short- or long-duration alternative would, so *some* of the difference between these two funds' return series is still "similar-duration Treasuries" rather than "credit exposure" — the credit exposure is real but it is not the whole story, and a more aggressive reader could reasonably argue this pair is the closest of the three to the line. |

Every rung, the confirmation window, the recovery rule and the fund-draw-down order (bond before
defensive) are held **identical** between the two variants — see `strategy-program/tools/
roth_disjoint.py`'s own `RUNGS`/`CONFIRM_MA`/etc. constants. The point of this backtest is to isolate
the cost of the ticker substitution alone; changing the rule at the same time would confound that
with the cost of changing the strategy, which is a different question.

## 5. Method

Contribution-funded at **$7,500 once a year** (the 2026 Roth limit, from `contributions.py`'s own
`ANNUAL_CONTRIBUTION`), lump-summed each January — deliberately the harder test than monthly
dollar-cost averaging, per that module's own reasoning. Both money-weighted IRR ("how did the
account holder do") and time-weighted CAGR ("how did the strategy do") are reported, because
contribution funding inverts sequence risk relative to a lump sum and quoting only one of the two is
the easiest mistake available here — `contributions.py`'s own module docstring says so at length.

Slippage: **5 basis points, one way, on every dollar actually traded.** An ETF's stored close is
already net of its own expense ratio, so the only real, un-modelled cost of running this strategy is
the cost of the rebalance trades themselves — the same convention and the same rate every backtest
tool in this programme uses (`drawdown_ladder.py`, `roth_voltarget.py`, `allocation_family.py`).

Window: the **longest span every symbol on both sides shares at once** — 2011-10-20 through
2026-08-11, 3,722 sessions, 14.77 years. Bound below by SCHD's own first stored session (§3) and
above by SSO's own last one.

## 6. Why 2008 is not in this backtest

Both variants need SCHD's history to run the "original" side of the comparison at all, and SCHD does
not exist until 2011-10-20 — four years after the substitute's own bond sleeve (BND, 2007-04-10) and
five after its leveraged and defensive sleeves (SSO/VIG, both mid-2006). The substitute side alone
could reach back to 2007; the comparison cannot, because there is no "original" ladder to compare it
against before SCHD started. `strategy-program/DRAWDOWN-LADDER.md` solved the identical problem by
substituting SPY for SCHD in its own crisis-window test; doing that again here would mean comparing
the *substitute's real defensive sleeve* against the *original's proxy* defensive sleeve, which
measures something other than the ticker substitution this document is about. Per this task's own
instruction — 2008 if the symbols reach it, otherwise 2020 and 2022 — both slices below sit inside
the shared window and are reported from it directly.

## 7. Results

```
                                      balance     paid in    mult      IRR      TWR    maxDD    MAR  rebal
original (QLD/SCHD/IEF)          $    326,967  $  120,000   2.72x   11.59%   10.60%    -23.4%   0.45    18
disjoint (SSO/VIG/BND)           $    272,225  $  120,000   2.27x    9.56%    8.88%    -24.5%   0.36    14
```

| | original (QLD/SCHD/IEF) | disjoint (SSO/VIG/BND) |
|---|---|---|
| final balance on $120,000 contributed | $326,967 | $272,225 |
| money-weighted IRR | 11.59% | 9.56% |
| time-weighted CAGR | 10.60% | 8.88% |
| contribution-adjusted max drawdown | −23.4% | −24.5% |
| MAR | 0.45 | 0.36 |
| rebalances | 18 | 14 |

### Severity slices

| | original, period return / max DD | disjoint, period return / max DD |
|---|---|---|
| **2020** (COVID crash and recovery) | +24.27% / −19.46% | +19.84% / −20.18% |
| **2022** (rate-driven bear market) | −15.71% / −23.42% | −14.20% / −24.52% |

Max drawdown in each slice is measured against the account's own running contribution-adjusted
high-water mark carried in from before the slice began, not reset at the slice boundary — the
ladder's armed state going into 2020 or 2022 is itself a consequence of what happened before either
year, and a cold restart would answer a different question ("how does a freshly switched-on strategy
behave here") than the one asked.

## 8. The cost of the substitution, as a number

| measure | cost |
|---|---|
| final balance | **−$54,742** (−16.7% of the original's own ending balance) |
| money-weighted IRR | **−2.02 percentage points** (11.59% → 9.56%) |
| time-weighted CAGR | **−1.72 percentage points** (10.60% → 8.88%) |
| contribution-adjusted max drawdown | **−1.10 percentage points deeper** (−23.4% → −24.5%) |
| MAR | **−0.09** (0.45 → 0.36) |

This is a real cost, not noise. Over 14.77 years and $120,000 contributed, giving up ticker overlap
with a taxable account costs roughly two percentage points of annual return on both the IRR and CAGR
measures, a slightly deeper drawdown, and a fifth of the strategy's risk-adjusted edge (MAR falls
about 20% relative, from 0.45 to 0.36). It is not catastrophic — the disjoint version still earns a
positive MAR well above 1×buy-and-hold's typical range and still multiplies contributions by 2.27× —
but it is not free, and reporting it as free would be the wrong finding to hand back.

## 9. What this does not test

- **The sample is one 14.77-year window with two named crisis years inside it**, exactly the
  "still small" caveat `DRAWDOWN-LADDER.md` §7 already gives for the strategy this document
  re-expresses. Nothing here adds a second independent crisis.
- **Every window here is in-sample.** All price history used predates this document's own writing
  date and the original card's own `designed_through`; nothing here is a forward test.
- **The §1091 argument in §2 and §4 is this author's judgement, not a ruling.** A tax professional
  reviewing the specific fund pairs before any real capital moves is the actual safeguard here, not
  this document.
- **Correlation between each original/substitute pair was not measured directly.** The case in §4 is
  made from index methodology and holdings composition, not from a computed correlation coefficient
  between the two return series — that would be a reasonable next check and is not done here.

## 10. Whether the Roth can hold this strategy on disjoint tickers

**Yes, mechanically — the substitution runs, validates as a `LadderCard`, and produces a materially
similar strategy on every ticker disjointness actually requires.** The honest qualification is that
"can" and "should" are different questions here. The disjoint version gives up about two points of
annual return and a fifth of its risk-adjusted edge relative to the original, in exchange for
eliminating a wash-sale-destruction risk that the original version carries in full on all three of
its traded sleeves. That is a real trade-off for the account owner to make, not a problem this
document can resolve on their behalf — and the bond-sleeve substitution (§4) is the one place in this
package where a more conservative reader might reasonably want a second opinion before relying on it.
