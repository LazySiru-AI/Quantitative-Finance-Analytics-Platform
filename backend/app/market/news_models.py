"""News, social-sentiment and event-market observations: what a provider is allowed to return.

Parallel to :mod:`app.market.macro_models`, and separate from :mod:`app.market.models` for the same
reason that one is separate: these are not price observations, they carry different time semantics,
and mixing them into the bar/quote module would put three unrelated vocabularies in one namespace.

**The governing rule for everything in this module.** Per
``strategy-program/AGENTS-INTEGRATION-PLAN.md`` §0, an agent may never emit a number -- so a provider
may only report what it *counted*, never what it *concluded*. That is why
:class:`SocialSnapshot` carries ``bullish``/``bearish``/``neutral`` as integer message counts and has
no ``score`` field: a bull ratio is a division this codebase can do, show its inputs for, and put in
a :class:`~app.report.models.FactBundle`; a "sentiment score" is a number whose derivation lives in
whatever produced it. Vibe-Trading's ``sentiment`` tool is the cautionary case -- a unigram lexicon
that emits a confident ``[-1, 1]`` float, with ``"low"`` in both its positive and negative word sets,
so every occurrence of that word inflates the denominator and silently dilutes the result. Nothing
downstream of a bare float can detect that. Counts survive the same mistake, because a reader can
see them.

**Time is an instant here, not a date.** :mod:`app.market.macro_models` uses ``dt.date`` because "a
macro observation is a date, not an instant". News is the opposite: an article published at 09:31 and
one published at 16:05 sit on opposite sides of a session, and an event study that cannot tell them
apart has already lost the thing it was measuring. Every timestamp below is a timezone-aware
``dt.datetime`` in UTC, and :func:`published_before` is the only sanctioned way to bound a feed --
see its docstring for why a naive comparison is a look-ahead bug rather than a style preference.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.market.models import MarketWarning

__all__ = [
    "EventMarket",
    "MacroNewsPanel",
    "NewsFeed",
    "NewsItem",
    "NewsVolumePoint",
    "NewsVolumeSeries",
    "SocialSnapshot",
    "SocialSummary",
    "TickerNewsPanel",
    "merge_feeds",
    "published_before",
]

#: Every `url` field on a wire model reachable from an upstream provider or a caller-supplied
#: request must pass through this. See `NewsItem.url`'s own docstring: a `javascript:` or `data:`
#: scheme rendered as a clickable link in the frontend would execute in the reader's browser, not
#: open an article. Case-insensitive and checked after stripping, since a scheme is not
#: case-sensitive and upstream feeds are not consistent about surrounding whitespace.
_ALLOWED_URL_SCHEMES = ("http://", "https://")


def _require_http_url(value: str) -> str:
    stripped = value.strip()
    if not stripped.lower().startswith(_ALLOWED_URL_SCHEMES):
        raise ValueError(
            f"url must start with http:// or https://, got {value!r}"
        )
    return stripped


class NewsItem(BaseModel):
    """One article, as some upstream reported it.

    ``summary`` is whatever the upstream supplied and is frequently ``None`` -- Reddit's RSS carries
    no body worth keeping, and GDELT returns headline metadata only. It is never synthesised here.
    """

    model_config = ConfigDict(frozen=True)

    title: str
    url: str
    """Must be `http://` or `https://` -- enforced below. A `javascript:` or `data:` URL rendered as
    a link by the frontend would execute in the reader's browser rather than open an article; every
    provider constructing a `NewsItem` from upstream data is expected to catch the resulting
    `ValidationError` and drop that one item rather than fail the whole feed (see e.g.
    `app.market.providers.yahoo_news`, `.gdelt`, `.reddit`)."""
    published: dt.datetime
    """Timezone-aware UTC. A provider that receives a naive timestamp must attach the upstream's
    documented zone before constructing this -- never assume local time, which silently shifts every
    article by the developer's own offset and is invisible in the output."""
    source: str
    """The provider ``name`` that fetched it (``yahoo_news``, ``gdelt``, ``reddit``), so a mixed feed
    can say where each row came from. Not the publisher."""
    publisher: str | None = None
    """The outlet, when the upstream names one (``Reuters``, ``r/stocks``). Distinct from
    ``source``: the provider is how we got it, the publisher is who wrote it."""
    summary: str | None = None

    @field_validator("url")
    @classmethod
    def _url_is_http(cls, value: str) -> str:
        return _require_http_url(value)


