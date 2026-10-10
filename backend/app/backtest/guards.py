"""Proof that a condition used only information available at the time it fired.

Everything else in this package measures. This module refuses. It answers one question -- *could this
rule have seen the future?* -- and it answers it conservatively: anything it cannot affirmatively
verify is a **failure**. :attr:`~app.backtest.models.GuardStatus.UNVERIFIED` is a failure state for
the same reason, so a study that skipped the check is visibly different from one that passed rather
than defaulting to the reassuring value.

Two independent checks, both required.

**1. The AST allowlist (static).** Every node type in the parsed tree must appear in
:data:`_ALLOWED_NODES` by identity. An unrecognised type is rejected by name. This is the
fail-closed core, and its real job is temporal: if someone later adds a ``Shift`` or ``Lead`` node to
:mod:`app.rules.nodes` and does not think about this module, the guard must reject it rather than
wave it through for want of a rule against it. :func:`_unlisted_node_types` compares the allowlist
against ``nodes.__all__`` so the omission surfaces as a failing test in *this* package rather than as
a silently permissive guard in production.

**2. Causality by tail truncation (empirical), and this is the one that finds real bugs.** An
indicator is causal exactly when its value at bar ``t`` does not depend on any bar after ``t``. So
compute it on the whole series, then recompute on the leading slice ``bars[:k]``, and compare every
position ``j < k``. A causal indicator gives identical numbers; one that peeks does not.

Truncating the **tail** rather than the head is the whole trick, and getting it backwards would make
this check useless in the noisiest possible way. Chopping the head moves a recursive indicator's
seed: an EMA(50) restarted 100 bars later legitimately differs from the full-series one -- measured
at **1.83 price points** on QQQ -- so a head-truncation check would flag every EMA, MACD, RSI and ATR
in the registry as future-peeking, and the only way to quiet it would be a tolerance so wide it could
no longer see an actual violation. Chopping the tail preserves the seed and asks precisely the
question causality is about.

Because the seed is preserved, the comparison is **exact** -- no tolerance, no epsilon to justify.
That was verified rather than assumed: every indicator in the registry (``sma``, ``ema``, ``macd``,
``rsi``, ``bb``, ``atr``) reproduces bit-identical values under tail truncation at four separate cut
points on 600 real QQQ sessions. Demanding equality is therefore not strictness for its own sake; it
is the observed behaviour of correct code, and any deviation at all is a finding.

What this does **not** prove: that the *bars* are point-in-time. If a provider silently revised a
close, or a split was applied retroactively across the whole history, every indicator here stays
perfectly causal over data that was never available in that form. That is
:mod:`app.backtest.runcard`'s job -- the data fingerprint is what makes such a revision visible --
and this module's findings say so rather than implying a guarantee they do not carry.
"""

from __future__ import annotations

from typing import Final
from typing import Literal as _TypingLiteral

import numpy as np
import pandas as pd

from app.backtest.models import GuardFinding, GuardReport, GuardStatus
from app.db.duck import Interval
from app.indicators import registry as indicator_registry
from app.indicators.base import IndicatorError, IndicatorRequest
from app.rules import nodes
from app.rules.macro_binding import RELEASE_LAG
from app.rules.nodes import (
    Arith,
    BoolExpr,
    BoolOp,
    Comparison,
    Cross,
    IndicatorRef,
    Literal,
    MacroField,
    MacroRef,
    Not,
    NumExpr,
    PriceField,
    PriceRef,
)

__all__ = ["CAUSALITY_CUTS", "ExpressionKind", "check", "required_indicator_refs"]

#: Which half of the grammar an expression is parsed as -- see :func:`check`'s ``kind``. Spelled as
#: a literal type rather than an enum to keep it a plain string at every call site and in the JSON
#: a `GuardReport` serialises into.
type ExpressionKind = _TypingLiteral["rule", "ranking"]

