"""Unit tests for `app.personas.instruments` -- the deterministic, offline symbol -> `InstrumentKind`
classifier and its ETF-proxy table.

Every assertion here is symbol-only and network-free by construction (the module itself never imports
anything network-capable), so unlike `test_personas_tickers.py` there is no `settings` fixture and
nothing to monkeypatch: the same input must always produce the same output, in this process or any
other.
"""

from __future__ import annotations

import pytest

from app.personas.instruments import PROXY_TABLE, classify, is_tradeable, suggest_proxy
from app.personas.models import InstrumentKind

# --- classify: one representative symbol per kind ---------------------------


def test_classify_crypto_curated_majors() -> None:
    for symbol in ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "MATIC", "LTC", "BCH"):
        assert classify(symbol) == "crypto"


def test_classify_crypto_quote_suffix() -> None:
    """Anything shaped like a stablecoin-quoted pair is crypto even when the base is not itself in the
    curated majors set -- the suffix is the more specific signal."""
    assert classify("PEPE-USD") == "crypto"
    assert classify("SHIB-USDT") == "crypto"


def test_classify_future_curated_roots() -> None:
    for symbol in (
        "GC", "SI", "HG", "PL", "PA",  # metals
        "CL", "BZ", "NG", "RB", "HO",  # energy
        "ZC", "ZS", "ZW", "ZL", "ZM",  # grains
        "ES", "NQ", "YM", "RTY",  # equity-index futures
        "ZB", "ZN", "ZF", "ZT",  # rates
    ):
        assert classify(symbol) == "future"


def test_classify_future_bz_is_the_accepted_ambiguous_case() -> None:
    """`BZ` is documented as genuinely ambiguous (also used as an equity ticker elsewhere) -- this
    module resolves it toward `future` on purpose, since symbol-only classification cannot tell the
    two apart and erring toward flagging is the safer failure mode."""
    assert classify("BZ") == "future"


def test_classify_index_caret_prefix() -> None:
    assert classify("^GSPC") == "index"
    assert classify("^DJI") == "index"


def test_classify_index_curated_names() -> None:
    for symbol in ("NDX", "SPX", "DJI", "RUT", "VIX", "SOX", "COMPQ", "NDXT"):
        assert classify(symbol) == "index"


def test_classify_fx_currency_pairs() -> None:
    for symbol in ("USDJPY", "EURUSD", "GBPCHF", "AUDNZD", "USDKRW", "USDCNY"):
        assert classify(symbol) == "fx"


def test_classify_fx_dollar_index() -> None:
    assert classify("DXY") == "fx"


def test_classify_etf_curated_set() -> None:
    for symbol in (
        "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "GDX", "GDXJ", "USO", "UNG", "TLT", "IEF", "HYG",
        "LQD", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "SOXX",
        "SMH", "ARKK", "IBIT", "ETHA", "VOO", "VTI", "SCHD", "QQQM",
    ):
        assert classify(symbol) == "etf"


def test_classify_sox_index_vs_soxx_etf_are_distinct() -> None:
    """`SOX` (the Philadelphia Semiconductor index) and `SOXX` (the ETF tracking it) are different
    symbols with different kinds -- a one-letter typo must not blur the two."""
    assert classify("SOX") == "index"
    assert classify("SOXX") == "etf"


def test_classify_unrecognised_symbol_defaults_to_equity() -> None:
    """A symbol with no curated entry anywhere is, per the module's documented default, treated as an
    ordinary equity -- not `"unknown"`. This is the overwhelmingly common case: most tickers named on
    an investing channel are stocks this module simply has no curated list for."""
    for symbol in ("NVDA", "AAPL", "ZZZZQ", "SOMENEWIPO"):
        assert classify(symbol) == "equity"


def test_classify_empty_input_is_unknown() -> None:
    """Empty (or whitespace-only) input is the one case reserved for `"unknown"` -- there is no symbol
    to classify at all, distinct from a real symbol this module has no curated entry for."""
    assert classify("") == "unknown"
    assert classify("   ") == "unknown"


# --- classify: case-insensitivity and whitespace tolerance -------------------


