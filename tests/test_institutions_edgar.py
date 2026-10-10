"""Tests for the read-only SEC EDGAR client.

Every test drives an ``httpx.MockTransport`` from either a real captured fixture in
``tests/fixtures/institutions/`` or a small synthetic payload built inline for shapes no fixture
covers (the ``index.json`` directory listing, and the ``accession-nunber`` misspelling SEC has
shipped in the wild but that the captured Atom fixture happens not to exhibit). No test in this
file makes a network call.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.institutions import edgar as edgar_module
from app.institutions.edgar import EdgarClient, FilingRef
from app.institutions.models import Source
from app.market.providers.base import (
    ProviderResponseError,
    ProviderUnavailable,
    RateLimited,
)

FIXTURES = Path(__file__).parent / "fixtures" / "institutions"


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this file runs with `EdgarClient._get`'s retry backoff at zero.

    `_get` (see its docstring) now retries a timeout/transport-error/5xx once before raising --
    real production behaviour, worth ~0.3s of real delay to smooth over a genuine SEC blip. That
    same 0.3s is pure waste in a test that drives an in-memory `httpx.MockTransport`, which fails
    or succeeds instantly: the tests in `TestErrorMapping` that always fail would otherwise pay it
    twice (once per attempt) on every run, and `TestRetryOnTransientFailure` below asserts on call
    counts and outcomes, never on timing.
    """
    monkeypatch.setattr(edgar_module, "_RETRY_BACKOFF_SECONDS", 0.0)


def _load_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def _load_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client_returning(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _client_json(
    status_code: int, payload: Any, headers: dict[str, str] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload, headers=headers or {})

    return _client_returning(handler)


def _client_text(
    status_code: int, text: str, headers: dict[str, str] | None = None
) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text=text, headers=headers or {})

    return _client_returning(handler)


# ---------------------------------------------------------------------------
# resolve_fund: ticker -> (cik10, series_id)
# ---------------------------------------------------------------------------


class TestResolveFund:
    def _client(self) -> httpx.Client:
        tickers = _load_json("sec_company_tickers_mf.json")

        def handler(request: httpx.Request) -> httpx.Response:
            user_agent = request.headers.get("user-agent", "")
            assert "@" in user_agent, f"SEC requires a contactable User-Agent, got {user_agent!r}"
            assert "company_tickers_mf.json" in str(request.url)
            return httpx.Response(200, json=tickers)

        return _client_returning(handler)

    def test_known_ticker_resolves_cik_and_series(self) -> None:
        client = EdgarClient(client=self._client())

        result = client.resolve_fund("IVV")

        assert result == ("0001100663", "S000004310")

    def test_cik_is_zero_padded_from_the_json_int(self) -> None:
        """`36405` in the fixture (a bare JSON int) must come back as the 10-digit string form
        every other EDGAR endpoint expects, not `"36405"` or the int itself."""
        client = EdgarClient(client=self._client())

        result = client.resolve_fund("VOO")

        assert result is not None
        cik10, _series_id = result
        assert cik10 == "0000036405"
        assert len(cik10) == 10

    def test_ticker_absent_from_map_returns_none_not_raises(self) -> None:
        """SPY is a unit investment trust and is deliberately absent from this endpoint -- a real,
        actively-tracked ETF that this lookup simply has nothing to say about."""
        client = EdgarClient(client=self._client())

        assert client.resolve_fund("SPY") is None

    def test_ticker_map_is_cached_after_the_first_call(self) -> None:
        calls: list[str] = []
        tickers = _load_json("sec_company_tickers_mf.json")

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200, json=tickers)

        client = EdgarClient(client=_client_returning(handler))

        client.resolve_fund("IVV")
        client.resolve_fund("QQQ")

        assert len(calls) == 1

    def test_lookup_is_case_insensitive(self) -> None:
        client = EdgarClient(client=self._client())

        assert client.resolve_fund("ivv") == ("0001100663", "S000004310")


# ---------------------------------------------------------------------------
# list_filings: submissions API, filtered to a form
# ---------------------------------------------------------------------------