#: Node types this guard has been reasoned about and accepts. Membership is by *type identity*, not
#: by structural duck-typing: a new node that happens to have a ``left``/``right`` pair must still be
#: added here deliberately.
_ALLOWED_NODES: Final[frozenset[type]] = frozenset(
    {Literal, PriceRef, MacroRef, IndicatorRef, Arith, Comparison, Cross, Not, BoolOp}
)

#: Bar columns a rule may read. Mirrors `PriceField` and is checked against it by a test -- if a
#: future field is added there, this guard must be told about it before rules may use it.
_ALLOWED_PRICE_FIELDS: Final[frozenset[PriceField]] = frozenset(PriceField)

#: Macro series a rule may read. Mirrors `MacroField` and is checked against it by a test, exactly as
#: `_ALLOWED_PRICE_FIELDS` mirrors `PriceField`.
#:
#: **Membership here is not sufficient.** A macro field must *also* carry an
#: `app.rules.macro_binding.RELEASE_LAG` entry, checked separately in :func:`_walk`, because the two
#: answer different questions: this set says "the guard has been told this series exists", the lag
#: table says "the guard knows when a value in it became public". A series added to `MacroField` and
#: to this set but forgotten in the lag table would bind by reference date -- reading a figure on the
#: day it *describes* rather than the day it was *published* -- and that failure produces a better
#: backtest and no error, which is the hardest kind to notice.
_ALLOWED_MACRO_FIELDS: Final[frozenset[MacroField]] = frozenset(MacroField)

#: How many leading slices to recompute each indicator on. Each cut costs one full recomputation of
#: every indicator the rule needs, so this trades directly against latency on a scan. Eight spread
#: across the post-warmup region is enough to catch a systematic violation -- a centered window or a
#: whole-series normalisation disagrees at *every* cut, not at a lucky one -- while keeping a
#: twelve-rule scan's guard cost bounded.
CAUSALITY_CUTS: Final[int] = 8

#: Below this many post-warmup bars there is nothing to truncate meaningfully, and the check reports
#: that it could not run rather than passing on no evidence.
_MIN_BARS_FOR_CAUSALITY: Final[int] = 40


def _unlisted_node_types() -> set[str]:
    """Names exported by :mod:`app.rules.nodes` that are node dataclasses but not on the allowlist.

    The mechanism that makes "fails closed" survive a refactor. Enum and type-alias exports are
    excluded; what remains are the AST dataclasses, and any of those missing from
    :data:`_ALLOWED_NODES` means this module has not been told about a way to build a tree.
    """
    unlisted: set[str] = set()
    for name in nodes.__all__:
        obj = getattr(nodes, name, None)
        if not isinstance(obj, type):
            continue  # `NumExpr`/`BoolExpr` are type aliases, not classes
        if issubclass(obj, str):
            continue  # the StrEnum operator tables are not nodes
        if not hasattr(obj, "__dataclass_fields__"):
            continue
        if obj not in _ALLOWED_NODES:
            unlisted.add(name)
    return unlisted


