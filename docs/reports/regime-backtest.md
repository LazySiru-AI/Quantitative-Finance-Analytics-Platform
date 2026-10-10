# Regime backtest — deterministic classifier and static card map

Generated 2026-08-31T13:40:36.643051+00:00 by `tools/regime_backtest_report.py`, over `2023-08-29` to `2026-08-28` (753 trading sessions). Zero model-call cost: `app.workflow.regime.classify` is deterministic arithmetic and `app.tournament.runner.run_card` evaluates a rule DSL -- no LLM was called to produce any number in this report.

**This is informational research, not a pre-registered study, and it does not alter `docs/WORKFLOW-STUDY-PLAN.md`'s decision rule** -- see the Conclusion section.

## Data availability

2s10s spread (FRED `T10Y2Y`): available, 753 sessions matched against a fetched history.
Composite Fear & Greed: **unavailable for the whole window, by construction.** CNN's endpoint has no as-of capability (see `app.market.macro`'s own module docstring), so `app.workflow.regime_backtest.regime_history` never backtests this signal at all -- see that module's docstring, "What is, and is not, backtestable".

## Regime frequency

| Regime | Sessions | Share |
|---|---:|---:|
| `risk_on_trend` | 403 | 53.5% |
| `risk_off` | 232 | 30.8% |
| `choppy_neutral` | 4 | 0.5% |
| `high_vol_stress` | 114 | 15.1% |
| **Total** | **753** | **100.0%** |

## Regime transition matrix

Row = the label a session carried; column = the label the *next* session (in trading-session order, not calendar order) carried.

| from \ to | `risk_on_trend` | `risk_off` | `choppy_neutral` | `high_vol_stress` |
|---|---:|---:|---:|---:|
| `risk_on_trend` | 391 | 1 | 1 | 9 |
| `risk_off` | 1 | 227 | 0 | 4 |
| `choppy_neutral` | 1 | 0 | 2 | 1 |
| `high_vol_stress` | 10 | 3 | 1 | 100 |

## Per-card in-regime vs out-of-regime comparison

Each label's primary mapped card (`regime_map.json`'s index-0 entry) is run once over the full window via `app.tournament.runner.run_card`, then its trades are redistributed into a daily return series and split by which sessions carry this label versus any other -- see `app.workflow.regime_backtest`'s module docstring for the exact geometric-decomposition rule this uses, since `run_card`'s own `AgentResult` carries no day-by-day equity curve to split directly.

### `risk_on_trend` — primary card `C-trend`

Full ordered map for this label: `C-trend`, `B-momentum`, `H-trend-diversified` (only the primary, index-0 card above was run -- see the module docstring for why).

Whole-window: total_return=90.62%, sharpe=1.394, trades=42.

| | in-regime | out-of-regime |
|---|---:|---:|
| sessions | 403 | 350 |
| trade entries | 19 | 23 |
| total return | 36.82% | 43.85% |
| CAGR | 21.66% | 29.92% |
| volatility (ann.) | 2.71% | 2.74% |
| Sharpe | 7.262 | 9.580 |
| max drawdown | -7.64% | -5.12% |
| exposure | 87.87% | 86.04% |

