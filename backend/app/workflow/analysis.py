"""Gate concordance: whether the TA gate and the Vibe gate agree with each other.

**What this answers, and what it does not.** `app.workflow.candidates.CandidateObservation` logs
every candidate the desk scanned and every gate's ruling on it, refusals included -- see that
module's own docstring for why the refused set is the study's only well-powered instrument. This
module asks a narrower, cheaper question of that same log: not "did a gate predict forward return"
(which needs resolved observations and is a statistical question), but "do the two gates, judging the
same candidate, land on the same answer" (which needs nothing but the two `passed` flags already
written down, and is a plain contingency-table count). Zero model cost, because nothing here samples
anything -- it is arithmetic over a log another stage already wrote.

**Why this is a pure function of already-read observations, not a settings-reading entry point.**
`app.workflow.candidates.read_observations` is the log's one reader; re-parsing `candidates.jsonl`
here would duplicate that function's corruption handling (`test_an_unreadable_row_is_skipped...`) and
risk drifting from it. So this module never touches disk: a caller reads the log with
`read_observations(settings=...)` and hands the result here. That split also makes the arithmetic
trivially testable against a synthetic observation set, with no `settings` fixture or temp directory
required.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.workflow.candidates import CandidateObservation

__all__ = ["GateConcordance", "gate_concordance"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GateConcordance(_Frozen):
    """The TA-vs-Vibe 2x2 contingency table over every candidate that carries a ruling from both
    gates, and how often the two agreed."""

    total: int
    """Candidates counted -- those carrying a ruling from both `ta_gated` and `vibe_gated`. A
    candidate missing either gate's ruling (a run that only enabled one arm) is excluded rather than
    treated as a tacit refusal; see `_gate_passed`."""

    both_pass: int
    ta_only: int
    """TA passed, Vibe refused."""

    vibe_only: int
    """Vibe passed, TA refused."""

    neither: int

    agreement_rate: float | None
    """`(both_pass + neither) / total` -- the fraction of candidates where the two gates reached the
    same verdict, pass or refuse alike. `None` when `total` is zero: an agreement rate computed over
    no candidates is not a rate of anything, and reporting `0.0` would misread as "the gates never
    agree" rather than "there is nothing to compare yet."""

    disagreement_count: int
    """`ta_only + vibe_only` -- named separately from the two counts it sums, because "how often did
    the gates disagree" is the question this table exists to answer, and a caller should not have to
    re-derive that sum to ask it."""


def _gate_passed(observation: CandidateObservation, gate: str) -> bool | None:
    """`gate`'s ruling on `observation`, or `None` if that gate never ruled on it."""
    for decision in observation.gates:
        if decision.gate == gate:
            return decision.passed
    return None


def gate_concordance(observations: Sequence[CandidateObservation]) -> GateConcordance:
    """Build the TA-vs-Vibe 2x2 contingency table from already-logged candidate observations.

    Counts every observation carrying a ruling from both `ta_gated` and `vibe_gated` -- which, for a
    candidate logged by `app.workflow.pipeline._stage_orders`, is every observation, since that stage
    always attaches all three gate rulings. The `full_workflow` gate is deliberately not read here:
    it is the conjunction of the other two (`_passes_gate`'s own definition), so including it would
    not add a third independent opinion, only restate the AND of the two this table already compares.
    """
    both_pass = ta_only = vibe_only = neither = 0
    counted = 0
    for obs in observations:
        ta_passed = _gate_passed(obs, "ta_gated")
        vibe_passed = _gate_passed(obs, "vibe_gated")
        if ta_passed is None or vibe_passed is None:
            continue
        counted += 1
        if ta_passed and vibe_passed:
            both_pass += 1
        elif ta_passed and not vibe_passed:
            ta_only += 1
        elif vibe_passed and not ta_passed:
            vibe_only += 1
        else:
            neither += 1

    agreement_rate = (both_pass + neither) / counted if counted else None
    return GateConcordance(
        total=counted,
        both_pass=both_pass,
        ta_only=ta_only,
        vibe_only=vibe_only,
        neither=neither,
        agreement_rate=agreement_rate,
        disagreement_count=ta_only + vibe_only,
    )
