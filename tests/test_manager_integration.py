"""Cross-layer integration for the manager desk: `collect() -> save() -> diff()` composed with the
REAL modules, no mocks.

Every other manager test file exercises one shard against fakes, which is exactly the shape of test
that stays green while two shards quietly disagree (see the repo's own "subagent tests inherit the
brief's premise" lesson). These assertions are therefore about the *contract between* layers -- the
figure-key vocabulary, the rule-id vocabulary, id stability, and the fail-soft bookkeeping -- so they
hold on an empty temp-rooted install where most sources have nothing to read.

Aligned to the settled `app.manager.sources` contract: `collect(settings, *, scope, as_of=None)`,
and a member snapshot marks the owner-only areas `ok=False` (present-but-withheld) rather than
omitting them, so they still appear in `sections` and in `ChangeSet.sections_missing`.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

import pytest

from app.config import Settings
from app.manager import rules, snapshots
from app.manager.models import AREAS, FIGURE_KEYS, RULES
from app.manager.sources import collect

#: The areas a member snapshot withholds. Kept as a literal here rather than imported so this test
#: pins the intended set even if the source module renames its private constant.
OWNER_ONLY_AREAS = frozenset({"account", "tax", "activity"})


def _decimalish(value: str) -> bool:
    try:
        Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        return False
    return True


# ---------------------------------------------------------------------------
# Layer A -- the bus honours its own vocabulary
# ---------------------------------------------------------------------------


def test_collect_returns_every_area_in_order(settings: Settings) -> None:
    snap = collect(settings, scope="owner")
    assert [s.key for s in snap.sections] == list(AREAS)
    assert snap.scope == "owner"


def test_member_snapshot_never_exposes_owner_only_data(settings: Settings) -> None:
    """The invariant that actually matters, stated so it holds under either withholding design: for a
    member, an owner-only area must carry no figures and no items -- whether it is omitted from
    `sections` entirely or present as an `ok=False` withheld section. Owner account/tax data must
    never reach a non-owner snapshot."""
    snap = collect(settings, scope="member")
    for area in OWNER_ONLY_AREAS:
        section = snap.section(area)
        if section is None:
            continue  # omitted entirely -- also acceptable
        assert section.ok is False, f"{area} present for a member must be ok=False"
        assert not section.items and not section.figures, f"{area} leaked owner data to a member"


def test_collect_never_raises_and_names_what_it_could_not_read(settings: Settings) -> None:
    snap = collect(settings, scope="owner")
    for section in snap.sections:
        if not section.ok:
            assert section.warnings, f"{section.key} failed without saying why"
            assert not section.items, f"{section.key} failed but still emitted items"
            assert not section.figures, f"{section.key} failed but still emitted figures"


def test_every_figure_key_is_in_the_pinned_vocabulary(settings: Settings) -> None:
    """The one contract both source shards must independently honour. A typo'd figure name here is a
    rule that silently never fires downstream -- the worst failure mode in the feature."""
    snap = collect(settings, scope="owner")
    for section in snap.sections:
        allowed = set(FIGURE_KEYS.get(section.key, ()))
        assert set(section.figures) <= allowed, f"{section.key} section: {set(section.figures) - allowed}"
        for item in section.items:
            assert set(item.figures) <= allowed, f"{section.key}/{item.id}: {set(item.figures) - allowed}"


def test_every_figure_value_is_a_decimal_string(settings: Settings) -> None:
    snap = collect(settings, scope="owner")
    for section in snap.sections:
        for key, value in section.figures.items():
            assert _decimalish(value), f"{section.key}.{key} = {value!r} is not a decimal string"
        for item in section.items:
            for key, value in item.figures.items():
                assert _decimalish(value), f"{section.key}/{item.id}.{key} = {value!r}"


def test_item_ids_are_unique_within_a_section(settings: Settings) -> None:
    snap = collect(settings, scope="owner")
    for section in snap.sections:
        ids = [i.id for i in section.items]
        assert len(ids) == len(set(ids)), f"{section.key} has duplicate item ids"


# ---------------------------------------------------------------------------
# Layer B -- persistence and the diff, composed on real snapshots
# ---------------------------------------------------------------------------


def test_snapshot_round_trips_through_disk(settings: Settings) -> None:
    snap = collect(settings, scope="owner")
    path = snapshots.save(settings, snap)
    assert path.is_file()
    assert snapshots.load(settings, dt.date.fromisoformat(snap.as_of), "owner") == snap


def test_diff_with_no_prior_snapshot_is_streams_only_not_a_crash(settings: Settings) -> None:
    snap = collect(settings, scope="owner")
    changes = rules.diff(snap, None, window="yesterday")
    assert changes.since is None
    assert changes.prior_snapshot is None
    assert changes.until == snap.as_of


def test_diff_emits_only_pinned_rule_ids(settings: Settings) -> None:
    today = collect(settings, scope="owner")
    prev_date = (dt.date.fromisoformat(today.as_of) - dt.timedelta(days=1)).isoformat()
    yesterday = today.model_copy(update={"as_of": prev_date})
    changes = rules.diff(today, yesterday, window="yesterday", prior_snapshot=yesterday.as_of)
    for item in changes.items:
        assert item.rule in RULES, f"unpinned rule id {item.rule!r}"
        assert item.area in AREAS
        for key, value in item.figures.items():
            assert _decimalish(value), f"{item.rule}.{key} = {value!r}"


def test_diff_names_missing_sections_rather_than_calling_them_unchanged(settings: Settings) -> None:
    snap = collect(settings, scope="owner")
    failed = {s.key for s in snap.sections if not s.ok}
    changes = rules.diff(snap, None, window="yesterday")
    assert set(changes.sections_missing) == failed


@pytest.mark.parametrize("window", ["yesterday", "week", "custom"])
def test_every_window_produces_a_well_formed_changeset(settings: Settings, window: str) -> None:
    snap = collect(settings, scope="owner")
    changes = rules.diff(snap, None, window=window)  # type: ignore[arg-type]
    assert changes.window == window
    assert changes.scope == "owner"
    for item in changes.items:
        assert len(item.headline) <= 160
        assert len(item.detail) <= 320
