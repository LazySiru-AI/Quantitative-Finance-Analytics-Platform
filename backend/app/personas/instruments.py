"""Deterministically classifying a ticker symbol into an `InstrumentKind`, symbol-only, no network.

**Why this exists.** `TickerMention.instrument` (see `app.personas.models`) defaults to `"equity"` so
every note written before the field existed loads unchanged, but a mention written going forward
should carry the real kind: an influencer naming `GC` is calling gold futures, not a stock, and a
watchlist that cannot tell the difference will happily suggest "buy GC" to someone whose broker has no
way to fill it. This module is the one place that decision gets made, so it is made the same way every
time -- from the symbol text alone, never from a network lookup, never from the transcript that
produced it. That is also why it is safe to run as a one-time reclassification pass over every mention
ever written: the same symbol always yields the same kind, regardless of when or how it was captured.

**Classification is a filter over curated sets, not a guess.** Every curated set below was
hand-checked against a real exchange/root list; nothing here infers a kind from a symbol's shape (a
5-letter symbol is not, on that basis alone, assumed to be a fund). The one exception is `fx`, which
does use a shape rule (a 6-letter run of two known 3-letter currency codes) because spelling out every
currency pair by hand would just reproduce the regex less legibly, with the same false-positive
exposure it has today (e.g. a genuine `AUDCAD`-shaped equity ticker, vanishingly unlikely on a US
exchange, would misclassify as `fx`).

**`classify` cannot always be right, and one root is a known, accepted miss.** `BZ` is both the NYMEX
Brent crude futures root and, on at least one exchange, an equity ticker. Symbol-only classification
has no way to tell those apart -- there is no transcript, no exchange field, nothing but three
characters -- so this module resolves the ambiguity toward `future`. That is a deliberate choice, not
an oversight: the cost of wrongly flagging a `BZ` equity mention as untradeable-as-is (the reader
checks and finds it is actually a stock) is far smaller than the cost of missing a real futures mention
because it looked equity-shaped, which is the whole reason this module exists. See `_FUTURE_ROOTS` for
the note where this is pinned in code, not just in this docstring where a future edit could drift from
the sets and no test would catch it.

**Decision order (first match wins), and why it is fixed instead of scored:**

1. `crypto` -- a curated set of majors, plus anything shaped like a stablecoin pair (`*-USD`/`*-USDT`).
   Checked first because the `-USD`/`-USDT` suffix rule is the most specific signal here and nothing
   below it could ever legitimately share that shape.
2. `future` -- curated CME/COMEX/NYMEX/CBOT roots. Checked before `index`/`etf` because several roots
   (`ES`, `NQ`, `YM`, `RTY`) are equity-index futures whose underlying index this module *also* curates
   under `index` (`SPX`, `NDX`, `DJI`, `RUT`) -- the root and the index are different symbols so they
   never collide in practice, but the ordering documents which table a look-alike should fall to if the
   curated sets are ever extended carelessly.
3. `index` -- a leading `^` (the common index-prefix convention) or a curated name.
4. `fx` -- `DXY` (the dollar index, conventionally quoted like a currency pair) or a 6-letter run of two
   known 3-letter currency codes.
5. `etf` -- a curated set of the ETFs this feature actually deals with (index/sector/commodity trackers
   and the two spot-crypto ETFs already in curated use elsewhere in this codebase).
6. Otherwise `equity` -- the historical default (see `InstrumentKind`'s docstring in `models.py`), and
   deliberately not `unknown`: the overwhelming majority of unrecognised symbols named on an investing
   channel are ordinary stocks this module simply has no curated entry for, and treating "not in my
   curated list" as "unknown" would make every future ETF launch or newly-covered small-cap silently
   stop being usable in a card universe until someone edits this file.

Empty (or whitespace-only) input is the one case that returns `"unknown"` -- there is no symbol to
classify at all, which is a different problem from "a real symbol I don't have curated."
"""

from __future__ import annotations

import re

from app.personas.models import InstrumentKind

__all__ = ["PROXY_TABLE", "classify", "is_tradeable", "suggest_proxy"]

#: Curated crypto majors named by the personas this feature ingests. Not exhaustive of every coin that
#: exists -- exhaustive is impossible and unnecessary, since the `-USD`/`-USDT` suffix rule below
#: catches the long tail of pairs an influencer might quote a price against.
_CRYPTO_SYMBOLS = frozenset(
    {
        "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "MATIC", "LTC", "BCH",
    }
)

_CRYPTO_QUOTE_SUFFIXES = ("-USD", "-USDT")

#: CME/COMEX/NYMEX/CBOT futures roots this feature's curated instruments actually cover, grouped the
#: way the exchanges group them. `BZ` (Brent crude, NYMEX) is the one root known to also be used as an
#: equity ticker elsewhere -- see the module docstring's "known, accepted miss" section. It stays in
#: this set anyway: symbol-only classification cannot disambiguate it, and erring toward `future` here
#: is the deliberate choice, not an accident of this set's construction.
_FUTURE_ROOTS = frozenset(
    {
        # metals
        "GC", "SI", "HG", "PL", "PA",
        # energy
        "CL", "BZ", "NG", "RB", "HO",
        # grains
        "ZC", "ZS", "ZW", "ZL", "ZM",
        # equity-index futures
        "ES", "NQ", "YM", "RTY",
        # rates
        "ZB", "ZN", "ZF", "ZT",
    }
)

