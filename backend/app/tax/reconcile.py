"""1099-B reconciliation: compare the engine's gains against a broker's official form.

The engine replays a merged ledger from scratch every time; the 1099-B is what the broker actually
filed with the IRS. They must agree, and when they do not, "off by $312" is not a finding — the whole
point of this module is to walk a discrepancy back to the specific lots that produced it.

Two responsibilities live here:

* :func:`parse_1099b_csv` turns a small, user-transcribed CSV (the user copies figures off their
  broker's 1099-B PDF or export) into :class:`Form1099BLine` rows. Parsing is strict: an unrecognised
  or missing column raises rather than being skipped, because a silently dropped row produces a
  reconciliation that looks clean and is not.
* :func:`reconcile` aggregates both sides by ``(symbol, account_id, term)`` and reports a
  :class:`~app.tax.models.ReconcileLine` per key, so a user staring at a mismatch can see exactly
  which disposals to check first.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Final, NamedTuple

from pydantic import BaseModel, ConfigDict

from app.core.models import Money
from app.core.money import parse_decimal, quantize_money
from app.tax.models import (
    GainsReport,
    HoldingTerm,
    ReconcileLine,
    ReconcileReport,
    ReconcileStatus,
)

__all__ = ["Form1099BLine", "Form1099BParseError", "parse_1099b_csv", "reconcile"]


class Form1099BParseError(ValueError):
    """A 1099-B CSV could not be interpreted.

    Raised rather than swallowed. Silently skipping an unrecognised column or a malformed row would
    produce a reconciliation report that is missing data and does not say so — indistinguishable from
    a clean one until the user notices a number is wrong.
    """

    def __init__(self, message: str, *, row: int | None = None) -> None:
        where = f" (row {row})" if row is not None else ""
        super().__init__(f"{message}{where}")
        self.row = row


class Form1099BLine(BaseModel):
    """One line the user transcribed from a broker 1099-B (or its consolidated 1099 export).

    Deliberately narrower than :class:`~app.tax.models.GainRow`: the 1099-B does not carry a
    disposal-level identity the engine can match on, only symbol / account / term, which is exactly
    the granularity :func:`reconcile` compares at.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str
    account_id: str
    term: HoldingTerm
    proceeds: Money
    cost_basis: Money
    wash_disallowed: Money = Decimal(0)
    """Box 1g on the form: the wash-sale loss disallowed amount the broker itself reports. Positive."""
    description: str | None = None


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

#: Header text (lower-cased, whitespace-collapsed) accepted for each field. Anything else in the
#: header row is an unrecognised column and raises -- the house rule is that unknown input raises,
#: because a column silently ignored becomes a row silently dropped.
_HEADER_ALIASES: Final[dict[str, str]] = {
    "symbol": "symbol",
    "ticker": "symbol",
    "account": "account_id",
    "account id": "account_id",
    "account_id": "account_id",
    "term": "term",
    "holding term": "term",
    "proceeds": "proceeds",
    "cost basis": "cost_basis",
    "cost_basis": "cost_basis",
    "basis": "cost_basis",
    "wash sale disallowed": "wash_disallowed",
    "wash sale loss disallowed": "wash_disallowed",
    "wash_disallowed": "wash_disallowed",
    "wash disallowed": "wash_disallowed",
    "disallowed": "wash_disallowed",
    "description": "description",
}

_REQUIRED_FIELDS: Final[frozenset[str]] = frozenset(
    {"symbol", "account_id", "term", "proceeds", "cost_basis"}
)

_TERM_ALIASES: Final[dict[str, HoldingTerm]] = {
    "short": HoldingTerm.SHORT,
    "short term": HoldingTerm.SHORT,
    "short_term": HoldingTerm.SHORT,
    "st": HoldingTerm.SHORT,
    "long": HoldingTerm.LONG,
    "long term": HoldingTerm.LONG,
    "long_term": HoldingTerm.LONG,
    "lt": HoldingTerm.LONG,
}


def _normalise_header(raw: str) -> str:
    return " ".join(raw.strip().lower().split())


