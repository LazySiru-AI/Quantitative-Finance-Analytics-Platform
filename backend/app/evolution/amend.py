"""Applying a reviewer's `ProposedAmendment`s to the *next* generation's `LoopConfig` -- safely, and
on the record.

`app.agents.reviewer` (a sibling package, written concurrently with this one) reads a generation's
own `GenerationOutcome` and may propose changing how the loop runs from here: loosen or tighten
`promotion_margin_pp`, rotate `holdout_windows`, steer `focus_symbols`/`avoid_symbols`, and so on --
see `app.agents.review_models.ProposedAmendment` for the exact fields `AmendmentField` names. This
module is the only place those proposals are actually applied. Three things about that had to be
true before any of it could be trusted, and each is a rule here rather than a convention a caller is
expected to remember.

**Validate by construction, never by hand.** `LoopConfig` (`app.evolution.models`) is a frozen
pydantic model that already declares every bound this loop runs under -- `population` 2..24,
`news_fraction` 0..1, `elite_count` >= 1, and so on. A second, hand-written copy of those same checks
here would be one more place for the two to drift out of sync, and a drift in *this* direction (an
amendment this module accepts that `LoopConfig`'s own constructor would refuse) is a live crash
waiting for the first collaborator that actually tries to use the resulting config. So an amendment is
never validated by an `if` statement written here: `config.model_copy(update={field: value})` is
applied first (pydantic's own `model_copy` does not re-run validators -- it is a plain attribute
swap), and the result is round-tripped through `LoopConfig(**dumped)`, which does. A `ValidationError`
from that round trip becomes a `RefusedAmendment` carrying pydantic's own message, verbatim -- never a
crash, and never an amendment that silently vanishes without a reason recorded anywhere.

**One invariant is not negotiable: `holdout_windows` must not intersect `windows`.** The owner has
granted the reviewer full authority to change which windows are held out, and `apply_amendments`
honours that -- an amendment that only touches `holdout_windows` (or only `windows`) is otherwise
treated like any other. But a window that is both a selection window and a holdout window has not
been held out at all: it contributed to the very median the holdout exists to check, which
`strategy-program/EVOLUTION-LOOP.md` section 1 names as "the one failure that makes the entire
mechanism decorative" (there, about running both window sets into the same round directory --
the failure mode here is a different mechanism, the same defect: a number that is supposed to be
independent evidence turns out not to be). `LoopConfig` itself does not encode this rule -- it is a
cross-field business invariant, not a per-field bound -- so this module checks it explicitly, on the
*resulting* config, after every amendment (not only ones that touch `windows`/`holdout_windows`
directly, since an earlier amendment in the same batch could have set one half of the conflict and a
later one the other half). This refuses a self-contradiction the reviewer's own proposal created, not
a policy choice the owner is free to make -- the owner's authority over *which* windows are held out
is not in question; a holdout that is not actually held out is not that authority being exercised.

**Amendments take effect for generation N+1 only, never retroactively.** `strategy-program/
PROTOCOL.md` section 2 makes this the integrity boundary of the whole programme: "a card edited after
any result exists is not a strategy, it is a memory of one." Nothing in this module reaches backward
-- it takes one `LoopConfig` and a batch of proposals and returns the config the *next* generation
should use; it never touches a `GenerationOutcome`, never rescoes a standing, never rewrites anything
already written to `gen{N:04d}/OUTCOME.json`. `app.evolution.loop` is the only caller, and it only
ever calls this after a generation has finished, to decide what its own *lane's next* generation
should run with -- see that module's wiring for exactly where.

**Append-only audit.** Every amendment this module is asked to apply -- whether it succeeds or is
refused -- is appended to `data/loop/amendments.jsonl` as one `AmendmentRecord` JSON line, following
`app.evolution.ledger.Ledger.record`'s own append pattern (mend a dangling unterminated last line
before appending, flush after every write) rather than inventing a second one. This is the file that
makes a self-modifying loop reviewable after the fact: a retuned promotion margin, a rotated holdout,
a refused overlap -- every one of them is a decision, and `PROTOCOL.md`'s own premise is that the
record of a decision outlives the run that produced it. A loop that could change its own gate with no
durable trace of having done so would not be auditable at all, whatever the reviewer's reasoning was.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.config import Settings
from app.evolution.models import (
    AmendmentOutcome,
    AmendmentRecord,
    LoopConfig,
    RefusedAmendment,
    amendments_path,
)
from app.tournament.purposes import Purpose

if TYPE_CHECKING:
    # `app.agents.review_models` is a sibling package written concurrently with this one and may not
    # exist yet in every checkout that imports `app.evolution.amend` -- exactly the situation
    # `app.evolution.loop.default_collaborators` already guards for `app.agents.designer` with a
    # `try/except ModuleNotFoundError`. Nothing below needs `ProposedAmendment` to be a real class at
    # runtime: every field this module reads off one (`field`, `value`, `reason`) is read by plain
    # attribute access, duck-typed exactly like every callable on `Collaborators` itself, so this
    # import is guarded to type-checking only. This module -- and its own tests -- can be imported and
    # run whether or not `app.agents.review_models` has landed yet.
    from app.agents.review_models import ProposedAmendment

__all__ = ["apply_amendments"]


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _append_amendment_lines(path: Path, records: Sequence[AmendmentRecord]) -> None:
    """Append `records` to `path`, one JSON line each.

    Copied from `app.evolution.ledger.Ledger.record`'s own append pattern rather than a second one
    invented for this file: mend a dangling, not-newline-terminated last line before appending (a
    process killed mid-write leaves one), then open in append mode and flush after every line so a
    reader never observes a partially written record. A no-op for an empty `records` -- so a call to
    `apply_amendments` with no amendments to apply never creates (or touches the mtime of) a file that
    does not otherwise need to exist yet, the same reasoning `Ledger.record` gives for its own no-op.
    """
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file() and path.stat().st_size > 0:
        with path.open("rb") as probe:
            probe.seek(-1, 2)
            if probe.read(1) != b"\n":
                with path.open("a", encoding="utf-8") as mend:
                    mend.write("\n")
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json())
            handle.write("\n")
            handle.flush()


def apply_amendments(
    *,
    config: LoopConfig,
    amendments: Sequence[ProposedAmendment],
    generation: int,
    purpose: Purpose,
    settings: Settings,
) -> AmendmentOutcome:
    """Apply `amendments` to `config`, in order, refusing any that would produce an invalid
    `LoopConfig` or an overlapping `holdout_windows`/`windows` pair -- see this module's own docstring
    for why both refusals exist and why nothing here is retroactive.

    Amendments are folded cumulatively: the second amendment in a batch is validated against the
    config the *first* amendment (if it applied) already produced, not against the original `config`
    argument, so a batch that changes `windows` and then `holdout_windows` sees a self-consistent
    config at each step. A refused amendment does not advance `current` -- the next amendment in the
    batch is still checked against the last config that actually validated.

    Every amendment in `amendments`, applied or refused, is written to `amendments_path(settings)`
    (one `AmendmentRecord` JSON line each) before this function returns -- see the module docstring's
    "Append-only audit" section. `AmendmentOutcome.config` is `config` with every *applied* amendment
    folded in, in order; a caller that never inspects `.applied`/`.refused` still gets the right
    config for the next generation to run with.
    """
    applied: list[AmendmentRecord] = []
    refused: list[RefusedAmendment] = []
    audit_rows: list[AmendmentRecord] = []
    current = config

    for amendment in amendments:
        field = amendment.field
        value = amendment.value
        reason = amendment.reason
        now = _utcnow()

        if field not in LoopConfig.model_fields:
            # Defensive only -- `AmendmentField` (`app.agents.review_models`) is a `Literal` of real
            # `LoopConfig` field names, so a well-typed reviewer can never produce this. Guarded anyway
            # because `ProposedAmendment` is duck-typed here (see the module docstring), and a test
            # fake or a future reviewer version is not guaranteed to respect that Literal at runtime.
            refusal_reason = f"{field!r} is not a LoopConfig field"
            record = AmendmentRecord(
                generation=generation,
                purpose=purpose,
                field=str(field),
                old_value="(unknown field)",
                new_value=str(value),
                reason=refusal_reason,
                applied_at=now,
                applied=False,
            )
            refused.append(RefusedAmendment(field=str(field), value=str(value), reason=refusal_reason))
            audit_rows.append(record)
            continue

        old_value = getattr(current, field)

        try:
            candidate = current.model_copy(update={field: value})
            # `model_copy(update=...)` does not re-run validators -- round-trip through the
            # constructor so every bound `LoopConfig` declares (population 2..24, news_fraction
            # 0..1, ...) is actually enforced. See the module docstring's "Validate by construction"
            # section for why this is the only validation this module performs by hand.
            revalidated = LoopConfig(**candidate.model_dump())
        except ValidationError as exc:
            refusal_reason = str(exc)
            record = AmendmentRecord(
                generation=generation,
                purpose=purpose,
                field=field,
                old_value=str(old_value),
                new_value=str(value),
                reason=refusal_reason,
                applied_at=now,
                applied=False,
            )
            refused.append(RefusedAmendment(field=field, value=str(value), reason=refusal_reason))
            audit_rows.append(record)
            continue

        if set(revalidated.holdout_windows) & set(revalidated.windows):
            refusal_reason = (
                "holdout_windows must not intersect windows -- a window that is also a selection "
                "window has not been held out at all (EVOLUTION-LOOP.md section 1: mixing the two "
                "window sets 'is the one failure that makes the entire mechanism decorative')"
            )
            record = AmendmentRecord(
                generation=generation,
                purpose=purpose,
                field=field,
                old_value=str(old_value),
                new_value=str(value),
                reason=refusal_reason,
                applied_at=now,
                applied=False,
            )
            refused.append(RefusedAmendment(field=field, value=str(value), reason=refusal_reason))
            audit_rows.append(record)
            continue

        record = AmendmentRecord(
            generation=generation,
            purpose=purpose,
            field=field,
            old_value=str(old_value),
            new_value=str(value),
            reason=reason,
            applied_at=now,
            applied=True,
        )
        applied.append(record)
        audit_rows.append(record)
        current = revalidated

    _append_amendment_lines(amendments_path(settings), audit_rows)

    return AmendmentOutcome(applied=tuple(applied), refused=tuple(refused), config=current)
