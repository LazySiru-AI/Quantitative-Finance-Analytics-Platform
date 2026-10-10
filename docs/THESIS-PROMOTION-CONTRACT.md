# Thesis → Library Promotion — Backend Contract (Phase 3.1)

**Status:** ✅ **BUILT (2026-09-05) as the reference-only card (§0 Option 1).** The endpoint
`POST /api/thesis/promote` ships, writing a survivor as a `reference_only` library card
(`app.thesis.promotion`, `app.tournament.models.StrategyCard.reference_only`); the round/desk
scoring paths refuse it. The safety model (server rebuilds from the ledger, no client DSL),
discipline-by-template-match, empty-string time-stop exit, and `source_thesis_hash` provenance are
all as drafted below. The one field the draft got wrong — `designed_through` (§4) — is resolved by
`reference_only` exempting the card from the cutoff; §9's tier/position/interval/exit decisions
stand. History of the blocker that forced this shape:

**Status (at draft):** ⛔ **BLOCKED during build (2026-09-05).** The contract below is sound except for one
load-bearing field (`designed_through`, §4) that the destination model's own validator refuses for a
fresh thesis survivor. This is not a bug to code around — it is the leakage-protection invariant
doing its job. The blocker, and the three ways past it, are in **§0** immediately below; they need an
owner decision before any code is written. Everything from §1 on is the original draft, left intact
so the decision has full context.

---

## 0. ⛔ Blocker found while building — the design-cutoff validator

`app.tournament.models.StrategyCard` carries a `model_validator`,
`_cannot_claim_to_have_seen_the_trading_window`
([backend/app/tournament/models.py:269](../backend/app/tournament/models.py)), that **rejects the
card at construction time** unless:

- a tournament card (`desk_only=False`) has `designed_through <= DESIGN_THROUGH` (**2026-02-13**), or
- a desk card (`desk_only=True`) has `designed_through < DESK_INCEPTION` (**2026-08-15**).

A Thesis survivor is *designed through roughly now*: it was pre-registered and then validated on a
**holdout** — an out-of-sample window that runs up to registration time. So its honest
`designed_through` is its registration date, which for any recently-run thesis is **after both
cutoffs**. The card cannot be constructed by either path. Concretely, `registered_at.date()` of a
2026-09 survivor fails `> 2026-02-13` (tournament) *and* `>= 2026-08-15` (desk).

**Why this is the invariant working, not a snag.** The gate exists so no card is scored on a window
its author already saw. A thesis survivor genuinely saw data through ~now; every existing scoring
window (tournament `TRADE_START`, desk `DESK_INCEPTION`) opened *before* that. There is therefore no
existing window it can be honestly scored on, and no honest `designed_through` that both passes the
validator and reflects when the thesis was really designed.

**The evolution loop dodges this only because it isn't dodging.** `card_for` hard-codes
`designed_through=DESIGN_THROUGH` ([backend/app/evolution/proposer.py:285,345](../backend/app/evolution/proposer.py))
— true for genomes, which are bred against data through the Feb cutoff. Pinning a *thesis* card to
Feb 13 would be **false** (it evaluated its rule on a holdout through September) and would defeat the
very gate the thesis apparatus exists to enforce. That path is off the table — it is the
date-fabrication class of defect this repo has been burned by before (see the memory on
`filled_at`/design-cutoff).

### The three honest ways forward (owner decision)

| | Option | Cost | Honesty |
|---|---|---|---|
| **1** | **Reference-only card** — add an `unscored`/`reference_only` flag to `StrategyCard` that exempts it from the cutoff *because it is never entered into any scored window*. A promoted survivor lands on the shelf as a readable spec with a back-link to its thesis evidence; scoring it is a separate, later decision. | small model change + make the tournament runner skip such cards | high — no fabricated date; the card is explicitly not scored, so there is no window to leak from |
| **2** | **Per-card forward window** — give a thesis/desk card a design cutoff equal to *its own* registration (or holdout-end) date, and score it desk-style on a forward window opening at that date, never in the tournament. | real change to the validator **and** the desk's `effective_inception` machinery (per-card, not the global constant) | highest — it scores the survivor exactly the honest way (forward-only, from when it was designed) |
| **3** | **Don't build 3.1** — leave a Thesis survivor where it already is (the thesis ledger, readable via `GET /api/thesis/ledger`), and add only a *cross-link* from the Competition/Paper-desk UI to that evidence, with no new card on the library shelf. | near-zero backend; a frontend link | high — nothing is claimed that isn't already true |

