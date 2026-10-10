"""Deterministic verdict extraction for the `followup_review` Vibe Trading preset.

`app.vibedesk.presets.followup_review`'s referee agent is instructed to end its report with exactly
one line -- `VERDICT: SUPPORT`, `VERDICT: REFUTE` or `VERDICT: INCONCLUSIVE` -- and nothing after it.
This module is the only place that reads that line back out, and it never makes a second model call to
do so: mirrors `app.tradingagents.schemas.parse_rating`, which extracts the portfolio manager's rating
from its own rendered decision the same way, for the same reason -- a model may design and argue a
verdict, but nothing downstream may re-score one by asking a model to summarize its own answer.

**Why INCONCLUSIVE is the default, not an error.** A referee that ends with no recognizable verdict
line at all (a model that ignored the instruction, or truncated) is treated exactly like a referee that
explicitly wrote `VERDICT: INCONCLUSIVE`: the study downstream gets "no signal" either way, never an
accidental SUPPORT or REFUTE manufactured from a parse failure. `was_explicit` is what lets a caller
tell the two cases apart afterward -- `True` means the model actually wrote the line, `False` means this
function fell back to the default -- so a study can report a compliance rate instead of silently mixing
abstentions (the model chose INCONCLUSIVE) with parse failures (the model wrote nothing recognizable).
"""

from __future__ import annotations

import re
from typing import Literal

__all__ = ["VibeVerdict", "parse_verdict"]

VibeVerdict = Literal["SUPPORT", "REFUTE", "INCONCLUSIVE"]

#: Matches a `VERDICT: <word>` token even when a model wraps it in markdown emphasis
#: (`**VERDICT: REFUTE**`, `_VERDICT: SUPPORT_`), leaves stray whitespace around the colon or the word,
#: uses a dash instead of a colon, or trails the word with punctuation or more prose on the same line.
#: The literal `VERDICT` keyword is required on every match -- this is what keeps a sentence that
#: merely uses the word "refute" in passing (with no `VERDICT:` label) from parsing as a verdict; see
#: the module tests for the case this guards against.
_VERDICT_RE = re.compile(
    r"(?i)[*_]*\s*VERDICT\s*[*_]*\s*[:\-]\s*[*_]*\s*(SUPPORT|REFUTE|INCONCLUSIVE)(?![A-Za-z])"
)


def parse_verdict(final_md: str) -> tuple[VibeVerdict, bool]:
    """The referee's verdict, extracted deterministically from its own rendered report.

    Scans from the *end* of the text: the contract asks for the verdict as the report's final line,
    but models routinely add a trailing pleasantry or a stray blank line after it, so this takes the
    *last* matching `VERDICT: ...` line in the text rather than requiring it to be the literal last
    line. Matching is case-insensitive and tolerant of surrounding markdown emphasis and whitespace.

    Returns `(verdict, was_explicit)`. When no verdict line is found anywhere in the text, returns
    `("INCONCLUSIVE", False)` -- see this module's own docstring for why that default, rather than an
    exception or a guess, is the correct failure mode here.
    """
    matches = list(_VERDICT_RE.finditer(final_md))
    if not matches:
        return "INCONCLUSIVE", False
    word = matches[-1].group(1).upper()
    verdict: VibeVerdict = word  # type: ignore[assignment]  # word is one of the three regex alternatives
    return verdict, True
