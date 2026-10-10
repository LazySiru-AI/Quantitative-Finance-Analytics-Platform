"""Tests for `app.personas.backfill_ingest`: parse an external agent's reply, prove it against the
transcript, persist it as a note with honest provenance.

Uses the `settings` fixture from `tests/conftest.py` (vault redirected into `tmp_path`), so nothing
here touches a real vault. The symbol validator is injected explicitly in the `validate_result` tests
and stubbed at its import site for the `ingest_result` ones -- the real
`app.personas.tickers.build_symbol_validator` reads the ledger, the research universe and (in
production) a market provider, none of which this module's behaviour depends on.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app.config import Settings
from app.personas import backfill_ingest
from app.personas.backfill_ingest import (
    BackfillMention,
    BackfillResult,
    BackfillResultInvalid,
    BackfillValidationFailed,
    ingest_result,
    parse_result,
    validate_result,
)
from app.personas.models import EpisodicNote, FollowedSource, Persona
from app.personas.service import PersonaError
from app.personas.store import VaultStore

_UTC = dt.UTC
_NOW = dt.datetime(2026, 9, 1, tzinfo=_UTC)

#: The reference text every grounding assertion below is made against. It states 950 and 12.5%, and
#: nothing else a `numeric_tokens` sweep would consider groundable.
_TRANSCRIPT = (
    "Nvidia is trading around 950 dollars today and I think it runs further. "
    "Tesla deliveries fell 12.5% and I am staying out of it."
)


def _reply(**overrides: object) -> dict[str, object]:
    """A well-formed reply body, every number of which appears in `_TRANSCRIPT`."""
    body: dict[str, object] = {
        "summary": "The speaker is bullish on Nvidia around 950 and cautious on Tesla.",
        "themes": ["AI capex", "EV demand"],
        "quotes": ["I think it runs further."],
        "mentions": [
            {"symbol": "NVDA", "stance": "bullish", "horizon": "swing", "reasoning": "Momentum at 950."},
        ],
    }
    body.update(overrides)
    return body


def _ok_validator(symbol: str) -> bool:
    """Stands in for `app.personas.tickers.build_symbol_validator`, including its normalisation --
    the real one upper-cases and strips before deciding, so a stub that did not would make a
    lowercase symbol look rejected for the wrong reason."""
    return symbol.strip().upper() in {"NVDA", "TSLA"}


# --- parse ------------------------------------------------------------------------


def test_parse_reads_a_fenced_json_block_surrounded_by_prose() -> None:
    text = (
        "Sure! Here is the structured note you asked for:\n\n"
        "```json\n" + json.dumps(_reply()) + "\n```\n\n"
        "Let me know if you would like anything adjusted.\n"
    )
    result = parse_result(text)
    assert result.summary.startswith("The speaker is bullish")
    assert result.themes == ("AI capex", "EV demand")
    assert result.mentions[0].symbol == "NVDA"


def test_parse_reads_bare_json_as_the_whole_reply() -> None:
    result = parse_result(json.dumps(_reply()) + "\n\n")
    assert result.mentions[0].horizon == "swing"


def test_parse_rejects_a_reply_with_no_json_at_all() -> None:
    with pytest.raises(BackfillResultInvalid) as exc:
        parse_result("I could not watch the video, sorry.")
    assert "no JSON" in str(exc.value)


def test_parse_rejects_the_wrong_shape() -> None:
    # `mentions` is an object, not the list of mentions the packet asks for.
    with pytest.raises(BackfillResultInvalid) as exc:
        parse_result(json.dumps(_reply(mentions={"NVDA": "bullish"})))
    assert "mentions" in str(exc.value)


def test_parse_rejects_a_missing_field() -> None:
    body = _reply()
    del body["quotes"]
    with pytest.raises(BackfillResultInvalid):
        parse_result(json.dumps(body))


def test_parse_rejects_malformed_json_inside_a_fence() -> None:
    with pytest.raises(BackfillResultInvalid) as exc:
        parse_result("```json\n{\"summary\": \"oops\",}\n```")
    assert "could not be parsed" in str(exc.value)


def test_parse_is_case_insensitive_about_stance_and_horizon() -> None:
    body = _reply(
        mentions=[{"symbol": "NVDA", "stance": "Bullish", "horizon": "LONG_TERM", "reasoning": ""}]
    )
    result = parse_result(json.dumps(body))
    assert result.mentions[0].stance == "bullish"
    assert result.mentions[0].horizon == "long_term"


def test_parse_defaults_horizon_and_reasoning_when_omitted() -> None:
    body = _reply(mentions=[{"symbol": "NVDA", "stance": "neutral"}])
    result = parse_result(json.dumps(body))
    assert result.mentions[0].horizon == "unclear"
    assert result.mentions[0].reasoning == ""


def test_parse_ignores_an_echoed_task_id() -> None:
    # An agent shown a "Task id: <id>" line in the packet routinely echoes it back inside the JSON;
    # `extra="forbid"` would reject that otherwise-faithful reply. A top-level id echo is dropped.
    body = _reply()
    body["task_id"] = "vidB-bbbbb2"
    result = parse_result(json.dumps(body))
    assert result.summary.startswith("The speaker is bullish")
    assert result.mentions[0].symbol == "NVDA"


def test_parse_still_rejects_an_unexpected_top_level_key() -> None:
    # Only the known id echoes are tolerated; any other surprise field is still a shape error, because
    # it means the reply answered a different question than the packet asked.
    body = _reply()
    body["confidence"] = 0.9
    with pytest.raises(BackfillResultInvalid):
        parse_result(json.dumps(body))


# --- validate ---------------------------------------------------------------------


def test_validate_passes_valid_symbols_and_transcript_numbers() -> None:
    report = validate_result(
        parse_result(json.dumps(_reply())),
        transcript=_TRANSCRIPT,
        symbol_validator=_ok_validator,
    )
    assert report.ok is True
    assert report.reasons == ()
    assert report.dropped_symbols == ()
    assert report.ungrounded_numbers == ()


def test_validate_drops_an_unvalidatable_symbol_without_failing() -> None:
    # A mangled caption word (or a real future/index the provider omits) is DROPPED, not a rejection:
    # the note keeps its summary, themes, quotes and every valid mention. dropped_symbols is
    # informational, so it never appears in `reasons` and never flips `ok`.
    body = _reply(
        mentions=[{"symbol": "LIGHT", "stance": "bullish", "horizon": "swing", "reasoning": "x"}]
    )
    report = validate_result(
        parse_result(json.dumps(body)), transcript=_TRANSCRIPT, symbol_validator=_ok_validator
    )
    assert report.ok is True
    assert report.dropped_symbols == ("LIGHT",)
    assert report.ungrounded_numbers == ()
    assert report.reasons == ()


def test_validate_admits_a_figure_derived_from_two_stated_ones() -> None:
    # The real grounding check uses `grounding.grounded_values`, which admits the difference of two
    # stated figures (130 - 100 = 30), NOT a naive "every digit must appear verbatim in the transcript"
    # subset -- which would false-reject the 30 that is nowhere in the source as a literal. This is the
    # exact false-rejection class the fix removed.
    transcript = "The stock went from 100 to 130 over the quarter."
    body = _reply(summary="It rose 30 over the period.", quotes=[], mentions=[])
    report = validate_result(
        parse_result(json.dumps(body)), transcript=transcript, symbol_validator=_ok_validator
    )
    assert report.ok is True
    assert report.ungrounded_numbers == ()


def test_validate_fails_on_a_number_the_transcript_never_stated() -> None:
    body = _reply(summary="He set a price target of 1200 dollars on Nvidia.")
    report = validate_result(
        parse_result(json.dumps(body)), transcript=_TRANSCRIPT, symbol_validator=_ok_validator
    )
    assert report.ok is False
    assert report.ungrounded_numbers == ("1200",)
    assert report.dropped_symbols == ()


def test_validate_accepts_a_number_that_is_in_the_transcript() -> None:
    body = _reply(summary="Tesla deliveries fell 12.5% and Nvidia trades near 950.")
    report = validate_result(
        parse_result(json.dumps(body)), transcript=_TRANSCRIPT, symbol_validator=_ok_validator
    )
    assert report.ok is True


def test_validate_excludes_quotes_from_the_number_check_but_checks_reasoning() -> None:
    # A number that appears ONLY in a quote is not checked (a quote is verbatim source text by
    # construction; re-checking it re-adds false rejects from caption spacing). A number in `reasoning`
    # IS checked. So 1200 (quote-only) passes; 777 (reasoning) is caught.
    body = _reply(
        summary="Nvidia trades near 950.",
        quotes=["My target is 1200."],
        mentions=[
            {"symbol": "NVDA", "stance": "bullish", "horizon": "swing", "reasoning": "Support at 777."}
        ],
    )
    report = validate_result(
        parse_result(json.dumps(body)), transcript=_TRANSCRIPT, symbol_validator=_ok_validator
    )
    assert report.ok is False
    assert report.ungrounded_numbers == ("777",)


def test_validate_number_fails_but_a_dropped_symbol_is_only_informational() -> None:
    body = _reply(
        summary="Target 1200.",
        mentions=[{"symbol": "LIGHT", "stance": "bullish", "horizon": "swing", "reasoning": ""}],
    )
    report = validate_result(
        parse_result(json.dumps(body)), transcript=_TRANSCRIPT, symbol_validator=_ok_validator
    )
    # Both lists are reported (a --dry-run shows everything at once), but only the ungrounded number
    # fails the report -- the dropped ticker does not.
    assert report.dropped_symbols == ("LIGHT",) and report.ungrounded_numbers == ("1200",)
    assert report.ok is False
    assert len(report.reasons) == 1 and "1200" in report.reasons[0]


# --- ingest -----------------------------------------------------------------------


def _persona(store: VaultStore, *, slug: str = "creator-a") -> Persona:
    persona = Persona(
        slug=slug,
        display_name="Creator A",
        sources=(
            FollowedSource(
                source_id="yt:UCabc",
                platform="youtube",
                handle=slug,
                channel_id="UCabc",
                url=f"https://www.youtube.com/@{slug}",
                added_at=_NOW,
            ),
        ),
        created_at=_NOW,
    )
    store.save_persona(persona)
    return persona


@pytest.fixture
def _stub_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the symbol validator `ingest_result` builds for itself.

    It is patched on `app.personas.tickers` (the definition site) rather than on this module, because
    `ingest_result` imports it at call time -- see its own comment on why.
    """
    from app.personas import tickers

    monkeypatch.setattr(tickers, "build_symbol_validator", lambda settings, **_: _ok_validator)


