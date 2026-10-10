"""Bridges news and social observations into the report's only vocabulary for numbers: facts.

:mod:`app.report.narrative` refuses every bare numeral in prose -- a sentence may only say a number
by citing a ``{{fact:id}}`` that resolves in the bundle. Nothing about that rule cares where a fact
came from; a count of articles or a count of bullish StockTwits messages is exactly as citable as a
drawdown depth, provided something has counted it and stamped it with a source. This module is that
something for :mod:`app.market.news_models`'s inputs -- it is the builder's counterpart for the news
and sentiment panel the way ``app.report.builder`` is the counterpart for the backtest engines, kept
separate because it draws from a different vocabulary (:class:`~app.market.news_models.NewsItem`,
:class:`~app.market.news_models.SocialSnapshot`) with its own timing and honesty rules.

**``None`` over a default, always.** ``strategy-program/AGENTS-INTEGRATION-PLAN.md`` §0 is explicit
that an agent -- and everything upstream of it -- may report what was counted, never what it
concluded, and that discipline extends to what happens when nothing *could* be counted. On the
captured StockTwits fixture, 8 of 12 messages carry no directional label at all, so a bull ratio
computed only over the 4 that do is a fact about 4 messages, not 12 -- and when zero messages carry
a label, the honest ratio is undefined, not 0.5 and not 0.0. Silently substituting either would put
a number in the report that nobody measured, dressed up as one that was. ``Fact.value`` already
blesses ``None`` as a first-class outcome -- it renders as an em dash and remains citable -- precisely
so that "we could not measure this" is a sentence the report can make, rather than a sentence that
quietly disappears.

**A missing section is still a row of facts, not an absent one.** When
:attr:`~app.market.news_models.TickerNewsPanel.social` is ``None`` -- the provider did not answer --
this module still emits every ``sentiment.*`` id, each with ``value=None``. The distinction matters
downstream: ``narrative._sentence`` drops a sentence outright when a fact id it needs is absent from
the bundle, but renders "—" for a fact id that is present with a ``None`` value only when the template
was written to say so. An absent id makes a report that reads the same whether sentiment could not be
reached or the section was simply never wired up; a present-but-``None`` fact makes the report capable
of saying, explicitly, that a provider was asked and had nothing to answer with.

**No fact here is a judgement.** Counts, ratios of counts, and elapsed time only -- never a mood, a
signal, or a verdict string. The moment this module started deriving `sentiment.mood` from a ratio
it would have crossed from reporting an observation to reporting a conclusion, and conclusions belong
to whatever reads the bundle downstream, not to the layer that assembles it.
"""

from __future__ import annotations

import datetime as dt

from app.market.news_models import SocialSnapshot, TickerNewsPanel
from app.report.models import Fact, FactKind

__all__ = ["news_facts"]


def _fact(
    fact_id: str,
    label: str,
    value: float | str | None,
    kind: FactKind,
    source: str,
    *,
    unit: str = "",
    as_of: dt.date | None = None,
) -> Fact:
    return Fact(
        id=fact_id, label=label, value=value, kind=kind, unit=unit, source=source, as_of=as_of
    )


def _news_source(panel: TickerNewsPanel) -> str:
    """Provider, symbol, and the actual span of articles held -- not just a bare count.

    Named after the provider that answered (:attr:`TickerNewsPanel.news_source`), which is ``None``
    when nothing did; an empty or absent feed still needs a re-derivable source string, so both cases
    are spelled out rather than left to look like a provider that returned nothing was never asked.
    """
    provider = panel.news_source or "no_provider"
    if not panel.news:
        return f"{provider}/{panel.symbol} 0 articles"
    published = [item.published for item in panel.news]
    span = f"{min(published).isoformat()}..{max(published).isoformat()}"
    return f"{provider}/{panel.symbol} {len(panel.news)} articles {span}"


def _news_facts(panel: TickerNewsPanel) -> list[Fact]:
    source = _news_source(panel)
    as_of = panel.generated_at.date()
    count = len(panel.news)

    newest_age_hours: float | None = None
    if panel.news:
        newest = max(item.published for item in panel.news)
        # Hours, not days: an article from nine hours ago and one from nine days ago read very
        # differently in a report about a fast-moving name, and coarsening to days would erase that
        # distinction for no reason -- the panel's own timestamps are already instants, not dates.
        newest_age_hours = (panel.generated_at - newest).total_seconds() / 3600.0

    return [
        _fact("news.count", "News articles", count, FactKind.COUNT, source, as_of=as_of),
        _fact(
            "news.newest_age_hours",
            # The unit belongs in the label because nothing else renders it. `Fact.unit` is carried
            # on the model but consumed by neither `narrative.format_fact` (which switches on `kind`
            # alone) nor `FactTable.tsx` -- so a `RATIO` fact renders as a bare `3.50`, and a reader
            # seeing "Newest article age: 3.50" has no way to know whether that is hours or days.
            # `unit="hours"` below stays as machine-readable metadata; this is the human-visible copy.
            "Newest article age (hours)",
            newest_age_hours,
            FactKind.RATIO,
            source,
            unit="hours",
            as_of=as_of,
        ),
    ]


