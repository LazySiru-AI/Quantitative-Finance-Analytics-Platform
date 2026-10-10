# c20-rotation — Defensive/Reflation Sector Rotation

Written before any trading-window result exists. Studied only data through **2026-02-13**.

## 1. Mechanism, and who is on the other side

The rule DSL has no cross-symbol operator: entry and exit are evaluated per instrument against that
instrument's own bars, with no way to express "buy the strongest of these six." Rotation here comes
from three things only — the universe, the fixed fill order, and a 3-of-6 slot cap — not from a
comparative rule.

The filter is one absolute condition, applied identically to six instruments: `close > sma(100) and
rsi(14) > 50 and rsi(14) < 75` — an established but not extended uptrend. The six split into two
economically opposed legs:

- **Defensive equity**: `XLP` (staples), `XLU` (utilities), `XLV` (health care) — the three lowest-beta
  S&P sectors.
- **Energy/commodity reflation**: `XLE` (energy), `DBC` (broad commodities), `USO` (crude oil).

Each name is only ever held while its own trend is intact. There is no attempt to predict which leg
should lead; the filter just drops whichever leg breaks trend and keeps whichever holds it.

**Who is on the other side.** Momentum capital that stays concentrated in the AI/growth complex
through a rotation because that is its mandate, not because it disputes the rotation is happening.
Cross-asset traders who fade an energy or commodity breakout as "a dead trade" and get run over by a
multi-month reflation move — and, symmetrically, traders who dismiss a defensive-sector rally as
"boring" and miss a growth-scare rotation into it. And momentum/CTA flow on the exit side of whichever
leg is currently breaking down: a slow, rule-following trend-break exit here is a late seller relative
to a discretionary desk that saw the top coming.

## 2. Why these names, in this order

**Universe, in fill order**: `XLP, USO, DBC, XLU, XLV, XLE`.

The order is ascending by each name's trailing 252-session correlation to QQQ (used as a proxy for the
AI/growth-momentum complex, since that is what both incumbents trade), measured through 2026-02-13:
`XLP 0.188, USO 0.270, DBC 0.342, XLU 0.397, XLV 0.430, XLE 0.509`. When more than 3 of 6 qualify on
the same session, the broker fills the names this round's own combined-book scoring cares about most —
the ones least correlated to the incumbents — first.

I am not claiming this ordering is a source of edge. `PROTOCOL.md`'s own sensitivity result — a
53.9-point spread, sigma 21.2, from re-ordering one identical card twelve ways — means any margin this
produces on a single window could be entirely inside that noise band. It is a deliberate, measured
tiebreak, not an arbitrary one, and that is the only claim being made for it.

## 3. Index-derived? No

None of these six is an S&P 500 or Nasdaq-100 constituent, and none is a single-stock pick. Five are
diversified sector or commodity-basket ETFs; `USO` tracks a single physical commodity future. Selection
logic is asset-class role and measured correlation to the AI-momentum complex, not index membership —
this card does not inherit `universe_knowable_from = 2026-03-31`.

I flag one honest caveat: the sector SPDRs' own holdings rebalance over time to track the present-day
S&P 500's sector composition, which is a much weaker, indirect version of the same survivorship effect.
It is not the reason any name is here.

## 4. What I measured through 2026-02-13

- **Correlation to QQQ** (252-session trailing, through 2026-02-13): `XLP 0.188, USO 0.270, DBC 0.342,
  XLU 0.397, XLV 0.430, XLE 0.509` — mean **0.356**. Mean pairwise correlation among the six themselves
  over the same window: **0.357**.
- **Breadth**: on the 4,994 sessions since 2006-04-09 (the date all six symbols have data) where the
  entry filter is computable, mean qualifying names is **2.78 of 6**, median **3**. At least 3 of 6
  qualify on **56.4%** of sessions, at least 4 on 35.7%, at least 1 on 85.8%. A 3-slot cap is a real,
  regularly binding constraint, not a formality.
- **Expected capital exposure**: 3 slots × 15% = **45% maximum commitment**, against the A-family's
  ~90% nominal (and 0.47–0.49 realised) capital exposure — the discipline was retired specifically for
  that combination of high exposure and negative adjusted excess. A naive occupancy proxy (mean of
  `min(qualifying, 3) × 0.15` across the same 4,994-session history) comes to **~0.32**, meaningfully
  below the A family's realised figure by construction, not chance. This proxy ignores actual
  trade-lifecycle timing (next-open fills, holding through the exit lag) and is not the harness's
  entry-notional `capital_exposure`; treat it as a directional estimate, not the true figure.

## 5. What this does that passive holding would not

A static equal-weight holding of `XLP/XLU/XLV/XLE/DBC/USO` would have been long the energy/commodity
leg all the way into its `oil-2014` collapse, and would own whichever leg is currently breaking down at
all times, with no mechanism to reduce it. This card only holds a name while its own trend is intact,
exits on a trend break, a 10% stop, or a 150-day time cap, and the 3-of-6 slot cap limits how much of
the book any single regime call can consume. That is discipline over exposure, not a directional
prediction — it will lag every turn by design (see §7), and the honest trade is fewer, later, smaller
commitments in exchange for never being pinned in a broken trend by construction.

