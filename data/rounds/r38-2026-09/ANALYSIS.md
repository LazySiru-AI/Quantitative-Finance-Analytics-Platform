macro pin : data/rounds/r21-2026-08/macro-pin.json
mandate   : SAVINGS, starting_cash $100,000
benchmark : 30-70-spy-agg (30/70 SPY/AGG, recomputed per window)
windows   : rank ('h10y-1', 'h10y-2', 'h5y-1', 'h5y-2', 'h5y-3') | report ('h3y-1', 'h3y-2', 'h3y-3', 'h3y-4') | bear ('b6m-1', 'b6m-2', 'b6m-3', 'b1y-1', 'b1y-2', 'b1y-3')

card                   horizon     h10y-1    h10y-2     h5y-1     h5y-2     h5y-3
r38-breakeven-lo-2     maxDD       -17.5%    -17.3%     -4.5%    -10.8%    -17.0%
r38-control            maxDD       -16.9%    -17.9%     -5.5%    -13.1%    -17.0%
r38-nominal-hi-4       maxDD       -16.9%    -17.9%     -5.5%    -13.1%    -17.0%
r38-price-placebo      maxDD       -16.2%    -16.2%     -5.3%    -11.9%    -16.1%
r38-realyield-hi-1     maxDD       -16.5%    -17.3%     -5.5%    -13.1%    -16.7%
r38-realyield-hi-2     maxDD       -16.9%    -17.9%     -5.5%    -13.1%    -17.0%
r38-realyield-lo-1     maxDD       -19.4%    -19.0%     -6.7%    -16.5%    -18.8%

== treatment minus control (drawdown & MAR), judged rungs ==
card                    fired  dd_margin  mar_margin  cagr_margin verdict
r38-breakeven-lo-2          4      +0.78      -0.032        -0.76 measured
r38-nominal-hi-4            3      +0.03      -0.037        -0.67 measured
r38-price-placebo           5      +0.94      -0.003        -0.30 measured
r38-realyield-hi-1          4      +0.37      +0.001        -0.11 measured
r38-realyield-hi-2          2      +0.00      -0.045        -0.77 measured
r38-realyield-lo-1          5      -1.72      +0.030        +1.08 measured

== bear-window firing (each macro card's condition, treatment vs control) ==
  r38-breakeven-lo-2     fired in 4/6 bear windows
  r38-nominal-hi-4       fired in 1/6 bear windows
  r38-price-placebo      fired in 6/6 bear windows
  r38-realyield-hi-1     fired in 2/6 bear windows
  r38-realyield-hi-2     fired in 0/6 bear windows
  r38-realyield-lo-1     fired in 6/6 bear windows

wrote data/rounds/r38-2026-09/analysis.json