class TestListFilings:
    def _client(self) -> httpx.Client:
        submissions = _load_json("sec_submissions_brk.json")

        def handler(request: httpx.Request) -> httpx.Response:
            assert "CIK0001067983.json" in str(request.url)
            return httpx.Response(200, json=submissions)

        return _client_returning(handler)

    def test_13f_hr_filings_include_amendments_by_default(self) -> None:
        """The fixture has 7 `13F-HR` rows and 1 `13F-HR/A` -- all 8 rows in total. This module
        includes the amendment rather than hiding it: an amendment supersedes the filing it
        corrects, and the caller -- not this module -- decides which view it wants."""
        client = EdgarClient(client=self._client())

        results = client.list_filings("0001067983", "13F-HR", limit=8)

        assert len(results) == 8
        forms = {r.form for r in results}
        assert forms == {"13F-HR", "13F-HR/A"}

    def test_results_are_filing_ref_with_expected_first_row(self) -> None:
        client = EdgarClient(client=self._client())

        results = client.list_filings("0001067983", "13F-HR", limit=8)

        assert results[0] == FilingRef(
            accession="0001193125-26-352200",
            filing_date=dt.date(2026, 8, 14),
            form="13F-HR",
            report_date=dt.date(2026, 6, 30),
        )

    def test_report_date_is_populated_from_the_parallel_reportdate_array(self) -> None:
        """The whole point of this field: a 13F filed 2026-08-14 reports the quarter ending
        2026-06-30, and `list_filings` must surface that period directly rather than leaving the
        caller to guess it from `filing_date` (the offset between the two is not fixed)."""
        client = EdgarClient(client=self._client())

        results = client.list_filings("0001067983", "13F-HR", limit=8)

        report_dates = [r.report_date for r in results]
        assert report_dates == [
            dt.date(2026, 6, 30),
            dt.date(2026, 3, 31),
            dt.date(2025, 12, 31),
            dt.date(2025, 9, 30),
            dt.date(2025, 3, 31),
            dt.date(2025, 6, 30),
            dt.date(2025, 3, 31),
            dt.date(2024, 12, 31),
        ]

    def test_limit_truncates(self) -> None:
        client = EdgarClient(client=self._client())

        results = client.list_filings("0001067983", "13F-HR", limit=3)

        assert len(results) == 3

    def test_unrelated_form_is_filtered_out(self) -> None:
        client = EdgarClient(client=self._client())

        results = client.list_filings("0001067983", "NPORT-P", limit=8)

        assert results == []

    def test_preserves_edgar_order_rather_than_resorting(self) -> None:
        """Filing order is not period order (see the module docstring): this method must not
        re-sort by any date, only pass through what EDGAR returned."""
        client = EdgarClient(client=self._client())

        results = client.list_filings("0001067983", "13F-HR", limit=8)

        dates = [r.filing_date for r in results]
        assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# list_series_filings: browse-edgar Atom feed
# ---------------------------------------------------------------------------


class TestListSeriesFilings:
    def _client(self) -> httpx.Client:
        atom = _load_text("sec_browse_atom_ivv.xml")

        def handler(request: httpx.Request) -> httpx.Response:
            assert "CIK=S000004310" in str(request.url)
            assert "output=atom" in str(request.url)
            return httpx.Response(200, text=atom)

        return _client_returning(handler)

    def test_parses_real_atom_feed(self) -> None:
        client = EdgarClient(client=self._client())

        results = client.list_series_filings("S000004310", "NPORT-P", limit=10)

        assert results[0] == FilingRef(
            accession="0002071691-26-015790",
            filing_date=dt.date(2026, 7, 13),
            form="NPORT-P/A",
        )
        assert results[1] == FilingRef(
            accession="0002071691-26-012459",
            filing_date=dt.date(2026, 5, 28),
            form="NPORT-P",
        )

    def test_report_date_is_always_none_the_atom_feed_carries_no_such_field(self) -> None:
        """See `FilingRef.report_date`'s docstring: the browse-edgar Atom feed has no
        `reportDate`-equivalent element, unlike the submissions JSON `list_filings` reads -- an
        NPORT-P's period comes from `repPdDate` inside the document itself instead."""
        client = EdgarClient(client=self._client())

        results = client.list_series_filings("S000004310", "NPORT-P", limit=10)

        assert all(r.report_date is None for r in results)

    def test_limit_truncates(self) -> None:
        client = EdgarClient(client=self._client())

        results = client.list_series_filings("S000004310", "NPORT-P", limit=2)

        assert len(results) == 2

    def test_handles_the_accession_nunber_misspelling(self) -> None:
        """SEC's own Atom renderer has shipped this element misspelled as `accession-nunber`
        (missing the second `m`) in production. The captured fixture happens to carry the correct
        spelling, so this test drives a small synthetic feed exhibiting the typo directly, to prove
        the fallback lookup actually works rather than being dead code."""
        atom = """<?xml version="1.0" encoding="ISO-8859-1" ?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <category label="form type" scheme="https://www.sec.gov/" term="NPORT-P" />
            <content type="text/xml">
              <accession-nunber>0001234567-26-000001</accession-nunber>
              <filing-date>2026-01-15</filing-date>
              <filing-type>NPORT-P</filing-type>
            </content>
          </entry>
        </feed>"""
        client = EdgarClient(client=_client_text(200, atom))

        results = client.list_series_filings("S000004310", "NPORT-P", limit=10)

        assert results == [
            FilingRef(
                accession="0001234567-26-000001",
                filing_date=dt.date(2026, 1, 15),
                form="NPORT-P",
            )
        ]

    def test_malformed_xml_raises_provider_response_error_not_a_parse_error(self) -> None:
        client = EdgarClient(client=_client_text(200, "<feed><entry not closed"))

        with pytest.raises(ProviderResponseError):
            client.list_series_filings("S000004310", "NPORT-P", limit=10)


