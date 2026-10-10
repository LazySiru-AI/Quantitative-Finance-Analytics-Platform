# Addendum for the 13F analysts — read `ANALYST_BRIEF.md` first

Everything in `ANALYST_BRIEF.md` still applies: the design cutoff, the 43-symbol roster, the rule
DSL, the card schema, the one-file scope fence. This adds one source of information and one hard
constraint on using it.

## What you may use

Institutional 13F holdings, through this repo's own API:

```python
import sys, datetime as dt
sys.path.insert(0, "backend")
from app.config import get_settings
from app.institutions import service, catalog

AS_OF = dt.date(2026, 2, 13)                 # the design cutoff — never move it
s = get_settings()
client = service.build_client(s)

fund = catalog.find("BRK")
snap = service.load_latest(fund, client=client, settings=s, as_of=AS_OF)
print(snap.period, snap.filed, len(snap.holdings))

delta = service.load_delta(fund, client=client, settings=s, as_of=AS_OF)  # two filings, diffed
print(delta.from_period, "->", delta.to_period, delta.counts)
```

`as_of` filters on **filing date**, not period. Pass it on every call. Omit it and you are reading
filings that were not public when you designed, which is the lookahead this addendum exists to
prevent.

## The constraint that defines this strategy

**A 13F reports a quarter-end position and does not become public for up to 45 days.** You may act
on a filing from its *filing* date, never from its *period* date. That is not a technicality — it
is the whole problem with the signal, and your thesis has to confront it rather than mention it.

Measured against the catalog on 2026-02-13, this is what was actually public:

| Manager | Latest public filing | Positions as of | Filed |
|---|---|---|---|
| BRK, PERSHING, APPALOOSA, DUQUESNE, THIRDPOINT, ELLIOTT, TIGERGLOBAL, COATUE, LONEPINE, SCION | Q3 2025 | **2025-09-30** | 2025-11-03 → 11-14 |
| ARKINVEST | Q4 2025 | 2025-12-31 | 2026-02-11 |
| RENTECH | Q4 2025 | 2025-12-31 | 2026-02-12 |
| SOROS, BRIDGEWATER | Q4 2025 | 2025-12-31 | 2026-02-13 |

So for ten of the fourteen managers, the freshest thing you can see describes positions held on
**30 September 2025** — and you are designing a strategy that starts trading on 17 February 2026.
The manager may have sold the entire position months ago. You will not know until the next filing,
which lands *during* the window you cannot see.

Position counts available at the cutoff: `BRK` 41, `PERSHING` 11, `SCION` 8, `APPALOOSA` 45,
`DUQUESNE` 65, `THIRDPOINT` 46, `ELLIOTT` 35, `TIGERGLOBAL` 56, `COATUE` 74, `LONEPINE` 25,
`ARKINVEST` 196, `SOROS` 244, `BRIDGEWATER` 1040, `RENTECH` 3185.

## The engine constraint you cannot design around

**The rule DSL has no 13F terms.** `entry` and `exit` are price and indicator expressions evaluated
per symbol against that symbol's own bars. There is no way to write "buy what Berkshire added".

So 13F can only reach your strategy through **universe selection**: you use the filings to decide
*what* to trade, and price rules decide *when*. Say that plainly in your thesis. Do not write a
thesis describing a signal the card cannot carry.

**Your universe is also fixed for the whole window.** A real 13F strategy would refresh at each
filing date — Q4 2025 stragglers land around 2026-02-17 and Q1 2026 filings around 2026-05-15, both
inside the trading window. This engine cannot rotate a universe mid-run. Name that limitation; it
means your strategy is a single stale snapshot held for six months, which is a weaker thing than a
13F strategy that updates.

## Mapping holdings to tradeable symbols

13F filings report **CUSIP**, not ticker. `Holding.ticker` is populated only where that CUSIP
matches an instrument in the local ledger — so most rows come back with `ticker=None`, and
that is expected, not a bug.

Your universe must be drawn from the 43-symbol roster in `ANALYST_BRIEF.md`. In practice:

```python
ROSTER = {"SNDK","SOXX","MU","AMD","DELL","IREN","NVDA","INTC","TSLA","NBIS","MRVL","META","NOW",
          "ORCL","EWY","NFLX","SCHD","UNH","PLTR","AMZN","BE","CRDO","OKLO","GLD","GOOGL","MSFT",
          "TSM","AVGO","APLD","KORU","BRK.B","NET","ARKK","COIN","LITE","SGOV","ADBE","SNOW","URA",
          "AGG","NLR","QCOM","QQQM"}
hits = [h for h in snap.holdings if h.ticker in ROSTER]
```

**Report how many holdings you had to discard for want of a ticker mapping.** If a manager's book
maps to only three tradeable names, your "13F strategy" is really a three-name bet and the reader
should be told.

## What to report, in addition to the standard report

- Which managers you used, and the exact `period` and `filed` dates of every filing you relied on.
- How stale that data was on 2026-02-17, in days.
- How many holdings mapped to tradeable tickers, and how many you lost to unmapped CUSIPs.
- Your honest view on whether a four-month-old snapshot of someone else's book is information at
  all. "No, and here is what I did about it" is a perfectly good answer — better than a thesis that
  assumes the edge exists because the manager is famous.
