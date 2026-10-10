"""The candidate dossier: everything a person needs to decide whether to shelve or reject a card.

**The problem this module answers.** Before this module existed, the approval screen showed a hash
(`g1859-fd7c2c196f35`) and four raw numbers. Nobody can decide anything from that -- not what the
strategy does, not where it came from, not whether its numbers mean anything, not what else already on
the shelf it overlaps with. :func:`compose_dossier` builds the one object that answers all four
questions from data already on disk, and only from data already on disk: every number in a
:class:`Dossier` is either copied verbatim from a ledger row / a generation's `OUTCOME.json` standing,
or a plain arithmetic derivation of numbers copied that way (a percentile, a Jaccard index, a median of
medians). Nothing here is model prose and nothing here is invented -- see "Deterministic, not
generated" in this programme's house rules. Two calls against the same on-disk state produce
byte-identical output.

**The central honesty requirement, and why `context` exists at all.** Across every candidate this loop
has ever scored -- 2,374 ledger rows at last count, including pure random ones -- the median holdout
excess is comfortably positive and the overwhelming majority of candidates post a positive holdout
median. A card's own "+14.88% holdout" is therefore *inside the field's ordinary range*, not evidence
that the card beats a coin flip from the same generator. `context` exists specifically to put the
field-wide number on screen next to the card's own number, every time, so a reader cannot read a
positive holdout figure as meaningful without also seeing how unremarkable a positive holdout figure
is. `cautions`' `holdout-does-not-discriminate` rule states this in words, from the same numbers.

**Every `context` field states its own population, and two populations are exposed side by side on
purpose -- see `Context`'s own docstring for the full accounting.** `field_..._same_purpose` figures
answer "what does this card's own purpose's field look like" (SPEC.md's own instruction: `context` is
"computed over ledger rows of the same purpose") and are the fair peer comparison a UI should put
beside a card's own number. `field_..._all_purposes` figures answer "how does the whole search behave,
every book together" and are what the central honesty numbers above (+15.02%, 94.3%, computed over
2,364 rows with a measured holdout) are actually stated over, and what
`cautions.holdout-does-not-discriminate`'s field-wide clause quotes. **These two populations differ by
as much as 2.5x on real data** -- this repo's live ledger has a roth-only selection median-of-medians
of +2.24% against an all-purpose +5.65% -- so a version of this module that collapsed the two into one
unqualified `_all_time` name was silently showing a reader the wrong one of the two roughly half the
time. `candidates_ever_run` is the one figure that is neither row-scoped nor purpose-scoped: it is
`app.evolution.ledger.Ledger.distinct_candidates()`'s own count, matching the `m` the loop's actual
Benjamini-Hochberg correction uses (`Ledger.q_values()`), which is what `cautions.q-above-5pct`'s "the
N hypotheses this search tested" sentence names. `percentile_all_time` is purpose-scoped like the
`same_purpose` figures, for the same peer-comparison reason, but is a *row-rank*, not a field
statistic -- see its own docstring on `Context` and `_percentile_all_time`'s docstring for exactly how
it is computed and why it must be this card's own recorded seat-request figure, not whichever
generation the genome was most recently re-scored in.

**`discipline` is not a description of the rule, and this module does not treat it as one.** A live
comparison of two library cards (`g1815-d05786e4c611` -> `g1823-e2a3d5060b09`, recorded as a mutation
of one another) found every field byte-identical except `agent_id`, `display_name` and `discipline`:
the same rule, the same universe, the same every numeric trait, labelled `"breakout"` on one card and
`"mean-reversion"` on the next. Wider inspection of the pending-seat set found a single shared
entry/exit template (`close > sma(N) and ema(N) crosses_above ema(N)` / `ema(N) crosses_below ema(N)`,
parameters masked) across all 25 outstanding requests. `discipline` is therefore surfaced here only as
`discipline_label`, alongside a note stating plainly that it is self-declared and known to disagree
with the rule -- never as `headline`'s lead clause, and never anywhere that would read as a derived
description. `headline` and the internal rule-summary it uses are built by parsing `entry`/`exit`
themselves (`app.rules.grammar`), never by reading `discipline`. `cautions.label-does-not-match-rule`
and `cautions.template-is-not-distinct` are the two rules that turn this finding into a per-card,
deterministic warning: the first flags a *specific* mislabelled sibling by id, the second flags that
the rule's own shape is not distinctive within the pending/shelved set, independent of any label.

**Copy, never recompute.** Every figure in `evidence` is copied from a `Standing` already computed by
`app.tournament.results` / `app.evolution.feedback.read_standings` and already written, unmodified, to
`gen{N:04d}/OUTCOME.json`. This module never re-scores a backtest, never re-derives a median from raw
trades, and never touches `app.tournament.scoring`. The only original arithmetic here is explicitly
derived context (percentiles, field medians, Jaccard overlap) -- and every such field says in its own
name what population it was computed over.

**`null` is never zero.** An unmeasured figure (a card that never ran a holdout window, a q-value that
could not be computed for want of trades) is `None` throughout this module and serializes to JSON
`null`. Nothing here substitutes `0`, `0.0`, or an empty string for "not measured" -- the frontend's
`formatPctFraction`/`formatSignedPctFraction` render `null` as an em dash for exactly this reason, and a
`0.00%` in its place would be read as a measured, unfavourable number rather than as "no measurement
exists."

**Where the numbers come from, module by module.** `evidence` and the generation-scoped half of
`context` are read through `app.evolution.history` (which already caches per generation directory --
see that module's own docstring). The field-wide half of `context` is read through
`app.evolution.ledger.Ledger`, cached in this module with an mtime+size check on `ledger.jsonl` (see
`_cached_ledger`) so a page of many dossiers does not re-read and re-parse a multi-megabyte JSONL file
once per card. `origin` is read from the generation's own `PLAN.md`, which already records each
genome's origin kind, parents and pre-run notes verbatim -- parsed here rather than re-derived, since
inventing a mechanism description from `origin_kind` alone risks stating something about a specific
operator (e.g. what a crossover inherits from which parent) that the operator's own implementation does
not actually do. `overlap` and the two new label/template cautions read every other seat request's own
card off disk to compare tickers and rule bodies directly.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import re
import statistics
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.config import Settings
from app.evolution import history
from app.evolution.ledger import Ledger, LedgerEntry
from app.evolution.models import (
    NOISE_FLOOR_PP,
    PendingSeat,
    Standing,
    content_digest,
    generated_tier_dir,
    loop_root,
)
from app.evolution.promotion import read_pending_seats
from app.indicators.registry import get as _indicator_spec
from app.rules import grammar
from app.rules.grammar import RuleSyntaxError
from app.rules.nodes import (
    Arith,
    BoolExpr,
    BoolOp,
    BoolOpKind,
    CompareOp,
    Comparison,
    Cross,
    CrossDir,
    IndicatorRef,
    Not,
    NumExpr,
    PriceField,
    PriceRef,
)
from app.rules.nodes import (
    Literal as RuleLiteral,
)

__all__ = [
    "CardSummary",
    "Caution",
    "Context",
    "Dossier",
    "EvidenceRow",
    "Origin",
    "Overlap",
    "OverlapEntry",
    "WhatADecisionDoes",
    "WhatItDoes",
    "card_summary",
    "compose_dossier",
    "headline",
    "short_id",
    "universe_note",
]


class _Frozen(BaseModel):
    """Matches `app.evolution.models._Frozen`: frozen, no extra fields, whitespace-stripped -- this
    module's models are a read-only HTTP contract, never mutated after construction."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Response shapes -- see `SPEC.md`'s "Contract: the dossier" for the field-by-field JSON this mirrors.
# ---------------------------------------------------------------------------


class WhatItDoes(_Frozen):
    """Plain-English rendering of the card's rule, composed from the card JSON via
    `app.rules.grammar` -- never from `discipline` (see this module's own docstring)."""

    universe: tuple[str, ...]
    universe_note: str
    entry_plain: str
    exit_plain: str
    risk_plain: str
    sizing_plain: str
    raw: dict[str, Any]


class Origin(_Frozen):
    """Where this genome came from, read from its own generation's `PLAN.md` -- never inferred from
    `origin_kind` alone. `generation`/`origin_kind` are `None` only when no plan record could be
    found for this id (a hand-authored library card that was never a loop genome, or a `PLAN.md`
    this module could not read)."""

    generation: int | None
    origin_kind: str | None
    parents: tuple[str, ...]
    note: str


class EvidenceRow(_Frozen):
    """One generation this genome was scored in. Every numeric field here is copied verbatim from
    that generation's `Standing` / `GenerationOutcome` -- never recomputed."""

    generation: int
    round_id: str
    rank: int
    field_size: int
    windows: tuple[str, ...]
    median_excess: Decimal | None
    worst_excess: Decimal | None
    hit_rate: float | None
    total_trades: int
    holdout_median_excess: Decimal | None
    holdout_windows: tuple[str, ...]
    q_value: float | None


