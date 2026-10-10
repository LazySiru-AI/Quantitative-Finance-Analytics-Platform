# Round 2 — an open universe

Read `ANALYST_BRIEF.md` first. Everything in it still holds: the design cutoff, the rule DSL, the
card schema, the engine constraints, the one-file scope fence. Two things change.

**Your round-1 card is finished and stays as submitted.** It is part of the final report. Do not
edit it, do not revisit it, and do not try to make round 2 consistent with it. If round 2 leads you
somewhere that contradicts your round-1 thinking, that is a finding worth stating, not a problem to
hide.

## What changes

**1. Your card goes in `docs/tournament/cards/round2/<your-agent-id>.json`** — a new directory.
Same filename as your round-1 card, new parent. That single path is the only thing you may create
or modify.

**2. The universe is no longer the round-1 roster.** Round 1 restricted you to a fixed roster of 43
tickers — a semiconductor- and AI-heavy set that most analysts found themselves
crowding into. Round 2 lifts that. You now choose from 93 symbols spanning asset classes the
previous roster could not reach:

**Broad equity** `SPY QQQ IWM DIA RSP MDY VTV VUG`
**US sectors** `XLK XLF XLV XLI XLY XLP XLU XLB XLRE XLC`
**International** `EFA EEM VEA VWO EWJ EWG EWU EWC EWZ INDA FXI`
**Bonds** `TLT IEF SHY LQD HYG TIP BND MUB`
**Commodities & metals** `SLV USO DBC CPER PPLT GDX GDXJ`
**Factor & dividend** `MTUM QUAL VLUE USMV SPLV VIG DVY`
**Thematic / industry** `SMH IGV XBI IBB ITA KRE XHB XRT JETS ICLN TAN ARKG ARKW`
**Large caps** `AAPL-free list:` `JNJ PG KO PEP WMT HD V MA JPM BAC XOM PFE ABBV TMO DIS T CSCO ACN
TXN HON CAT DE GE BA LIN SHW NEE DUK SO`

Every one has verified daily bars across both the design and trading windows — that was checked,
not assumed. Pick **up to 12**.

## What this makes possible that round 1 did not

Round 1's universe was one correlated sector bet wearing ten different rule sets. MU appeared in 8
of 10 universes; NVDA, AVGO and TSM in 7. Whatever the ten strategies measured, they measured it on
substantially the same names at the same time.

This roster contains genuinely uncorrelated things: long bonds and gold miners and Brazilian
equities and defence and biotech do not move together the way ten semiconductor names do. **If your
strategy has ever wanted an asset outside equities, or a hedge, or a low-correlation sleeve, this is
where you can express it.** You are not obliged to — a concentrated bet you can defend is still
better than diversification for its own sake — but you should now be choosing, rather than being
forced.

**Measured correlations, so you do not repeat a false lead.** An earlier round-2 analyst
computed these over the 259 sessions to the cutoff, and two of them contradict what this brief
originally suggested:

| pair | corr | what it means |
|---|---|---|
| the 11 US sector ETFs, mean pairwise | **0.581** | Round 1's semiconductor cluster was 0.589. Sector-versus-sector is **not** diversification; it is the same trade in eleven costumes. |
| `HYG` vs `SPY` | **0.824** | High yield trades as equity beta here, not as credit. It is not a hedge. |
| `HYG` vs `IEF` | 0.226 | Not a clean inverse either — the risk-on/risk-off pairing this brief suggested does not hold in this data. |
| `EEM`/`FXI`/`EWZ` vs `SPY` | 0.49–0.74 | "Uncorrelated emerging markets" is not supported. |
| `IEF` vs `SPY` | **−0.110** | A real diversifier. |
| `TLT` vs `SPY` | 0.090 | Likewise. |
| `GLD` vs `SPY` | 0.042 | Likewise — though note `GLD`'s own annualised volatility measured 24.9% in this window, so it is not the calm ballast its reputation suggests. |

