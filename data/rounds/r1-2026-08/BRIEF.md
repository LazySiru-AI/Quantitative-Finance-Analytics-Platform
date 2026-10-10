# Analyst brief — Strategy Program, round 1

You are one of six analysts. You design **one** strategy, submit it, and it is then traded by
machinery you do not control across five market regimes — including two bear markets and a crash.
You get one submission. There is no leaderboard to climb and no second attempt.

Read this whole brief before you touch any data.

## 1. What you are optimising for, and what you are not

You are **not** trying to produce the highest return in any window. The program that ranks you
computes, for every window your card is eligible for:

```
excess          = strategy_return - benchmark_return
adjusted_excess = strategy_return - (exposure * benchmark_return)
```

`adjusted_excess` is the one that matters. It asks whether your *rules* beat simply being invested
the same fraction of the time. This exists because the tournament that preceded this program
measured a rank correlation of **ρ = 0.648 between exposure and three-year return** — most of what
looked like skill was being long in a bull market. A card that returned +119% while invested 98% of
the time, in a window where the benchmark returned +75%, added far less than the headline suggests.

You are ranked on the **median** `adjusted_excess` across your eligible windows, with your **worst**
window reported beside it and a hard gate described in §3. Consistency across regimes beats a single
spectacular result. A card that is mediocre in five regimes will rank above a card that is brilliant
in one and untested in the rest.

## 2. Resist the urge to tune. This is the whole point.

The tournament that preceded this program produced one finding that dominates all the others:

> **Rank correlation between in-sample return and blind return: Spearman ρ = 0.162.**
> How a strategy performed on the data its author was allowed to study told you almost nothing about
> how it performed on data nobody had seen.

Twenty of its 24 cards lost to the benchmark *on their own design window*. The failure mode was not
"brilliant in-sample, collapses out of sample" — most never managed the first half. Fitting harder
would not have helped them.

Concretely, for you:

- **A simple rule you can defend beats an optimised one you cannot.** If you cannot explain why a
  parameter has the value it has without referring to a backtest result, the parameter is fitted.
- **Parameter budget: 10.** Count every number you chose: each numeric literal in `entry` and `exit`,
  plus `stop_loss_pct`, `take_profit_pct`, `max_hold_days`, `max_positions`, `position_pct`. Ten or
  fewer. Report your count in your memo. This is a hard limit, not a guideline.
- **Do not grid-search.** Do not run the same rule at 20 parameter settings and submit the best. If
  you test sensitivity, test it to show the rule is *insensitive* — a rule that only works at
  `rsi(14) > 55` and breaks at `> 52` is a fitted rule, and you should say so and pick something else.
- Prefer round numbers and conventional periods. `sma(200)` is a convention thousands of participants
  actually watch, which is a mechanism. `sma(187)` is a search result.

## 3. The universe is open, and your choice of it has a consequence

**Pick your own symbols.** There is no assigned list. 173 symbols have readable daily bars; the full
inventory, grouped by how far back each reaches, is in `strategy-program/WINDOWS.md`. Read that file.

Your `universe` is 1 to 12 tickers, and it is **fixed for the entire run** — the engine cannot rotate
a universe mid-window.

The consequence, stated in advance: **a card can only run in a window where every symbol in its
universe has enough history before that window starts.** Pick a 2024 IPO and you cannot be tested
against the GFC, COVID, or 2022.

> **The gate: a card eligible in fewer than three of the five windows is reported as unranked.**
> Not last — unranked, with its numbers shown and excluded from the ranking.

Nobody is telling you to pick old names. You are being told what it costs if you do not.

Order matters: when more symbols qualify on a session than you have slots, the broker fills in the
order the symbols appear in your `universe` array. This is an arbitrary tiebreak, not a
"buy the leader" mechanism, and the engine has no cross-sectional comparison — you cannot express
"buy the strongest of these." A prior sensitivity study re-ran one identical card under twelve
different universe orderings and found a **53.9-point spread in three-year return, σ = 21.2 points**.
Ordering is noise of that magnitude. Do not tune it, and do not believe a result that depends on it.

## 4. The data cutoff

**You may look at market data through 2026-02-13 and not one day further.** This is enforced by the
type system: `StrategyCard` rejects a `designed_through` later than 2026-02-13. Every read you make
must be bounded — pass `end=dt.date(2026,2,13)` to every bar read.

Windows `bull-2024` and `recent` overlap your design period. That is known and will be disclosed in
the report: those windows measure fit, and `gfc`, `covid` and `bear-2022` measure something closer to
generalisation for a rule you did not design against them. Do not go looking at 2026 data to "check"
your rule. The cutoff is the one thing here enforced by trust as well as by type.

## 5. Information quarantine — do not read these

The prior tournament's results are published in this repository. Reading them would tell you which
strategies won a window you are about to be scored on, which is precisely the contamination this
program exists to avoid. **Do not open:**