def _sentiment_source(panel: TickerNewsPanel, snapshot: SocialSnapshot | None) -> str:
    """Provider, symbol, and the actual window -- re-derivable even when a piece of it is missing.

    ``window_start`` is legitimately ``None`` on a :class:`SocialSnapshot` -- the upstream did not
    say how far back it looked -- and that absence is itself worth surfacing in the source string
    rather than papered over with an assumed lookback, matching the reasoning in
    :class:`~app.market.news_models.SocialSnapshot`'s own docstring for why the field exists at all.
    """
    if snapshot is None:
        # No provider answered at all: there is no window to name, so the source says exactly that
        # instead of inventing a provider or a span that was never observed.
        return f"no_social_provider/{panel.symbol}"
    start = snapshot.window_start.isoformat() if snapshot.window_start is not None else "unspecified"
    return f"{snapshot.source}/{snapshot.symbol} {start}..{snapshot.as_of.isoformat()}"


def _sentiment_facts(panel: TickerNewsPanel) -> list[Fact]:
    """Every ``sentiment.*`` id, always -- with ``value=None`` wherever the panel has nothing to say.

    Built from ``panel.social`` when present and from an all-``None`` row when it is not, so the set
    of ids returned never depends on whether the social provider answered. See the module docstring's
    "A missing section is still a row of facts" for why that invariant is the point.
    """
    summary = panel.social
    snapshot = summary.snapshot if summary is not None else None
    source = _sentiment_source(panel, snapshot)
    as_of = snapshot.as_of.date() if snapshot is not None else None

    messages = snapshot.total if snapshot is not None else None
    labelled = snapshot.labelled if snapshot is not None else None
    bullish = snapshot.bullish if snapshot is not None else None
    bearish = snapshot.bearish if snapshot is not None else None
    neutral = snapshot.neutral if snapshot is not None else None
    # `bull_ratio`/`labelled_share` are taken from `SocialSummary`, not recomputed here -- it is
    # already the one place in the codebase permitted to derive a ratio (see its own docstring), and
    # it already applies the None-over-zero rule this module's docstring insists on. Recomputing them
    # here would be a second implementation of the same division to drift from the first.
    bull_ratio = summary.bull_ratio if summary is not None else None
    labelled_share = summary.labelled_share if summary is not None else None

    return [
        _fact(
            "sentiment.messages", "Social messages", messages, FactKind.COUNT, source, as_of=as_of
        ),
        _fact(
            "sentiment.labelled",
            "Labelled messages",
            labelled,
            FactKind.COUNT,
            source,
            as_of=as_of,
        ),
        _fact(
            "sentiment.bullish", "Bullish messages", bullish, FactKind.COUNT, source, as_of=as_of
        ),
        _fact(
            "sentiment.bearish", "Bearish messages", bearish, FactKind.COUNT, source, as_of=as_of
        ),
        _fact(
            "sentiment.neutral",
            "Unlabelled messages",
            neutral,
            FactKind.COUNT,
            source,
            as_of=as_of,
        ),
        _fact(
            "sentiment.bull_ratio",
            "Bullish share of labelled messages",
            bull_ratio,
            FactKind.PERCENT,
            source,
            as_of=as_of,
        ),
        _fact(
            "sentiment.labelled_share",
            "Labelled share of all messages",
            labelled_share,
            FactKind.PERCENT,
            source,
            as_of=as_of,
        ),
    ]


def news_facts(panel: TickerNewsPanel) -> dict[str, Fact]:
    """Transcribe one news-and-sentiment panel into citable facts, keyed by id.

    Mirrors :func:`app.report.builder.build_bundle`'s shape deliberately: this function computes
    nothing beyond counting and dividing what the panel already holds, so it can be merged straight
    into :attr:`~app.report.models.FactBundle.facts` by whichever caller assembles the full bundle.
    """
    facts = _news_facts(panel) + _sentiment_facts(panel)
    return {fact.id: fact for fact in facts}
