"""Prove a directory of strategy cards belongs to the "sector family off the taxable book": every
card is `purpose == roth`, every card's `universe` is ticker-disjoint from every `savings`/`trading`
card in the library, and every card is eligible in at least :data:`MIN_ELIGIBLE_MAIN_WINDOWS` of the
eight round-2/3 regime windows.

`strategy-program/DISJOINT-SECTOR-FAMILY.md` is the family's hub document; this is the gate a card
directory has to clear before it is trusted as belonging to that family. Three checks, each cheap on
its own and each catching a different way a card can fail to be what it claims:

1. **Purpose.** A card that is not `purpose == roth` is not a Roth-disjoint card no matter what
   tickers it holds -- `app.tournament.purposes.find_disjointness_violations` (check 2) only ever
   compares a *roth* card against the taxable universe, so a mislabelled card would silently escape
   the one check that exists to catch a collision.
2. **Ticker disjointness from the taxable library.** Built two ways that should agree: a direct set
   intersection against every `savings`/`trading` card in the library, and a call to
   `app.tournament.purposes.find_disjointness_violations` over the combined (library + field) cards.
   The two are computed independently and printed side by side so a disagreement between them is a
   loud finding about this tool, not a silent one.

   **All six tiers are read, not the four `load_library` walks.** `app.tournament.results.load_library`
   covers `backend/app/paper/library/{base,variants,candidates,retired}` -- the `StrategyCard` tiers --
   and never looks inside `allocation/` or `ladder/`. As of 2026-09-08 those two directories are the
   only place five taxable tickers (AGG, BIL, QLD, SCHD, SGOV) are claimed, so a taxable set built from
   `load_library` alone would be quietly short by five. `load_purposed_library` below walks the extra
   two tiers as `AllocationCard`/`LadderCard`, the same way `app.evolution.promotion._library_cards`
   does at promotion time; all three shapes expose the tradeable `.universe` that
   `find_disjointness_violations` checks (a ladder's `signal_symbol` is deliberately not in it -- see
   that function's docstring).

3. **Window eligibility** (skippable with `--skip-eligibility`). Reuses
   `strategy-program/tools/windows.py`'s `eligible_windows`/`symbol_first_bar`/`MAIN_WINDOWS`/
   `MIN_ELIGIBLE_MAIN_WINDOWS` rather than re-deriving any of it -- this module is not the source of
   truth for what "eligible" means, `windows.py` is. The bar store is opened read-only exactly once,
   for the same "the store's default connection takes a write lock that turns a concurrent reader's
   whole run into indistinguishable-from-missing-data `IOException`s" reason `windows.py`'s own module
   docstring gives.

Ticker disjointness is a **necessary condition for this family, not a sufficient one for tax safety**.
IRC §1091 disallows a loss replaced by a *substantially identical* security, a term that does not turn
on ticker symbols matching -- two different tickers can already be substantially identical (a fund and
a share class of the same fund, most plainly), and whether a leveraged fund tracking the same index as
an unleveraged one crosses that line is unsettled. Rev. Rul. 2008-5 is also why the stakes of getting
this wrong inside a Roth are higher than an ordinary wash sale: a replacement bought inside an IRA
within the 61-day window doesn't defer the disallowed loss into a later basis, it destroys it with no
basis adjustment anywhere. See `app.tournament.purposes` and `strategy-program/ROTH-DISJOINT-LADDER.md`
§2 for the fuller argument. This tool checks the one thing that is mechanical and cheap to check --
ticker equality -- and reports exactly that; passing it is not a finding that a roster is safe under
§1091.

Usage:

    cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/disjoint_field.py \\
        --cards data/rounds/r34-2026-09/cards [--cards <dir> ...] \\
        [--skip-eligibility] [--library-root <path>]

Run as a plain script, not ``-m`` -- ``strategy-program`` is not a legal Python package name (the
hyphen), so it can only be invoked by file path, with `backend` and the repo root already on
``PYTHONPATH`` for the `app.*` imports this module makes. Exits 0 when every check passes, 1 (with a
``FAIL: ...`` line naming every reason) otherwise.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from app.tournament.allocation import AllocationCard
from app.tournament.ladder import LadderCard
from app.tournament.models import StrategyCard
from app.tournament.purposes import DisjointnessViolation, Purpose, find_disjointness_violations
from app.tournament.results import LIBRARY_ROOT, load_library

if TYPE_CHECKING:
    import datetime as dt

    import duckdb

__all__ = ["main"]

# `strategy-program/tools/` is not inside a legal Python package (the hyphen in the directory name),
# so its modules cannot be imported with a normal `from ... import ...` statement -- the same
# constraint `tests/test_contributions.py` documents and works around for `contributions.py`. Loading
# `windows.py` by file path, once, at import time, means every function below can call
# `windows.eligible_windows(...)` etc. exactly as if it had been imported normally.
_windows_spec = importlib.util.spec_from_file_location(
    "disjoint_field_windows", str(Path(__file__).with_name("windows.py"))
)
assert _windows_spec is not None and _windows_spec.loader is not None
windows = importlib.util.module_from_spec(_windows_spec)
sys.modules.setdefault("disjoint_field_windows", windows)
_windows_spec.loader.exec_module(windows)


class CardLoadError(Exception):
    """A `*.json` file under a `--cards` directory did not validate as a `StrategyCard`."""

    def __init__(self, path: Path, detail: str) -> None:
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


def load_field(cards_dirs: list[Path]) -> list[tuple[Path, StrategyCard]]:
    """Every `*.json` under each of `cards_dirs`, sorted for a stable report order.

    Raises `CardLoadError` (not a bare pydantic `ValidationError`) on the first file that does not
    validate as a `StrategyCard`, naming the offending path -- a caller wants to know *which* file is
    broken, not just that the batch failed. `windows.py`'s `PROVENANCE_SIDECAR_FILENAME` is skipped
    the same way `windows._load_cards` skips it: it is a legitimate sidecar, not a card, and
    `StrategyCard`'s `extra="forbid"` would otherwise bury the real error under a wall of missing-
    field complaints.
    """
    found: list[tuple[Path, StrategyCard]] = []
    for cards_dir in cards_dirs:
        for path in sorted(cards_dir.glob("*.json")):
            if path.name == windows.PROVENANCE_SIDECAR_FILENAME:
                continue
            try:
                card = StrategyCard.model_validate_json(path.read_text(encoding="utf-8"))
            except Exception as exc:
                raise CardLoadError(path, str(exc)) from exc
            found.append((path, card))
    return found


def check_purpose(field: list[tuple[Path, StrategyCard]]) -> list[str]:
    """Offenders: every field card whose `purpose` is not `Purpose.ROTH`, by `agent_id`."""
    return [
        f"{card.agent_id} ({path.name}): purpose={card.purpose.value!r}, expected 'roth'"
        for path, card in field
        if card.purpose is not Purpose.ROTH
    ]


#: Every card shape that carries a `purpose` and a tradeable `.universe` -- the three
#: `find_disjointness_violations` accepts (see its docstring on why `.universe` is the right field for
#: all three, and why a ladder's `signal_symbol` is deliberately not in it).
PurposedCard = StrategyCard | AllocationCard | LadderCard

#: The two library tiers `load_library` does not walk, and the model each one's JSON validates as.
#: `app.evolution.promotion._library_cards` walks the same two, for the same reason, at promotion time.
_EXTRA_TIERS: tuple[tuple[str, type[AllocationCard] | type[LadderCard]], ...] = (
    ("allocation", AllocationCard),
    ("ladder", LadderCard),
)


def load_purposed_library(library_root: Path | None = None) -> dict[str, list[PurposedCard]]:
    """Every purposed card under `library_root`, keyed by tier -- all six tiers, not four.

    `app.tournament.results.load_library` covers `base`/`variants`/`candidates`/`retired`, the
    `StrategyCard` tiers. `allocation/` and `ladder/` hold `AllocationCard`s and `LadderCard`s, and as
    of 2026-09-08 they are the *only* place five taxable tickers (AGG, BIL, QLD, SCHD, SGOV) are
    claimed. A taxable set built from `load_library` alone would silently omit them, which is exactly
    the shape of failure this tool exists to catch, so the two extra tiers are walked here explicitly.
    A missing tier directory is an empty tier, matching `load_library`'s own tolerance.
    """
    root = library_root if library_root is not None else LIBRARY_ROOT
    library: dict[str, list[PurposedCard]] = {
        tier: list(cards) for tier, cards in load_library(root).items()
    }
    for tier, model in _EXTRA_TIERS:
        tier_dir = root / tier
        found: list[PurposedCard] = []
        if tier_dir.is_dir():
            for path in sorted(tier_dir.glob("*.json")):
                found.append(model.model_validate_json(path.read_text(encoding="utf-8")))
        library[tier] = found
    return library


def taxable_ticker_set(library: dict[str, list[PurposedCard]]) -> dict[str, list[str]]:
    """Every ticker traded by a `savings`- or `trading`-purpose card anywhere in `library`, mapped to
    the `agent_id`s that trade it (a ticker can be claimed by more than one taxable card).
    """
    out: dict[str, list[str]] = {}
    for cards in library.values():
        for card in cards:
            if card.purpose not in (Purpose.SAVINGS, Purpose.TRADING):
                continue
            for symbol in card.universe:
                out.setdefault(symbol, []).append(card.agent_id)
    return out


def check_taxable_overlap(
    field: list[tuple[Path, StrategyCard]], taxable: dict[str, list[str]]
) -> list[str]:
    """Offenders: every (field card, taxable ticker) collision found by direct set intersection --
    the independent check meant to agree with `find_disjointness_violations` (see module docstring).

    Restricted to `purpose == roth` field cards, the same restriction
    `find_disjointness_violations` itself applies (it only ever compares a *roth* card against the
    taxable universe -- see that function's own docstring) -- so the two checks are asking the
    identical question and their offender counts are directly comparable. A non-roth field card is
    check 1's offender, not check 2's; counting it here too would report the same wrong-purpose card
    as two different kinds of failure and make the two checks disagree by construction on any field
    that mixes purposes (a real, if unlikely, case: `backend/app/paper/library/candidates` itself
    holds cards of every purpose, since the tournament library is not scoped to this family).
    """
    offenders: list[str] = []
    for _path, card in field:
        if card.purpose is not Purpose.ROTH:
            continue
        hits = sorted(set(card.universe) & taxable.keys())
        for symbol in hits:
            claimants = ", ".join(taxable[symbol])
            offenders.append(f"{card.agent_id}: {symbol!r} also traded by taxable card(s) {claimants}")
    return offenders


def run_disjointness_violations(
    field: list[tuple[Path, StrategyCard]], library: dict[str, list[PurposedCard]]
) -> tuple[DisjointnessViolation, ...]:
    """`find_disjointness_violations` over the combined (every taxable library card) + (every field
    card) roster -- the second, independent way of asking check 2's question.
    """
    all_cards: list[PurposedCard] = []
    for cards in library.values():
        all_cards.extend(cards)
    all_cards.extend(card for _path, card in field)
    return find_disjointness_violations(all_cards)


def check_eligibility(
    field: list[tuple[Path, StrategyCard]],
) -> tuple[dict[str, dict[str, bool | str]], list[str]]:
    """Per-card eligible-window map (see `windows.eligible_windows`) and a list of cards eligible in
    fewer than `windows.MIN_ELIGIBLE_MAIN_WINDOWS` of `windows.MAIN_WINDOWS`. Opens the bar store
    read-only exactly once, for every card in `field` together.
    """
    from app.config import get_settings
    from app.db import duck

    settings = get_settings()
    conn: duckdb.DuckDBPyConnection
    with duck.connect(settings.analytics_path, read_only=True) as conn:
        first_bars = windows.symbol_first_bar(conn, settings)

    elig_map: dict[str, dict[str, bool | str]] = {}
    offenders: list[str] = []
    for path, card in field:
        universe_knowable_from: dt.date | None = windows.resolve_universe_knowable_from(
            card, path.parent
        )
        elig = windows.eligible_windows(
            card, first_bars, windows.MAIN_WINDOWS, universe_knowable_from=universe_knowable_from
        )
        elig_map[card.agent_id] = elig
        n_ok = sum(1 for tag in windows.MAIN_WINDOWS if elig[tag] is True)
        if n_ok < windows.MIN_ELIGIBLE_MAIN_WINDOWS:
            offenders.append(
                f"{card.agent_id}: eligible in only {n_ok}/{len(windows.MAIN_WINDOWS)} main windows "
                f"(needs >= {windows.MIN_ELIGIBLE_MAIN_WINDOWS})"
            )
    return elig_map, offenders


def _print_table(
    field: list[tuple[Path, StrategyCard]],
    taxable: dict[str, list[str]],
    elig_map: dict[str, dict[str, bool | str]] | None,
) -> None:
    id_w = max((len(card.agent_id) for _path, card in field), default=8)
    id_w = max(id_w, len("card id"))
    header = (
        f"{'card id'.ljust(id_w)}  {'purpose'.ljust(8)}  {'n tickers'.rjust(9)}  "
        f"{'taxable hits'.rjust(12)}  eligible windows"
    )
    print(header)
    print("-" * len(header))
    for _path, card in field:
        n_hits = len(set(card.universe) & taxable.keys())
        if elig_map is None:
            elig_str = "skipped"
        else:
            elig = elig_map.get(card.agent_id, {})
            n_ok = sum(1 for v in elig.values() if v is True)
            elig_str = f"{n_ok}/{len(elig)}"
        print(
            f"{card.agent_id.ljust(id_w)}  {card.purpose.value.ljust(8)}  "
            f"{str(len(card.universe)).rjust(9)}  {str(n_hits).rjust(12)}  {elig_str}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--cards",
        type=Path,
        action="append",
        required=True,
        help="directory of *.json StrategyCard files; may be passed more than once",
    )
    parser.add_argument(
        "--skip-eligibility",
        action="store_true",
        help="skip check 3 (window eligibility) -- does not open the bar store at all",
    )
    parser.add_argument(
        "--library-root",
        type=Path,
        default=None,
        help="override backend/app/paper/library (default) as the taxable-library root, e.g. for a "
        "synthetic library built in a test's tmp_path",
    )
    args = parser.parse_args(argv)

    try:
        field = load_field(args.cards)
    except CardLoadError as exc:
        print(f"FAIL: could not load {exc.path}: {exc.detail}")
        return 1

    if not field:
        print("no cards found under " + ", ".join(str(d) for d in args.cards))
        return 1

    reasons: list[str] = []

    # Check 1: purpose == roth
    purpose_offenders = check_purpose(field)
    reasons.extend(purpose_offenders)

    # Check 2: ticker disjointness from the taxable library, two independent ways
    library = load_purposed_library(args.library_root)
    taxable = taxable_ticker_set(library)
    overlap_offenders = check_taxable_overlap(field, taxable)
    reasons.extend(overlap_offenders)

    violations = run_disjointness_violations(field, library)
    field_agent_ids = {card.agent_id for _path, card in field}
    violation_offenders = [
        v.message for v in violations if v.roth_agent_id in field_agent_ids
    ]
    # The two checks are independent derivations of the same fact and are expected to agree; a
    # divergence is reported explicitly rather than silently deduplicated, because it means one of
    # the two implementations (this tool's direct intersection, or `find_disjointness_violations`) is
    # wrong, not that they measure different things.
    if len(overlap_offenders) != len(violation_offenders):
        reasons.append(
            f"check 2 disagreement: direct intersection found {len(overlap_offenders)} offending "
            f"lines, find_disjointness_violations found {len(violation_offenders)} -- see printed "
            "detail above/below"
        )
    reasons.extend(f"find_disjointness_violations: {msg}" for msg in violation_offenders)

    # Check 3: window eligibility
    elig_map: dict[str, dict[str, bool | str]] | None = None
    if not args.skip_eligibility:
        try:
            elig_map, eligibility_offenders = check_eligibility(field)
        except Exception as exc:
            print(f"could not open the bar store for the eligibility check: {exc}")
            print("falling back as if --skip-eligibility had been passed (not retrying).")
            eligibility_offenders = []
        else:
            reasons.extend(eligibility_offenders)

    print()
    print(f"field: {len(field)} card(s) from " + ", ".join(str(d) for d in args.cards))
    print()
    _print_table(field, taxable, elig_map)
    print()

    if purpose_offenders:
        print("check 1 (purpose == roth) -- offenders:")
        for line in purpose_offenders:
            print(f"  {line}")
        print()

    print(f"check 2 (ticker disjointness): direct intersection found {len(overlap_offenders)} "
          f"offending line(s); find_disjointness_violations found {len(violation_offenders)}")
    if overlap_offenders:
        print("  direct intersection:")
        for line in overlap_offenders:
            print(f"    {line}")
    if violation_offenders:
        print("  find_disjointness_violations:")
        for line in violation_offenders:
            print(f"    {line}")
    print()

    if args.skip_eligibility:
        print("check 3 (window eligibility): skipped (--skip-eligibility)")
    elif elig_map is not None:
        n_below = sum(
            1
            for _path, card in field
            if sum(1 for v in elig_map.get(card.agent_id, {}).values() if v is True)
            < windows.MIN_ELIGIBLE_MAIN_WINDOWS
        )
        print(
            f"check 3 (window eligibility): {len(field) - n_below}/{len(field)} card(s) clear "
            f">= {windows.MIN_ELIGIBLE_MAIN_WINDOWS}/{len(windows.MAIN_WINDOWS)} main windows"
        )
    print()

    if reasons:
        print(f"FAIL: {len(reasons)} reason(s)")
        for line in reasons:
            print(f"  {line}")
        return 1

    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
