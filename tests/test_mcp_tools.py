"""The MCP tool layer (`app.mcp.tools`).

These tests exercise the pure adapter, not a running MCP server -- see `app/mcp/__init__.py` for
why the two are separate. The point of most of them is not that a field is copied across correctly;
it is that the *confidence* of a number travels with the number. A model reading a tool result has
none of the context a person reading the page has: no disclaimer above it, no warning list beside
it, no "as of" line beneath it. Whatever the payload does not say, the model will not know.
"""

from __future__ import annotations

import datetime as dt
import pathlib
import tempfile
from decimal import Decimal

import pytest

from app.mcp import tools


class _Gains:
    """Stand-in for `GainsReport`, carrying only what `tax_summary` reads."""

    def __init__(self, *, rows: int, uncertain: int, unknown_fees: int = 0) -> None:
        self.rows = tuple(range(rows))
        self.rows_with_uncertain_basis = uncertain
        self.rows_with_unknown_fees = unknown_fees
        self.short_term_proceeds = Decimal("1000.00")
        self.short_term_basis = Decimal("400.00")
        self.short_term_gain = Decimal("600.00")
        self.long_term_proceeds = Decimal("0.00")
        self.long_term_basis = Decimal("0.00")
        self.long_term_gain = Decimal("0.00")
        self.disallowed_loss_total = Decimal("12.34")
        self.permanently_disallowed_total = Decimal("56.78")
        self.excluded_account_ids = ("ira-1",)

    @property
    def net_gain(self) -> Decimal:
        return self.short_term_gain + self.long_term_gain


class _Report:
    def __init__(self, gains: _Gains) -> None:
        self.tax_year = 2026
        self.generated_at = dt.datetime(2026, 4, 1, 12, 0, tzinfo=dt.UTC)
        self.gains = gains
        self.warning_groups = ()
        self.permanent_disallowance_count = 1


def _summary(monkeypatch: pytest.MonkeyPatch, *, rows: int, uncertain: int) -> dict:
    """Drive `tax_summary` against a stub report, bypassing SQLite entirely.

    The engine is exercised by its own 1,500-test suite; what needs testing here is the shaping.
    """
    report = _Report(_Gains(rows=rows, uncertain=uncertain))

    class _Settings:
        ledger_path = type("P", (), {"exists": staticmethod(lambda: True)})()
        # `tax_summary` reads the account manifest for opening positions and declared cash -- the
        # same declarations the Tax page uses, so that an MCP client and the UI cannot disagree
        # about realised gain. Pointed at a directory with no manifest in it, which is the ordinary
        # "user has not written one" path and leaves these tests measuring what they always did.
        data_dir = pathlib.Path(tempfile.gettempdir()) / "invdash-no-manifest-here"
        data_source = "local"

    monkeypatch.setattr(tools, "ledger_db_path", lambda settings: settings.ledger_path)
    monkeypatch.setattr(tools.sqlite, "connect", lambda *a, **k: _NullCtx())
    monkeypatch.setattr(tools.tax_engine, "report_from_ledger", lambda *a, **k: report)
    return tools.tax_summary(_Settings(), year=2026)


class _NullCtx:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return False


def test_a_degraded_year_is_labelled_an_upper_bound_with_a_caveat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHAT THIS PREVENTS: the finding this whole tool contract exists for.

    `docs/reports/phase-3.md` records 330 of 333 disposals with unverifiable basis and concludes the
    total "should not be treated as meaningful". If that conclusion does not travel in the payload,
    a model quotes the figure as fact and the caveat dies at the API boundary.
    """
    result = _summary(monkeypatch, rows=333, uncertain=330)
    quality = result["data_quality"]

    assert quality["confidence"] == "upper_bound"
    assert quality["disposals_with_uncertain_basis"] == 330
    assert quality["uncertain_basis_ratio"] == pytest.approx(0.9910, abs=1e-4)
    # Addressed to the reader of the tool result, and explicit about the consequence -- a bare
    # ratio is something a model can rationalise past.
    assert "UPPER BOUND" in quality["caveat"]
    assert "330 of 333" in quality["caveat"]


def test_a_clean_year_carries_no_caveat_and_is_not_hedged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHAT THIS PREVENTS: crying wolf.

    A caveat on every response trains the reader to ignore it. A year whose basis is fully known
    must come back plainly, or the warning on the year that needs it carries no signal.
    """
    result = _summary(monkeypatch, rows=100, uncertain=0)
    quality = result["data_quality"]

    assert quality["confidence"] == "reliable"
    assert "caveat" not in quality


def test_the_threshold_catches_a_merely_degraded_year_not_only_a_catastrophic_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHAT THIS PREVENTS: a threshold set so high it only fires on the case we already knew about.

    A quarter of a filing resting on guessed basis is already past the point where a total should be
    quoted without qualification, even though it is nowhere near 2026's 99%.
    """
    result = _summary(monkeypatch, rows=100, uncertain=25)
    assert result["data_quality"]["confidence"] == "upper_bound"


def test_money_crosses_the_boundary_as_strings_never_floats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHAT THIS PREVENTS: undoing `Decimal` at the last step.

    The ledger is Decimal end to end so a cent is never lost to binary floating point. Serialising
    to a JSON number would reintroduce exactly that at the tool boundary, and a model reading
    `600.0000000001` has been handed a worse number than the one computed.
    """
    result = _summary(monkeypatch, rows=1, uncertain=0)

    assert result["short_term"]["gain"] == "600.00"
    assert isinstance(result["net_gain"], str)
    assert isinstance(result["wash_sales"]["deferred_total"], str)


def test_permanent_and_deferred_disallowance_stay_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHAT THIS PREVENTS: collapsing a permanent loss into a timing difference.

    A Rev. Rul. 2008-5 disallowance into an IRA is gone, not postponed. The engine keeps the two
    totals apart deliberately; summing them here would misreport a destroyed loss as deferred.
    """
    result = _summary(monkeypatch, rows=1, uncertain=0)

    assert result["wash_sales"]["deferred_total"] == "12.34"
    assert result["wash_sales"]["permanently_disallowed_total"] == "56.78"


def test_a_missing_ledger_is_distinguishable_from_a_year_with_no_disposals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHAT THIS PREVENTS: a model concluding the user had no taxable events.

    "Nothing imported" and "nothing sold" are different answers, and the HTTP layer already keeps
    them apart. A tool that flattened both to an empty result would let an agent state, wrongly and
    confidently, that there were no disposals.
    """

    class _Settings:
        ledger_path = type("P", (), {"exists": staticmethod(lambda: False)})()
        data_dir = pathlib.Path(tempfile.gettempdir()) / "invdash-no-manifest-here"
        data_source = "local"

    monkeypatch.setattr(tools, "ledger_db_path", lambda settings: settings.ledger_path)
    with pytest.raises(tools.LedgerMissingError) as excinfo:
        tools.tax_summary(_Settings(), year=2026)

    assert "not the same as a year with no disposals" in str(excinfo.value)
