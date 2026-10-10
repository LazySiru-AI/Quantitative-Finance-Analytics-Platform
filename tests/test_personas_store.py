"""Tests for `app.personas.store.VaultStore`: the Obsidian-compatible markdown vault.

Every test uses the `settings` fixture from `tests/conftest.py`, which redirects `INVDASH_VAULT_DIR`
into `tmp_path` -- nothing here ever touches a real vault. `_make_note` builds a fully-populated
`EpisodicNote` with sensible defaults so each test only has to override the one or two fields it is
actually exercising.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.config import Settings
from app.personas.models import EpisodicNote, Persona, TickerMention, persona_dir
from app.personas.store import VaultStore

_UTC = dt.UTC


def _make_note(
    *,
    note_id: str = "abc123",
    persona: str = "creator-a",
    published: dt.datetime | None = dt.datetime(2026, 9, 1, tzinfo=_UTC),
    ingested_at: dt.datetime = dt.datetime(2026, 9, 1, 23, 40, tzinfo=_UTC),
    title: str | None = "36/1 September Market Headwinds",
    summary: str = "The influencer discussed NVDA earnings and TSLA delivery numbers.",
    themes: tuple[str, ...] = ("AI capex", "EV demand"),
    quotes: tuple[str, ...] = ("This is a verbatim quote.",),
    mentions: tuple[TickerMention, ...] = (
        TickerMention(symbol="NVDA", stance="bullish", reasoning="Strong earnings beat."),
        TickerMention(symbol="TSLA", stance="neutral", reasoning="Mixed delivery numbers."),
    ),
    degraded: bool = False,
    kind: str = "video_transcript",
    transcript_source: str | None = "auto",
    lang: str = "en",
    source_id: str = "yt:UCaaaaaaaaaaaaaaaaaaaaaa",
    url: str = "https://www.youtube.com/watch?v=abc123",
) -> EpisodicNote:
    return EpisodicNote(
        note_id=note_id,
        persona=persona,
        source_id=source_id,
        published=published,
        ingested_at=ingested_at,
        url=url,
        title=title,
        kind=kind,  # type: ignore[arg-type]
        transcript_source=transcript_source,  # type: ignore[arg-type]
        lang=lang,
        summary=summary,
        themes=themes,
        quotes=quotes,
        mentions=mentions,
        # write_note derives its own target location from persona/date/note_id -- see the store's
        # module docstring -- so this placeholder proves the incoming value is never consulted.
        path="placeholder",
        degraded=degraded,
    )


# --- personas ---------------------------------------------------------------------


def test_list_personas_on_empty_vault_returns_empty_tuple(settings: Settings) -> None:
    assert VaultStore(settings).list_personas() == ()


def test_save_and_load_persona_round_trip(settings: Settings) -> None:
    store = VaultStore(settings)
    persona = Persona(
        slug="creator-a",
        display_name="Creator A",
        created_at=dt.datetime(2026, 9, 1, tzinfo=_UTC),
    )
    store.save_persona(persona)
    assert store.load_persona("creator-a") == persona


def test_save_persona_overwrites_in_place(settings: Settings) -> None:
    store = VaultStore(settings)
    persona = Persona(slug="s1", display_name="One", created_at=dt.datetime(2026, 9, 1, tzinfo=_UTC))
    store.save_persona(persona)
    updated = persona.model_copy(update={"note_count": 5})
    store.save_persona(updated)
    loaded = store.load_persona("s1")
    assert loaded is not None
    assert loaded.note_count == 5


def test_load_persona_missing_returns_none(settings: Settings) -> None:
    assert VaultStore(settings).load_persona("does-not-exist") is None


def test_list_personas_sorted_by_display_name(settings: Settings) -> None:
    store = VaultStore(settings)
    created = dt.datetime(2026, 9, 1, tzinfo=_UTC)
    store.save_persona(Persona(slug="b-slug", display_name="Zebra", created_at=created))
    store.save_persona(Persona(slug="a-slug", display_name="Apple", created_at=created))
    assert [p.display_name for p in store.list_personas()] == ["Apple", "Zebra"]


def test_list_personas_skips_corrupt_persona_file(settings: Settings) -> None:
    store = VaultStore(settings)
    created = dt.datetime(2026, 9, 1, tzinfo=_UTC)
    store.save_persona(Persona(slug="good", display_name="Good", created_at=created))
    corrupt_dir = persona_dir(settings, "bad")
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / "persona.json").write_text("not json at all", encoding="utf-8")
    assert [p.slug for p in store.list_personas()] == ["good"]


def test_delete_persona(settings: Settings) -> None:
    store = VaultStore(settings)
    assert store.delete_persona("does-not-exist") is False
    store.save_persona(
        Persona(slug="x", display_name="X", created_at=dt.datetime(2026, 9, 1, tzinfo=_UTC))
    )
    assert store.delete_persona("x") is True
    assert store.load_persona("x") is None
    assert store.delete_persona("x") is False


# --- episodic notes: basic round trip -----------------------------------------------


def test_write_note_and_load_note_round_trip(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note()
    path = store.write_note(note, transcript_text="raw transcript text")
    assert path.is_file()

    loaded = store.load_note(note.persona, note.note_id)
    assert loaded is not None
    expected_path = f"influencers/{note.persona}/notes/2026-09-01-{note.note_id}.md"
    assert loaded == note.model_copy(update={"path": expected_path})


def test_write_note_ignores_incoming_path_field(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="pathignore1")
    assert note.path == "placeholder"
    store.write_note(note)
    loaded = store.load_note(note.persona, "pathignore1")
    assert loaded is not None
    assert loaded.path == f"influencers/{note.persona}/notes/2026-09-01-pathignore1.md"


def test_write_note_returns_absolute_path_actually_written(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="ret1")
    path = store.write_note(note)
    assert path.read_text(encoding="utf-8").startswith("---\n")


def test_write_note_refuses_to_overwrite_existing_note(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="dup1")
    store.write_note(note)
    with pytest.raises(ValueError, match="dup1"):
        store.write_note(note)


def test_write_note_transcript_written_and_readable(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="tr1")
    store.write_note(note, transcript_text="raw content here")
    assert store.read_transcript(note.persona, "tr1") == "raw content here"


def test_read_transcript_missing_returns_none(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="notr1")
    store.write_note(note)  # no transcript_text given
    assert store.read_transcript(note.persona, "notr1") is None


def test_note_without_transcript_omits_transcript_link(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="nolink1")
    path = store.write_note(note)
    raw = path.read_text(encoding="utf-8")
    assert "[Transcript]" not in raw
    assert "[Original]" in raw


def test_note_with_transcript_includes_transcript_link(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="link1")
    path = store.write_note(note, transcript_text="text")
    raw = path.read_text(encoding="utf-8")
    assert "[Transcript](../transcripts/link1.md)" in raw


# --- published: nullable, omitted when unknown ---------------------------------------


def test_write_note_omits_published_key_when_none(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="nodate1", published=None)
    path = store.write_note(note)

    raw = path.read_text(encoding="utf-8")
    assert "published:" not in raw
    # Falls back to `ingested_at`'s date for the filename prefix.
    assert path.name == f"{note.ingested_at.date().isoformat()}-nodate1.md"

    loaded = store.load_note(note.persona, "nodate1")
    assert loaded is not None
    assert loaded.published is None


def test_write_note_writes_published_key_when_known(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="hasdate1")
    path = store.write_note(note)
    raw = path.read_text(encoding="utf-8")
    assert "published: 2026-09-01T00:00:00+00:00" in raw


# --- listing order --------------------------------------------------------------------


def test_list_notes_newest_first(settings: Settings) -> None:
    store = VaultStore(settings)
    older = _make_note(
        note_id="old1",
        published=dt.datetime(2026, 8, 1, tzinfo=_UTC),
        ingested_at=dt.datetime(2026, 8, 1, tzinfo=_UTC),
    )
    newer = _make_note(
        note_id="new1",
        published=dt.datetime(2026, 9, 1, tzinfo=_UTC),
        ingested_at=dt.datetime(2026, 9, 1, tzinfo=_UTC),
    )
    store.write_note(older)
    store.write_note(newer)
    assert [n.note_id for n in store.list_notes("creator-a")] == ["new1", "old1"]


def test_list_notes_on_missing_persona_returns_empty_tuple(settings: Settings) -> None:
    assert VaultStore(settings).list_notes("does-not-exist") == ()


def test_has_note(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="has1")
    assert store.has_note(note.persona, "has1") is False
    store.write_note(note)
    assert store.has_note(note.persona, "has1") is True


def test_load_note_missing_returns_none(settings: Settings) -> None:
    assert VaultStore(settings).load_note("does-not-exist", "also-missing") is None


# --- corruption handling ---------------------------------------------------------------


def test_list_notes_skips_unparseable_file(settings: Settings) -> None:
    store = VaultStore(settings)
    good = _make_note(note_id="good1")
    store.write_note(good)
    notes_dir = persona_dir(settings, good.persona) / "notes"
    (notes_dir / "2026-09-01-corrupt1.md").write_text("not frontmatter at all", encoding="utf-8")
    assert [n.note_id for n in store.list_notes(good.persona)] == ["good1"]


def test_load_note_for_corrupt_file_returns_none(settings: Settings) -> None:
    store = VaultStore(settings)
    notes_dir = persona_dir(settings, "creator-a") / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "2026-09-01-bad1.md").write_text("garbage, no frontmatter", encoding="utf-8")
    assert store.load_note("creator-a", "bad1") is None


# --- frontmatter quoting: title with a colon and a quote -------------------------------


def test_title_with_colon_and_quote_round_trips(settings: Settings) -> None:
    store = VaultStore(settings)
    tricky_title = 'Markets: "Big" moves & a backslash \\ at the end'
    note = _make_note(note_id="tt1", title=tricky_title)
    store.write_note(note)
    loaded = store.load_note(note.persona, "tt1")
    assert loaded is not None
    assert loaded.title == tricky_title


def test_title_none_round_trips(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="tn1", title=None)
    store.write_note(note)
    loaded = store.load_note(note.persona, "tn1")
    assert loaded is not None
    assert loaded.title is None


def test_empty_mentions_and_quotes_round_trip(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="empty1", mentions=(), quotes=())
    store.write_note(note)
    loaded = store.load_note(note.persona, "empty1")
    assert loaded is not None
    assert loaded.mentions == ()
    assert loaded.quotes == ()


# --- themes (contract amendment) --------------------------------------------------------


def test_themes_round_trip(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="th1", themes=("Theme A", "Theme B", "Theme C"))
    store.write_note(note)
    loaded = store.load_note(note.persona, "th1")
    assert loaded is not None
    assert loaded.themes == ("Theme A", "Theme B", "Theme C")


def test_no_themes_omits_section_and_round_trips_to_empty_tuple(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="noth1", themes=())
    path = store.write_note(note)
    raw = path.read_text(encoding="utf-8")
    assert "## Themes" not in raw

    loaded = store.load_note(note.persona, "noth1")
    assert loaded is not None
    assert loaded.themes == ()


# --- degraded (contract amendment) ------------------------------------------------------


def test_degraded_true_round_trips(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="deg1", degraded=True)
    path = store.write_note(note)
    assert "degraded: true" in path.read_text(encoding="utf-8")

    loaded = store.load_note(note.persona, "deg1")
    assert loaded is not None
    assert loaded.degraded is True


def test_degraded_false_round_trips(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(note_id="deg2", degraded=False)
    path = store.write_note(note)
    assert "degraded: false" in path.read_text(encoding="utf-8")

    loaded = store.load_note(note.persona, "deg2")
    assert loaded is not None
    assert loaded.degraded is False


def test_degraded_defaults_to_false_when_key_is_missing(settings: Settings) -> None:
    """A note written before this field existed has no `degraded:` line at all -- it must still
    load, and must load as `False`, per the contract amendment."""
    store = VaultStore(settings)
    note = _make_note(note_id="predeg1")
    path = store.write_note(note)
    raw = path.read_text(encoding="utf-8")
    assert "degraded: false\n" in raw
    path.write_text(raw.replace("degraded: false\n", ""), encoding="utf-8")

    loaded = store.load_note(note.persona, "predeg1")
    assert loaded is not None
    assert loaded.degraded is False


# --- Korean round trip -----------------------------------------------------------------


def test_korean_summary_quotes_and_themes_round_trip(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(
        note_id="ko1",
        lang="ko",
        summary="이 영상에서는 엔비디아와 테슬라에 대해 이야기합니다.",
        themes=("반도체 수요", "전기차 시장"),
        quotes=("엔비디아 실적이 매우 좋았습니다.", "테슬라는 애매합니다."),
        mentions=(
            TickerMention(symbol="NVDA", stance="bullish", reasoning="실적이 예상치를 상회함"),
        ),
    )
    store.write_note(note)

    loaded = store.load_note(note.persona, "ko1")
    assert loaded is not None
    assert loaded.summary == note.summary
    assert loaded.themes == note.themes
    assert loaded.quotes == note.quotes
    assert loaded.mentions == note.mentions
    assert loaded.lang == "ko"


# --- instrument / horizon (contract amendment) --------------------------------------


def test_instrument_and_horizon_round_trip(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(
        note_id="ih1",
        mentions=(
            TickerMention(
                symbol="GC",
                stance="bullish",
                reasoning="Gold breakout.",
                instrument="future",
                horizon="intraday",
            ),
        ),
    )
    path = store.write_note(note)
    raw = path.read_text(encoding="utf-8")
    assert "- **GC** [future, intraday] — bullish. Gold breakout." in raw

    loaded = store.load_note(note.persona, "ih1")
    assert loaded is not None
    assert len(loaded.mentions) == 1
    assert loaded.mentions[0].instrument == "future"
    assert loaded.mentions[0].horizon == "intraday"


def test_legacy_ticker_line_without_brackets_parses_to_defaults(settings: Settings) -> None:
    """A note written before `instrument`/`horizon` existed has no `[...]` bracket at all on its
    `## Tickers` bullet -- 216 such notes are on disk. It must still parse, and must parse to the
    model's own defaults, not raise."""
    store = VaultStore(settings)
    note = _make_note(
        note_id="legacy1",
        mentions=(TickerMention(symbol="AAPL", stance="bullish", reasoning="Legacy note."),),
    )
    path = store.write_note(note)
    raw = path.read_text(encoding="utf-8")
    legacy_raw = raw.replace(
        "- **AAPL** [equity, unclear] — bullish. Legacy note.",
        "- **AAPL** — bullish. Legacy note.",
    )
    assert legacy_raw != raw  # sanity: the replacement actually matched something
    path.write_text(legacy_raw, encoding="utf-8")

    loaded = store.load_note(note.persona, "legacy1")
    assert loaded is not None
    assert len(loaded.mentions) == 1
    assert loaded.mentions[0].symbol == "AAPL"
    assert loaded.mentions[0].instrument == "equity"
    assert loaded.mentions[0].horizon == "unclear"


