# Rounds 3B and 3C — the reconciliation UI, and a frontend that can be tested

**1728 Python tests pass** (up from 1722), 1 skipped. **31 frontend tests pass**, where there were
none. `ruff` clean, `mypy --strict` clean across 105 source files, `tsc --noEmit` clean with
`noImplicitReturns` newly on, `vite build` clean.

---

## 3B — `POST /api/tax/reconcile` had no consumer

The only endpoint in the API with nothing calling it, and the one whose absence mattered most.
This application's own disclaimer, printed at the top of the Tax page, says its figures are a
calculation that must be reconciled against the broker's 1099-B before filing. The engine that does
that comparison was written in Phase 3, tested to 16 cases, and could not be run from the
application. `docs/reports/defects-2.md` then found the permanently-disallowed figure understated
for tax year 2026 and said in as many words that this reconciliation *"is what would have
caught it"*.

### The deltas had to be serialised before any UI could exist

`proceeds_delta`, `basis_delta` and `gain_delta` were plain `@property`, so they did not cross the
wire. Money in this API is a decimal *string* precisely so that no client does arithmetic on it —
which left the one column a reconciliation exists for, "off by how much", reachable only by
subtracting two decimal strings in IEEE doubles. They are `computed_field` now. The subtraction
stays in `Decimal` on the server and the answer travels.

### What the panel refuses to say

**A clean result is real and limited.** Every line agreeing to the cent means the lines the user
*transcribed* agree. A disposal absent from both sides — a transaction missing from the export and
therefore also missing from what they typed — cannot appear. So a clean run reports the count it
compared and tells the reader to check it against the form, and never renders as "your taxes are
correct".

**The two "missing" statuses are opposites.** Missing from the engine means the broker reported a
disposal that was not computed, so the *ledger* is incomplete. Missing from the 1099-B is the
reverse and a different investigation. A single "mismatch" count would hide which side to go and
look at.

**The absent side renders an em dash.** A real zero and an absent figure are the same value on the
wire; only the status separates them. `$0.00` there would state a number the form does not contain.

Verified against the UAT sandbox: a matching line reports clean; a $100 proceeds difference plus a
fabricated NVDA line report −$1,100.00 total with the per-line breakdown and the "likely a
transaction missing from the imported export" note; `term=medium` returns *"unrecognised term
'medium' (row 2)"* with the stale result cleared, so an old comparison cannot be read as applying to
new input.

---

## 3C — the frontend had no tests and no runner

`package.json` declared `dev`, `build`, `preview`, `typecheck`. Zero `*.test.*` files across 3,541
lines of pages and ten typed API clients. `tsc` was the only guard, and `defects-1.md` documents
exactly what it misses: a union that drifted from its backend enum compiled clean, rendered a blank
headline, and returned `undefined` at runtime from a switch with no `default`.

Now: `vitest` + `@testing-library/react`, a `test` script, `noImplicitReturns` on, and the run
wired into CI's frontend job ahead of the build.

### The setup enforces one rule

**No test makes a network request.** The dev server proxies `/api` to a live backend; a component
that fetches on mount would otherwise reach the user's real ledger from a test run. The global
`fetch` is replaced with one that throws, naming the URL. A test that needs a response stubs the API
module; a test that did not mean to fetch fails loudly instead of depending on whatever is running
on port 8000.

### Three defects, found by the first four test files

**`formatMoneyOrDash(undefined)` threw.** The function whose entire purpose is rendering an absent
figure as `—` rather than `$0.00` crashed on the most common shape of absent: a field simply not on
the wire. It tested `=== null`. This is not hypothetical — it is what took the Tax page to a white
screen during 3B, when a backend field that had not been redeployed arrived as `undefined` and
`formatMoney` called `.trim()` on it. Now `== null`, covering both.

**Two facts competed for one hint slot on the cash tile.** When cash was partial *and* there were
unsettled proceeds, a ternary chain showed the settled/unsettled split and silently dropped
"3 accounts excluded" — so the size of the gap was stated nowhere, on a page whose rule is to name
the gap rather than merely flag it. Both are shown now. Confirmed live: the sandbox portfolio reads
`$3,017.88 settled · $1,050.45 unsettled · 1 account excluded`, where it previously stopped after
"unsettled".

**A render crash took down the whole application, navigation included.** There was no error boundary
anywhere. One is now wrapped around the route tree, keyed on pathname so navigating away from a
crashed page clears it. It shows the error text deliberately — this is a local single-user
developer tool, the person reading the screen is the person who can fix it, and "something went
wrong" would cost them the only useful fact — and it says plainly that nothing was written, which is
the first question after a crash in something that computes tax figures.

### What the tests assert

Not coverage. The rules this codebase states about itself and had no way to check:

- **`tests/test_frontend_contract.py` (5, Python).** Every member of every backend enum that crosses
  the wire is present in the TypeScript union mirroring it. This is the one that would have caught
  the original drift: `assertNever` guards turn the *next* edit of a union into a compile error, but
  the drift happens when a **Python** enum gains a member, and nothing on the Python side had any
  reason to notice. Proven to fail on a synthetic drifted enum before being committed.
- **`money.test.ts` (12).** Precision past what a double holds; no rounding; no negative zero; an
  absent figure renders `—` and a genuine zero still renders `$0.00`, because the distinction only
  works in both directions.
- **`labels.test.ts` (7).** Every member of every shared union produces a non-empty, distinct,
  non-raw-token label; a conflicting import is toned as a problem rather than as the success it
  numerically resembles; budget exhaustion and catalogue exhaustion do not share a label, having
  been merged once already.
- **`Portfolio.test.tsx` (8).** Withheld cash and withheld equity render `—`; a partial total names
  what it excludes at the point the total is shown; the as-of stamp says outright when it is mixing
  three pricing dates; nothing priced says so rather than showing a zero.
- **`ErrorBoundary.test.tsx` (4).**

---

## Still open from `docs/reports/open-work.md`

Round 4 as planned: Stooq (probed again this round — still an anti-bot challenge page, so Yahoo
remains a single point of failure for all market data), Fear & Greed component units, the remaining
small surface fixes, and `SPINOFF`. Then round 5: rewriting `HANDOFF.md`, and the second UAT run
with the three harness fixes applied first.
