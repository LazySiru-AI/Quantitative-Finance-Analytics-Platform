"""The instrument-class guard: a leveraged product's card is meaningless without its unlevered twin.

Daily-reset leveraged and inverse ETFs do not deliver their multiple over any period longer than one
session. They rebalance to a fixed exposure every day, so their multi-day return is
**path-dependent**: in a choppy market they decay against the underlying regardless of which way it
ends up going. A strategy that sits out the chop and holds through the trends will therefore look
brilliant on SOXL for reasons that have nothing to do with the strategy -- it is measuring leverage
decay avoidance and calling it edge.

So when the subject is one of these, the loop runs the identical thesis against the unlevered
equivalent and shows both. This fires **automatically from the registry** rather than depending on
the user remembering to ask, because the person most likely to forget is the one most likely to be
fooled.

The mapping is deliberately conservative. An entry here asserts that the pair track the same
underlying exposure closely enough that a strategy comparison is meaningful, and a wrong mapping is
worse than a missing one -- a missing one produces a card with a stated gap, a wrong one produces a
confident comparison against the wrong instrument. Where no clean unlevered equivalent trades, the
entry records ``None`` and the card says so.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["REGISTRY", "LeveragedInstrument", "describe", "lookup", "unlevered_for"]


@dataclass(frozen=True, slots=True)
class LeveragedInstrument:
    """One daily-reset product and the plain exposure it is built on."""

    symbol: str
    factor: float
    """Daily reset multiple. Negative for inverse products: ``-1`` for SH, ``-3`` for SOXS."""
    underlying: str | None
    """Ticker of the unlevered equivalent, or ``None`` where none trades. ``None`` is an honest
    answer and the card reports the gap rather than substituting something approximate."""
    note: str = ""


#: Daily-reset products this project knows about, keyed by symbol.
#:
#: Sourced from the holdings the plan names -- SOXL/SOXS, TQQQ/SQQQ, NVDL, MUU/MULL, TSLL, CRDU,
#: IREX, GDXU/NUGT -- plus the common index pairs. Coverage is not the point; the point is that the
#: guard fires without being asked for the instruments actually held.
REGISTRY: dict[str, LeveragedInstrument] = {
    inst.symbol: inst
    for inst in (
        LeveragedInstrument("SOXL", 3.0, "SOXX", "3x semiconductors"),
        LeveragedInstrument("SOXS", -3.0, "SOXX", "-3x semiconductors"),
        LeveragedInstrument("TQQQ", 3.0, "QQQ", "3x Nasdaq-100"),
        LeveragedInstrument("SQQQ", -3.0, "QQQ", "-3x Nasdaq-100"),
        LeveragedInstrument("UPRO", 3.0, "SPY", "3x S&P 500"),
        LeveragedInstrument("SPXU", -3.0, "SPY", "-3x S&P 500"),
        LeveragedInstrument("TNA", 3.0, "IWM", "3x Russell 2000"),
        LeveragedInstrument("TZA", -3.0, "IWM", "-3x Russell 2000"),
        LeveragedInstrument("NVDL", 2.0, "NVDA", "2x single-stock, NVDA"),
        LeveragedInstrument("TSLL", 2.0, "TSLA", "2x single-stock, TSLA"),
        LeveragedInstrument("NUGT", 2.0, "GDX", "2x gold miners"),
        LeveragedInstrument("GDXU", 2.0, "GDX", "2x gold miners"),
        LeveragedInstrument("TMF", 3.0, "TLT", "3x long Treasuries"),
        LeveragedInstrument("TMV", -3.0, "TLT", "-3x long Treasuries"),
        # Named in the plan's holdings but without a clean unlevered equivalent that trades. The
        # entry exists so the guard still *fires* and the card states the gap, rather than the
        # instrument silently looking like an ordinary ETF.
        LeveragedInstrument("MUU", 2.0, None, "2x single-stock; no unlevered equivalent mapped"),
        LeveragedInstrument("MULL", 2.0, None, "2x single-stock; no unlevered equivalent mapped"),
        LeveragedInstrument("CRDU", 2.0, None, "2x single-stock; no unlevered equivalent mapped"),
        LeveragedInstrument("IREX", 2.0, None, "leveraged; no unlevered equivalent mapped"),
    )
}


def lookup(symbol: str) -> LeveragedInstrument | None:
    """The registry entry for a symbol, or ``None`` if it is an ordinary instrument."""
    return REGISTRY.get(symbol.upper())


def unlevered_for(symbol: str) -> str | None:
    """The ticker to run the same thesis against, or ``None``.

    ``None`` covers both "not leveraged" and "leveraged with nothing to compare against" -- callers
    that need to tell those apart use :func:`lookup`, and the card does, because the two produce
    different sentences.
    """
    entry = lookup(symbol)
    return entry.underlying if entry else None


def describe(symbol: str) -> str | None:
    """A sentence for the card explaining why a comparison is or is not present."""
    entry = lookup(symbol)
    if entry is None:
        return None
    if entry.underlying is None:
        return (
            f"{entry.symbol} is a daily-reset {entry.factor:+g}x product with no unlevered "
            "equivalent mapped here. Its multi-day returns are path-dependent and decay in choppy "
            "markets regardless of direction, so these figures cannot be separated from that decay."
        )
    return (
        f"{entry.symbol} is a daily-reset {entry.factor:+g}x product on {entry.underlying}. Its "
        "multi-day returns are path-dependent, so the same thesis is run against "
        f"{entry.underlying} below -- without that comparison this card could be measuring leverage "
        "decay and calling it strategy."
    )
