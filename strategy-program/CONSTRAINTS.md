# Real-world constraints

A strategy that looks good only when one of these is relaxed is not a strategy. Each entry says
whether the constraint is **enforced by code** or **enforced by discipline** — the second kind is
where this project has been burned.

## Information timing

**13F filings are public up to 45 days after quarter end.** §13(f) requires institutional managers
over $100m to file within 45 days of each quarter's end. A position held on 30 September may not be
publicly known until 14 November. A filing may therefore be acted on from its **filing date**, never
its period date.

*Enforced by code, if you pass the argument.* `as_of` on every institutional call bounds candidates
by `FilingRef.filing_date`. A filing reporting 2026-06-30 but filed 2026-08-14 is correctly invisible
to `as_of=2026-08-13`. The default is `None`, which applies no bound at all — so forgetting the
argument silently gives you tomorrow's newspaper.

**A 13F-derived universe may only trade a window that begins after the filing date it was derived
from.** *Enforced by discipline. Not by code, and it cannot be.* The lookahead guard checks whether an
indicator is causal on symbols already chosen; it has no way to know when the *basket* became
knowable. The prior tournament ran three 13F cards over a window starting 2023-08-21 whose universes
were chosen from filings dated 2025-11-14 and 2026-02-13 — a portfolio picked with knowledge of which
names would work, over a window two years of which predated the documents. The guard passed all
three. Their three-year numbers are unmeasured, not results.

**NPORT-P is roughly 60 days.** Registered funds file NPORT, not 13F. An ETF does not file a 13F.

**§13(f) covers US-listed equities only, and puts and calls appear as separate lines.** Scion's four
largest disclosed holdings — 95% of that book — are option lines. A long copy of that book takes the
opposite of the trade. Michael Burry's largest "position" was a bet *against* Palantir.

**CUSIP is the identity key, and the ticker bridge is narrow.** There is no free general CUSIP→ticker
directory. The available bridge resolves only CUSIPs present in the local ledger — a small
set of entries, mapping only a few percent of raw holdings across all filers. Matching on issuer name instead is
ruled out: it is unreliable and has been rejected in this project already. If a name does not resolve,
it is not tradeable here, and the honest response is a smaller universe rather than a workaround.

## Execution

*All enforced by code.*

- Decisions use data strictly **before** the decision session. Fills happen at the **next session's
  open**. You never get the close you decided on.
- **Stops are evaluated against the previous close, not the intraday low**, because the decision-maker
  cannot see the session's low. Stop-outs land later and worse than an intraday check implies — one
  card's worst trade lost **19.9% against a 12% stop**. This is a deliberately conservative model of a
  stop, not a bug.
- Deterministic adverse slippage. Commissions, SEC fees and TAF charged. Whole shares only. A $500
  minimum clip. T+1 cash settlement respected — an entry that cannot be paid for is rejected, and
  rejections are counted and reported.
- **No dividends anywhere.** Benchmark and strategies alike trade price only. SPY returned +75.40%
  price-only over 2023–2026 against +81.32% total return, so every margin measured in this program
  flatters the strategy by roughly two points a year against a real buy-and-hold investor.
- **Cash earns nothing.** There is no interest on an idle balance. A strategy that sits in cash is
  modelled as flat, which understates a real defensive position in a high-rate period.

## Structural limits of the engine

*Enforced by code, in the sense that you cannot express these at all* — with one partial exception,
the ranking key described in the second bullet, which is new and is the only one of these that has
ever moved.

- **The universe is fixed for the whole run.** The engine cannot rotate a universe mid-window. Any
  signal that refreshes — a 13F basket above all — is a single stale snapshot held for the entire
  window, not a live strategy. This is the most material limitation in the whole harness.
- **No cross-sectional comparison in a rule — but slot selection can now rank.** `entry` and `exit`
  are still evaluated per symbol against that symbol's own bars, and that has not changed: you cannot
  write an entry condition contingent on another symbol, a spread, or a pair. A name that fails
  `entry` is never considered, whatever the rest of the universe is doing.

  What *has* changed is the tiebreak. When more names qualify than there are slots, something has to
  choose, and it used to be the order the universe array happened to be written in — an arbitrary
  tiebreak worth a **53.9-point spread, σ = 21.2 points** over twelve orderings of one identical card.
  A card may now set **`rank_by`**, a numeric rule-DSL expression evaluated per symbol at the decision
  session and sorted across the qualifying names, highest first: `close / sma(200)`, `rsi(14)`,
  `(close - sma(50)) / atr(14)`. Negation inverts it (`0 - rsi(14)` takes the weakest); there is no
  second direction field. This is what "buy the strongest of these" means here, and it is the only
  cross-sectional step in the engine.

  *`rank_by` is guarded exactly as `entry` and `exit` are* — same node allowlist, same causality
  check, per universe symbol, before the card trades. A non-causal key is lookahead in the selection
  step, which is harder to notice than lookahead in an entry rule precisely because the entry rule
  beside it stays clean.

  **Leaving `rank_by` unset is still a choice, and it is the old one.** Unset reproduces universe-order
  fills byte for byte — deliberately, because every card frozen before this field existed has published
  numbers that were produced that way. Those cards are all still exposed to the full 53.9-point spread
  and their margins must still be read against that floor. Setting `rank_by` does not make the spread
  go away either; it replaces an arbitrary choice with a stated one, which is a different claim from
  a better result. The one time relative-strength ordering was measured against random orderings of
  the same card it ranked **9th of 10 — better than the alphabet, and inside the noise**
  (`backend/app/paper/library/README.md`).
- **One stop and one position size for every symbol.** No per-symbol volatility scaling. A universe
  mixing a 15%-vol ETF with a 60%-vol single name gets one stop that fits neither.
- **Long only.** No shorts, no options, no leverage beyond holding a leveraged ETF and accepting its
  decay.
- Not expressible: ADX, stochastics, Ichimoku, volume profile, Fibonacci levels, multi-timeframe
  confluence. `vwap()` exists but is registered for intraday intervals only and fails on daily bars.

## A risk control currently relaxed

The persona mandate caps a single name at **25% of the book**. Rounds run with that raised to 100% so
that concentrated cards run as written rather than having their orders refused wholesale — in the
prior tournament this was discovered the hard way, when three cards designed at 30–40% per name had
their entries rejected en masse and one filled 6 orders against 449 rejections.

This is a deliberate loosening of a real risk control. Every card relying on it says so, every report
discloses it, and drawdowns should be read in that light. Runs that keep the real cap pass
`--honour-persona-cap`, and any number quoted without it should say so.