def test_ingest_writes_a_note_with_external_provenance(
    settings: Settings, _stub_validator: None
) -> None:
    store = VaultStore(settings)
    _persona(store)

    note = ingest_result(
        settings,
        persona_slug="creator-a",
        video_id="vnew",
        result=parse_result(json.dumps(_reply())),
        transcript=_TRANSCRIPT,
        url="https://www.youtube.com/watch?v=vnew",
        title="September Market View",
        published=_NOW,
        lang="ko",
    )

    assert note.summary_source == "external"
    assert note.degraded is False
    assert note.kind == "video_transcript"
    assert note.source_id == "yt:UCabc"  # the persona's first enabled youtube source
    assert note.path.startswith("influencers/creator-a/notes/")

    # It is really on disk, and reads back the same way.
    loaded = store.load_note("creator-a", "vnew")
    assert loaded is not None
    assert loaded.summary_source == "external"
    assert loaded.summary == note.summary
    assert store.read_transcript("creator-a", "vnew") == _TRANSCRIPT

    # The persona record was folded forward, not left stale.
    assert store.load_persona("creator-a").note_count == 1  # type: ignore[union-attr]


def test_ingest_upper_cases_symbols(settings: Settings, _stub_validator: None) -> None:
    store = VaultStore(settings)
    _persona(store)
    body = _reply(
        mentions=[{"symbol": "nvda", "stance": "bullish", "horizon": "swing", "reasoning": "ok"}]
    )
    note = ingest_result(
        settings,
        persona_slug="creator-a",
        video_id="vnew",
        result=parse_result(json.dumps(body)),
        transcript=_TRANSCRIPT,
    )
    assert [m.symbol for m in note.mentions] == ["NVDA"]
    assert store.load_persona("creator-a").tickers == ("NVDA",)  # type: ignore[union-attr]


