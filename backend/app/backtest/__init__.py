"""The backtest workbench: drawdown profiles, event studies, reverse conditioning, guarded scans.

Phase 6 answered "is this rule firing, and what usually follows?" for one curated rule at a time.
This package answers the three questions that need *more* machinery than that, and every extra piece
of machinery here exists to say **no** more often, not to find more edges.

The distinction that organises the package:

* :mod:`~app.backtest.drawdown` is **descriptive**. "How far did SOXL fall and how long did it take
  to come back" is a fact about a price series. No hypothesis, no baseline, no multiple testing --
  nothing to correct for, because nothing is being claimed.
* :mod:`~app.backtest.events` is **confirmatory**, and only when the condition was chosen before
  looking. It measures one stated hypothesis against its own baseline.
* :mod:`~app.backtest.events`'s reverse conditioning is **exploratory by construction** -- it reads
  the data and hands back the conditions that describe it. Its output is labelled as such and is
  never a result, only a candidate.
* :mod:`~app.backtest.scan` is where the honesty cost is paid: testing many conditions at once is
  the one operation in this package that manufactures apparent discoveries out of nothing, so it is
  the one operation that carries a visible trial count and a Benjamini-Hochberg correction.

:mod:`~app.backtest.guards` sits underneath all of it and fails closed, and
:mod:`~app.backtest.runcard` makes any result reproducible after the fact.
"""
