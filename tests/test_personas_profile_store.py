"""Tests for `app.personas.profile_store.ProfileStore`: `profile.md`, its `profile.history/` archive,
and per-symbol `theses/<SYMBOL>.md`.

Every test uses the `settings` fixture from `tests/conftest.py`, which redirects `INVDASH_VAULT_DIR`
into `tmp_path` -- nothing here ever touches a real vault. `_make_profile`/`_make_thesis` build
fully-populated models with sensible defaults so each test only has to override what it is actually
exercising.
"""

from __future__ import annotations

import datetime as dt

from app.config import Settings
from app.personas.models import PersonaProfile, ProfileClaim, RegimeView, TickerThesis, persona_dir
from app.personas.profile_store import ProfileStore

_UTC = dt.UTC


def _make_profile(
    *,
    persona: str = "creator-a",
    version: int = 1,
    consolidated_at: dt.datetime = dt.datetime(2026, 9, 2, 7, 40, tzinfo=_UTC),
    note_count: int = 20,
    summary: str = "A Korean market commentator focused on semiconductors and EVs.",
    beliefs: tuple[ProfileClaim, ...] = (
        ProfileClaim(text="Believes AI capex is still expanding.", citations=("vidAAAAAA01",)),
    ),
    playbook: tuple[ProfileClaim, ...] = (
        ProfileClaim(text="Buys pullbacks to the 20-day moving average.", citations=("vidB-bbbbb2",)),
    ),
    methodology: tuple[ProfileClaim, ...] = (),
    regime: RegimeView | None = None,
    vocabulary: tuple[str, ...] = ("박스권", "눌림목"),
    degraded: bool = False,
) -> PersonaProfile:
    return PersonaProfile(
        persona=persona,
        version=version,
        consolidated_at=consolidated_at,
        note_count=note_count,
        summary=summary,
        beliefs=beliefs,
        playbook=playbook,
        methodology=methodology,
        regime=regime,
        vocabulary=vocabulary,
        degraded=degraded,
        # save_profile derives its own target location from `persona` -- see the store's module
        # docstring -- so this placeholder proves the incoming value is never consulted.
        path="placeholder",
    )


def _make_thesis(
    *,
    persona: str = "creator-a",
    symbol: str = "nvda",
    stance: str = "bullish",
    updated_at: dt.datetime = dt.datetime(2026, 9, 2, 7, 40, tzinfo=_UTC),
    claims: tuple[ProfileClaim, ...] = (
        ProfileClaim(text="Strong earnings beat expectations.", citations=("vidAAAAAA01",)),
    ),
) -> TickerThesis:
    return TickerThesis(
        persona=persona,
        symbol=symbol,
        stance=stance,  # type: ignore[arg-type]
        updated_at=updated_at,
        claims=claims,
        path="placeholder",
    )


# --- profile: basic round trip -----------------------------------------------------


def test_save_and_load_profile_round_trip(settings: Settings) -> None:
    store = ProfileStore(settings)
    profile = _make_profile()
    path = store.save_profile(profile)
    assert path.is_file()

    loaded = store.load_profile(profile.persona)
    expected_path = f"influencers/{profile.persona}/profile.md"
    assert loaded == profile.model_copy(update={"path": expected_path})


def test_save_profile_ignores_incoming_path_field(settings: Settings) -> None:
    store = ProfileStore(settings)
    profile = _make_profile()
    assert profile.path == "placeholder"
    store.save_profile(profile)
    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.path == f"influencers/{profile.persona}/profile.md"


def test_load_profile_missing_returns_none(settings: Settings) -> None:
    assert ProfileStore(settings).load_profile("does-not-exist") is None


def test_save_profile_writes_readable_markdown(settings: Settings) -> None:
    store = ProfileStore(settings)
    path = store.save_profile(_make_profile())
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---\n")
    assert "## Summary" in raw
    assert "## Beliefs" in raw
    assert "## Playbook" in raw