def test_ingest_falls_back_to_the_watch_url_when_none_is_given(
    settings: Settings, _stub_validator: None
) -> None:
    _persona(VaultStore(settings))
    note = ingest_result(
        settings,
        persona_slug="creator-a",
        video_id="vnew",
        result=parse_result(json.dumps(_reply())),
        transcript=_TRANSCRIPT,
    )
    assert note.url == "https://www.youtube.com/watch?v=vnew"
    assert note.published is None  # never a stand-in date


def test_ingest_unknown_persona_raises_404(settings: Settings, _stub_validator: None) -> None:
    with pytest.raises(PersonaError) as exc:
        ingest_result(
            settings,
            persona_slug="nobody",
            video_id="vnew",
            result=parse_result(json.dumps(_reply())),
            transcript=_TRANSCRIPT,
        )
    assert exc.value.status_code == 404


def test_ingest_duplicate_video_raises_409(settings: Settings, _stub_validator: None) -> None:
    store = VaultStore(settings)
    _persona(store)
    result = parse_result(json.dumps(_reply()))
    ingest_result(
        settings, persona_slug="creator-a", video_id="vnew", result=result, transcript=_TRANSCRIPT
    )
    with pytest.raises(PersonaError) as exc:
        ingest_result(
            settings, persona_slug="creator-a", video_id="vnew", result=result, transcript=_TRANSCRIPT
        )
    assert exc.value.status_code == 409
    # Immutability held: the first note is still the only one.
    assert len(store.list_notes("creator-a")) == 1