# ---------------------------------------------------------------------------
# holdings_document_url: the index.json walk
# ---------------------------------------------------------------------------


class TestHoldingsDocumentUrl:
    def _index_client(self, items: list[dict[str, str]]) -> httpx.Client:
        payload = {"directory": {"item": items, "name": "/some/dir/"}}

        def handler(request: httpx.Request) -> httpx.Response:
            assert "index.json" in str(request.url)
            return httpx.Response(200, json=payload)

        return _client_returning(handler)

    def test_13f_picks_the_non_primary_doc_xml_file(self) -> None:
        """A 13F's `primary_doc.xml` is the cover page only -- the actual information table is a
        second, arbitrarily-named XML file (a real one: `56757.xml`)."""
        items = [
            {"name": "0000950123-25-008361-index.htm"},
            {"name": "primary_doc.xml"},
            {"name": "56757.xml"},
        ]
        client = EdgarClient(client=self._index_client(items))

        url = client.holdings_document_url("0001067983", "0000950123-25-008361", Source.THIRTEEN_F)

        assert url == (
            "https://www.sec.gov/Archives/edgar/data/1067983/000095012325008361/56757.xml"
        )

    def test_nport_picks_primary_doc_xml(self) -> None:
        """NPORT holdings live directly in `primary_doc.xml`, unlike a 13F -- the same filename
        means something different for each source, which is exactly why the rule branches on
        `Source` rather than always avoiding or always preferring that name."""
        items = [
            {"name": "0002071691-26-012459-index.htm"},
            {"name": "primary_doc.xml"},
        ]
        client = EdgarClient(client=self._index_client(items))

        url = client.holdings_document_url("0001100663", "0002071691-26-012459", Source.NPORT)

        assert url == (
            "https://www.sec.gov/Archives/edgar/data/1100663/000207169126012459/primary_doc.xml"
        )

    def test_cik_leading_zeros_are_stripped_for_the_archive_path(self) -> None:
        items = [{"name": "primary_doc.xml"}]
        client = EdgarClient(client=self._index_client(items))

        url = client.holdings_document_url("0001100663", "0002071691-26-012459", Source.NPORT)

        assert "/data/1100663/" in url
        assert "/data/0001100663/" not in url

    def test_13f_with_no_non_primary_xml_raises_provider_response_error(self) -> None:
        items = [{"name": "primary_doc.xml"}, {"name": "cover-page.htm"}]
        client = EdgarClient(client=self._index_client(items))

        with pytest.raises(ProviderResponseError):
            client.holdings_document_url("0001067983", "0000950123-25-008361", Source.THIRTEEN_F)

    def test_nport_with_no_primary_doc_raises_provider_response_error(self) -> None:
        items = [{"name": "some-other-file.xml"}]
        client = EdgarClient(client=self._index_client(items))

        with pytest.raises(ProviderResponseError):
            client.holdings_document_url("0001100663", "0002071691-26-012459", Source.NPORT)

    def test_malformed_index_json_raises_provider_response_error_not_key_error(self) -> None:
        client = EdgarClient(client=_client_json(200, {"unexpected": "shape"}))

        with pytest.raises(ProviderResponseError):
            client.holdings_document_url("0001100663", "0002071691-26-012459", Source.NPORT)


# ---------------------------------------------------------------------------
# Error mapping shared across every endpoint
# ---------------------------------------------------------------------------


