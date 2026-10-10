"""Deterministic fact gathering: the only place a stage's numbers are allowed to come from.

Every function here turns one data-layer read into an :class:`~app.agentdesk.models.EvidenceSection`,
and :func:`build_pack` assembles the sections a stage is configured to see into one
:class:`~app.agentdesk.models.EvidencePack`. Nothing in this module calls a model, and nothing in it
raises on a bad day from a provider -- see the next paragraph.

**Every builder is fail-soft, by construction rather than by convention.** Each public function
(`price_evidence`, `news_evidence`, ...) is a thin wrapper around a private twin that returns
`(EvidenceSection, tuple[str, ...])` -- the section, plus zero or more warning strings explaining any
provider failure or empty result. The public function drops the warnings and returns the section
alone, matching the exact signatures wave-2 is built against; :func:`build_pack` calls the private
twins directly so it can fold every one of those warnings into `EvidencePack.warnings`. A provider
outage therefore never raises past this module -- it becomes an empty section plus a sentence in the
pack a reader (and the model) can see, which is the same contract `app.market.macro.build_snapshot`
and `app.market.news` already hold their callers to; this module extends it to the desk's evidence
layer rather than inventing a second convention.

**Numbers become strings exactly once.** Every :class:`~app.agentdesk.models.EvidenceItem.value` is
formatted at the point a provider's number is read (`f"{value:.2f}"` for a price, `str(count)` for a
count) and never re-derived from a re-parsed string later -- the whole point of storing a number as
text is that the figure a model reads in the rendered prompt is byte-identical to the figure
`app.agentdesk.grounding` checks its prose against.

**`price_evidence`'s verified-snapshot block is the anti-confabulation device this package borrows
from TradingAgents.** A market analyst that is handed only "the latest close" has nothing to check
its own arithmetic against if it tries to describe a trend; handing it the last several closes as
individually grounded facts (not just as narrative text) means "the stock rose for three sessions" is
a claim the grounding gate can actually verify, not just a claim the model asserts.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

import pandas as pd

from app.agentdesk.models import EvidenceItem, EvidencePack, EvidenceSection
from app.config import Settings
from app.indicators import registry as indicator_registry
from app.indicators.base import IndicatorError
from app.market import livefeed, store
from app.market.models import Interval
from app.market.providers.base import ProviderError
from app.market.registry import default_registry

__all__ = [
    "DEFAULT_INDICATORS",
    "SECTION_KEYS",
    "build_pack",
    "events_evidence",
    "fundamentals_evidence",
    "indicator_evidence",
    "intraday_evidence",
    "live_quote_evidence",
    "macro_evidence",
    "news_evidence",
    "price_evidence",
    "render_pack",
    "social_evidence",
]

#: One spec string per indicator, in the colon-and-comma syntax `app.indicators.base.parse_spec`
#: actually parses (`"bb:20,2"`, not `"bb(20,2)"`) -- see this module's delivery report for the
#: reconciliation note: the brief's own illustrative example used parenthesised arguments, which is
#: not a syntax this registry accepts. `sma(50)`, `sma(200)`, `ema(10)`, `rsi(14)`, `macd`, `bb(20,2)`
#: and `atr(14)` from the brief map onto the seven entries below one-for-one at their default/parameter
#: values.
DEFAULT_INDICATORS: tuple[str, ...] = (
    "sma:50",
    "sma:200",
    "ema:10",
    "rsi:14",
    "macd",
    "bb:20,2",
    "atr:14",
)

#: Every section `build_pack` knows how to assemble. A caller's `sections` argument may name any
#: subset, in any order; anything outside this tuple is a caller bug, raised loudly rather than
#: silently skipped -- the whole point of a closed set here is that a desk's stage prompt and its
#: evidence pack cannot silently drift apart.
#:
#: `"live_quote"` and `"intraday"` are appended at the end, deliberately: `build_pack` assembles
#: sections in the order the *caller* asked for, but every existing preset names its sections
#: explicitly and none of them names these two, so appending here changes nothing for any current
#: caller. Both are look-ahead-gated (see `_is_historical`) -- a replay of a past date gets an empty
#: section and a warning rather than today's price, which is the invariant `AsOfMarket` enforces
#: everywhere else in this application and the one a live feed is most able to break.
SECTION_KEYS: tuple[str, ...] = (
    "price",
    "indicators",
    "news",
    "social",
    "fundamentals",
    "macro",
    "events",
    "live_quote",
    "intraday",
)

#: How many calendar days of daily bars `price_evidence` reads by default -- wide enough to cover a
#: multi-week trend narrative without paying for a symbol's full history on every stage.
_DEFAULT_LOOKBACK_DAYS = 180

#: How many of the most recent closes go into the verified snapshot -- see the module docstring.
_SNAPSHOT_CLOSES = 10

#: `sma:200`'s warmup alone is 200 bars; this is calendar days, not trading days, so the padding has
#: to clear roughly 200 trading days plus weekends/holidays. 420 calendar days is comfortably north of
#: a trading year (~252 sessions).
_INDICATOR_LOOKBACK_DAYS = 420

_NEWS_LIMIT = 20
_SOCIAL_LIMIT = 30
_EVENTS_LIMIT = 10


def _empty(title: str, reason: str) -> tuple[EvidenceSection, tuple[str, ...]]:
    """A section with nothing in it, and the one-line reason why -- the fail-soft return shared by
    every private builder below when a provider failed or genuinely had nothing to report."""
    return EvidenceSection(title=title), (reason,)


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------


def _price_evidence(
    symbol: str, as_of: dt.date | None, *, settings: Settings, lookback_days: int = _DEFAULT_LOOKBACK_DAYS
) -> tuple[EvidenceSection, tuple[str, ...]]:
    warnings: list[str] = []
    reference = as_of or dt.date.today()
    start = reference - dt.timedelta(days=lookback_days)

    try:
        series = store.ensure_series(symbol, Interval.DAY, start=start, end=as_of, settings=settings)
    except ProviderError as exc:
        return _empty("Price", f"price data unavailable for {symbol}: {exc}")
    except Exception as exc:  # pragma: no cover - defensive; the data layer types its own failures
        return _empty("Price", f"price data unavailable for {symbol}: {type(exc).__name__}: {exc}")

    warnings.extend(f"{symbol} price: {w.message}" for w in series.warnings)
    if not series.bars:
        warnings.append(f"price data unavailable for {symbol}: the store returned no bars")
        return EvidenceSection(title="Price"), tuple(warnings)

    source = series.source.value
    latest = series.bars[-1]
    latest_date = latest.ts.date().isoformat()

    items: list[EvidenceItem] = [
        EvidenceItem(key="open", label="Open", value=f"{latest.open:.2f}", unit="USD", as_of=latest_date, source=source),
        EvidenceItem(key="high", label="High", value=f"{latest.high:.2f}", unit="USD", as_of=latest_date, source=source),
        EvidenceItem(key="low", label="Low", value=f"{latest.low:.2f}", unit="USD", as_of=latest_date, source=source),
        EvidenceItem(key="close", label="Close", value=f"{latest.close:.2f}", unit="USD", as_of=latest_date, source=source),
    ]
    if latest.volume is not None:
        items.append(
            EvidenceItem(
                key="volume", label="Volume", value=str(latest.volume), unit="shares",
                as_of=latest_date, source=source,
            )
        )

    recent = series.bars[-_SNAPSHOT_CLOSES:]
    lines = [
        f"Verified snapshot -- the last {len(recent)} daily closes, oldest first. Quote only these "
        "figures when describing a trend; do not estimate an intermediate value."
    ]
    for offset, bar in enumerate(recent):
        days_back = len(recent) - 1 - offset
        key = "close_t" if days_back == 0 else f"close_t-{days_back}"
        bar_date = bar.ts.date().isoformat()
        value = f"{bar.close:.2f}"
        items.append(
            EvidenceItem(key=key, label=f"Close ({bar_date})", value=value, unit="USD", as_of=bar_date, source=source)
        )
        lines.append(f"- {bar_date}: {value}")

    return EvidenceSection(title="Price", items=tuple(items), text="\n".join(lines)), tuple(warnings)


def price_evidence(
    symbol: str, as_of: dt.date | None, *, settings: Settings, lookback_days: int = _DEFAULT_LOOKBACK_DAYS
) -> EvidenceSection:
    section, _warnings = _price_evidence(symbol, as_of, settings=settings, lookback_days=lookback_days)
    return section


# ---------------------------------------------------------------------------
# Indicators
# ---------------------------------------------------------------------------


def _indicator_evidence(
    symbol: str, as_of: dt.date | None, *, settings: Settings, indicators: tuple[str, ...] = DEFAULT_INDICATORS
) -> tuple[EvidenceSection, tuple[str, ...]]:
    warnings: list[str] = []
    reference = as_of or dt.date.today()
    start = reference - dt.timedelta(days=_INDICATOR_LOOKBACK_DAYS)

    try:
        store.ensure_series(symbol, Interval.DAY, start=start, end=as_of, settings=settings)
        frame = store.read_frame(symbol, Interval.DAY, start=start, end=as_of, settings=settings)
    except ProviderError as exc:
        return _empty("Indicators", f"indicator data unavailable for {symbol}: {exc}")
    except Exception as exc:  # pragma: no cover - defensive; the data layer types its own failures
        return _empty("Indicators", f"indicator data unavailable for {symbol}: {type(exc).__name__}: {exc}")

    if frame.empty:
        warnings.append(f"indicator data unavailable for {symbol}: the store returned no bars")
        return EvidenceSection(title="Indicators"), tuple(warnings)

    requests = []
    for spec_text in indicators:
        try:
            requests.append(indicator_registry.request(spec_text, interval=Interval.DAY))
        except IndicatorError as exc:
            warnings.append(f"indicator {spec_text!r} skipped for {symbol}: {exc}")

    if not requests:
        warnings.append(f"no requested indicator could be parsed for {symbol}")
        return EvidenceSection(title="Indicators"), tuple(warnings)

    computed = indicator_registry.compute(frame, requests)
    if computed.empty:
        warnings.append(f"indicator computation produced no rows for {symbol}")
        return EvidenceSection(title="Indicators"), tuple(warnings)

    as_of_date = frame["ts"].iloc[-1]
    as_of_str = as_of_date.date().isoformat() if hasattr(as_of_date, "date") else str(as_of_date)
    latest_row = computed.iloc[-1]

    items = [
        EvidenceItem(key=col, label=col.upper(), value=f"{float(latest_row[col]):.2f}", as_of=as_of_str, source="duckdb-store")
        for col in computed.columns
        if not pd.isna(latest_row[col])
    ]
    if not items:
        warnings.append(f"every requested indicator is still inside its warmup window for {symbol}")
    return EvidenceSection(title="Indicators", items=tuple(items)), tuple(warnings)


def indicator_evidence(
    symbol: str, as_of: dt.date | None, *, settings: Settings, indicators: tuple[str, ...] = DEFAULT_INDICATORS
) -> EvidenceSection:
    section, _warnings = _indicator_evidence(symbol, as_of, settings=settings, indicators=indicators)
    return section


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


def _news_evidence(symbol: str, *, settings: Settings) -> tuple[EvidenceSection, tuple[str, ...]]:
    warnings: list[str] = []
    reg = default_registry(settings)
    try:
        feed = reg.get_symbol_news(symbol, limit=_NEWS_LIMIT)
    except ProviderError as exc:
        return _empty("News", f"news unavailable for {symbol}: {exc}")
    except Exception as exc:  # pragma: no cover - defensive; the data layer types its own failures
        return _empty("News", f"news unavailable for {symbol}: {type(exc).__name__}: {exc}")

    warnings.extend(f"{symbol} news: {w.message}" for w in feed.warnings)
    if not feed.items:
        warnings.append(f"no headlines available for {symbol}")
        return EvidenceSection(title="News"), tuple(warnings)

    generated_at = dt.datetime.now(dt.UTC).date().isoformat()
    items = (
        EvidenceItem(
            key="headline_count", label="Headline count", value=str(len(feed.items)), unit="articles",
            as_of=generated_at, source=feed.source or "news",
        ),
    )
    # Headline titles are prose, not grounded evidence -- a number embedded in a headline ("beats by
    # $0.10") must never be treated as something the stage is entitled to quote on its own authority.
    # See app.agentdesk.grounding and the EvidenceSection contract in models.py.
    lines = [
        f"- {item.published.date().isoformat()} [{item.publisher or item.source}] {item.title}"
        for item in feed.items
    ]
    return EvidenceSection(title="News", items=items, text="\n".join(lines)), tuple(warnings)


def news_evidence(symbol: str, *, settings: Settings) -> EvidenceSection:
    section, _warnings = _news_evidence(symbol, settings=settings)
    return section


# ---------------------------------------------------------------------------
# Social
# ---------------------------------------------------------------------------


def _social_evidence(symbol: str, *, settings: Settings) -> tuple[EvidenceSection, tuple[str, ...]]:
    reg = default_registry(settings)
    try:
        snapshot = reg.get_social(symbol, limit=_SOCIAL_LIMIT)
    except ProviderError as exc:
        return _empty("Social", f"social sentiment unavailable for {symbol}: {exc}")
    except Exception as exc:  # pragma: no cover - defensive; the data layer types its own failures
        return _empty("Social", f"social sentiment unavailable for {symbol}: {type(exc).__name__}: {exc}")

    as_of_str = snapshot.as_of.date().isoformat()
    # Counts only, matching app.market.news_models' own rule: a provider may report what it counted,
    # never what it concluded. There is no "sentiment score" item here on purpose.
    items = (
        EvidenceItem(key="bullish", label="Bullish messages", value=str(snapshot.bullish), unit="messages", as_of=as_of_str, source=snapshot.source),
        EvidenceItem(key="bearish", label="Bearish messages", value=str(snapshot.bearish), unit="messages", as_of=as_of_str, source=snapshot.source),
        EvidenceItem(key="neutral", label="Unlabelled messages", value=str(snapshot.neutral), unit="messages", as_of=as_of_str, source=snapshot.source),
        EvidenceItem(key="total", label="Total messages", value=str(snapshot.total), unit="messages", as_of=as_of_str, source=snapshot.source),
    )
    return EvidenceSection(title="Social", items=items), ()


def social_evidence(symbol: str, *, settings: Settings) -> EvidenceSection:
    section, _warnings = _social_evidence(symbol, settings=settings)
    return section


# ---------------------------------------------------------------------------
# Fundamentals
# ---------------------------------------------------------------------------


def _fundamentals_evidence(symbol: str, *, settings: Settings) -> tuple[EvidenceSection, tuple[str, ...]]:
    reg = default_registry(settings)
    try:
        fundamentals = reg.get_fundamentals(symbol)
    except ProviderError as exc:
        return _empty("Fundamentals", f"fundamentals unavailable for {symbol}: {exc}")
    except Exception as exc:  # pragma: no cover - defensive; the data layer types its own failures
        return _empty("Fundamentals", f"fundamentals unavailable for {symbol}: {type(exc).__name__}: {exc}")

    if not fundamentals.facts:
        # Not a provider outage -- most of this portfolio is ETFs, which is the *expected* answer.
        # See app.market.fundamentals' own module docstring. Still worth a warning: an empty section
        # with no explanation reads as "the desk forgot to look," not as "there is nothing to find."
        reason = fundamentals.unavailable_reason or f"no fundamentals facts available for {symbol}"
        return _empty("Fundamentals", reason)

    items = tuple(
        EvidenceItem(
            key=fact.concept, label=fact.label, value=f"{fact.value:.2f}", unit=fact.unit,
            as_of=fact.period_end.isoformat(), source="sec-edgar",
        )
        for fact in fundamentals.facts
    )
    return EvidenceSection(title="Fundamentals", items=items), ()


def fundamentals_evidence(symbol: str, *, settings: Settings) -> EvidenceSection:
    section, _warnings = _fundamentals_evidence(symbol, settings=settings)
    return section


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------


def _macro_evidence(*, settings: Settings) -> tuple[EvidenceSection, tuple[str, ...]]:
    from app.market.macro import build_snapshot  # local import: keeps this module importable even
    # if app.market.macro's own provider wiring is mid-change; every other section already reaches
    # into app.market lazily via default_registry for the same reason.

    try:
        snapshot = build_snapshot(settings)
    except Exception as exc:  # pragma: no cover - build_snapshot itself never raises; defensive only
        return _empty("Macro", f"macro snapshot unavailable: {type(exc).__name__}: {exc}")

    warnings = [f"macro: {w.message}" for w in snapshot.warnings]
    items: list[EvidenceItem] = []
    for tile in (*snapshot.rates, *snapshot.oil):
        if tile.value is None or tile.as_of is None:
            continue
        items.append(
            EvidenceItem(
                key=tile.key, label=tile.label, value=f"{tile.value:.2f}", unit=tile.unit.value,
                as_of=tile.as_of.isoformat(), source=tile.source.value,
            )
        )
    if snapshot.fear_greed is not None:
        fear_greed = snapshot.fear_greed
        items.append(
            EvidenceItem(
                key="fear_greed", label="Fear & Greed Index", value=f"{fear_greed.score:.0f}",
                unit="index", as_of=fear_greed.as_of.isoformat(), source=fear_greed.source.value,
            )
        )

    if not items:
        warnings.append("macro snapshot returned no usable tiles")
    return EvidenceSection(title="Macro", items=tuple(items)), tuple(warnings)


def macro_evidence(*, settings: Settings) -> EvidenceSection:
    section, _warnings = _macro_evidence(settings=settings)
    return section


# ---------------------------------------------------------------------------
# Events (prediction markets)
# ---------------------------------------------------------------------------


def _events_evidence(symbol: str, *, settings: Settings) -> tuple[EvidenceSection, tuple[str, ...]]:
    reg = default_registry(settings)
    try:
        markets = reg.get_events(symbol, limit=_EVENTS_LIMIT)
    except ProviderError as exc:
        return _empty("Events", f"prediction markets unavailable for {symbol}: {exc}")
    except Exception as exc:  # pragma: no cover - defensive; the data layer types its own failures
        return _empty("Events", f"prediction markets unavailable for {symbol}: {type(exc).__name__}: {exc}")

    if not markets:
        return _empty("Events", f"no prediction markets found for {symbol}")

    items: list[EvidenceItem] = []
    lines: list[str] = []
    for index, market in enumerate(markets):
        as_of_str = market.as_of.date().isoformat()
        items.append(
            EvidenceItem(
                key=f"event_{index}_probability", label=f"Prediction market probability ({market.slug})",
                value=f"{market.probability:.2f}", unit="probability", as_of=as_of_str, source=market.source,
            )
        )
        # The question text is prose, not grounded evidence -- see the same reasoning as news
        # headlines above: a figure embedded in the question wording is not one this stage measured.
        lines.append(f"- {market.question} (probability {market.probability:.0%}, source {market.source})")

    return EvidenceSection(title="Events", items=tuple(items), text="\n".join(lines)), ()


def events_evidence(symbol: str, *, settings: Settings) -> EvidenceSection:
    section, _warnings = _events_evidence(symbol, settings=settings)
    return section


# ---------------------------------------------------------------------------
# Live quote and intraday -- the only two sections that can see *today*, and therefore the only two
# that need a look-ahead gate.
# ---------------------------------------------------------------------------

#: How many calendar days back `_intraday_evidence` asks the store for, to find "the current
#: session". Five, not one: a Monday morning, a holiday, or any request made before the open has no
#: bars for today at all, and asking for exactly one day would report "no data" for the ordinary case
#: of a market that simply has not opened yet. The section then keeps only the newest session present
#: and says so when that session is not today.
_INTRADAY_LOOKBACK_DAYS = 5

#: How many bars go into the section's readable table. The full `bars` window goes into the *items*
#: (as high/low/volume/count); this is only how much of it is spelled out as prose.
_INTRADAY_TABLE_BARS = 6


def _is_historical(as_of: dt.date | None) -> bool:
    """Whether `as_of` names a date in the past, and a live section must therefore stay empty.

    `None` means "now" and is not historical; today is not historical. Anything earlier is a replay,
    and a replay that could see the current quote would be exactly the look-ahead this application
    spends `AsOfMarket` preventing -- a backtest is worthless the moment one of its inputs knows the
    answer. Compared in UTC, matching every other timestamp this feature produces.
    """
    return as_of is not None and as_of < dt.datetime.now(dt.UTC).date()


def _live_quote_evidence(
    symbol: str, as_of: dt.date | None, *, settings: Settings
) -> tuple[EvidenceSection, tuple[str, ...]]:
    if _is_historical(as_of):
        assert as_of is not None  # _is_historical is False for None
        return _empty(
            "Live quote",
            f"live quote omitted for {symbol}: this request is as of {as_of.isoformat()}, a past "
            "date, and a historical view must not see the current market",
        )
    if not settings.paperlive_enabled:
        return _empty(
            "Live quote",
            f"live quote unavailable for {symbol}: live quotes are disabled "
            "(INVDASH_PAPERLIVE_ENABLED=0)",
        )

    try:
        quote, snap = livefeed.latest_with_snapshot(symbol)
    except Exception as exc:  # pragma: no cover - livefeed is fail-soft; defensive only
        return _empty("Live quote", f"live quote unavailable for {symbol}: {type(exc).__name__}: {exc}")

    if quote is None:
        detail = ""
        if snap is not None:
            reasons = [e.message for e in snap.errors if e.symbol == symbol.upper()]
            if reasons:
                detail = f": {reasons[0]}"
        return _empty("Live quote", f"no live quote available for {symbol}{detail}")

    # `transport` is how *this process* got the quote ("poll"/"stream"), which is the provenance a
    # reader of a live figure actually needs; `LiveQuote.source` ("yahoo") is the upstream behind it.
    transport = snap.transport if snap is not None else quote.source
    market_state = snap.market_state if snap is not None else "UNKNOWN"
    ts = quote.ts.isoformat()
    age_seconds = max(int((dt.datetime.now(dt.UTC) - quote.ts).total_seconds()), 0)

    items: list[EvidenceItem] = [
        EvidenceItem(key="price", label="Last price", value=f"{quote.price:.2f}", unit="USD", as_of=ts, source=transport),
    ]
    if quote.previous_close is not None:
        items.append(
            EvidenceItem(
                key="previous_close", label="Previous close", value=f"{quote.previous_close:.2f}",
                unit="USD", as_of=ts, source=transport,
            )
        )
    if quote.change is not None:
        items.append(
            EvidenceItem(
                key="change", label="Change on the day", value=f"{quote.change:.2f}", unit="USD",
                as_of=ts, source=transport,
            )
        )
    if quote.change_pct is not None:
        # Carried at the four decimals `app.market.live._percent` produces rather than rounded to two
        # here: `app.agentdesk.grounding` admits a *coarser* restatement of a grounded figure and not
        # a finer one, so storing the full precision is what lets a stage write "up 1.2%" or "1.20%"
        # and pass, while storing "1.20" would reject the underlying "1.2018".
        items.append(
            EvidenceItem(
                key="change_pct", label="Change on the day", value=f"{quote.change_pct:.4f}",
                unit="%", as_of=ts, source=transport,
            )
        )
    items.append(
        EvidenceItem(key="market_state", label="Market state", value=market_state, as_of=ts, source=transport)
    )
    items.append(
        EvidenceItem(
            key="quote_age_seconds", label="Quote age", value=str(age_seconds), unit="seconds",
            as_of=ts, source=transport,
        )
    )

    staleness = (
        "The feed reports this quote as STALE -- it has not refreshed recently, so treat it as an "
        "upper bound on freshness, not as the current market."
        if quote.stale
        else "The feed reports this quote as current."
    )
    text = (
        f"Live quote for {symbol}, taken at {ts} (transport {transport}, market state "
        f"{market_state}). {staleness}"
    )
    return EvidenceSection(title="Live quote", items=tuple(items), text=text), ()


def live_quote_evidence(symbol: str, as_of: dt.date | None, *, settings: Settings) -> EvidenceSection:
    section, _warnings = _live_quote_evidence(symbol, as_of, settings=settings)
    return section


def _intraday_evidence(
    symbol: str, as_of: dt.date | None, *, settings: Settings, bars: int = 24
) -> tuple[EvidenceSection, tuple[str, ...]]:
    if _is_historical(as_of):
        assert as_of is not None  # _is_historical is False for None
        return _empty(
            "Intraday",
            f"intraday bars omitted for {symbol}: this request is as of {as_of.isoformat()}, a past "
            "date, and a historical view must not see the current session",
        )
    if bars < 1:
        return _empty("Intraday", f"intraday bars omitted for {symbol}: {bars} bars requested")

    warnings: list[str] = []
    reference = as_of or dt.date.today()
    start = reference - dt.timedelta(days=_INTRADAY_LOOKBACK_DAYS)

    try:
        series = store.ensure_series(symbol, Interval.FIVE_MIN, start=start, end=as_of, settings=settings)
    except ProviderError as exc:
        return _empty("Intraday", f"intraday bars unavailable for {symbol}: {exc}")
    except Exception as exc:  # pragma: no cover - defensive; the data layer types its own failures
        return _empty("Intraday", f"intraday bars unavailable for {symbol}: {type(exc).__name__}: {exc}")

    warnings.extend(f"{symbol} intraday: {w.message}" for w in series.warnings)
    if not series.bars:
        warnings.append(f"intraday bars unavailable for {symbol}: the store returned no 5-minute bars")
        return EvidenceSection(title="Intraday"), tuple(warnings)

    # The newest session present, not "today": before the open, on a weekend, or on a holiday the
    # newest 5-minute bars are the previous session's, and reporting them *labelled as* the previous
    # session is far more useful than reporting nothing. Grouped by UTC date, which is the same
    # calendar day as the session for every US listing this application prices (a US regular session
    # runs 13:30-20:00 UTC); a venue whose session straddles UTC midnight would split here.
    session = series.bars[-1].ts.date()
    session_bars = [bar for bar in series.bars if bar.ts.date() == session]
    recent = session_bars[-bars:]
    if session != dt.datetime.now(dt.UTC).date():
        warnings.append(
            f"{symbol} intraday: the newest 5-minute bars are from the {session.isoformat()} "
            "session, not today -- the market has not traded since"
        )

    source = series.source.value
    last = recent[-1]
    last_ts = last.ts.isoformat()
    items: list[EvidenceItem] = [
        EvidenceItem(key="last_close", label="Last 5-minute close", value=f"{last.close:.2f}", unit="USD", as_of=last_ts, source=source),
        EvidenceItem(key="session_high", label="Session high", value=f"{max(b.high for b in recent):.2f}", unit="USD", as_of=last_ts, source=source),
        EvidenceItem(key="session_low", label="Session low", value=f"{min(b.low for b in recent):.2f}", unit="USD", as_of=last_ts, source=source),
        EvidenceItem(key="bar_count", label="Bars in window", value=str(len(recent)), unit="bars", as_of=last_ts, source=source),
    ]
    volumes = [bar.volume for bar in recent]
    if all(volume is not None for volume in volumes):
        # Only when *every* bar reports one. Summing a window with a `None` in it would silently
        # report a partial total as the session's volume, which is worse than not reporting it.
        items.insert(
            3,
            EvidenceItem(
                key="session_volume", label="Volume over the window",
                value=str(sum(volume for volume in volumes if volume is not None)), unit="shares",
                as_of=last_ts, source=source,
            ),
        )
    else:
        warnings.append(f"{symbol} intraday: at least one bar in the window reports no volume, so no total is given")

    # No VWAP: a correct one is sum(price * volume) / sum(volume), and the window above may have bars
    # with no volume at all -- a mean of closes computed in its place and labelled "VWAP-ish" would be
    # a number that does not mean what its label says, which is precisely what this layer exists to
    # prevent. Omitted rather than approximated.
    table = [
        f"Last {min(len(recent), _INTRADAY_TABLE_BARS)} five-minute bars of the "
        f"{session.isoformat()} session, oldest first, times in UTC. These lines are context: quote "
        "only the figures in the items above."
    ]
    for bar in recent[-_INTRADAY_TABLE_BARS:]:
        table.append(
            f"- {bar.ts.strftime('%H:%M')} open {bar.open:.2f} high {bar.high:.2f} "
            f"low {bar.low:.2f} close {bar.close:.2f}"
        )

    return EvidenceSection(title="Intraday", items=tuple(items), text="\n".join(table)), tuple(warnings)


def intraday_evidence(
    symbol: str, as_of: dt.date | None, *, settings: Settings, bars: int = 24
) -> EvidenceSection:
    section, _warnings = _intraday_evidence(symbol, as_of, settings=settings, bars=bars)
    return section


# ---------------------------------------------------------------------------
# Assembly and rendering
# ---------------------------------------------------------------------------

_BUILDERS = {
    "price": lambda symbol, as_of, settings: _price_evidence(symbol, as_of, settings=settings),
    "indicators": lambda symbol, as_of, settings: _indicator_evidence(symbol, as_of, settings=settings),
    "news": lambda symbol, as_of, settings: _news_evidence(symbol, settings=settings),
    "social": lambda symbol, as_of, settings: _social_evidence(symbol, settings=settings),
    "fundamentals": lambda symbol, as_of, settings: _fundamentals_evidence(symbol, settings=settings),
    "macro": lambda symbol, as_of, settings: _macro_evidence(settings=settings),
    "events": lambda symbol, as_of, settings: _events_evidence(symbol, settings=settings),
    "live_quote": lambda symbol, as_of, settings: _live_quote_evidence(symbol, as_of, settings=settings),
    "intraday": lambda symbol, as_of, settings: _intraday_evidence(symbol, as_of, settings=settings),
}


def build_pack(symbol: str, as_of: dt.date | None, *, settings: Settings, sections: Sequence[str]) -> EvidencePack:
    """Every requested section, assembled in the order given, with every builder's warnings folded in.

    `sections` must be drawn from :data:`SECTION_KEYS` -- an unknown key is a caller bug (a stage
    configured against a section this module cannot build) and raises immediately rather than being
    skipped, which would silently hand a stage fewer facts than its prompt claims it has.
    """
    unknown = [key for key in sections if key not in SECTION_KEYS]
    if unknown:
        raise ValueError(
            f"unknown evidence section(s): {', '.join(unknown)}; available: {', '.join(SECTION_KEYS)}"
        )

    built: list[EvidenceSection] = []
    warnings: list[str] = []
    for key in sections:
        section, section_warnings = _BUILDERS[key](symbol, as_of, settings)
        built.append(section)
        warnings.extend(section_warnings)

    return EvidencePack(symbol=symbol, as_of=as_of, sections=tuple(built), warnings=tuple(warnings))


def render_pack(pack: EvidencePack) -> str:
    """The markdown a stage actually reads, and the exact text `app.agentdesk.grounding.check` and
    `grounded_values` are validated against reading back out.

    Every item renders as `- Label: value unit (as of ..., source ...)`; a section's free `text` block
    follows verbatim. An empty pack gets the literal anti-fabrication sentence this feature exists to
    enforce -- see `EvidencePack.is_empty`'s own docstring -- and every collected warning renders last,
    under its own heading, so a reader (and the model) can see exactly what could not be fetched.
    """
    lines: list[str] = []
    for section in pack.sections:
        lines.append(f"## {section.title}")
        for item in section.items:
            meta_bits = []
            if item.as_of:
                meta_bits.append(f"as of {item.as_of}")
            if item.source:
                meta_bits.append(f"source {item.source}")
            meta = f" ({', '.join(meta_bits)})" if meta_bits else ""
            unit = f" {item.unit}" if item.unit else ""
            lines.append(f"- {item.label}: {item.value}{unit}{meta}")
        if section.text:
            lines.append(section.text)
        lines.append("")

    if pack.is_empty:
        lines.append(
            "No usable data was retrieved for this request. Do not estimate or fabricate values -- "
            "report that data is unavailable."
        )
        lines.append("")

    if pack.warnings:
        lines.append("## Warnings")
        lines.extend(f"- {warning}" for warning in pack.warnings)
        lines.append("")

    return "\n".join(lines).strip() + "\n"