**Recommendation: Option 1.** It delivers the actual user-visible goal — a survivor becomes a
first-class, honest shelf card — with the smallest change, and it *correctly defers* the genuinely
hard "score a strategy designed through now" problem (Option 2) instead of fudging it with a false
date. Option 3 is the fallback if putting an unscored card on the shelf is judged to add more
confusion than value.

Whichever is chosen, §4's `designed_through` row is wrong as written and is superseded by this
section.

---

**Status (original):** draft for owner review. Nothing here is built yet.
**Scope:** one new HTTP endpoint that copies a *Thesis survivor* into the strategy-competition
library as an unscored candidate card, plus the one model field and one persistence addition that
endpoint needs. Frontend wiring and the "run a round to score it" step are **out of scope** (§10).

This is the "no clean write path exists" item flagged in
[docs/STRATEGY-AGENT-UX-ANALYSIS.md](STRATEGY-AGENT-UX-ANALYSIS.md) §3.1. It stayed unbuilt because
it needs product decisions, not because it's mechanical. Those decisions are collected in §9.

---

## 1. The gap, in one sentence

A Thesis run can produce a **survivor** — a pre-registered, falsifiable rule that cleared in-sample,
out-of-sample holdout, *and* Benjamini-Hochberg correction against the ticker's whole ledger — and
today there is **no way to get that survivor onto the strategy shelf** where the Competition tab and
the paper desks draw from. Card creation is not HTTP-exposed at all: the only writer is the
evolution loop's internal `write_cards` ([backend/app/evolution/proposer.py:622](../backend/app/evolution/proposer.py)),
called from the loop supervisor thread, never from a request. This endpoint would be the
**first-ever write-a-card-from-a-request path in the repo**, which is exactly why its safety model
(§3.3) is the most important part of this document.

---

## 2. The two `StrategyCard`s — do not conflate them

There are two unrelated Pydantic classes both named `StrategyCard`. The promotion is a translation
from the first to the second.

| | **Source** | **Destination** |
|---|---|---|
| Class | `app.thesis.models.StrategyCard` | `app.tournament.models.StrategyCard` |
| File | [backend/app/thesis/models.py:347](../backend/app/thesis/models.py) | [backend/app/tournament/models.py:117](../backend/app/tournament/models.py) |
| Shape | one instrument, one interval, rich statistical evidence | a **pure specification** — entry/exit rules + risk knobs, **no score fields at all** |
| Carries a verdict? | yes (`verdict: Verdict`) | no — scoring is separate (§6) |

The survivor's actual falsifiable content lives on `ThesisRecord`
([backend/app/thesis/models.py:250](../backend/app/thesis/models.py)), which holds the frozen
`thesis: Thesis` (entry, exit, stop, symbol, interval, direction, hypothesis, `falsifies_if`,
rationale), the `verdict`, and the `in_sample`/`holdout` `Evidence`. **Everything the destination
card needs is reconstructable from `ThesisRecord` server-side** — the client supplies no rule text.

---

## 3. The endpoint

### 3.1 Shape

```
POST /api/thesis/promote
```

Mounted on the existing thesis router (`APIRouter(prefix="/api/thesis")`,
[backend/app/api/thesis.py:80](../backend/app/api/thesis.py)), alongside `/run`, `/ledger`,
`/holdout`, `/catalogue`.

**Request body** (`PromoteRequest`, new):

```python
class PromoteRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=16, pattern=r"^[A-Za-z0-9.\-^=]+$")
    thesis_hash: str = Field(min_length=8, max_length=128)  # WHICH survivor
    # --- owner risk policy, all optional, all validated numerics (never DSL) ---
    position_pct: Decimal = Field(default=Decimal("0.15"), gt=0, le=1)  # see §9-B
    purpose: Purpose = Purpose.TRADING
    tier: Literal["candidates"] = "candidates"  # see §9-A; a Literal so no other tier is writable
```

Note what is **not** here: no `entry`, `exit`, `universe`, `stop_loss_pct`, or any other rule/DSL
field. The client identifies a survivor; it does not describe one. See §3.3.