`CAGR`/volatility/Sharpe read `n/a` under a year of in-subset sessions -- `app.backtest.metrics.compute` refuses to annualise a sample that thin (see that module's own docstring); a blank cell here is the honest absence of a claim, not a missing number.

### `risk_off` — primary card `c14-riskmanaged-wide`

Full ordered map for this label: `c14-riskmanaged-wide`, `c21-uncorrelated` (only the primary, index-0 card above was run -- see the module docstring for why).

Whole-window: total_return=12.45%, sharpe=1.004, trades=30.

| | in-regime | out-of-regime |
|---|---:|---:|
| sessions | 232 | 521 |
| trade entries | 11 | 19 |
| total return | 0.22% | 11.08% |
| CAGR | n/a | 5.22% |
| volatility (ann.) | n/a | 0.57% |
| Sharpe | n/a | 8.926 |
| max drawdown | -1.97% | -1.18% |
| exposure | 72.53% | 74.33% |

`CAGR`/volatility/Sharpe read `n/a` under a year of in-subset sessions -- `app.backtest.metrics.compute` refuses to annualise a sample that thin (see that module's own docstring); a blank cell here is the honest absence of a claim, not a missing number.

### `choppy_neutral` — primary card `c07-chop`

Full ordered map for this label: `c07-chop`, `c18-meanrev` (only the primary, index-0 card above was run -- see the module docstring for why).

Whole-window: total_return=13.27%, sharpe=0.849, trades=29.

| | in-regime | out-of-regime |
|---|---:|---:|
| sessions | 4 | 749 |
| trade entries | 1 | 28 |
| total return | 0.00% | 14.03% |
| CAGR | n/a | 4.52% |
| volatility (ann.) | n/a | 1.37% |
| Sharpe | n/a | 3.229 |
| max drawdown | 0.00% | -1.51% |
| exposure | 20.00% | 20.13% |

`CAGR`/volatility/Sharpe read `n/a` under a year of in-subset sessions -- `app.backtest.metrics.compute` refuses to annualise a sample that thin (see that module's own docstring); a blank cell here is the honest absence of a claim, not a missing number.

### `high_vol_stress` — primary card `c19-volatility`

Full ordered map for this label: `c19-volatility`, `c09-convex`, `B4-tight-stop` (only the primary, index-0 card above was run -- see the module docstring for why).

Whole-window: total_return=26.08%, sharpe=1.481, trades=32.

| | in-regime | out-of-regime |
|---|---:|---:|
| sessions | 114 | 639 |
| trade entries | 16 | 16 |
| total return | 20.68% | 7.40% |
| CAGR | n/a | 2.86% |
| volatility (ann.) | n/a | 1.06% |
| Sharpe | n/a | 2.664 |
| max drawdown | -0.09% | -1.90% |
| exposure | 60.87% | 15.78% |

`CAGR`/volatility/Sharpe read `n/a` under a year of in-subset sessions -- `app.backtest.metrics.compute` refuses to annualise a sample that thin (see that module's own docstring); a blank cell here is the honest absence of a claim, not a missing number.

## Conclusion

Every comparison above is `total_return` on the *same card, same window*, split by which sessions the classifier called this label versus every other label -- the direct test of `regime_map.json`'s premise that each label's assigned card suits sessions carrying that label specifically. A card whose in-regime and out-of-regime rows look alike is evidence the assignment carries no information over this window; a card that diverges materially, in the direction its own thesis predicts, is evidence the mapping is doing something real.

- `risk_on_trend` (`C-trend`): in-regime total_return was lower than out-of-regime (36.82% vs 43.85%, gap -7.03%), over 403 in-regime and 350 out-of-regime session(s).
- `risk_off` (`c14-riskmanaged-wide`): in-regime total_return was lower than out-of-regime (0.22% vs 11.08%, gap -10.87%), over 232 in-regime and 521 out-of-regime session(s).
- `choppy_neutral` (`c07-chop`): in-regime total_return was lower than out-of-regime (0.00% vs 14.03%, gap -14.03%), over 4 in-regime and 749 out-of-regime session(s).
- `high_vol_stress` (`c19-volatility`): in-regime total_return was higher than out-of-regime (20.68% vs 7.40%, gap 13.28%), over 114 in-regime and 639 out-of-regime session(s).

**This finding does not alter `docs/WORKFLOW-STUDY-PLAN.md`'s pre-registered decision rule.** That study governs whether the Agent Workflow desk's model-gated arms beat `raw_signal`; this report is a separate, informational check of whether the *deterministic* regime classifier's static card map is supported by history, run once, outside that pre-registration. A null result here (no material in/out difference) is a real and expected finding, consistent with this programme's base rate that most measured edges do not survive -- it is not evidence the classifier or the map is broken, and neither result edits `app/workflow/regime.py`'s thresholds or `regime_map.json`'s assignments; that stays a human decision, made out of band from this script.