def test_profile_frontmatter_and_body_shape(settings: Settings) -> None:
    """Loosely pin the frontmatter and citation-link rendering the contract's own example lays out."""
    store = ProfileStore(settings)
    profile = _make_profile()
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")
    assert "persona: creator-a" in raw
    assert "version: 1" in raw
    assert "vocabulary: [박스권, 눌림목]" in raw
    assert "[[vidAAAAAA01]]" in raw
    assert "[[vidB-bbbbb2]]" in raw


# --- profile: multi-citation claims -------------------------------------------------


def test_multi_citation_claim_round_trips(settings: Settings) -> None:
    store = ProfileStore(settings)
    profile = _make_profile(
        beliefs=(
            ProfileClaim(
                text="Consistently bullish on AI capex across many videos.",
                citations=("vidAAAAAA01", "vidB-bbbbb2", "vidC-ccc-c3"),
            ),
        ),
    )
    store.save_profile(profile)
    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.beliefs[0].citations == ("vidAAAAAA01", "vidB-bbbbb2", "vidC-ccc-c3")
    assert loaded.beliefs[0].text == "Consistently bullish on AI capex across many videos."


# --- profile: colon/quote survival in prose ------------------------------------------


def test_summary_and_claim_text_with_colon_and_quote_round_trip(settings: Settings) -> None:
    store = ProfileStore(settings)
    tricky_summary = 'Markets: "risk-on" mode, up & down, a backslash \\ at the end.'
    tricky_claim_text = 'Says "buy the dip" when RSI: 14 drops below 30.'
    profile = _make_profile(
        summary=tricky_summary,
        beliefs=(ProfileClaim(text=tricky_claim_text, citations=("vidAAAAAA01",)),),
    )
    store.save_profile(profile)
    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.summary == tricky_summary
    assert loaded.beliefs[0].text == tricky_claim_text


# --- profile: Korean round trip ------------------------------------------------------


def test_korean_summary_beliefs_and_vocabulary_round_trip(settings: Settings) -> None:
    store = ProfileStore(settings)
    profile = _make_profile(
        summary="이 분석가는 반도체와 전기차 섹터에 집중합니다.",
        beliefs=(
            ProfileClaim(text="AI 관련 설비 투자가 계속 확대되고 있다고 믿습니다.", citations=("n1",)),
        ),
        playbook=(
            ProfileClaim(text="눌림목에서 분할 매수하는 전략을 씁니다.", citations=("n2", "n3")),
        ),
        vocabulary=("박스권", "눌림목", "손절"),
    )
    store.save_profile(profile)
    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.summary == profile.summary
    assert loaded.beliefs == profile.beliefs
    assert loaded.playbook == profile.playbook
    assert loaded.vocabulary == profile.vocabulary


# --- profile: methodology (Phase 7a) -------------------------------------------------


def test_methodology_round_trips_with_korean_text_and_multi_citation(settings: Settings) -> None:
    store = ProfileStore(settings)
    profile = _make_profile(
        methodology=(
            ProfileClaim(
                text="RSI(14)가 30 아래로 떨어지면 분할 매수를 시작합니다.",
                citations=("n1", "n2", "n3"),
            ),
        ),
    )
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")
    assert "## Methodology" in raw
    assert raw.index("## Playbook") < raw.index("## Methodology")
    assert "[[n1]]" in raw and "[[n2]]" in raw and "[[n3]]" in raw

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.methodology == profile.methodology
    assert loaded.methodology[0].citations == ("n1", "n2", "n3")


def test_empty_methodology_omits_section_and_round_trips_as_empty_tuple(
    settings: Settings,
) -> None:
    store = ProfileStore(settings)
    profile = _make_profile(methodology=())
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")
    assert "## Methodology" not in raw

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.methodology == ()


def test_legacy_profile_with_no_methodology_section_loads_with_empty_tuple(
    settings: Settings,
) -> None:
    """A profile.md written before Phase 7a added `methodology` has no `## Methodology` heading at
    all -- it must still load, not fail, with `methodology=()` rather than requiring the section."""
    store = ProfileStore(settings)
    profile = _make_profile()
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")
    assert "## Methodology" not in raw  # sanity: the fixture itself has no methodology

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.methodology == ()