class TestErrorMapping:
    def test_403_raises_provider_response_error(self) -> None:
        client = EdgarClient(client=_client_json(403, {}))

        with pytest.raises(ProviderResponseError):
            client.resolve_fund("IVV")

    def test_429_raises_rate_limited_honouring_retry_after(self) -> None:
        client = EdgarClient(client=_client_json(429, {}, headers={"Retry-After": "45"}))

        with pytest.raises(RateLimited) as excinfo:
            client.resolve_fund("IVV")

        assert excinfo.value.retry_after == 45.0

    def test_429_without_retry_after_header_leaves_it_none(self) -> None:
        client = EdgarClient(client=_client_json(429, {}))

        with pytest.raises(RateLimited) as excinfo:
            client.resolve_fund("IVV")

        assert excinfo.value.retry_after is None

    def test_500_raises_provider_unavailable(self) -> None:
        client = EdgarClient(client=_client_text(500, "internal error"))

        with pytest.raises(ProviderUnavailable):
            client.resolve_fund("IVV")

    def test_timeout_raises_provider_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        client = EdgarClient(client=_client_returning(handler))

        with pytest.raises(ProviderUnavailable):
            client.resolve_fund("IVV")

    def test_transport_error_raises_provider_unavailable(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client = EdgarClient(client=_client_returning(handler))

        with pytest.raises(ProviderUnavailable):
            client.resolve_fund("IVV")

    def test_malformed_json_body_raises_provider_response_error(self) -> None:
        """A 200 with a body that is not valid JSON at all -- e.g. a truncated response -- must not
        surface as a bare `json.JSONDecodeError` two frames from the HTTP call."""
        client = EdgarClient(client=_client_text(200, "{not valid json"))

        with pytest.raises(ProviderResponseError):
            client.resolve_fund("IVV")

    def test_fund_map_missing_expected_fields_raises_provider_response_error_not_key_error(
        self,
    ) -> None:
        client = EdgarClient(client=_client_json(200, {"unexpected": "shape"}))

        with pytest.raises(ProviderResponseError):
            client.resolve_fund("IVV")

    def test_submissions_missing_filings_key_raises_provider_response_error_not_key_error(
        self,
    ) -> None:
        client = EdgarClient(client=_client_json(200, {"cik": "0001067983"}))

        with pytest.raises(ProviderResponseError):
            client.list_filings("0001067983", "13F-HR")


# ---------------------------------------------------------------------------
# Retry on a transient failure -- reproduced live against VTI (see `_get`'s docstring): a
# `list_series_filings` call timed out once and succeeded moments later, and the whole `load_latest`
# failed with no recovery. `_MAX_ATTEMPTS`/`_RETRY_BACKOFF_SECONDS` exist to absorb exactly that.
# ---------------------------------------------------------------------------


class TestRetryOnTransientFailure:
    def _flaky_client(
        self, first: Callable[[httpx.Request], httpx.Response]
    ) -> tuple[httpx.Client, list[int]]:
        """A client whose first call raises/answers via ``first`` and every later call succeeds
        with a plain 200. ``calls`` records how many requests were actually made, by reference."""
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return first(request)
            return httpx.Response(200, json=_load_json("sec_company_tickers_mf.json"))

        return _client_returning(handler), calls

    def test_a_timeout_then_success_recovers_on_retry(self) -> None:
        def first(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out", request=request)

        client, calls = self._flaky_client(first)
        edgar_client = EdgarClient(client=client)

        result = edgar_client.resolve_fund("IVV")

        assert result == ("0001100663", "S000004310")
        assert len(calls) == 2

    def test_a_transport_error_then_success_recovers_on_retry(self) -> None:
        def first(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        client, calls = self._flaky_client(first)
        edgar_client = EdgarClient(client=client)

        result = edgar_client.resolve_fund("IVV")

        assert result == ("0001100663", "S000004310")
        assert len(calls) == 2

    def test_a_5xx_then_success_recovers_on_retry(self) -> None:
        def first(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="upstream hiccup")

        client, calls = self._flaky_client(first)
        edgar_client = EdgarClient(client=client)

        result = edgar_client.resolve_fund("IVV")

        assert result == ("0001100663", "S000004310")
        assert len(calls) == 2

    def test_a_persistent_timeout_still_raises_after_the_retry_budget(self) -> None:
        """Exhausting the budget must still raise -- a real outage does not become healthy no
        matter how the request is worded, and this must not hang or retry forever."""
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            raise httpx.TimeoutException("timed out", request=request)

        client = EdgarClient(client=_client_returning(handler))

        with pytest.raises(ProviderUnavailable):
            client.resolve_fund("IVV")

        assert len(calls) == edgar_module._MAX_ATTEMPTS

    def test_a_persistent_5xx_still_raises_after_the_retry_budget(self) -> None:
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(500, text="internal error")

        client = EdgarClient(client=_client_returning(handler))

        with pytest.raises(ProviderUnavailable):
            client.resolve_fund("IVV")

        assert len(calls) == edgar_module._MAX_ATTEMPTS

    def test_429_is_never_retried(self) -> None:
        """SEC is explicitly asking for less traffic -- asking again immediately is the wrong
        response, not a recovery attempt. Exactly one request must be made."""
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(429, json={}, headers={"Retry-After": "45"})

        client = EdgarClient(client=_client_returning(handler))

        with pytest.raises(RateLimited):
            client.resolve_fund("IVV")

        assert len(calls) == 1

    def test_non_429_4xx_is_never_retried(self) -> None:
        """A malformed request or a changed endpoint shape does not become well-formed by asking
        again -- only the transient failure modes in `_get`'s docstring are retried."""
        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            return httpx.Response(403, json={})

        client = EdgarClient(client=_client_returning(handler))

        with pytest.raises(ProviderResponseError):
            client.resolve_fund("IVV")

        assert len(calls) == 1