def test_classify_is_case_insensitive_and_strips_whitespace() -> None:
    assert classify("btc") == "crypto"
    assert classify(" Btc ") == "crypto"
    assert classify("gc") == "future"
    assert classify(" spy ") == "etf"
    assert classify("spx") == "index"
    assert classify("usdjpy") == "fx"
    assert classify(" nvda ") == "equity"


# --- PROXY_TABLE / suggest_proxy ---------------------------------------------


def test_every_proxy_table_entry_resolves_via_suggest_proxy() -> None:
    for symbol, proxy in PROXY_TABLE.items():
        assert suggest_proxy(symbol) == proxy


def test_suggest_proxy_is_case_insensitive_and_strips_whitespace() -> None:
    for symbol, proxy in PROXY_TABLE.items():
        assert suggest_proxy(symbol.lower()) == proxy
        assert suggest_proxy(f" {symbol} ") == proxy


def test_suggest_proxy_returns_none_when_no_proxy_is_curated() -> None:
    assert suggest_proxy("NVDA") is None
    assert suggest_proxy("SOL") is None, "no confidently-real US-listed spot-Solana ETF is curated"
    assert suggest_proxy("") is None


def test_every_proxy_table_source_symbol_is_not_itself_tradeable() -> None:
    """Every key in `PROXY_TABLE` exists precisely because you cannot trade it directly through an
    ordinary equities broker -- if a source symbol classified as equity/etf, offering it a proxy would
    be nonsensical (you could just trade the thing itself)."""
    for symbol in PROXY_TABLE:
        kind = classify(symbol)
        assert not is_tradeable(kind), f"{symbol} classified as {kind!r}, expected a non-tradeable kind"


def test_every_proxy_table_target_is_a_tradeable_equity_or_etf() -> None:
    """The whole point of a proxy is that a reader CAN trade it -- so every value in `PROXY_TABLE` must
    itself classify as `equity` or `etf`."""
    for proxy in PROXY_TABLE.values():
        kind = classify(proxy)
        assert is_tradeable(kind), f"proxy {proxy!r} classified as {kind!r}, expected equity or etf"


@pytest.mark.parametrize(
    ("symbol", "expected_proxy"),
    [
        ("GC", "GLD"),
        ("SI", "SLV"),
        ("HG", "CPER"),
        ("PL", "PPLT"),
        ("CL", "USO"),
        ("BZ", "BNO"),
        ("NG", "UNG"),
        ("ZC", "CORN"),
        ("ZS", "SOYB"),
        ("ZW", "WEAT"),
        ("ES", "SPY"),
        ("NQ", "QQQ"),
        ("YM", "DIA"),
        ("RTY", "IWM"),
        ("ZB", "TLT"),
        ("ZN", "IEF"),
        ("NDX", "QQQ"),
        ("SPX", "SPY"),
        ("DJI", "DIA"),
        ("RUT", "IWM"),
        ("SOX", "SOXX"),
        ("VIX", "VIXY"),
        ("DXY", "UUP"),
        ("BTC", "IBIT"),
        ("ETH", "ETHA"),
    ],
)
def test_proxy_table_matches_the_documented_mapping(symbol: str, expected_proxy: str) -> None:
    """Pins the exact mapping named in the module's spec, one row at a time, so a future edit that
    silently drops or changes a row fails at a specific, readable assertion."""
    assert PROXY_TABLE[symbol] == expected_proxy


def test_proxy_table_has_no_solana_entry() -> None:
    """Explicitly pins the one documented omission: `SOL` has no curated proxy because there is no
    confidently-real US-listed spot-Solana ETF, and this module omits rather than invents one."""
    assert "SOL" not in PROXY_TABLE


# --- is_tradeable -------------------------------------------------------------


def test_is_tradeable_true_only_for_equity_and_etf() -> None:
    tradeable: dict[InstrumentKind, bool] = {
        "equity": True,
        "etf": True,
        "index": False,
        "future": False,
        "crypto": False,
        "fx": False,
        "unknown": False,
    }
    for kind, expected in tradeable.items():
        assert is_tradeable(kind) is expected