def parse_1099b_csv(text: str) -> list[Form1099BLine]:
    """Parse a user-transcribed 1099-B CSV into :class:`Form1099BLine` rows.

    Accepts the documented header aliases above, case-insensitively and tolerant of surrounding
    whitespace. Money fields go through :func:`app.core.money.parse_decimal`, so ``$1,234.56`` and
    ``(123.45)`` parse exactly as they do everywhere else in this codebase.

    Raises:
        Form1099BParseError: The file is empty, a header column is not recognised, a required column
            is missing, a row has the wrong number of fields, a term value is not recognised, or a
            money field fails to parse.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        header_row = next(reader)
    except StopIteration:
        raise Form1099BParseError("empty file: no header row") from None

    field_by_index: dict[int, str] = {}
    for idx, raw_header in enumerate(header_row):
        normalised = _normalise_header(raw_header)
        if normalised not in _HEADER_ALIASES:
            raise Form1099BParseError(f"unrecognised column {raw_header!r}")
        field_by_index[idx] = _HEADER_ALIASES[normalised]

    missing = _REQUIRED_FIELDS - set(field_by_index.values())
    if missing:
        raise Form1099BParseError(f"missing required column(s): {', '.join(sorted(missing))}")

    lines: list[Form1099BLine] = []
    for row_num, row in enumerate(reader, start=2):  # header occupies row 1
        if not row or all(not cell.strip() for cell in row):
            continue  # blank line, tolerated
        if len(row) != len(header_row):
            raise Form1099BParseError(
                f"row has {len(row)} fields, expected {len(header_row)}", row=row_num
            )

        values = {field_by_index[idx]: cell.strip() for idx, cell in enumerate(row)}

        symbol = values["symbol"]
        account_id = values["account_id"]
        if not symbol:
            raise Form1099BParseError("empty Symbol", row=row_num)
        if not account_id:
            raise Form1099BParseError("empty Account", row=row_num)

        term_raw = values["term"].lower()
        if term_raw not in _TERM_ALIASES:
            raise Form1099BParseError(f"unrecognised term {values['term']!r}", row=row_num)

        proceeds = parse_decimal(values["proceeds"], field="Proceeds", allow_empty=False)
        cost_basis = parse_decimal(values["cost_basis"], field="Cost Basis", allow_empty=False)
        wash_disallowed = parse_decimal(
            values.get("wash_disallowed"), field="Wash Sale Disallowed"
        )

        lines.append(
            Form1099BLine(
                symbol=symbol.upper(),
                account_id=account_id,
                term=_TERM_ALIASES[term_raw],
                proceeds=proceeds,
                cost_basis=cost_basis,
                wash_disallowed=wash_disallowed if wash_disallowed is not None else Decimal(0),
                description=values.get("description") or None,
            )
        )

    return lines


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

_Key = tuple[str, str, HoldingTerm]


@dataclass
class _EngineAgg:
    proceeds: Decimal = Decimal(0)
    basis: Decimal = Decimal(0)
    gain: Decimal = Decimal(0)
    disposal_ids: list[str] = field(default_factory=list)


@dataclass
class _FormAgg:
    proceeds: Decimal = Decimal(0)
    basis: Decimal = Decimal(0)
    wash_disallowed: Decimal = Decimal(0)

    @property
    def gain(self) -> Decimal:
        """Mirrors ``GainRow.reportable_gain_loss``: proceeds minus basis, wash-sale add-back applied.

        The 1099-B reports proceeds and cost basis before any wash-sale adjustment, plus the
        disallowed amount as a separate box (1g). The reportable gain/loss the broker actually
        arrives at is ``proceeds - cost_basis + wash_disallowed`` -- the add-back shrinks a loss (or
        turns part of it into a smaller loss), never enlarges one, which is the same relationship
        ``GainRow.reportable_gain_loss`` has to ``disallowed_loss`` on the engine side.
        """
        return self.proceeds - self.basis + self.wash_disallowed


class _Note(NamedTuple):
    """A reconciliation note in three forms at once.

    ``text`` is the canonical English sentence (what ``ReconcileLine.note`` has always carried, and
    what logs and tests read). ``code`` is a stable, language-neutral id for that sentence, and
    ``params`` the values interpolated into it -- together they let a localised client render its own
    translation, in its own word order, and fall back to ``text`` when it does not recognise the
    code. Keeping all three on one return value is what stops the English and the code drifting: a
    builder cannot emit one without the other.
    """

    text: str
    code: str
    params: dict[str, str] | None = None


def _missing_from_engine_note(account_id: str) -> _Note:
    base = (
        "Present on the 1099-B but no matching disposal was computed for this symbol, account and "
        "term."
    )
    if "webull" in account_id.lower():
        return _Note(
            base + " Webull's Account Statement export is known to omit some transactions.",
            "missing_from_engine_webull",
        )
    return _Note(
        base + " Likely a transaction missing from the imported export for this account.",
        "missing_from_engine_generic",
    )


def _missing_from_1099b_note() -> _Note:
    return _Note(
        "Computed by the engine but not present on the 1099-B for this symbol, account and term -- "
        "check whether this disposal was included when transcribing the form.",
        "missing_from_1099b",
    )


def _amount_differs_note(
    *, engine_basis: Decimal, form_basis: Decimal, wash_disallowed: Decimal, symbol: str
) -> _Note | None:
    basis_delta = engine_basis - form_basis
    if wash_disallowed != 0 and abs(basis_delta) == wash_disallowed:
        higher = basis_delta > 0
        direction = "higher" if higher else "lower"
        return _Note(
            f"Engine cost basis is {direction} than the 1099-B by exactly the wash-sale disallowed "
            f"amount (${wash_disallowed}) the form reports for {symbol}; the engine may not have "
            "applied this wash sale, or applied it against a different lot.",
            "amount_differs_wash_higher" if higher else "amount_differs_wash_lower",
            {"amount": str(wash_disallowed), "symbol": symbol},
        )
    return None


def reconcile(gains: GainsReport, form_lines: Sequence[Form1099BLine]) -> ReconcileReport:
    """Compare the engine's :class:`~app.tax.models.GainsReport` against 1099-B lines.

    Both sides are aggregated by ``(symbol, account_id, term)`` -- the granularity a 1099-B actually
    reports at, coarser than the individual-disposal granularity of :class:`GainRow`. Money is summed
    as exact :class:`~decimal.Decimal`; the running totals are only quantized to cents at the point
    they become comparison inputs and report fields, so intermediate rounding never masks or invents
    a discrepancy.
    """
    engine_agg: dict[_Key, _EngineAgg] = {}
    for row in gains.rows:
        key: _Key = (row.symbol, row.account_id, row.term)
        agg = engine_agg.setdefault(key, _EngineAgg())
        agg.proceeds += row.proceeds
        agg.basis += row.cost_basis
        agg.gain += row.reportable_gain_loss
        agg.disposal_ids.append(row.disposal_id)

    form_agg: dict[_Key, _FormAgg] = {}
    for line in form_lines:
        key = (line.symbol, line.account_id, line.term)
        form_entry = form_agg.setdefault(key, _FormAgg())
        form_entry.proceeds += line.proceeds
        form_entry.basis += line.cost_basis
        form_entry.wash_disallowed += line.wash_disallowed

    all_keys = sorted(set(engine_agg) | set(form_agg), key=lambda k: (k[0], k[1], k[2]))

    lines: list[ReconcileLine] = []
    matched = 0
    differing = 0

    for symbol, account_id, term in all_keys:
        engine = engine_agg.get((symbol, account_id, term))
        form = form_agg.get((symbol, account_id, term))

        if engine is not None and form is not None:
            engine_proceeds = quantize_money(engine.proceeds)
            engine_basis = quantize_money(engine.basis)
            engine_gain = quantize_money(engine.gain)
            form_proceeds = quantize_money(form.proceeds)
            form_basis = quantize_money(form.basis)
            form_gain = quantize_money(form.gain)

            clean = (
                engine_proceeds == form_proceeds
                and engine_basis == form_basis
                and engine_gain == form_gain
            )
            if clean:
                matched += 1
                recon_line = ReconcileLine(
                    symbol=symbol,
                    account_id=account_id,
                    term=term,
                    status=ReconcileStatus.MATCHED,
                    engine_proceeds=engine_proceeds,
                    engine_basis=engine_basis,
                    engine_gain=engine_gain,
                    form_proceeds=form_proceeds,
                    form_basis=form_basis,
                    form_gain=form_gain,
                    disposal_ids=tuple(engine.disposal_ids),
                )
            else:
                differing += 1
                note = _amount_differs_note(
                    engine_basis=engine_basis,
                    form_basis=form_basis,
                    wash_disallowed=form.wash_disallowed,
                    symbol=symbol,
                )
                recon_line = ReconcileLine(
                    symbol=symbol,
                    account_id=account_id,
                    term=term,
                    status=ReconcileStatus.AMOUNT_DIFFERS,
                    engine_proceeds=engine_proceeds,
                    engine_basis=engine_basis,
                    engine_gain=engine_gain,
                    form_proceeds=form_proceeds,
                    form_basis=form_basis,
                    form_gain=form_gain,
                    disposal_ids=tuple(engine.disposal_ids),
                    note=note.text if note else None,
                    note_code=note.code if note else None,
                    note_params=note.params if note else None,
                )
        elif engine is not None:
            differing += 1
            _note = _missing_from_1099b_note()
            recon_line = ReconcileLine(
                symbol=symbol,
                account_id=account_id,
                term=term,
                status=ReconcileStatus.MISSING_FROM_1099B,
                engine_proceeds=quantize_money(engine.proceeds),
                engine_basis=quantize_money(engine.basis),
                engine_gain=quantize_money(engine.gain),
                disposal_ids=tuple(engine.disposal_ids),
                note=_note.text,
                note_code=_note.code,
                note_params=_note.params,
            )
        else:
            assert form is not None  # one side must be present -- key came from the union
            differing += 1
            _note = _missing_from_engine_note(account_id)
            recon_line = ReconcileLine(
                symbol=symbol,
                account_id=account_id,
                term=term,
                status=ReconcileStatus.MISSING_FROM_ENGINE,
                form_proceeds=quantize_money(form.proceeds),
                form_basis=quantize_money(form.basis),
                form_gain=quantize_money(form.gain),
                note=_note.text,
                note_code=_note.code,
                note_params=_note.params,
            )

        lines.append(recon_line)

    total_gain_delta = quantize_money(sum((line.gain_delta for line in lines), Decimal(0)))

    return ReconcileReport(
        lines=tuple(lines),
        matched_count=matched,
        differing_count=differing,
        total_gain_delta=total_gain_delta,
    )