#: Index symbols named without the leading `^` some data providers use. `SOX` here is the Philadelphia
#: Semiconductor *index*, distinct from `SOXX`, the ETF that tracks it -- the two are different symbols
#: on purpose and each belongs to exactly one curated set below.
_INDEX_SYMBOLS = frozenset({"NDX", "SPX", "DJI", "RUT", "VIX", "SOX", "COMPQ", "NDXT"})

#: ISO-4217-style currency codes this module recognises for FX-pair shape matching. Not the full ISO
#: list -- just the majors an investing-content influencer is actually likely to name.
_CURRENCIES = ("USD", "EUR", "JPY", "GBP", "CHF", "CAD", "AUD", "NZD", "CNY", "KRW")

#: A 6-letter run of exactly two (possibly repeated) known currency codes, e.g. `USDJPY`, `EURUSD`.
#: Because the alternation is repeated rather than paired explicitly, this also matches a degenerate
#: case like `USDUSD` -- accepted rather than special-cased, since no real symbol takes that shape and
#: excluding it would add complexity for a case that can never actually occur.
_FX_PAIR_RE = re.compile(r"^(?:" + "|".join(_CURRENCIES) + r"){2}$")

#: ETFs this feature deals with in curated form: the broad index/sector/commodity trackers an
#: influencer or a proxy lookup is likely to name, plus the two spot-crypto ETFs (`IBIT`, `ETHA`) that
#: are also `PROXY_TABLE` targets below.
_ETF_SYMBOLS = frozenset(
    {
        "SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "GDX", "GDXJ", "USO", "UNG", "TLT", "IEF", "HYG",
        "LQD", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", "SOXX",
        "SMH", "ARKK", "IBIT", "ETHA", "VOO", "VTI", "SCHD", "QQQM",
    }
)


def classify(symbol: str) -> InstrumentKind:
    """Classify `symbol` into an `InstrumentKind`, deterministically and offline.

    Case-insensitive and whitespace-tolerant (`" gc "` classifies exactly like `"GC"`). See the module
    docstring for the fixed first-match-wins order this follows and why each check is where it is.
    """
    s = symbol.strip().upper()
    if not s:
        return "unknown"

    if s in _CRYPTO_SYMBOLS or s.endswith(_CRYPTO_QUOTE_SUFFIXES):
        return "crypto"

    if s in _FUTURE_ROOTS:
        return "future"

    if s.startswith("^") or s in _INDEX_SYMBOLS:
        return "index"

    if s == "DXY" or (len(s) == 6 and _FX_PAIR_RE.match(s)):
        return "fx"

    if s in _ETF_SYMBOLS:
        return "etf"

    return "equity"


#: Non-equity symbol (upper-cased) -> a real, US-listed tradeable ETF a reader could actually buy as a
#: stand-in. Deliberately incomplete: a symbol is only here when there is a genuine, confidently-real
#: ETF for it. `SOL` (Solana) has no such entry -- there is no US-listed spot-Solana ETF this module's
#: author could confirm with confidence, and inventing one would be strictly worse than the watchlist
#: simply saying "no proxy available" (which is what an absent key produces via `suggest_proxy`).
PROXY_TABLE: dict[str, str] = {
    # metals futures -> commodity ETFs
    "GC": "GLD",
    "SI": "SLV",
    "HG": "CPER",
    "PL": "PPLT",
    # energy futures -> commodity ETFs
    "CL": "USO",
    "BZ": "BNO",
    "NG": "UNG",
    # grain futures -> commodity ETFs
    "ZC": "CORN",
    "ZS": "SOYB",
    "ZW": "WEAT",
    # equity-index futures -> the matching broad-index ETF
    "ES": "SPY",
    "NQ": "QQQ",
    "YM": "DIA",
    "RTY": "IWM",
    # rates futures -> the matching bond ETF
    "ZB": "TLT",
    "ZN": "IEF",
    # cash indices -> the matching broad-index/sector ETF
    "NDX": "QQQ",
    "SPX": "SPY",
    "DJI": "DIA",
    "RUT": "IWM",
    "SOX": "SOXX",
    "VIX": "VIXY",
    # FX -> the matching currency-exposure ETF
    "DXY": "UUP",
    # crypto -> spot-crypto ETFs
    "BTC": "IBIT",
    "ETH": "ETHA",
}


def suggest_proxy(symbol: str) -> str | None:
    """A tradeable ETF proxy for `symbol`, or `None` when `PROXY_TABLE` has none.

    Case-insensitive and whitespace-tolerant like `classify`. A `None` here means exactly "this module
    has no curated proxy" -- never inferred, never guessed at query time.
    """
    return PROXY_TABLE.get(symbol.strip().upper())


def is_tradeable(kind: InstrumentKind) -> bool:
    """Whether a mention of this kind is something a reader could act on directly through an ordinary
    equities broker. Only `"equity"` and `"etf"` qualify -- an index cannot be bought, a future needs a
    futures account, crypto and fx need a different venue entirely, and `"unknown"` has no confirmed
    kind to trade at all."""
    return kind in ("equity", "etf")
