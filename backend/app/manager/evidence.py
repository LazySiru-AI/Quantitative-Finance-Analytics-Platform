"""Layer C's evidence assembler: turn a `ManagerSnapshot` + `ChangeSet` into an
`app.agentdesk.models.EvidencePack` the manager's grounded stages read and are checked against.

**Why this is a manager-specific assembler and not `app.agentdesk.evidence.build_pack`.** That
builder is single-symbol with a closed section vocabulary (price/indicators/news/...); the manager's
evidence is the whole app's state across fourteen non-symbol areas. So this module builds the pack
from the manager's own shapes, following the *same* `EvidenceItem(key, label, value, unit, as_of,
source)` convention so `app.agentdesk.grounding.grounded_values` / `numeric_tokens` keep working
unmodified -- every figure the model is allowed to quote is minted as an item; free prose goes in
`EvidenceSection.text`, which the gate renders but never treats as quotable (exactly as the base
evidence layer intends).

The result is a `symbol=""` macro-shaped pack: one `EvidenceSection` per snapshot section that
collected, its `figures` and every item's `figures` minted as `EvidenceItem`s, plus one section for
the change set so the model may cite a change's own numbers. Sections that failed to collect
(`ok=False`) contribute nothing but a warning -- the model is told what could not be seen rather than
being handed a fabricated zero, the whole feature's standing rule.
"""

from __future__ import annotations

import datetime as dt

from app.agentdesk.models import EvidenceItem, EvidencePack, EvidenceSection
from app.manager.models import ChangeItem, ChangeSet, ManagerSnapshot, SnapshotSection

__all__ = ["build_pack", "render_change_lines"]


def _section_items(section: SnapshotSection) -> tuple[EvidenceItem, ...]:
    """Every figure in a snapshot section -- the section-level totals and each item's own figures --
    minted as a grounded `EvidenceItem`. Keys are namespaced (`<area>.<figure>`,
    `<area>.<item_id>.<figure>`) so they stay unique within the one big manager section and a reader
    of the pack can see which row a number came from."""
    items: list[EvidenceItem] = []
    for key, value in section.figures.items():
        items.append(
            EvidenceItem(
                key=f"{section.key}.{key}", label=f"{section.key} {key}", value=value,
                as_of=section.as_of or "", source="manager-snapshot",
            )
        )
    for row in section.items:
        for key, value in row.figures.items():
            items.append(
                EvidenceItem(
                    key=f"{section.key}.{row.id}.{key}", label=f"{row.label} {key}", value=value,
                    as_of=row.observed_at or section.as_of or "", source="manager-snapshot",
                )
            )
    return tuple(items)


def _section_text(section: SnapshotSection) -> str:
    """The prose a section contributes: its own summary line plus each item's one-line `text`. Free
    prose only -- numbers here are NOT grounded (that is what the `figures` above are for), matching
    `EvidenceSection.text`'s contract."""
    lines: list[str] = []
    if section.text:
        lines.append(section.text)
    for row in section.items:
        if row.text:
            lines.append(f"- {row.text}")
    return "\n".join(lines)


def render_change_lines(items: tuple[ChangeItem, ...]) -> str:
    """The change set rendered as readable prose for the model, one line per change, newest concerns
    first as the caller ordered them. Severity and area are prefixes; the headline is the line."""
    if not items:
        return "(no changes detected in this window)"
    return "\n".join(f"[{item.severity}] {item.area}: {item.headline}" for item in items)


def _change_items(changes: ChangeSet) -> tuple[EvidenceItem, ...]:
    """Every figure carried on a `ChangeItem`, minted so the model may quote a change's own numbers
    (a weight that moved, days-until-safe) without the gate rejecting them."""
    out: list[EvidenceItem] = []
    for change in changes.items:
        for key, value in change.figures.items():
            out.append(
                EvidenceItem(
                    key=f"change.{change.id}.{key}", label=f"{change.rule} {key}", value=value,
                    as_of=change.observed_at or change.as_of or "", source="manager-change",
                )
            )
    return tuple(out)


def build_pack(
    snapshot: ManagerSnapshot,
    changes: ChangeSet,
    *,
    focus_areas: tuple[str, ...] | None = None,
) -> EvidencePack:
    """Assemble the manager evidence pack. `focus_areas`, when given, keeps only those snapshot
    sections (used by chat to narrow the pack to the areas a question is about); `None` includes every
    collected section. The change set is always included as its own section -- it is the spine of a
    brief. Failed sections are dropped from the body but named in `warnings`, so the model is told what
    it could not see."""
    sections: list[EvidenceSection] = []
    warnings: list[str] = list(snapshot.warnings)

    for section in snapshot.sections:
        if focus_areas is not None and section.key not in focus_areas:
            continue
        if not section.ok:
            reason = section.warnings[0] if section.warnings else "unavailable"
            warnings.append(f"{section.key}: {reason}")
            continue
        sections.append(
            EvidenceSection(
                title=f"State: {section.key}",
                items=_section_items(section),
                text=_section_text(section),
            )
        )

    sections.append(
        EvidenceSection(
            title=f"Changes since {changes.since or 'inception (no prior snapshot)'}",
            items=_change_items(changes),
            text=render_change_lines(changes.items),
        )
    )
    if changes.sections_missing:
        warnings.append("changes could not compare: " + ", ".join(changes.sections_missing))

    as_of: dt.date | None = None
    try:
        as_of = dt.date.fromisoformat(snapshot.as_of)
    except ValueError:
        as_of = None

    return EvidencePack(symbol="", as_of=as_of, sections=tuple(sections), warnings=tuple(warnings))
