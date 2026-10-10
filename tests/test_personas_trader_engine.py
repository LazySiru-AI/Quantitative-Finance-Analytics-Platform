"""Pure-helper tests for `app.personas.trader` -- the persona paper trader engine (Phase 10, built and
proven, not modified by this change).

**No model, no `SessionCalendar`, no network.** These tests exercise only the parts of the engine that
run without a grounded call or a market fetch: the candidate-universe builder (`_persona_universe`) and
the read-model reconstruction (`build_trader_book`), which is a pure function over a stored blob. The
service-layer tests (`tests/test_personas_trader_service.py`) cover `advance_one_decision`/
`backfill_trader` themselves, with the model call monkeypatched.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.config import Settings
from app.paper.mandate import default_mandate
from app.paper.paperbroker import PaperBroker
from app.personas import trader
from app.personas.models import EpisodicNote, Persona, TickerMention

NOW = dt.datetime(2026, 1, 10, 12, 0, tzinfo=dt.UTC)


def _persona(slug: str = "alpha") -> Persona:
    return Persona(slug=slug, display_name=slug.title(), created_at=NOW)


def _note(note_id: str, *, mentions: tuple[TickerMention, ...]) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona="alpha",
        source_id="yt:UCtest",
        published=NOW,
        ingested_at=NOW,
        url="https://www.youtube.com/watch?v=" + note_id,
        title=f"video {note_id}",
        kind="video_transcript",
        transcript_source="auto",
        lang="en",
        summary="a summary",
        mentions=mentions,
        path="",
    )


def _mention(symbol: str) -> TickerMention:
    return TickerMention(symbol=symbol, stance="bullish", reasoning="method signal")


# ---------------------------------------------------------------------------
# _persona_universe
# ---------------------------------------------------------------------------


def test_universe_keeps_held_names_even_when_not_mentioned(settings: Settings) -> None:
    """A held position must stay candidate so a decision can always sell it -- even a name the
    validator would reject (it never runs the validator against `held` at all)."""
    universe = trader._persona_universe((), held=["totallyfakeheld123"], settings=settings)
    assert universe == ("TOTALLYFAKEHELD123",)


def test_universe_drops_a_structurally_implausible_mention(settings: Settings) -> None:
    """A mention that cannot possibly be a ticker (too long) is dropped by the validator's first,
    cheapest layer -- deterministic regardless of the ledger or research universe's contents."""
    notes = (_note("n1", mentions=(_mention("NOTASTOCKSYMBOL"),)),)
    universe = trader._persona_universe(notes, held=(), settings=settings)
    assert universe == ()


def test_universe_caps_and_orders_held_before_mentions(settings: Settings) -> None:
    """Held names are kept regardless of the cap trim order, come first, and the whole tuple never
    exceeds `cap`."""
    held = ["AAA", "BBB", "CCC"]
    universe = trader._persona_universe((), held=held, settings=settings, cap=2)
    assert universe == ("AAA", "BBB")  # capped to 2; held names, in held order


def test_universe_is_a_noop_over_no_notes_and_no_holdings(settings: Settings) -> None:
    assert trader._persona_universe((), held=(), settings=settings) == ()


# ---------------------------------------------------------------------------
# build_trader_book
# ---------------------------------------------------------------------------


def test_build_trader_book_none_blob_is_empty_at_default_inception(settings: Settings) -> None:
    persona = _persona()
    book = trader.build_trader_book(persona=persona, blob=None, settings=settings)
    assert book.persona == "alpha"
    assert book.as_of is None
    assert book.inception == trader.DEFAULT_INCEPTION.isoformat()
    assert book.cash == book.starting_cash == format(trader.STARTING_CASH_USD, "f")
    assert book.equity == format(trader.STARTING_CASH_USD, "f")
    assert book.return_pct == "0"
    assert book.decisions == ()
    assert book.positions == ()
    assert book.warnings == ("not traded yet",)


def test_blob_round_trips_through_build_trader_book(settings: Settings) -> None:
    """A blob built the way `TraderStore.save`/`advance_one_decision` produce it (broker state from
    `PaperBroker.to_state()`, plus the equity curve and running spend) reconstructs into a `TraderBook`
    carrying the same cash, spend and curve -- the read path `list_trader_books` relies on."""
    persona = _persona()
    broker = PaperBroker(default_mandate(starting_cash=trader.STARTING_CASH_USD))
    broker.cash = Decimal("97531.25")
    blob = {
        "inception": trader.DEFAULT_INCEPTION.isoformat(),
        "broker_state": broker.to_state(),
        "equity_curve": [{"date": "2026-01-05", "equity": "97531.25"}],
        "decisions": [],
        "spent_usd": "0.42",
        "last_decided": "2026-01-05",
    }
    book = trader.build_trader_book(
        persona=persona, blob=blob, settings=settings, as_of=dt.date(2026, 1, 5)
    )
    assert book.persona == "alpha"
    assert book.inception == trader.DEFAULT_INCEPTION.isoformat()
    assert book.as_of == "2026-01-05"
    assert book.cash == "97531.25"
    assert book.equity == "97531.25"  # no priced positions, so equity == cash
    assert book.spent_usd == "0.42"
    assert len(book.equity_curve) == 1
    assert book.equity_curve[0].date == "2026-01-05"
    assert book.equity_curve[0].equity == "97531.25"


def test_blob_with_unknown_inception_falls_back_to_default(settings: Settings) -> None:
    persona = _persona()
    blob = {
        "inception": "not-a-date",
        "broker_state": None,
        "equity_curve": [],
        "decisions": [],
        "spent_usd": "0",
        "last_decided": None,
    }
    book = trader.build_trader_book(persona=persona, blob=blob, settings=settings)
    assert book.inception == trader.DEFAULT_INCEPTION.isoformat()
