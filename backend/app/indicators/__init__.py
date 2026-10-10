"""Technical indicators.

One registry, one definition per indicator, three consumers: the chart overlays, the rule DSL
(Phase 6) and the backtest workbench (Phase 7). The single definition is the point. If the chart
draws a 20-period Bollinger band from one implementation and a rule evaluates ``close < bb_lower``
against another, the picture and the table disagree and there is no way to tell which lied.
"""
