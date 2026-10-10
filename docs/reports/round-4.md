# Round 4 — resilience, and units on numbers that had none

**1737 Python tests pass** (up from 1728), 1 skipped. 31 frontend tests pass. `ruff` clean,
`mypy --strict` clean across 105 source files, `tsc` clean, `vite build` clean.

Four items from `docs/reports/open-work.md`. Two turned out to be smaller than the audit implied and
one turned out to be a decision rather than a fix, which is recorded here as plainly as the code
changes.

## 4A — Stooq, and what "no fallback" actually costs

Probed again before touching anything, across every shape the provider could take:

```
https://stooq.com/q/d/l/?s=spy.us&i=d   200 — JavaScript anti-bot challenge
https://stooq.pl/q/d/l/?s=spy.us&i=d    200 — same challenge
http://stooq.com/q/d/l/?s=spy.us&i=d    200 — same challenge
https://stooq.com/q/l/?s=spy.us&…&e=csv 404
```

There is no header-only fix and no unchallenged endpoint. Clearing it means executing the
challenge script, which is not something a data provider in this application does.

**The audit overstated the defect, and the correction is worth recording.** I wrote that "the
registry reports a fallback chain it does not have". On reading the code, the *failure* path is
already honest: Stooq raises a correctly-typed `ProviderResponseError` rather than returning an
empty frame, and an exhausted walk raises with what every provider said — so a Yahoo outage is
reported as an outage, never as "no history for this ticker". The previous phase had reasoned
through this carefully and its docstring says so.

What was actually missing is *structural* visibility: nothing said "you have one working source"
until something failed. So:

- `KNOWN_DEGRADED` records which providers cannot serve and why, keyed by name — a provider that
  starts working again is re-enabled by deleting a line.
- `ProviderRegistry.describe()` and `GET /api/health/providers` report the chain, how many members
  can actually serve, and name the single point of failure when there is one.
- **It reports; it does not probe.** A probe would put a network round trip per provider behind an
  endpoint meant to be polled, and would describe only this instant, while the useful fact here does
  not change between requests. Pinned by a test that makes any outbound call fail and requires the
  endpoint to answer anyway.
- One muted line at the foot of the Macro page: *"Market data comes from yahoo alone — the
  registered fallback (stooq) cannot currently serve."* A line, not a banner: a warning that appears
  on every visit and describes a condition the user cannot change stops being read within a week,
  and takes the actionable warnings beside it down with it.

Stooq stays registered. Its failure is harmless and correctly typed, and the day it answers again
the change is one deleted line.

## 4B — Fear & Greed components had no units

The confirmed half of UAT backlog item #10, and a genuine one. `FearGreedComponent.raw_value`'s own
docstring reads *"in its own unit — an index level, a ratio, a spread. Not a 0-100 score, and not
comparable across components"* — and the gauge rendered it as `raw_value.toFixed(2)` under a column
headed **Raw**. An S&P 500 level, a put/call ratio and a credit spread appeared as three unlabelled
decimals on adjacent rows, inviting exactly the comparison the model says is invalid.

`FEAR_GREED_UNITS` maps each of CNN's seven tokens to a unit and a description. It lives in
`macro_models.py` rather than in either provider, because the unit is a property of the measurement
and not of who reported it — the CNN feed and the local composite describe the same seven
quantities, and reading one map means they cannot disagree. The gauge now renders `7,781.89 index`,
`0.71 ratio`, `1.21 pp`, with the description under the component name.

An unknown key gets `(None, None)` and renders no suffix. Inferring a unit from the magnitude of a
number is how a ratio gets labelled an index.

**The other half of #10 does not reproduce and is closed**: the macro page stamps `generated_at`,
every tile carries `as_of`, and the gauge carries its own.

## 4C — three surface items

**`report.ts`'s hand-rolled `Quote`** — four fields, `price` typed `number | null` against a backend
field that is required, and an index signature swallowing everything else — is now a re-export of
the real type. Nothing rendered wrongly because of it, but two declarations disagreed about what the
server guarantees and the looser one was what the report page believed. The index signature also
meant no amount of backend drift could ever make it fail to compile.

**RSI on a perfectly flat series returned 100.** `phase-5.md` recorded this as a known judgement
call *"worth revisiting when Phase 6 attaches rules to thresholds"*; Phase 6 shipped and it was not
revisited. It also said the behaviour was pinned by a test — it was not. The two existing tests
cover strictly monotonic series, where 100 and 0 are correct and well defined; nothing covered the
flat case, where RS is 0/0.

100 there is a claim, not an answer: it reads as "maximally overbought" about an instrument that has
not moved, and would fire any `rsi(14) > 70` rule on a halted or untraded series. It is NaN now,
which is what this codebase does everywhere else with a figure it cannot support — an undefined RSI
propagates as undefined and a rule referencing it does not fire. Two tests: the flat case, and a
flat *stretch* inside a moving series, which stays defined because Wilder's smoothing carries
earlier movement forward. Without the second, "flat" could quietly come to mean "recently quiet".

**A pre-existing flaky test, found and fixed.** `test_expired_entry_is_refetched` failed once in a
full run and passed in isolation. `ttl=0.0` means "never serve from cache", and the cache tested
`age > ttl` — so two requests inside one clock tick gave an age of exactly `0.0`, which is not
greater than `0.0`, and the second was served from cache. Reliable on Windows, whose `time.time()`
resolution is coarse enough that adjacent calls routinely read the same value. Now `>=`. No
production TTL is 0 so nothing served to a user was affected, but the code did not mean what its
test said it meant.

## 4D — SPINOFF: deliberately not implemented

`core/lots.py` emits an `UNSUPPORTED_ACTION` warning for a spinoff and leaves lots untouched. It
stays that way. There is no spinoff and no split in the real ledger it was tested against (verified read-only:
seven action types, none of them corporate actions), so an implementation
would be lot-splitting logic in a tax engine with nothing to verify it against — which is the exact
shape of code this project refuses elsewhere.

What was worth checking is that the warning reaches a user, and it does: `UNSUPPORTED_ACTION` flows
through the same channel as `OVERSOLD` and `MISSING_BASIS` onto both the Portfolio and Tax pages,
and it has a written label rather than a raw token. A new test now pins that every `WarningKind` has
one — `WARNING_KIND_LABEL` is a lookup, not a union, so `tsc` cannot check it and the fallback
renders the internal identifier.

## Still open

Round 5: rewriting `HANDOFF.md` (still describing "Phases 0–2 of 8, 328 tests"), fixing the
remaining stale claims in `MIGRATION.md`, applying the three UAT harness fixes, and running persona
2 against everything rounds 3 and 4 changed.

Unchanged and still the user's: the Webull Account Statement export, and the 1099-B reconciliation —
which now has a UI to run it in.