def test_methodology_line_with_no_citation_is_skipped_not_loaded_uncited(
    settings: Settings,
) -> None:
    store = ProfileStore(settings)
    profile = _make_profile(
        methodology=(ProfileClaim(text="Cited methodology claim.", citations=("n1",)),),
    )
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")

    corrupted = raw.replace(
        "## Methodology\n- Cited methodology claim. [[n1]]",
        "## Methodology\n- Cited methodology claim. [[n1]]\n- An uncited methodology line.",
    )
    assert corrupted != raw
    path.write_text(corrupted, encoding="utf-8")

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert len(loaded.methodology) == 1
    assert loaded.methodology[0].text == "Cited methodology claim."


# --- profile: regime (macro/regime commentator view) --------------------------------


def test_regime_round_trips_with_all_fields(settings: Settings) -> None:
    store = ProfileStore(settings)
    regime = RegimeView(
        risk="mixed",
        rates="Expects the Fed to hold through year-end.",
        summary="Cautiously bullish on risk assets while rates stay on hold.",
        sectors_favoured=("semiconductors", "EVs"),
        sectors_avoided=("real estate",),
        citations=("n1", "n2"),
        has_signal=True,
    )
    profile = _make_profile(
        regime=regime,
        methodology=(ProfileClaim(text="Watches the 50-day moving average.", citations=("n3",)),),
    )
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")
    assert "## Regime" in raw
    assert raw.index("## Methodology") < raw.index("## Regime")
    assert "risk: mixed" in raw
    assert "[semiconductors, EVs]" in raw
    assert "[real estate]" in raw
    assert "[n1, n2]" in raw

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.regime == regime


def test_regime_none_omits_section_and_round_trips_as_none(settings: Settings) -> None:
    store = ProfileStore(settings)
    profile = _make_profile(regime=None)
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")
    assert "## Regime" not in raw

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.regime is None


def test_regime_with_has_signal_false_omits_section_and_round_trips_as_none(
    settings: Settings,
) -> None:
    """A `RegimeView` that is present but says nothing (`has_signal=False`, the pure-technical-trader
    case) must render no `## Regime` section at all -- and, since a missing section is indistinguishable
    from "no RegimeView", it loads back as `regime=None`, not as the original `has_signal=False` view."""
    store = ProfileStore(settings)
    regime = RegimeView(
        risk="on",
        rates="This should never be written.",
        summary="Neither should this.",
        sectors_favoured=("tech",),
        citations=("n1",),
        has_signal=False,
    )
    profile = _make_profile(regime=regime)
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")
    assert "## Regime" not in raw
    assert "This should never be written." not in raw

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.regime is None


def test_legacy_profile_with_no_regime_section_loads_with_none(settings: Settings) -> None:
    """A profile.md written before `regime` existed has no `## Regime` heading at all -- it must
    still load, not fail, with `regime=None` rather than requiring the section."""
    store = ProfileStore(settings)
    profile = _make_profile()
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")
    assert "## Regime" not in raw  # sanity: the fixture itself has no regime

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.regime is None


def test_regime_korean_text_round_trips(settings: Settings) -> None:
    store = ProfileStore(settings)
    regime = RegimeView(
        risk="off",
        rates="연준이 금리를 동결할 것으로 예상합니다.",
        summary="위험자산에 대해 신중한 입장입니다.",
        sectors_favoured=("반도체", "전기차"),
        sectors_avoided=("부동산",),
        citations=("n1", "n2", "n3"),
        has_signal=True,
    )
    profile = _make_profile(regime=regime)
    store.save_profile(profile)

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    assert loaded.regime == regime


# --- profile: history archiving -----------------------------------------------------


def test_save_profile_archives_previous_version(settings: Settings) -> None:
    store = ProfileStore(settings)
    v1 = _make_profile(version=1, consolidated_at=dt.datetime(2026, 9, 1, tzinfo=_UTC))
    store.save_profile(v1)
    assert store.profile_history(v1.persona) == ()

    v2 = _make_profile(version=2, consolidated_at=dt.datetime(2026, 9, 2, tzinfo=_UTC))
    store.save_profile(v2)

    history = store.profile_history(v1.persona)
    assert len(history) == 1

    history_dir = persona_dir(settings, v1.persona) / "profile.history"
    archived_raw = (history_dir / history[0]).read_text(encoding="utf-8")
    assert "version: 1" in archived_raw

    # profile.md itself now holds the new version, not the archived one.
    loaded = store.load_profile(v1.persona)
    assert loaded is not None
    assert loaded.version == 2


