"""Deciding whether a symbol the model extracted from a transcript is a real instrument.

**Why this module exists at all.** The transcripts this feature ingests are *auto-generated captions*
(verified: every seed channel's only caption track is machine-made), and four of the five seed
channels speak Korean. Auto-captions mangle tickers in both directions. They turn a real symbol into
ordinary words -- "LITE" becomes "light", "ON" becomes "on" -- and they turn ordinary words into
things that look like symbols. A model reading that text and asked for tickers will, entirely
reasonably, produce some symbols that no exchange has ever listed. Writing those into a note would
put fabricated instruments into the persona's permanent memory, and every later phase (the
consolidated profile, the per-ticker theses, the strategy card) reads that memory as fact.

**The check is layered cheapest-first, and it is a filter, not a guess.** A symbol that cannot be
confirmed is dropped and logged; nothing here ever rewrites a symbol into a different one it thinks
was meant. Guessing that "light" meant `LITE` is exactly the failure this module exists to prevent.

1. **Structural.** 1-5 characters, starting with a letter. Rejects prose instantly and costs nothing.
2. **Known to the ledger.** Every `instrument.primary_symbol` and every `symbol_alias.symbol` the
   user's own imported history contains. This is the "validated against the instrument table" the
   contract names, and it is a pure local read.
3. **Known to the research universe.** The symbol pools `app.evolution.universe` already defines, so a
   symbol this application researches but the user has never personally held still passes without a
   network call.
4. **Confirmed by a provider.** Anything still unresolved gets one cached `get_profile` lookup. This
   is the layer that matters for the actual use case -- an influencer naming a stock the user has
   never held and this repo has never researched is the *interesting* case, not the error case, so
   rejecting it for being unfamiliar would defeat the feature.

A provider that is unreachable is **not** the same as a symbol that does not exist, and the two are
kept apart: `SymbolNotFound` rejects the symbol, while any other provider failure leaves it
unresolved, logs that the check could not be completed, and rejects it for this ingest rather than
admitting an unverified symbol into permanent memory. That asymmetry is deliberate -- a note is
immutable once written, so the cost of wrongly dropping a mention (it is missing from one note) is far
smaller than the cost of wrongly keeping one (a fabricated instrument in the persona's memory forever).

Results are memoised per validator instance, so a transcript naming the same symbol nine times costs
one lookup, and a 20-video backfill of one channel shares the cache across every video.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from app.config import Settings

__all__ = ["build_symbol_validator", "structurally_plausible"]

logger = logging.getLogger(__name__)

#: Uppercase, starts with a letter, 1-5 characters, allowing the `.`/`-` class-share separators this
#: repo already normalises elsewhere (`BRK.B` / `BRK-B`). Anything else is prose, not a ticker.
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,4}$")

#: Single-letter tickers are real (`F`, `T`, `V`), but a one-letter token falling out of an
#: auto-caption is overwhelmingly more likely to be a stray initial than a deliberate mention of Ford.
#: They are not rejected outright -- that would lose real mentions -- but they never pass on structure
#: alone; they must be confirmed by the ledger, the universe, or a provider.
_NEEDS_CONFIRMATION_LEN = 1


def structurally_plausible(symbol: str) -> bool:
    """Whether `symbol` could be a ticker at all. Cheap, local, and the only check that runs for the
    overwhelming majority of the garbage an auto-caption produces."""
    return bool(_SYMBOL_RE.match(symbol.strip().upper()))


def _ledger_symbols(settings: Settings) -> frozenset[str]:
    """Every symbol the user's own imported history knows about. Empty (not an error) when the ledger
    has not been created yet -- a fresh install with no broker import is a supported state, and this
    check simply contributes nothing in that case."""
    from app.datasource import DataServiceError, ledger_db_path
    from app.db import sqlite as ledger

    try:
        path = ledger_db_path(settings)
    except DataServiceError:
        return frozenset()
    if not path.exists():
        return frozenset()
    try:
        with ledger.connect(path, read_only=True) as conn:
            rows = conn.execute(
                "SELECT primary_symbol FROM instrument WHERE primary_symbol IS NOT NULL"
            ).fetchall()
            aliases = conn.execute(
                "SELECT symbol FROM symbol_alias WHERE symbol IS NOT NULL"
            ).fetchall()
    except Exception:  # a missing table or a locked db must not fail an ingest
        logger.warning("personas.tickers: could not read ledger symbols from %s", path, exc_info=True)
        return frozenset()
    out = {str(r[0]).strip().upper() for r in rows if r[0]}
    out |= {str(r[0]).strip().upper() for r in aliases if r[0]}
    return frozenset(out)


def _universe_symbols() -> frozenset[str]:
    """Every symbol this repo's research universe already covers. A local constant read; contributes
    nothing (rather than failing) if that module's shape ever changes.

    Enumerated through the public `pool_for(purpose)` over every `Purpose`, deliberately. The first
    version of this function walked `dir(universe_module)` looking for anything with a callable
    `all_symbols`, which found **nothing**: the pools live in a module-private `dict`, and a `dict`
    has no such attribute. The only match was the `Pool` *class* itself, whose unbound `all_symbols`
    then raised `TypeError` straight into a bare `except: continue`. The result was a layer that
    silently contributed zero symbols while this module's docstring claimed it recognised researched
    names without a network call -- so `NVDA` was rejected under `allow_network=False` and paid for a
    provider round trip otherwise. Reflection over a module's namespace is not an API; `pool_for` is.
    """
    try:
        # `Purpose` from its own module, not from `universe` -- `universe` merely imports it and does
        # not re-export it, so taking it from there is an attribute mypy correctly refuses to trust.
        from app.evolution.universe import pool_for
        from app.tournament.purposes import Purpose
    except ImportError:
        logger.debug("personas.tickers: research universe unavailable", exc_info=True)
        return frozenset()

    out: set[str] = set()
    for purpose in Purpose:
        try:
            out.update(str(s).strip().upper() for s in pool_for(purpose).all_symbols())
        except Exception:
            # One unusable purpose must not cost the symbols the others contribute.
            logger.debug("personas.tickers: pool %r unavailable", purpose, exc_info=True)
            continue
    return frozenset(out)


def build_symbol_validator(
    settings: Settings,
    *,
    allow_network: bool = True,
) -> Callable[[str], bool]:
    """A memoised `symbol -> bool` predicate implementing the layered check above.

    `allow_network=False` stops at layer 3, which is what tests use so the suite never reaches a
    provider. With it off, a symbol that is neither in the ledger nor in the research universe is
    rejected -- correct for a test, and deliberately *not* the production default, because the whole
    point of the feature is surfacing instruments the user does not already hold.
    """
    known = _ledger_symbols(settings) | _universe_symbols()
    memo: dict[str, bool] = {}

    def validate(raw: str) -> bool:
        symbol = raw.strip().upper()
        cached = memo.get(symbol)
        if cached is not None:
            return cached
        result = _validate_uncached(symbol)
        memo[symbol] = result
        if not result:
            logger.info("personas.tickers: dropped unvalidated symbol %r", raw)
        return result

    def _validate_uncached(symbol: str) -> bool:
        if not structurally_plausible(symbol):
            return False
        if symbol in known:
            return True
        if len(symbol) <= _NEEDS_CONFIRMATION_LEN and not allow_network:
            return False
        if not allow_network:
            return False
        return _confirmed_by_provider(settings, symbol)

    return validate


def _confirmed_by_provider(settings: Settings, symbol: str) -> bool:
    """One cached provider profile lookup. `SymbolNotFound` is a real answer ("no such instrument");
    any other provider failure means the question could not be asked, which rejects the symbol for
    this ingest without claiming it does not exist -- see the module docstring on why an immutable
    note makes that the right way round."""
    from app.market.providers.base import ProviderError, SymbolNotFound
    from app.market.registry import default_registry

    try:
        default_registry(settings).get_profile(symbol)
    except SymbolNotFound:
        return False
    except ProviderError as exc:
        logger.warning(
            "personas.tickers: could not confirm %r (provider unavailable: %s); dropping it for "
            "this ingest rather than admitting an unverified symbol",
            symbol,
            exc,
        )
        return False
    except Exception:  # never let a provider bug fail an ingest
        logger.warning("personas.tickers: unexpected error confirming %r", symbol, exc_info=True)
        return False
    return True