class SocialSnapshot(BaseModel):
    """Message counts for one symbol over one window. **Counts only -- deliberately no score.**

    See the module docstring. ``bullish``/``bearish`` are the upstream's *own* labels where it has
    them (StockTwits lets a poster tag a message), and ``neutral`` is every message that carried no
    label. Nothing in this class infers a label from text.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    source: str
    as_of: dt.datetime
    """Timezone-aware UTC: when the snapshot was taken, not when the newest message was posted."""
    window_start: dt.datetime | None = None
    """Oldest message the snapshot covers, when the upstream lets us know. ``None`` means the window
    is whatever the endpoint chose to return, which is itself worth surfacing rather than hiding
    behind an assumed lookback."""
    bullish: int = Field(ge=0)
    bearish: int = Field(ge=0)
    neutral: int = Field(ge=0)
    """Messages the upstream returned with no directional label. Not "unknown sentiment" -- unlabelled
    is the majority case on every stream measured here, and folding it into either side would be an
    invented number."""

    @property
    def total(self) -> int:
        """Every message in the window, labelled or not."""
        return self.bullish + self.bearish + self.neutral

    @property
    def labelled(self) -> int:
        """Only the messages that carried a direction -- the denominator a bull ratio actually wants."""
        return self.bullish + self.bearish


class NewsVolumePoint(BaseModel):
    """How many articles matched a query on one day, and how many the upstream indexed in total.

    **Two counts, never their ratio.** The module docstring's rule applies here exactly as it does to
    :class:`SocialSnapshot`: ``matched / indexed_total`` is the number a study actually wants -- an
    attention *share*, which survives the fact that GDELT's whole corpus grows year over year -- but it
    is a division this codebase performs, shows its inputs for, and can be argued with. Storing the
    quotient instead would discard the denominator, and a reader could no longer tell a genuine spike
    in coverage from a quiet day early in the archive when GDELT was monitoring a tenth as much.

    **A date, not an instant, and this is the one place news is allowed to be.** Everything else in
    this module is a timezone-aware ``dt.datetime`` because an article at 09:31 and one at 16:05 sit
    on opposite sides of a session. A volume *series* is different: the upstream aggregates into daily
    buckets before we ever see it, so there is no instant left to preserve and pretending otherwise --
    by pinning every bucket to midnight and typing it as a datetime -- would invent a precision the
    data does not have. A caller aligning this to sessions must decide its own convention for which
    trading day a UTC bucket belongs to, and say so.
    """

    model_config = ConfigDict(frozen=True)

    day: dt.date
    """The upstream's own daily bucket, in UTC."""
    matched: int = Field(ge=0)
    """Articles matching the query in that bucket -- GDELT's ``value``."""
    indexed_total: int = Field(ge=0)
    """Every article the upstream indexed in that bucket, matching or not -- GDELT's ``norm``. The
    denominator, kept so the share above can be derived rather than asserted."""