**Response** — `201 Created`, body is the created destination card
(`app.tournament.models.StrategyCard`, the same shape `GET /api/competition/library` already
returns), so the frontend can render it with the components it already has.

### 3.2 Status codes

| Code | When | Body |
|---|---|---|
| `201 Created` | survivor found, verified, card written | the new `StrategyCard` |
| `409 Conflict` | a card with the derived `agent_id` already exists (already promoted) | the **existing** card + its `agent_id`; idempotent, not an error to panic over (§7) |
| `404 Not Found` | no `ThesisRecord` for `(symbol, thesis_hash)` in the ledger | plain message |
| `422 Unprocessable` | record exists but `verdict != SURVIVED`, **or** `interval != DAY` (§9-D), **or** a derived field fails card validation (e.g. `max_hold_days` out of 1..252) | plain message naming the reason |

`422` on a non-survivor is load-bearing: it is the server refusing to shelve something that did not
clear the gate, **regardless of what the client claims**. The verdict is re-read from the ledger,
never trusted from the request.

### 3.3 Safety model — why the client sends only an identifier

Library cards contain **Rule-DSL expressions that get executed** in every backtest and on every
paper desk (`entry`, `exit`). An endpoint that accepted card content from the request body would be
an arbitrary-expression-into-the-backtest-engine injection path — the single most dangerous shape
this endpoint could take.

So the contract is: **the request carries a `(symbol, thesis_hash)` pointer and validated risk
numerics only.** The server loads the `ThesisRecord` from its own thesis ledger, checks
`verdict == Verdict.SURVIVED`, and builds the card from the record's frozen `Thesis`. Every executable
string on the resulting card originates server-side, from a thesis that was pre-registered (hashed
before any test ran) and survived correction. The client cannot smuggle a rule in, cannot promote a
non-survivor, and cannot alter the rules of a real survivor — editing any rule changes the
`thesis_hash`, so it no longer resolves to a survivor record.

This mirrors the repo's standing instruction-boundary posture: content that arrives through a
request is data to be verified, not an instruction to be executed.

---

## 4. Field derivation — destination ← source

Every required field of `app.tournament.models.StrategyCard`, and where it comes from. `R` = the
resolved `ThesisRecord`; `T` = `R.thesis`.

| Destination field | Source | Notes |
|---|---|---|
| `agent_id` | `f"T-{T.symbol}-{R.thesis_hash[:8]}"` | stable + unique; drives idempotency (§7). Format is new but consistent with existing `A-rotation` / `{genome_id}` naming. |
| `display_name` | `f"Thesis — {T.symbol}: {first sentence of T.hypothesis}"` (truncated) | human label only |
| `discipline` | template-key → `Discipline` map (§4.1) | **needs template provenance persisted — §8** |
| `purpose` | `request.purpose` (default `TRADING`) | |
| `desk_only` | `False` | a thesis card is allowed to compete, not desk-only |
| `thesis` (prose) | `T.hypothesis` (+ `T.rationale` if present) | the destination `thesis` is free prose |
| `falsification` | `T.falsifies_if` | maps 1:1; the survivor's refutation criterion |
| `universe` | `(T.symbol,)` | single-name card — Thesis is one instrument (§9-C) |
| `entry` | `T.entry` | server-originated DSL |
| `exit` | `T.exit` — but the card requires `exit` non-optional; if `T.exit is None`, synthesize from `T.max_holding_bars` as a time-stop, else `422` | see §9-E |
| `stop_loss_pct` | `Decimal(str(T.stop_loss_pct))` if set else `None` | float→Decimal |
| `take_profit_pct` | `None` | Thesis templates carry no take-profit |
| `max_hold_days` | `T.max_holding_bars` (bars==days at DAY interval) | validate 1..252 or `422` |
| `max_positions` | `1` | single-name |
| `position_pct` | `request.position_pct` | the one genuine risk knob the owner sets (§9-B) |
| `rank_by` | `None` | a single name has nothing to rank |
| `designed_through` | `R.registered_at.date()` | **the pre-registration date** — the design was frozen at registration, so the card may be evaluated on any later data without look-ahead. This is the honest leakage cutoff for the design-cutoff / `effective_inception` gate. |

### 4.1 Template → Discipline map

