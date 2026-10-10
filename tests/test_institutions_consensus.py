"""Tests for `app.institutions.consensus` (the cross-institution ranking) and
`app.api.institutions_consensus` (its router).

Offline and deterministic throughout: every test injects `PortfolioDelta` objects built directly
in-process and monkeypatches `app.institutions.consensus.service.load_delta` so no test ever
constructs a real `EdgarClient` request or touches the network -- see
`app.institutions.consensus.build_consensus`'s docstring for the `client`/`funds`/`now` parameters
that make this injection possible.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import institutions_consensus as consensus_api
from app.config import Settings
from app.institutions import consensus
from app.institutions.models import Action, FundRef, HoldingChange, PortfolioDelta, Source

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _fund(
    key: str,
    *,
    source: Source = Source.THIRTEEN_F,
    name: str | None = None,
    principal: str | None = None,
) -> FundRef:
    return FundRef(
        key=key,
        name=name or f"{key} Test Fund",
        source=source,
        cik="0000000000",
        principal=principal,
    )


def _change(
    cusip: str,
    action: Action,
    *,
    issuer: str = "Test Co",
    ticker: str | None = None,
    weight_delta: Decimal = Decimal("0.01"),
    shares_delta: Decimal = Decimal("1000"),
) -> HoldingChange:
    """A `HoldingChange` with `action` set directly -- `app.institutions.deltas._classify` is not
    involved, so the share counts below are internally consistent but not re-derived into `action`;
    tests pin whichever `Action` they need to exercise.
    """
    shares_before = Decimal("10000")
    shares_after = shares_before + shares_delta
    weight_before = Decimal("0.05")
    weight_after = weight_before + weight_delta
    value_before = Decimal("100000")
    value_after = value_before + Decimal("1000")
    return HoldingChange(
        cusip=cusip,
        issuer=issuer,
        ticker=ticker,
        action=action,
        shares_before=shares_before,
        shares_after=shares_after,
        shares_delta=shares_delta,
        shares_pct_change=None,
        value_before=value_before,
        value_after=value_after,
        value_delta=value_after - value_before,
        weight_before=weight_before,
        weight_after=weight_after,
        weight_delta=weight_delta,
    )


def _delta(
    fund: FundRef,
    changes: list[HoldingChange],
    *,
    from_period: dt.date = dt.date(2026, 3, 31),
    to_period: dt.date = dt.date(2026, 6, 30),
) -> PortfolioDelta:
    return PortfolioDelta(
        fund=fund,
        from_period=from_period,
        to_period=to_period,
        from_accession="0000000000-26-000001",
        to_accession="0000000000-26-000002",
        total_value_before=Decimal("1000000"),
        total_value_after=Decimal("1100000"),
        changes=tuple(changes),
    )


def _settings(tmp_path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache")


def _fake_load_delta(deltas_by_key: dict[str, PortfolioDelta], failures: dict[str, Exception] | None = None):
    failures = failures or {}

    def _load_delta(fund, *, client, settings, as_of=None, candidate_limit=None):
        if fund.key in failures:
            raise failures[fund.key]
        return deltas_by_key[fund.key]

    return _load_delta


# ---------------------------------------------------------------------------
# Core ranking behaviour
# ---------------------------------------------------------------------------


def test_more_buyers_ranks_above_fewer_even_with_a_seller(tmp_path, monkeypatch):
    """A CUSIP bought by 3 and sold by 1 must rank above one bought by only 2 -- vote count is the
    primary key, not net_funds and not weight."""
    fund_x = _fund("FUNDX")
    fund_y = _fund("FUNDY")
    fund_z = _fund("FUNDZ")
    fund_w = _fund("FUNDW")
    fund_p = _fund("FUNDP")
    fund_q = _fund("FUNDQ")

    deltas = {
        "FUNDX": _delta(fund_x, [_change("AAAAAAAAA", Action.ADD, weight_delta=Decimal("0.01"))]),
        "FUNDY": _delta(fund_y, [_change("AAAAAAAAA", Action.NEW, weight_delta=Decimal("0.02"))]),
        "FUNDZ": _delta(fund_z, [_change("AAAAAAAAA", Action.ADD, weight_delta=Decimal("0.03"))]),
        "FUNDW": _delta(fund_w, [_change("AAAAAAAAA", Action.TRIM, weight_delta=Decimal("-0.01"))]),
        "FUNDP": _delta(fund_p, [_change("BBBBBBBBB", Action.ADD, weight_delta=Decimal("0.05"))]),
        "FUNDQ": _delta(fund_q, [_change("BBBBBBBBB", Action.NEW, weight_delta=Decimal("0.05"))]),
    }
    monkeypatch.setattr(consensus.service, "load_delta", _fake_load_delta(deltas))

    result = consensus.build_consensus(
        settings=_settings(tmp_path),
        funds=(fund_x, fund_y, fund_z, fund_w, fund_p, fund_q),
        client=object(),
    )

    assert [row.cusip for row in result.buys] == ["AAAAAAAAA", "BBBBBBBBB"]
    top = result.buys[0]
    assert top.buyer_count == 3
    assert top.seller_count == 1
    assert top.net_funds == 2

    # The seller also shows up ranked in `sells`, on its own.
    assert [row.cusip for row in result.sells] == ["AAAAAAAAA"]
    assert result.sells[0].seller_count == 1
    assert result.sells[0].buyer_count == 3


def test_hold_never_appears_on_either_side(tmp_path, monkeypatch):
    fund = _fund("HOLDFUND")
    deltas = {
        "HOLDFUND": _delta(
            fund,
            [
                _change("CCCCCCCCC", Action.HOLD, weight_delta=Decimal("0")),
                _change("DDDDDDDDD", Action.ADD, weight_delta=Decimal("0.02")),
            ],
        )
    }
    monkeypatch.setattr(consensus.service, "load_delta", _fake_load_delta(deltas))

    result = consensus.build_consensus(settings=_settings(tmp_path), funds=(fund,), client=object())

    all_cusips = {row.cusip for row in result.buys} | {row.cusip for row in result.sells}
    assert "CCCCCCCCC" not in all_cusips
    assert "DDDDDDDDD" in {row.cusip for row in result.buys}


def test_failed_fund_lands_in_unchecked_and_is_excluded_from_buyer_count(tmp_path, monkeypatch):
    good = _fund("GOODFUND")
    bad = _fund("BADFUND")
    deltas = {
        "GOODFUND": _delta(good, [_change("EEEEEEEEE", Action.ADD, weight_delta=Decimal("0.01"))]),
    }
    failures = {"BADFUND": TimeoutError("EDGAR did not respond")}
    monkeypatch.setattr(consensus.service, "load_delta", _fake_load_delta(deltas, failures))

    result = consensus.build_consensus(
        settings=_settings(tmp_path), funds=(good, bad), client=object()
    )

    assert result.checked == ["GOODFUND"]
    assert len(result.unchecked) == 1
    assert result.unchecked[0].key == "BADFUND"
    assert "TimeoutError" in result.unchecked[0].reason
    assert result.buys[0].buyer_count == 1  # not 2 -- BADFUND never contributed a vote


# ---------------------------------------------------------------------------
# The ARK double-count rule
# ---------------------------------------------------------------------------


def test_ark_double_count_rule_fires_on_same_side(tmp_path, monkeypatch):
    arkinvest = _fund("ARKINVEST", source=Source.THIRTEEN_F, principal="Cathie Wood")
    arkk = _fund("ARKK", source=Source.NPORT)
    other = _fund("OTHERFUND")

    deltas = {
        "ARKINVEST": _delta(
            arkinvest, [_change("FFFFFFFFF", Action.ADD, weight_delta=Decimal("0.02"))]
        ),
        "ARKK": _delta(arkk, [_change("FFFFFFFFF", Action.ADD, weight_delta=Decimal("0.05"))]),
        "OTHERFUND": _delta(
            other, [_change("FFFFFFFFF", Action.NEW, weight_delta=Decimal("0.03"))]
        ),
    }
    monkeypatch.setattr(consensus.service, "load_delta", _fake_load_delta(deltas))

    result = consensus.build_consensus(
        settings=_settings(tmp_path), funds=(arkinvest, arkk, other), client=object()
    )

    row = next(r for r in result.buys if r.cusip == "FFFFFFFFF")
    # Both ARK legs are checked, but only one vote is counted for the pair.
    assert "ARKINVEST" in result.checked and "ARKK" in result.checked
    assert row.buyer_count == 2  # ARKINVEST + OTHERFUND, not ARKK too
    mover_keys = {m.key for m in row.movers}
    assert mover_keys == {"ARKINVEST", "OTHERFUND"}
    assert "ARKK" not in mover_keys


def test_ark_pair_not_suppressed_on_opposite_sides(tmp_path, monkeypatch):
    """If the manager and the ETF disagree on direction for the same CUSIP, that is real
    information and neither leg is dropped."""
    arkinvest = _fund("ARKINVEST", source=Source.THIRTEEN_F)
    arkk = _fund("ARKK", source=Source.NPORT)

    deltas = {
        "ARKINVEST": _delta(
            arkinvest, [_change("GGGGGGGGG", Action.ADD, weight_delta=Decimal("0.02"))]
        ),
        "ARKK": _delta(arkk, [_change("GGGGGGGGG", Action.TRIM, weight_delta=Decimal("-0.01"))]),
    }
    monkeypatch.setattr(consensus.service, "load_delta", _fake_load_delta(deltas))

    result = consensus.build_consensus(
        settings=_settings(tmp_path), funds=(arkinvest, arkk), client=object()
    )

    buy_row = next(r for r in result.buys if r.cusip == "GGGGGGGGG")
    sell_row = next(r for r in result.sells if r.cusip == "GGGGGGGGG")
    assert buy_row.buyer_count == 1
    assert sell_row.seller_count == 1
    assert {m.key for m in buy_row.movers} == {"ARKINVEST", "ARKK"}


def test_ark_pair_counts_independently_when_only_one_present(tmp_path, monkeypatch):
    """Suppression only fires when *both* halves of the pair are in `checked` -- ARKK moving alone
    is a normal, fully-counted vote."""
    arkk = _fund("ARKK", source=Source.NPORT)
    deltas = {"ARKK": _delta(arkk, [_change("HHHHHHHHH", Action.ADD, weight_delta=Decimal("0.02"))])}
    monkeypatch.setattr(consensus.service, "load_delta", _fake_load_delta(deltas))

    result = consensus.build_consensus(settings=_settings(tmp_path), funds=(arkk,), client=object())

    row = next(r for r in result.buys if r.cusip == "HHHHHHHHH")
    assert row.buyer_count == 1
    assert {m.key for m in row.movers} == {"ARKK"}


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_ranking_is_deterministic_when_counts_tie(tmp_path, monkeypatch):
    """Two positions with identical buyer_count and identical total_weight_delta break the tie on
    CUSIP ascending, independent of input order."""
    fund_b = _fund("TIEFUND1")
    fund_a = _fund("TIEFUND2")
    # Deliberately fed to the fake in an order that would produce the wrong answer if insertion
    # order leaked through.
    deltas = {
        "TIEFUND1": _delta(fund_b, [_change("ZZZZZZZZZ", Action.ADD, weight_delta=Decimal("0.02"))]),
        "TIEFUND2": _delta(fund_a, [_change("AAAAAAAAA", Action.ADD, weight_delta=Decimal("0.02"))]),
    }
    monkeypatch.setattr(consensus.service, "load_delta", _fake_load_delta(deltas))

    result = consensus.build_consensus(
        settings=_settings(tmp_path), funds=(fund_b, fund_a), client=object()
    )

    assert [row.cusip for row in result.buys] == ["AAAAAAAAA", "ZZZZZZZZZ"]


def test_movers_are_sorted_by_fund_key_regardless_of_input_order(tmp_path, monkeypatch):
    fund_z = _fund("ZFUND")
    fund_a = _fund("AFUND")
    deltas = {
        "ZFUND": _delta(fund_z, [_change("IIIIIIIII", Action.ADD, weight_delta=Decimal("0.01"))]),
        "AFUND": _delta(fund_a, [_change("IIIIIIIII", Action.ADD, weight_delta=Decimal("0.01"))]),
    }
    monkeypatch.setattr(consensus.service, "load_delta", _fake_load_delta(deltas))

    result = consensus.build_consensus(
        settings=_settings(tmp_path), funds=(fund_z, fund_a), client=object()
    )
    row = next(r for r in result.buys if r.cusip == "IIIIIIIII")
    assert [m.key for m in row.movers] == ["AFUND", "ZFUND"]


# ---------------------------------------------------------------------------
# Decimal in, Decimal out
# ---------------------------------------------------------------------------


def test_decimals_stay_decimal_end_to_end(tmp_path, monkeypatch):
    fund = _fund("DECFUND")
    weight_delta = Decimal("0.1")  # not exactly representable as a binary float
    shares_delta = Decimal("12345")
    deltas = {
        "DECFUND": _delta(
            fund,
            [_change("JJJJJJJJJ", Action.ADD, weight_delta=weight_delta, shares_delta=shares_delta)],
        )
    }
    monkeypatch.setattr(consensus.service, "load_delta", _fake_load_delta(deltas))

    result = consensus.build_consensus(settings=_settings(tmp_path), funds=(fund,), client=object())

    row = result.buys[0]
    assert type(row.total_weight_delta) is Decimal
    assert row.total_weight_delta == weight_delta
    mover = row.movers[0]
    assert type(mover.weight_delta) is Decimal
    assert type(mover.shares_delta) is Decimal
    assert mover.weight_delta == weight_delta
    assert mover.shares_delta == shares_delta

    # And across the wire: every Decimal-typed field must serialize as a JSON *string*, never a
    # bare float, matching how `Money`/`Quantity` already cross this application's wire.
    body = json.loads(result.model_dump_json())
    row_json = body["buys"][0]
    assert isinstance(row_json["total_weight_delta"], str)
    assert isinstance(row_json["movers"][0]["weight_delta"], str)
    assert isinstance(row_json["movers"][0]["shares_delta"], str)


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


def test_cached_response_is_served_without_recomputing(tmp_path, monkeypatch):
    fund = _fund("CACHEFUND")
    call_count = {"n": 0}
    deltas = {
        "CACHEFUND": _delta(fund, [_change("KKKKKKKKK", Action.ADD, weight_delta=Decimal("0.01"))])
    }

    def _counting_load_delta(f, *, client, settings, as_of=None, candidate_limit=None):
        call_count["n"] += 1
        return deltas[f.key]

    monkeypatch.setattr(consensus.service, "load_delta", _counting_load_delta)
    settings = _settings(tmp_path)

    first = consensus.build_consensus(settings=settings, funds=(fund,), client=object())
    second = consensus.build_consensus(settings=settings, funds=(fund,), client=object())

    assert call_count["n"] == 1  # second call served from disk cache, no fund walked again
    assert second.generated_at == first.generated_at


def test_refresh_true_forces_recompute(tmp_path, monkeypatch):
    fund = _fund("REFRESHFUND")
    call_count = {"n": 0}
    deltas = {
        "REFRESHFUND": _delta(
            fund, [_change("LLLLLLLLL", Action.ADD, weight_delta=Decimal("0.01"))]
        )
    }

    def _counting_load_delta(f, *, client, settings, as_of=None, candidate_limit=None):
        call_count["n"] += 1
        return deltas[f.key]

    monkeypatch.setattr(consensus.service, "load_delta", _counting_load_delta)
    settings = _settings(tmp_path)

    consensus.build_consensus(settings=settings, funds=(fund,), client=object())
    consensus.build_consensus(settings=settings, funds=(fund,), client=object(), refresh=True)

    assert call_count["n"] == 2


def test_stale_cache_beyond_ttl_is_recomputed(tmp_path, monkeypatch):
    fund = _fund("STALEFUND")
    call_count = {"n": 0}
    deltas = {
        "STALEFUND": _delta(fund, [_change("MMMMMMMMM", Action.ADD, weight_delta=Decimal("0.01"))])
    }

    def _counting_load_delta(f, *, client, settings, as_of=None, candidate_limit=None):
        call_count["n"] += 1
        return deltas[f.key]

    monkeypatch.setattr(consensus.service, "load_delta", _counting_load_delta)
    settings = _settings(tmp_path)

    stale_now = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=consensus._CACHE_TTL_SECONDS + 60)
    consensus.build_consensus(settings=settings, funds=(fund,), client=object(), now=stale_now)
    consensus.build_consensus(settings=settings, funds=(fund,), client=object())

    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(consensus_api.router)
    return app


def test_route_shape_via_test_client(monkeypatch):
    """Proves the route exists and is shaped right, with the service layer stubbed out entirely --
    no fund walk, no disk cache, no network."""
    fixed_generated_at = dt.datetime(2026, 8, 24, 12, 0, 0, tzinfo=dt.UTC)

    def _fake_build_consensus(*, settings, as_of=None, refresh=False, limit=20):
        row = consensus.ConsensusRow(
            cusip="NNNNNNNNN",
            issuer="Example Corp",
            ticker="EX",
            buyer_count=3,
            seller_count=1,
            net_funds=2,
            total_weight_delta=Decimal("0.045"),
            movers=[
                consensus.FundMove(
                    key="FUNDA",
                    name="Fund A",
                    principal=None,
                    action=Action.ADD,
                    weight_delta=Decimal("0.02"),
                    shares_delta=Decimal("500"),
                    period=dt.date(2026, 6, 30),
                    source=Source.THIRTEEN_F,
                ),
            ],
        )
        return consensus.ConsensusResponse(
            generated_at=fixed_generated_at,
            as_of=as_of,
            checked=["FUNDA", "FUNDB"],
            unchecked=[consensus.UncheckedFund(key="FUNDC", name="Fund C", reason="TimeoutError: x")],
            buys=[row],
            sells=[],
        )

    monkeypatch.setattr(consensus_api, "build_consensus", _fake_build_consensus)

    client = TestClient(_app())
    response = client.get("/api/institutions/consensus")

    assert response.status_code == 200
    body = response.json()
    assert body["checked"] == ["FUNDA", "FUNDB"]
    assert body["unchecked"] == [{"key": "FUNDC", "name": "Fund C", "reason": "TimeoutError: x"}]
    assert body["buys"][0]["cusip"] == "NNNNNNNNN"
    assert body["buys"][0]["buyer_count"] == 3
    assert isinstance(body["buys"][0]["total_weight_delta"], str)
    assert body["sells"] == []
    print(json.dumps(body, indent=2))


def test_route_passes_query_params_through(monkeypatch):
    received = {}

    def _fake_build_consensus(*, settings, as_of=None, refresh=False, limit=20):
        received["as_of"] = as_of
        received["refresh"] = refresh
        received["limit"] = limit
        return consensus.ConsensusResponse(
            generated_at=dt.datetime.now(dt.UTC),
            as_of=as_of,
            checked=[],
            unchecked=[],
            buys=[],
            sells=[],
        )

    monkeypatch.setattr(consensus_api, "build_consensus", _fake_build_consensus)

    client = TestClient(_app())
    response = client.get("/api/institutions/consensus?as_of=2026-06-30&refresh=true&limit=5")

    assert response.status_code == 200
    assert received["as_of"] == dt.date(2026, 6, 30)
    assert received["refresh"] is True
    assert received["limit"] == 5
