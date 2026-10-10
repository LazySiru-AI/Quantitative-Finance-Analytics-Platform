# Round 15 — three accounts, three scoring bases

**Not investment advice.** Simulated books on a paper account. I am not a licensed financial adviser
and none of this is a recommendation about real capital.

**Pre-registered 2026-08-24, before any round-15 run exists.** Every figure quoted below is a
property of the cards, the engine source, or the bar store — never of a round-15 result. Where a
number comes from an earlier round it is attributed to that round.

---

## 1. What this round is actually asking

Every one of the fourteen rounds so far has scored a single kind of account: a lump sum, taxable,
with no contributions and no horizon. All 54 scored agents across every committed round are
`purpose="trading"` cards. That was never a decision — it is what the engine could express.

A real investor does not have one account. The programme models three, with materially different rules:

| account | opening capital | funding after inception | tax treatment | ticker constraint |
|---|---|---|---|---|
| Savings | $20,000 | $1,000/month (variant: $500) | taxable | none |
| Trading | $100,000 | none — lump sum | taxable | none |
| Roth IRA | $30,000 | $7,500/year | Roth | **disjoint from the taxable books** |

So round 15 asks one question, and it is not "which strategy is best":

> **Does the funding shape of an account change which strategy should sit in it?**

That is a question the programme has never been able to ask, and the answer has a real consequence:
if the ranking is stable across funding shapes, one leaderboard was sufficient all along and the
three-purpose split is bookkeeping. If it inverts, then fourteen rounds of "best card" have been
answering for an account shape that covers a third of the modelled capital.

## 2. Why the existing engine cannot answer it, and what has to be built first

This is the honest blocker, stated before any design, because the design is shaped entirely by it.

**(a) Allocation and ladder results are not readable by the scorer.** `AllocationResult`
(`backend/app/tournament/allocation.py:396`) and `LadderResult` (`ladder.py:373`) are field-for-field
identical to `AgentResult` (`models.py:280`) but are separate pydantic models. `isinstance` is
`False`, and `AgentResult.model_validate_json` rejects their `"card"` payload outright. Every
round-15 candidate is an allocation or ladder card. **Nothing in `results.py` or `score.py` can load
a single one of them today.**

**(b) `capital_exposure` means two different things.** For a `StrategyCard` it is
`entry_notional / starting_equity`, fixed when the trade opens. For an allocation book it is
`invested_value / current_equity` averaged over sessions — which for a continuously-invested sleeve
book is always near 1.0. The programme's primary rank key is

    adjusted_excess = corrected_return - (capital_exposure * benchmark_return)

and feeding an allocation book's ≈1.0 into that formula does not produce a wrong-ish number, it
produces a different metric wearing the same name. `ALLOCATION-FAMILY.md` already flags re-deriving
this convention as undone work.

**(c) Nothing can score a contribution stream from a card.** `contributions.py::simulate` is the only
harness in the repository that models a monthly or annual deposit, and the only money-weighted IRR
implementation anywhere in `backend/`. Its signature takes a `WeightFn`:

    WeightFn = Callable[[int, Mapping[str, Sequence[float]]], dict[str, float]]

a hand-written Python closure over float price series. It cannot take an `AllocationCard`. Every
existing savings and Roth study — `roth_matrix.py`, `savings_family.py`, `allocation_family.py` —
supplies a hand-written factory instead. Those studies are therefore **not frozen cards**, and under
`PROTOCOL.md` §2 a thing that is not frozen is not a round entry.

### The bridge, pre-registered as round 15's first deliverable

Two adapters, both additive, neither touching `AgentResult`:

1. **`ScoredRun` reader** in `results.py` — parses any of the three run-file shapes and normalises to
   one view carrying an explicit `exposure_basis: "entry-notional" | "invested-value"`. Any code
   computing `adjusted_excess` must read that field. A run whose basis is `invested-value` is
   **not** assigned an `adjusted_excess` at all; it is scored on `excess` and reported as such.
   Silence here would be the single most damaging thing this round could ship.

2. **`card_weight_fn(card) -> WeightFn`** — evaluates a frozen `AllocationCard` or `LadderCard`
   against the `closes` mapping `simulate` already passes, so one frozen artifact can be run
   lump-sum through `run_allocation`/`run_ladder_card` **and** contribution-funded through
   `simulate`. The ladder half is close to free: `LadderCard` was ported *from*
   `tools/drawdown_ladder.py`'s `Ladder`, so the state machine already exists in `WeightFn` shape.