Every one of the six catalogue templates
([backend/app/thesis/author.py:59](../backend/app/thesis/author.py)) maps onto an **existing**
`Discipline` value ([backend/app/tournament/models.py:95](../backend/app/tournament/models.py)) — no
new enum member is needed:

| Template `key` | `Discipline` |
|---|---|
| `band_reversion` | `MEAN_REVERSION` |
| `oversold_bounce` | `MEAN_REVERSION` |
| `trend_following` | `TREND` |
| `momentum_persistence` | `MOMENTUM` |
| `volatility_contraction` | `VOLATILITY` |
| `decay_avoidance` | `RISK_MANAGED` |

Discipline is not cosmetic: it is the label the tournament's multiple-testing correction uses to
tell genuinely different ideas apart from ten variations on one (per the `Discipline` docstring).
Getting it right is why §8 exists.

---

## 5. New model field: provenance

`app.tournament.models.StrategyCard` has no `origin`/`source` field today. Add **one optional field**,
following the exact precedent of `falsification` (added later, optional, no migration needed for the
~57 cards already on disk — the model is `extra="forbid"`, so *omitted* is fine, *unknown* is not):

```python
source_thesis_hash: str | None = None
"""Set only on cards promoted from a Thesis survivor (POST /api/thesis/promote). Links the card
back to its ThesisRecord for audit and for promotion idempotency. None for every hand-authored or
evolution-bred card."""
```

This is enough to (a) trace any shelved card back to the exact pre-registered thesis that earned it,
and (b) make double-promotion detectable without parsing `agent_id`. A broader `origin` enum
(`"thesis" | "evolution" | "hand"`) is a reasonable future generalization but is **not** required
for 3.1 and is left out to keep the change one field wide.

---

## 6. Tier and scoring semantics

- **A promoted card lands in `candidates/`** (`backend/app/paper/library/candidates/`), unscored.
  It is a pure specification the moment it is written — the destination model carries **no** score
  fields (no `median_excess`, `q_value`, returns); those live only in `AgentResult`/`Standing`,
  computed when a card is *run through a tournament round*, never stored back on the card.
- **Promotion does not score, does not run anything, does not seat anything.** It writes one JSON
  file. The card shows em-dashes in the Competition library until the owner runs a round that
  includes it — which is the honest state, and the same state every hand-authored candidate is in
  before its first round.
- This deliberately **differs** from the evolution loop's route into `candidates/`, which requires
  clearing a statistical gate over ≥2 consecutive generations
  ([backend/app/evolution/promotion.py](../backend/app/evolution/promotion.py)). A thesis survivor
  earned its place by a *different but real* gate: pre-registration + holdout + BH correction. The
  contract's position is that these are comparable evidentiary bars, so both may write to
  `candidates/`. Promotion out of `candidates/` into `base`/`variants` remains the existing manual
  step and is untouched.

---

## 7. Idempotency & dedupe

`agent_id` is a pure function of `(symbol, thesis_hash)`, so promoting the same survivor twice is
naturally idempotent at the filename level. The endpoint makes that explicit:

- If `candidates/{agent_id}.json` already exists → **`409`** with the existing card. Re-promoting is
  a no-op, not a duplicate, and never an overwrite (a survivor's rules are immutable by hash, so a
  second promotion can only be identical anyway).
- No `force`/overwrite flag in v1. There is no legitimate reason to overwrite a card whose content
  is hash-pinned.

---

## 8. Prerequisite backend addition (small)

The discipline map (§4.1) is keyed by **template key**, but the frozen `Thesis` object does not
carry which template produced it. The clean fix is to **persist `template_key` on `ThesisRecord`**
(not on `Thesis` — adding a field to the hashed `Thesis` would change every thesis hash):

```python
# ThesisRecord, backend/app/thesis/models.py
template_key: str | None = None  # the app.thesis.author template this thesis was instantiated from
```

Set it where the author instantiates a thesis from a `Template`. For records written before this
field exists, `template_key` is `None`; the promotion endpoint then falls back to `RISK_MANAGED`
(the most conservative label for correction purposes) and includes a note. This keeps old ledgers
promotable without a migration.

*Alternative considered and rejected:* reverse-matching a thesis to its template by comparing
`entry`/`hypothesis` text. Brittle (templates parameterize their expressions), and it fails silently
when a template is edited. Persisting the key is one line and exact.

---

## 9. Owner decisions

