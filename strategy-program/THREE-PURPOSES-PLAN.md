# Three purposes: restructuring the competition, the desk, and the scoring

**Not investment advice.** Simulated books on a paper account. I am not a licensed financial adviser
and none of this is a recommendation about real capital.

**Written 2026-08-22, before any of it is built.** Section 8 stages the work and says what is
executed now and what is deferred.

---

## 1. The three purposes

| | **Savings** | **Trading** | **Roth** |
|---|---|---|---|
| funding | $20,000 seed, then **$1,000/month** (possibly $500) | **$50,000 once**, no additions | **$7,500 once a year** (the annual limit) |
| horizon | 10–20 years | *unbounded* | long, and never taxed on the way out |
| tax treatment | `taxable` | `taxable` | `roth_ira` |
| what it is for | a savings portfolio that compounds | trend and swing trading on rules | tax-free compounding of the allocation strategies |
| symbols | shared pool | shared pool | **disjoint from the other two** |

Each is a different question. Nothing in the programme today distinguishes them.

**Trading has no horizon bound, and that is a decision rather than an omission.** The owner declined
to set one, so nothing in the scoring may treat three years as a limit. A purpose whose horizon is
unstated is not the same as one whose horizon is short, and encoding a large number that pretends to
be a bound would be worse than leaving it open.

**Amounts and dates here are configured, not defaults.** Trading is $50,000. The paper desk's
inception moves to 2026-08-15 (§7), which restarts the forward record.

## 2. Why one leaderboard cannot rank all three

The competition scores every card on **lump-sum adjusted excess over regime windows**. That is the
right basis for exactly one of the three purposes, and the wrong one for the other two — and this
programme has already measured how wrong.

**Contribution funding inverts sequence risk.** A lump-sum investor fears a crash at the end, when
the balance is largest; a contributor is *helped* by a crash early, because the same dollars buy
more. `strategy-program/ROTH-MOMENTUM.md` measured the gap directly: QLD through the 2006–2011
crisis returns a money-weighted **IRR of 10.70%** against a time-weighted **CAGR of 2.29%**. An
8.4-point spread on one strategy in one window, produced entirely by *when the money arrived*.

So a savings card ranked on lump-sum excess is being scored on a question its owner will never ask.

**And the two numbers must never share a column.** `data/rounds/r12-2026-08/ROTH-CANDIDATES.md`
already states this: an IRR and an `adjusted_excess` are different quantities, and ranking them
together is a category error, not a rounding one.

**A second, sharper reason.** Round 12's own feasibility check found that **10 of 21 ladder windows
are shorter than a long-lookback strategy's own signal period**, so the rule never activates and the
book holds its fallback sleeve start to finish. Those cells measure the fallback, not the strategy. A
savings mandate is *made* of long-lookback strategies. Scoring it on the trading matrix would produce
a table that looks complete and measures nothing — the same shape as `DEFECTS.md` D5.

## 3. What this dissolves

Rounds 8 through 12 were one long argument about **distinctness** — discipline caps, base-family
caps, holdings overlap — and three of the last four ended with the owner overriding the rule.

Much of that fight was one roster being asked to serve several purposes implicitly. A savings card
and a swing-trading card do not compete for the same seat, so they never needed to be distinct from
each other. Splitting by purpose removes the pressure that produced the overrides, rather than
tuning the rule that mediated it again.

**It does not dissolve all of it.** Within the trading purpose, `B3-concentrated` and `B-momentum`
still hold four of the same six names, and round 12's holdings rule still decides that. Purpose
separation makes the question smaller; it does not answer it.

## 4. Naming: `Purpose`, not `Mandate`

`backend/app/paper/mandate.py` already defines `Mandate` — the paper desk's capital and risk
constraint set (`starting_cash`, `max_positions`, slippage, fees). It is unrelated and it is load-
bearing. The new concept takes the owner's own word, **purpose**, and the two never collide.

