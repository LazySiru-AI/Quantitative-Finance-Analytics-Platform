"""The rule-desk fill journal (`backend/app/paperdesk/fill_journal.py`) and its notification hook.

**Synthetic states, not a real desk run.** `app.paperdesk.desk.refresh` replays every card back to
inception off the real bar store; driving it here would make these tests a test of the replay, take
minutes, and skip on a fresh clone. What `diff_and_record` actually consumes is four fields --
`state.as_of`, and each book's `purpose`, each desk's `agent_id` and its holdings' `symbol`/`quantity`
-- so the stand-ins below supply exactly those. The hook that calls it is covered by asserting the
emitted events off `_record_and_notify_fills`, which takes a state the same way.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import pytest

import app.notify as notify_pkg
from app.config import Settings
from app.notify import events as notify_events
from app.paperdesk import desk as paperdesk
from app.paperdesk import fill_journal
from app.paperdesk.models import PaperDeskState

_AS_OF = dt.date(2026, 9, 9)


@dataclass(frozen=True)
class _Holding:
    symbol: str
    quantity: Decimal


@dataclass(frozen=True)
class _Desk:
    agent_id: str
    holdings: list[_Holding]


@dataclass(frozen=True)
class _Book:
    purpose: str
    desks: list[_Desk]


@dataclass(frozen=True)
class _State:
    books: list[_Book]
    as_of: dt.date = _AS_OF


def _state(desks: dict[str, dict[str, str]], *, purpose: str = "trading") -> PaperDeskState:
    """`{"<agent id>": {"<symbol>": "<qty>"}}` -> a state `diff_and_record` can read."""
    books = [
        _Book(
            purpose=purpose,
            desks=[
                _Desk(
                    agent_id=agent_id,
                    holdings=[
                        _Holding(symbol=symbol, quantity=Decimal(qty))
                        for symbol, qty in positions.items()
                    ],
                )
                for agent_id, positions in desks.items()
            ],
        )
    ]
    return cast(PaperDeskState, _State(books=books))


class TestBaseline:
    def test_first_run_records_the_snapshot_and_reports_nothing(self, settings: Settings) -> None:
        deltas = fill_journal.diff_and_record(settings, _state({"A-mom": {"NVDA": "10"}}))
        assert deltas == []
        assert not fill_journal.journal_path(settings).exists()
        snapshot = json.loads(
            fill_journal.snapshot_path(settings).read_text(encoding="utf-8")
        )
        assert snapshot == {"trading/A-mom": {"NVDA": "10"}}

    def test_a_desk_seen_for_the_first_time_is_baselined_not_announced(
        self, settings: Settings
    ) -> None:
        fill_journal.diff_and_record(settings, _state({"A-mom": {"NVDA": "10"}}))
        deltas = fill_journal.diff_and_record(
            settings, _state({"A-mom": {"NVDA": "10"}, "B-new": {"AAPL": "5"}})
        )
        assert deltas == []
        # ...but the next run differences it normally.
        deltas = fill_journal.diff_and_record(
            settings, _state({"A-mom": {"NVDA": "10"}, "B-new": {"AAPL": "8"}})
        )
        assert [(d.desk, d.side, str(d.quantity)) for d in deltas] == [
            ("trading/B-new", "BUY", "3")
        ]


class TestDeltas:
    def test_new_symbol_and_increase_are_buys_gone_and_decrease_are_sells(
        self, settings: Settings
    ) -> None:
        fill_journal.diff_and_record(
            settings, _state({"A-mom": {"NVDA": "10", "AAPL": "4", "MSFT": "2"}})
        )
        deltas = fill_journal.diff_and_record(
            settings, _state({"A-mom": {"NVDA": "14", "AAPL": "1", "TSLA": "3"}})
        )
        assert [(d.symbol, d.side, str(d.quantity)) for d in deltas] == [
            ("AAPL", "SELL", "3"),
            ("MSFT", "SELL", "2"),
            ("NVDA", "BUY", "4"),
            ("TSLA", "BUY", "3"),
        ]
        assert {d.as_of for d in deltas} == {_AS_OF}

    def test_an_unchanged_book_produces_nothing_and_still_rewrites_the_snapshot(
        self, settings: Settings
    ) -> None:
        fill_journal.diff_and_record(settings, _state({"A-mom": {"NVDA": "10"}}))
        assert fill_journal.diff_and_record(settings, _state({"A-mom": {"NVDA": "10"}})) == []
        assert not fill_journal.journal_path(settings).exists()

    def test_the_same_card_in_two_books_is_two_desks(self, settings: Settings) -> None:
        first = _state({"A-mom": {"NVDA": "10"}}, purpose="trading")
        second = _state({"A-mom": {"NVDA": "2"}}, purpose="roth")
        both = cast(
            PaperDeskState,
            _State(books=[*cast(Any, first).books, *cast(Any, second).books]),
        )
        fill_journal.diff_and_record(settings, both)

        changed = cast(
            PaperDeskState,
            _State(
                books=[
                    *cast(Any, _state({"A-mom": {"NVDA": "12"}}, purpose="trading")).books,
                    *cast(Any, _state({"A-mom": {"NVDA": "2"}}, purpose="roth")).books,
                ]
            ),
        )
        deltas = fill_journal.diff_and_record(settings, changed)
        assert [d.desk for d in deltas] == ["trading/A-mom"]

    def test_deltas_are_appended_to_the_journal(self, settings: Settings) -> None:
        fill_journal.diff_and_record(settings, _state({"A-mom": {"NVDA": "10"}}))
        fill_journal.diff_and_record(settings, _state({"A-mom": {"NVDA": "12"}}))
        fill_journal.diff_and_record(settings, _state({"A-mom": {"NVDA": "12", "AAPL": "1"}}))
        lines = [
            json.loads(line)
            for line in fill_journal.journal_path(settings)
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        assert [(row["symbol"], row["side"], row["quantity"]) for row in lines] == [
            ("NVDA", "BUY", "2"),
            ("AAPL", "BUY", "1"),
        ]
        assert lines[0]["as_of"] == _AS_OF.isoformat()

    def test_a_corrupt_snapshot_rebaselines_rather_than_announcing_every_position(
        self, settings: Settings
    ) -> None:
        fill_journal.snapshot_path(settings).write_text("{not json", encoding="utf-8")
        assert fill_journal.diff_and_record(settings, _state({"A-mom": {"NVDA": "10"}})) == []


class TestNotifyHook:
    def test_each_delta_emits_one_paper_fill_event(self, settings: Settings) -> None:
        paperdesk._record_and_notify_fills(settings, _state({"A-mom": {"NVDA": "10"}}))
        assert notify_events.list_since(settings) == []

        paperdesk._record_and_notify_fills(settings, _state({"A-mom": {"NVDA": "6"}}))
        emitted = notify_events.list_since(settings)
        assert len(emitted) == 1
        event = emitted[0]
        assert event.kind == "paper.fill"
        assert event.severity == "notable"
        assert event.headline == "trading/A-mom: SELL 4 NVDA"
        assert event.refs == ("symbol:NVDA", "desk:trading/A-mom")
        assert event.source == "paperdesk.refresh"
        assert event.id == "paper.fill:desk:trading/A-mom:NVDA:SELL:2026-09-09"

    def test_the_hook_swallows_a_broken_emit(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paperdesk._record_and_notify_fills(settings, _state({"A-mom": {"NVDA": "10"}}))

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("notify is broken")

        monkeypatch.setattr(notify_pkg, "emit", _boom)
        paperdesk._record_and_notify_fills(settings, _state({"A-mom": {"NVDA": "11"}}))
        assert notify_events.list_since(settings) == []
