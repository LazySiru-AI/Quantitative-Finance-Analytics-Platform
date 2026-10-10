# Analyst brief — Strategy Program, round 3

Round 3 asks one question the first two could not: **does a wider universe change the competition's
result?**

Rounds 1 and 2 drew from 173 stored symbols, of which roughly 60 were individual equities and the
rest ETFs. Every card in both rounds was therefore picked from the same thin pool, and the two
strategies that survived to `base/` — `B-momentum` and `C-trend` — are both trend-family books on
overlapping AI, semiconductor and cloud names. That is not obviously a discovery about markets. It
may be a discovery about what was in the store.

The store now holds **633 symbols, 513 of them current S&P 500 and Nasdaq-100 constituents**, and
**380 symbols reach back to 2004** against 86 before. This round measures what that buys.

## 0. What is different from round 2

| | round 2 | round 3 |
|---|---|---|
| symbols available | 173 (≈60 stocks) | 633 (513 index constituents) |
| symbols reaching the GFC | 86 | 380 |
| where the list came from | whatever had been synced | `IVV` and `QQQ` N-PORT filings, price-validated |
| new failure mode | — | survivorship, see §3 |

Windows, scoring, the DSL, the broker, the design cutoff and the eligibility gate are **unchanged**
from round 2. That is deliberate: if the field's results move, the universe is the thing that moved.

## 1. The two arms

**The controlled arm** — `B-wide` and `C-wide`. These are `B-momentum` and `C-trend` with every
field copied byte-for-byte except the universe, which is replaced by a mechanical draw from the wider
store: the top N index constituents by median dollar volume over the design year, restricted to
symbols with history back to 2004, ranked once and frozen. Entry, exit, stop, take-profit, hold cap,
slot count and position size are asserted identical to the base card at build time.

This is the only part of the round that isolates anything. It is also honest about what it isolates:
a twelve-name universe cannot be *widened*, only swapped, so these cards change the universe **and**
the selection method together. They do not measure breadth alone, and no reading of them should claim
otherwise.

Both carry a provenance sidecar declaring `universe_knowable_from: 2026-03-31`, because a
"largest constituents" rule is an explicitly index-derived selection. They are therefore **unranked**
on every window in the matrix. That does not weaken the comparison: the head-to-head against
`B-momentum` and `C-trend` on the same windows is arithmetic, and needs no leaderboard position.

**The open arm** — six analyst-designed cards, free choice across the whole store, one per
discipline. This is the actual competition, and the thing that would show up as "the field got
better" if breadth is worth having.

## 2. What you are optimising for

Unchanged from round 2. Cards are ranked on **median excess, worst-window excess and hit rate
together**, with a Borda composite and an explicit **Pareto frontier** — the set no other card beats
on all three at once. A convex card with a poor median and the best crisis window is a defensible
entry; round 2 placed exactly such a card 17th of 18 on median while it was the best card in the
crisis by seventeen points, which is why the frontier exists.

A card eligible in fewer than **five of the eight** main windows is unranked, not last.

## 3. Survivorship — the new failure mode, and the one to read twice

The constituent list is **today's** membership. Today's S&P 500 contains no Lehman Brothers, no Bear
Stearns, no Washington Mutual, no Countrywide, no GM. Every one was removed *because it collapsed*.

A card whose universe is drawn from that list and then run over `gfc` is not being tested against the
financial crisis. It is being tested against the subset of the crisis's participants that survived
it, and it will look good for a reason that has nothing to do with its rules. The bias does not
appear as an error. It appears as a suspiciously strong backtest.

**The bias is in the selection, not in the data.** The store holding 633 symbols is neutral; adding
history for a company that later failed would *reduce* the problem. What creates it is choosing names
from a list whose membership was decided after the window being tested.

So the gate is scoped to the selection:

- A card that **declares an index-derived selection** inherits `universe_knowable_from = 2026-03-31`
  and is unranked on every window starting before it — which, in this matrix, is all of them.
- A card that selects on **its own reasoning** — a thesis, sector behaviour, liquidity, volatility,
  length of listed history — is not gated, and must state that argument in its thesis where a reader
  can judge it.
- **Survivorship is reported per window either way, sized rather than asserted.** Index turnover runs
  a few percent a year, so a twelve-month window carries a small distortion and an eighteen-year one
  carries a large one. A report that says "the GFC number is flattered by an unknown amount" has told
  the reader something. One that silently blocks the window has told them nothing.

A memo claiming liquidity grounds for twelve names that are transparently the twelve largest index
members will be read as index-derived. See `strategy-program/WINDOWS.md` for the full rule.

## 4. Resist the urge to tune

Unchanged, and still the point of the programme. The tournament preceding round 1 measured rank
correlation between in-sample and blind return at **Spearman ρ = 0.162**. Performance on the data an
author studied predicted almost nothing about performance on data nobody had seen.

The wider universe makes this *worse*, not better: 513 names is a far larger search space, and a
twelve-name book selected from it after looking hard at history is a much easier thing to overfit
than one selected from sixty. Keep the parameter count low, justify every number, and do not scan the
trading windows.

## 5. The data cutoff

`designed_through` is **2026-02-13** and the model refuses a later date. Every read must pass
`end=dt.date(2026, 2, 13)`. Reading past the cutoff is the one disqualifying act.

## 6. Deliverables

One card at `cards/<agent_id>.json` and one memo at `memos/<agent_id>.md`, the memo written before
any result exists. The memo states the mechanism, who is on the other side, the selection argument
including whether it is index-derived, what was measured through the cutoff with real numbers, every
parameter and why, what would falsify the thesis, and a prediction of the card's worst window.

The prediction is scored. An analyst who correctly predicts their own failure mode has understood
their strategy; one whose card fails somewhere they never considered has not.

## 7. What this round cannot settle

Round 3 is **not a walk-forward round**. No calendar time has passed since round 2, so the design
cutoff has not advanced and no genuinely unseen data exists. It widens the choice set; it does not
add new data. The walk-forward begins when real time has elapsed.

And a result showing the open arm beating round 2's field would be consistent with two very different
stories — that breadth helps, or that six analysts searching a larger space found more noise. The
controlled arm exists precisely because it cannot tell those apart on its own.