## 6. Every parameter, and why

- **Universe (6, not 12)**: kept deliberately smaller than the cap. `c16-dispersion-wide` (round 3)
  showed that breadth for its own sake — one name per sector, ordered by measured correlation — did not
  produce edge; it finished 7th of 10. This card keeps two coherent, opposed legs instead of scattering
  across sectors with no shared logic.
- **`close > sma(100)`**: a 100-day filter, faster than the incumbents' `sma(200)` regime filter and
  slower than the retired `A-rotation`'s `sma(50)`. Cross-asset instruments (energy, commodities,
  defensive equity) trend more slowly and noisily than single momentum stocks, but the shortest
  round-4 windows (45–74 sessions) need a filter that can already be resolved at window open, which a
  200-day filter is more likely to have stale.
- **`rsi(14) > 50 and rsi(14) < 75`**: confirms established, not barely-positive, momentum, while
  excluding the most overbought tail. Directly modeled on `A-rotation`'s 55–80 band, shifted down
  slightly for cross-asset use.
- **Exit `close < sma(100) or rsi(14) < 40`**: symmetric trend-break plus a faster momentum-fade signal;
  the 40/50 asymmetry (exit below 40, re-entry needs above 50) avoids exiting and re-entering on
  ordinary chop between 40 and 50.
- **`stop_loss_pct = 0.10`**: tighter than the incumbents' and `A-rotation`'s 12%, because five of six
  names here (all but `USO`) are diversified baskets with structurally lower idiosyncratic vol than a
  single momentum stock; the sixth (`USO`) is the highest-vol name in the book and the stop is sized to
  it, not loosened for the other five.
- **`max_hold_days = 150`**: roughly 7 months — long enough to span most of one regime leg (the
  `oil-2014` and `inflation-2021` windows run 5.5–12 months) without holding blind through a second
  reversal.
- **`max_positions = 3`, `position_pct = 0.15`**: 45% maximum commitment, chosen to sit well under the
  A family's ~90% nominal exposure. §4's breadth measurement (median 3 of 6 qualify) confirms the cap
  binds regularly rather than being decorative.
- **No take-profit**: mirrors `B-momentum`'s own measured finding (capping gains cut its mean
  per-signal return from ~20% to 2–9%) — a reflation or defensive-rotation leg that is working is
  exactly the kind of move a cap would amputate.

## 7. What would falsify the thesis

- **The trend filter's lag costs more than its discipline saves.** At a sharp turning point — like the
  start of `oil-2014`'s collapse — a name can stay "in trend" on a 100-day average for weeks after the
  break has started, so the card can be caught holding into the first leg of a reversal before the exit
  fires. If adjusted excess is negative specifically because of slow exits at turning points (visible in
  the trade log as large single-name losses near a window's start), the mechanism — not the thesis about
  correlation — is the problem.
- **Correlation to `B-momentum` comes in near the incumbents' own 0.57**, not meaningfully below it. If
  so, the combined-book diversification claim (§8) fails on its own measured terms regardless of this
  card's standalone return.
- **`taper-2013` is a specific, named risk.** Utilities (`XLU`) are rate-sensitive bond-proxies and are
  documented to have underperformed broadly during the 2013 taper tantrum specifically because of that
  sensitivity — this is a case where a defensive-equity label does not mean defensive-to-rate-shocks. If
  `taper-2013` is not the worst or near-worst window, that specific piece of the thesis was wrong.

## 8. Predictions, all scored

- **Worst window**: `taper-2013`. Utilities are rate-sensitive and have a documented history of
  underperforming specifically during 2013's taper tantrum; this card has no rate-hedge leg (that
  basket — Treasuries/gold — was deliberately left to `c14-riskmanaged-wide` rather than duplicated
  here, see §2 of the card thesis). Rough magnitude: **−10% to −18% adjusted excess**, wide because six
  windows against a ±21-point noise floor is a small sample.
- **`oil-2014`**: expect the trend-lag failure mode described in §7 to show up here — held into part of
  the initial energy/commodity break before the filter exits — but capped by the 10% stop and the
  15%-per-slot sizing. Net expectation: **flat to modestly negative**, better than a static hold of the
  same six names because the exit removes the position instead of riding it down further, but not a
  clean win.
- **`inflation-2021`**: this is the window the thesis is built for. Energy led the S&P 500 sector table
  in calendar 2021 and commodities were strong on the reflation trade; expect the energy/commodity leg
  to be held for most of the window and to be the primary contributor. Net expectation: **the strongest
  window of the six**, plausibly the only one to clear a double-digit adjusted excess.
- **Expected correlation to `B-momentum`**: **roughly 0.25–0.40**. Below the 0.57 this round's brief
  measures between `B-momentum` and `C-trend`, because none of these six names shares AI-capex earnings
  exposure, but not as low as `c14-riskmanaged-wide`'s near-zero figure, because equity-sector and
  energy exposure still carries real beta to broad risk sentiment that a pure bond/gold book does not.
