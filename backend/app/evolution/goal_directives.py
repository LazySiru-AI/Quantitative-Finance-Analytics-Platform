"""Finds text in `LoopConfig.goal` that is *shaped like* a config directive but is not one.

`goal` is free text, recorded verbatim, parsed by nothing -- see :attr:`app.evolution.models.LoopConfig.goal`
and `frontend/src/pages/competition/LoopPanel.tsx`'s module docstring, which forbids ever letting the
goal's contents steer the search. Nothing here changes that. **This module reads `goal` to write a note
for a person, never to configure a run**: its only caller is `app.evolution.loop._write_plan_file`,
which puts the result in `gen{N}/PLAN.md`'s "What this generation is for" section. No value produced
here reaches the proposer, the scorer, or the config, and none may be made to.

**What went wrong without it.** `data/loop/gen1873/PLAN.md` and `gen1877/PLAN.md` both record::

    **Goal:** add saving as one of purpose as well
    purposes=['trading', 'roth', 'saving']

Three faults stacked, none of them visible anywhere. The directive was typed into the half of the
config nothing reads. The value `saving` is not a purpose at all -- `app.tournament.purposes.Purpose`
is `savings`/`trading`/`roth`. And both generations then ran the default lanes exactly as though the
request had never been made, leaving a pre-registration document that quotes an instruction next to a
record of it not happening, with nothing marking the gap. This module is what marks it.

**Server-side, the note can be stronger than the form's warning.** The pre-flight check in
`frontend/src/pages/competition/goalDirectives.ts` compares a directive against a *draft* -- what the
person is about to send. Here the config is the run's own settled fact, so a note can say what the
generation is actually running with, not merely that the form could not have set it. Keep the two in
step by hand: they are deliberate duplicates in the house style `PURPOSE_LABELS` and `requestJson`
already follow, not two views of one shared contract.

**A note, never a refusal.** A goal that contradicts its config is not an error and must never fail a
write, reject a start, or change a single setting. The generation runs; the record simply stops being
silent about the discrepancy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.tournament.purposes import Purpose
from app.tournament.results import RANK_BY_CHOICES

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to the type checker
    from app.evolution.models import LoopConfig

__all__ = ["GoalDirective", "find_unapplied_goal_directives", "goal_directive_notes"]

#: Read from the enum rather than restated, for the reason `app.tournament.results._PURPOSE_VALUES`
#: gives for doing the same: this file cannot then drift out of agreement about how many purposes exist.
_LEGAL_PURPOSES: tuple[str, ...] = tuple(p.value for p in Purpose)

#: Every ``key=`` spelling worth recognising, mapped to the `LoopConfig` field it is aiming at. Keys are
#: matched case-insensitively with ``_``/``-``/spaces stripped first (see `_normalise_key`).
_KEY_ALIASES: dict[str, str] = {
    "purpose": "purposes",
    "purposes": "purposes",
    "book": "purposes",
    "books": "purposes",
    "focus": "focus_symbols",
    "focussymbols": "focus_symbols",
    "include": "focus_symbols",
    "mustinclude": "focus_symbols",
    "avoid": "avoid_symbols",
    "avoidsymbols": "avoid_symbols",
    "exclude": "avoid_symbols",
    "mustavoid": "avoid_symbols",
    "rank": "rank_by",
    "rankby": "rank_by",
    "rankedby": "rank_by",
    "sortby": "rank_by",
    "metric": "rank_by",
}

_FIELD_NOUN: dict[str, str] = {
    "purposes": "purposes",
    "rank_by": "the ranking metric",
    "focus_symbols": "the must-include tickers",
    "avoid_symbols": "the must-avoid tickers",
}

_FIELD_VALUE_NOUN: dict[str, tuple[str, str]] = {
    "purposes": ("a purpose", "purposes"),
    "rank_by": ("a ranking metric", "ranking metrics"),
    "focus_symbols": ("a ticker", "tickers"),
    "avoid_symbols": ("a ticker", "tickers"),
}

#: ``key = value`` only, never ``key: value``. A colon is ordinary punctuation in the kind of sentence
#: this field is *for* ("what I want to know: does a semiconductor tilt survive a drawdown"), and
#: matching it would turn every well-written goal into a false alarm. The key may not contain a space --
#: allowing one makes ``"plus avoid=TSLA"`` match with the key ``"plus avoid"``, which resolves to no
#: field and silently swallows the ``avoid=`` directive inside it.
_DIRECTIVE_RE = re.compile(
    r"\b([A-Za-z][A-Za-z_-]{1,15}?)\s*=\s*"
    r"(\[[^\]\n]*\]?|\([^)\n]*\)?|\"[^\"\n]*\"|'[^'\n]*'|[A-Za-z0-9._-]+(?:\s*,\s*['\"]?[A-Za-z0-9._-]+['\"]?)*)"
)

#: Two or more comma-separated all-caps tokens: ``NVDA, AMD, MU``. Two, not one, because a single
#: capitalised word in a sentence is far more often an acronym than a ticker list.
_TICKER_RUN_RE = re.compile(r"\b[A-Z]{1,5}\b(?:\s*,\s*\b[A-Z]{1,5}\b)+")

#: All-caps words that turn up in goal prose and are not tickers. A false positive costs a reader a note
#: about their own English, so the list errs towards silence.
_NOT_TICKERS: frozenset[str] = frozenset(
    {
        "A", "I", "AI", "ML", "LLM", "US", "USA", "EU", "UK", "ETF", "ETFS", "IRA", "ROTH", "CAGR",
        "IRR", "TWR", "PNL", "YTD", "MTD", "QTD", "EOD", "OK", "NO", "YES", "TODO", "FIFO", "LIFO",
        "MA", "EMA", "SMA", "RSI", "ATR", "AND", "OR", "NOT", "VS", "TBD", "NA", "PP", "BPS", "MAX",
        "MIN",
    }
)

#: The phrases that mean "rank by" in prose. Deliberately narrow: a bare mention of the word "median"
#: in a sentence about medians is not a directive, and treating it as one would make this noise.
_METRIC_CUE_RE = re.compile(
    r"\b(?:rank(?:ed|ing)?\s+by|sort(?:ed)?\s+by|scored?\s+on|selected?\s+on|optimi[sz]e\s+for)\s+"
    r"((?:the\s+|a\s+|its\s+)?[A-Za-z][A-Za-z-]*(?:\s+[A-Za-z][A-Za-z-]*){0,2})",
    re.IGNORECASE,
)

_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an|its)\s+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class GoalDirective:
    """One directive-shaped phrase in `goal` that the config it was written for does not carry."""

    field: str
    """Which `LoopConfig` field it was aiming at."""

    quoted: str
    """The slice of goal text that triggered this, verbatim -- quoted back into the plan so a reader
    can see which words are meant rather than having to guess."""

    values: tuple[str, ...]
    """What the directive asked for, normalised for the field (tickers uppercased, the rest lowered)."""

    effective: tuple[str, ...]
    """What the run is *actually* using for that field. The whole point of running this server-side:
    the form's own pre-flight warning can only say what the draft would send."""

    illegal: tuple[str, ...]
    """The subset of `values` that is not legal for this field at all -- `saving` for `purposes`.
    Always empty for the two symbol fields: the tradeable pool is validated at start, not here."""

    legal_values: tuple[str, ...] | None
    """Every legal value, for the fields with a closed set; `None` for the symbol fields."""