class Context(_Frozen):
    """What the same numbers look like across the whole field -- every figure here is a row-based
    statistic over `data/loop/ledger.jsonl` (one row per (genome, generation) actually scored, *not*
    deduped to one row per distinct genome; see `_row_stats`'s own docstring for why raw rows are the
    right population), except `candidates_ever_run` and `percentile_all_time`, called out below.

    **Every field name states its own population; nothing here is ambiguous between "this card's
    purpose" and "every purpose the loop has ever searched".** That distinction used to be collapsed
    into unqualified `_all_time` names, and it matters by a factor of 2.5x on real data: this repo's
    live ledger has a roth-only selection median-of-medians of +2.24% against an all-purpose figure of
    +5.65% (see `_row_stats` and this module's own docstring). A UI comparing a roth card's own number
    against the wrong one of these two would be quietly making the card look far better, or far worse,
    than its actual peers say it is.

    * `field_..._same_purpose` -- the fair peer comparison: this card's own purpose's rows only. This
      is what a UI should show beside the card's own median/holdout number, per SPEC.md's own
      instruction that `context` is "computed over ledger rows of the same purpose".
    * `field_..._all_purposes` -- the whole-search view, every purpose's rows together. This is the
      population the central honesty numbers this programme was built around are stated over (a
      +15.02% all-purpose holdout median, 94.3% positive) and is what `cautions.holdout-does-not-
      discriminate`'s "of everything this search has ever tried" clause uses -- a statement about how
      the search's own generator behaves is more informative pooled across both books than split by
      one purpose's few hundred rows.
    * `holdout_measurements_same_purpose` / `_all_purposes` -- how many rows each `holdout_positive_
      fraction_*`/`holdout_median_*` figure was actually computed over (a holdout figure is `None` on
      a row that never ran a holdout window, so this is *not* the same as the purpose's total row
      count). Pair a fraction with *this* count in prose, never with `candidates_ever_run` -- the two
      are different populations (rows-with-a-holdout-measurement vs. distinct genomes) that happened
      to get paired incorrectly in an earlier version of this module.
    """

    field_median_excess_this_generation: Decimal | None
    field_median_excess_same_purpose: Decimal | None
    field_median_excess_all_purposes: Decimal | None
    field_holdout_median_same_purpose: Decimal | None
    field_holdout_median_all_purposes: Decimal | None
    field_holdout_positive_fraction_same_purpose: float | None
    field_holdout_positive_fraction_all_purposes: float | None
    holdout_measurements_same_purpose: int
    holdout_measurements_all_purposes: int
    percentile_all_time: float | None
    """This card's own recorded selection median (see `_card_reference_values`) ranked strictly below
    every *other* same-purpose row -- `count(v < card_median) / n`. `None` when this card has no
    recorded median of its own yet."""
    candidates_ever_run: int
    """Distinct genomes across the *whole* ledger, every purpose -- deliberately not row-scoped and
    not purpose-scoped. Matches `app.evolution.ledger.Ledger.distinct_candidates()`'s own meaning
    exactly (this module calls no other computation for it), because that is the same `m` the loop's
    own Benjamini-Hochberg correction (`Ledger.q_values()`) actually uses -- the "hypotheses this
    search tested" the `q-above-5pct` caution's text names is this figure, not a row count."""
    generations_with_outcomes: int
    noise_floor_pp: Decimal
    margin_over_noise_pp: Decimal | None


class Caution(_Frozen):
    code: str
    severity: Literal["blocking", "serious", "note"]
    text: str


class OverlapEntry(_Frozen):
    genome_id: str
    headline: str
    shared_tickers: tuple[str, ...]
    jaccard: float


class Overlap(_Frozen):
    with_shelved: tuple[OverlapEntry, ...]
    with_seated: tuple[OverlapEntry, ...]
    note: str


class WhatADecisionDoes(_Frozen):
    shelve: str
    reject: str
    seat: str
    retire: str


#: Fixed, deterministic, identical on every dossier -- see `SPEC.md`'s "what_a_decision_does" block.
#: The paper desk is simulated and holds no real money; every one of the four sentences below says so
#: or says nothing that implies otherwise, per this programme's house rules.
_WHAT_A_DECISION_DOES = WhatADecisionDoes(
    shelve="Keeps the card, names it, and tracks it. It places no orders and does not join the desk.",
    reject="Declines it permanently. The loop will not re-file this genome even if it clears the gate again.",
    seat="Adds it to the simulated paper desk's roster. The desk holds no real money and approving places no order.",
    retire="Removes it from the shelf without ever seating it. Also permanent.",
)

#: Attached to every dossier's `discipline_label_note` verbatim -- see this module's own docstring for
#: the `g1815`/`g1823` comparison that establishes this as a measured fact, not a suspicion.
_DISCIPLINE_LABEL_NOTE = (
    "Self-declared tag from the card's own genome record. It is not derived from the entry/exit rule "
    "and is known to disagree with it on real cards -- an identical rule and universe has been seen "
    "labelled both 'breakout' and 'mean-reversion' across two generations. Read `headline` and "
    "`what_it_does` for what the rule actually does; see the `label-does-not-match-rule` caution when "
    "this specific card has a mislabelled sibling."
)


class Dossier(_Frozen):
    genome_id: str
    agent_id: str
    headline: str
    short_id: str
    purpose: str
    discipline_label: str
    discipline_label_note: str
    stage: str | None
    requested_at: dt.datetime | None

    what_it_does: WhatItDoes
    thesis: str

    origin: Origin
    evidence: tuple[EvidenceRow, ...]
    context: Context
    cautions: tuple[Caution, ...]
    overlap: Overlap
    what_a_decision_does: WhatADecisionDoes


class CardSummary(_Frozen):
    """Just the naming fields for one genome -- `card_summary`'s return shape.

    A cheap alternative to `compose_dossier` for a caller that only needs to *name* a row (e.g. a
    25-row pending-seats list), not decide it. Every field here is also present on the corresponding
    full `Dossier` for the same genome and is guaranteed byte-identical to it (`headline` in
    particular is built by the same `headline()` call `compose_dossier` makes) -- see
    `tests/test_evolution_dossier.py::TestCardSummary::test_headline_matches_the_full_dossier`.
    """

    genome_id: str
    headline: str
    short_id: str
    discipline_label: str
    discipline_label_note: str
    rule_template_id: str
    """`_rule_template_id`'s key for this card's own (numbers-masked) entry/exit shape -- two
    `CardSummary`s sharing this value ran the identical template with different parameters. Grouping
    a list of summaries by this field is what lets a caller flag `template-is-not-distinct`-style
    crowding across a whole queue without running `compose_dossier`'s per-row disk scan for each one."""


def card_summary(genome_id: str, *, settings: Settings) -> CardSummary | None:
    """The naming fields alone for `genome_id`, without composing a full `Dossier` -- for a caller
    (e.g. `GET /api/competition/loop/pending-seats`, which can return up to 25 rows) that needs every
    row to show a readable name and needs it cheaply, not the full evidence/context/cautions payload.

    `None` under exactly the same condition `compose_dossier` returns `None` under -- no card found
    for `genome_id` anywhere this module looks -- and never raises for a malformed or missing card, so
    one bad row's card cannot blank an entire queue that is otherwise fine.

    Reuses `_find_card`'s and `_read_json`'s per-process, mtime-signature-checked cache (`_CARD_CACHE`,
    see that cache's own docstring), so calling this once per row of a 25-row list reads each distinct
    card file at most once, not 25 times, exactly like `_cached_ledger` does for the field-wide
    statistics `compose_dossier` computes.
    """
    card = _find_card(genome_id, settings=settings)
    if card is None:
        return None
    universe = tuple(str(t) for t in (card.get("universe") or ()))
    purpose = str(card.get("purpose") or "")
    return CardSummary(
        genome_id=genome_id,
        headline=headline(
            entry_expr=card.get("entry"), exit_expr=card.get("exit"), universe=universe, purpose=purpose
        ),
        short_id=short_id(genome_id),
        discipline_label=str(card.get("discipline") or ""),
        discipline_label_note=_DISCIPLINE_LABEL_NOTE,
        rule_template_id=_rule_template_id(card),
    )


# ---------------------------------------------------------------------------
# Naming -- `SPEC.md`'s "Naming" section. Exported standalone so the frontend and other backend
# surfaces apply the identical rule rather than each growing their own.
# ---------------------------------------------------------------------------


def short_id(genome_id: str) -> str:
    """`"g1859-fd7c2c196f35"` -> `"g1859·fd7c"` -- generation prefix + first 4 hex digits of the
    content digest, rendered as a subordinate id chip. Uses `content_digest` (never recomputes the
    split rule it already encodes) and returns `genome_id` unchanged when it carries no `-` separator
    at all, matching `content_digest`'s own tolerance for a malformed id."""
    digest = content_digest(genome_id)
    if digest == genome_id:
        return genome_id
    prefix = genome_id[: -(len(digest) + 1)]
    return f"{prefix}·{digest[:4]}"


def _fmt_num(value: float | str) -> str:
    """No trailing `.0` on a whole float -- matches `app.rules.grammar._fmt_number`'s own convention,
    duplicated rather than imported since that name is private to its module."""
    if isinstance(value, str):
        return value
    if float(value).is_integer():
        return str(int(value))
    return str(value)


class _UntranslatableError(Exception):
    """Raised internally when this module has no plain-English phrase for a node the parser accepted.
    Always caught at the top of the translation it occurred in and turned into a raw-expression
    fallback -- never lets an unrecognised indicator crash a dossier."""


def _arg(ref: IndicatorRef, index: int) -> float | str:
    """`ref.args[index]`, or the registry's own default for that parameter when the rule text omitted
    a trailing argument (the grammar accepts `sma()` with no arguments; the registry, not the parser,
    owns what the omitted value defaults to -- see `app.rules.grammar._parse_indicator_call`'s own
    docstring)."""
    if index < len(ref.args):
        return ref.args[index]
    spec = _indicator_spec(ref.name)
    if spec is not None and index < len(spec.params):
        # `ParamSpec.default` is `Any`; naming the type is what makes the declared return real.
        default: float | str = spec.params[index].default
        return default
    raise _UntranslatableError(f"{ref.name} is missing argument {index} with no known default")