## 5. The data model

```python
class Purpose(StrEnum):
    SAVINGS = "savings"     # monthly contributions, 10-20 years, taxable
    TRADING = "trading"     # one lump sum, under 3 years, taxable
    ROTH    = "roth"        # annual contributions, long horizon, tax-free, disjoint symbols
```

A `PurposeSpec` carries what each one *is*: funding shape and amount, horizon, the benchmark it is
measured against, its tax treatment, and whether its symbols must be disjoint from the others.

**`purpose` becomes a field on all three card models**, not a sidecar. It decides *how a card is
scored*, which is far too load-bearing to sit in an unvalidated file beside the card — and the
`provenance.json` precedent exists precisely because that data was advisory. This one is not.

The three card models (`StrategyCard`, `AllocationCard`, `LadderCard`) are separately frozen with
`extra="forbid"` and share no base class, so this is three parallel edits. **The field defaults to
`Purpose.TRADING`**, which is what every existing card actually is, so no existing card JSON changes
and no existing test breaks on validation.

## 6. Symbol disjointness — the wash-sale invariant

**This is the one genuinely new safety property, and the reason it matters is sharper than
tidiness.**

An ordinary wash sale *defers* a loss into the replacement lot's basis; you get it back eventually.
**A replacement bought inside an IRA destroys the loss outright** — Rev. Rul. 2008-5, no basis
adjustment anywhere. `backend/app/tax/washsale.py` already models this correctly, separates
`permanently_disallowed` from `deferred_disallowed`, and refuses to sum them.

But that machinery is **detective, not preventive**: it reports the damage after the trade. Nothing
anywhere stops a Roth strategy and a taxable strategy from naming the same ticker in the first place.

The invariant:

> **No symbol traded by a `roth`-purpose card may appear in the universe of any `savings`- or
> `trading`-purpose card.**

Enforced as a check over the whole library, surfaced as a test, and reported by name — "these two
cards both trade QLD, and one of them is in the Roth" — rather than as a boolean.

**What this deliberately does not claim.** §1091 turns on *substantially identical* securities, not
identical tickers. QLD and QQQ are not the same security but a 2× fund on the same index is not
obviously "not substantially identical" either, and the IRS has never ruled on ETF pairs of that
kind. Ticker disjointness is a **necessary condition that is easy to check, not a sufficient one**,
and the plan says so rather than implying the check makes the account safe.

## 7. What changes where

**Scoring basis per purpose.** Trading keeps lump-sum `adjusted_excess` over regime windows.
Savings and Roth are scored on the contribution harness (`strategy-program/tools/contributions.py`),
reporting money-weighted IRR *and* time-weighted CAGR, because quoting only the flattering one is
the easiest mistake available here.

**Benchmarks per purpose.** Today `PaperDeskState.benchmark` is one global field and
`runner._BENCHMARK` is the string `"SPY"`. A savings book measured against SPY is measured against
the wrong thing; it wants a blended 60/40. Nothing in the codebase composes more than one symbol into
one return, so **a blended benchmark is new code**, not a parameter.

**Inception moves to 2026-08-15.** The desk has been running from 2026-01-01 with $100,000 per
card; the purposes restructure it onto real funding, so the forward record restarts rather than
carrying a number produced under different rules.

**The cost is that the desk becomes nearly empty**, and it should be said out loud rather than
discovered: with the latest stored bar at 2026-08-21 that is a handful of sessions, and a return
over a handful of sessions is noise. The desk stops being evidence about anything for months.

**What it does *not* touch is the competition.** Rounds 11 and 12 measure the out-of-sample window
2026-02-17 to 2026-08-18, which is derived from the design cutoff and written as literal dates — not
from the desk's inception. Every gate, ranking and selection figure in those rounds is unaffected.