**The bridge must be verified before it is trusted.** The acceptance test is not a unit test: run an
existing card (`qld-schd-sgov`) through both paths over one window with contributions set to zero,
and require the two equity curves to agree. If a card scores differently through the bridge than
through the engine, every number in this round is measuring the bridge instead of the strategy.

## 3. Sub-round layout — one directory, three purposes

`build_leaderboard(round_id, rank_by, rounds_root, purpose)` already filters by the card's own
`purpose` field **before** ranking, and `LeaderboardData` already carries `scoring_basis` and
`unscored_reason`. So the three sub-rounds need no new directory convention and no new endpoint:

    data/rounds/r15-2026-08/
      BRIEF.md
      cards/            all three purposes' cards, each carrying its own `purpose`
      results/<window>/runs/*.json      one tree, as PROTOCOL.md §9 requires

`results/<window>/runs/` is a published interface — `/api/competition` reads that exact shape — so
it is not renamed. The sub-rounds are distinguished by the card's `purpose`, which is the mechanism
that already exists, not a new one invented for this round.

### The three sub-rounds

| sub-round | funding | scored on | benchmark |
|---|---|---|---|
| **15-T trading** | $100,000 lump sum | `adjusted_excess`, median over eligible main windows | SPY, and QQQ alongside |
| **15-S savings** | $20,000 + $1,000/mo | money-weighted IRR **and** time-weighted CAGR, both | 60/40 SPY/AGG, and SPY, and QQQ |
| **15-R roth** | $30,000 + $7,500/yr | money-weighted IRR **and** time-weighted CAGR, both | 60/40 SPY/AGG, and SPY, and QQQ |

Both figures are reported for the contribution-funded arms because `PROTOCOL.md` §7 requires it and
because, as `ROTH-CANDIDATES.md` puts it, "quoting only the flattering one is the easiest mistake
available here". IRR and CAGR diverge precisely when sequence risk bites, which is the thing a
contribution schedule exists to create.

**A savings sensitivity arm runs at $500/month.** `PURPOSE_SPECS[SAVINGS].contribution_variants`
already carries `Decimal("500")`, so this is a declared variant, not a new parameter. Its only job is
to answer whether the ranking is stable to drip size. If the ranking inverts between $500 and $1,000
on the same cards over the same windows, then neither ranking is a property of the strategies.

### The benchmark gap

`benchmarks.REGISTRY` holds exactly two blends, `spy` and `60-40-spy-agg`. **There is no QQQ blend.**
One is added as a prerequisite. It is a single-leg blend at weight 1, the same shape as `spy`.

Round 5 already measured why QQQ matters as a second yardstick: it compounded at +18.56%/yr against
SPY's +12.14%/yr over the decade, which roughly halved the reported edge of every card measured
against SPY alone — `A-rotation`'s 10-year figure fell from +5.28% to +0.63%. A round comparing
leveraged-Nasdaq sleeves against SPY only would be flattering itself by choice of denominator.

## 4. The candidate field

Round 15 is a **purpose-fit** round, not a discovery round. The field is deliberately small and every
entry is an ETF allocation expressed as continuous target weights — no card in this round picks a new
stock. The owner's stated interest is strategies that "rebalance by proportion instead of buying new
names", which is exactly what `AllocationCard` expresses and `StrategyCard` cannot.

### Already frozen, entering as-is

| card | shape | current purpose |
|---|---|---|
| `qld-schd-sgov` | allocation, 3 sleeves, mean-reversion tilts | savings |
| `spy-schd-agg-gld-bil-atr-tilt` | allocation, 5 sleeves, ATR vol tilt | savings |
| `ladder-qld-schd` | ladder, SPY-signal drawdown rungs | trading |
| `ladder-sso-vig-bnd` | ladder, Roth-disjoint tickers | roth |

### New candidates to be authored

Authored against `designed_through` no later than the round's cutoff, then frozen before any run.
The design budget is `PROTOCOL.md` §3's ten parameters, and **no grid search** — a candidate is
argued from a thesis, not selected from a sweep.

The gap `ALLOCATION-FAMILY.md` identifies is that the strongest risk-adjusted variant it found
(continuous vol-targeting at 12%) **cannot be expressed** by `AllocationCard` at all: `TiltRule`
carries a fixed `Decimal shift_pct`, and vol-targeting needs a continuous function of a real-valued
indicator. Round 15 does **not** attempt a fourth card type. Candidates stay inside what the frozen
model can express, and the inexpressible variant is recorded as a finding rather than smuggled in as
an approximation.

Each new candidate must state, in its thesis: what it holds, what makes it move, what would falsify
it, and who is on the other side of the trade.

## 5. Windows

Per `PROTOCOL.md` §5, windows are added and never re-cut. The trading arm uses the existing main
window matrix. The contribution-funded arms need windows long enough for a drip to matter — a
$1,000/month schedule over a 90-day window is a lump sum with extra steps.

**Pre-registered constraint:** a contribution-funded arm runs only on windows of at least three
years, and a card eligible in fewer than three such windows is **unranked**, its numbers published
and excluded from the ranking rather than sorted to the bottom. This mirrors §3's regime gate rather
than inventing a second standard.

**Bar coverage must be checked before the run, not after.** SSO's and BIL's last stored session is
2026-08-11 against SPY's 2026-08-21 — roughly seven sessions stale. `price_blend` raises
`InsufficientHistory` rather than silently repricing over a shorter window, so a stale leg is a hard
failure, which is the correct behaviour and must be resolved by syncing, never by shortening.

## 6. What this round predicts, in advance

Pre-registering the expectation is what makes the result informative rather than a story told
afterwards. Four claims, each falsifiable:

1. **The ranking will not be stable across funding shapes.** Specifically, `qld-schd-sgov` — the
   most volatile candidate, 35% in a 2x-leveraged sleeve — will rank better under monthly
   contributions than under a lump sum, because a drip buys more of a sleeve that has fallen.
   Falsified if its rank is the same or worse in the savings arm than the trading arm.

2. **IRR and time-weighted CAGR will disagree on at least one card by more than 2 percentage
   points**, and the disagreement will be largest for the highest-drawdown card. Falsified if every
   card's two figures agree inside 2 points.

3. **The $500 and $1,000 savings arms will produce the same ordering.** Drip size should change the
   magnitude and not the ranking. Falsified — and it is the more interesting outcome — if the
   ordering inverts, which would mean the ranking is a property of the contribution schedule rather
   than of the strategies.

4. **No candidate will beat QQQ buy-and-hold on raw return over the long windows**, and the case for
   every one of them will rest on drawdown instead. This is what `ALLOCATION-FAMILY.md` found across
   four variants and three windows; round 15 expects to reproduce it. Falsified if any candidate
   beats QQQ on both return and drawdown.

## 7. The control

Every round needs a measurement that must come out at a known value, or the round is unreadable.

**The control for round 15 is the bridge itself:** `qld-schd-sgov` run through `card_weight_fn` with
`annual_contribution=0` and `band_pct` matched to the card, against the same card run through
`run_allocation` over the same window with the same starting capital. The two ending equities must
agree to within rounding.

If that divergence is not effectively zero, **every other figure in this round is unreadable until it
is** — the same standing this round's predecessor gave its own control, which passed at exactly 0.00.

## 8. What this round deliberately does not do

- **It does not re-run rounds 1–14.** Gate A reads round 5; Gate S′ reads rounds 2, 4 and 5; rounds
  6–12 scored over those frozen matrices and two ended in owner overrides argued from specific
  figures in them. Round 15 writes only to its own directory.
- **It does not add a fourth card type.** Vol-targeting and risk parity stay inexpressible and stay
  recorded as such.
- **It does not promote anything.** `PROTOCOL.md` §6 requires two consecutive rounds on differing
  window sets before a candidate moves to base. Round 15 is the first round any savings or Roth card
  has ever run in; nothing can be promoted on one round's evidence, and the round that tries would be
  repeating the error §6(b) was written to stop.
- **It does not claim the Roth substitute tickers satisfy IRC §1091.** `ladder-sso-vig-bnd` holds
  SSO/VIG/BND rather than QLD/SCHD/IEF so the Roth book is disjoint from the taxable ones, because
  Rev. Rul. 2008-5 destroys the loss outright with no basis adjustment anywhere. That the substitutes
  are *not* substantially identical is an argument, not a ruling, and it stays labelled as one.

## 9. Order of work

1. Add the QQQ blend to `benchmarks.REGISTRY`.
2. Sync SSO and BIL bars; re-check coverage for all eleven symbols.
3. Build `card_weight_fn` and the `ScoredRun` reader. **Run the §7 control. Stop if it fails.**
4. Author and freeze the new candidate cards. Commit them before any run exists.
5. Run the three arms, serially — `PROTOCOL.md` §8: never launch a round detached, and never kill a
   run by killing `python.exe`.
6. Score, write `SELECTION.md` and `NARRATIVE.json`, report.

---

**Not investment advice.**