def _walk(node: object, findings: list[GuardFinding]) -> list[IndicatorRef]:
    """Depth-first walk collecting indicator references, appending a finding for anything unlisted.

    Returns whatever it could collect even on failure: a report naming *both* the unknown node and
    the unknown indicator is more useful than one that stops at the first problem.
    """
    refs: list[IndicatorRef] = []
    if type(node) not in _ALLOWED_NODES:
        findings.append(
            GuardFinding(
                check="ast_whitelist",
                passed=False,
                detail=(
                    f"unrecognised expression node {type(node).__name__!r}: this guard fails closed, "
                    "so a node type it has not been taught about is rejected rather than trusted"
                ),
            )
        )
        return refs

    match node:
        case Literal():
            pass
        case PriceRef(field=field):
            if field not in _ALLOWED_PRICE_FIELDS:
                findings.append(
                    GuardFinding(
                        check="ast_whitelist",
                        passed=False,
                        detail=f"price field {field!r} is not one this guard permits",
                    )
                )
        case MacroRef(field=macro_field):
            if macro_field not in _ALLOWED_MACRO_FIELDS:
                findings.append(
                    GuardFinding(
                        check="ast_whitelist",
                        passed=False,
                        detail=f"macro series {macro_field!r} is not one this guard permits",
                    )
                )
            elif macro_field not in RELEASE_LAG:
                # Fail closed on the lag table, not just on the enum. See `_ALLOWED_MACRO_FIELDS`
                # for why the two are separate checks rather than one.
                findings.append(
                    GuardFinding(
                        check="macro_release_lag",
                        passed=False,
                        detail=(
                            f"macro series {macro_field.value!r} has no RELEASE_LAG entry, so the "
                            "date it became knowable is unknown; this guard refuses it rather than "
                            "letting it bind by reference date, which would read a value on the day "
                            "it describes instead of the day it was published"
                        ),
                    )
                )
        case IndicatorRef():
            refs.append(node)
        case Arith(left=left, right=right) | Comparison(left=left, right=right):
            refs.extend(_walk(left, findings))
            refs.extend(_walk(right, findings))
        case Cross(left=left, right=right):
            refs.extend(_walk(left, findings))
            refs.extend(_walk(right, findings))
        case Not(operand=operand):
            refs.extend(_walk(operand, findings))
        case BoolOp(operands=operands):
            for operand in operands:
                refs.extend(_walk(operand, findings))
    return refs


def required_indicator_refs(node: BoolExpr | NumExpr) -> list[IndicatorRef]:
    """Every :class:`~app.rules.nodes.IndicatorRef` in a tree, for callers that only want the list."""
    return _walk(node, [])


def _spec_text(ref: IndicatorRef) -> str:
    """``IndicatorRef`` back to the registry's spec syntax: ``rsi:14``, ``bb:20,2``, ``vwap:session``.

    Arguments are rendered the way :func:`app.indicators.base.column_name` renders them -- a whole
    float loses its ``.0`` -- so the text round-trips through
    :func:`app.indicators.registry.request` instead of failing to parse ``14.0`` as an int period.
    """
    parts: list[str] = []
    for arg in ref.args:
        if isinstance(arg, float) and arg.is_integer():
            parts.append(str(int(arg)))
        else:
            parts.append(str(arg))
    return f"{ref.name}:{','.join(parts)}" if parts else ref.name


def _resolve(
    refs: list[IndicatorRef], interval: Interval, findings: list[GuardFinding]
) -> list[IndicatorRequest]:
    """Resolve each reference against the registry, recording a failure for any that will not."""
    requests: list[IndicatorRequest] = []
    seen: set[str] = set()
    for ref in refs:
        text = _spec_text(ref)
        if text in seen:
            continue
        seen.add(text)
        try:
            requests.append(indicator_registry.request(text, interval=interval))
        except IndicatorError as exc:
            findings.append(
                GuardFinding(
                    check="unknown_indicator",
                    passed=False,
                    detail=f"{text}: {exc}",
                )
            )
    return requests