def _normalise_key(raw: str) -> str:
    return re.sub(r"[\s_-]", "", raw.lower())


def _split_value(raw: str) -> list[str]:
    """``"['trading', 'roth']"`` -> ``["trading", "roth"]`` -- one layer of brackets, then quotes, then
    commas: the shapes a person types when half-remembering Python."""
    unwrapped = re.sub(r"^[\[(]", "", raw.strip())
    unwrapped = re.sub(r"[\])]$", "", unwrapped)
    parts = [p.strip().strip("\"'").strip() for p in unwrapped.split(",")]
    return [p for p in parts if p]


def _normalise_value(field: str, raw: str) -> str:
    if field in ("focus_symbols", "avoid_symbols"):
        return raw.upper()
    if field == "rank_by":
        return re.sub(r"\s+", "-", raw.lower())
    return raw.lower()


def _legal_values(field: str) -> tuple[str, ...] | None:
    if field == "purposes":
        return _LEGAL_PURPOSES
    if field == "rank_by":
        return tuple(RANK_BY_CHOICES)
    return None


def _effective(field: str, config: LoopConfig) -> tuple[str, ...]:
    if field == "purposes":
        return tuple(p.value for p in config.purposes)
    if field == "rank_by":
        return (config.rank_by,)
    if field == "focus_symbols":
        return tuple(config.focus_symbols)
    return tuple(config.avoid_symbols)