class NewsVolumeSeries(BaseModel):
    """A daily news-volume history for one query, plus enough about the upstream's own coverage that
    an empty stretch cannot be mistaken for a quiet one.

    This is the news half of what ``strategy-program/AGENTS-INTEGRATION-PLAN.md`` Phase D calls
    **D-news**, and it carries the same coverage guard
    :class:`app.market.social_history.SocialHistoryRange` does, for the same reason stated there: a
    caller who asks for 2011 must not receive an empty, silent answer that reads identically to
    "no news matched in 2011" when the true answer is "this archive does not go back that far."

    The distinction matters more here than it does for the social store, because the boundary is not a
    local file's start date that grows every day -- it is a fixed property of the upstream, and it sits
    in the middle of this programme's window matrix rather than before it. See
    :data:`app.market.providers.gdelt.COVERAGE_START`.
    """

    model_config = ConfigDict(frozen=True)

    query: str
    source: str
    """The provider ``name`` that produced it, matching :attr:`NewsItem.source`."""
    points: tuple[NewsVolumePoint, ...] = ()
    """Ordered oldest to newest. Empty is a legitimate answer and is not, on its own, a failure --
    read it together with :attr:`requested_start_before_coverage`."""
    coverage_start: dt.date
    """The earliest day this upstream can answer for at all, irrespective of what was requested."""
    requested_start: dt.date
    """What the caller actually asked for, kept verbatim so the comparison below is auditable rather
    than something the caller has to reconstruct."""

    @property
    def requested_start_before_coverage(self) -> bool:
        """`True` when the caller asked for history predating the archive itself.

        A caller reading this as `True` knows that a short or empty :attr:`points` is a coverage gap
        rather than a measurement, and -- critically for a study that reports across a window matrix --
        that this window cannot be counted as *run*.
        """
        return self.requested_start < self.coverage_start

    @property
    def covered_days(self) -> int:
        """How many daily buckets actually came back. The sample size a claim about this series rests
        on, and the number to report next to any q-value derived from it."""
        return len(self.points)


class EventMarket(BaseModel):
    """One prediction market's current pricing.

    ``probability`` is the only float here that is not a count, and it is passed through from the
    upstream rather than derived: it is the market's own mid price, which is a reported observation
    in exactly the way a closing price is.
    """

    model_config = ConfigDict(frozen=True)

    question: str
    slug: str
    source: str
    as_of: dt.datetime
    probability: float = Field(ge=0.0, le=1.0)
    volume: float | None = None
    resolution_date: dt.date | None = None
    """A date, not an instant -- resolution is scheduled by day. ``None`` when the upstream has not
    committed to one."""


class NewsFeed(BaseModel):
    """A provider's answer for one query, with whatever it needs to caveat about it.

    Carries ``warnings`` for the same reason :class:`~app.market.models.BarSeries` does: a feed that
    came back short, throttled, or from the second provider in a chain must be able to say so without
    the caller having to guess from a row count.
    """

    model_config = ConfigDict(frozen=True)

    items: tuple[NewsItem, ...] = ()
    source: str = ""
    as_of: dt.datetime | None = None
    warnings: tuple[MarketWarning, ...] = ()


def published_before[ItemT: NewsItem](
    items: Iterable[ItemT], as_of: dt.datetime | None
) -> tuple[ItemT, ...]:
    """Keep only items published at or before ``as_of``. **This is a look-ahead guard, not a filter.**

    Every news read that feeds a backtest or an event study must pass through here. The failure it
    prevents is the worst kind this codebase has: an article published the afternoon of the move,
    included in the window that was supposed to predict the move, produces a signal that is real,
    reproducible, statistically significant, and worth nothing -- and there is no way to see it in
    the output. `app/backtest/guards.py` guards the bar store the same way and for the same reason.

    ``as_of=None`` means "live, no bound" and returns everything. That default is safe only because
    the caller who wants a bound is the one who has it; a provider cannot know whether it is being
    read live or as of 2019.

    A naive ``as_of`` is rejected rather than coerced. Comparing a naive datetime to the
    timezone-aware ``published`` raises ``TypeError`` in Python anyway; catching it here turns an
    obscure traceback from inside a comprehension into a sentence naming the actual mistake.
    """
    if as_of is None:
        return tuple(items)
    if as_of.tzinfo is None:
        raise ValueError(
            "as_of must be timezone-aware: a naive bound cannot be compared to a UTC publication "
            "time, and assuming local time shifts the cutoff by the developer's own offset."
        )
    return tuple(item for item in items if item.published <= as_of)


