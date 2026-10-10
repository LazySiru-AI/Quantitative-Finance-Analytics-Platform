"""The reverse institutions lookup: which tracked filers hold one symbol.

`uat/feedback/BACKLOG.md` names `institutions-no-symbol-search-or-reverse-link-from-ticker-portfolio`
twice as the largest unbuilt thing the persona runs surfaced -- there was no way to ask "which
tracked filers hold NVDA".

**The tests that matter most here are the ones about an empty answer.** A reverse lookup walks every
tracked filer over the network. If some of those fetches fail and the endpoint returns an empty list
anyway, "no tracked filer holds NVDA" is false and the reader cannot tell. Three tests below exist
only to keep that distinction alive.

No test here touches the network: every fund is supplied through `find_holders(funds=...)` and the
snapshots come from a stub client, so a failure is about this module's logic and never about SEC
being slow.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from app.config import Settings
from app.institutions import holders
from app.institutions.models import FundRef, Holding, Snapshot, Source

PERIOD = dt.date(2026, 6, 30)
FILED = dt.date(2026, 8, 14)

NVDA_CUSIP = "67066G104"
AMD_CUSIP = "007903107"


def _fund(key: str, name: str) -> FundRef:
    return FundRef(key=key, name=name, source=Source.THIRTEEN_F, cik="0001067983")


def _holding(cusip: str, issuer: str, *, ticker: str | None = None, value: str = "1000000") -> Holding:
    return Holding(
        cusip=cusip,
        issuer=issuer,
        value=Decimal(value),
        shares=Decimal("1000"),
        weight=Decimal("0.10"),
        ticker=ticker,
    )


def _snapshot(fund: FundRef, *rows: Holding, rescaled: bool = False) -> Snapshot:
    return Snapshot(
        fund=fund,
        period=PERIOD,
        filed=FILED,
        accession="0001067983-26-000001",
        total_value=Decimal("10000000"),
        holdings=tuple(rows),
        value_units_rescaled=rescaled,
    )


class _StubClient:
    """Stands in for `EdgarClient`.

    Deliberately bare. The first version of this stub offered a `close()` method, and because
    `find_holders` called it the tests passed while the real code raised `AttributeError` on its
    first live call -- `EdgarClient` has no `close`. A stub with a wider interface than the class it
    replaces makes every test that uses it prove less than it appears to, so this one has nothing on
    it at all: any attribute access the production path needs will fail loudly here too.
    """


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):
    """Route `service.load_latest` and the ledger CUSIP map through per-test fixtures."""

    def install(snapshots: dict[str, Snapshot | Exception], cusip_tickers: dict[str, str]) -> None:
        # Mirrors `service.load_latest`'s real signature exactly -- `fund` positional, `client`
        # keyword-only. The first version had them reversed, which no unit test could catch.
        def fake_load_latest(fund, *, client, settings, as_of=None):
            outcome = snapshots[fund.key]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        monkeypatch.setattr(holders.service, "load_latest", fake_load_latest)
        monkeypatch.setattr(
            holders.catalog, "ledger_cusip_tickers", lambda settings: dict(cusip_tickers)
        )

    return install


class TestMatching:
    def test_matches_on_cusip_from_the_ledger_mapping(self, patched, settings: Settings) -> None:
        brk = _fund("BRK", "Berkshire Hathaway Inc")
        patched(
            {"BRK": _snapshot(brk, _holding(NVDA_CUSIP, "NVIDIA CORP"))},
            {NVDA_CUSIP: "NVDA"},
        )
        result = holders.find_holders(
            "NVDA", settings=settings, client=_StubClient(), funds=(brk,)
        )

        assert [h.key for h in result.holders] == ["BRK"]
        assert result.symbol_resolved is True

    def test_an_unresolvable_symbol_returns_nothing_and_says_so(
        self, patched, settings: Settings
    ) -> None:
        """The lookup's real limit, and the reason `symbol_resolved` exists.

        CUSIP is the only bridge, and it comes from the user's own ledger, so a symbol they have
        never traded resolves to nothing and *cannot* match however many filers hold it. Asked for
        AAPL against this ledger the live endpoint returns zero holders while VTI, VOO and IVV all
        hold it.

        A resolved `Holding.ticker` does not rescue this and a fallback on it was removed as
        unreachable: `service.load_latest` sets that field through `catalog.apply_tickers` from the
        *same* `ledger_cusip_tickers` mapping, so a holding carries a ticker exactly when its CUSIP
        is already in the match set. Hence the ticker being present below and still matching
        nothing -- the empty ledger map is what decides it."""
        ark = _fund("ARKK", "ARK Innovation ETF")
        patched({"ARKK": _snapshot(ark, _holding(NVDA_CUSIP, "NVIDIA CORP", ticker="NVDA"))}, {})

        result = holders.find_holders(
            "NVDA", settings=settings, client=_StubClient(), funds=(ark,)
        )

        assert result.holders == ()
        assert result.symbol_resolved is False, "an empty list here means 'could not look'"
        assert result.checked == result.total == 1, "and not 'a fund failed'"

    def test_issuer_name_never_matches(self, patched, settings: Settings) -> None:
        """The same company is disclosed as 'NVIDIA CORP', 'NVIDIA CORPORATION' and 'Nvidia Corp' by
        different filers in one quarter. Matching on it would attribute someone else's position to a
        symbol, so a holding whose *only* connection is its name must not appear."""
        soros = _fund("SOROS", "Soros Fund Management LLC")
        patched({"SOROS": _snapshot(soros, _holding("999999999", "NVDA HOLDINGS PLC"))}, {})

        result = holders.find_holders(
            "NVDA", settings=settings, client=_StubClient(), funds=(soros,)
        )

        assert result.holders == ()

    def test_a_filer_disclosing_two_share_classes_yields_both_rows(
        self, patched, settings: Settings
    ) -> None:
        brk = _fund("BRK", "Berkshire Hathaway Inc")
        patched(
            {
                "BRK": _snapshot(
                    brk,
                    _holding(NVDA_CUSIP, "NVIDIA CORP", value="900"),
                    _holding("67066G888", "NVIDIA CORP CL B", value="100"),
                )
            },
            {NVDA_CUSIP: "NVDA", "67066G888": "NVDA"},
        )
        result = holders.find_holders(
            "NVDA", settings=settings, client=_StubClient(), funds=(brk,)
        )

        assert len(result.holders) == 2
        assert [str(h.value) for h in result.holders] == ["900", "100"], "sorted by value, descending"


class TestAnEmptyAnswerIsNotAlwaysTheSameAnswer:
    """The three tests this module exists for."""

    def test_a_fund_that_cannot_be_read_is_named_not_skipped(
        self, patched, settings: Settings
    ) -> None:
        good = _fund("BRK", "Berkshire Hathaway Inc")
        bad = _fund("SCION", "Scion Asset Management, LLC")
        patched(
            {
                "BRK": _snapshot(good, _holding(NVDA_CUSIP, "NVIDIA CORP")),
                "SCION": TimeoutError("EDGAR did not respond"),
            },
            {NVDA_CUSIP: "NVDA"},
        )
        result = holders.find_holders(
            "NVDA", settings=settings, client=_StubClient(), funds=(good, bad)
        )

        assert [h.key for h in result.holders] == ["BRK"]
        assert [u.key for u in result.unchecked] == ["SCION"]
        assert "EDGAR did not respond" in result.unchecked[0].reason
        assert (result.checked, result.total) == (1, 2)

    def test_one_unreadable_fund_does_not_abort_the_whole_walk(
        self, patched, settings: Settings
    ) -> None:
        """A failure on the *first* fund must not lose the ones after it -- the regression that
        would turn a partial answer into an empty one."""
        bad = _fund("SCION", "Scion Asset Management, LLC")
        good = _fund("BRK", "Berkshire Hathaway Inc")
        patched(
            {
                "SCION": RuntimeError("parse failed"),
                "BRK": _snapshot(good, _holding(NVDA_CUSIP, "NVIDIA CORP")),
            },
            {NVDA_CUSIP: "NVDA"},
        )
        result = holders.find_holders(
            "NVDA", settings=settings, client=_StubClient(), funds=(bad, good)
        )

        assert [h.key for h in result.holders] == ["BRK"]
        assert result.checked == 1

    def test_a_genuinely_empty_answer_reports_full_coverage(
        self, patched, settings: Settings
    ) -> None:
        """"Nobody holds it" and "I could not check" must be distinguishable. This is the former:
        every fund was read and none held the symbol."""
        brk = _fund("BRK", "Berkshire Hathaway Inc")
        patched({"BRK": _snapshot(brk, _holding(AMD_CUSIP, "ADVANCED MICRO DEVICES"))}, {NVDA_CUSIP: "NVDA"})

        result = holders.find_holders(
            "NVDA", settings=settings, client=_StubClient(), funds=(brk,)
        )

        assert result.holders == ()
        assert result.unchecked == ()
        assert (result.checked, result.total) == (1, 1), "an empty answer over full coverage"


class TestProvenanceTravels:
    def test_a_rescaled_filing_marks_every_row_it_produced(
        self, patched, settings: Settings
    ) -> None:
        """`Snapshot.value_units_rescaled` is a judgement about someone else's data -- a filing whose
        value column was read as thousands and multiplied up. A row derived from one must carry it,
        or the reader sees a figure silently multiplied by a thousand."""
        duq = _fund("DUQUESNE", "Duquesne Family Office LLC")
        patched(
            {"DUQUESNE": _snapshot(duq, _holding(NVDA_CUSIP, "NVIDIA CORP"), rescaled=True)},
            {NVDA_CUSIP: "NVDA"},
        )
        result = holders.find_holders(
            "NVDA", settings=settings, client=_StubClient(), funds=(duq,)
        )

        assert result.holders[0].value_units_rescaled is True

    def test_period_and_accession_travel_with_each_row(self, patched, settings: Settings) -> None:
        brk = _fund("BRK", "Berkshire Hathaway Inc")
        patched({"BRK": _snapshot(brk, _holding(NVDA_CUSIP, "NVIDIA CORP"))}, {NVDA_CUSIP: "NVDA"})

        row = holders.find_holders(
            "NVDA", settings=settings, client=_StubClient(), funds=(brk,)
        ).holders[0]

        assert (row.period, row.filed) == (PERIOD, FILED)
        assert row.accession == "0001067983-26-000001"


class TestInput:
    def test_a_blank_symbol_is_rejected(self, settings: Settings) -> None:
        with pytest.raises(ValueError, match="must not be blank"):
            holders.find_holders("   ", settings=settings, client=_StubClient(), funds=())

    def test_the_symbol_is_normalised_to_upper_case(self, patched, settings: Settings) -> None:
        brk = _fund("BRK", "Berkshire Hathaway Inc")
        patched({"BRK": _snapshot(brk, _holding(NVDA_CUSIP, "NVIDIA CORP"))}, {NVDA_CUSIP: "NVDA"})

        result = holders.find_holders(
            " nvda ", settings=settings, client=_StubClient(), funds=(brk,)
        )

        assert result.symbol == "NVDA"
        assert len(result.holders) == 1