# ---------------------------------------------------------------------------
# Rule summary -- a compact, headline-length description of what entry/exit actually do. Never reads
# `discipline`. Falls back to the raw expression, never to an invented category, when it cannot
# recognise the shape.
# ---------------------------------------------------------------------------


def _iter_bool_nodes(node: BoolExpr) -> Iterator[BoolExpr]:
    """Every `BoolExpr` node in `node`'s tree, `node` itself included -- the boolean-only counterpart
    of `app.rules.grammar.indicator_refs`' walk, needed here to find every `Cross`/`Comparison` a rule
    contains without re-parsing it more than once."""
    yield node
    match node:
        case Not(operand):
            yield from _iter_bool_nodes(operand)
        case BoolOp(_, operands):
            for operand in operands:
                yield from _iter_bool_nodes(operand)
        case Comparison() | Cross():
            pass


def _is_trend_filter(node: Comparison) -> bool:
    """`close`/`open` compared against a bare `sma`/`ema` -- the "is the market in the right regime"
    shape this loop's proposer writes constantly (`close > sma(135)`). Used both by `_rule_summary`
    (headline text) and by `_phrase_comparison` (the "(a rising-market filter)" annotation) so the two
    never disagree about what counts as a filter."""
    return (
        isinstance(node.left, PriceRef)
        and node.left.field in (PriceField.CLOSE, PriceField.OPEN)
        and isinstance(node.right, IndicatorRef)
        and node.right.name in ("sma", "ema")
        and node.right.output is None
    )


def _rule_summary(entry_expr: Any, exit_expr: Any) -> str:
    """A compact, deterministic description of what `entry_expr` does, for `headline()`.

    **Never derived from `discipline`.** See this module's own docstring for the measured proof that
    `discipline` is a self-declared tag that can and does disagree with the rule it is attached to.
    This function reads only `entry`/`exit`, parsed through `app.rules.grammar` -- the same closed,
    `eval`-free grammar the rule engine itself evaluates.

    Recognises exactly two shapes explicitly (a same-family moving-average crossover, and a
    trend/regime filter against a bare `sma`/`ema`) because those are, respectively, the only cross
    and the only filter every one of this loop's 25 outstanding pending-seat cards actually contains --
    see this module's docstring for the masked-template measurement. Anything else falls back first to
    a full plain-English rendering of the whole entry condition, and only falls back to the raw
    expression text if that rendering also fails (an indicator this module has no phrase for, or a
    rule that does not parse at all) -- never to an invented category.
    """
    if not isinstance(entry_expr, str) or not entry_expr.strip():
        return "No entry rule is defined"
    try:
        entry_ast = grammar.parse(entry_expr)
    except RuleSyntaxError:
        return entry_expr

    crosses = [node for node in _iter_bool_nodes(entry_ast) if isinstance(node, Cross)]
    filters = [
        node
        for node in _iter_bool_nodes(entry_ast)
        if isinstance(node, Comparison) and _is_trend_filter(node)
    ]

    parts: list[str] = []
    if crosses:
        cross = crosses[0]
        left, right = cross.left, cross.right
        if (
            isinstance(left, IndicatorRef)
            and isinstance(right, IndicatorRef)
            and left.name == right.name
            and left.output is None
            and right.output is None
            and left.name in ("sma", "ema")
        ):
            kind = "EMA" if left.name == "ema" else "SMA"
            fast, slow = _fmt_num(_arg(left, 0)), _fmt_num(_arg(right, 0))
            parts.append(f"{kind} {fast}/{slow} crossover")
        else:
            try:
                verb = "crosses above" if cross.direction == CrossDir.ABOVE else "crosses below"
                parts.append(f"{_phrase_num(left)} {verb} {_phrase_num(right)}")
            except _UntranslatableError:
                pass

    if filters:
        try:
            period = _fmt_num(_arg(filters[0].right, 0))  # type: ignore[arg-type]
            parts.append(f"{period}-day regime filter")
        except _UntranslatableError:
            pass

    if parts:
        return ", ".join(parts)

    try:
        return _phrase_bool(entry_ast, entry_crosses={}, in_conjunction=False)
    except _UntranslatableError:
        return entry_expr


def headline(*, entry_expr: Any, exit_expr: Any, universe: Sequence[str], purpose: str) -> str:
    """`"{what the rule does} · {top3 tickers}{+N} · {Purpose}"`.

    The first clause is `_rule_summary(entry_expr, exit_expr)` -- what the parsed rule actually does --
    never `discipline`. See this module's docstring for why: `discipline` is a self-declared label that
    has been observed to disagree with an identical rule's own behaviour.
    """
    summary = _rule_summary(entry_expr, exit_expr)
    tickers = list(universe)
    if tickers:
        top3 = "/".join(tickers[:3])
        extra = len(tickers) - 3
        ticker_part = f"{top3} +{extra}" if extra > 0 else top3
    else:
        ticker_part = "no tickers"
    purpose_label = purpose.strip().capitalize() if purpose and purpose.strip() else "Unlabeled purpose"
    return f"{summary} · {ticker_part} · {purpose_label}"


# ---------------------------------------------------------------------------
# Plain-English rule translation -- entry_plain / exit_plain. AST-driven (app.rules.grammar / .nodes),
# never string-pattern-matched, so it covers every combination the grammar accepts, not just the shapes
# seen in today's library. Falls back to the raw expression, and says so, for anything it cannot
# translate -- it never invents a description for an indicator it doesn't recognise.
# ---------------------------------------------------------------------------

_PRICE_PHRASES: dict[PriceField, str] = {
    PriceField.OPEN: "the opening price",
    PriceField.HIGH: "the high",
    PriceField.LOW: "the low",
    PriceField.CLOSE: "the price",
    PriceField.VOLUME: "the volume",
}

_COMPARE_WORDS: dict[CompareOp, str] = {
    CompareOp.LT: "is below",
    CompareOp.LTE: "is at or below",
    CompareOp.GT: "is above",
    CompareOp.GTE: "is at or above",
    CompareOp.EQ: "equals",
    CompareOp.NEQ: "does not equal",
}

_ARITH_WORDS = {"+": "plus", "-": "minus", "*": "times", "/": "divided by"}


def _phrase_indicator(ref: IndicatorRef) -> str:
    """One indicator output in plain English. Explicit per indicator + output combination -- see
    `backend/app/indicators/*.py` for what each one actually measures; nothing here is guessed. Raises
    `_UntranslatableError` for any indicator/output this module has not been taught, so the caller
    falls back to the raw expression rather than a made-up description."""
    name, output = ref.name, ref.output
    if name in ("sma", "ema") and output is None:
        return f"the {_fmt_num(_arg(ref, 0))}-day average"
    if name == "rsi" and output is None:
        return f"the {_fmt_num(_arg(ref, 0))}-day RSI"
    if name == "atr" and output is None:
        return f"the {_fmt_num(_arg(ref, 0))}-day average true range (a volatility measure)"
    if name == "bb":
        period, stddev = _fmt_num(_arg(ref, 0)), _fmt_num(_arg(ref, 1))
        if output == "upper":
            return f"the upper band of a {period}-day, {stddev}-deviation Bollinger channel"
        if output == "lower":
            return f"the lower band of a {period}-day, {stddev}-deviation Bollinger channel"
        if output == "mid":
            return f"the {period}-day average (the middle of a Bollinger channel)"
    if name == "vwap":
        anchor = ref.args[0] if ref.args else "session"
        if anchor == "session":
            return "the volume-weighted average price for the session"
        return f"the volume-weighted average price anchored to {anchor}"
    if name == "swing" and output in ("high", "low"):
        return f"the last confirmed {_fmt_num(_arg(ref, 0))}-bar swing {output}"
    if name == "rsi_at_swing" and output in ("high", "low"):
        return f"the RSI reading at the last confirmed {_fmt_num(_arg(ref, 1))}-bar swing {output}"
    if name == "macd_at_swing" and output in ("high", "low"):
        return f"the MACD line at the last confirmed {_fmt_num(_arg(ref, 3))}-bar swing {output}"
    if name == "macd":
        label = {"macd": "MACD line", "signal": "MACD signal line", "hist": "MACD histogram"}.get(
            output or "", "MACD"
        )
        return f"the {label}"
    raise _UntranslatableError(
        f"no plain-English phrase is defined for {name}" + (f"_{output}" if output else "")
    )


def _phrase_num(node: NumExpr) -> str:
    match node:
        case RuleLiteral(value):
            return _fmt_num(value)
        case PriceRef(field):
            return _PRICE_PHRASES[field]
        case IndicatorRef():
            return _phrase_indicator(node)
        case Arith(left, op, right):
            return f"{_phrase_num(left)} {_ARITH_WORDS[op.value]} {_phrase_num(right)}"
    raise _UntranslatableError("unsupported numeric expression")