**The desk becomes three books.** `PaperDeskState` is flat today — one `starting_cash`, one
`inception`, one `desks` list. Three books need a `books` wrapper, each carrying its own funding,
inception, benchmark and desks. Starting capital and inception are currently constants in `desk.py`,
not settings; per-purpose funding makes them per-book data.

> **Updated 2026-08-23, after this plan was written.** Half of that paragraph has since been done.
> `desk.INCEPTION` moved to 2026-08-15, and `desk._mandate` no longer holds a starting-capital
> literal at all — it reads `PURPOSE_SPECS[Purpose.TRADING].seed`, so the desk trades the trading
> purpose's own $50,000 rather than a flat $100,000 that happened to agree with nothing. That is one
> book sourced from purpose data, not three books; the `books` wrapper, per-book benchmarks and the
> per-card `purpose` lookup are still ahead. Recorded here rather than by rewriting the sentence,
> because a plan that silently updates itself stops being a record of what was planned.

**`library/allocation/` is orphaned.** No loader reads it — not `results.py`, not `jobs.py`, not
`desk.py`. The allocation cards already committed there are unreachable. Any purpose that seats an
allocation card needs that path built.

## 8. Staging, and what is executed now

**Stage 1 — the model and the invariant.** `Purpose`, `PurposeSpec`, the `purpose` field on all three
card models, and the disjointness check with its tests. Additive and backward-compatible: nothing
changes shape, no existing card or test breaks.

**Stage 1 also — candidates for the two purposes that have none.** The savings purpose has no cards
at all; the Roth purpose has the ladder, whose tickers currently overlap whatever taxable strategies
hold. Both need designing and backtesting on the right basis.

**Stage 2, deferred — the desk restructure.** Three books changes the response shape, breaks the
roster tests deliberately, and needs per-book funding and blended benchmarks. It is a bigger change
than everything in stage 1 combined and it should not ride along with the model work.

**Stage 3, deferred — per-purpose competition and selection.** Three leaderboards, three gate sets,
three rosters. Depends on stage 2's shape.

Doing stage 1 first is not caution for its own sake: the disjointness invariant is the piece with a
real-money consequence attached, and it does not need the desk restructure to be useful.

## 9. Risks and open questions

- **Monthly $1,000 against $500 is a real fork**, not a detail. At a 10-year horizon the contribution
  stream dominates the terminal balance, so a strategy ranked at one rate may not rank at the other.
  Both should be reported until the owner picks.
- **The savings purpose's symbols overlap the trading purpose's by design** (both taxable), which
  means the *trading* book can create wash sales against the *savings* book — deferred, not
  destroyed, so it is a smaller problem than the Roth one, but it is not zero and nothing checks it.
- **A card's purpose is declared, not derived.** Nothing stops a card declaring `savings` and trading
  like a swing strategy. The purpose decides the scoring basis, so a mis-declared card is scored on
  the wrong question — and no test can catch that, only a reader.
- **The Roth cannot hold the ladder as it stands** if the taxable books trade QLD, SCHD or IEF. Either
  the Roth's ladder is re-expressed on disjoint tickers, or the taxable books give those up.

> **Updated 2026-08-24, after this plan was written.** The owner set the three purposes' opening
> capital: trading $100,000, savings $20,000 (unchanged from section 1's table), and roth a $30,000
> seed (this document's section 1 table names none for roth; the $30,000 is an existing IRA balance
> the account already carries, and the $7,500/year contribution continues on top of it rather than
> being the account's only funding). Trading's $100,000 is this plan's own original figure —
> `PurposeSpec.seed` had been moved to $50,000 by the owner on 2026-08-23 (see this section's own
> 2026-08-23 note above), and this instruction reverts that, back to what section 1's table always
> said. `backend/app/tournament/purposes.py` and `backend/app/paperdesk/desk.py` carry the code-side
> detail and history of all three figures. Recorded here rather than by rewriting the sentences
> above, for the same reason the 2026-08-23 note gives: a plan that silently updates itself stops
> being a record of what was planned.