def _cut_points(n: int, warmup: int) -> list[int]:
    """Deterministic slice lengths in the post-warmup region.

    Deterministic by construction rather than seeded: a guard whose verdict depends on an RNG draw is
    worse than no guard, because a rule that passed yesterday and fails today teaches the reader to
    ignore it.
    """
    low = max(warmup + 2, _MIN_BARS_FOR_CAUSALITY // 2)
    high = n - 1
    if high <= low:
        return []
    step = max(1, (high - low) // CAUSALITY_CUTS)
    cuts = sorted({min(high, low + i * step) for i in range(CAUSALITY_CUTS)})
    return [c for c in cuts if low <= c <= high]


def _first_disagreement(full: np.ndarray, prefix: np.ndarray) -> int | None:
    """Index of the first position where the two disagree, treating NaN as equal to NaN.

    ``np.isclose`` alone reports two NaNs as *different*, which would flag every indicator's warmup
    window as a causality violation -- the check would fail loudest exactly where it has nothing to
    say.
    """
    k = prefix.size
    a = full[:k]
    both_nan = np.isnan(a) & np.isnan(prefix)
    differs = ~(both_nan | (a == prefix))
    hits = np.flatnonzero(differs)
    return int(hits[0]) if hits.size else None


def _causality_findings(
    requests: list[IndicatorRequest], bars: pd.DataFrame
) -> list[GuardFinding]:
    """Recompute each indicator on leading slices and demand identical values before the cut."""
    findings: list[GuardFinding] = []
    n = len(bars)

    for request in requests:
        warmup = request.spec.warmup(request.params)
        cuts = _cut_points(n, warmup)
        if not cuts:
            findings.append(
                GuardFinding(
                    check="causality",
                    passed=False,
                    detail=(
                        f"{request.key}: only {n} bars against a {warmup}-bar warmup leaves no "
                        "post-warmup region to truncate, so causality could not be demonstrated -- "
                        "this guard reports that as a failure rather than passing on no evidence"
                    ),
                )
            )
            continue

        full = request.compute(bars)
        violated = False
        for cut in cuts:
            prefix = request.compute(bars.iloc[:cut].reset_index(drop=True))
            for column in full.columns:
                index = _first_disagreement(
                    full[column].to_numpy(dtype=float), prefix[column].to_numpy(dtype=float)
                )
                if index is None:
                    continue
                findings.append(
                    GuardFinding(
                        check="causality",
                        passed=False,
                        detail=(
                            f"{column}: value at bar {index} changed when bars after {cut - 1} were "
                            f"removed ({full[column].iloc[index]!r} on the full series vs "
                            f"{prefix[column].iloc[index]!r} on bars[:{cut}]) -- bar {index} was "
                            "computed using information from a later bar"
                        ),
                    )
                )
                violated = True
                break
            if violated:
                break

        if not violated:
            findings.append(
                GuardFinding(
                    check="causality",
                    passed=True,
                    detail=(
                        f"{request.key}: identical at every position across {len(cuts)} leading "
                        f"slices of {n} bars"
                    ),
                )
            )
    return findings


def _macro_findings(tree: BoolExpr | NumExpr, bars: pd.DataFrame) -> list[GuardFinding]:
    """Prove, per scored session, that no bar read a macro value before it was published.

    Distinct from :func:`_causality_findings` and deliberately not folded into it. That check
    recomputes an indicator on leading slices of the bar frame and demands the recursion agrees --
    a statement about seeds and windows, and **meaningless for a value that is looked up rather than
    computed**. A `MacroRef` would pass it trivially while reading next month's newspaper, which is
    why adding `MacroRef` to `_ALLOWED_NODES` without this would make the guard report success on a
    node it has no evidence about.

    Returns an empty list for a tree with no macro reference, so a price-only rule's report is
    unchanged.
    """
    from app.rules import macro_binding

    fields = macro_binding.required_macro_fields(tree)
    if not fields:
        return []

    try:
        from app.rules.macro_pin import active_pin

        series = active_pin()
        dates = macro_binding._bar_dates(bars)
        bound = macro_binding.bind_macro(fields, series, bars.index, dates=dates)
        violations = macro_binding.verify_release_binding(bound, fields, series, dates)
    except Exception as exc:  # a guard that cannot run must fail, never pass quietly
        return [
            GuardFinding(
                check="macro_release_binding",
                passed=False,
                detail=f"release-date binding could not be verified ({exc!r}); failing closed",
            )
        ]

    if violations:
        shown = "; ".join(v.describe() for v in violations[:3])
        more = "" if len(violations) <= 3 else f" (and {len(violations) - 3} more)"
        return [
            GuardFinding(
                check="macro_release_binding",
                passed=False,
                detail=(
                    f"{len(violations)} session(s) bound a macro value that had not been released "
                    f"by that date: {shown}{more}"
                ),
            )
        ]

    names = ", ".join(f.value for f in fields)
    return [
        GuardFinding(
            check="macro_release_binding",
            passed=True,
            detail=(
                f"every scored session's value for {names} was already published on that date, "
                f"re-derived independently of the join that produced it. This proves the configured "
                f"release lag was respected; it does not prove the lag is correct, and it does not "
                f"see revisions -- FRED serves today's revised figure against a historical "
                f"reference date, which needs the ALFRED vintage archive to close."
            ),
        )
    ]


def check(
    expression: str, bars: pd.DataFrame, *, interval: Interval, kind: ExpressionKind = "rule"
) -> GuardReport:
    """Verify one condition. Never raises -- a failure is a report, not an exception.

    A caller forced to wrap this in ``try``/``except`` will eventually not, and an un-run guard
    reads as a passed one. Every failure path therefore comes back as
    :attr:`~app.backtest.models.GuardStatus.FAILED` carrying a finding that says why, including a
    parse error, an unknown indicator, and an interval the indicator is not defined on.

    ``kind`` selects which of the grammar's two entry points parses ``expression``, and nothing
    else: ``"rule"`` (the default, and what every pre-existing caller gets without changing)
    requires a condition, ``"ranking"`` requires a number -- a `StrategyCard.rank_by` key. Every
    check below this point is deliberately shared rather than duplicated for the numeric case,
    because a ranking key must satisfy exactly what a rule must satisfy: the same node allowlist
    (nothing that could reach a later bar), the same indicator resolution, and above all the same
    causality check. A key that is not causal chooses which name gets a scarce slot using data
    from after the decision -- lookahead in the selection step rather than the entry step, which is
    harder to spot precisely because the entry rule it accompanies is clean.
    """
    findings: list[GuardFinding] = []

    unlisted = _unlisted_node_types()
    if unlisted:
        findings.append(
            GuardFinding(
                check="ast_whitelist",
                passed=False,
                detail=(
                    f"app.rules.nodes exports node type(s) {sorted(unlisted)} that this guard has "
                    "not been taught about; refusing every expression until it is"
                ),
            )
        )

    from app.rules import grammar  # lazy, matching `app.rules.service`'s collaborator pattern

    try:
        tree = grammar.parse(expression) if kind == "rule" else grammar.parse_ranking(expression)
    except Exception as exc:  # the parser defines its own failure types; none may escape here
        findings.append(GuardFinding(check="parse", passed=False, detail=str(exc)))
        return GuardReport(status=GuardStatus.FAILED, expression=expression, findings=findings)

    refs = _walk(tree, findings)
    findings.append(
        GuardFinding(
            check="ast_whitelist",
            passed=not any(f.check == "ast_whitelist" and not f.passed for f in findings),
            detail=(
                "every node in the tree is on the allowlist; the grammar has no way to reference a "
                "later bar, and adj_close is not a referenceable field"
            ),
        )
    )

    requests = _resolve(refs, interval, findings)
    if any(f.check == "unknown_indicator" for f in findings):
        return GuardReport(status=GuardStatus.FAILED, expression=expression, findings=findings)

    try:
        findings.extend(_causality_findings(requests, bars))
    except Exception as exc:
        findings.append(
            GuardFinding(
                check="causality",
                passed=False,
                detail=f"causality check could not run ({exc!r}); failing closed",
            )
        )

    findings.extend(_macro_findings(tree, bars))

    findings.append(
        GuardFinding(
            check="point_in_time",
            passed=True,
            detail=(
                "scope note: this verifies the rule is causal over the bars it was given. It does "
                "not prove those bars are point-in-time -- a retroactively revised close or "
                "back-applied split is outside what any AST check can see. The run card's data "
                "fingerprint is what makes that visible."
            ),
        )
    )

    failed = [f for f in findings if not f.passed]
    status = GuardStatus.FAILED if failed else GuardStatus.PASSED
    return GuardReport(status=status, expression=expression, findings=findings)