def _phrase_comparison(node: Comparison, *, in_conjunction: bool) -> str:
    text = f"{_phrase_num(node.left)} {_COMPARE_WORDS[node.op]} {_phrase_num(node.right)}"

    if (
        isinstance(node.left, IndicatorRef)
        and node.left.name == "rsi"
        and node.left.output is None
        and isinstance(node.right, RuleLiteral)
    ):
        threshold = node.right.value
        if node.op in (CompareOp.LT, CompareOp.LTE) and threshold <= 35:
            text += " (oversold territory)"
        elif node.op in (CompareOp.GT, CompareOp.GTE) and threshold >= 65:
            text += " (overbought territory)"

    if in_conjunction and _is_trend_filter(node):
        if node.op in (CompareOp.GT, CompareOp.GTE):
            text += " (a rising-market filter)"
        elif node.op in (CompareOp.LT, CompareOp.LTE):
            text += " (a falling-market filter)"

    return text


def _phrase_cross(node: Cross, *, entry_crosses: Mapping[tuple[NumExpr, NumExpr], CrossDir]) -> str:
    """`"crosses above"`/`"crosses below"`, upgraded to `"crosses back above"`/`"crosses back below"`
    when this exact `(left, right)` pair crossed the *opposite* direction somewhere in the entry rule --
    exactly the case an exit rule that reverses its own entry's crossover is (`ema(13) crosses_below
    ema(21)` exiting a position an `ema(13) crosses_above ema(21)` entry opened). `entry_crosses` is
    empty when rendering the entry itself, so an entry's own crosses are never annotated "back"."""
    verb = "crosses above" if node.direction == CrossDir.ABOVE else "crosses below"
    opposite = CrossDir.BELOW if node.direction == CrossDir.ABOVE else CrossDir.ABOVE
    if entry_crosses.get((node.left, node.right)) == opposite:
        verb = "crosses back " + verb.rsplit(" ", 1)[-1]
    return f"{_phrase_num(node.left)} {verb} {_phrase_num(node.right)}"


def _phrase_bool(
    node: BoolExpr,
    *,
    entry_crosses: Mapping[tuple[NumExpr, NumExpr], CrossDir],
    in_conjunction: bool,
) -> str:
    match node:
        case Comparison():
            return _phrase_comparison(node, in_conjunction=in_conjunction)
        case Cross():
            return _phrase_cross(node, entry_crosses=entry_crosses)
        case Not(operand):
            return f"not ({_phrase_bool(operand, entry_crosses=entry_crosses, in_conjunction=False)})"
        case BoolOp(op, operands):
            child_in_conjunction = op == BoolOpKind.AND and len(operands) > 1
            parts = [
                _phrase_bool(operand, entry_crosses=entry_crosses, in_conjunction=child_in_conjunction)
                for operand in operands
            ]
            joiner = " and " if op == BoolOpKind.AND else " or "
            return joiner.join(parts)
    raise _UntranslatableError("unsupported boolean expression")


def _entry_crosses(expression: str) -> dict[tuple[NumExpr, NumExpr], CrossDir]:
    try:
        tree = grammar.parse(expression)
    except RuleSyntaxError:
        return {}
    return {
        (node.left, node.right): node.direction
        for node in _iter_bool_nodes(tree)
        if isinstance(node, Cross)
    }


def _translate(
    expression: str, *, entry_crosses: Mapping[tuple[NumExpr, NumExpr], CrossDir]
) -> tuple[str, bool]:
    """`(text, translated_ok)`. `translated_ok` is `False` exactly when `text` is a fallback sentence
    naming the raw expression rather than a plain-English phrase -- see `_sentence`, the only caller."""
    try:
        tree = grammar.parse(expression)
    except RuleSyntaxError as exc:
        return (
            f"Could not translate this into plain English (the rule does not parse: {exc}). "
            f"Raw rule: `{expression}`",
            False,
        )
    try:
        phrase = _phrase_bool(tree, entry_crosses=entry_crosses, in_conjunction=False)
    except _UntranslatableError as exc:
        return (f"Could not translate this into plain English ({exc}). Raw rule: `{expression}`", False)
    return phrase, True


def _sentence(
    prefix: str,
    expression: Any,
    *,
    entry_crosses: Mapping[tuple[NumExpr, NumExpr], CrossDir] | None = None,
) -> str:
    if not isinstance(expression, str) or not expression.strip():
        return "No rule is defined."
    text, ok = _translate(expression, entry_crosses=entry_crosses or {})
    return f"{prefix} {text}." if ok else text


# ---------------------------------------------------------------------------
# Risk / sizing plain English -- numeric card fields, not expressions, so no grammar involved.
# ---------------------------------------------------------------------------


def _decimalish(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _pct(fraction: Decimal) -> str:
    pct = fraction * 100
    if pct == pct.to_integral_value():
        return f"{int(pct)}%"
    return f"{pct}%"


def _risk_plain(card: Mapping[str, Any]) -> str:
    parts: list[str] = []
    stop = _decimalish(card.get("stop_loss_pct"))
    # The U+2212 MINUS SIGN below is deliberate typography in prose a person reads, paired with
    # the '+' on the take-profit line; a hyphen-minus sets narrower and reads as a dash.
    parts.append(
        f"Cuts a losing position at −{_pct(stop)}."  # noqa: RUF001
        if stop is not None
        else "No stop loss is set."
    )
    take = _decimalish(card.get("take_profit_pct"))
    parts.append(f"Takes profit at +{_pct(take)}." if take is not None else "No profit target.")
    max_hold = card.get("max_hold_days")
    if isinstance(max_hold, int) and max_hold > 0:
        parts.append(f"Force-closes any position still open after {max_hold} trading days.")
    else:
        parts.append("No maximum hold period.")
    return " ".join(parts)


def _sizing_plain(card: Mapping[str, Any]) -> str:
    max_positions = card.get("max_positions")
    position_pct = _decimalish(card.get("position_pct"))
    if not isinstance(max_positions, int) or position_pct is None:
        return "Position sizing is not fully specified on this card."
    total = position_pct * max_positions * 100
    total_str = f"{int(total)}%" if total == total.to_integral_value() else f"{total}%"
    base = (
        f"At most {max_positions} position{'s' if max_positions != 1 else ''} at once, "
        f"{_pct(position_pct)} of the book each"
    )
    if total < 100:
        return f"{base} — so at most {total_str} invested, the rest in cash."
    if total == 100:
        return f"{base} — so up to {total_str} invested, fully deployed at the cap."
    return (
        f"{base} — so up to {total_str} invested if every slot fills, more than 100% of the book "
        "(overlapping or leveraged sizing)."
    )


_RAW_FIELDS = (
    "entry",
    "exit",
    "stop_loss_pct",
    "take_profit_pct",
    "max_hold_days",
    "max_positions",
    "position_pct",
)


def _raw_subset(card: Mapping[str, Any]) -> dict[str, Any]:
    return {key: card.get(key) for key in _RAW_FIELDS}


# ---------------------------------------------------------------------------
# Universe note -- a small, explicit, hand-maintained ticker -> sector map. Never guessed: a ticker
# missing from this map renders as "unclassified" rather than an invented label.
# ---------------------------------------------------------------------------

_TICKER_SECTORS: dict[str, str] = {
    # Semiconductors (chip designers/makers)
    "AMD": "semiconductor", "NVDA": "semiconductor", "INTC": "semiconductor", "AVGO": "semiconductor",
    "QCOM": "semiconductor", "TXN": "semiconductor", "MU": "semiconductor", "MRVL": "semiconductor",
    "CRDO": "semiconductor", "SNDK": "semiconductor/storage", "TSM": "semiconductor foundry",
    # Semiconductor capital equipment
    "AMAT": "semiconductor equipment", "LRCX": "semiconductor equipment", "KLAC": "semiconductor equipment",
    "LITE": "optical components",
    # Software / cloud / internet
    "MSFT": "software", "ORCL": "software", "CRM": "software", "ADBE": "software", "INTU": "software",
    "NOW": "software", "SNOW": "software", "NET": "software/cloud security", "PLTR": "software/data analytics",
    "GOOGL": "internet/software", "META": "internet/software", "AMZN": "internet retail/cloud",
    # Hardware / networking / devices
    "AAPL": "consumer technology hardware", "DELL": "computer hardware", "CSCO": "networking equipment",
    # Media / autos
    "NFLX": "media/streaming", "TSLA": "auto/EV",
    # Financials
    "JPM": "banking", "BAC": "banking", "WFC": "banking", "C": "banking", "USB": "banking",
    "COIN": "crypto exchange/fintech",
    # Healthcare
    "JNJ": "healthcare", "MRK": "healthcare/pharma",
    # Consumer staples
    "PG": "consumer staples", "KO": "consumer staples", "PEP": "consumer staples", "CL": "consumer staples",
    "WMT": "consumer staples/retail",
    # Industrials / energy
    "MMM": "industrials", "CVX": "energy", "XOM": "energy", "OXY": "energy", "SLB": "energy services",
    # Small/speculative energy-tech
    "OKLO": "nuclear energy", "NBIS": "AI infrastructure", "IREN": "bitcoin mining/data centers",
    "APLD": "data centers", "BE": "fuel cells/clean energy",
    # Sector / thematic ETFs
    "IGV": "software sector ETF", "SMH": "semiconductor sector ETF", "SOXX": "semiconductor sector ETF",
    "XLK": "technology sector ETF", "XLF": "financials sector ETF", "XLE": "energy sector ETF",
    "XLP": "consumer staples sector ETF", "XLV": "healthcare sector ETF", "XLI": "industrials sector ETF",
    "XLB": "materials sector ETF", "XLU": "utilities sector ETF", "XLY": "consumer discretionary sector ETF",
    "KRE": "regional bank ETF",
    # Broad-market ETFs
    "SPY": "broad-market ETF", "QQQ": "broad-market ETF (Nasdaq-100)", "DIA": "broad-market ETF (Dow)",
    "IWM": "broad-market ETF (small-cap)", "VUG": "broad-market growth ETF", "DVY": "dividend ETF",
    # Bonds
    "TLT": "long-term Treasury ETF", "IEF": "intermediate Treasury ETF", "LQD": "investment-grade bond ETF",
    # Commodities
    "GLD": "gold ETF", "SLV": "silver ETF", "GDX": "gold miners ETF", "DBC": "broad commodities ETF",
    "USO": "oil ETF",
    # International
    "EEM": "emerging markets ETF", "EWZ": "Brazil ETF", "FXI": "China large-cap ETF", "INDA": "India ETF",
}


def universe_note(universe: Sequence[str]) -> str:
    """`"6 names: 3 semiconductor equipment, 1 networking equipment, 1 software, and 1 software sector
    ETF."` -- derived purely from `_TICKER_SECTORS`. A ticker absent from that map contributes to an
    `"unclassified"` group rather than being guessed at."""
    n = len(universe)
    if n == 0:
        return "No tickers are named in this universe."
    labels = [_TICKER_SECTORS.get(ticker, "unclassified") for ticker in universe]
    counts = Counter(labels)
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ordered) == 1:
        label, _count = ordered[0]
        return f"{n} name{'s' if n != 1 else ''}, all {label}."
    parts = [f"{count} {label}" for label, count in ordered]
    joined = " and ".join(parts) if len(parts) == 2 else ", ".join(parts[:-1]) + f", and {parts[-1]}"
    return f"{n} names: {joined}."