def test_ingest_rejects_an_ungrounded_number_and_writes_nothing(
    settings: Settings, _stub_validator: None
) -> None:
    store = VaultStore(settings)
    _persona(store)
    body = _reply(summary="He set a price target of 1200 dollars.")

    with pytest.raises(BackfillValidationFailed) as exc:
        ingest_result(
            settings,
            persona_slug="creator-a",
            video_id="vnew",
            result=parse_result(json.dumps(body)),
            transcript=_TRANSCRIPT,
        )

    assert any("1200" in reason for reason in exc.value.reasons)
    # HARD-REJECT: nothing at all was persisted, not even a degraded note.
    assert store.has_note("creator-a", "vnew") is False
    assert store.load_persona("creator-a").note_count == 0  # type: ignore[union-attr]


def test_ingest_drops_an_unvalidatable_symbol_and_keeps_the_rest(
    settings: Settings, _stub_validator: None
) -> None:
    store = VaultStore(settings)
    _persona(store)
    body = _reply(
        mentions=[
            {"symbol": "NVDA", "stance": "bullish", "horizon": "swing", "reasoning": "ok"},
            {"symbol": "LIGHT", "stance": "bullish", "horizon": "swing", "reasoning": "mangled"},
        ]
    )
    note = ingest_result(
        settings,
        persona_slug="creator-a",
        video_id="vnew",
        result=parse_result(json.dumps(body)),
        transcript=_TRANSCRIPT,
    )
    # The note IS written; the unvalidatable mention is dropped, the valid one kept -- matching the
    # in-house summariser, not a whole-note rejection.
    assert store.has_note("creator-a", "vnew") is True
    assert {m.symbol for m in note.mentions} == {"NVDA"}


