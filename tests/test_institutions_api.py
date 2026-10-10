"""Integration tests for the institutions HTTP API (`app.api.institutions`) and, by necessity, the
service layer it calls (`app.institutions.service`) -- the two are shipped and tested together in
this phase, and the service module has no router of its own to exercise it from.

`app.main` already wires this router in (`app.include_router(institutions.router)`), but this file
follows `tests/test_macro_api.py`'s pattern anyway: a bare `FastAPI()` around just
`institutions.router`, so this suite never depends on the rest of the application's startup (the
ledger migration in `app.main`'s lifespan, every other router's imports) succeeding first.

No test makes a network call. Every EDGAR interaction goes through `httpx.MockTransport`, driven
either by the real captured fixtures in `tests/fixtures/institutions/` (for the tests that assert
real, checkable figures -- the two Berkshire 13F quarters, the two IVV NPORT-P periods) or by small
synthetic filings built inline (for tests where only the *bookkeeping* -- which accession won, what
status code came back -- is under test, not the holdings content). `FakeEdgarSite` below is the one
seam shared by both: it is not `EdgarClient` and does not try to be, it is a fake HTTP server for
the handful of URL shapes `app.institutions.service` calls.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import institutions as institutions_api
from app.config import Settings
from app.core.models import Instrument
from app.db import sqlite as ledger
from app.institutions import catalog
from app.institutions import service as institutions_service
from app.institutions.edgar import EdgarClient
from app.institutions.models import FundRef

FIXTURES = Path(__file__).parent / "fixtures" / "institutions"


def _load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _fund(key: str) -> FundRef:
    fund = catalog.find(key)
    assert fund is not None, f"test fixture assumes {key!r} is in the default catalog"
    return fund


def _nodash(accession: str) -> str:
    return accession.replace("-", "")


# ---------------------------------------------------------------------------
# Synthetic filings -- for tests where only bookkeeping (which accession won, which status code
# came back) is under test, not the holdings content itself.
# ---------------------------------------------------------------------------

_EMPTY_13F = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
    "</informationTable>"
)

_EMPTY_NPORT_TEMPLATE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<edgarSubmission xmlns="http://www.sec.gov/edgar/nport">'
    "<formData><genInfo><repPdDate>{period}</repPdDate><repPdEnd>{period}</repPdEnd></genInfo>"
    "<invstOrSecs></invstOrSecs></formData>"
    "</edgarSubmission>"
)


def _submissions(rows: list[tuple[str, str, str, str]]) -> dict[str, Any]:
    """A minimal `filings.recent`-shaped submissions payload.

    ``rows`` are ``(form, filingDate, reportDate, accession)`` tuples, matching the four parallel
    arrays `EdgarClient.list_filings` actually reads -- everything else a real submissions payload
    carries (`cik`, `name`, `size`, ...) is irrelevant to this module and omitted.
    """
    return {
        "filings": {
            "recent": {
                "accessionNumber": [r[3] for r in rows],
                "filingDate": [r[1] for r in rows],
                "reportDate": [r[2] for r in rows],
                "form": [r[0] for r in rows],
            }
        }
    }


class FakeEdgarSite:
    """An in-memory stand-in for the handful of EDGAR URL shapes `app.institutions.service` calls.

    Routes purely on URL shape, never touching the network (`httpx.MockTransport` guarantees that
    for the whole test process, not just this class). ``index.json`` always answers with the same
    two-file directory listing -- ``primary_doc.xml`` plus a second, arbitrarily-named XML -- which
    is a real shape for both a 13F (`EdgarClient.holdings_document_url` picks the non-primary file)
    and an NPORT (it picks `primary_doc.xml`), so one fake listing serves both `Source`s. A document
    request for an accession not present in ``documents`` gets ``default_document`` instead, so a
    candidate window wider than the real fixtures on hand still resolves to a valid (if
    uninteresting) filing rather than failing on a 404 EDGAR itself would never actually send here.
    """

    def __init__(
        self,
        *,
        submissions: Any | None = None,
        atom: str | None = None,
        documents: dict[str, str] | None = None,
        default_document: str = _EMPTY_13F,
    ) -> None:
        self._submissions = submissions
        self._atom = atom
        self._documents = documents or {}
        self._default_document = default_document
        self.requested_urls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested_urls.append(url)
        user_agent = request.headers.get("user-agent", "")
        assert "@" in user_agent, f"SEC requires a contactable User-Agent, got {user_agent!r}"

        if "submissions/CIK" in url:
            assert self._submissions is not None, f"no submissions fixture configured for {url!r}"
            return httpx.Response(200, json=self._submissions)
        if "browse-edgar" in url and "output=atom" in url:
            assert self._atom is not None, f"no atom fixture configured for {url!r}"
            return httpx.Response(200, text=self._atom)
        if url.endswith("index.json"):
            return httpx.Response(
                200,
                json={"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "info.xml"}]}},
            )
        if url.endswith("primary_doc.xml") or url.endswith("info.xml"):
            accession = url.rstrip("/").split("/")[-2]
            body = self._documents.get(accession, self._default_document)
            return httpx.Response(200, text=body)
        raise AssertionError(f"FakeEdgarSite has no route configured for {url!r}")

    def client(self) -> EdgarClient:
        return EdgarClient(client=httpx.Client(transport=httpx.MockTransport(self.handler)))


def _failing_client(status_code: int, *, headers: dict[str, str] | None = None) -> EdgarClient:
    """An `EdgarClient` whose very first HTTP call (the submissions/atom listing) fails this way."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={}, headers=headers or {})

    return EdgarClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _timeout_client() -> EdgarClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    return EdgarClient(client=httpx.Client(transport=httpx.MockTransport(handler)))