def _build_what_it_does(card: Mapping[str, Any], *, universe: tuple[str, ...]) -> WhatItDoes:
    entry_expr = card.get("entry")
    exit_expr = card.get("exit")
    entry_crosses = _entry_crosses(entry_expr) if isinstance(entry_expr, str) else {}
    return WhatItDoes(
        universe=universe,
        universe_note=universe_note(universe),
        entry_plain=_sentence("Buys when", entry_expr),
        exit_plain=_sentence("Sells when", exit_expr, entry_crosses=entry_crosses),
        risk_plain=_risk_plain(card),
        sizing_plain=_sizing_plain(card),
        raw=_raw_subset(card),
    )


# ---------------------------------------------------------------------------
# Card lookup -- finds the JSON for a genome id anywhere it could plausibly live: not-yet-promoted
# under `data/loop/generated/`, or promoted into any library tier.
# ---------------------------------------------------------------------------

_LIBRARY_TIERS = ("candidates", "base", "variants", "retired", "allocation", "ladder")


#: `{path: ((mtime_ns, size), parsed_or_None)}`. Cached per-process so a page composing many
#: dossiers/summaries -- or the label-mismatch and template-sibling checks below, which each scan
#: every card in the library -- read and parse a given card file at most once per change, the same
#: caching discipline `_cached_ledger` applies to `ledger.jsonl`. A missing file caches as `(0, 0) ->
#: None`; because the signature is re-derived from a fresh `path.stat()` on every call before the
#: cache is consulted, a file that starts existing later (a promotion moving a card mid-process) gets
#: a different signature and is read fresh rather than staying "missing" forever.
_CARD_CACHE: dict[Path, tuple[tuple[int, int], dict[str, Any] | None]] = {}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        signature = (0, 0)
    cached = _CARD_CACHE.get(path)
    if cached is not None and cached[0] == signature:
        return cached[1]
    if signature == (0, 0):
        _CARD_CACHE[path] = (signature, None)
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = None
    result = data if isinstance(data, dict) else None
    _CARD_CACHE[path] = (signature, result)
    return result


def _card_path_under(root: Path, genome_id: str) -> Path | None:
    """`root / f"{genome_id}.json"`, or `None` if that path would not sit directly inside `root`.

    The HTTP boundary (`app.api.evolution_dossier.GenomeIdPath`) already refuses ids with separators
    or dots, so this is the defence-in-depth half: whatever the caller, an id can never name a file
    outside the directory it was meant to index. `resolve()` on both sides so `..`, a backslash on
    Windows, or a symlinked tier all collapse to a real location before the containment check.
    """
    root_resolved = root.resolve()
    candidate = (root / f"{genome_id}.json").resolve()
    if candidate.parent != root_resolved:
        return None
    return candidate


def _find_card(genome_id: str, *, settings: Settings) -> dict[str, Any] | None:
    generated = _card_path_under(generated_tier_dir(settings), genome_id)
    if generated is not None and generated.is_file():
        card = _read_json(generated)
        if card is not None:
            return card
    for tier in _LIBRARY_TIERS:
        path = _card_path_under(settings.library_dir / tier, genome_id)
        if path is not None and path.is_file():
            card = _read_json(path)
            if card is not None:
                return card
    return None


def _iter_all_cards(*, settings: Settings) -> Iterator[tuple[str, dict[str, Any]]]:
    """`(genome_id, card)` for every card this loop could plausibly be asked about: not-yet-promoted
    genomes under `data/loop/generated/`, and every library tier. Used by the label-mismatch and
    template-distinctiveness cautions, which have to compare one card against every other card rather
    than look one up by id."""
    seen: set[str] = set()
    roots = [generated_tier_dir(settings)]
    roots.extend(settings.library_dir / tier for tier in _LIBRARY_TIERS)
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            genome_id = path.stem
            if genome_id in seen:
                continue
            card = _read_json(path)
            if card is None:
                continue
            seen.add(genome_id)
            yield genome_id, card


# ---------------------------------------------------------------------------
# Origin -- parsed from `gen{N:04d}/PLAN.md`'s "Candidates" section (`app.evolution.loop._write_plan_file`
# writes one line per genome: `` - `{genome_id}` ({origin}, {shape}, parents={list}) -- {notes}``).
# ---------------------------------------------------------------------------

_GEN_DIR_RE = re.compile(r"^gen(\d+)$")
_PLAN_CANDIDATE_RE = re.compile(
    r"^- `(?P<gid>[^`]+)` \((?P<kind>\w+), (?P<shape>\w+), parents=(?P<parents>\[.*\]|none)\) -- "
    r"(?P<notes>.*)$",
    re.MULTILINE,
)


def _parse_origin_from_plan(plan_markdown: str, genome_id: str) -> tuple[str, tuple[str, ...], str] | None:
    for match in _PLAN_CANDIDATE_RE.finditer(plan_markdown):
        if match.group("gid") != genome_id:
            continue
        parents_text = match.group("parents")
        if parents_text == "none":
            parents: tuple[str, ...] = ()
        else:
            try:
                parsed = ast.literal_eval(parents_text)
            except (ValueError, SyntaxError):
                parsed = []
            parents = tuple(str(item) for item in parsed) if isinstance(parsed, list) else ()
        return match.group("kind"), parents, match.group("notes").strip()
    return None


def _generation_numbers(settings: Settings) -> list[int]:
    root = loop_root(settings)
    if not root.is_dir():
        return []
    numbers: list[int] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        match = _GEN_DIR_RE.match(child.name)
        if match is not None:
            numbers.append(int(match.group(1)))
    numbers.sort()
    return numbers


def _evidence_and_origin(
    genome_id: str, *, settings: Settings
) -> tuple[tuple[EvidenceRow, ...], Origin, Decimal | None]:
    """Every generation this genome was scored in, oldest first, plus its origin (found in the
    earliest generation whose `PLAN.md` names it) and this genome's field's own selection median in
    the *last* generation it was scored in (`field_median_excess_this_generation`).

    Reads through `app.evolution.history.get_generation`, which already caches per generation
    directory -- this function adds no caching of its own on top, since a repeated dossier request in
    the same process pays only for the (cheap, already-cached) directory-signature check, not for a
    re-parse of `OUTCOME.json`.
    """
    evidence: list[EvidenceRow] = []
    origin: Origin | None = None
    field_median_this_generation: Decimal | None = None

    for generation in _generation_numbers(settings):
        detail = history.get_generation(settings, generation)
        if detail is None:
            continue
        outcome = detail.outcome

        if origin is None and detail.plan_markdown:
            parsed = _parse_origin_from_plan(detail.plan_markdown, genome_id)
            if parsed is not None:
                kind, parents, note = parsed
                origin = Origin(generation=generation, origin_kind=kind, parents=parents, note=note)

        matched: Standing | None = None
        for standing in outcome.standings:
            if standing.genome_id == genome_id:
                matched = standing
                break
        if matched is None:
            continue

        evidence.append(
            EvidenceRow(
                generation=generation,
                round_id=outcome.round_id,
                rank=matched.rank,
                field_size=len(outcome.standings),
                windows=outcome.windows,
                median_excess=matched.median_excess,
                worst_excess=matched.worst_excess,
                hit_rate=matched.hit_rate,
                total_trades=matched.total_trades,
                holdout_median_excess=matched.holdout_median_excess,
                holdout_windows=outcome.holdout_windows,
                q_value=matched.q_value,
            )
        )
        medians = [s.median_excess for s in outcome.standings if s.median_excess is not None]
        field_median_this_generation = statistics.median(medians) if medians else None

    if origin is None:
        origin = Origin(
            generation=None,
            origin_kind=None,
            parents=(),
            note="No generation-plan record was found for this genome.",
        )

    return tuple(evidence), origin, field_median_this_generation