These are the calls that are genuinely yours — each changes behavior, and I've marked my
recommendation. Everything else in this doc is mechanical translation.

**A. Which tier?** → *Recommend `candidates/`* (§6). The `tier` field is a `Literal["candidates"]`
so nothing else is reachable in v1. If you'd rather thesis cards land on their own shelf (a new
`thesis/` tier) so they're visually separable from evolution/hand candidates, that's a wider change
(new tier in `TIERS`, new directory, UI grouping) — say so and I'll re-scope.

**B. `position_pct` default and ceiling.** A single-name card puts `position_pct` of the book into
one instrument. → *Recommend default `0.15`, hard ceiling `1.0`, owner-settable per promotion.* If
you want a lower cap (single-name concentration risk), name it and it becomes the `le=` bound.

**C. Single-name universe — acceptable?** A Thesis is about *one* instrument, so the card's universe
is `(symbol,)`. Single-name cards are legal in the library but most existing cards rotate across a
basket. → *Recommend allowing it* (the evidence is genuinely single-name; widening it would be
inventing a claim the thesis never tested). Flagging because it's a modeling choice, not a bug.

**D. Restrict to daily interval?** The library card has no interval field — the tournament runs
daily bars — so an hourly thesis survivor has nowhere to put its interval and `max_holding_bars`
wouldn't equal `max_hold_days`. → *Recommend v1 rejects non-DAY survivors with `422`.* Hourly
promotion would need an interval-aware tournament, which is its own project.

**E. Exit-less theses.** A Thesis may have `exit == None` (pure horizon/time-stop), but the library
card requires a non-null `exit`. → *Recommend synthesizing a time-stop exit from `max_holding_bars`
when `exit` is None, and `422` if neither is present.* Alternative: reject all exit-less survivors.

---

## 10. Out of scope (deliberate follow-ups)

- **Frontend "Promote to library" button.** Attaches in `ThesisCardHeader`
  ([frontend/src/components/ThesisCard.tsx:80](../frontend/src/components/ThesisCard.tsx)) next to
  the `VerdictBadge`, gated on `card.verdict === "survived"`. Calls `POST /api/thesis/promote` with
  `{ symbol, thesis_hash }`. A separate, small frontend task once this contract is accepted.
- **Running a round to score the promoted card.** Already exists — the Competition "Next round" flow
  picks up anything in `candidates/`. Promotion just makes the card *eligible*.
- **Seating a scored thesis card on a paper desk.** The existing pending-seat lifecycle
  ([backend/app/api/evolution.py:336](../backend/app/api/evolution.py)) already handles that once a
  card has a genome/roster path; whether a thesis card needs a genome to be seatable is a question
  for a later phase, not this one.

---

## 11. Test plan (what "done" would prove)

Backend, `pytest`:

1. **Happy path** — a ledger with a `SURVIVED` record → `POST /promote` returns `201`, writes
   `candidates/T-{symbol}-{hash8}.json`, and the file round-trips through
   `app.tournament.models.StrategyCard.model_validate_json`.
2. **Non-survivor refused** — a `REJECTED`/`INCONCLUSIVE`/`None` record → `422`, no file written.
   (The load-bearing safety test.)
3. **No client DSL** — assert the request model has no rule fields; a request carrying an extra
   `entry` is rejected by `extra`-forbid / ignored, and the written card's `entry` equals the
   *ledger's* thesis entry, not anything from the request.
4. **Idempotent** — promoting the same `(symbol, thesis_hash)` twice → second call `409`, exactly
   one file on disk, identical content.
5. **Interval gate** — an hourly survivor → `422` (§9-D).
6. **Exit synthesis** — an exit-less survivor with `max_holding_bars` → `201` with a synthesized
   time-stop exit; one with neither → `422` (§9-E).
7. **Discipline mapping** — a record with `template_key="band_reversion"` → card
   `discipline == MEAN_REVERSION`; a record with `template_key=None` → `RISK_MANAGED` + note (§8).
8. **`designed_through`** — equals `registered_at.date()`, and is `< today` so the card is
   immediately round-eligible under the design-cutoff gate.
9. **Provenance** — the written card's `source_thesis_hash == thesis_hash`; a hand-authored library
   card still validates with `source_thesis_hash` absent (`None`).

No frontend tests in this phase (the button is §10).