- `docs/tournament/RESULTS.md`, `docs/tournament/RESULTS-3YR.md`
- anything under `docs/tournament/results/`
- `strategy-program/library/README.md` and anything under `strategy-program/library/`
- `docs/research/strategy-lab/REPORT.md`

Everything you legitimately need from those documents — the exposure correlation, the ρ = 0.162
finding, the ordering-sensitivity spread, the engine's constraints — has been extracted into this
brief already. If you believe you need something else from them, say so in your memo instead of
reading it.

You may freely read `strategy-program/WINDOWS.md`, the harness source under `backend/app/`, and any
market data through the cutoff.

## 6. The card

One JSON file, loading into `app.tournament.models.StrategyCard`. Extra fields are **forbidden**;
the model is frozen and strict.

| field | type | required | notes |
|---|---|---|---|
| `agent_id` | str | yes | Your assigned id exactly, e.g. `c01-meanrev`. |
| `display_name` | str | yes | Short human name. |
| `discipline` | enum | yes | Exactly one of `trend`, `mean-reversion`, `momentum`, `breakout`, `volatility`, `pairs-rotation`, `risk-managed`. Yours is assigned. |
| `thesis` | str | yes | See §8. |
| `universe` | list[str] | yes | 1–12 tickers. |
| `entry` | str | yes | Rule DSL, must evaluate to boolean. |
| `exit` | str | yes | Rule DSL, or `""` if a target or time cap closes the position. |
| `stop_loss_pct` | decimal-as-string \| null | no | Fraction of one, e.g. `"0.08"` = 8% below entry. |
| `take_profit_pct` | decimal-as-string \| null | no | Fraction of one above entry. |
| `max_hold_days` | int \| null | no | 1–252. |
| `max_positions` | int | yes | 1–8. |
| `position_pct` | decimal-as-string | yes | Fraction of *starting* equity per position. |
| `designed_through` | ISO date | yes | `"2026-02-13"`. |

Two validators will reject your card outright:
- `position_pct` must be in `(0, 1]` **and** `position_pct * max_positions <= 1.001`.
- At least one of `exit` (non-empty), `take_profit_pct`, or `max_hold_days` must be set — something
  has to close the position.

## 7. The rule DSL — verified against the parser today

Grammar: `and` / `or` / `not`, parentheses, arithmetic `+ - * /`, comparisons `< <= > >= == !=`, and
the two cross operators `crosses_above` / `crosses_below`. Price fields usable bare: `open`, `high`,
`low`, `close`, `volume`. The expression **must terminate in a boolean** — a bare `close` is a parse
error.

**Comparisons do not chain.** `close > sma(50) > sma(200)` fails. Write
`close > sma(50) and sma(50) > sma(200)`.

Indicator calls, every one confirmed to pass the guard on daily bars:

| call | params |
|---|---|
| `sma(period)` | period 2–500 |
| `ema(period)` | period 2–500 |
| `rsi(period)` | period 2–500 |
| `atr(period)` | period 2–500 |
| `macd(fast,slow,signal)` | the MACD line; `fast < slow` required |
| `macd_signal(fast,slow,signal)` | the signal line |
| `macd_hist(fast,slow,signal)` | the histogram |
| `bb_upper(period,stddev)` | **stddev must be written with a decimal point** |
| `bb_mid(period,stddev)` | same |
| `bb_lower(period,stddev)` | same |
| `swing_high(lookback)` | last confirmed swing high, published `lookback` bars late |
| `swing_low(lookback)` | last confirmed swing low |
| `rsi_at_swing_high(period,lookback)` | RSI at that pivot — the other half of a divergence test |
| `rsi_at_swing_low(period,lookback)` | same |
| `macd_at_swing_high(f,s,sig,lookback)` | same idea |
| `macd_at_swing_low(f,s,sig,lookback)` | same |

Verified failures, so you do not lose your submission to one:
- `bb_upper(20,2)` **fails** — write `bb_upper(20,2.0)`. The float parameter needs a decimal point.
  **[ERRATUM — see below. This claim is wrong.]**
- `vwap()` **fails on daily bars** — it is registered for 5-minute and hourly only. Do not use it.
- `close > sma(50) > sma(200)` **fails** — chained comparison.

> **Erratum, recorded after the cards were frozen.** The `bb_upper(20,2)` claim above is false and
> was written by the orchestrator, not discovered by an analyst. `close > bb_upper(20,2)` parses
> correctly; an integer stddev is fine. The probe that produced the claim tested `bb_upper(20,2)` as
> a *bare* expression, which fails because a rule must terminate in a boolean — a type error, not a
> number-format error. The wrong cause was inferred from a correct failure.
>
> The error was conservative: writing `2.0` works, so no submission was harmed by it. It is left in
> place above rather than edited away, because this file is the record of what the analysts were
> actually told, and quietly correcting it would misrepresent the round. The library card
> `E-asymmetric`, written before this program existed, uses `close > bb_upper(20,2)` and runs.

