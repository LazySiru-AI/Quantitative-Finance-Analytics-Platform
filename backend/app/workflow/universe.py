"""Dynamic ticker selection for the Agent Workflow desk.

Wraps :mod:`app.discovery.candidates`, :mod:`app.discovery.selector` and
:mod:`app.discovery.workflow_selectors` -- it does not reimplement any of them. This module owns no
mutable state and makes no model call: every symbol it returns comes from a deterministic, as-of-gated
read through :class:`~app.paper.marketdata.AsOfMarket` (indirectly, via those three modules).

**Why this module does not import `app.workflow.pipeline`.** `pipeline.py` imports every workflow
submodule (`book`, `candidates`, `regime`, `taxcheck`, `verdict`, and now this one) as a module, so a
`universe.py` that imported `WorkflowConfig` back from `pipeline.py` at module scope would be
`pipeline -> universe -> pipeline`, a real import cycle. `resolve_universe` below therefore takes
plain keyword arguments -- the handful of fields the pipeline's `WorkflowConfig` happens to carry --
rather than the config object itself. `docs/WORKFLOW-UNIVERSE-BUILD-SPEC.md` recon #1 lays out the same
reasoning against a `UniverseSelectConfig` wrapper type; this module skips even that indirection and
takes the fields directly, since there are only five of them and a wrapper type would just be another
name for the same cycle risk if a future edit ever imported it from the wrong place.

**Never raises.** A bad `rank_key` (a `KeyError` from `app.discovery.selector.select`), an unknown
`candidate_pool`, or a `"screen"` request with neither `selector_id` nor `candidate_pool`/`rank_key` at
all are none of them treated as exceptional -- each degrades to an empty shortlist with a logged
warning. This mirrors `_scan_signals`'s own "never raise on a symbol/config it cannot use" convention
(`pipeline.py`) and, more importantly, avoids the closed-union-over-a-server-string hazard this
codebase has already been bitten by once (`docs/closed-unions-kill-pages`): `universe_mode` and its
siblings arrive off the wire through `app.workflow.service`'s validation, but this function is also
callable directly (as the tests below do), and a defensive floor here is what keeps a malformed call
from taking the whole run down instead of just returning nothing to research.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from collections.abc import Callable
from pathlib import Path

from app.agentdesk.models import agentdesk_dir
from app.config import Settings
from app.discovery.candidates import CandidateSet, sector_candidates, theme_candidates
from app.discovery.selector import select
from app.discovery.workflow_selectors import select_for_workflow
from app.tournament.models import StrategyCard

__all__ = [
    "CANDIDATE_POOLS",
    "load_prior_shortlist",
    "resolve_universe",
    "save_prior_shortlist",
]

logger = logging.getLogger(__name__)

#: The two candidate pools screen mode's raw (non-selector) fallback path can draw from -- both from
#: `app.discovery.candidates`, both ETF rosters. Single-stock pools are out of scope: the bar store
#: holds no delisted names (see that module's own docstring), so a single-stock CandidateSet would be
#: survivor-biased by construction until a point-in-time constituent feed exists. Keyed by the same
#: `label` each `CandidateSet` reports on itself (`StoredETFCandidates.label`), so a value that round-
#: trips through here and back into a stored `Selection.candidate_set` always agrees with its own key.
CANDIDATE_POOLS: dict[str, Callable[[Settings], CandidateSet]] = {
    "sector-etf": sector_candidates,
    "theme-etf": theme_candidates,
}

#: Used only when `screen_top_n` is not supplied by the caller at all -- the raw (`candidate_pool` +
#: `rank_key`) fallback path's own floor. The `selector_id` path never consults this: each of the eight
#: frozen selectors in `app.discovery.workflow_selectors` picks its own top_n per regime.
_DEFAULT_SCREEN_TOP_N = 3


def resolve_universe(
    *,
    universe_mode: str | None,
    selector_id: str | None,
    candidate_pool: str | None,
    rank_key: str | None,
    screen_top_n: int | None,
    regime_label: str,
    card: StrategyCard,
    settings: Settings,
    as_of: dt.date,
    prior_picks: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """The universe `_stage_candidate_scan` should scan today, best-first where the source ranks.

    `universe_mode` `None` or `"card"` (or anything else this module does not recognise -- see the
    module docstring on why an unrecognised value degrades rather than raises) returns `card.universe`
    verbatim, unchanged in order or content: this is what makes `universe_mode="card"` byte-for-byte
    identical to a build without this module at all.

    `"screen"` with `selector_id` set is the primary path: it defers entirely to
    `app.discovery.workflow_selectors.select_for_workflow`, which is the only thing that can faithfully
    reproduce the eight frozen Round-33 selectors (regime-conditioned pools, hysteresis, gates) that are
    not expressible as a bare `rank_key`. `candidate_pool`/`rank_key` are not consulted on this path --
    the named selector owns its own pool and ranking internally. `screen_top_n`, if set, IS passed
    through as the selector's `top_n_override` (a live widening of the shortlist size, honoured by
    `mom12_1_hysteresis`); `None` leaves each selector at its frozen per-regime top_n.

    `"screen"` with no `selector_id` but a `candidate_pool` and `rank_key` is the raw fallback: an
    ad-hoc `app.discovery.selector.select` call, always `collapse=True` (uncollapsed top-N can spend two
    of three slots on one correlated pair -- see `select`'s own docstring) and top_n from `screen_top_n`
    (or :data:`_DEFAULT_SCREEN_TOP_N` if that too is unset).

    `"screen"` with neither degrades to an empty tuple, logged -- `app.workflow.service` is expected to
    reject this combination as a 422 before a run is ever created, so reaching this branch at all is a
    defect one layer up, not a normal runtime condition; this function still does not raise for it.

    `prior_picks` threads through to `select_for_workflow` for the selectors that carry state day over
    day (hysteresis, cooldowns). The live caller (`app.workflow.pipeline._stage_universe_select`)
    resolves it from :func:`load_prior_shortlist` and persists the new shortlist with
    :func:`save_prior_shortlist` right after, so a live screen run's hysteresis sees the actual prior
    run's picks. A backtest replay instead threads `prior_picks` through its own date loop
    (`app.discovery.selector_bakeoff`) and never touches that store, so the two paths stay independent.
    """
    if universe_mode != "screen":
        return tuple(card.universe)

    if selector_id:
        return select_for_workflow(
            selector_id,
            as_of=as_of,
            regime_label=regime_label,
            settings=settings,
            prior_picks=prior_picks,
            card_universe=tuple(card.universe),
            top_n_override=screen_top_n,
        )

    if candidate_pool is None or rank_key is None:
        logger.warning(
            "universe: universe_mode='screen' with no selector_id and no candidate_pool/rank_key; "
            "empty shortlist"
        )
        return ()

    pool_fn = CANDIDATE_POOLS.get(candidate_pool)
    if pool_fn is None:
        logger.warning("universe: unknown candidate_pool %r; empty shortlist", candidate_pool)
        return ()
    pool = pool_fn(settings)

    try:
        selection = select(
            as_of,
            candidates=pool,
            settings=settings,
            rank_key=rank_key,
            top_n=screen_top_n if screen_top_n is not None else _DEFAULT_SCREEN_TOP_N,
            collapse=True,
        )
    except KeyError as exc:
        logger.warning("universe: %s; falling back to an empty shortlist", exc)
        return ()
    return selection.picks


# ---------------------------------------------------------------------------
# Live hysteresis: the prior screened shortlist, per (universe_source, selector_id)
# ---------------------------------------------------------------------------
#
# The selectors that carry state day over day (mom12_1_hysteresis, breakout_atr, meanrev_rsi,
# trend_sticky, signal_density) need the *actual* prior run's shortlist as their `prior_picks`, or
# their hysteresis/cooldown never engages live and they collapse to their stateless variants -- which
# would defeat the low-churn behaviour that is the whole point of, e.g., mom12_1_hysteresis. This is a
# small, explicit, per-selector store, NOT a shared mutable cache: it is keyed by the exact
# `(universe_source, selector_id)` pair, read once at the start of a screen run and overwritten once at
# the end, so nothing leaks across selectors or across universe modes. Backtests never use it (they
# thread prior_picks through their own loop), so it cannot contaminate a replay.


def _prior_shortlist_path(settings: Settings, *, selector_id: str, universe_source: str) -> Path:
    safe = selector_id.replace("/", "_")
    return agentdesk_dir(settings) / "workflow" / "prior_shortlist" / f"{universe_source}__{safe}.json"


def load_prior_shortlist(
    settings: Settings, *, selector_id: str, universe_source: str = "screen"
) -> tuple[str, ...]:
    """The most recent shortlist persisted for this `(universe_source, selector_id)`, or `()`.

    Never raises: a missing file (the selector's first-ever run), an unreadable one, or a malformed
    payload all degrade to an empty tuple -- the same "no prior state" a stateless selector or a first
    session starts from. So a corrupted store weakens hysteresis for one run rather than failing it.
    """
    path = _prior_shortlist_path(settings, selector_id=selector_id, universe_source=universe_source)
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return tuple(str(s) for s in payload.get("picks", ()))
    except (ValueError, OSError) as exc:
        logger.warning("universe: could not read prior shortlist %s: %s; treating as empty", path, exc)
        return ()


def save_prior_shortlist(
    settings: Settings,
    *,
    selector_id: str,
    universe_source: str = "screen",
    as_of: dt.date,
    picks: tuple[str, ...],
) -> None:
    """Persist `picks` as this selector's prior shortlist for the next run to read. Best-effort: an IO
    failure is logged, not raised -- a run that could not record its shortlist still completes; the next
    run merely starts hysteresis cold, exactly as :func:`load_prior_shortlist`'s own miss path does."""
    path = _prior_shortlist_path(settings, selector_id=selector_id, universe_source=universe_source)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"as_of": as_of.isoformat(), "picks": list(picks)}), encoding="utf-8"
        )
    except OSError as exc:
        logger.warning("universe: could not persist prior shortlist %s: %s", path, exc)