def test_profile_history_lists_newest_first(settings: Settings) -> None:
    store = ProfileStore(settings)
    store.save_profile(_make_profile(version=1, consolidated_at=dt.datetime(2026, 9, 1, tzinfo=_UTC)))
    store.save_profile(_make_profile(version=2, consolidated_at=dt.datetime(2026, 9, 2, tzinfo=_UTC)))
    store.save_profile(_make_profile(version=3, consolidated_at=dt.datetime(2026, 9, 3, tzinfo=_UTC)))

    history = store.profile_history("creator-a")
    assert len(history) == 2  # v1 and v2 archived; v3 is the current profile.md

    history_dir = persona_dir(settings, "creator-a") / "profile.history"
    versions = []
    for name in history:
        raw = (history_dir / name).read_text(encoding="utf-8")
        versions.append("version: 2" in raw)
    # Newest-first: the v2 archive (consolidated 2026-09-02) must come before the v1 archive.
    assert versions == [True, False]


def test_profile_history_on_never_consolidated_persona_returns_empty_tuple(
    settings: Settings,
) -> None:
    assert ProfileStore(settings).profile_history("does-not-exist") == ()


def test_history_is_never_deleted_across_many_saves(settings: Settings) -> None:
    store = ProfileStore(settings)
    for version in range(1, 5):
        store.save_profile(
            _make_profile(
                version=version,
                consolidated_at=dt.datetime(2026, 9, version, tzinfo=_UTC),
            )
        )
    # 4 saves: versions 1-3 archived, version 4 is the live profile.md.
    assert len(store.profile_history("creator-a")) == 3


# --- profile: version listing and lookup ---------------------------------------------


def test_list_versions_after_multiple_saves(settings: Settings) -> None:
    store = ProfileStore(settings)
    store.save_profile(_make_profile(version=1, consolidated_at=dt.datetime(2026, 9, 1, tzinfo=_UTC)))
    store.save_profile(_make_profile(version=2, consolidated_at=dt.datetime(2026, 9, 2, tzinfo=_UTC)))
    store.save_profile(_make_profile(version=3, consolidated_at=dt.datetime(2026, 9, 3, tzinfo=_UTC)))

    assert store.list_versions("creator-a") == (1, 2, 3)


def test_list_versions_on_never_consolidated_persona_returns_empty_tuple(
    settings: Settings,
) -> None:
    assert ProfileStore(settings).list_versions("does-not-exist") == ()


def test_list_versions_with_single_save_returns_one_version(settings: Settings) -> None:
    store = ProfileStore(settings)
    store.save_profile(_make_profile(version=1))
    assert store.list_versions("creator-a") == (1,)


def test_load_version_fetches_current_and_archived_versions(settings: Settings) -> None:
    store = ProfileStore(settings)
    v1 = _make_profile(
        version=1,
        consolidated_at=dt.datetime(2026, 9, 1, tzinfo=_UTC),
        summary="First consolidation.",
    )
    v2 = _make_profile(
        version=2,
        consolidated_at=dt.datetime(2026, 9, 2, tzinfo=_UTC),
        summary="Second consolidation.",
    )
    store.save_profile(v1)
    store.save_profile(v2)

    loaded_v1 = store.load_version("creator-a", 1)
    loaded_v2 = store.load_version("creator-a", 2)
    assert loaded_v1 is not None
    assert loaded_v2 is not None
    assert loaded_v1.version == 1
    assert loaded_v1.summary == "First consolidation."
    assert loaded_v2.version == 2
    assert loaded_v2.summary == "Second consolidation."
    # v2 is the live profile.md; v1 is archived -- both must be reachable by version number alone.
    assert loaded_v2.path == "influencers/creator-a/profile.md"
    assert loaded_v1.path != loaded_v2.path