# ---------------------------------------------------------------------------
# Field-wide ledger statistics -- cached per-process, invalidated on `ledger.jsonl`'s own
# (mtime, size), so a page of many dossiers reads and parses the ledger file at most once per change.
#
# **Row-based, not deduped by genome, and that is verified, not assumed.** A genome re-scored across
# several generations (a surviving elite, re-run under whatever window rotation a later generation
# happens to draw) contributes one ledger row per generation it actually ran. `SPEC.md`'s own worked
# numbers -- 2,374 rows, a +5.65% all-purpose median-of-medians, a +15.02% all-purpose holdout median,
# 94.3% holdout-positive -- were checked directly against this repo's live `data/loop/ledger.jsonl`
# and only reproduce when computed over raw rows; deduping to one row per distinct genome (e.g. "most
# recent measurement per genome", the scheme `Ledger.q_values()` uses for its own, different purpose)
# gives different numbers. `candidates_ever_run` is the one figure in this section that *is* a
# distinct-genome count -- see its own docstring on `Context` for why that one deliberately differs.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RowStats:
    """Row-based statistics over some subset of ledger rows (e.g. "every row", or "every row of one
    purpose"). `holdout_measurements` is `len(entries)` restricted to rows with a non-`None`
    `holdout_median_excess` -- the population `holdout_positive_fraction`/`holdout_median` were
    actually computed over, and *not* the same number as `row_count` (a row can have a selection
    median with no holdout figure at all) or as any distinct-genome count."""

    row_count: int
    median_excess: Decimal | None
    holdout_median: Decimal | None
    holdout_positive_fraction: float | None
    holdout_measurements: int


def _row_stats(entries: Sequence[LedgerEntry]) -> _RowStats:
    medians = [e.median_excess for e in entries if e.median_excess is not None]
    holdouts = [e.holdout_median_excess for e in entries if e.holdout_median_excess is not None]
    positive = sum(1 for h in holdouts if h > 0)
    return _RowStats(
        row_count=len(entries),
        median_excess=statistics.median(medians) if medians else None,
        holdout_median=statistics.median(holdouts) if holdouts else None,
        holdout_positive_fraction=(positive / len(holdouts)) if holdouts else None,
        holdout_measurements=len(holdouts),
    )


@dataclass(frozen=True)
class _CachedLedgerStats:
    candidates_ever_run: int
    """Distinct genomes across the whole ledger -- see `Context.candidates_ever_run`'s own docstring
    for why this is the one figure here that is a genome count rather than a row count."""
    all_purposes: _RowStats


_LEDGER_CACHE: dict[Path, tuple[tuple[int, int], _CachedLedgerStats, tuple[LedgerEntry, ...]]] = {}