def _is_applied(field: str, values: tuple[str, ...], effective: tuple[str, ...]) -> bool:
    """Did the run end up doing what the directive asked?

    **Set equality for `purposes` and `rank_by`, containment for the two symbol lists**, and the
    difference is not cosmetic. `purposes` *replaces* the lane rotation: a goal asking for
    ``purposes=trading`` against a run breeding trading and roth did not take effect, even though
    trading is in there. `focus_symbols` is a per-candidate constraint: every ticker the goal named is
    genuinely being enforced on every candidate, so a longer include list than the goal asked for still
    satisfies it.
    """
    if field in ("purposes", "rank_by"):
        return set(values) == set(effective)
    return set(values) <= set(effective)


def find_unapplied_goal_directives(config: LoopConfig) -> tuple[GoalDirective, ...]:
    """Every directive-shaped phrase in `config.goal` that `config` itself does not carry.

    Empty for the ordinary case -- a goal written as a question, which is what the field is for -- and
    empty for a goal whose directive the config *does* reflect: that text is redundant, not misleading,
    and a note about it would train readers to skip this section.
    """
    goal = config.goal or ""
    if not goal.strip():
        return ()

    found: list[GoalDirective] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    def push(field: str, quoted: str, values: tuple[str, ...]) -> None:
        key = (field, values)
        if key in seen:
            return
        effective = _effective(field, config)
        if _is_applied(field, values, effective):
            return
        seen.add(key)
        legal = _legal_values(field)
        illegal = () if legal is None else tuple(v for v in values if v not in legal)
        found.append(
            GoalDirective(
                field=field,
                quoted=quoted.strip(),
                values=values,
                effective=effective,
                illegal=illegal,
                legal_values=legal,
            )
        )

    # Blanked as each `key=value` is consumed, so the two prose passes below cannot report the same
    # words a second time under a different heading.
    residue = list(goal)
    for match in _DIRECTIVE_RE.finditer(goal):
        field = _KEY_ALIASES.get(_normalise_key(match.group(1)))
        if field is None:
            continue
        values = tuple(_normalise_value(field, v) for v in _split_value(match.group(2)))
        if not values:
            continue
        for i in range(match.start(), match.end()):
            residue[i] = " "
        push(field, match.group(0), values)
    rest = "".join(residue)

    for match in _METRIC_CUE_RE.finditer(rest):
        phrase = _LEADING_ARTICLE_RE.sub("", match.group(1).strip())
        words = phrase.split()
        # Longest legal prefix wins, so "ranked by excess per exposure over the matrix" resolves to
        # `excess-per-exposure` rather than being reported as an illegal four-word metric.
        value = _normalise_value("rank_by", words[0] if words else phrase)
        for n in range(len(words), 0, -1):
            candidate = _normalise_value("rank_by", " ".join(words[:n]))
            if candidate in RANK_BY_CHOICES:
                value = candidate
                break
        push("rank_by", match.group(0), (value,))

    held = set(config.focus_symbols) | set(config.avoid_symbols)
    for match in _TICKER_RUN_RE.finditer(rest):
        tickers = tuple(
            t for t in (part.strip() for part in match.group(0).split(",")) if t and t not in _NOT_TICKERS
        )
        if len(tickers) < 2 or set(tickers) <= held:
            continue
        push("focus_symbols", match.group(0), tickers)

    return tuple(found)


def _describe(directive: GoalDirective) -> str:
    effective = ", ".join(directive.effective) if directive.effective else "(none)"
    sentence = (
        f"- `{directive.quoted}` -- the goal names {_FIELD_NOUN[directive.field]}, but `goal` is not "
        f"parsed, so this had no effect. This generation ran with "
        f"`{directive.field}` = {effective}."
    )
    if directive.illegal and directive.legal_values is not None:
        one, many = _FIELD_VALUE_NOUN[directive.field]
        quoted = ", ".join(f"`{v}`" for v in directive.illegal)
        is_are = f"is not {one}" if len(directive.illegal) == 1 else f"are not {many}"
        sentence += (
            f" {quoted} {is_are} in any case -- the legal values are "
            f"{', '.join(directive.legal_values)}."
        )
    return sentence


def goal_directive_notes(config: LoopConfig) -> tuple[str, ...]:
    """`find_unapplied_goal_directives` rendered as PLAN.md bullet lines; `()` when there is nothing
    to say, in which case the caller writes no heading either."""
    return tuple(_describe(d) for d in find_unapplied_goal_directives(config))
