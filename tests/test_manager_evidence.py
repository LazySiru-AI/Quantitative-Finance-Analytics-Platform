"""The manager evidence assembler: `ManagerSnapshot` + `ChangeSet` -> a grounded `EvidencePack`.

Guards the properties layer C depends on: every snapshot figure is minted as a groundable item,
prose stays in `text` (never grounded), failed sections contribute a warning not a fabricated zero,
`focus_areas` narrows the pack, and the change set is always its own section.
"""

from __future__ import annotations

from decimal import Decimal

from app.agentdesk.grounding import grounded_values
from app.manager.evidence import build_pack, render_change_lines
from app.manager.models import (
    ChangeItem,
    ChangeSet,
    ManagerSnapshot,
    SectionItem,
    SnapshotSection,
    SourceRef,
)


def _snap(*sections: SnapshotSection) -> ManagerSnapshot:
    return ManagerSnapshot(
        scope="owner", as_of="2026-09-09", generated_at="2026-09-09T12:00:00Z", sections=sections,
    )


def _account() -> SnapshotSection:
    return SnapshotSection(
        key="account", ok=True, as_of="2026-09-09", text="2 positions",
        figures={"total_market_value": "1000.00"},
        items=(
            SectionItem(id="NVDA", label="NVDA", figures={"weight_pct": "0.31"}, text="NVDA 31%",
                        refs=(SourceRef(kind="symbol", id="NVDA", label="NVDA"),)),
        ),
    )


def _empty_changes(snap: ManagerSnapshot) -> ChangeSet:
    return ChangeSet(window="yesterday", since=None, until=snap.as_of, scope="owner")


def test_every_snapshot_figure_is_grounded() -> None:
    snap = _snap(_account())
    pack = build_pack(snap, _empty_changes(snap))
    grounded = grounded_values(pack)
    # grounded_values normalises (1000.00 -> 1000), so match on a normalised prefix, not the literal.
    assert any(v.startswith("1000") for v in grounded)  # section total minted
    assert "0.31" in grounded                            # item figure minted verbatim


def test_failed_section_becomes_a_warning_not_a_body() -> None:
    snap = _snap(_account(), SnapshotSection(key="tax", ok=False, warnings=("owner-only; omitted",)))
    pack = build_pack(snap, _empty_changes(snap))
    titles = [s.title for s in pack.sections]
    assert not any("tax" in t for t in titles)
    assert any("tax" in w for w in pack.warnings)


def test_change_set_is_always_its_own_section() -> None:
    snap = _snap(_account())
    changes = ChangeSet(
        window="yesterday", since="2026-09-08", until="2026-09-09", scope="owner",
        items=(ChangeItem(id="c1", area="account", rule="position_weight_moved", severity="notable",
                          headline="NVDA weight moved", figures={"weight_pct": "0.31"}),),
    )
    pack = build_pack(snap, changes)
    change_secs = [s for s in pack.sections if s.title.startswith("Changes since")]
    assert len(change_secs) == 1
    assert "0.31" in grounded_values(pack)


def test_focus_areas_narrows_the_pack() -> None:
    snap = _snap(
        _account(),
        SnapshotSection(key="market", ok=True, figures={"fear_greed": "64"}, text="fear/greed 64"),
    )
    pack = build_pack(snap, _empty_changes(snap), focus_areas=("account",))
    titles = [s.title for s in pack.sections]
    assert any("account" in t for t in titles)
    assert not any("market" in t for t in titles)


def test_all_failed_snapshot_yields_no_state_sections() -> None:
    snap = _snap(SnapshotSection(key="account", ok=False, warnings=("x",)))
    pack = build_pack(snap, ChangeSet(window="yesterday", since=None, until="2026-09-09", scope="owner"))
    # No State: section survives; only the change section (which always carries the "no changes"
    # placeholder prose, so the pack is deliberately not `is_empty`), and the failure is warned.
    assert not any(s.title.startswith("State") for s in pack.sections)
    assert any("account" in w for w in pack.warnings)


def test_render_change_lines_is_stable() -> None:
    items = (
        ChangeItem(id="c1", area="tax", rule="wash_window_closing", severity="attention",
                   headline="MU window closes in 2d"),
    )
    line = render_change_lines(items)
    assert "[attention]" in line and "tax" in line and "MU" in line
    assert render_change_lines(()) == "(no changes detected in this window)"


def test_figures_are_decimal_strings() -> None:
    snap = _snap(_account())
    pack = build_pack(snap, _empty_changes(snap))
    for section in pack.sections:
        for item in section.items:
            Decimal(item.value)  # raises if a float repr or unit leaked in
