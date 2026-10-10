"""Which tickers the news is currently talking about -- a universe bias, never a score.

This module answers exactly one question: *of the symbols a purpose's pool already allows, which
ones does the news layer currently have coverage for, and how much?* It exists so the searcher in
`app.evolution.loop` can occasionally propose a genome built around a ticker that just became
newsworthy, rather than only ever recombining tickers a human already put in `app.evolution.universe`.
That is the entire job. It is not a signal generator.

**The governing rule, from `strategy-program/AGENTS-INTEGRATION-PLAN.md` section 0: "An agent may
propose, name, argue and select. An agent may never emit a number."** And from
`app.market.news_models`'s own module docstring: "a provider may only report what it counted, never
what it concluded." This module inherits both, one layer up. It never computes a sentiment score, a
signal strength, or a predicted return. `Attention.bull_ratio` is copied from
`app.market.news_models.SocialSummary` -- a number a provider already reported, not one this module
derives -- and every other field here is a plain count: how many articles came back, how many social
messages came back, which providers answered. Ordering that tuple of counts is the only "judgement"
this module performs, and even that judgement is `sorted()`, not a model.

**Nothing here is evidence that news attention predicts returns.** `AGENTS-INTEGRATION-PLAN.md`
section 4, Phase D ("measure before believing") is the pre-registered study that would establish
whether a news-volume spike or an extreme bull ratio carries any forward return after correction --
and as of this writing that phase has not run. Its social half cannot even be attempted yet: StockTwits
and Reddit serve only a live window with no historical query, so there is no sentiment history to test
against (see `app.market.social_history` and the Phase D section of the plan for the full account of
why). Until Phase D reports a result, `trending_symbols` is a way of choosing *what to test*, not a
reason to believe a candidate will do well. The genome it feeds records the tickers it was handed and
why (`Genome.notes`, `Genome.origin == "news"`); the loop's own leaderboard, built from
`app.tournament.results` off real backtest runs, is what decides -- exactly as always -- whether
testing that candidate was worth doing. News never touches scoring.

**Never raises.** Every provider call in this module goes through the same degrade-a-section contract
`app.market.news.build_ticker_panel` itself is built on: a symbol whose news chain is down, rate
limited, or simply offline gets an `Attention` with zero counts and an empty `sources` tuple, not an
exception. `rank_attention` and `trending_symbols` both need to run with the loop's single generation
budget, unattended, potentially with no network at all -- a searcher that dies because one ticker's
news chain hiccuped would be strictly worse than a searcher that never looked at the news.

**Caching.** `rank_attention` is called once per generation, and a wide candidate list times a
provider round trip per symbol is both slow and rude to the upstreams. Results are cached on disk
under `loop_root(settings)/news_cache/{date}.json`, keyed by symbol and the `as_of` bound the caller
asked for, so a loop iterating every few minutes does not re-hammer the same providers for the same
question. See `MAX_SYMBOLS_PROBED` and `CACHE_TTL` below for the two knobs that bound the work.

**Look-ahead honesty.** `as_of` is threaded straight through to `build_ticker_panel`, which threads it
straight through to the provider chain -- `app.market.providers.yahoo_news`, `.gdelt` and `.reddit`
all bound their own feeds via `app.market.news_models.published_before` before this module ever sees
the result, so a historical `as_of` here gets a historical news panel, not today's headlines relabelled.
Social is the one exception, and it is a real, documented gap rather than an oversight: `SocialProvider`
has no `as_of` parameter at all (see `app.market.providers.stocktwits`'s module docstring), so
`Attention.social_messages` and `Attention.bull_ratio` always reflect the *live* stream regardless of
what `as_of` was requested. A caller running this against a historical `as_of` gets an honest,
look-ahead-safe news count and a social count it should not trust for that date.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.config import Settings
from app.evolution.models import loop_root
from app.market.news import build_ticker_panel
from app.tournament.purposes import Purpose

__all__ = [
    "CACHE_TTL",
    "MAX_SYMBOLS_PROBED",
    "Attention",
    "provenance",
    "rank_attention",
    "trending_symbols",
]


#: How many candidate symbols one `rank_attention` call will probe. A generation's universe pool can
#: run well past this; probing all of it would mean one provider round trip per symbol on every
#: generation, which is both slow (the loop's own single-slot lock is already the dominant wait) and
#: an easy way to get an upstream to start rate-limiting the whole application. 24 is generous enough
#: to cover a purpose's whole growth+leveraged+satellite+stability pool in the common case while
#: staying well short of "one HTTP round trip per ticker in the market."
MAX_SYMBOLS_PROBED: Final[int] = 24

#: How long a cached `Attention` stays valid before `rank_attention` will re-probe its provider chain
#: for that symbol. Measured in hours rather than minutes because this runs once per generation and
#: news volume does not move fast enough within a single loop iteration to be worth re-fetching every
#: cycle; measured in hours rather than a full day because the entire point of this module is to
#: notice a symbol that became newly in play *today*, and a day-long cache would miss that until
#: tomorrow.
CACHE_TTL: Final[dt.timedelta] = dt.timedelta(hours=4)


@dataclass(frozen=True, slots=True)
class Attention:
    """One symbol's news-layer coverage, as counts -- never a conclusion about what the counts mean.

    Every field is either a count the provider chain reported, a list of who reported it, or a
    timestamp. There is no field for "how bullish" or "how strong" this attention is, because this
    module is not permitted to compute one -- see the module docstring.
    """

    symbol: str
    news_items: int
    """How many articles `app.market.news.build_ticker_panel` returned. Zero both when nothing was
    published and when the news chain was down -- the two are indistinguishable from here by design;
    `sources` is what tells them apart (empty means nothing answered)."""

    social_messages: int | None
    """`SocialSnapshot.total` for this symbol, or `None` when no social provider could answer at all.
    Deliberately never `0` standing in for "unknown" -- a provider that *answered* with zero messages
    is a different fact from a provider that never answered, and only the first one is `0` here."""

    bull_ratio: float | None
    """Copied verbatim from `app.market.news_models.SocialSummary.bull_ratio`. Never derived in this
    module -- see that class's own docstring for why it is `None` rather than a default whenever
    nothing was labelled."""

    sources: tuple[str, ...]
    """Which providers actually answered for this symbol (e.g. `("yahoo_news", "stocktwits")`).
    Empty when nothing did -- the marker for "we could not ask", distinct from a real zero count."""

    as_of: dt.datetime
    """The instant this attention describes: the caller's `as_of` bound when one was given (so a
    historical probe is stamped with the date it is honestly about), or the moment the panel was
    actually built when the call was live."""


def _normalise_symbols(symbols: Sequence[str], *, cap: int) -> tuple[str, ...]:
    """Upper-case, de-duplicate preserving first occurrence, and cap -- see `MAX_SYMBOLS_PROBED`."""
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in symbols:
        symbol = raw.strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        ordered.append(symbol)
        if len(ordered) >= cap:
            break
    return tuple(ordered)


def _as_of_key(as_of: dt.datetime | None) -> str | None:
    return as_of.isoformat() if as_of is not None else None


def _cache_path(settings: Settings, *, day: dt.date) -> Path:
    return loop_root(settings) / "news_cache" / f"{day.isoformat()}.json"


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    """The cache is disposable. Anything unreadable is treated as empty, never as a reason to fail."""
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    """Best-effort. A write failure (read-only filesystem, full disk) costs the next call a re-probe,
    not this call a crash -- caching is an optimisation, never a dependency of correctness here."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
    except OSError:
        pass