def test_bracket_with_unrecognised_instrument_falls_back_to_equity(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(
        note_id="garbage1",
        mentions=(TickerMention(symbol="XYZ", stance="bearish", reasoning="Garbage bracket."),),
    )
    path = store.write_note(note)
    raw = path.read_text(encoding="utf-8")
    garbage_raw = raw.replace(
        "- **XYZ** [equity, unclear] — bearish. Garbage bracket.",
        "- **XYZ** [zorbnaxis, unclear] — bearish. Garbage bracket.",
    )
    assert garbage_raw != raw

    path.write_text(garbage_raw, encoding="utf-8")

    loaded = store.load_note(note.persona, "garbage1")
    assert loaded is not None
    assert len(loaded.mentions) == 1
    assert loaded.mentions[0].symbol == "XYZ"
    assert loaded.mentions[0].instrument == "equity"
    assert loaded.mentions[0].horizon == "unclear"


def test_korean_reasoning_with_instrument_and_horizon_round_trips(settings: Settings) -> None:
    store = VaultStore(settings)
    note = _make_note(
        note_id="ko-ih1",
        lang="ko",
        mentions=(
            TickerMention(
                symbol="GC",
                stance="bullish",
                reasoning="금 가격이 돌파했습니다.",
                instrument="future",
                horizon="intraday",
            ),
        ),
    )
    store.write_note(note)

    loaded = store.load_note(note.persona, "ko-ih1")
    assert loaded is not None
    assert loaded.mentions == note.mentions
    assert loaded.mentions[0].reasoning == "금 가격이 돌파했습니다."
    assert loaded.mentions[0].instrument == "future"
    assert loaded.mentions[0].horizon == "intraday"


# --- log.md --------------------------------------------------------------------------


def test_append_log_appends_lines_in_order(settings: Settings) -> None:
    store = VaultStore(settings)
    store.append_log("creator-a", "line one")
    store.append_log("creator-a", "line two")
    log_path = persona_dir(settings, "creator-a") / "log.md"
    assert log_path.read_text(encoding="utf-8") == "line one\nline two\n"
