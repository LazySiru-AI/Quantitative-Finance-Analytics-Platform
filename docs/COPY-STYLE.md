# Copy style: budgets, voice, and what colour is allowed to say

Every on-screen string in this application goes through `t()` and lives in `frontend/src/i18n/messages/*.ts`.
This file is the editorial rule those strings are held to. `frontend/src/i18n/proseBudget.test.ts`
enforces the lengths; the rest is review.

## Why

Measured 2026-09-02: 349 of 2,537 catalog keys were prose of 80+ characters or several sentences —
about **62,000 English characters** of explanation rendered on top of the data it explained, and the
same again in Korean. The longest single strings ran 568, 564, 501, 463 and 458 characters. The
important sentence was usually in there. The reader had to find it.

Long copy is not more careful copy. A 458-character framing note is skipped; a seven-word one is read.

## Budgets

| Slot | Key shape | Budget | Voice |
|---|---|---|---|
| Page subtitle | `*.subtitle` | **90** | One clause. The heading already named the page — do not name it again. |
| Card / section note | anything else | **120** | Fragments are fine. Never restate the label above it. |
| Disclosure body | `*.more`, `*.body`, `*.detail`, `*.explain`, `*.why`, `*.intro`, `*.blurb`, `*.caveat`, `*.disclaimer` | **240** | The only slot where full sentences and worked reasoning belong — the reader opened it deliberately. |
| Pill label | rendered through `StatusPill` | **3 words** | A state, not a sentence about a state. Mono, uppercase, set by CSS. |
| Empty state | `*.empty*` | **100** | What is missing, then the one action that fixes it. |

Korean is measured against the same numbers. It is not a translation of the budget but the same rule
applied twice — Korean generally says the same thing in fewer characters, so a `ko` string over the
cap usually means the English it came from was over it too.

## Rules

1. **Do not restate the label.** If the column header says `Cost basis`, the note under it does not
   begin "The cost basis is…".
2. **One explanation per fact, app-wide.** The 13F lag was explained twice (Institutions 349 chars,
   Consensus 307); the wash-sale scope twice, each cross-referencing the other page by name. One key,
   reused.
3. **Do not cross-reference pages in body text.** Link the page.
4. **Lead with the number, not the setup.** "N of M disposals have no cost basis" before any
   sentence about what that implies.
5. **The long form is kept, not deleted.** Move it into an `InfoNote` body. Deleting a caveat is not
   concision, it is a different (worse) decision.
6. **Some things may never move behind ⓘ.** Anything the reader is worse off for not seeing keeps a
   visible short form plus a pill: "not tax advice", the 13F reporting lag, in-sample returns,
   simulated money. Shorten these; never hide them.
7. **Both languages in the same edit.** `MessagePair` makes a key impossible without both, so the
   only question is whether the Korean is good — write it, do not machine-fill it.
8. **Placeholders carry the specifics.** `{days}`, `{count}`, `{symbol}` — a sentence that hardcodes
   a number is a sentence that will be wrong.

## Colour encoding

`StatusPill` has six tones. Pick the meaning; the palette follows.

| Tone | Means | Token |
|---|---|---|
| `ok` | good, passed, held, live | `--up` |
| `warn` | caution, stale, dormant, in-sample | `--warn` |
| `bad` | failed, rejected, loss | `--down` |
| `info` | active, running, signalling | `--accent` |
| `special` | blocked, exploratory — stopped before it started | `--accent-2`, dashed + hatched |
| `neutral` | unknown, none, not applicable | `--muted`, dashed + italic |

**Colour is never the only signal.** The stylesheet has said so since long before this document:
every pill carries words, `neutral` is additionally dashed and italic so an unknown never reads as a
quiet "no", and `special` is hatched so "never ran" never reads as "ran and broke". A page showing
two or more tones renders a `PillLegend`.

Semantic colour is separate from the accent. Do not use `--up`/`--down` for emphasis, and do not use
`--accent` to mean "good".

## Before → after

| Before | After |
|---|---|
| "Each desk is an independent reference strategy on its own simulated capital -- not a combined portfolio. No total across desks, and no total across books, is a suggested allocation…" (458) | "Each desk: own capital, own rules. Not a portfolio — book totals aren't comparable." + ⓘ |
| "This is a calculation, not tax advice. Reconcile every figure below against your actual 1099-B forms before filing…" | pill `NOT ADVICE` + "Calculation only. Reconcile with your 1099-B before filing." |
| "This desk has not opened a position since inception. Its entry rule has not fired…" | pill `DORMANT` + "Entry rule never fired since inception." |
| "The mark is {days} days behind -- treat every figure on this page as that many days stale." | pill `STALE {days}D` — the pill *is* the sentence |

## Adding a string

1. Pick the shard by page (`messages/<area>.ts`); component-owned strings go in `messages/ui.ts`.
2. Key as `<area>.<thing>.<detail>`.
3. Write `en` and `ko` inside the budget.
4. Run `npm --prefix frontend test -- proseBudget`.

Never add a key to `proseBudget.allowlist.ts`. That list only shrinks — it is the set of strings that
predate the budget, and it is deleted along with this rule's escape hatch when it empties.