def _entry_to_attention(symbol: str, entry: dict[str, Any]) -> Attention | None:
    try:
        return Attention(
            symbol=symbol,
            news_items=int(entry["news_items"]),
            social_messages=entry["social_messages"],
            bull_ratio=entry["bull_ratio"],
            sources=tuple(entry.get("sources", ())),
            as_of=dt.datetime.fromisoformat(entry["as_of"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _attention_to_entry(attention: Attention, *, as_of_key: str | None, cached_at: dt.datetime) -> dict[str, Any]:
    return {
        "news_items": attention.news_items,
        "social_messages": attention.social_messages,
        "bull_ratio": attention.bull_ratio,
        "sources": list(attention.sources),
        "as_of": attention.as_of.isoformat(),
        "as_of_key": as_of_key,
        "cached_at": cached_at.isoformat(),
    }


def _probe(symbol: str, *, settings: Settings, as_of: dt.datetime | None, now: dt.datetime) -> Attention:
    """One symbol's worth of `build_ticker_panel`, folded into an `Attention` that never raises.

    Catches every exception, not just `app.market.providers.base.ProviderError`. `build_ticker_panel`
    already promises never to let a `ProviderError` escape -- but this module's own promise is wider
    ("the loop must be able to run with no network at all"), and the cheapest way to keep that promise
    is to not trust an upstream contract this module does not own to hold under every failure mode a
    fully offline environment can produce.
    """
    try:
        panel = build_ticker_panel(settings, symbol, as_of=as_of)
    except Exception:
        return Attention(
            symbol=symbol,
            news_items=0,
            social_messages=None,
            bull_ratio=None,
            sources=(),
            as_of=as_of or now,
        )

    sources: list[str] = []
    if panel.news_source:
        sources.append(panel.news_source)

    social_messages: int | None = None
    bull_ratio: float | None = None
    if panel.social is not None:
        social_messages = panel.social.snapshot.total
        bull_ratio = panel.social.bull_ratio
        if panel.social.snapshot.source not in sources:
            sources.append(panel.social.snapshot.source)

    return Attention(
        symbol=symbol,
        news_items=len(panel.news),
        social_messages=social_messages,
        bull_ratio=bull_ratio,
        sources=tuple(sources),
        as_of=as_of if as_of is not None else panel.generated_at,
    )


def rank_attention(
    *,
    symbols: Sequence[str],
    settings: Settings,
    as_of: dt.datetime | None = None,
) -> tuple[Attention, ...]:
    """Probe `symbols` for news-layer coverage and return them ordered by how much there is.

    Ordering is `news_items` descending, then `social_messages` descending (a missing social count
    sorts as if it were zero, never ahead of a real zero), then `symbol` ascending -- a fixed,
    deterministic tiebreak so that two runs against an identical (cached or live) answer set always
    produce the same order, which matters for `Genome.genome_id_for`'s content-addressing upstream.

    Bounded to at most `MAX_SYMBOLS_PROBED` symbols (deduplicated, upper-cased, first-occurrence
    order preserved before the cap is applied) and backed by an on-disk cache under
    `loop_root(settings)/news_cache/` -- see `CACHE_TTL`. Never raises: a candidate whose provider
    chain is down, or entirely absent, comes back as a zero-count `Attention`, not an exception.
    """
    now = dt.datetime.now(dt.UTC)
    probe_symbols = _normalise_symbols(symbols, cap=MAX_SYMBOLS_PROBED)
    if not probe_symbols:
        return ()

    day = (as_of or now).date()
    cache_path = _cache_path(settings, day=day)
    cache = _load_cache(cache_path)
    as_of_key = _as_of_key(as_of)

    results: dict[str, Attention] = {}
    cache_dirty = False

    for symbol in probe_symbols:
        cached_entry = cache.get(symbol)
        reused: Attention | None = None
        if cached_entry is not None and cached_entry.get("as_of_key") == as_of_key:
            cached_at_raw = cached_entry.get("cached_at")
            cached_at = None
            if isinstance(cached_at_raw, str):
                try:
                    cached_at = dt.datetime.fromisoformat(cached_at_raw)
                except ValueError:
                    cached_at = None
            if cached_at is not None and (now - cached_at) < CACHE_TTL:
                reused = _entry_to_attention(symbol, cached_entry)

        if reused is not None:
            results[symbol] = reused
            continue

        attention = _probe(symbol, settings=settings, as_of=as_of, now=now)
        results[symbol] = attention
        cache[symbol] = _attention_to_entry(attention, as_of_key=as_of_key, cached_at=now)
        cache_dirty = True

    if cache_dirty:
        _save_cache(cache_path, cache)

    ordered = sorted(
        results.values(),
        key=lambda a: (-a.news_items, -(a.social_messages or 0), a.symbol),
    )
    return tuple(ordered)


def _has_coverage(attention: Attention) -> bool:
    """Whether a provider actually reported *something* for this symbol -- the filter that keeps
    `trending_symbols` from returning an alphabetical shrug when every candidate came back at zero."""
    return attention.news_items > 0 or bool(attention.social_messages)


def trending_symbols(
    *,
    purpose: Purpose,
    settings: Settings,
    limit: int = 8,
    candidates: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """The `limit` most-covered symbols a `purpose`'s pool allows, most-covered first.

    `candidates` defaults to `None`, which resolves the pool via
    `app.evolution.universe.pool_for(purpose).all_symbols()` -- imported lazily inside this function
    because `app.evolution.universe` is written by a different worker in this phase and may not exist
    yet on disk while this module is developed or tested. Passing `candidates` explicitly (as every
    test in this suite does) bypasses that import entirely, and is also how a caller keeps a Roth
    loop's candidate list confined to `Pool.all_symbols()` for `Purpose.ROTH` and never sees a taxable
    ticker, or vice versa -- `pool_for` is what enforces that partition, this function only consumes
    its output.

    Never raises. Returns `()` when there are no candidates, when every candidate probed to zero
    coverage (see `_has_coverage`), or when the probe itself failed outright -- "nothing is currently
    in play" and "we could not tell" are both honestly reported as an empty tuple, because a caller
    biasing generation composition on this result treats absence the same way either way: fall back
    to the pool's own tickers.
    """
    if candidates is None:
        from app.evolution.universe import pool_for

        pool = pool_for(purpose)
        candidates = pool.all_symbols()

    if not candidates:
        return ()

    try:
        ranked = rank_attention(symbols=candidates, settings=settings)
    except Exception:
        return ()

    covered = tuple(attention.symbol for attention in ranked if _has_coverage(attention))
    return covered[:limit]


def provenance(attention: Attention) -> str:
    """One line saying why a symbol was chosen -- counts only, no conclusion.

    For a genome whose universe was biased by `trending_symbols`, this is what `Genome.notes` should
    record: it names what was measured (how many articles, how many social messages, who answered,
    as of when) and never what that implies about the symbol's prospects. Compare
    `strategy-program/AGENTS-INTEGRATION-PLAN.md` section 0: an agent -- and the genome it produces --
    "may propose, name, argue and select" but "may never emit a number" it did not simply copy from
    something that counted it. Example output::

        SMH: 14 news items, 212 social messages (yahoo_news, stocktwits), as of 2026-08-24T13:02Z
        QQQ: 0 news items (no source reported), as of 2026-08-24T13:02Z
    """
    news_plural = "" if attention.news_items == 1 else "s"
    bits = [f"{attention.news_items} news item{news_plural}"]
    if attention.social_messages is not None:
        social_plural = "" if attention.social_messages == 1 else "s"
        bits.append(f"{attention.social_messages} social message{social_plural}")

    source_note = f"({', '.join(attention.sources)})" if attention.sources else "(no source reported)"
    as_of_utc = attention.as_of.astimezone(dt.UTC)
    timestamp = as_of_utc.strftime("%Y-%m-%dT%H:%MZ")

    return f"{attention.symbol}: {', '.join(bits)} {source_note}, as of {timestamp}"
