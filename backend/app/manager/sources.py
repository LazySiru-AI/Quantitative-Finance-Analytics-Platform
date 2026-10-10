"""Layer A of the manager desk: the information bus.

:func:`collect` is the pinned entry point (`docs/MANAGER-DESK-PLAN.md` §2.1): it reads every
application surface **in-process** into one :class:`~app.manager.models.ManagerSnapshot`, one
:class:`~app.manager.models.SnapshotSection` per area in :data:`app.manager.models.AREAS`, in that
order.

**This module is the dispatcher; the area builders live beside it.** `app.manager.sources_owner`
holds the six sections that make up the owner's own book (`account`, `tax`, `activity`, `paperdesk`,
`persona_books`, `persona_traders`); `app.manager.sources_research` holds the remaining eight
(`research`, `desks`, `live`, `personas`, `market`, `events`, `news`, `data`). Both modules import
:class:`SourceContext` from here, so this module imports them back only lazily, inside
:func:`collect` -- a module-level `from app.manager import sources_owner` here would be a straight
import cycle. Splitting the actual reads out this way (rather than inlining all fourteen in one file)
is what lets a source-specific defect be fixed, and a source-specific test suite
(`tests/test_manager_sources_owner.py`, `tests/test_manager_sources_research.py`) be written, without
touching this dispatcher at all.

**Fail-soft per source, in two layers.** Every builder in `sources_owner`/`sources_research` already
wraps its own upstream call in `try/except Exception` and returns `ok=False` with a reason on
failure -- that is documented on each of those two modules. :func:`collect` wraps the *call to the
builder itself* in a second `try/except` as a backstop, so a builder that somehow still raises (a bug
in the builder, an exception from constructing the `SnapshotSection` itself) degrades only its own
area rather than the whole collect. Nothing in this module ever fabricates a zero for a figure a
builder could not read; :func:`collect` additionally strips any figure key a builder emitted outside
its own `FIGURE_KEYS[area]` entry, so a naming drift in a builder cannot leak an unpinned key onto the
wire.

**Owner-only areas.** For `scope="member"`, `account`/`tax`/`activity` (:data:`OWNER_ONLY_AREAS`) are
never read at all -- their builder is never called, so a spy on the underlying service sees zero
calls for those three areas on a member snapshot -- and, per `app.manager.models.AREAS`'s own
docstring ("a missing [section] is named in `ManagerSnapshot.warnings` / `ChangeSet.sections_missing`"
is the *failure* convention), the section is **absent from `sections` entirely** rather than present
with `ok=False`: this is a deliberate design omission, not a collection failure, and must not be
reported as one. `snapshot.warnings` therefore never names an owner-only area either.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from app.config import Settings
from app.manager.models import AREAS, FIGURE_KEYS, Area, ManagerSnapshot, Scope, SnapshotSection

__all__ = ["OWNER_ONLY_AREAS", "SourceContext", "collect"]

logger = logging.getLogger(__name__)

#: Areas whose builder is never called for `scope="member"`, and whose section is omitted from
#: `ManagerSnapshot.sections` entirely (not emitted as `ok=False`) on a member snapshot -- see the
#: module docstring.
OWNER_ONLY_AREAS: frozenset[str] = frozenset({"account", "tax", "activity"})


@dataclass(frozen=True)
class SourceContext:
    """What every area builder in `sources_owner`/`sources_research` reads instead of taking its own
    `(settings, as_of, scope)` triple -- one object so adding a field (a feature flag, a cache) never
    means touching all fourteen builder signatures.

    `now` is separate from `as_of`: `as_of` is the *data* date the snapshot describes (the ledger's
    last trade date, a stored bar's date -- whatever a given area's own "as of" means), while `now`
    is the wall-clock instant `collect()` started, for areas that report a real-time reading (macro's
    Fear & Greed, a live decision) rather than a stored-as-of one.
    """

    settings: Settings
    as_of: dt.date
    scope: Scope
    now: dt.datetime


def _builders() -> dict[Area, Callable[[SourceContext], SnapshotSection]]:
    """The area -> builder dispatch table, assembled from `sources_owner`/`sources_research`.

    Imported lazily (inside this function, called only from `collect`) rather than at module level:
    both of those modules do `from app.manager.sources import SourceContext` at *their* module level,
    so an eager import here would be a straight cycle.
    """
    from app.manager import sources_owner, sources_research

    return {
        "account": sources_owner.account_section,
        "tax": sources_owner.tax_section,
        "paperdesk": sources_owner.paperdesk_section,
        "persona_books": sources_owner.persona_books_section,
        "persona_traders": sources_owner.persona_traders_section,
        "research": sources_research.research_section,
        "desks": sources_research.desks_section,
        "live": sources_research.live_section,
        "personas": sources_research.personas_section,
        "market": sources_research.market_section,
        "events": sources_research.events_section,
        "news": sources_research.news_section,
        "data": sources_research.data_section,
        "activity": sources_owner.activity_section,
    }


def _strip_unpinned_figures(section: SnapshotSection, allowed: set[str]) -> SnapshotSection:
    """Drop any `figures`/`item.figures` key not in `allowed`, leaving everything else untouched.

    A no-op (returns `section` itself) when nothing needs stripping, so the common case allocates
    nothing extra.
    """
    if set(section.figures).issubset(allowed) and all(
        set(item.figures).issubset(allowed) for item in section.items
    ):
        return section

    logger.warning(
        "manager.sources: %s emitted figure key(s) outside FIGURE_KEYS -- stripped", section.key
    )
    return section.model_copy(
        update={
            "figures": {k: v for k, v in section.figures.items() if k in allowed},
            "items": tuple(
                item.model_copy(
                    update={"figures": {k: v for k, v in item.figures.items() if k in allowed}}
                )
                for item in section.items
            ),
        }
    )


def collect(settings: Settings, *, scope: Scope, as_of: dt.date | None = None) -> ManagerSnapshot:
    """Read every application surface in-process into one `ManagerSnapshot`.

    One `SnapshotSection` per area in `AREAS`, in that order, except: for `scope="member"`, the
    owner-only areas (`OWNER_ONLY_AREAS`) are omitted from `sections` entirely -- a deliberate design
    absence, not a failure, so they are never named in `warnings` either. A source that fails yields
    `ok=False` with the reason in its own `warnings`; `items`/`figures` stay empty rather than
    carrying a fabricated zero. Never raises past this function.
    """
    resolved_as_of = as_of if as_of is not None else dt.date.today()
    now = dt.datetime.now(dt.UTC)
    ctx = SourceContext(settings=settings, as_of=resolved_as_of, scope=scope, now=now)
    builders = _builders()

    sections: list[SnapshotSection] = []
    top_level_warnings: list[str] = []

    for raw_area in AREAS:
        area = cast(Area, raw_area)
        if scope == "member" and area in OWNER_ONLY_AREAS:
            continue

        builder = builders[area]
        try:
            section = builder(ctx)
        except Exception as exc:  # backstop -- see module docstring
            logger.warning("manager.sources: %s source failed", area, exc_info=True)
            section = SnapshotSection(key=area, ok=False, warnings=(f"{type(exc).__name__}: {exc}",))

        section = _strip_unpinned_figures(section, set(FIGURE_KEYS.get(area, ())))

        sections.append(section)
        if not section.ok:
            top_level_warnings.extend(f"{area}: {w}" for w in section.warnings)

    return ManagerSnapshot(
        scope=scope,
        as_of=resolved_as_of.isoformat(),
        generated_at=now.isoformat(),
        sections=tuple(sections),
        warnings=tuple(top_level_warnings),
    )