def test_load_version_unknown_version_returns_none(settings: Settings) -> None:
    store = ProfileStore(settings)
    store.save_profile(_make_profile(version=1))
    assert store.load_version("creator-a", 99) is None


def test_load_version_on_never_consolidated_persona_returns_none(settings: Settings) -> None:
    assert ProfileStore(settings).load_version("does-not-exist", 1) is None


def test_load_version_can_diff_two_consolidations(settings: Settings) -> None:
    """The stated purpose of `list_versions`/`load_version`: a caller loads two versions to compare
    what drifted between them."""
    store = ProfileStore(settings)
    store.save_profile(
        _make_profile(
            version=1,
            consolidated_at=dt.datetime(2026, 9, 1, tzinfo=_UTC),
            beliefs=(ProfileClaim(text="Old belief.", citations=("n1",)),),
        )
    )
    store.save_profile(
        _make_profile(
            version=2,
            consolidated_at=dt.datetime(2026, 9, 2, tzinfo=_UTC),
            beliefs=(ProfileClaim(text="New belief.", citations=("n2",)),),
        )
    )

    versions = store.list_versions("creator-a")
    assert versions == (1, 2)
    old = store.load_version("creator-a", versions[0])
    new = store.load_version("creator-a", versions[-1])
    assert old is not None
    assert new is not None
    assert old.beliefs[0].text == "Old belief."
    assert new.beliefs[0].text == "New belief."


# --- profile: corrupt-file handling --------------------------------------------------


def test_load_profile_for_corrupt_file_returns_none(settings: Settings) -> None:
    directory = persona_dir(settings, "creator-a")
    directory.mkdir(parents=True)
    (directory / "profile.md").write_text("garbage, no frontmatter", encoding="utf-8")
    assert ProfileStore(settings).load_profile("creator-a") is None


def test_save_profile_over_corrupt_prior_still_archives_it(settings: Settings) -> None:
    """A corrupt `profile.md` (e.g. hand-edited) must not block a new consolidation, and must not be
    silently discarded -- it is still archived, falling back to file mtime for the archive name since
    it has no readable `consolidated_at`."""
    directory = persona_dir(settings, "creator-a")
    directory.mkdir(parents=True)
    (directory / "profile.md").write_text("garbage, no frontmatter", encoding="utf-8")

    store = ProfileStore(settings)
    store.save_profile(_make_profile(version=1))

    history = store.profile_history("creator-a")
    assert len(history) == 1
    history_dir = directory / "profile.history"
    assert (history_dir / history[0]).read_text(encoding="utf-8") == "garbage, no frontmatter"


# --- claim lines: missing citation is skipped, not raised ---------------------------


def test_claim_line_with_no_citation_is_skipped_not_loaded_uncited(settings: Settings) -> None:
    store = ProfileStore(settings)
    profile = _make_profile(
        beliefs=(ProfileClaim(text="A cited belief.", citations=("n1",)),),
    )
    path = store.save_profile(profile)
    raw = path.read_text(encoding="utf-8")

    # Hand-edit in an uncited belief line, simulating an external editor stripping citations.
    corrupted = raw.replace(
        "## Beliefs\n- A cited belief. [[n1]]",
        "## Beliefs\n- A cited belief. [[n1]]\n- An uncited belief with no citation at all.",
    )
    assert corrupted != raw
    path.write_text(corrupted, encoding="utf-8")

    loaded = store.load_profile(profile.persona)
    assert loaded is not None
    # Only the cited belief survives; the uncited line is dropped, not raised as invalid, and never
    # constructed with an invented or empty citation.
    assert len(loaded.beliefs) == 1
    assert loaded.beliefs[0].text == "A cited belief."


def test_thesis_claim_line_with_no_citation_is_skipped(settings: Settings) -> None:
    store = ProfileStore(settings)
    thesis = _make_thesis(claims=(ProfileClaim(text="Cited claim.", citations=("n1",)),))
    path = store.save_thesis(thesis)
    raw = path.read_text(encoding="utf-8")
    corrupted = raw.replace(
        "## Claims\n- Cited claim. [[n1]]",
        "## Claims\n- Cited claim. [[n1]]\n- Uncited claim.",
    )
    assert corrupted != raw
    path.write_text(corrupted, encoding="utf-8")

    loaded = store.load_thesis(thesis.persona, thesis.symbol)
    assert loaded is not None
    assert len(loaded.claims) == 1
    assert loaded.claims[0].text == "Cited claim."


