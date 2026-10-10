"""Discovery: compute the universe from what was knowable, instead of being handed one.

Every other backtest package here takes a universe as an input and asks whether a strategy worked on
it. This one takes a *rule* as the input and asks whether the rule would have found the universe.
The three modules split along the line that makes that gradeable:

* :mod:`app.discovery.candidates` -- what could have been chosen on a given day, behind a protocol
  so the survivor-only sector roster available today can be swapped for a survivorship-free
  constituent list later without touching anything else.
* :mod:`app.discovery.selector` -- the choice, made through an `AsOfMarket` that cannot see past the
  decision date.
* :mod:`app.discovery.exam` -- the grade, measured against the equal-weight candidate set rather
  than against SPY, because only the former isolates selection skill from the market going up.
"""

from __future__ import annotations

__all__: list[str] = []