def merge_feeds(feeds: Sequence[NewsFeed], *, limit: int | None = None) -> tuple[NewsItem, ...]:
    """Interleave several providers' items into one newest-first list, de-duplicated by URL.

    De-duplication is by exact ``url`` and nothing cleverer. Yahoo and GDELT both index the same
    wire stories, so the same article genuinely arrives twice with an identical link often enough to
    be worth collapsing -- but two links that differ by a tracking parameter are left as two rows
    rather than guessed at, because a title-similarity match would silently drop a genuine follow-up
    story that reused its predecessor's headline.
    """
    seen: set[str] = set()
    merged: list[NewsItem] = []
    for item in sorted(
        (item for feed in feeds for item in feed.items),
        key=lambda i: i.published,
        reverse=True,
    ):
        if item.url in seen:
            continue
        seen.add(item.url)
        merged.append(item)
        if limit is not None and len(merged) >= limit:
            break
    return tuple(merged)


# --- API response shapes ---------------------------------------------------------------------
#
# These are what `app.market.news` builds and `app.api.news` returns. They live here rather than in
# the service module so the frontend's TypeScript types and the service's construction site have one
# definition between them, and so a provider author can see the shape their data ends up in.
#
# **They cannot fail.** `app.market.macro.build_snapshot` set the precedent and the reasoning is
# identical: a dead upstream degrades its own section and the endpoint still answers 200. A news
# panel that 500s because StockTwits is having a bad afternoon takes the headlines down with it, and
# the reader loses two working sections to one broken one. Absence is rendered as an empty section
# plus a warning that names which upstream failed and why -- never as an exception reaching the
# router, and never as a silently empty list that looks like "no news today".


class SocialSummary(BaseModel):
    """A :class:`SocialSnapshot` plus the ratios a reader actually wants, computed once, here.

    **This is the only place a ratio is allowed to be derived, and it is derived, not modelled.**
    ``bull_ratio`` is ``bullish / labelled`` -- explicitly over the *labelled* denominator, not the
    total -- because those are two very different numbers and the difference is the whole reason
    :class:`SocialSnapshot` keeps ``neutral`` separate. On the captured StockTwits fixture, 8 of 12
    messages carry no label at all: a "67% neutral" reading and a "50% bullish among those who said"
    reading describe the same stream, and only one of them is about sentiment.

    Both denominators are therefore published side by side, and ``bull_ratio`` is ``None`` -- never
    ``0.5``, never ``0.0`` -- when nothing was labelled. A default would be a number nobody measured.
    """

    model_config = ConfigDict(frozen=True)

    snapshot: SocialSnapshot
    bull_ratio: float | None = None
    """``bullish / (bullish + bearish)``. ``None`` when no message carried a label."""
    labelled_share: float | None = None
    """``(bullish + bearish) / total`` -- how much of the stream expressed a direction at all.
    ``None`` when the window was empty. Read this before ``bull_ratio``: a bull ratio computed over
    four messages out of twelve is a fact about four messages."""

    @classmethod
    def of(cls, snapshot: SocialSnapshot) -> SocialSummary:
        labelled = snapshot.labelled
        total = snapshot.total
        return cls(
            snapshot=snapshot,
            bull_ratio=(snapshot.bullish / labelled) if labelled else None,
            labelled_share=(labelled / total) if total else None,
        )


class TickerNewsPanel(BaseModel):
    """Everything the Ticker page's News & Sentiment panel needs, in one request.

    One request rather than three so the panel's sections cannot disagree about what "now" means --
    the same reasoning `GET /api/macro/snapshot` is built on.
    """

    model_config = ConfigDict(frozen=True)

    symbol: str
    generated_at: dt.datetime
    as_of: dt.datetime | None = None
    news: tuple[NewsItem, ...] = ()
    news_source: str | None = None
    """Which provider in the chain actually answered. ``None`` when none could."""
    social: SocialSummary | None = None
    """``None`` when no social provider could answer -- with a warning saying so. Not an empty
    snapshot, which would read as "nobody is talking about this" rather than "we could not ask"."""
    warnings: tuple[MarketWarning, ...] = ()


class MacroNewsPanel(BaseModel):
    """Global headlines and prediction-market pricing for the Macro page."""

    model_config = ConfigDict(frozen=True)

    generated_at: dt.datetime
    as_of: dt.datetime | None = None
    query: str = ""
    news: tuple[NewsItem, ...] = ()
    news_source: str | None = None
    events: tuple[EventMarket, ...] = ()
    warnings: tuple[MarketWarning, ...] = ()