# --- theses: basic round trip --------------------------------------------------------


def test_save_and_load_thesis_round_trip(settings: Settings) -> None:
    store = ProfileStore(settings)
    thesis = _make_thesis()
    path = store.save_thesis(thesis)
    assert path.is_file()

    loaded = store.load_thesis(thesis.persona, "NVDA")
    expected_path = f"influencers/{thesis.persona}/theses/NVDA.md"
    assert loaded == thesis.model_copy(update={"path": expected_path, "symbol": "NVDA"})


def test_save_thesis_ignores_incoming_path_field(settings: Settings) -> None:
    store = ProfileStore(settings)
    thesis = _make_thesis(symbol="tsla")
    assert thesis.path == "placeholder"
    store.save_thesis(thesis)
    loaded = store.load_thesis(thesis.persona, "TSLA")
    assert loaded is not None
    assert loaded.path == f"influencers/{thesis.persona}/theses/TSLA.md"


def test_save_thesis_symbol_is_case_insensitive_on_lookup(settings: Settings) -> None:
    store = ProfileStore(settings)
    store.save_thesis(_make_thesis(symbol="NVDA"))
    assert store.load_thesis("creator-a", "nvda") is not None


def test_load_thesis_missing_returns_none(settings: Settings) -> None:
    assert ProfileStore(settings).load_thesis("does-not-exist", "NVDA") is None


def test_save_thesis_overwrites_in_place(settings: Settings) -> None:
    store = ProfileStore(settings)
    store.save_thesis(_make_thesis(stance="bullish"))
    store.save_thesis(_make_thesis(stance="bearish"))
    loaded = store.load_thesis("creator-a", "NVDA")
    assert loaded is not None
    assert loaded.stance == "bearish"


# --- theses: listing -------------------------------------------------------------------


def test_list_theses_on_persona_with_no_theses_returns_empty_tuple(settings: Settings) -> None:
    assert ProfileStore(settings).list_theses("does-not-exist") == ()


def test_list_theses_sorted_by_symbol(settings: Settings) -> None:
    store = ProfileStore(settings)
    store.save_thesis(_make_thesis(symbol="TSLA"))
    store.save_thesis(_make_thesis(symbol="AAPL"))
    store.save_thesis(_make_thesis(symbol="NVDA"))
    assert [t.symbol for t in store.list_theses("creator-a")] == ["AAPL", "NVDA", "TSLA"]


def test_list_theses_skips_unparseable_file(settings: Settings) -> None:
    store = ProfileStore(settings)
    store.save_thesis(_make_thesis(symbol="NVDA"))
    theses_dir = persona_dir(settings, "creator-a") / "theses"
    (theses_dir / "BAD.md").write_text("not frontmatter at all", encoding="utf-8")
    assert [t.symbol for t in store.list_theses("creator-a")] == ["NVDA"]


def test_load_thesis_for_corrupt_file_returns_none(settings: Settings) -> None:
    theses_dir = persona_dir(settings, "creator-a") / "theses"
    theses_dir.mkdir(parents=True)
    (theses_dir / "BAD.md").write_text("garbage, no frontmatter", encoding="utf-8")
    assert ProfileStore(settings).load_thesis("creator-a", "BAD") is None


# --- theses: Korean claim text --------------------------------------------------------


def test_thesis_korean_claims_round_trip(settings: Settings) -> None:
    store = ProfileStore(settings)
    thesis = _make_thesis(
        symbol="NVDA",
        claims=(
            ProfileClaim(text="실적이 예상치를 크게 상회했습니다.", citations=("n1", "n2")),
        ),
    )
    store.save_thesis(thesis)
    loaded = store.load_thesis("creator-a", "NVDA")
    assert loaded is not None
    assert loaded.claims == thesis.claims
