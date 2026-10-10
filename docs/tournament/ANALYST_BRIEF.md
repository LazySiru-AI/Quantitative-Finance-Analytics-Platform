# Analyst brief — read this in full before writing anything

You are one of ten analysts in a strategy tournament. You design **one** strategy. It is then
traded blind, by someone else, over a window you cannot see. You get one submission.

Repo root: `<repo>`. Python:
`.venv/Scripts/python.exe`, run from the repo root. Shell is Git Bash on Windows.

## Your deliverable

Exactly one file: `docs/tournament/cards/<your-agent-id>.json`, holding one `StrategyCard`.

**You own that single path and nothing else.** Do not create, edit or delete any other file — not
another analyst's card, not a Python module, not a test, not anything under `data/`. Nine other
analysts are working in this same directory, concurrently, on their own files.
**`data/store/ledger.sqlite` and `data/accounts.toml` are the user's real financial records: never
write to them.**

## The rule that makes this tournament mean anything

**You may look at market data through 2026-02-13 and not one day further.** Trading runs
2026-02-17 → 2026-08-18. Look at the trading window and you are fitting the data you are about to
be scored on; your result would then measure nothing at all.

Read bars like this. The `end=` is not optional and must not move:

```python
import sys, datetime as dt
sys.path.insert(0, "backend")
from app.config import get_settings
from app.db import duck

s = get_settings()
with duck.connect(s.analytics_path) as conn:
    bars = duck.read_bars(conn, s.bars_dir, "NVDA", duck.Interval.DAY,
                          end=dt.date(2026, 2, 13))       # <-- never omit or move this
```

`StrategyCard` rejects a `designed_through` later than 2026-02-13, so a card that admits to looking
further will not load. That is the point — do not work around it.

## Your universe

A fixed roster of 43 symbols, every one with verified bar coverage across both windows:

```
SNDK SOXX MU AMD DELL IREN NVDA INTC TSLA NBIS MRVL META NOW ORCL EWY NFLX SCHD UNH
PLTR AMZN BE CRDO OKLO GLD GOOGL MSFT TSM AVGO APLD KORU BRK.B NET ARKK COIN LITE
SGOV ADBE SNOW URA AGG NLR QCOM QQQM
```

Pick **up to 12**. Leveraged and inverse funds were deliberately excluded — do not ask for them.
The list spans a wide volatility range, from `SGOV`/`AGG` (cash-like, bonds) through `GLD`/`SCHD`
to `IREN`/`OKLO`/`APLD`. It is semiconductor- and AI-heavy, which is a real property of this roster
and not a neutral backdrop.

## The rule language

`entry` and `exit` are expressions in the repo's DSL (`backend/app/rules/grammar.py` has the full
grammar).

- Price fields: `open high low close volume`
- Comparisons: `< <= > >= == !=`, plus `crosses_above` / `crosses_below`
- Logic: `and or not`, parentheses; arithmetic `+ - * /`
- **Chained comparisons are a parse error.** Write `a > b and a < c`, never `b < a < c`.
- Indicators — period 2–500, `bb` stddev 0.1–10:
  `sma(p)` · `ema(p)` · `rsi(p)` · `atr(p)` ·
  `macd(f,s,sig)` · `macd_signal(f,s,sig)` · `macd_hist(f,s,sig)` ·
  `bb_upper(p,sd)` · `bb_mid(p,sd)` · `bb_lower(p,sd)`
- `vwap()` is **intraday only**. You are on daily bars. Do not use it.

Real examples from the repo's own catalog: `close > sma(200)` · `ema(50) crosses_above ema(200)` ·
`rsi(14) < 30` · `close < bb_lower(20,2)` · `macd_hist(12,26,9) crosses_above 0` ·
`high - low > atr(14) * 1.5` · `bb_upper(20,2) - bb_lower(20,2) < close * 0.04` (a squeeze) ·
`atr(14) < close * 0.02` (a low-volatility condition).

## The card

Read `backend/app/tournament/models.py` in full first — its docstrings state every rule below and
why each exists. Your JSON needs:

| field | notes |
|---|---|
| `agent_id` | exactly the id you were given |
| `display_name` | yours to choose |
| `discipline` | exactly the one you were given |
| `thesis` | see below — this is the field that matters most |
| `universe` | 1–12 symbols from the list above |
| `entry`, `exit` | DSL expressions |
| `stop_loss_pct`, `take_profit_pct` | fractions of one — `0.08` is 8% |
| `max_hold_days` | 1–252, or null |
| `max_positions` | 1–8 |
| `position_pct` | fraction of one; `position_pct * max_positions` must not exceed 1.0 |
| `designed_through` | `"2026-02-13"` |

You need at least one of `exit` / `take_profit_pct` / `max_hold_days` — with none of them a stop is
the only way out, and the strategy would only ever be sold at a loss.

**Your `thesis` must say why this should work.** A mechanism; a reason the edge might exist; who is
on the other side. "Buys when RSI is low" restates your rules and is not a thesis. Write it before
you see any result — it is the only thing separating a hypothesis from a curve fit, and the report
prints it next to what actually happened.

## Two engine constraints you must design around

**Stops are evaluated against the previous close, not the intraday low**, and fill at the next
open — because the decision-maker structurally cannot see the session's low. A name that gaps
through your stop and recovers by the close will not stop you out until a close confirms it.
Stop-outs land later and at worse prices than an intraday check would give.

**`stop_loss_pct` and `position_pct` are single fixed numbers.** There is no per-symbol volatility
scaling and no ATR-based sizing; the engine does not support it. A stop that suits `GLD` is
noise-width on `IREN`. Either choose a universe of comparable volatility or accept the mismatch and
say so — but do not write a thesis that quietly assumes sizing the card cannot express.

## Do the work

Study the design window. Measure things. Let what you find set your parameters, and report the
numbers you actually measured rather than plausible-sounding defaults.

**Resist the urge to tune.** There is no leaderboard to climb and no second submission. A strategy
fitted hard to 2024–early-2026 is precisely the one most likely to fall apart in the window that
follows. A simple rule you can defend beats an optimised one you cannot.

## Definition of done

Your card must load and both expressions must pass the lookahead guard. Substitute your own id:

```bash
cd "<repo>" && .venv/Scripts/python.exe -c "
import sys, pathlib, datetime as dt; sys.path.insert(0,'backend')
from app.tournament.models import StrategyCard
from app.backtest.guards import check
from app.config import get_settings
from app.db import duck
card = StrategyCard.model_validate_json(
    pathlib.Path('docs/tournament/cards/<YOUR-ID>.json').read_text())
print('card OK:', card.agent_id, '| planned RRR:', card.reward_risk)
s = get_settings()
with duck.connect(s.analytics_path) as conn:
    bars = duck.read_bars(conn, s.bars_dir, card.universe[0], duck.Interval.DAY,
                          end=dt.date(2026,2,13))
for label, expr in (('entry', card.entry), ('exit', card.exit)):
    if expr.strip():
        print(label, check(expr, bars, interval=duck.Interval.DAY).status)
"
```

If an expression fails, fix it. Do not submit a card that cannot run.

## Report back

- the JSON you wrote, pasted
- the verbatim output of the validation command
- what you actually measured in the design window, and how it set your parameters
- **what you expect to go wrong.** Every strategy has a regime it hates. Naming yours in advance is
  worth more than a confident forecast, and the report will print it beside the outcome.