def _ledger_signature(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (0, 0)
    return (stat.st_mtime_ns, stat.st_size)


def _compute_global_stats(entries: Sequence[LedgerEntry]) -> _CachedLedgerStats:
    return _CachedLedgerStats(
        candidates_ever_run=len({e.genome_id for e in entries}),
        all_purposes=_row_stats(entries),
    )


def _cached_ledger(settings: Settings) -> tuple[_CachedLedgerStats, tuple[LedgerEntry, ...]]:
    """`(all-purpose stats, every parsed entry)`, cached on `ledger.jsonl`'s own `(mtime_ns, size)` so
    a page composing many dossiers reads and JSON-parses the ledger file at most once per change.
    Same-purpose statistics are *not* cached here -- `_row_stats` over an already-in-memory, purpose-
    filtered slice of `entries` is pure computation, not a disk read, so the caching this docstring
    promises (avoiding re-reading a multi-megabyte file) is already satisfied by caching `entries`
    itself; a second cache keyed on purpose would only add invalidation surface for no I/O saved."""
    path = loop_root(settings) / "ledger.jsonl"
    signature = _ledger_signature(path)
    cached = _LEDGER_CACHE.get(path)
    if cached is not None and cached[0] == signature:
        return cached[1], cached[2]
    entries = Ledger(path).entries()
    stats = _compute_global_stats(entries)
    _LEDGER_CACHE[path] = (signature, stats, entries)
    return stats, entries


def _percentile_all_time(
    card_median: Decimal | None, purpose: str, entries: Sequence[LedgerEntry]
) -> float | None:
    """This card's own recorded selection median (see `_card_reference_values` for *which* recorded
    median that is, and why it is not simply "whichever generation this genome was most recently
    scored in") ranked strictly below every *other* same-purpose ledger row -- `count(v < card_median)
    / n`, over raw rows (see this section's own docstring for why rows, not distinct genomes).

    Strict `<`, not `<=`: this genome's own row(s) can appear more than once in `entries` at the same
    value (a card that cleared the promotion gate twice on identical-window re-runs posts the same
    median both times), and counting a tie against itself as "at or below" would inflate a card's own
    percentile by its own repeat appearances.

    Verified against this repo's live ledger: `g1859-fd7c2c196f35`'s own `PendingSeat.median_excess`
    (+24.65%) ranks at 0.9975 among the 1,206 roth rows recorded at the time this was checked, which
    this exact formula reproduces to four decimal places -- see
    `tests/test_evolution_dossier.py::TestLedgerCache::test_percentile_all_time_is_scoped_to_purpose`
    and `::TestComposeDossierEvidenceAndOrigin::test_percentile_uses_the_seat_requests_own_median_not_a_later_rescore`.
    """
    if card_median is None:
        return None
    population = [e.median_excess for e in entries if e.purpose == purpose and e.median_excess is not None]
    if not population:
        return None
    below = sum(1 for value in population if value < card_median)
    return below / len(population)


def _latest_value(evidence: Sequence[EvidenceRow], attr: str) -> Any | None:
    """The most recent (highest-generation) evidence row's value for `attr` that is not `None` --
    `evidence` is oldest-first, so this walks backward and returns the first hit. Used only as the
    fallback in `_card_reference_values`, for a genome that has evidence but no `PendingSeat` yet --
    see that function's own docstring for why it is not used to represent "this card's own number"
    once a seat request exists."""
    for row in reversed(evidence):
        value = getattr(row, attr)
        if value is not None:
            return value
    return None


def _card_reference_values(
    own_seat: PendingSeat | None, evidence: Sequence[EvidenceRow]
) -> tuple[Decimal | None, Decimal | None, float | None]:
    """`(median_excess, holdout_median_excess, q_value)` representing "this card's own number", for
    every place this module needs one scalar to compare against the field: `percentile_all_time`, the
    `holdout-does-not-discriminate` caution's per-card clause, and the `q-above-5pct` caution.

    **Prefers the seat request's own recorded figures over the latest evidence row, and this is
    load-bearing, not a style choice.** A promoted genome keeps being re-scored after its seat is
    filed -- an elite the loop carries forward runs again under whatever window rotation the next
    generation happens to draw, and that measurement can differ enormously from the one that actually
    cleared the promotion gate. Measured on this repo's own live ledger: `g1859-fd7c2c196f35` cleared
    the gate at a +24.65% selection median in generations 1859 and 1863, then was re-run in generation
    1867 under a harder window mix and posted +0.31%. `PendingSeat.median_excess` /
    `.holdout_median_excess` / `.q_value` are already the canonical, never-recomputed figures a person
    reviewing the seat-approval screen sees for this exact card (`PendingSeat`'s own docstring: "every
    numeric field here is copied from the Standing the deterministic scorer already computed").
    Preferring the latest evidence row instead -- what an earlier version of this module did -- quietly
    substitutes a later, unrelated measurement for the number the decision was actually made on, and
    can invert a card's own percentile: 0.9975 using the correct (+24.65%) figure, 0.3126 using the
    wrong (+0.31%) one, for the identical card.

    Falls back to the latest evidence row's values only when no seat request has ever been filed for
    this genome (still sitting in `generated/`, never cleared the gate) -- the best information
    available before a `PendingSeat` exists at all.
    """
    if own_seat is not None:
        return own_seat.median_excess, own_seat.holdout_median_excess, own_seat.q_value
    return (
        _latest_value(evidence, "median_excess"),
        _latest_value(evidence, "holdout_median_excess"),
        _latest_value(evidence, "q_value"),
    )


# ---------------------------------------------------------------------------
# Overlap -- Jaccard over ticker sets against every currently shelved/seated seat request.
# ---------------------------------------------------------------------------


def _card_universe_and_headline(
    library_path: str, *, settings: Settings
) -> tuple[tuple[str, ...], str] | None:
    path = settings.repo_root / library_path
    if not path.is_file():
        path = Path(library_path)
        if not path.is_file():
            return None
    data = _read_json(path)
    if data is None:
        return None
    universe_raw = data.get("universe")
    if not isinstance(universe_raw, list):
        return None
    tickers = tuple(str(t) for t in universe_raw)
    purpose = str(data.get("purpose") or "")
    other_headline = headline(
        entry_expr=data.get("entry"), exit_expr=data.get("exit"), universe=tickers, purpose=purpose
    )
    return tickers, other_headline


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _overlap_note(with_shelved: Sequence[OverlapEntry], with_seated: Sequence[OverlapEntry]) -> str:
    if not with_shelved and not with_seated:
        return "No shelved or seated card shares a ticker with this one."
    shared = sorted({ticker for entry in (*with_shelved, *with_seated) for ticker in entry.shared_tickers})
    parts = []
    if with_shelved:
        parts.append(f"{len(with_shelved)} shelved card{'s' if len(with_shelved) != 1 else ''}")
    if with_seated:
        parts.append(f"{len(with_seated)} seated card{'s' if len(with_seated) != 1 else ''}")
    return f"{' and '.join(parts)} already trade {', '.join(shared)} in common with this one."


def _overlap(
    genome_id: str,
    universe: Sequence[str],
    *,
    settings: Settings,
    pending_seats: Sequence[PendingSeat],
) -> Overlap:
    own = set(universe)
    with_shelved: list[OverlapEntry] = []
    with_seated: list[OverlapEntry] = []
    for seat in pending_seats:
        if seat.genome_id == genome_id or seat.status not in ("shelved", "seated"):
            continue
        loaded = _card_universe_and_headline(seat.library_path, settings=settings)
        if loaded is None:
            continue
        other_universe, other_headline = loaded
        jaccard = _jaccard(own, set(other_universe))
        if jaccard <= 0:
            continue
        entry = OverlapEntry(
            genome_id=seat.genome_id,
            headline=other_headline,
            shared_tickers=tuple(sorted(own & set(other_universe))),
            jaccard=jaccard,
        )
        (with_shelved if seat.status == "shelved" else with_seated).append(entry)
    with_shelved.sort(key=lambda e: (-e.jaccard, e.genome_id))
    with_seated.sort(key=lambda e: (-e.jaccard, e.genome_id))
    return Overlap(
        with_shelved=tuple(with_shelved),
        with_seated=tuple(with_seated),
        note=_overlap_note(with_shelved, with_seated),
    )


# ---------------------------------------------------------------------------
# Label/template cautions -- the correction that established `discipline` is unverified also found
# that the pending-seat set shares one entry/exit template. These two functions detect both facts
# per-card, deterministically, by comparing this card's own JSON fields against every other card's.
# ---------------------------------------------------------------------------

_DIGIT_RE = re.compile(r"\d+(?:\.\d+)?")


def _rule_body_key(card: Mapping[str, Any]) -> tuple[Any, ...]:
    """A canonical tuple of every field that would have to match for two cards to be "the same rule
    body": universe, entry, exit, and every numeric trait. Excludes `agent_id`, `display_name`,
    `discipline` and `thesis` on purpose -- those are exactly the fields the `g1815`/`g1823`
    comparison found could differ while everything else was byte-identical."""
    return (
        tuple(card.get("universe") or ()),
        card.get("entry"),
        card.get("exit"),
        card.get("stop_loss_pct"),
        card.get("take_profit_pct"),
        card.get("max_hold_days"),
        card.get("max_positions"),
        card.get("position_pct"),
    )


def _masked_template(card: Mapping[str, Any]) -> tuple[str, str]:
    """`entry`/`exit` with every number replaced by `N` -- the shape of the rule with its specific
    parameters erased, matching the comparison that found all 25 pending-seat cards share one shape."""

    def mask(expr: Any) -> str:
        return _DIGIT_RE.sub("N", expr) if isinstance(expr, str) else ""

    return mask(card.get("entry")), mask(card.get("exit"))


def _rule_template_id(card: Mapping[str, Any]) -> str:
    """A stable string key for `_masked_template(card)` -- two cards with the same key ran the
    identical entry/exit shape with different numbers. Exposed on `CardSummary.rule_template_id` so a
    caller (the pending-seats list) can group or flag same-template cards across many rows without
    composing a full `Dossier`, and without running `_count_template_siblings`'s per-row disk scan for
    each one -- grouping by this key over an already-fetched list is O(n) instead."""
    masked_entry, masked_exit = _masked_template(card)
    return f"{masked_entry} || {masked_exit}"


def _find_label_mismatch(
    genome_id: str, card: Mapping[str, Any], *, settings: Settings
) -> tuple[str, str] | None:
    """`(other_genome_id, other_discipline)` for the first other card found with a byte-identical
    `_rule_body_key` but a different `discipline` -- or `None` if this card's rule body is unique to
    it, or every card sharing it agrees on the label."""
    this_key = _rule_body_key(card)
    this_label = str(card.get("discipline") or "")
    for other_id, other_card in _iter_all_cards(settings=settings):
        if other_id == genome_id:
            continue
        if _rule_body_key(other_card) != this_key:
            continue
        other_label = str(other_card.get("discipline") or "")
        if other_label != this_label:
            return other_id, other_label
    return None


def _count_template_siblings(
    genome_id: str, card: Mapping[str, Any], pending_seats: Sequence[PendingSeat], *, settings: Settings
) -> int:
    """How many *other* pending/shelved seat requests share this card's masked entry/exit template.
    Scoped to the pending/shelved set (not the whole library) because the finding this exists to
    surface is specifically about the loop's *current* review queue offering up cosmetically distinct
    but structurally identical cards, not about the human-curated library's long history."""
    this_template = _masked_template(card)
    count = 0
    for seat in pending_seats:
        if seat.genome_id == genome_id or seat.status not in ("pending", "shelved"):
            continue
        other_card = _find_card(seat.genome_id, settings=settings)
        if other_card is None:
            continue
        if _masked_template(other_card) == this_template:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Cautions -- SPEC.md's caution table, every rule in the exact order given, each computed from the
# frozen ledger + this card's own evidence/context/overlap, never from a live re-score.
# ---------------------------------------------------------------------------


def _pct1(fraction: float) -> str:
    return f"{fraction * 100:.1f}"


def _signed_pct(value: Decimal | None) -> str:
    if value is None:
        return "not measured"
    return f"{value * 100:+.2f}%"


def _cautions(
    *,
    evidence: Sequence[EvidenceRow],
    universe: Sequence[str],
    context: Context,
    overlap: Overlap,
    discipline_label: str,
    label_mismatch: tuple[str, str] | None,
    template_sibling_count: int,
    card_holdout: Decimal | None,
    card_q: float | None,
) -> tuple[Caution, ...]:
    """Every deterministic caution rule this dossier can fire, in the fixed order `SPEC.md`'s own
    table lists them (plus the two rules the label/template correction added at the end). Each rule
    exists to catch one specific way of misreading this loop's numbers as more reassuring than they
    are -- and every rule's `text` states the actual number that fired it, never just the rule's name:

    1. `holdout-does-not-discriminate` -- catches reading a positive holdout excess as evidence of
       skill, when the field's holdout-positive rate is high enough that a positive holdout is the
       ordinary outcome for *any* candidate this search proposes, random ones included.
    2. `q-above-5pct` -- catches trusting a card whose multiple-comparison-corrected false-discovery
       rate is not actually low, or that has no q-value at all (too few closed trades to test).
    3. `margin-inside-noise` -- catches a selection median that has never, even at its best measured
       generation, cleared the measured 21.2pp ordering-noise floor (`NOISE_FLOOR_PP`); blocking
       because a card that fails this on its most favourable measurement has no clearance to point to.
    4. `thin-trades` -- catches a hit rate or median computed from too few closed trades to be
       anything but noise.
    5. `narrow-universe` -- catches a card concentrated in fewer than 5 names, where one name's
       idiosyncratic move can dominate every window's result.
    6. `worst-window-deep` -- catches a card whose best-case framing hides a single-window drawdown
       deep enough to matter on its own.
    7. `single-window-set` -- catches evidence gathered on only one selection-window set (or none at
       all), which the promotion protocol itself does not treat as a real clearance; blocking because
       the promotion gate this loop already enforces requires differing window sets for exactly this
       reason.
    8. `shelf-crowding` -- catches concentrating the shelf further into names it already holds a lot
       of, via ticker-set Jaccard against every shelved/seated card.
    9. `never-saw-a-crash` -- catches a card that has never been run against any of the loop's three
       sharpest drawdown windows (covid, gfc, q4-2018), selection or holdout.
    10. `label-does-not-match-rule` -- catches trusting `discipline` as a description at all: fires
        when another card in the library has a byte-identical rule body under a different label (see
        this module's own docstring for the measured `g1815`/`g1823` proof that this happens).
    11. `template-is-not-distinct` -- catches reading this card as one strategy among many distinct
        ideas, when its entry/exit template (parameters masked) is shared by other cards still in the
        pending/shelved queue -- on the data this module was built against, every one of 25 pending
        cards shares the identical template with the other 24.

    `card_holdout`/`card_q` are `_card_reference_values`'s output, computed by the caller once and
    passed in here rather than re-derived from `evidence` -- see that function's own docstring for why
    "this card's own number" is the seat request's recorded figure, not simply its latest evidence row.
    """
    cautions: list[Caution] = []

    all_purposes_fraction = context.field_holdout_positive_fraction_all_purposes
    if all_purposes_fraction is not None and all_purposes_fraction > 0.80:
        if card_holdout is None:
            tail = (
                " This card has no holdout measurement of its own yet, and the same field-wide "
                "pattern still applies to whatever holdout figure it eventually posts."
            )
        elif context.field_holdout_median_same_purpose is None:
            tail = (
                f" This card's {_signed_pct(card_holdout)} cannot yet be compared to a same-purpose "
                "field median (none has been measured), but the field-wide pattern above still "
                "applies to it."
            )
        else:
            same_purpose_median = context.field_holdout_median_same_purpose
            relation = (
                "above" if card_holdout > same_purpose_median
                else "below" if card_holdout < same_purpose_median
                else "equal to"
            )
            tail = (
                f" This card's {_signed_pct(card_holdout)} is {relation} its own purpose's field "
                f"holdout median ({_signed_pct(same_purpose_median)}), so a positive holdout here is "
                "not evidence that this card is better than a coin flip from the same generator."
            )
        cautions.append(
            Caution(
                code="holdout-does-not-discriminate",
                severity="serious",
                text=(
                    f"{_pct1(all_purposes_fraction)}% of the "
                    f"{context.holdout_measurements_all_purposes} holdout measurements this search "
                    f"has recorded, across every purpose, also came back positive.{tail}"
                ),
            )
        )

    if card_q is None or card_q > 0.05:
        if card_q is None:
            text = (
                "This card's q-value is undefined -- too few closed trades have ever been recorded "
                "for it to compute a p-value, so no false-discovery-rate correction can vouch for it."
            )
        else:
            text = (
                f"q = {card_q:.3f} — after correcting for the {context.candidates_ever_run} distinct "
                f"hypotheses this search has tested, roughly {round(card_q * 100)} in 100 cards "
                "clearing this bar would be expected to be false positives."
            )
        cautions.append(Caution(code="q-above-5pct", severity="serious", text=text))

    best_median = max(
        (row.median_excess for row in evidence if row.median_excess is not None), default=None
    )
    best_median_pp = best_median * 100 if best_median is not None else None
    margin = best_median_pp - context.noise_floor_pp if best_median_pp is not None else None
    if margin is None or margin <= 0:
        if margin is None:
            text = (
                "No selection-window median has ever been measured for this card, so no margin over "
                f"the {context.noise_floor_pp}pp ordering-noise floor can be established."
            )
        else:
            text = (
                f"Best selection median is {best_median_pp:+.2f}pp; after the measured "
                f"{context.noise_floor_pp}pp ordering-noise floor the margin is {margin:+.2f}pp, "
                "which is at or below zero."
            )
        cautions.append(Caution(code="margin-inside-noise", severity="blocking", text=text))

    thin_rows = [row for row in evidence if row.total_trades < 30]
    if thin_rows:
        detail = ", ".join(f"generation {row.generation} ({row.total_trades} trades)" for row in thin_rows)
        cautions.append(
            Caution(
                code="thin-trades",
                severity="serious",
                text=(
                    f"{len(thin_rows)} of {len(evidence)} scored generation(s) took fewer than 30 "
                    f"total trades: {detail}. A hit rate or median computed on that few trades is noisy."
                ),
            )
        )

    if len(universe) < 5:
        cautions.append(
            Caution(
                code="narrow-universe",
                severity="note",
                text=f"Universe holds {len(universe)} ticker(s); below the 5-ticker floor this rule watches for.",
            )
        )

    worst = min((row.worst_excess for row in evidence if row.worst_excess is not None), default=None)
    if worst is not None and worst < Decimal("-0.20"):
        cautions.append(
            Caution(
                code="worst-window-deep",
                severity="note",
                text=(
                    f"Worst single-window excess reached {_signed_pct(worst)} in at least one measured "
                    "generation, a drawdown deeper than the -20pp note threshold."
                ),
            )
        )

    distinct_window_sets = {row.windows for row in evidence}
    if len(distinct_window_sets) < 2:
        text = (
            "This card has never been scored, so no window set has ever been run for it."
            if not evidence
            else (
                f"Only {len(distinct_window_sets)} distinct selection-window set has ever been run "
                f"for this card, across {len(evidence)} scored generation(s); the promotion protocol "
                "requires clearance on differing window sets before evidence is meaningful."
            )
        )
        cautions.append(Caution(code="single-window-set", severity="blocking", text=text))

    worst_overlap: OverlapEntry | None = None
    worst_overlap_kind = ""
    for kind, entries in (("shelved", overlap.with_shelved), ("seated", overlap.with_seated)):
        for entry in entries:
            if worst_overlap is None or entry.jaccard > worst_overlap.jaccard:
                worst_overlap, worst_overlap_kind = entry, kind
    if worst_overlap is not None and worst_overlap.jaccard >= 0.60:
        cautions.append(
            Caution(
                code="shelf-crowding",
                severity="note",
                text=(
                    f"{worst_overlap.jaccard:.0%} ticker overlap "
                    f"({', '.join(worst_overlap.shared_tickers)}) with the already-{worst_overlap_kind} "
                    f"{worst_overlap.headline} ({worst_overlap.genome_id})."
                ),
            )
        )

    seen_windows: set[str] = set()
    for row in evidence:
        seen_windows.update(row.windows)
        seen_windows.update(row.holdout_windows)
    if not (seen_windows & {"covid", "gfc", "q4-2018"}):
        text = (
            "This card has never been scored against any window, including the loop's three sharpest "
            "drawdowns (covid, gfc, q4-2018)."
            if not evidence
            else (
                "This card has never been run against covid, gfc, or q4-2018 -- the loop's three "
                f"sharpest drawdown windows -- across any of its {len(evidence)} scored generation(s)."
            )
        )
        cautions.append(Caution(code="never-saw-a-crash", severity="serious", text=text))

    if label_mismatch is not None:
        other_id, other_label = label_mismatch
        cautions.append(
            Caution(
                code="label-does-not-match-rule",
                severity="serious",
                text=(
                    f"Labelled {discipline_label!r}, but {other_id} carries an identical rule and "
                    f"universe labelled {other_label!r}; the discipline tag is not derived from the "
                    "strategy."
                ),
            )
        )

    if template_sibling_count > 0:
        cautions.append(
            Caution(
                code="template-is-not-distinct",
                severity="serious",
                text=(
                    f"This card's entry/exit template (parameters masked) is shared by "
                    f"{template_sibling_count} other card(s) in the pending/shelved set. The numbers "
                    "differ; the shape of the rule does not."
                ),
            )
        )

    return tuple(cautions)


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def compose_dossier(genome_id: str, *, settings: Settings) -> Dossier | None:
    """Everything a person needs to decide `genome_id`, or `None` when no card can be found for it
    anywhere this module looks (not-yet-promoted `data/loop/generated/`, or any library tier) -- the
    caller (`app.api.evolution_dossier`) turns `None` into the route's documented `404`."""
    card = _find_card(genome_id, settings=settings)
    if card is None:
        return None

    universe = tuple(str(t) for t in (card.get("universe") or ()))
    purpose = str(card.get("purpose") or "")
    discipline_label = str(card.get("discipline") or "")
    agent_id = str(card.get("agent_id") or genome_id)
    thesis = str(card.get("thesis") or "")

    what_it_does = _build_what_it_does(card, universe=universe)

    evidence, origin, field_median_this_generation = _evidence_and_origin(genome_id, settings=settings)

    pending_seats = read_pending_seats(settings)
    own_seat = next((seat for seat in pending_seats if seat.genome_id == genome_id), None)
    card_median, card_holdout, card_q = _card_reference_values(own_seat, evidence)

    global_stats, ledger_entries = _cached_ledger(settings)
    same_purpose_stats = _row_stats(tuple(e for e in ledger_entries if e.purpose == purpose))
    generations_with_outcomes = history.list_generations(settings, limit=1)[1]
    percentile_all_time = _percentile_all_time(card_median, purpose, ledger_entries)

    best_median = max(
        (row.median_excess for row in evidence if row.median_excess is not None), default=None
    )
    margin_over_noise_pp = best_median * 100 - NOISE_FLOOR_PP if best_median is not None else None

    context = Context(
        field_median_excess_this_generation=field_median_this_generation,
        field_median_excess_same_purpose=same_purpose_stats.median_excess,
        field_median_excess_all_purposes=global_stats.all_purposes.median_excess,
        field_holdout_median_same_purpose=same_purpose_stats.holdout_median,
        field_holdout_median_all_purposes=global_stats.all_purposes.holdout_median,
        field_holdout_positive_fraction_same_purpose=same_purpose_stats.holdout_positive_fraction,
        field_holdout_positive_fraction_all_purposes=global_stats.all_purposes.holdout_positive_fraction,
        holdout_measurements_same_purpose=same_purpose_stats.holdout_measurements,
        holdout_measurements_all_purposes=global_stats.all_purposes.holdout_measurements,
        percentile_all_time=percentile_all_time,
        candidates_ever_run=global_stats.candidates_ever_run,
        generations_with_outcomes=generations_with_outcomes,
        noise_floor_pp=NOISE_FLOOR_PP,
        margin_over_noise_pp=margin_over_noise_pp,
    )

    overlap = _overlap(genome_id, universe, settings=settings, pending_seats=pending_seats)
    label_mismatch = _find_label_mismatch(genome_id, card, settings=settings)
    template_sibling_count = _count_template_siblings(genome_id, card, pending_seats, settings=settings)
    cautions = _cautions(
        evidence=evidence,
        universe=universe,
        context=context,
        overlap=overlap,
        discipline_label=discipline_label,
        label_mismatch=label_mismatch,
        template_sibling_count=template_sibling_count,
        card_holdout=card_holdout,
        card_q=card_q,
    )

    return Dossier(
        genome_id=genome_id,
        agent_id=agent_id,
        headline=headline(
            entry_expr=card.get("entry"), exit_expr=card.get("exit"), universe=universe, purpose=purpose
        ),
        short_id=short_id(genome_id),
        purpose=purpose,
        discipline_label=discipline_label,
        discipline_label_note=_DISCIPLINE_LABEL_NOTE,
        stage=own_seat.status if own_seat is not None else None,
        requested_at=own_seat.requested_at if own_seat is not None else None,
        what_it_does=what_it_does,
        thesis=thesis,
        origin=origin,
        evidence=evidence,
        context=context,
        cautions=cautions,
        overlap=overlap,
        what_a_decision_does=_WHAT_A_DECISION_DOES,
    )
