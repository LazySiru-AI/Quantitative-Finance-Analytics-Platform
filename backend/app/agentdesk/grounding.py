"""The grounding gate: the mechanical check that replaces the loop's blanket no-numbers rule for a
desk stage, and the retry loop built around it.

See `app.agentdesk`'s own module docstring for why this package relaxes the evolution loop's "an
agent may never emit a number" rule and replaces it with a stronger, checkable one: a stage may state
any number that traces back to its `EvidencePack`, and nothing else. Two functions do the actual work.
`numeric_tokens` decides what counts as "a number" in free text; `grounded_values` decides what counts
as "in the pack." `check` is just the two compared against each other, and `run_grounded` is the retry
loop `app.agentdesk`'s docstring promises: a rejected stage is re-asked with its own failure quoted
back to it, up to `MAX_GROUNDING_ATTEMPTS` times, and released `degraded` rather than blocked if it
still cannot pass.

**Why normalisation has to happen on both sides of the comparison, not just one.** A model asked to
quote "4.6" is free to write "4.60", "$4.60" or "460%" of something else entirely -- the first two are
the same fact spelled two ways and must compare equal; the third is a different fact and must not.
`numeric_tokens` and `grounded_values` share the same digit-normalisation helpers for exactly this
reason: if the two sides normalised differently, a real match could fail for a formatting reason that
has nothing to do with whether the number was fabricated.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from itertools import permutations

from pydantic import BaseModel

from app.agentdesk.models import (
    MAX_GROUNDING_ATTEMPTS,
    EvidencePack,
    GroundingIssue,
    GroundingVerdict,
)
from app.agents.client import call_structured
from app.agents.models import (
    DEFAULT_MODEL,
    AgentBudget,
    AgentCall,
    AgentResponseInvalid,
    AgentRole,
    AgentTransientError,
    AgentUnavailable,
)
from app.config import Settings

__all__ = [
    "GroundedResult",
    "check",
    "correction_prompt",
    "grounded_values",
    "numeric_tokens",
    "run_grounded",
]

# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------

#: Strips the `(url)` half of a markdown link, leaving `[label text]` behind -- a filing accession
#: number or a date sitting in a URL must not register as a number the prose "cited".
_LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")

#: One numeric literal: an optional currency symbol, an optional leading minus, a run of digits and
#: commas (thousands separators are not validated for correct grouping, only stripped -- `"12,34"` is
#: accepted as a token and normalises the same as `"1234"` would, which is the conservative direction
#: to be wrong in), an optional decimal tail, and an optional trailing percent sign. The leading
#: negative lookbehind keeps this from matching a digit run glued onto a preceding letter or dot (a
#: version string, a truncated decimal continuation) rather than sitting in prose on its own.
_NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<currency>[$€£])?(?P<sign>-)?(?P<num>\d[\d,]*(?:\.\d+)?)(?P<percent>%)?"
)

#: An ordinal suffix immediately following a digit run -- "21st", "3rd" -- the tell that the number is
#: a date component, not a measurement.
_ORDINAL_TAIL_RE = re.compile(r"(st|nd|rd|th)\b", re.IGNORECASE)

#: A whole calendar date, in the forms this application actually emits and a model actually echoes:
#: `2026-08-28`, `2026/08/28`, `08/28/2026`, `28-08-2026`, and the bare `2026-08` month.
#:
#: Removed wholesale *before* scanning rather than filtered token by token afterwards, because the
#: interesting component is the day: a bare four-digit year is already exempt and a one- or two-digit
#: month is caught by the small-integer exemption, but a day past the 10th is neither, so
#: `"as of 2026-08-28"` used to yield the token `28` and reject the sentence. Every system prompt in
#: `app.tradingagents.prompts` explicitly instructs its agent to cite the as-of date of any figure it
#: leans on, so this was not an edge case -- it rejected the behaviour the prompts ask for, on almost
#: every stage, which is the most expensive kind of false positive this gate can have.
#:
#: The trailing boundary is `(?!\w)(?!\.\d)`, not a blanket `(?![\w.])`: a sentence-final period
#: directly after the date (`"as of 2026-08-28."`) is ordinary prose and must not stop the match,
#: yet a plain `(?![\w.])` treated that period as part of the following token and forced the engine to
#: backtrack to the shorter `2026-08` alternative, leaving the day (`-28`) behind to leak as a token
#: and reject the sentence -- the exact false rejection this whole scrub exists to prevent, one comma
#: or full stop away. Only a `.` that begins a decimal (`(?!\.\d)`) still blocks the match, so a date
#: glued to a decimal continuation cannot be silently swallowed.
#: The bare month-day alternative (`08-17`, `08/28`) is listed *last* so the year-bearing forms above
#: still match a full `2026-08-17` whole rather than leaving `08-17` behind. It is deliberately narrow:
#: a zero-padded or `10`-`12` month (`0[1-9]|1[0-2]`) and a real day (`01`-`31`), which excludes both an
#: invalid "month" like the `20` of a Bollinger `(20,2)` and an ordinary unpadded subtraction like
#: `8-17`. Every analyst labels its price series with these parenthetical `(08-17)` day stamps -- the
#: prompts ask for the as-of date of each figure -- so without this the day past the 10th leaked as a
#: token and degraded the stage for dating its own evidence, the same false rejection the year-bearing
#: forms were added to prevent, one missing century apart.
_DATE_RE = re.compile(
    r"(?<![\w.])(?:"
    r"\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?"  # 2026-08-28, 2026/08/28, 2026-08
    r"|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}"  # 08/28/2026, 28-08-26
    r"|(?:0[1-9]|1[0-2])[-/](?:0[1-9]|[12]\d|3[01])"  # bare month-day, no year: 08-17, 08/28
    r")(?!\w)(?!\.\d)"
)

#: A whole ISO-8601 *timestamp* -- `2026-09-08T14:32:05+00:00`, `2026-09-08 14:32`, `2026-09-08T14:32:05Z`.
#:
#: Removed before `_DATE_RE`, and it has to be: `_DATE_RE`'s trailing `(?!\w)` cannot match a date
#: glued to a `T`, so on a full timestamp it backtracked to the bare-month alternative, matched
#: `2026-09`, and left `-08T14:32:05+00:00` behind -- which then yielded the tokens `-8`, `14`, `32`
#: and `5` and rejected the sentence. Every live-quote fact this application produces is stamped with
#: exactly this format (`app.agentdesk.evidence.live_quote_evidence` puts a `LiveQuote.ts` on each
#: item's `as_of`, and `render_pack` writes it into the prompt as `(as of ...)`), and every prompt
#: instructs its agent to cite the as-of of any figure it leans on -- so without this the gate
#: rejected an analyst for dating a live quote the way it was handed to it.
_ISO_DATETIME_RE = re.compile(
    r"(?<![\w.])\d{4}[-/]\d{1,2}[-/]\d{1,2}[T ]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?(?!\w)"
)

#: A clock time on its own -- `14:32`, `09:35:07`, `9:35 ET`, `2:30 pm`, `14:32 UTC`, `14:32+00:00`.
#:
#: Same class of defect as `_DATE_RE`, one unit down. A minute past `:10` is neither a bare year nor a
#: small integer, so `"as of 14:32 UTC"` used to yield the tokens `14` and `32` and degrade the stage
#: for saying when it looked. A live quote is the first evidence in this application whose as-of is a
#: *time* rather than a date -- a daily bar only ever needed `_DATE_RE` -- so this is what the
#: `live_quote` and `intraday` sections need in order for an ordinary sentence about them to pass.
#:
#: Deliberately narrow: the hours-and-minutes core requires a colon and exactly two minute digits, so
#: a ratio (`3:1`) and a score are not swallowed, and nothing without a colon can hide in here at all.
#: The optional meridiem, timezone label and UTC offset are consumed as part of the same match only
#: when they directly follow the time, so a bare `UTC` or a lone `+05:30` elsewhere in the prose is
#: untouched. Timezone abbreviations are listed longest-first so `EST` is not left as a stray `S`.
_TIME_RE = re.compile(
    r"(?<![\w.:])\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?"
    r"(?:\s?[ap]\.?m\.?)?"
    r"(?:\s?(?:UTC|GMT|EDT|EST|CDT|CST|MDT|MST|PDT|PST|ET|CT|MT|PT|Z))?"
    r"(?:\s?[+-]\d{2}:?\d{2})?"
    r"(?!\d)",
    re.IGNORECASE,
)

#: A parameterised indicator name -- `RSI(14)`, `SMA(200)`, `bb(20,2)`, `close_10_ema` -- or a
#: window written as a compound adjective, `200-day`, `14-period`, `50-week`.
#:
#: The digits here name *which* indicator is being discussed; they are not a reading of it. The
#: evidence pack's own `EvidenceItem.label` values are literally `"RSI(14)"` and `"SMA(200)"`
#: (see `app.agentdesk.evidence.DEFAULT_INDICATORS`), so an analyst using the label it was handed
#: was emitting an ungrounded `14` and `200` and being rejected for quoting the evidence correctly.
#:
#: Scoped deliberately: only digits inside parentheses that are *attached* to a preceding word, and
#: only digits bound to one of a closed list of window nouns. A bare parenthesised number in prose
#: ("(187.45)") is still scanned, so this cannot be used to smuggle a fabricated figure into parens.
#: The second alternative catches the same parenthesised parameters when a space sits between the
#: indicator name and its params -- `Bollinger Bands (20,2)`, `MACD (12, 26, 9)` -- which the attached
#: form above misses. It is scoped tighter than the attached form on purpose: its parentheses may hold
#: only integers, commas and spaces (`[\d,\s]`, no `.`), so a genuine decimal quoted in parentheses
#: after a word (`the close (319.70)`) is still scanned and cannot be smuggled past the gate, while an
#: integer parameter tuple a model spells with a space (`(20,2)` -> the token `202`) no longer leaks.
_INDICATOR_PARAM_RE = re.compile(
    r"(?:"
    r"\w\(\s*\d[\d,\s.]*\)"  # RSI(14), bb(20,2)
    r"|(?<=\w)\s\(\s*\d[\d,\s]*\)"  # Bollinger Bands (20,2): space before integer/tuple params
    r"|(?<![\w.])\d{1,4}[-\s](?:day|days|week|weeks|month|months|period|periods|bar|bars|session|sessions)\b"
    r")",
    re.IGNORECASE,
)


def _normalize_digits(raw: str) -> str:
    """Strip thousands separators and collapse a trailing `.0`/`.50`/`.500` to the shortest exact
    decimal, so `"1,234.50"` and `"1234.5"` produce the identical string."""
    text = raw.replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
        if text in ("", "-"):
            text = "0"
    return text


def numeric_tokens(text: str) -> tuple[str, ...]:
    """Every numeric literal in `text`, normalised so the same figure written two ways compares equal.

    Normalisation removes the presentational choices a model is free to make when restating a fact:
    thousands separators are stripped (`"1,234.50"` and `"1234.5"` both become `"1234.5"`), a leading
    currency symbol and a trailing `%` are dropped (the unit already lives on the matching
    `EvidenceItem`, not on the token), and a trailing run of decimal zeros collapses to the shortest
    exact form (`"100.0"` -> `"100"`).

    Three shapes of digit run are deliberately never returned, each because it produces far more false
    rejections than genuine fabrications caught:

    * **A bare four-digit year, 1900-2100** ("the 2024 filing") -- a filing year is not a measurement
      this gate has any business checking against an `EvidencePack`.
    * **An ordinal inside a date** ("the 21st") -- the digits preceding `st`/`nd`/`rd`/`th` are dropped
      before they are ever considered, rather than extracted and hoped to be grounded.
    * **Small integers, 0 through 10 inclusive.** A deliberate, named trade-off: in the prose this gate
      actually sees, a bare small integer is overwhelmingly a count or a rank ("3 of the 4 majors
      rose", "the second-largest holding") rather than a reported measurement, and treating every one
      as groundable produced false rejections on completely ordinary sentences far more often than it
      caught anything real. The cost is real: a model that fabricates a small measurement (an RSI of
      5, say) is not caught by this gate. That cost was judged smaller than the alternative.

    Five further constructs are removed from the text *before* any of that runs, because each one
    contains digits that name something rather than measure it -- see each pattern's own comment:
    markdown link targets (`_LINK_TARGET_RE`), whole ISO timestamps (`_ISO_DATETIME_RE`), whole
    calendar dates (`_DATE_RE`), bare clock times (`_TIME_RE`), and parameterised indicator names and
    window lengths (`_INDICATOR_PARAM_RE`). These matter more than they look: every system prompt
    instructs its agent to cite as-of dates and to refer to indicators by the labels the evidence
    uses, so without them the gate rejected agents for following their instructions correctly.

    **Order is load-bearing.** The timestamp scrub must run before the date scrub -- see
    `_ISO_DATETIME_RE`'s comment for the concrete failure when it does not -- and the time scrub after
    both, so a bare `14:32` is only reached once every timestamp it might have been part of is gone.
    """
    scrubbed = _LINK_TARGET_RE.sub("]", text)
    scrubbed = _ISO_DATETIME_RE.sub(" ", scrubbed)
    scrubbed = _DATE_RE.sub(" ", scrubbed)
    scrubbed = _TIME_RE.sub(" ", scrubbed)
    scrubbed = _INDICATOR_PARAM_RE.sub(" ", scrubbed)
    tokens: list[str] = []
    for match in _NUMBER_RE.finditer(scrubbed):
        tail = scrubbed[match.end() : match.end() + 3]
        if _ORDINAL_TAIL_RE.match(tail):
            continue

        raw_num = match.group("num")
        sign = match.group("sign") or ""
        currency = match.group("currency")
        percent = match.group("percent")

        is_plain = not sign and not currency and not percent and "," not in raw_num and "." not in raw_num
        if is_plain and len(raw_num) == 4 and 1900 <= int(raw_num) <= 2100:
            continue

        normalized = _normalize_digits(raw_num)
        if not sign and "." not in normalized and 0 <= int(normalized) <= 10:
            continue

        tokens.append(f"{sign}{normalized}")
    return tuple(tokens)


# ---------------------------------------------------------------------------
# The grounded set
# ---------------------------------------------------------------------------


def _clean_numeric_string(value: str) -> str:
    text = value.strip()
    for symbol in ("$", "€", "£", "%", ","):
        text = text.replace(symbol, "")
    return text


def _format_decimal(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
        if text in ("", "-"):
            text = "0"
    if text == "-0":
        text = "0"
    return text


#: The decimal precisions a grounded figure is *also* admitted at, coarsest last. A stage that states
#: a real number to fewer decimals than the evidence carries is rounding it, not inventing it.
_ROUNDING_QUANTA = (Decimal("0.1"), Decimal("0.01"))


def _add_grounded(values: set[str], value: Decimal) -> None:
    """Admit a grounded figure at its own precision, at each coarser decimal rounding that keeps a
    fractional part, and -- for a signed figure -- at its magnitude under the same rules.

    Two restatements of a grounded number are ordinary prose, not fabrication, and both used to degrade
    the stage that made them:

    * **Fewer decimals.** A derived percentage of `9.73` written back as `9.7%`, or a close of `127.31`
      as `127.3`, is a one-decimal rounding of a real number, but `"9.7" != "9.73"`. So each figure is
      added at its natural precision *and* at one- and two-decimal roundings (`ROUND_HALF_UP`, the way a
      person rounds).
    * **Sign carried in words.** A percentage change the pack holds as `-9.73` is written by a stage as
      "9.73% below"; a diluted EPS of `-15.23` as "a 15.23 loss"; a net income of `-3848152000` as "lost
      3,848,152,000". The direction lives in the prose, and this gate does not check direction -- only
      whether the number traces to the evidence -- so a signed figure's magnitude is admitted too.

    A rounding (or a magnitude's rounding) is admitted only while it keeps a decimal point. Collapsing a
    figure to a bare integer (`9.73 -> "10"`, `70.04 -> "70"`) is deliberately *not* admitted: it would
    hand away the gate's integer strictness and let a fabricated round number match any evidence figure
    that merely sits near it. An integer a stage writes is therefore still checked exactly -- only its
    fractional restatements are relaxed."""
    for signed in {value, abs(value)}:  # the figure, and its magnitude when it is negative
        values.add(_format_decimal(signed))
        for quantum in _ROUNDING_QUANTA:
            rounded = _format_decimal(signed.quantize(quantum, rounding=ROUND_HALF_UP))
            if "." in rounded:
                values.add(rounded)


def grounded_values(pack: EvidencePack) -> frozenset[str]:
    """Every figure a stage is entitled to state, drawn from `EvidenceItem.value` alone.

    `EvidenceSection.text` never contributes a value here -- see that field's own docstring and
    `app.agentdesk.models.EvidencePack`'s: free prose (a headline, a filing title, a rule expression)
    is content a stage must read but is not itself a fact it measured, and a number quoted *out of*
    that prose is exactly the confabulation this gate exists to catch, not evidence for it.

    **Simple arithmetic on two grounded figures is also admitted, across the whole pack.** For every
    ordered pair of items *anywhere in the pack*, the absolute difference, both directions of
    percentage change, and the ratio (as a bare quotient and as a percentage) are added too, each
    rounded to two decimal places. A stage comparing two figures it was handed ("the close is 27.08
    above the 50-day, +27.02%") or dividing them ("debt-to-equity of 3.87", "ROE of 151.90%") is doing
    arithmetic on grounded numbers, not inventing a third one -- and the number it states genuinely
    traces back to the pack, which is the only question this gate exists to answer. The ratio matters
    as much as the difference: a fundamentals analyst's debt-to-equity, ROE, ROA, leverage and margin
    are all quotients, none of them a difference or a percentage *change*, so without admitting ratios
    every one of them degraded the stage for dividing two figures it was handed.

    This deliberately spans sections. It used to be restricted to same-section pairs, on the theory
    that "a price minus a headline count" was meaningless and should not be admitted -- but that
    confused two different jobs. Whether a comparison is *semantically* meaningful is the reader's
    concern; whether a stated number was *fabricated* is this gate's, and a difference of two real
    evidence figures is not a fabrication however unlikely the pairing. The restriction had a large,
    concrete cost: an instrument's `Close` lives in the `Price` section while its moving averages live
    in `Indicators`, so "close is N above its 50-day" -- the single most common sentence a technical
    desk writes, and exactly what these presets' prompts ask for -- could never be grounded, and every
    stage that wrote it was degraded for stating arithmetic on the very numbers it was handed.

    **Every figure is admitted at its own precision and at coarser decimal roundings** -- see
    `_add_grounded`. A stage that writes a grounded `9.73%` as `9.7%` is rounding a real number, not
    fabricating one, and must not be degraded for it.
    """
    values: set[str] = set()
    pack_decimals: list[Decimal] = []
    for section in pack.sections:
        for item in section.items:
            try:
                decimal_value = Decimal(_clean_numeric_string(item.value))
            except InvalidOperation:
                continue
            _add_grounded(values, decimal_value)
            pack_decimals.append(decimal_value)

    for first, second in permutations(pack_decimals, 2):
        diff = (first - second).quantize(Decimal("0.01"))
        _add_grounded(values, diff)
        if second != 0:
            pct_change = ((first - second) / second * 100).quantize(Decimal("0.01"))
            _add_grounded(values, pct_change)
            # A *ratio* of two grounded figures is admitted for the same reason a difference is: it is
            # arithmetic on numbers the stage was handed, not a third invented one. The fundamentals
            # analyst's whole job is ratios -- debt-to-equity (liabilities / equity), ROE
            # (net income / equity), ROA, net margin, a leverage percentage -- none of which is a
            # difference or a percentage *change*, so without this every one of them degraded the stage
            # for dividing two evidence figures. Both the bare quotient (`3.87`) and its percentage form
            # (`151.90`) are added, since a ratio is stated either way.
            try:
                ratio = (first / second).quantize(Decimal("0.01"))
                _add_grounded(values, ratio)
                ratio_pct = (first / second * Decimal(100)).quantize(Decimal("0.01"))
                _add_grounded(values, ratio_pct)
            except InvalidOperation:
                pass
    return frozenset(values)


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def check(text: str, pack: EvidencePack) -> GroundingVerdict:
    """Whether every numeric token in `text` traces back to `pack`.

    Checked in this order: blank prose is `"empty_output"` regardless of the pack; a non-empty pack
    that nonetheless got no items cannot ground *any* number, so a cited figure against an empty pack
    is `"no_evidence"` rather than being lumped in with an ordinary mismatch; anything else with a
    token outside `grounded_values(pack)` is `"ungrounded_number"`, naming every offending token so
    `correction_prompt` can quote them back verbatim.
    """
    stripped = text.strip()
    if not stripped:
        return GroundingVerdict(
            ok=False, issues=(GroundingIssue(kind="empty_output", detail="the stage produced no prose"),)
        )

    tokens = numeric_tokens(text)

    if pack.is_empty and tokens:
        offending = ", ".join(sorted(set(tokens)))
        return GroundingVerdict(
            ok=False,
            issues=(
                GroundingIssue(
                    kind="no_evidence",
                    detail=(
                        "the evidence pack for this stage was empty, but the prose cites the following "
                        f"figure(s) as if they were measured: {offending}"
                    ),
                ),
            ),
            checked_tokens=len(tokens),
        )

    grounded = grounded_values(pack)
    offending_tokens = sorted({token for token in tokens if token not in grounded})
    if offending_tokens:
        return GroundingVerdict(
            ok=False,
            issues=(
                GroundingIssue(
                    kind="ungrounded_number",
                    detail=(
                        "the following figure(s) do not appear in the evidence pack, and are not a "
                        f"difference or percentage change between two figures that do: {', '.join(offending_tokens)}"
                    ),
                ),
            ),
            checked_tokens=len(tokens),
        )

    return GroundingVerdict(ok=True, checked_tokens=len(tokens))


def correction_prompt(verdict: GroundingVerdict) -> str:
    """The text appended to a rejected stage's own user turn on retry.

    Names every issue's own `detail` verbatim -- `GroundingIssue.detail` already documents itself as
    quoted back to the model this way -- so a re-ask names exactly what was rejected rather than
    telling the model, unhelpfully, that *something* about its last answer was wrong.
    """
    lines = ["Your previous answer failed an automated grounding check and must be corrected:"]
    for issue in verdict.issues:
        lines.append(f"- ({issue.kind}) {issue.detail}")
    lines.append(
        "Rewrite your answer. Every number you state must appear in the evidence above, or be a "
        "difference or percentage change computed directly from two figures that do. If you have "
        "nothing grounded to say, state plainly that the data is unavailable rather than estimating it."
    )
    return "\n".join(lines)


def schema_correction_prompt(exc: AgentResponseInvalid) -> str:
    """The text appended on retry after a response that could not be parsed into the required schema.

    Deliberately does not quote `exc.reason` back verbatim: it carries the model's own 4,000-character
    raw response, which would balloon the retry turn and re-feed the malformed text. A pointed
    reminder of the contract is what a transient formatting lapse -- a dropped required field, a
    stray sentence after the closing brace, an unclosed string -- actually needs.
    """
    return (
        "Your previous response could not be parsed into the required structure. Respond again with "
        "ONLY a single JSON object that validates against the schema: include every required field, "
        "close every string and brace, and write nothing before or after the object."
    )


# ---------------------------------------------------------------------------
# The retry loop
# ---------------------------------------------------------------------------

#: Backoff before re-attempting a *transient* error (a model/API overload, a non-zero CLI exit),
#: doubling per attempt and capped. A malformed response is retried immediately -- it is the model's
#: formatting, not the backend's health -- but an overloaded backend needs a moment to recover, and
#: re-firing into it instantly just earns the same error. The observed failure is a hard rate-limit
#: rejection (`is_error`, `duration_api_ms: 0`, `total_cost_usd: 0`) -- an instant 429/529 that clears
#: in tens of seconds, not single digits -- so the base is chosen for that, not for a brief blip.
#: `min(base * 2**(attempt-1), cap)`: ~8s, 16s, 32s, then held at the cap.
_TRANSIENT_BACKOFF_BASE_S = 8.0
_TRANSIENT_BACKOFF_CAP_S = 60.0


@dataclass(frozen=True)
class GroundedResult[T: BaseModel]:
    """What `run_grounded` hands back: the structured value a caller actually wants, the verdict that
    let it out the door, and the full accounting of what producing it cost."""

    value: T
    verdict: GroundingVerdict
    calls: tuple[AgentCall, ...]
    budget: AgentBudget


def run_grounded[T: BaseModel](
    *,
    role: AgentRole,
    system: str,
    user: str,
    output_format: type[T],
    prose_of: Callable[[T], str],
    pack: EvidencePack,
    settings: Settings,
    budget: AgentBudget,
    model: str = DEFAULT_MODEL,
    max_attempts: int = MAX_GROUNDING_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> GroundedResult[T]:
    """Call, check, and -- on failure -- re-ask with the failure quoted back, up to `max_attempts`.

    Every attempt's `AgentCall` is kept, in order, and `budget` is threaded through each call so the
    accumulated spend of a rejected-then-retried stage is visible on the run, not just the spend of
    whichever attempt happened to be accepted. A retry is always built from the *original* `user`
    plus that attempt's own `correction_prompt` -- never from the previous attempt's already-corrected
    turn -- so the prompt does not grow by one more copy of the evidence pack on every retry.

    **Never raises for a grounding failure.** A stage that still fails on its last attempt is returned
    with `verdict.ok=False` and `verdict.degraded=True`, carrying whatever the model actually produced
    -- see `app.agentdesk.models.StageState`'s own `"degraded"` state, which this is the source of.
    `BudgetExhausted` and `AgentUnavailable` are not grounding failures; they propagate to the caller
    unchanged, exactly as `app.agents.client.call_structured` raises them.
    """
    if max_attempts < 1:
        raise ValueError(f"max_attempts must be at least 1, got {max_attempts}")

    calls: list[AgentCall] = []
    current_budget = budget
    value: T | None = None
    verdict: GroundingVerdict | None = None
    last_invalid: AgentResponseInvalid | None = None
    last_error: AgentUnavailable | None = None

    for attempt in range(1, max_attempts + 1):
        # The most recent failure drives the retry note: a response that would not parse at all is
        # corrected on the schema, one that parsed but failed grounding is corrected on the numbers,
        # and a first attempt (or one after a transient transport blip, which is nothing to correct)
        # gets the bare user turn. Both corrections are built from the *original* `user`, never a
        # previous corrected turn, so the evidence pack is not recopied each retry.
        if last_invalid is not None:
            turn = f"{user}\n\n{schema_correction_prompt(last_invalid)}"
        elif verdict is not None:
            turn = f"{user}\n\n{correction_prompt(verdict)}"
        else:
            turn = user

        try:
            value, call, current_budget = call_structured(
                role=role,
                system=system,
                user=turn,
                output_format=output_format,
                model=model,
                settings=settings,
                budget=current_budget,
            )
        except AgentResponseInvalid as exc:
            # A malformed response is a transient formatting lapse: re-ask with a schema correction
            # within the same attempt budget rather than failing the whole pipeline on one bad turn.
            last_invalid = exc
            last_error = exc
            continue
        except AgentTransientError as exc:
            # The transport reached the model but that one call errored (a non-zero CLI exit, an
            # `is_error` envelope): re-attempt the same turn -- there is no response to correct.
            # A systemic `AgentUnavailable`/`BudgetExhausted` (no credential, a refusal, the cap) is
            # not caught here and propagates unchanged, exactly as before. Unlike a malformed response,
            # this one waits before retrying: the failure is the backend's health, not the model's
            # formatting, and re-firing instantly into an overloaded backend just earns the same error.
            last_error = exc
            if attempt < max_attempts:
                sleep(min(_TRANSIENT_BACKOFF_BASE_S * 2 ** (attempt - 1), _TRANSIENT_BACKOFF_CAP_S))
            continue

        last_invalid = None
        calls.append(call)
        verdict = check(prose_of(value), pack).model_copy(update={"attempts": attempt})
        if verdict.ok:
            return GroundedResult(value=value, verdict=verdict, calls=tuple(calls), budget=current_budget)

    if value is None:
        # Every attempt raised a retryable error -- there is no value to return degraded, so surface
        # the last failure to the caller, which fails this one stage (and, per `run_pipeline`, blocks
        # the stages downstream of it) rather than fabricating a report the model never produced.
        assert last_error is not None  # value is None only because every attempt raised
        raise last_error

    assert verdict is not None  # a non-None value always set a verdict alongside it
    degraded = verdict.model_copy(update={"degraded": True})
    return GroundedResult(value=value, verdict=degraded, calls=tuple(calls), budget=current_budget)
