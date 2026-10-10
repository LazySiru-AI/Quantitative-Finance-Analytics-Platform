"""The dashboard's facts, shaped for a language model rather than a browser.

Every function here is a thin adapter over the *same* service function the HTTP router calls --
``engine.report_from_ledger``, ``service.build_decision_table``, ``macro.build_snapshot``. None of
them re-implements a calculation, and none of them loops back through the app's own HTTP API. A
second implementation of a tax figure is exactly the defect class this project keeps finding, and a
loopback would make the MCP server depend on a running uvicorn for no benefit.

## Why the return shapes are not just ``model_dump()``

Two things a browser gets for free that a model does not:

**Provenance.** A person reading the Tax page sees the disclaimer above it, the warnings beside it,
and the "as of" line under it. A model receiving ``{"short_term_gain": "123456.78"}`` sees a number
that looks like a fact. So every payload here carries when it was computed and what it came from.

**Confidence.** This is the load-bearing part. A large share of disposals in this dataset have a
cost basis the replay could not establish -- a sizeable share on a real ledger -- and each of
those books zero basis, which can only *overstate* the resulting gain. Handing that total to a model
*without* that conclusion attached would industrialise the problem the UI already had: the model
writes "your 2026 short-term gains were $X" into a report, confidently, and the caveat never travels
with the number.

(An earlier version of this docstring quoted ``docs/reports/phase-3.md``'s "330 of 333" and its
conclusion that the figure "should not be treated as meaningful". Those figures were measured
against the Phase 3 engine and no longer reproduce -- see the 2026-08-12 supersession note at the
top of that report. Nothing below depended on the numbers: the ratio has always been computed from
the live counters, which is exactly why the stale prose did not change any behaviour. It is
corrected here so the example does not read as a current measurement.)

So :func:`tax_summary` computes the uncertainty ratio from the same counters the report already
carries and emits an explicit, model-addressed caveat when it is high. The rule this module holds
to: **a number and its trustworthiness travel together, or neither is returned.**
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from app.config import Settings
from app.datasource import ledger_db_path
from app.db import sqlite
from app.db.duck import Interval
from app.ingest.manifest import load_declarations
from app.market import macro as macro_module
from app.rules import service as rules_service
from app.tax import engine as tax_engine

__all__ = [
    "LedgerMissingError",
    "decision_table",
    "macro_snapshot",
    "tax_summary",
]

#: Above this share of disposals carrying an unverifiable basis, the year's gain totals are reported
#: as an upper bound rather than an estimate.
#:
#: 0.20 was chosen to catch a *degraded* year rather than only a catastrophic one, on the reasoning
#: that a fifth of a filing resting on guessed basis is already past the point where a total should
#: be quoted plainly. A functional test then measured the live figure on a real ledger: a ratio
#: just above 0.20 -- so the caveat fires, but by only a couple of percentage points.
#:
#: That margin is the argument for this number, and it is worth keeping because the earlier draft of
#: this comment got it backwards. It justified 0.20 as "well below the 0.99 the data shows", quoting
#: a Phase 3 measurement that no longer reproduces against the current engine. Had the threshold been
#: set anywhere near that figure -- which the old justification made sound safe -- it would not fire
#: on today's data at all, and the totals would be presented as reliable.
UNCERTAIN_BASIS_CAVEAT_THRESHOLD = 0.20


class LedgerMissingError(RuntimeError):
    """No ledger on disk yet.

    Distinct from "a year with no disposals", exactly as the HTTP layer distinguishes them: one
    means *import something*, the other means *nothing was sold*. A model told "no data" for the
    first case would reasonably conclude the user had no taxable events, which is a different and
    wrong answer.
    """


def _money(value: Decimal) -> str:
    """Decimals cross this boundary as strings, never as floats.

    The whole ledger is ``Decimal`` precisely so a cent is never lost to binary floating point
    (see ``app.core.money``). Serialising to a JSON number would undo that at the last step, and
    a model reading ``123456.7800000001`` has been handed a worse figure than the one computed.
    """
    return str(value)


def _provenance(generated_at: dt.datetime, source: str) -> dict[str, Any]:
    return {
        "generated_at": generated_at.isoformat(),
        "source": source,
    }


def tax_summary(settings: Settings, *, year: int) -> dict[str, Any]:
    """Realised gains, wash sales and Form 8949 totals for one tax year -- with their confidence.

    Mirrors ``app.api.tax._build``: same ledger path, same read-only connection, same engine call,
    and -- load-bearing -- the same user declarations. An MCP client asking for tax figures must
    get the ones the Tax page shows, not a second opinion computed without the manifest.
    """
    ledger_file = ledger_db_path(settings)
    if not ledger_file.exists():
        raise LedgerMissingError(
            "no ledger yet -- broker exports have not been imported, so no tax figures exist. "
            "This is not the same as a year with no disposals."
        )

    manifest = load_declarations(settings)
    with sqlite.connect(ledger_file, read_only=True) as conn:
        report = tax_engine.report_from_ledger(
            conn,
            tax_year=year,
            opening=manifest.opening_positions if manifest else (),
        )

    gains = report.gains
    row_count = len(gains.rows)
    uncertain = gains.rows_with_uncertain_basis
    ratio = (uncertain / row_count) if row_count else 0.0

    quality: dict[str, Any] = {
        "disposals_total": row_count,
        "disposals_with_uncertain_basis": uncertain,
        "disposals_with_unknown_fees": gains.rows_with_unknown_fees,
        "uncertain_basis_ratio": round(ratio, 4),
        "confidence": "upper_bound" if ratio > UNCERTAIN_BASIS_CAVEAT_THRESHOLD else "reliable",
    }

    # Addressed to the model that will read it, not to a developer. A structured ratio alone is
    # something a model can reason past ("mostly fine"); a sentence stating the consequence is much
    # harder to discard when it is writing prose for a human about money.
    if ratio > UNCERTAIN_BASIS_CAVEAT_THRESHOLD:
        quality["caveat"] = (
            f"{uncertain} of {row_count} disposals ({ratio:.0%}) have an unverifiable cost basis, "
            "because the source broker export does not carry the acquisition detail. The gain "
            "totals below are therefore an UPPER BOUND, not an estimate. Do not present them as "
            "final figures, do not put them on a tax return, and say plainly that they are "
            "provisional whenever you quote them."
        )

    return {
        "tax_year": report.tax_year,
        "short_term": {
            "proceeds": _money(gains.short_term_proceeds),
            "basis": _money(gains.short_term_basis),
            "gain": _money(gains.short_term_gain),
        },
        "long_term": {
            "proceeds": _money(gains.long_term_proceeds),
            "basis": _money(gains.long_term_basis),
            "gain": _money(gains.long_term_gain),
        },
        "net_gain": _money(gains.net_gain),
        "wash_sales": {
            "deferred_total": _money(gains.disallowed_loss_total),
            # Kept separate from the deferred total for the same reason the engine keeps them
            # separate: a Rev. Rul. 2008-5 disallowance into an IRA is gone, not postponed, and
            # collapsing the two would understate a permanent loss as a timing difference.
            "permanently_disallowed_total": _money(gains.permanently_disallowed_total),
            "permanent_disallowance_count": report.permanent_disallowance_count,
        },
        "excluded_accounts": list(gains.excluded_account_ids),
        "data_quality": quality,
        # One row per (kind, account) rather than the ungrouped detail: the full list runs to
        # hundreds of entries on a degraded year, which is unreadable for a person and pure token
        # cost for a model. The counts carry the same information.
        "warning_groups": [
            {"kind": group.kind, "account_id": group.account_id, "count": group.count}
            for group in report.warning_groups
        ],
        "provenance": _provenance(report.generated_at, "ledger replay (SQLite)"),
    }


def _evidence(item: Any) -> dict[str, Any]:
    """One horizon's forward-return measurement.

    ``hit_rate`` and ``baseline_hit_rate`` are emitted together, always, and ``None`` is preserved
    rather than coerced to ``0.0``. Both rules come straight from the model's own docstring: a rule
    with too few triggers has *no* measurable history, and a 0.0 there is a claim that something was
    measured and found to be zero. A model would read that as a real, terrible edge.

    Emitting the pair together matters for the same reason the UI never separates them: a 55% hit
    rate reads as an edge right up until the baseline turns out to be 56%.
    """
    return {
        "horizon_bars": item.horizon,
        "hit_rate": item.hit_rate,
        "baseline_hit_rate": item.baseline_hit_rate,
        "edge": item.edge,
        "median_return": item.median_return,
        "baseline_median_return": item.baseline_median_return,
        "sample_size": item.sample_size,
        # Overlapping windows inflate a naive sample count; this is the number significance was
        # actually computed against, and dropping it would let a model quote n=340 for an effect
        # measured on 312 independent observations.
        "independent_sample_size": item.independent_sample_size,
        "significance": item.significance.value,
    }


def decision_table(settings: Settings, *, symbol: str, interval: str = "1d") -> dict[str, Any]:
    """Every catalog rule evaluated for one symbol, with the evidence behind each verdict.

    Mirrors ``app.api.rules.decisions``. A rule that cannot be evaluated degrades to a row carrying
    its reason rather than raising, so a partial answer is normal here and is not an error.
    """
    table = rules_service.build_decision_table(settings, symbol, Interval(interval))

    return {
        "symbol": table.symbol,
        "interval": table.interval.value,
        "bars_evaluated": table.bars_evaluated,
        "rows": [
            {
                "rule_id": row.rule.rule_id,
                "name": row.rule.name,
                "expression": row.rule.expression,
                "state": row.state.state.value,
                "as_of": None if row.state.as_of is None else row.state.as_of.isoformat(),
                "last_trigger": (
                    None if row.state.last_trigger is None else row.state.last_trigger.isoformat()
                ),
                "triggers_in_history": row.state.triggers_in_history,
                "evidence": [_evidence(item) for item in row.evidence],
                "warnings": [
                    {"kind": warning.kind, "message": warning.message} for warning in row.warnings
                ],
            }
            for row in table.rows
        ],
        "warnings": [
            {"kind": warning.kind, "message": warning.message} for warning in table.warnings
        ],
        "provenance": _provenance(table.generated_at, "stored bars + rule catalog"),
    }


def macro_snapshot(settings: Settings) -> dict[str, Any]:
    """The macro panel: rates, curve, energy, volatility, sentiment.

    Mirrors ``app.api.macro.snapshot``. ``refresh`` is deliberately not exposed: a model calling a
    tool in a loop must not be able to force an unbounded number of upstream provider round-trips
    against rate-limited APIs. The cached view is the correct default for an agent, and its age is
    reported in ``provenance`` so staleness is visible rather than silent.
    """
    snapshot = macro_module.build_snapshot(settings)

    return {
        "rates": [_tile(tile) for tile in snapshot.rates],
        "oil": [_tile(tile) for tile in snapshot.oil],
        "movers": [
            {
                "symbol": mover.symbol,
                "label": mover.label,
                "price": mover.price,
                "currency": mover.currency,
            }
            for mover in snapshot.movers
        ],
        "fear_greed": (
            None
            if snapshot.fear_greed is None
            else {
                "score": snapshot.fear_greed.score,
                "rating": snapshot.fear_greed.rating.value,
                "source": snapshot.fear_greed.source.value,
                "as_of": snapshot.fear_greed.as_of.isoformat(),
            }
        ),
        "warnings": [
            {"kind": warning.kind, "message": warning.message} for warning in snapshot.warnings
        ],
        "provenance": _provenance(snapshot.generated_at, "macro providers (FRED, CNN, market data)"),
    }


def _tile(tile: Any) -> dict[str, Any]:
    """One macro tile, with its own `as_of` and source rather than the snapshot's.

    Per-tile provenance, not per-snapshot: a macro panel routinely mixes a yield published this
    morning with a weekly series and a sentiment reading that failed to refresh, and one timestamp
    for the whole page would describe none of them. The UI already renders provenance per tile for
    exactly this reason; the tool contract matches it rather than flattening it away.
    """
    return {
        "key": tile.key,
        "label": tile.label,
        # Left as a float deliberately. `_money` exists for ledger Decimals, where a lost cent is
        # a wrong tax figure; a Treasury yield or a crude price is genuinely a float and dressing
        # it as an exact decimal string would imply a precision the source does not have.
        "value": tile.value,
        "unit": tile.unit.value,
        "as_of": None if tile.as_of is None else tile.as_of.isoformat(),
        "source": tile.source.value,
    }