# ---------------------------------------------------------------------------
# App + client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app() -> FastAPI:
    """A bare app around just the institutions router -- see the module docstring."""
    fastapi_app = FastAPI()
    fastapi_app.include_router(institutions_api.router)
    return fastapi_app


@pytest.fixture
def client(settings: Settings, app: FastAPI) -> TestClient:
    """`settings` (from `tests/conftest.py`) redirects every path to `tmp_path` -- no test here
    touches the user's real ledger or cache."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /api/institutions/funds -- must never touch the network
# ---------------------------------------------------------------------------


class TestFundsEndpoint:
    def test_lists_the_static_catalog_with_no_network_call(self, client: TestClient) -> None:
        """No `build_client` monkeypatch is installed for this test at all -- if this endpoint ever
        started calling `service.build_client`, the default `EdgarClient` would try to reach the
        real network and this test would hang or fail, not silently pass."""
        response = client.get("/api/institutions/funds")

        assert response.status_code == 200
        body = response.json()
        assert [f["key"] for f in body["funds"]] == [f.key for f in catalog.default_catalog()]

    def test_response_matches_the_fund_ref_shape(self, client: TestClient) -> None:
        body = client.get("/api/institutions/funds").json()
        fund = body["funds"][0]
        assert set(fund) == {"key", "name", "source", "cik", "series_id", "ticker", "principal"}


# ---------------------------------------------------------------------------
# GET /api/institutions/{key}/changes -- 13F end to end (Berkshire)
# ---------------------------------------------------------------------------


class TestChangesEndpointThirteenF:
    def _site(self) -> FakeEdgarSite:
        submissions = _load_json("sec_submissions_brk.json")
        q1 = _load_text("sec_13f_brk_2026q1.xml")  # period 2026-03-31, accession ...-226661
        q2 = _load_text("sec_13f_brk_2026q2.xml")  # period 2026-06-30, accession ...-352200
        return FakeEdgarSite(
            submissions=submissions,
            documents={
                _nodash("0001193125-26-226661"): q1,
                _nodash("0001193125-26-352200"): q2,
            },
        )

    def test_end_to_end_matches_the_known_berkshire_figures(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pinned correctness assertion from the brief: diffing these two real Berkshire
        quarters yields exactly this action breakdown, and Chevron/Bank of America's share-vs-value
        divergence is the entire point of classifying `Action` from shares alone (see
        `app.institutions.deltas`'s module docstring)."""
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        response = client.get("/api/institutions/BRK/changes")

        assert response.status_code == 200
        body = response.json()
        assert body["counts"] == {"new": 0, "exit": 0, "add": 3, "trim": 3, "hold": 3}

        by_cusip = {c["cusip"]: c for c in body["changes"]}

        chevron = by_cusip["166764100"]
        assert chevron["action"] == "hold"
        assert Decimal(chevron["shares_delta"]) == 0
        assert Decimal(chevron["value_delta"]) == Decimal("-3471222716")

        bac = by_cusip["060505104"]
        assert bac["action"] == "trim"
        assert Decimal(bac["shares_delta"]) == Decimal("-30230150")
        assert Decimal(bac["value_delta"]) == Decimal("2504612931")

    def test_total_values_and_periods_match_the_fixtures(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        body = client.get("/api/institutions/BRK/changes").json()

        assert body["from_period"] == "2026-03-31"
        assert body["to_period"] == "2026-06-30"
        assert body["from_accession"] == "0001193125-26-226661"
        assert body["to_accession"] == "0001193125-26-352200"
        assert Decimal(body["total_value_before"]) == Decimal("171470670847")
        assert Decimal(body["total_value_after"]) == Decimal("206315311212")

    def test_money_crosses_the_wire_as_decimal_strings_never_floats(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        body = client.get("/api/institutions/BRK/changes").json()

        assert isinstance(body["total_value_before"], str)
        assert isinstance(body["total_value_after"], str)
        for change in body["changes"]:
            assert isinstance(change["value_before"], str)
            assert isinstance(change["value_after"], str)
            assert isinstance(change["value_delta"], str)
            assert isinstance(change["shares_before"], str)
            assert isinstance(change["shares_after"], str)
            assert isinstance(change["shares_delta"], str)
        raw = client.get("/api/institutions/BRK/changes").text
        assert "NaN" not in raw and "Infinity" not in raw

    def test_ticker_is_resolved_from_the_users_ledger_when_the_cusip_is_owned(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        """Chevron's CUSIP is added to the ledger as `"CVX"`; Bank of America's is not. The response
        must resolve the first and leave the second `None` -- a CUSIP outside the user's ledger has
        no ticker to give, per `app.institutions.catalog.ledger_cusip_tickers`'s docstring."""
        with ledger.connect(settings.ledger_path) as conn:
            ledger.migrate(conn)
            ledger.upsert_instrument(
                conn,
                Instrument(instrument_id="cvx-1", primary_symbol="CVX", cusip="166764100"),
            )

        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        body = client.get("/api/institutions/BRK/changes").json()
        by_cusip = {c["cusip"]: c for c in body["changes"]}

        assert by_cusip["166764100"]["ticker"] == "CVX"
        assert by_cusip["060505104"]["ticker"] is None


# ---------------------------------------------------------------------------
# GET /api/institutions/{key}/changes -- NPORT end to end (IVV), and the period-vs-filing-date claim
# ---------------------------------------------------------------------------


class TestChangesEndpointNport:
    def _site(self) -> FakeEdgarSite:
        atom = _load_text("sec_browse_atom_ivv.xml")
        older_period = _load_text("sec_nport_ivv_2025-09-30.xml")  # filed 2026-07-13 (later!)
        newer_period = _load_text("sec_nport_ivv_2026-03-31.xml")  # filed 2026-05-28 (earlier!)
        return FakeEdgarSite(
            atom=atom,
            documents={
                _nodash("0002071691-26-015790"): older_period,
                _nodash("0002071691-26-012459"): newer_period,
            },
            # `load_delta`'s default candidate window (see `_CANDIDATE_SLACK`) asks for more than
            # two raw filings -- the real IVV atom feed has ten -- so every candidate beyond the two
            # above needs *some* parseable document. This one reports a period far older than
            # either fixture above so it can never win a place in the top two by period, regardless
            # of which of the four extra accessions it gets served for.
            default_document=_EMPTY_NPORT_TEMPLATE.format(period="1990-01-01"),
        )

    def test_pairs_by_period_not_by_filing_date(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real out-of-order iShares dates this package's docstrings cite: accession
        ...-015790 was filed 2026-07-13 (later) but reports the period ending 2025-09-30 (older);
        accession ...-012459 was filed 2026-05-28 (earlier) but reports 2026-03-31 (newer). A
        service that paired by filing date would report this delta running backwards -- `from`
        newer than `to`."""
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        response = client.get("/api/institutions/IVV/changes")

        assert response.status_code == 200
        body = response.json()
        assert body["from_period"] == "2025-09-30"
        assert body["to_period"] == "2026-03-31"
        assert body["from_accession"] == "0002071691-26-015790"
        assert body["to_accession"] == "0002071691-26-012459"
        assert Decimal(body["total_value_before"]) == Decimal("14274297832.54")
        assert Decimal(body["total_value_after"]) == Decimal("13121748826.92")


# ---------------------------------------------------------------------------
# GET /api/institutions/{key}/holdings
# ---------------------------------------------------------------------------


class TestHoldingsEndpoint:
    def _site(self) -> FakeEdgarSite:
        submissions = _load_json("sec_submissions_brk.json")
        q1 = _load_text("sec_13f_brk_2026q1.xml")
        q2 = _load_text("sec_13f_brk_2026q2.xml")
        return FakeEdgarSite(
            submissions=submissions,
            documents={
                _nodash("0001193125-26-226661"): q1,
                _nodash("0001193125-26-352200"): q2,
            },
        )

    def test_no_period_returns_the_most_recently_disclosed_one(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        body = client.get("/api/institutions/BRK/holdings").json()

        assert body["period"] == "2026-06-30"
        assert body["accession"] == "0001193125-26-352200"
        assert Decimal(body["total_value"]) == Decimal("206315311212")

    def test_explicit_period_returns_that_periods_snapshot(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        body = client.get("/api/institutions/BRK/holdings?period=2026-03-31").json()

        assert body["period"] == "2026-03-31"
        assert body["accession"] == "0001193125-26-226661"
        assert Decimal(body["total_value"]) == Decimal("171470670847")

    def test_period_outside_the_fetched_window_is_404_not_an_empty_snapshot(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        response = client.get("/api/institutions/BRK/holdings?period=1999-01-01")

        assert response.status_code == 404
        assert "1999-01-01" in response.json()["detail"]

    def test_response_matches_the_snapshot_shape(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        body = client.get("/api/institutions/BRK/holdings").json()

        assert set(body) == {
            "fund",
            "period",
            "filed",
            "accession",
            "total_value",
            "holdings",
            "value_units_rescaled",
        }
        holding = body["holdings"][0]
        assert set(holding) == {"cusip", "issuer", "value", "shares", "weight", "ticker"}


# ---------------------------------------------------------------------------
# `as_of` -- the session-replay lookahead boundary (UAT runs 9 and 11)
# ---------------------------------------------------------------------------


class TestAsOfBound:
    """`as_of` bounds candidate filings to ones whose *filing date* -- never their period -- is on
    or before it. The real Berkshire Q2-2026 13F (`sec_13f_brk_2026q2.xml`) is the calibrating case:
    it reports the quarter ending 2026-06-30 but was not filed until 2026-08-14, so a caller
    replaying 2026-08-13 must not be able to see it, while a caller replaying 2026-08-14 -- the exact
    filing date -- must."""

    def _site(self) -> FakeEdgarSite:
        submissions = _load_json("sec_submissions_brk.json")
        q1 = _load_text("sec_13f_brk_2026q1.xml")
        q2 = _load_text("sec_13f_brk_2026q2.xml")
        return FakeEdgarSite(
            submissions=submissions,
            documents={
                _nodash("0001193125-26-226661"): q1,
                _nodash("0001193125-26-352200"): q2,
            },
        )

    def test_as_of_the_day_before_the_filing_date_excludes_it(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Q2 filing was filed 2026-08-14 -- `as_of=2026-08-13` must fall back to the prior
        quarter, not the period it reports on."""
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        body = client.get("/api/institutions/BRK/holdings?as_of=2026-08-13").json()

        assert body["period"] == "2026-03-31"
        assert body["accession"] == "0001193125-26-226661"
        assert Decimal(body["total_value"]) == Decimal("171470670847")

    def test_as_of_the_exact_filing_date_includes_it(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The other side of the same boundary: `as_of=2026-08-14`, the exact date the Q2 filing
        became public, must include it -- an off-by-one here is exactly the bug this feature exists
        to prevent."""
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        body = client.get("/api/institutions/BRK/holdings?as_of=2026-08-14").json()

        assert body["period"] == "2026-06-30"
        assert body["accession"] == "0001193125-26-352200"
        assert Decimal(body["total_value"]) == Decimal("206315311212")

    def test_omitting_as_of_matches_the_existing_unbounded_expectations(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same assertions as `TestHoldingsEndpoint.test_no_period_returns_the_most_recently_
        disclosed_one` -- this is an addition, not a change, so the unbounded path must still answer
        exactly as it always has."""
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        body = client.get("/api/institutions/BRK/holdings").json()

        assert body["period"] == "2026-06-30"
        assert body["accession"] == "0001193125-26-352200"
        assert Decimal(body["total_value"]) == Decimal("206315311212")

    def test_bound_leaving_fewer_than_two_periods_is_409_naming_the_bound(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """BRK's real submissions history has its earliest filing on 2025-02-14
        (`0000950123-25-002701`, period 2024-12-31). `as_of=2025-02-14` keeps only that one filing --
        one usable period, not enough for a delta -- and the 409's message must name the bound, not
        just the count, so a reader does not conclude the filer has only ever filed once."""
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        response = client.get("/api/institutions/BRK/changes?as_of=2025-02-14")

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "BRK" in detail
        assert "1" in detail
        assert "2025-02-14" in detail

    def test_bound_predating_every_filing_is_a_clear_error_not_an_empty_success(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A date before BRK's earliest filing must not read as "no such fund" or silently succeed
        with nothing -- it is `PeriodNotFound`, worded to say the bound is why."""
        site = self._site()
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        response = client.get("/api/institutions/BRK/holdings?as_of=1990-01-01")

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "1990-01-01" in detail
        assert "BRK" in detail

    def test_unparseable_as_of_is_422(self, client: TestClient) -> None:
        """FastAPI must reject a malformed `as_of` itself, before this ever reaches `service` and
        risks a network call -- confirmed here rather than assumed."""
        response = client.get("/api/institutions/BRK/holdings?as_of=not-a-date")

        assert response.status_code == 422

    def test_widening_the_candidate_window_lets_a_bound_reach_far_enough_back(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/changes`'s auto-computed candidate window (`limit=2 + _CANDIDATE_SLACK == 6`) is sized
        for the *unfiltered* case. This fund has ten filings; the five most recent all postdate
        `as_of=2025-05-15`, so an unwidened window would fetch only its six most recent filings,
        the `as_of` filter would discard five of those six, and only one usable period would survive
        -- a wrong 409 for a fund that plainly has two periods on record before that date. Without
        the widening in `load_snapshots` (see `_AS_OF_CANDIDATE_MULTIPLIER`), this test fails with a
        409; with it, the window reaches all ten filings and the request succeeds."""
        rows = [
            ("13F-HR", "2026-08-14", "2026-06-30", "0000000000-26-000010"),
            ("13F-HR", "2026-05-15", "2026-03-31", "0000000000-26-000009"),
            ("13F-HR", "2026-02-17", "2025-12-31", "0000000000-26-000008"),
            ("13F-HR", "2025-11-14", "2025-09-30", "0000000000-26-000007"),
            ("13F-HR", "2025-08-14", "2025-06-30", "0000000000-26-000006"),
            ("13F-HR", "2025-05-15", "2025-03-31", "0000000000-26-000005"),
            ("13F-HR", "2025-02-14", "2024-12-31", "0000000000-26-000004"),
            ("13F-HR", "2024-11-14", "2024-09-30", "0000000000-26-000003"),
            ("13F-HR", "2024-08-14", "2024-06-30", "0000000000-26-000002"),
            ("13F-HR", "2024-05-15", "2024-03-31", "0000000000-26-000001"),
        ]
        submissions = _submissions(rows)
        site = FakeEdgarSite(submissions=submissions)  # default filler document throughout
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        response = client.get("/api/institutions/BRK/changes?as_of=2025-05-15")

        assert response.status_code == 200
        body = response.json()
        assert body["from_period"] == "2024-12-31"
        assert body["to_period"] == "2025-03-31"
        assert body["from_accession"] == "0000000000-26-000004"
        assert body["to_accession"] == "0000000000-26-000005"

    def test_explicit_candidate_limit_is_never_widened(self, settings: Settings) -> None:
        """A caller that pins `candidate_limit` explicitly is asking for that exact window, bound or
        not -- widening it behind their back would defeat the point of pinning it (see
        `test_a_later_filed_amendment_supersedes_the_original_for_the_same_period`, which relies on
        an exact, unpadded window). Calling `load_snapshots` directly so the candidate window itself,
        not just the final answer, is what is under test: `candidate_limit=1` asks EDGAR for only
        BRK's single most recent filing (period 2026-06-30, filed 2026-08-14), and `as_of=2026-08-14`
        does not filter it out -- so exactly one snapshot must come back. If this module widened an
        explicit `candidate_limit` the way it widens the auto-computed default, three filings would
        be fetched instead of one and this would return more than one snapshot."""
        fund = _fund("BRK")
        submissions = _load_json("sec_submissions_brk.json")
        site = FakeEdgarSite(submissions=submissions)

        snapshots = institutions_service.load_snapshots(
            fund,
            client=site.client(),
            settings=settings,
            limit=2,
            candidate_limit=1,
            as_of=dt.date(2026, 8, 14),
        )

        assert [snap.period for snap in snapshots] == [dt.date(2026, 6, 30)]


# ---------------------------------------------------------------------------
# Amendment resolution: a later-filed amendment must supersede the filing it corrects
# ---------------------------------------------------------------------------


class TestAmendmentResolution:
    def test_a_later_filed_amendment_supersedes_the_original_for_the_same_period(
        self, settings: Settings
    ) -> None:
        """BRK's real submissions history (`sec_submissions_brk.json`) contains exactly this case:
        accession `0000950123-25-008361` (a `13F-HR/A`, filed 2025-08-14) and
        `0000950123-25-005701` (a plain `13F-HR`, filed 2025-05-15) both report period 2025-03-31.
        `load_snapshots` must resolve that collision to the amendment -- the later-filed one -- the
        same rule `app.institutions.deltas.latest_pair` documents for the same reason: a
        restatement supersedes the filing it corrects. Called directly against `service` (rather
        than through an HTTP endpoint) so the assertion is exactly this claim and nothing else --
        the holdings content of every fetched document is an unexamined filler here, only the
        accession selected for the contested period is under test."""
        fund = _fund("BRK")
        submissions = _load_json("sec_submissions_brk.json")
        site = FakeEdgarSite(submissions=submissions)

        snapshots = institutions_service.load_snapshots(
            fund, client=site.client(), settings=settings, limit=8, candidate_limit=8
        )

        by_period = {snap.period: snap for snap in snapshots}
        assert dt.date(2025, 3, 31) in by_period
        assert by_period[dt.date(2025, 3, 31)].accession == "0000950123-25-008361"
        assert by_period[dt.date(2025, 3, 31)].filed == dt.date(2025, 8, 14)


# ---------------------------------------------------------------------------
# The one-filing case: 409, never an empty delta
# ---------------------------------------------------------------------------


class TestInsufficientHistory:
    def test_a_single_filing_on_record_is_409_not_an_empty_delta(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        submissions = _submissions([("13F-HR", "2026-08-14", "2026-06-30", "0000000000-26-000001")])
        site = FakeEdgarSite(submissions=submissions)  # one filing; default filler document
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        response = client.get("/api/institutions/BRK/changes")

        assert response.status_code == 409
        detail = response.json()["detail"]
        assert "BRK" in detail
        assert "1" in detail  # names the actual count, not a generic message

    def test_zero_filings_on_record_is_404_for_holdings(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/holdings` with no filings at all is a different, sharper case than `/changes`'s 409:
        there is no "most recent period" to name, so this is `PeriodNotFound`, not
        `InsufficientHistory`."""
        submissions = _submissions([])
        site = FakeEdgarSite(submissions=submissions)
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        response = client.get("/api/institutions/BRK/holdings")

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def test_unknown_key_is_404_and_lists_the_valid_keys(self, client: TestClient) -> None:
        response = client.get("/api/institutions/NOT-A-REAL-FUND/holdings")

        assert response.status_code == 404
        detail = response.json()["detail"]
        assert "NOT-A-REAL-FUND" in detail
        for fund in catalog.default_catalog():
            assert fund.key in detail

    def test_unknown_key_404_applies_to_changes_too(self, client: TestClient) -> None:
        response = client.get("/api/institutions/NOT-A-REAL-FUND/changes")
        assert response.status_code == 404

    def test_rate_limited_is_429_and_forwards_retry_after(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            institutions_service,
            "build_client",
            lambda cfg: _failing_client(429, headers={"Retry-After": "45"}),
        )

        response = client.get("/api/institutions/BRK/holdings")

        assert response.status_code == 429
        # `RateLimited.retry_after` is a float (`EdgarClient._get` parses the header via
        # `float(retry_after)`), so the forwarded header is `"45.0"`, not `"45"`.
        assert response.headers.get("retry-after") == "45.0"

    def test_rate_limited_without_retry_after_still_maps_to_429(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: _failing_client(429))

        response = client.get("/api/institutions/BRK/holdings")

        assert response.status_code == 429

    def test_upstream_5xx_is_503_provider_unavailable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: _failing_client(500))

        response = client.get("/api/institutions/BRK/holdings")

        assert response.status_code == 503

    def test_timeout_is_503_provider_unavailable(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: _timeout_client())

        response = client.get("/api/institutions/BRK/holdings")

        assert response.status_code == 503

    def test_unexpected_4xx_is_502_provider_response_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A non-429 4xx from EDGAR (`EdgarClient._get`'s mapping) is `ProviderResponseError`,
        which this router must map to 502 -- the upstream sent something unexpected, not something
        this endpoint's caller got wrong."""
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: _failing_client(403))

        response = client.get("/api/institutions/BRK/holdings")

        assert response.status_code == 502

    def test_malformed_filing_document_is_502_filing_parse_error(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SEC served a 200 with a body this application's parser cannot read -- an upstream
        problem (a schema change, a corrupted response), not a bad request."""
        submissions = _submissions(
            [
                ("13F-HR", "2026-08-14", "2026-06-30", "0000000000-26-000001"),
                ("13F-HR", "2026-05-15", "2026-03-31", "0000000000-26-000002"),
            ]
        )
        site = FakeEdgarSite(submissions=submissions, default_document="<not>even well-formed xml")
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        response = client.get("/api/institutions/BRK/holdings")

        assert response.status_code == 502

    def test_no_nan_or_infinity_token_reaches_the_wire_on_a_working_response(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        submissions = _load_json("sec_submissions_brk.json")
        q1 = _load_text("sec_13f_brk_2026q1.xml")
        q2 = _load_text("sec_13f_brk_2026q2.xml")
        site = FakeEdgarSite(
            submissions=submissions,
            documents={
                _nodash("0001193125-26-226661"): q1,
                _nodash("0001193125-26-352200"): q2,
            },
        )
        monkeypatch.setattr(institutions_service, "build_client", lambda cfg: site.client())

        raw = client.get("/api/institutions/BRK/changes").text

        assert "NaN" not in raw and "Infinity" not in raw
        json.loads(raw)