def test_ingest_converts_a_lost_write_race_to_a_graceful_409(
    settings: Settings, _stub_validator: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two sessions ingesting the same shared vault at once: this one passes the has_note() pre-check
    # (note absent), then the OTHER writer creates the note, so write_note raises a bare ValueError.
    # That must surface as the same PersonaError(409) the pre-check raises -- so a batch CLI reports a
    # duplicate and continues -- not as an uncaught crash. Simulated: has_note False on the pre-check,
    # True in the except; write_note raises the immutable-note ValueError.
    from app.personas import store as store_mod

    _persona(VaultStore(settings))
    calls = {"has_note": 0}

    def fake_has_note(self: object, slug: str, note_id: str) -> bool:
        calls["has_note"] += 1
        return calls["has_note"] > 1  # False on the pre-check, True once the race is lost

    def fake_write_note(self: object, note: object, *, transcript_text: str | None = None) -> object:
        raise ValueError(f"note {getattr(note, 'note_id', '?')!r} already exists; immutable")

    monkeypatch.setattr(store_mod.VaultStore, "has_note", fake_has_note)
    monkeypatch.setattr(store_mod.VaultStore, "write_note", fake_write_note)

    with pytest.raises(PersonaError) as exc:
        ingest_result(
            settings, persona_slug="creator-a", video_id="vrace",
            result=parse_result(json.dumps(_reply())), transcript=_TRANSCRIPT,
        )
    assert exc.value.status_code == 409


def test_ingest_reraises_a_non_duplicate_write_error(
    settings: Settings, _stub_validator: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A ValueError from write_note when the note does NOT exist afterward is a genuine failure (a
    # malformed note, a disk error) and must propagate, never be masked as a duplicate.
    from app.personas import store as store_mod

    _persona(VaultStore(settings))
    monkeypatch.setattr(store_mod.VaultStore, "has_note", lambda self, slug, nid: False)

    def boom(self: object, note: object, *, transcript_text: str | None = None) -> object:
        raise ValueError("some other write failure")

    monkeypatch.setattr(store_mod.VaultStore, "write_note", boom)
    with pytest.raises(ValueError, match="some other write failure"):
        ingest_result(
            settings, persona_slug="creator-a", video_id="vrace2",
            result=parse_result(json.dumps(_reply())), transcript=_TRANSCRIPT,
        )


def test_ingest_appends_a_log_line_naming_the_external_agent(
    settings: Settings, _stub_validator: None
) -> None:
    from app.personas.models import persona_dir

    _persona(VaultStore(settings))
    ingest_result(
        settings,
        persona_slug="creator-a",
        video_id="vnew",
        result=parse_result(json.dumps(_reply())),
        transcript=_TRANSCRIPT,
    )
    log = (persona_dir(settings, "creator-a") / "log.md").read_text(encoding="utf-8")
    assert "ingested vnew from external agent (1 tickers)" in log


# --- store round trip -------------------------------------------------------------


def _note(**overrides: object) -> EpisodicNote:
    fields: dict[str, object] = {
        "note_id": "abc123",
        "persona": "creator-a",
        "source_id": "yt:UCabc",
        "published": _NOW,
        "ingested_at": _NOW,
        "url": "https://www.youtube.com/watch?v=abc123",
        "title": "t",
        "kind": "video_transcript",
        "transcript_source": "auto",
        "lang": "en",
        "summary": "s",
        "themes": (),
        "quotes": (),
        "mentions": (),
        "path": "placeholder",
        "degraded": False,
    }
    fields.update(overrides)
    return EpisodicNote(**fields)  # type: ignore[arg-type]


def test_store_round_trips_summary_source_external(settings: Settings) -> None:
    store = VaultStore(settings)
    store.write_note(_note(summary_source="external"))
    loaded = store.load_note("creator-a", "abc123")
    assert loaded is not None and loaded.summary_source == "external"


def test_store_defaults_summary_source_to_model(settings: Settings) -> None:
    store = VaultStore(settings)
    store.write_note(_note())
    loaded = store.load_note("creator-a", "abc123")
    assert loaded is not None and loaded.summary_source == "model"


def test_a_legacy_note_without_the_key_loads_as_model(settings: Settings) -> None:
    store = VaultStore(settings)
    path = store.write_note(_note())
    # Strip the key the way a note written before this field existed would not have had it.
    raw = path.read_text(encoding="utf-8")
    assert "summary_source: model" in raw
    path.write_text(
        "\n".join(line for line in raw.splitlines() if not line.startswith("summary_source:")) + "\n",
        encoding="utf-8",
    )
    loaded = store.load_note("creator-a", "abc123")
    assert loaded is not None and loaded.summary_source == "model"


def test_module_exports_the_pinned_names() -> None:
    # The API worker builds against these; a rename here is a contract break, not a refactor.
    for name in (
        "BackfillMention", "BackfillResult", "BackfillResultInvalid", "BackfillValidationFailed",
        "ValidationReport", "parse_result", "validate_result", "ingest_result",
    ):
        assert hasattr(backfill_ingest, name), name
    assert BackfillMention(symbol="NVDA", stance="bullish").horizon == "unclear"
    assert BackfillResult(summary="s", themes=(), quotes=(), mentions=()).mentions == ()