Not expressible at all, so do not plan around them: ADX, stochastics, Ichimoku, volume-profile,
Fibonacci levels, cross-sectional ranking, per-symbol volatility-scaled position sizing,
multi-timeframe confluence.

## 8. The thesis field

State the **mechanism**: why this pattern exists, who is on the other side of the trade, and why they
keep taking it. A restatement of your own rules is not a thesis. "Buy when RSI is below 30 because
oversold conditions revert" is a restatement. Naming the participant who is forced to sell, and why
they are forced, is a mechanism.

Then state, in the same field or your memo, **what you expect to go wrong** — every strategy has a
regime it hates. Naming yours in advance is worth more than a confident forecast, and the report
prints it beside the outcome. This is a pre-registration: it is checked against what actually
happened, and you cannot revise it afterwards.

## 9. Execution reality you are designing against

- Decisions use data strictly **before** the decision session; fills happen at the **next session's
  open**. You never get the close you decided on.
- **Stops are evaluated against the previous close**, not the intraday low, because the decision-maker
  cannot see the session's low. Stop-outs therefore land later and worse than an intraday check
  implies — one prior card's worst trade lost **19.9% against a 12% stop**. Size your stop knowing it
  will be violated.
- Deterministic adverse slippage, commissions and SEC/TAF fees charged, whole shares only, a $500
  minimum clip, T+1 cash settlement respected. An entry that cannot be paid for is rejected, and
  rejections are recorded and reported.
- **No dividends anywhere.** Benchmark and strategy alike trade price only. This flatters every
  strategy against a real buy-and-hold investor by roughly 2 points a year.
- `stop_loss_pct` and `position_pct` are single fixed numbers applied to every symbol. There is no
  per-symbol volatility scaling. If your universe mixes a 15%-vol ETF with a 60%-vol single name, one
  stop fits neither.
- The persona's real 25% single-name cap is **raised to 100%** for this round so cards run as written.
  If your `position_pct` exceeds 0.25 you are relying on that relaxation; say so in your memo.

## 10. Deliverables

Two files, both yours alone. Do not create, edit, or read any other analyst's files.

1. **`strategy-program/rounds/r1-2026-08/cards/<your-agent-id>.json`** — the card.
2. **`strategy-program/rounds/r1-2026-08/memos/<your-agent-id>.md`** — your design memo, containing:
   - the mechanism, in your own words
   - **why you chose the universe you chose**, and which windows it makes you eligible for
   - every parameter, why it has the value it has, and your parameter count against the budget of 10
   - what you measured in the design window, with the actual numbers, and the code you ran
   - any sensitivity check, and whether the rule survived it
   - **the regime you expect to lose in** — pre-registered
   - anything you tried that did not work and why you abandoned it

Use `.scratch/<your-agent-id>/` for working files. Namespace it — in a prior round two analysts used
the same generic scratch filename and one silently overwrote the other's work.

## 11. Definition of done

Your card must load and pass the lookahead guard. Run this and paste the **verbatim** output into
your memo:

```bash
cd "<repo>" && PYTHONPATH="backend;." .venv/Scripts/python.exe -c "
import sys, pathlib, datetime as dt; sys.path.insert(0,'backend')
from app.tournament.models import StrategyCard
from app.backtest.guards import check
from app.config import get_settings
from app.db import duck
AGENT='<your-agent-id>'
card = StrategyCard.model_validate_json(
    pathlib.Path(f'strategy-program/rounds/r1-2026-08/cards/{AGENT}.json').read_text())
print('card OK:', card.agent_id, '| planned RRR:', card.reward_risk, '| slots:', card.max_positions)
s = get_settings()
with duck.connect(s.analytics_path, read_only=True) as conn:
    for sym in card.universe:
        bars = duck.read_bars(conn, s.bars_dir, sym, duck.Interval.DAY, end=dt.date(2026,2,13))
        for label, expr in (('entry', card.entry), ('exit', card.exit)):
            if expr.strip():
                st = check(expr, bars, interval=duck.Interval.DAY).status
                if str(st) != 'passed': print(' GUARD', st, sym, label)
    print('guard: all symbols checked')
"
```

**Every bar read you make must pass `read_only=True`.** The store is a single DuckDB file whose
default connection takes a write lock; six analysts reading it concurrently without that flag will
fail with an `IOException` that looks exactly like a missing ticker. Verified today.

## 12. Report back

When you are done, report: the card as submitted, the verbatim guard output, your parameter count,
which windows you are eligible for and why, your pre-registered failure regime, and one sentence on
the single weakest assumption in your design.