Cross-asset is where the diversification is. Sector ETFs are not. Verify anything here that matters
to your design rather than taking it on trust — it was one analyst's measurement, not a law.

Measure correlations before you assume them. `XLU` and `TLT` are both "defensive" and behave
differently; `GDX` and `SLV` are both "metals" and are not the same trade.

## What does not change

The design cutoff is still **2026-02-13**. Read bars with `end=dt.date(2026, 2, 13)`, always. The
trading window is still 2026-02-17 → 2026-08-18, 127 sessions, and you still cannot see it.

Stops are still evaluated against the previous close and filled at the next open. `stop_loss_pct`
and `position_pct` are still single fixed numbers with no per-symbol volatility scaling — and on
this roster the volatility spread is *wider* than round 1's, from `SHY` and `MUB` (nearly flat) to
`GDXJ` and `ARKW`. That constraint bites harder here, not less.

Universe order is still the tiebreak when more names qualify than you have slots — the runner fills
in the order symbols appear in your `universe` list. **In round 1 nobody knew this except one
analyst.** Now everyone does: order your universe by preference, deliberately.

## For the 13F analysts (`a11`, `a12`, `a13`) — one hard limitation

You may still use 13F filings, and `as_of=dt.date(2026, 2, 13)` is still mandatory on every call.
The publication-lag rule is unchanged: act on a filing from its **filing date**, never its period
date.

**But the CUSIP-to-ticker bridge will fail on almost all of this roster.** `Holding.ticker` is
populated only where a filing's CUSIP matches an instrument in the *local ledger* — and the
ledger holds none of `JNJ`, `XLU`, `TLT` or most of round 2, so those CUSIPs are not in it
and cannot resolve. Round 1's mapping loss was already 95.7%; here it will be worse.

Do not work around this by matching issuer names to tickers automatically. "JOHNSON & JOHNSON" →
`JNJ` looks safe and the general technique is not: it silently attaches real tickers to wrong
companies, which is precisely why the codebase refuses to do it. If you want to assert a specific
mapping, state the CUSIP, the issuer name, the ticker and your reasoning for that one name, so a
reader can check it.

The honest outcome may be that **13F is simply not usable on this roster**, in which case say so
plainly and design a strategy that stands on its own. A round-2 card whose report reads "the signal
I was built around cannot reach this universe, here is what I did instead" is a better submission
than one that pretends otherwise. That is a real finding about the data, and it will be reported as
one.

## Definition of done

Identical to round 1, with your new path:

```bash
cd "<repo>" && .venv/Scripts/python.exe -c "
import sys, pathlib, datetime as dt; sys.path.insert(0,'backend')
from app.tournament.models import StrategyCard
from app.backtest.guards import check
from app.config import get_settings
from app.db import duck
card = StrategyCard.model_validate_json(
    pathlib.Path('docs/tournament/cards/round2/<YOUR-ID>.json').read_text())
print('card OK:', card.agent_id, '| planned RRR:', card.reward_risk)
s = get_settings()
with duck.connect(s.analytics_path, read_only=True) as conn:
    bars = duck.read_bars(conn, s.bars_dir, card.universe[0], duck.Interval.DAY,
                          end=dt.date(2026,2,13))
for label, expr in (('entry', card.entry), ('exit', card.exit)):
    if expr.strip():
        print(label, check(expr, bars, interval=duck.Interval.DAY).status)
"
```

Use `read_only=True` — twelve other analysts are reading the same DuckDB file concurrently and the
write lock will otherwise bounce you.

**Write scratch files under a subdirectory named for your agent id.** In round 1 two analysts used
the same generic filename in the shared scratchpad and one overwrote the other's work mid-task.

## Report back

Same as round 1, plus one thing: **say what you did differently now the constraint is gone, and
why.** If your round-2 card looks much like your round-1 card, that is a legitimate answer — but
say so explicitly, and say what you considered and rejected.
