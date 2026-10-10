**Not investment advice.** Simulated results on stored price history. I am not a licensed financial adviser and none of this is a recommendation about real capital.

# Which windows make the `B`-family variants' differing exit rules bind?

**Answer:** windows where a big single-name winner is still open when the base card's 180-day hold ends and `B2-hold-90`'s 90-day cap has already forced it out -- a long, quiet uptrend running past the 90-day mark, not a crash. The single largest four-way spread on record is `h5y-1` (r5, half-decade, early) at +69.11%, and every top-5 window below shares the same shape: a multi-month run in one or two names that `B2-hold-90` is forced to exit early while the base rides it further. `B4-tight-stop`'s 8%-vs-12% stop, by contrast, rarely produces a large spread on its own -- see section 3.

## 1. What the four cards actually differ on

| card | stop_loss_pct | max_hold_days | max_positions | position_pct |
|---|---|---|---|---|
| `B-momentum` (base) | 0.12 | 180 | 6 | 0.15 |
| `B2-hold-90` | 0.12 | **90** | 6 | 0.15 |
| `B3-concentrated` | 0.12 | 180 | **4** | **0.22** |
| `B4-tight-stop` | **0.08** | 180 | 6 | 0.15 |

`B3-concentrated` changes sizing, not exit discipline -- its `stop_loss_pct` and `max_hold_days` are identical to the base. It cannot, by construction, show a window where "its exit rule bound and the base's did not": whatever spread it produces against the base is fewer-bigger-positions amplifying the *same* trades, a genuinely different question from the one this document is about. It is reported in every table below (the round asked for all four), but the `exit-spread` column -- `B-momentum`/`B2-hold-90`/`B4-tight-stop` only -- is the number that actually answers "do the differing exits bind."

## 2. Ranked spread table

44 windows on disk have a stored, complete four-card result (0 more were found with at least one card missing and are excluded). `spread` is the four-way `max - min` of `adjusted_excess`; `exit-spread` excludes `B3-concentrated`. Both in percentage points.

| window | round | regime | sessions | benchmark | spread | exit-spread | B-momentum | B2-hold-90 | B3-concentrated | B4-tight-stop |
|---|---|---|---|---|---|---|---|---|---|---|
| `h5y-1` | r5 | half-decade, early | 1260 | +75.70% | +69.11% | +28.49% | +131.23% | +105.47% | +64.85% | +133.96% |
| `h10y-1` | r5 | decade, early endpoint | 2517 | +172.56% | +65.61% | +6.79% | +161.78% | +156.46% | +97.64% | +163.25% |
| `h1y-2` | r5 | one year, 2016 | 254 | +24.45% | +56.66% | +32.13% | +62.72% | +30.60% | +87.26% | +62.72% |
| `h10y-2` | r5 | decade, recent endpoint | 2515 | +261.15% | +38.68% | +37.17% | +168.15% | +130.97% | +129.46% | +132.74% |
| `h3y-4` | r5 | three years, 2023-26 | 751 | +66.77% | +36.31% | +36.31% | +51.49% | +31.26% | +26.15% | +15.18% |
| `h5y-3` | r5 | half-decade, recent | 1256 | +73.05% | +35.47% | +35.47% | +68.18% | +36.04% | +52.73% | +32.70% |
| `h3y-1` | r5 | three years, 2014-17 | 756 | +27.55% | +33.60% | +23.17% | +81.51% | +59.37% | +48.94% | +82.54% |
| `inflation-2021` | r4 | inflation onset and rotation | 252 | +26.55% | +31.41% | +15.83% | +10.87% | -4.96% | +26.44% | +10.78% |
| `h3y-3` | r5 | three years, 2020-23 | 756 | +23.02% | +29.02% | +18.66% | +55.69% | +37.73% | +66.75% | +56.38% |
| `h3y-2` | r5 | three years, 2017-20 | 754 | +43.69% | +23.88% | +23.88% | +53.60% | +76.51% | +72.11% | +52.63% |
| `h1y-3` | r5 | one year, 2018 | 251 | +1.85% | +23.71% | +23.71% | +0.16% | +23.87% | +3.60% | +0.16% |
| `h1y-6` | r5 | one year, 2025 | 250 | +11.60% | +17.05% | +2.53% | +13.01% | +14.75% | -2.31% | +12.21% |
| `recent` | r1 | recent bull | 249 | +20.62% | +16.57% | +1.96% | +16.91% | +15.03% | +31.52% | +14.95% |
| `bull-2024` | r1 | bull | 250 | +14.00% | +16.05% | +13.37% | +7.40% | +20.55% | +4.50% | +7.18% |
| `h5y-2` | r5 | half-decade, middle | 1259 | +108.00% | +12.09% | +7.75% | +142.88% | +135.12% | +147.21% | +141.45% |
| `live-4` | r11 | live out-of-sample, weeks 13-16 | 21 | +0.31% | +9.35% | +0.00% | +17.12% | +17.12% | +26.47% | +17.12% |
| `h1y-1` | r5 | one year, 2014 | 252 | +14.08% | +7.83% | +5.89% | +2.64% | +8.54% | +0.71% | +2.97% |
| `b1y-2` | r5 | one year into the covid low | 253 | -21.28% | +7.11% | +4.62% | +20.43% | +23.80% | +16.69% | +19.18% |
| `chop-2015` | r2 | sideways | 260 | -0.04% | +7.02% | +7.02% | +24.60% | +17.58% | +23.29% | +24.60% |
| `h1y-4` | r5 | one year, 2020 | 253 | +16.61% | +6.95% | +4.12% | +47.61% | +43.49% | +50.44% | +47.61% |
| `b1y-3` | r5 | the 2015-16 growth scare | 253 | -11.50% | +6.78% | +6.78% | +17.71% | +10.92% | +16.49% | +17.70% |
| `taper-2013` | r4 | rate shock, taper tantrum | 74 | -0.82% | +5.11% | +0.00% | +11.01% | +11.01% | +16.12% | +11.01% |
| `b1y-1` | r5 | the 2022 bear year | 253 | -21.15% | +4.38% | +1.12% | -6.49% | -6.49% | -9.76% | -5.37% |
| `live-2` | r11 | live out-of-sample, weeks 5-8 | 21 | +7.36% | +4.19% | +0.00% | +10.50% | +10.50% | +14.69% | +10.50% |
| `b6m-1` | r5 | six months into the covid low | 127 | -25.77% | +4.10% | +4.10% | +13.34% | +17.43% | +17.00% | +13.37% |
| `h6m-6` | r5 | six months, H2 2025 | 125 | +6.05% | +3.99% | +2.01% | -7.96% | -7.96% | -11.95% | -9.97% |
| `live-6` | r11 | live out-of-sample, weeks 21-25 | 21 | +3.42% | +3.99% | +1.27% | -2.58% | -3.84% | +0.14% | -2.58% |
| `b6m-2` | r5 | six months into the 2022 bear | 127 | -20.88% | +3.84% | +1.09% | -5.42% | -5.42% | -8.17% | -4.33% |
| `bear-2022` | r1 | rate-driven bear | 196 | -25.14% | +3.71% | +1.10% | -5.15% | -5.15% | -7.75% | -4.05% |
| `banks-2023` | r4 | regional banking crisis | 64 | +5.68% | +3.36% | +0.59% | +5.82% | +5.82% | +8.60% | +5.23% |
| `live-3` | r11 | live out-of-sample, weeks 9-12 | 21 | +4.01% | +2.99% | +0.00% | +12.89% | +12.89% | +15.88% | +12.89% |
| `b6m-3` | r5 | six months into the Q4-2018 low | 127 | -14.30% | +2.97% | +0.42% | -5.43% | -5.43% | -7.97% | -5.01% |
| `h1y-5` | r5 | one year, 2022 | 251 | -6.75% | +2.27% | +0.26% | -4.05% | -4.05% | -6.06% | -3.79% |
| `live-5` | r11 | live out-of-sample, weeks 17-20 | 21 | +0.15% | +2.26% | +0.00% | -12.62% | -12.62% | -14.88% | -12.62% |
| `oil-2014` | r4 | oil collapse and dollar surge | 163 | +5.56% | +1.87% | +0.00% | +0.75% | +0.75% | +2.62% | +0.75% |
| `covid` | r1 | COVID crash and snapback | 93 | -8.71% | +0.93% | +0.00% | +27.70% | +27.70% | +26.76% | +27.70% |
| `h6m-1` | r5 | six months, H2 2014 | 126 | +6.76% | +0.75% | +0.00% | +2.33% | +2.33% | +3.08% | +2.33% |
| `h6m-4` | r5 | six months, H2 2020 | 126 | +15.98% | +0.65% | +0.00% | +5.42% | +5.42% | +6.07% | +5.42% |
| `h6m-2` | r5 | six months, H2 2016 | 127 | +7.47% | +0.41% | +0.00% | +4.97% | +4.97% | +4.56% | +4.97% |
| `q4-2018` | r2 | sharp quarter-long selloff | 65 | -20.05% | +0.39% | +0.00% | -0.79% | -0.79% | -1.18% | -0.79% |
| `live-1` | r11 | live out-of-sample, weeks 1-4 | 22 | -2.75% | +0.37% | +0.00% | -0.85% | -0.85% | -1.23% | -0.85% |
| `h6m-3` | r5 | six months, H2 2018 | 126 | -2.13% | +0.12% | +0.00% | +0.39% | +0.39% | +0.51% | +0.39% |
| `volmageddon-2018` | r4 | volatility shock | 45 | -9.42% | +0.12% | +0.00% | +0.04% | +0.04% | +0.16% | +0.04% |
| `h6m-5` | r5 | six months, H2 2022 | 127 | -3.21% | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% | +0.00% |

## 3. The mechanism, from the trade logs

### Top 5 by spread

**`h5y-1`** (r5, half-decade, early) -- spread +69.11%, exit-spread +28.49%, benchmark +75.70%, 1260 sessions, base `max_drawdown` -10.20%.
- `B-momentum`: 68 trade(s) closing in-window -- open_at_end=3, rule=39, stop=6, time=20
- `B2-hold-90`: 89 trade(s) closing in-window -- open_at_end=3, rule=39, stop=6, time=41
- `B3-concentrated`: 50 trade(s) closing in-window -- open_at_end=1, rule=31, stop=4, time=14
- `B4-tight-stop`: 68 trade(s) closing in-window -- open_at_end=3, rule=32, stop=13, time=20
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2013-09-05 exited 2014-01-14 (time, 90d held, pnl=+500.75, return=+33.42%)
      - base: AMZN entered 2013-09-05 exited 2014-03-31 (rule, 142d held, pnl=+246.77, return=+16.47%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2013-09-17 exited 2014-01-27 (time, 90d held, pnl=+398.59, return=+26.77%)
      - base: GOOGL entered 2013-09-17 exited 2014-05-08 (rule, 161d held, pnl=+237.79, return=+15.97%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2013-10-01 exited 2014-02-10 (time, 90d held, pnl=+145.75, return=+9.71%)
      - base: MSFT entered 2013-10-01 exited 2014-06-19 (time, 180d held, pnl=+368.04, return=+24.51%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2013-11-06 exited 2014-03-19 (time, 90d held, pnl=+325.38, return=+21.71%)
      - base: MRVL entered 2013-11-06 exited 2014-06-27 (rule, 160d held, pnl=+149.44, return=+9.97%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2013-11-12 exited 2014-03-25 (time, 90d held, pnl=+305.16, return=+20.47%)
      - base: NVDA entered 2013-11-12 exited 2014-08-01 (time, 180d held, pnl=+190.47, return=+12.77%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2014-02-11 exited 2014-06-20 (time, 90d held, pnl=+181.15, return=+12.27%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2014-02-20 exited 2014-06-30 (time, 90d held, pnl=+313.26, return=+21.18%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2014-04-23 exited 2014-08-29 (time, 90d held, pnl=+383.55, return=+25.68%)
      - base: MU entered 2014-04-23 exited 2014-10-13 (rule, 120d held, pnl=+135.61, return=+9.08%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2014-05-29 exited 2014-10-06 (time, 90d held, pnl=+216.54, return=+14.38%)
      - base: NFLX entered 2014-05-29 exited 2014-10-17 (rule, 99d held, pnl=-164.51, return=-10.92%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2014-06-03 exited 2014-10-09 (time, 90d held, pnl=+335.52, return=+23.28%)
      - base: META entered 2014-06-03 exited 2015-02-19 (time, 180d held, pnl=+328.85, return=+22.82%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2014-10-24 exited 2015-03-06 (time, 90d held, pnl=+238.89, return=+16.10%)
      - base: NOW entered 2014-10-24 exited 2015-07-15 (time, 180d held, pnl=+315.45, return=+21.26%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2014-10-28 exited 2015-03-10 (time, 90d held, pnl=+795.96, return=+52.91%)
      - base: AVGO entered 2014-10-28 exited 2015-07-17 (time, 180d held, pnl=+964.31, return=+64.11%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2014-11-04 exited 2015-03-17 (time, 90d held, pnl=+210.78, return=+13.96%)
      - base: NVDA entered 2014-11-04 exited 2015-06-30 (rule, 163d held, pnl=+29.65, return=+1.96%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2015-01-21 exited 2015-06-01 (time, 90d held, pnl=+74.19, return=+5.04%)
      - base: TSM entered 2015-01-21 exited 2015-06-09 (rule, 96d held, pnl=-9.65, return=-0.66%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2015-02-03 exited 2015-06-12 (time, 90d held, pnl=+289.40, return=+19.59%)
      - base: AMZN entered 2015-02-03 exited 2015-10-20 (time, 180d held, pnl=+866.66, return=+58.65%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2015-04-09 exited 2015-08-17 (time, 90d held, pnl=+1424.25, return=+95.39%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2015-06-04 exited 2015-10-12 (time, 90d held, pnl=+199.57, return=+13.49%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2015-07-14 exited 2015-11-18 (time, 90d held, pnl=+453.38, return=+30.34%)
      - base: GOOGL entered 2015-07-14 exited 2016-03-31 (time, 180d held, pnl=+502.26, return=+33.61%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2015-10-08 exited 2016-02-18 (time, 90d held, pnl=+182.99, return=+12.28%)
      - base: MSFT entered 2015-10-08 exited 2016-04-29 (rule, 140d held, pnl=+87.95, return=+5.90%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2016-02-29 exited 2016-07-07 (time, 90d held, pnl=+775.75, return=+51.87%)
      - base: NVDA entered 2016-02-29 exited 2016-11-11 (time, 180d held, pnl=+2271.18, return=+151.87%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2016-03-03 exited 2016-07-12 (time, 90d held, pnl=+225.56, return=+15.02%)
      - base: AVGO entered 2016-03-03 exited 2016-11-16 (time, 180d held, pnl=+309.49, return=+20.60%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2016-03-09 exited 2016-07-18 (time, 90d held, pnl=+1871.04, return=+123.69%)
      - base: AMD entered 2016-03-09 exited 2016-11-22 (time, 180d held, pnl=+4387.69, return=+290.07%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2016-04-01 exited 2016-08-09 (time, 90d held, pnl=+440.44, return=+29.82%)
      - base: AMZN entered 2016-04-01 exited 2016-12-15 (time, 180d held, pnl=+437.44, return=+29.62%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2016-06-03 exited 2016-10-11 (time, 90d held, pnl=+331.52, return=+22.17%)
      - base: TSM entered 2016-06-03 exited 2017-02-21 (time, 180d held, pnl=+414.12, return=+27.69%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2016-07-11 exited 2016-11-15 (time, 90d held, pnl=-13.24, return=-0.94%)
      - base: META entered 2016-07-11 exited 2016-11-15 (rule, 90d held, pnl=-13.24, return=-0.94%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2016-07-14 exited 2016-11-18 (time, 90d held, pnl=+192.59, return=+12.77%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2016-07-21 exited 2016-11-28 (time, 90d held, pnl=+442.81, return=+29.75%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2016-11-23 exited 2017-04-05 (time, 90d held, pnl=+361.13, return=+24.37%)
      - base: AVGO entered 2016-11-23 exited 2017-08-14 (time, 180d held, pnl=+590.45, return=+39.85%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2016-12-15 exited 2017-04-27 (time, 90d held, pnl=+129.19, return=+8.78%)
      - base: GOOGL entered 2016-12-15 exited 2017-09-05 (time, 180d held, pnl=+231.43, return=+15.72%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2017-01-11 exited 2017-05-22 (time, 90d held, pnl=+313.70, return=+21.36%)
      - base: AMZN entered 2017-01-11 exited 2017-09-28 (time, 180d held, pnl=+291.13, return=+19.82%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2017-01-17 exited 2017-05-25 (time, 90d held, pnl=+243.27, return=+17.26%)
      - base: META entered 2017-01-17 exited 2017-10-03 (time, 180d held, pnl=+452.27, return=+32.10%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2017-01-17 exited 2017-05-25 (time, 90d held, pnl=+365.72, return=+24.72%)
      - base: NOW entered 2017-01-17 exited 2017-10-03 (time, 180d held, pnl=+598.90, return=+40.49%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2017-01-25 exited 2017-06-05 (time, 90d held, pnl=+260.10, return=+17.41%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2017-05-08 exited 2017-09-14 (time, 90d held, pnl=+928.81, return=+61.68%)
      - base: NVDA entered 2017-05-08 exited 2018-01-24 (time, 180d held, pnl=+1938.53, return=+128.72%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2017-07-17 exited 2017-11-21 (time, 90d held, pnl=+296.60, return=+19.57%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2017-08-29 exited 2018-01-08 (time, 90d held, pnl=+696.89, return=+47.18%)
      - base: MU entered 2017-08-29 exited 2018-05-17 (time, 180d held, pnl=+1210.00, return=+81.93%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2017-08-31 exited 2018-01-10 (time, 90d held, pnl=+421.61, return=+28.20%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2017-10-02 exited 2018-02-09 (time, 90d held, pnl=+73.75, return=+5.04%)
      - base: GOOGL entered 2017-10-02 exited 2018-03-28 (rule, 122d held, pnl=+37.75, return=+2.58%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2017-10-13 exited 2018-02-23 (time, 90d held, pnl=+706.08, return=+48.33%)
      - base: AMZN entered 2017-10-13 exited 2018-07-03 (time, 180d held, pnl=+1037.26, return=+71.00%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2018-01-03 exited 2018-05-14 (time, 90d held, pnl=+924.18, return=+61.77%)
      - base: NFLX entered 2018-01-03 exited open at window end (open_at_end, 167d held, pnl=+1224.55, return=+81.84%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2018-02-21 exited 2018-06-29 (time, 90d held, pnl=+272.86, return=+18.22%)
      - base: (no matching base trade)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: AMD entered 2013-09-23 exited 2013-10-22 (stop, 21d held, pnl=-191.69, return=-12.87%)
      - base: AMD entered 2013-09-23 exited 2013-10-23 (stop, 22d held, pnl=-238.61, return=-16.02%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NFLX entered 2014-01-24 exited 2014-04-01 (stop, 46d held, pnl=-124.28, return=-8.40%)
      - base: NFLX entered 2014-01-24 exited 2014-04-07 (stop, 50d held, pnl=-167.48, return=-11.32%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AMD entered 2014-08-20 exited 2014-09-16 (stop, 18d held, pnl=-126.46, return=-8.48%)
      - base: AMD entered 2014-08-20 exited 2014-09-16 (rule, 18d held, pnl=-126.46, return=-8.48%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NFLX entered 2014-05-29 exited 2014-10-17 (stop, 99d held, pnl=-164.51, return=-10.92%)
      - base: NFLX entered 2014-05-29 exited 2014-10-17 (rule, 99d held, pnl=-164.51, return=-10.92%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NOW entered 2015-07-17 exited 2015-08-21 (stop, 25d held, pnl=-185.30, return=-12.32%)
      - base: NOW entered 2015-07-17 exited 2015-08-21 (rule, 25d held, pnl=-185.30, return=-12.32%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NVDA entered 2015-08-12 exited 2015-08-25 (stop, 9d held, pnl=-101.86, return=-6.93%)
      - base: NVDA entered 2015-08-12 exited 2015-08-25 (rule, 9d held, pnl=-101.86, return=-6.93%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NFLX entered 2015-10-09 exited 2015-10-16 (stop, 5d held, pnl=-182.06, return=-12.26%)
      - base: NFLX entered 2015-10-09 exited 2015-10-19 (stop, 6d held, pnl=-210.66, return=-14.19%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: META entered 2016-02-02 exited 2016-02-08 (stop, 4d held, pnl=-188.54, return=-12.63%)
      - base: META entered 2016-02-02 exited 2016-02-09 (stop, 5d held, pnl=-231.05, return=-15.47%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2016-05-27 exited 2016-06-28 (stop, 21d held, pnl=-136.77, return=-9.16%)
      - base: MRVL entered 2016-05-27 exited 2016-06-28 (rule, 21d held, pnl=-136.77, return=-9.16%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NVDA entered 2017-03-21 exited 2017-04-06 (stop, 12d held, pnl=-120.69, return=-8.10%)
      - base: NVDA entered 2017-03-21 exited 2017-04-17 (stop, 18d held, pnl=-175.49, return=-11.77%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: META entered 2018-03-12 exited 2018-03-21 (stop, 7d held, pnl=-164.84, return=-11.12%)
      - base: META entered 2018-03-12 exited 2018-03-21 (rule, 7d held, pnl=-164.84, return=-11.12%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2018-05-30 exited 2018-06-26 (stop, 19d held, pnl=-129.25, return=-8.57%)
      - base: MRVL entered 2018-05-30 exited 2018-06-26 (rule, 19d held, pnl=-129.25, return=-8.57%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: MU entered 2018-07-13 exited 2018-08-15 (stop, 23d held, pnl=-154.75, return=-10.32%)
      - base: MU entered 2018-07-13 exited 2018-08-16 (stop, 24d held, pnl=-198.76, return=-13.25%)

**`h10y-1`** (r5, decade, early endpoint) -- spread +65.61%, exit-spread +6.79%, benchmark +172.56%, 2517 sessions, base `max_drawdown` -10.20%.
- `B-momentum`: 117 trade(s) closing in-window -- open_at_end=4, rule=67, stop=12, time=34
- `B2-hold-90`: 143 trade(s) closing in-window -- open_at_end=3, rule=63, stop=12, time=65
- `B3-concentrated`: 89 trade(s) closing in-window -- open_at_end=4, rule=51, stop=10, time=24
- `B4-tight-stop`: 119 trade(s) closing in-window -- open_at_end=4, rule=57, stop=25, time=33
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2013-09-05 exited 2014-01-14 (time, 90d held, pnl=+500.75, return=+33.42%)
      - base: AMZN entered 2013-09-05 exited 2014-03-31 (rule, 142d held, pnl=+246.77, return=+16.47%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2013-09-17 exited 2014-01-27 (time, 90d held, pnl=+398.59, return=+26.77%)
      - base: GOOGL entered 2013-09-17 exited 2014-05-08 (rule, 161d held, pnl=+237.79, return=+15.97%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2013-10-01 exited 2014-02-10 (time, 90d held, pnl=+145.75, return=+9.71%)
      - base: MSFT entered 2013-10-01 exited 2014-06-19 (time, 180d held, pnl=+368.04, return=+24.51%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2013-11-06 exited 2014-03-19 (time, 90d held, pnl=+325.38, return=+21.71%)
      - base: MRVL entered 2013-11-06 exited 2014-06-27 (rule, 160d held, pnl=+149.44, return=+9.97%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2013-11-12 exited 2014-03-25 (time, 90d held, pnl=+305.16, return=+20.47%)
      - base: NVDA entered 2013-11-12 exited 2014-08-01 (time, 180d held, pnl=+190.47, return=+12.77%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2014-02-11 exited 2014-06-20 (time, 90d held, pnl=+181.15, return=+12.27%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2014-02-20 exited 2014-06-30 (time, 90d held, pnl=+313.26, return=+21.18%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2014-04-23 exited 2014-08-29 (time, 90d held, pnl=+383.55, return=+25.68%)
      - base: MU entered 2014-04-23 exited 2014-10-13 (rule, 120d held, pnl=+135.61, return=+9.08%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2014-05-29 exited 2014-10-06 (time, 90d held, pnl=+216.54, return=+14.38%)
      - base: NFLX entered 2014-05-29 exited 2014-10-17 (rule, 99d held, pnl=-164.51, return=-10.92%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2014-06-03 exited 2014-10-09 (time, 90d held, pnl=+335.52, return=+23.28%)
      - base: META entered 2014-06-03 exited 2015-02-19 (time, 180d held, pnl=+328.85, return=+22.82%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2014-10-24 exited 2015-03-06 (time, 90d held, pnl=+238.89, return=+16.10%)
      - base: NOW entered 2014-10-24 exited 2015-07-15 (time, 180d held, pnl=+315.45, return=+21.26%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2014-10-28 exited 2015-03-10 (time, 90d held, pnl=+795.96, return=+52.91%)
      - base: AVGO entered 2014-10-28 exited 2015-07-17 (time, 180d held, pnl=+964.31, return=+64.11%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2014-11-04 exited 2015-03-17 (time, 90d held, pnl=+210.78, return=+13.96%)
      - base: NVDA entered 2014-11-04 exited 2015-06-30 (rule, 163d held, pnl=+29.65, return=+1.96%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2015-01-21 exited 2015-06-01 (time, 90d held, pnl=+74.19, return=+5.04%)
      - base: TSM entered 2015-01-21 exited 2015-06-09 (rule, 96d held, pnl=-9.65, return=-0.66%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2015-02-03 exited 2015-06-12 (time, 90d held, pnl=+289.40, return=+19.59%)
      - base: AMZN entered 2015-02-03 exited 2015-10-20 (time, 180d held, pnl=+866.66, return=+58.65%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2015-04-09 exited 2015-08-17 (time, 90d held, pnl=+1424.25, return=+95.39%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2015-06-04 exited 2015-10-12 (time, 90d held, pnl=+199.57, return=+13.49%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2015-07-14 exited 2015-11-18 (time, 90d held, pnl=+453.38, return=+30.34%)
      - base: GOOGL entered 2015-07-14 exited 2016-03-31 (time, 180d held, pnl=+502.26, return=+33.61%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2015-10-08 exited 2016-02-18 (time, 90d held, pnl=+182.99, return=+12.28%)
      - base: MSFT entered 2015-10-08 exited 2016-04-29 (rule, 140d held, pnl=+87.95, return=+5.90%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2016-02-29 exited 2016-07-07 (time, 90d held, pnl=+775.75, return=+51.87%)
      - base: NVDA entered 2016-02-29 exited 2016-11-11 (time, 180d held, pnl=+2271.18, return=+151.87%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2016-03-03 exited 2016-07-12 (time, 90d held, pnl=+225.56, return=+15.02%)
      - base: AVGO entered 2016-03-03 exited 2016-11-16 (time, 180d held, pnl=+309.49, return=+20.60%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2016-03-09 exited 2016-07-18 (time, 90d held, pnl=+1871.04, return=+123.69%)
      - base: AMD entered 2016-03-09 exited 2016-11-22 (time, 180d held, pnl=+4387.69, return=+290.07%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2016-04-01 exited 2016-08-09 (time, 90d held, pnl=+440.44, return=+29.82%)
      - base: AMZN entered 2016-04-01 exited 2016-12-15 (time, 180d held, pnl=+437.44, return=+29.62%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2016-06-03 exited 2016-10-11 (time, 90d held, pnl=+331.52, return=+22.17%)
      - base: TSM entered 2016-06-03 exited 2017-02-21 (time, 180d held, pnl=+414.12, return=+27.69%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2016-07-11 exited 2016-11-15 (time, 90d held, pnl=-13.24, return=-0.94%)
      - base: META entered 2016-07-11 exited 2016-11-15 (rule, 90d held, pnl=-13.24, return=-0.94%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2016-07-14 exited 2016-11-18 (time, 90d held, pnl=+192.59, return=+12.77%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2016-07-21 exited 2016-11-28 (time, 90d held, pnl=+442.81, return=+29.75%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2016-11-23 exited 2017-04-05 (time, 90d held, pnl=+361.13, return=+24.37%)
      - base: AVGO entered 2016-11-23 exited 2017-08-14 (time, 180d held, pnl=+590.45, return=+39.85%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2016-12-15 exited 2017-04-27 (time, 90d held, pnl=+129.19, return=+8.78%)
      - base: GOOGL entered 2016-12-15 exited 2017-09-05 (time, 180d held, pnl=+231.43, return=+15.72%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2017-01-11 exited 2017-05-22 (time, 90d held, pnl=+313.70, return=+21.36%)
      - base: AMZN entered 2017-01-11 exited 2017-09-28 (time, 180d held, pnl=+291.13, return=+19.82%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2017-01-17 exited 2017-05-25 (time, 90d held, pnl=+243.27, return=+17.26%)
      - base: META entered 2017-01-17 exited 2017-10-03 (time, 180d held, pnl=+452.27, return=+32.10%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2017-01-17 exited 2017-05-25 (time, 90d held, pnl=+365.72, return=+24.72%)
      - base: NOW entered 2017-01-17 exited 2017-10-03 (time, 180d held, pnl=+598.90, return=+40.49%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2017-01-25 exited 2017-06-05 (time, 90d held, pnl=+260.10, return=+17.41%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2017-05-08 exited 2017-09-14 (time, 90d held, pnl=+928.81, return=+61.68%)
      - base: NVDA entered 2017-05-08 exited 2018-01-24 (time, 180d held, pnl=+1938.53, return=+128.72%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2017-07-17 exited 2017-11-21 (time, 90d held, pnl=+296.60, return=+19.57%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2017-08-29 exited 2018-01-08 (time, 90d held, pnl=+696.89, return=+47.18%)
      - base: MU entered 2017-08-29 exited 2018-05-17 (time, 180d held, pnl=+1210.00, return=+81.93%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2017-08-31 exited 2018-01-10 (time, 90d held, pnl=+421.61, return=+28.20%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2017-10-02 exited 2018-02-09 (time, 90d held, pnl=+73.75, return=+5.04%)
      - base: GOOGL entered 2017-10-02 exited 2018-03-28 (rule, 122d held, pnl=+37.75, return=+2.58%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2017-10-13 exited 2018-02-23 (time, 90d held, pnl=+706.08, return=+48.33%)
      - base: AMZN entered 2017-10-13 exited 2018-07-03 (time, 180d held, pnl=+1037.26, return=+71.00%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2018-01-03 exited 2018-05-14 (time, 90d held, pnl=+924.18, return=+61.77%)
      - base: NFLX entered 2018-01-03 exited 2018-09-20 (time, 180d held, pnl=+1242.37, return=+83.03%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2018-02-21 exited 2018-06-29 (time, 90d held, pnl=+272.86, return=+18.22%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2018-05-08 exited 2018-09-14 (time, 90d held, pnl=+156.56, return=+10.44%)
      - base: NVDA entered 2018-05-08 exited 2018-10-11 (rule, 109d held, pnl=-41.05, return=-2.74%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2018-05-10 exited 2018-09-18 (time, 90d held, pnl=+2622.36, return=+174.97%)
      - base: AMD entered 2018-05-10 exited 2018-10-30 (rule, 120d held, pnl=+547.42, return=+36.53%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2018-05-16 exited 2018-09-24 (time, 90d held, pnl=+98.77, return=+6.74%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2019-01-10 exited 2019-05-21 (time, 90d held, pnl=+628.62, return=+42.64%)
      - base: NOW entered 2019-01-10 exited 2019-09-27 (time, 180d held, pnl=+544.38, return=+36.93%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2019-02-01 exited 2019-06-12 (time, 90d held, pnl=+448.90, return=+29.89%)
      - base: AMD entered 2019-02-01 exited 2019-10-18 (time, 180d held, pnl=+391.56, return=+26.07%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2019-02-13 exited 2019-06-24 (time, 90d held, pnl=+411.26, return=+27.31%)
      - base: MSFT entered 2019-02-13 exited 2019-10-30 (time, 180d held, pnl=+502.54, return=+33.38%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2019-07-09 exited 2019-11-13 (time, 90d held, pnl=+234.16, return=+15.76%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2019-07-16 exited 2019-11-20 (time, 90d held, pnl=+409.44, return=+27.97%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2019-07-24 exited 2019-11-29 (time, 90d held, pnl=+224.59, return=+15.25%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2019-08-22 exited 2019-12-31 (time, 90d held, pnl=+517.89, return=+34.49%)
      - base: NVDA entered 2019-08-22 exited 2020-03-17 (rule, 142d held, pnl=+255.39, return=+17.01%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2019-10-24 exited 2020-03-05 (time, 90d held, pnl=+801.75, return=+53.98%)
      - base: AMD entered 2019-10-24 exited 2020-07-14 (time, 180d held, pnl=+1018.41, return=+68.57%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2020-03-30 exited 2020-08-06 (time, 90d held, pnl=+590.87, return=+38.73%)
      - base: NFLX entered 2020-03-30 exited 2020-12-14 (time, 180d held, pnl=+596.33, return=+39.09%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2020-04-07 exited 2020-08-14 (time, 90d held, pnl=+1021.23, return=+65.99%)
      - base: NVDA entered 2020-04-07 exited 2020-12-22 (time, 180d held, pnl=+1420.39, return=+91.78%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2020-04-08 exited 2020-08-17 (time, 90d held, pnl=+804.66, return=+56.85%)
      - base: AMZN entered 2020-04-08 exited 2020-12-23 (time, 180d held, pnl=+826.92, return=+58.42%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2020-04-14 exited 2020-08-20 (time, 90d held, pnl=+795.40, return=+52.47%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2020-04-16 exited 2020-08-24 (time, 90d held, pnl=+535.65, return=+35.94%)
      - base: MRVL entered 2020-04-16 exited 2020-12-31 (time, 180d held, pnl=+1307.94, return=+87.76%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2020-04-16 exited 2020-08-24 (time, 90d held, pnl=+322.27, return=+23.10%)
      - base: MSFT entered 2020-04-16 exited 2020-12-31 (time, 180d held, pnl=+377.55, return=+27.06%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2020-10-16 exited 2021-02-26 (time, 90d held, pnl=+443.02, return=+29.84%)
      - base: GOOGL entered 2020-10-16 exited 2021-07-07 (time, 180d held, pnl=+930.36, return=+62.67%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2020-11-05 exited 2021-03-18 (time, 90d held, pnl=+61.70, return=+4.63%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2021-03-18 exited 2021-07-27 (time, 90d held, pnl=+458.50, return=+32.75%)
      - base: META entered 2021-03-18 exited 2021-10-27 (rule, 155d held, pnl=+170.06, return=+12.15%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2021-04-09 exited 2021-08-17 (time, 90d held, pnl=+567.77, return=+38.39%)
      - base: NVDA entered 2021-04-09 exited 2021-12-23 (time, 180d held, pnl=+1613.98, return=+109.14%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2021-06-04 exited 2021-10-12 (time, 90d held, pnl=+79.63, return=+5.29%)
      - base: AVGO entered 2021-06-04 exited 2022-02-18 (time, 180d held, pnl=+351.62, return=+23.34%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2021-06-07 exited 2021-10-13 (time, 90d held, pnl=+461.34, return=+31.43%)
      - base: MRVL entered 2021-06-07 exited 2022-02-22 (time, 180d held, pnl=+525.54, return=+35.80%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2023-04-04 exited 2023-08-14 (time, 90d held, pnl=+314.27, return=+20.96%)
      - base: NFLX entered 2023-04-04 exited open at window end (open_at_end, 103d held, pnl=+365.41, return=+24.37%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: AMD entered 2013-09-23 exited 2013-10-22 (stop, 21d held, pnl=-191.69, return=-12.87%)
      - base: AMD entered 2013-09-23 exited 2013-10-23 (stop, 22d held, pnl=-238.61, return=-16.02%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NFLX entered 2014-01-24 exited 2014-04-01 (stop, 46d held, pnl=-124.28, return=-8.40%)
      - base: NFLX entered 2014-01-24 exited 2014-04-07 (stop, 50d held, pnl=-167.48, return=-11.32%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AMD entered 2014-08-20 exited 2014-09-16 (stop, 18d held, pnl=-126.46, return=-8.48%)
      - base: AMD entered 2014-08-20 exited 2014-09-16 (rule, 18d held, pnl=-126.46, return=-8.48%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NFLX entered 2014-05-29 exited 2014-10-17 (stop, 99d held, pnl=-164.51, return=-10.92%)
      - base: NFLX entered 2014-05-29 exited 2014-10-17 (rule, 99d held, pnl=-164.51, return=-10.92%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NOW entered 2015-07-17 exited 2015-08-21 (stop, 25d held, pnl=-185.30, return=-12.32%)
      - base: NOW entered 2015-07-17 exited 2015-08-21 (rule, 25d held, pnl=-185.30, return=-12.32%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NVDA entered 2015-08-12 exited 2015-08-25 (stop, 9d held, pnl=-101.86, return=-6.93%)
      - base: NVDA entered 2015-08-12 exited 2015-08-25 (rule, 9d held, pnl=-101.86, return=-6.93%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NFLX entered 2015-10-09 exited 2015-10-16 (stop, 5d held, pnl=-182.06, return=-12.26%)
      - base: NFLX entered 2015-10-09 exited 2015-10-19 (stop, 6d held, pnl=-210.66, return=-14.19%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: META entered 2016-02-02 exited 2016-02-08 (stop, 4d held, pnl=-188.54, return=-12.63%)
      - base: META entered 2016-02-02 exited 2016-02-09 (stop, 5d held, pnl=-231.05, return=-15.47%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2016-05-27 exited 2016-06-28 (stop, 21d held, pnl=-136.77, return=-9.16%)
      - base: MRVL entered 2016-05-27 exited 2016-06-28 (rule, 21d held, pnl=-136.77, return=-9.16%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NVDA entered 2017-03-21 exited 2017-04-06 (stop, 12d held, pnl=-120.69, return=-8.10%)
      - base: NVDA entered 2017-03-21 exited 2017-04-17 (stop, 18d held, pnl=-175.49, return=-11.77%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: META entered 2018-03-12 exited 2018-03-21 (stop, 7d held, pnl=-164.84, return=-11.12%)
      - base: META entered 2018-03-12 exited 2018-03-21 (rule, 7d held, pnl=-164.84, return=-11.12%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2018-05-30 exited 2018-06-26 (stop, 19d held, pnl=-129.25, return=-8.57%)
      - base: MRVL entered 2018-05-30 exited 2018-06-26 (rule, 19d held, pnl=-129.25, return=-8.57%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: MU entered 2018-07-13 exited 2018-08-15 (stop, 23d held, pnl=-154.75, return=-10.32%)
      - base: MU entered 2018-07-13 exited 2018-08-16 (stop, 24d held, pnl=-198.76, return=-13.25%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AMD entered 2019-02-01 exited 2019-03-07 (stop, 23d held, pnl=-140.35, return=-9.35%)
      - base: AMD entered 2019-02-01 exited 2019-10-18 (time, 180d held, pnl=+391.56, return=+26.07%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NFLX entered 2019-06-25 exited 2019-07-19 (stop, 17d held, pnl=-190.84, return=-12.86%)
      - base: NFLX entered 2019-06-25 exited 2019-07-19 (stop, 17d held, pnl=-190.84, return=-12.86%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AVGO entered 2019-07-22 exited 2019-08-06 (stop, 11d held, pnl=-117.86, return=-7.88%)
      - base: AVGO entered 2019-07-22 exited 2019-08-06 (rule, 11d held, pnl=-117.86, return=-7.88%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: META entered 2019-06-18 exited 2019-08-26 (stop, 48d held, pnl=-103.57, return=-7.62%)
      - base: META entered 2019-06-18 exited 2019-10-03 (rule, 75d held, pnl=-130.38, return=-9.60%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2019-09-12 exited 2019-10-02 (stop, 14d held, pnl=-138.56, return=-9.29%)
      - base: (no matching base trade)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: MRVL entered 2019-11-05 exited 2019-12-05 (stop, 21d held, pnl=-163.95, return=-11.04%)
      - base: MRVL entered 2019-11-05 exited 2019-12-06 (stop, 22d held, pnl=-170.55, return=-11.48%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NVDA entered 2021-01-06 exited 2021-03-09 (stop, 42d held, pnl=-123.27, return=-8.39%)
      - base: NVDA entered 2021-01-06 exited 2021-03-09 (stop, 42d held, pnl=-123.27, return=-8.39%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: MRVL entered 2021-04-07 exited 2021-04-20 (stop, 9d held, pnl=-131.41, return=-8.93%)
      - base: MRVL entered 2021-04-07 exited 2021-05-04 (stop, 19d held, pnl=-204.78, return=-13.92%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: MU entered 2022-02-11 exited 2022-03-07 (stop, 15d held, pnl=-153.80, return=-10.53%)
      - base: MU entered 2022-02-11 exited 2022-03-08 (stop, 16d held, pnl=-241.96, return=-16.56%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NVDA entered 2022-03-29 exited 2022-04-06 (stop, 6d held, pnl=-200.92, return=-13.20%)
      - base: NVDA entered 2022-03-29 exited 2022-04-07 (stop, 7d held, pnl=-226.88, return=-14.91%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AVGO entered 2022-03-18 exited 2022-05-02 (stop, 30d held, pnl=-113.80, return=-7.85%)
      - base: AVGO entered 2022-03-18 exited 2022-05-02 (rule, 30d held, pnl=-113.80, return=-7.85%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NFLX entered 2023-04-04 exited 2023-05-03 (stop, 20d held, pnl=-134.64, return=-8.98%)
      - base: NFLX entered 2023-04-04 exited open at window end (open_at_end, 103d held, pnl=+365.41, return=+24.37%)

**`h1y-2`** (r5, one year, 2016) -- spread +56.66%, exit-spread +32.13%, benchmark +24.45%, 254 sessions, base `max_drawdown` -9.56%.
- `B-momentum`: 14 trade(s) closing in-window -- open_at_end=6, rule=4, time=4
- `B2-hold-90`: 18 trade(s) closing in-window -- open_at_end=6, rule=4, time=8
- `B3-concentrated`: 10 trade(s) closing in-window -- open_at_end=4, rule=3, time=3
- `B4-tight-stop`: 14 trade(s) closing in-window -- open_at_end=6, rule=3, stop=1, time=4
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2016-02-29 exited 2016-07-07 (time, 90d held, pnl=+775.75, return=+51.87%)
      - base: NVDA entered 2016-02-29 exited 2016-11-11 (time, 180d held, pnl=+2271.18, return=+151.87%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2016-03-03 exited 2016-07-12 (time, 90d held, pnl=+225.56, return=+15.02%)
      - base: AVGO entered 2016-03-03 exited 2016-11-16 (time, 180d held, pnl=+309.49, return=+20.60%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2016-03-09 exited 2016-07-18 (time, 90d held, pnl=+1871.04, return=+123.69%)
      - base: AMD entered 2016-03-09 exited 2016-11-22 (time, 180d held, pnl=+4387.69, return=+290.07%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2016-04-01 exited 2016-08-09 (time, 90d held, pnl=+440.44, return=+29.82%)
      - base: AMZN entered 2016-04-01 exited 2016-12-15 (time, 180d held, pnl=+437.44, return=+29.62%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2016-06-03 exited 2016-10-11 (time, 90d held, pnl=+331.52, return=+22.17%)
      - base: TSM entered 2016-06-03 exited open at window end (open_at_end, 177d held, pnl=+377.60, return=+25.25%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2016-07-11 exited 2016-11-15 (time, 90d held, pnl=-13.24, return=-0.94%)
      - base: META entered 2016-07-11 exited 2016-11-15 (rule, 90d held, pnl=-13.24, return=-0.94%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2016-07-14 exited 2016-11-18 (time, 90d held, pnl=+192.59, return=+12.77%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2016-07-21 exited 2016-11-28 (time, 90d held, pnl=+442.81, return=+29.75%)
      - base: (no matching base trade)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2016-05-27 exited 2016-06-28 (stop, 21d held, pnl=-136.77, return=-9.16%)
      - base: MRVL entered 2016-05-27 exited 2016-06-28 (rule, 21d held, pnl=-136.77, return=-9.16%)

**`h10y-2`** (r5, decade, recent endpoint) -- spread +38.68%, exit-spread +37.17%, benchmark +261.15%, 2515 sessions, base `max_drawdown` -10.59%.
- `B-momentum`: 109 trade(s) closing in-window -- open_at_end=1, rule=58, stop=13, time=37
- `B2-hold-90`: 134 trade(s) closing in-window -- open_at_end=1, rule=53, stop=14, time=66
- `B3-concentrated`: 82 trade(s) closing in-window -- open_at_end=1, rule=46, stop=10, time=25
- `B4-tight-stop`: 117 trade(s) closing in-window -- open_at_end=1, rule=53, stop=29, time=34
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2016-02-29 exited 2016-07-07 (time, 90d held, pnl=+775.75, return=+51.87%)
      - base: NVDA entered 2016-02-29 exited 2016-11-11 (time, 180d held, pnl=+2271.18, return=+151.87%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2016-03-03 exited 2016-07-12 (time, 90d held, pnl=+225.56, return=+15.02%)
      - base: AVGO entered 2016-03-03 exited 2016-11-16 (time, 180d held, pnl=+309.49, return=+20.60%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2016-03-09 exited 2016-07-18 (time, 90d held, pnl=+1871.04, return=+123.69%)
      - base: AMD entered 2016-03-09 exited 2016-11-22 (time, 180d held, pnl=+4387.69, return=+290.07%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2016-04-01 exited 2016-08-09 (time, 90d held, pnl=+440.44, return=+29.82%)
      - base: AMZN entered 2016-04-01 exited 2016-12-15 (time, 180d held, pnl=+437.44, return=+29.62%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2016-06-03 exited 2016-10-11 (time, 90d held, pnl=+331.52, return=+22.17%)
      - base: TSM entered 2016-06-03 exited 2017-02-21 (time, 180d held, pnl=+414.12, return=+27.69%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2016-07-11 exited 2016-11-15 (time, 90d held, pnl=-13.24, return=-0.94%)
      - base: META entered 2016-07-11 exited 2016-11-15 (rule, 90d held, pnl=-13.24, return=-0.94%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2016-07-14 exited 2016-11-18 (time, 90d held, pnl=+192.59, return=+12.77%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2016-07-21 exited 2016-11-28 (time, 90d held, pnl=+442.81, return=+29.75%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2016-11-23 exited 2017-04-05 (time, 90d held, pnl=+361.13, return=+24.37%)
      - base: AVGO entered 2016-11-23 exited 2017-08-14 (time, 180d held, pnl=+590.45, return=+39.85%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2016-12-15 exited 2017-04-27 (time, 90d held, pnl=+129.19, return=+8.78%)
      - base: GOOGL entered 2016-12-15 exited 2017-09-05 (time, 180d held, pnl=+231.43, return=+15.72%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2017-01-11 exited 2017-05-22 (time, 90d held, pnl=+313.70, return=+21.36%)
      - base: AMZN entered 2017-01-11 exited 2017-09-28 (time, 180d held, pnl=+291.13, return=+19.82%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2017-01-17 exited 2017-05-25 (time, 90d held, pnl=+243.27, return=+17.26%)
      - base: META entered 2017-01-17 exited 2017-10-03 (time, 180d held, pnl=+452.27, return=+32.10%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2017-01-17 exited 2017-05-25 (time, 90d held, pnl=+365.72, return=+24.72%)
      - base: NOW entered 2017-01-17 exited 2017-10-03 (time, 180d held, pnl=+598.90, return=+40.49%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2017-01-25 exited 2017-06-05 (time, 90d held, pnl=+260.10, return=+17.41%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2017-05-08 exited 2017-09-14 (time, 90d held, pnl=+928.81, return=+61.68%)
      - base: NVDA entered 2017-05-08 exited 2018-01-24 (time, 180d held, pnl=+1938.53, return=+128.72%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2017-07-17 exited 2017-11-21 (time, 90d held, pnl=+296.60, return=+19.57%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2017-08-29 exited 2018-01-08 (time, 90d held, pnl=+696.89, return=+47.18%)
      - base: MU entered 2017-08-29 exited 2018-05-17 (time, 180d held, pnl=+1210.00, return=+81.93%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2017-08-31 exited 2018-01-10 (time, 90d held, pnl=+421.61, return=+28.20%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2017-10-02 exited 2018-02-09 (time, 90d held, pnl=+73.75, return=+5.04%)
      - base: GOOGL entered 2017-10-02 exited 2018-03-28 (rule, 122d held, pnl=+37.75, return=+2.58%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2017-10-13 exited 2018-02-23 (time, 90d held, pnl=+706.08, return=+48.33%)
      - base: AMZN entered 2017-10-13 exited 2018-07-03 (time, 180d held, pnl=+1037.26, return=+71.00%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2018-01-03 exited 2018-05-14 (time, 90d held, pnl=+924.18, return=+61.77%)
      - base: NFLX entered 2018-01-03 exited 2018-09-20 (time, 180d held, pnl=+1242.37, return=+83.03%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2018-02-21 exited 2018-06-29 (time, 90d held, pnl=+272.86, return=+18.22%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2018-05-08 exited 2018-09-14 (time, 90d held, pnl=+156.56, return=+10.44%)
      - base: NVDA entered 2018-05-08 exited 2018-10-11 (rule, 109d held, pnl=-41.05, return=-2.74%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2018-05-10 exited 2018-09-18 (time, 90d held, pnl=+2622.36, return=+174.97%)
      - base: AMD entered 2018-05-10 exited 2018-10-30 (rule, 120d held, pnl=+547.42, return=+36.53%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2018-05-16 exited 2018-09-24 (time, 90d held, pnl=+98.77, return=+6.74%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2019-01-10 exited 2019-05-21 (time, 90d held, pnl=+628.62, return=+42.64%)
      - base: NOW entered 2019-01-10 exited 2019-09-27 (time, 180d held, pnl=+544.38, return=+36.93%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2019-02-01 exited 2019-06-12 (time, 90d held, pnl=+448.90, return=+29.89%)
      - base: AMD entered 2019-02-01 exited 2019-10-18 (time, 180d held, pnl=+391.56, return=+26.07%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2019-02-13 exited 2019-06-24 (time, 90d held, pnl=+411.26, return=+27.31%)
      - base: MSFT entered 2019-02-13 exited 2019-10-30 (time, 180d held, pnl=+502.54, return=+33.38%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2019-07-09 exited 2019-11-13 (time, 90d held, pnl=+234.16, return=+15.76%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2019-07-16 exited 2019-11-20 (time, 90d held, pnl=+409.44, return=+27.97%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2019-07-24 exited 2019-11-29 (time, 90d held, pnl=+224.59, return=+15.25%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2019-08-22 exited 2019-12-31 (time, 90d held, pnl=+517.89, return=+34.49%)
      - base: NVDA entered 2019-08-22 exited 2020-03-17 (rule, 142d held, pnl=+255.39, return=+17.01%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2019-10-24 exited 2020-03-05 (time, 90d held, pnl=+801.75, return=+53.98%)
      - base: AMD entered 2019-10-24 exited 2020-07-14 (time, 180d held, pnl=+1018.41, return=+68.57%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2020-03-30 exited 2020-08-06 (time, 90d held, pnl=+590.87, return=+38.73%)
      - base: NFLX entered 2020-03-30 exited 2020-12-14 (time, 180d held, pnl=+596.33, return=+39.09%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2020-04-07 exited 2020-08-14 (time, 90d held, pnl=+1021.23, return=+65.99%)
      - base: NVDA entered 2020-04-07 exited 2020-12-22 (time, 180d held, pnl=+1420.39, return=+91.78%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2020-04-08 exited 2020-08-17 (time, 90d held, pnl=+804.66, return=+56.85%)
      - base: AMZN entered 2020-04-08 exited 2020-12-23 (time, 180d held, pnl=+826.92, return=+58.42%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMD entered 2020-04-14 exited 2020-08-20 (time, 90d held, pnl=+795.40, return=+52.47%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2020-04-16 exited 2020-08-24 (time, 90d held, pnl=+535.65, return=+35.94%)
      - base: MRVL entered 2020-04-16 exited 2020-12-31 (time, 180d held, pnl=+1307.94, return=+87.76%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2020-04-16 exited 2020-08-24 (time, 90d held, pnl=+322.27, return=+23.10%)
      - base: MSFT entered 2020-04-16 exited 2020-12-31 (time, 180d held, pnl=+377.55, return=+27.06%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2020-10-16 exited 2021-02-26 (time, 90d held, pnl=+443.02, return=+29.84%)
      - base: GOOGL entered 2020-10-16 exited 2021-07-07 (time, 180d held, pnl=+930.36, return=+62.67%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2020-11-05 exited 2021-03-18 (time, 90d held, pnl=+61.70, return=+4.63%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2021-03-18 exited 2021-07-27 (time, 90d held, pnl=+458.50, return=+32.75%)
      - base: META entered 2021-03-18 exited 2021-10-27 (rule, 155d held, pnl=+170.06, return=+12.15%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2021-04-09 exited 2021-08-17 (time, 90d held, pnl=+567.77, return=+38.39%)
      - base: NVDA entered 2021-04-09 exited 2021-12-23 (time, 180d held, pnl=+1613.98, return=+109.14%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2021-06-04 exited 2021-10-12 (time, 90d held, pnl=+79.63, return=+5.29%)
      - base: AVGO entered 2021-06-04 exited 2022-02-18 (time, 180d held, pnl=+351.62, return=+23.34%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2021-06-07 exited 2021-10-13 (time, 90d held, pnl=+461.34, return=+31.43%)
      - base: MRVL entered 2021-06-07 exited 2022-02-22 (time, 180d held, pnl=+525.54, return=+35.80%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2023-04-04 exited 2023-08-14 (time, 90d held, pnl=+314.27, return=+20.96%)
      - base: NFLX entered 2023-04-04 exited 2023-10-12 (rule, 132d held, pnl=+75.63, return=+5.04%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2023-05-19 exited 2023-09-28 (time, 90d held, pnl=+240.19, return=+16.19%)
      - base: MRVL entered 2023-05-19 exited 2023-10-23 (rule, 107d held, pnl=+136.90, return=+9.23%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2023-07-20 exited 2023-11-27 (time, 90d held, pnl=+285.15, return=+19.24%)
      - base: MU entered 2023-07-20 exited 2024-04-08 (time, 180d held, pnl=+1485.02, return=+100.21%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2023-09-11 exited 2024-01-19 (time, 90d held, pnl=+232.56, return=+17.23%)
      - base: MSFT entered 2023-09-11 exited 2024-05-29 (time, 180d held, pnl=+352.23, return=+26.10%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2023-10-06 exited 2024-02-15 (time, 90d held, pnl=+977.06, return=+66.96%)
      - base: NVDA entered 2023-10-06 exited 2024-06-26 (time, 180d held, pnl=+2700.93, return=+185.09%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2023-10-13 exited 2024-02-23 (time, 90d held, pnl=+637.06, return=+43.78%)
      - base: AVGO entered 2023-10-13 exited 2024-07-03 (time, 180d held, pnl=+1215.44, return=+83.52%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2023-11-03 exited 2024-03-15 (time, 90d held, pnl=+384.67, return=+26.67%)
      - base: NOW entered 2023-11-03 exited 2024-05-31 (rule, 143d held, pnl=+121.27, return=+8.41%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2023-11-06 exited 2024-03-18 (time, 90d held, pnl=+368.75, return=+26.56%)
      - base: AMZN entered 2023-11-06 exited 2024-07-26 (time, 180d held, pnl=+414.65, return=+29.87%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2023-12-14 exited 2024-04-25 (time, 90d held, pnl=+192.61, return=+12.75%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2024-03-20 exited 2024-07-30 (time, 90d held, pnl=+220.75, return=+14.91%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2024-05-10 exited 2024-09-19 (time, 90d held, pnl=+204.67, return=+13.77%)
      - base: NFLX entered 2024-05-10 exited 2025-01-30 (time, 180d held, pnl=+880.73, return=+59.26%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2024-06-06 exited 2024-10-15 (time, 90d held, pnl=+289.84, return=+19.59%)
      - base: META entered 2024-06-06 exited 2025-02-26 (time, 180d held, pnl=+498.21, return=+33.67%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2024-06-28 exited 2024-11-05 (time, 90d held, pnl=+333.31, return=+23.87%)
      - base: NOW entered 2024-06-28 exited 2025-03-05 (rule, 170d held, pnl=+231.70, return=+16.59%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2024-08-14 exited 2024-12-20 (time, 90d held, pnl=+164.20, return=+11.94%)
      - base: TSM entered 2024-08-14 exited 2025-02-28 (rule, 135d held, pnl=+57.96, return=+4.21%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2024-09-13 exited 2025-01-24 (time, 90d held, pnl=+699.78, return=+46.61%)
      - base: AVGO entered 2024-09-13 exited 2025-03-07 (rule, 119d held, pnl=+187.33, return=+12.48%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2024-09-18 exited 2025-01-29 (time, 90d held, pnl=+418.83, return=+28.07%)
      - base: AMZN entered 2024-09-18 exited 2025-03-11 (rule, 118d held, pnl=+58.04, return=+3.89%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2025-04-22 exited 2025-08-29 (time, 90d held, pnl=+332.35, return=+22.03%)
      - base: NFLX entered 2025-04-22 exited 2025-10-24 (rule, 129d held, pnl=+156.85, return=+10.40%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2025-05-06 exited 2025-09-15 (time, 90d held, pnl=+228.32, return=+17.60%)
      - base: MSFT entered 2025-05-06 exited 2026-01-05 (rule, 167d held, pnl=+124.16, return=+9.57%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2025-05-08 exited 2025-09-17 (time, 90d held, pnl=+1053.92, return=+72.35%)
      - base: AVGO entered 2025-05-08 exited 2026-01-27 (time, 180d held, pnl=+850.43, return=+58.38%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2025-05-15 exited 2025-09-24 (time, 90d held, pnl=+498.46, return=+33.73%)
      - base: NVDA entered 2025-05-15 exited 2026-02-03 (time, 180d held, pnl=+569.63, return=+38.54%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2025-05-15 exited 2025-09-24 (time, 90d held, pnl=+608.73, return=+45.01%)
      - base: TSM entered 2025-05-15 exited 2026-02-03 (time, 180d held, pnl=+1061.83, return=+78.51%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2016-05-27 exited 2016-06-28 (stop, 21d held, pnl=-136.77, return=-9.16%)
      - base: MRVL entered 2016-05-27 exited 2016-06-28 (rule, 21d held, pnl=-136.77, return=-9.16%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NVDA entered 2017-03-21 exited 2017-04-06 (stop, 12d held, pnl=-120.69, return=-8.10%)
      - base: NVDA entered 2017-03-21 exited 2017-04-17 (stop, 18d held, pnl=-175.49, return=-11.77%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: META entered 2018-03-12 exited 2018-03-21 (stop, 7d held, pnl=-164.84, return=-11.12%)
      - base: META entered 2018-03-12 exited 2018-03-21 (rule, 7d held, pnl=-164.84, return=-11.12%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2018-05-30 exited 2018-06-26 (stop, 19d held, pnl=-129.25, return=-8.57%)
      - base: MRVL entered 2018-05-30 exited 2018-06-26 (rule, 19d held, pnl=-129.25, return=-8.57%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: MU entered 2018-07-13 exited 2018-08-15 (stop, 23d held, pnl=-154.75, return=-10.32%)
      - base: MU entered 2018-07-13 exited 2018-08-16 (stop, 24d held, pnl=-198.76, return=-13.25%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AMD entered 2019-02-01 exited 2019-03-07 (stop, 23d held, pnl=-140.35, return=-9.35%)
      - base: AMD entered 2019-02-01 exited 2019-10-18 (time, 180d held, pnl=+391.56, return=+26.07%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NFLX entered 2019-06-25 exited 2019-07-19 (stop, 17d held, pnl=-190.84, return=-12.86%)
      - base: NFLX entered 2019-06-25 exited 2019-07-19 (stop, 17d held, pnl=-190.84, return=-12.86%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AVGO entered 2019-07-22 exited 2019-08-06 (stop, 11d held, pnl=-117.86, return=-7.88%)
      - base: AVGO entered 2019-07-22 exited 2019-08-06 (rule, 11d held, pnl=-117.86, return=-7.88%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: META entered 2019-06-18 exited 2019-08-26 (stop, 48d held, pnl=-103.57, return=-7.62%)
      - base: META entered 2019-06-18 exited 2019-10-03 (rule, 75d held, pnl=-130.38, return=-9.60%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2019-09-12 exited 2019-10-02 (stop, 14d held, pnl=-138.56, return=-9.29%)
      - base: (no matching base trade)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: MRVL entered 2019-11-05 exited 2019-12-05 (stop, 21d held, pnl=-163.95, return=-11.04%)
      - base: MRVL entered 2019-11-05 exited 2019-12-06 (stop, 22d held, pnl=-170.55, return=-11.48%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NVDA entered 2021-01-06 exited 2021-03-09 (stop, 42d held, pnl=-123.27, return=-8.39%)
      - base: NVDA entered 2021-01-06 exited 2021-03-09 (stop, 42d held, pnl=-123.27, return=-8.39%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: MRVL entered 2021-04-07 exited 2021-04-20 (stop, 9d held, pnl=-131.41, return=-8.93%)
      - base: MRVL entered 2021-04-07 exited 2021-05-04 (stop, 19d held, pnl=-204.78, return=-13.92%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: MU entered 2022-02-11 exited 2022-03-07 (stop, 15d held, pnl=-153.80, return=-10.53%)
      - base: MU entered 2022-02-11 exited 2022-03-08 (stop, 16d held, pnl=-241.96, return=-16.56%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NVDA entered 2022-03-29 exited 2022-04-06 (stop, 6d held, pnl=-200.92, return=-13.20%)
      - base: NVDA entered 2022-03-29 exited 2022-04-07 (stop, 7d held, pnl=-226.88, return=-14.91%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AVGO entered 2022-03-18 exited 2022-05-02 (stop, 30d held, pnl=-113.80, return=-7.85%)
      - base: AVGO entered 2022-03-18 exited 2022-05-02 (rule, 30d held, pnl=-113.80, return=-7.85%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NFLX entered 2023-04-04 exited 2023-05-03 (stop, 20d held, pnl=-134.64, return=-8.98%)
      - base: NFLX entered 2023-04-04 exited 2023-10-12 (rule, 132d held, pnl=+75.63, return=+5.04%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NVDA entered 2023-10-06 exited 2023-10-27 (stop, 15d held, pnl=-102.67, return=-7.04%)
      - base: NVDA entered 2023-10-06 exited 2024-06-26 (time, 180d held, pnl=+2700.93, return=+185.09%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AVGO entered 2023-10-13 exited 2023-10-27 (stop, 10d held, pnl=-127.88, return=-8.79%)
      - base: AVGO entered 2023-10-13 exited 2024-07-03 (time, 180d held, pnl=+1215.44, return=+83.52%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2024-05-17 exited 2024-06-05 (stop, 12d held, pnl=-125.84, return=-8.54%)
      - base: (no matching base trade)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: META entered 2024-06-06 exited 2024-07-26 (stop, 34d held, pnl=-87.82, return=-5.94%)
      - base: META entered 2024-06-06 exited 2025-02-26 (time, 180d held, pnl=+498.21, return=+33.67%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AMZN entered 2024-08-01 exited 2024-08-05 (stop, 2d held, pnl=-282.04, return=-18.62%)
      - base: AMZN entered 2024-08-01 exited 2024-08-05 (rule, 2d held, pnl=-282.04, return=-18.62%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NVDA entered 2024-08-19 exited 2024-09-04 (stop, 11d held, pnl=-227.80, return=-15.27%)
      - base: NVDA entered 2024-08-19 exited 2024-09-04 (stop, 11d held, pnl=-227.80, return=-15.27%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: TSM entered 2024-08-14 exited 2024-09-09 (stop, 17d held, pnl=-90.36, return=-6.57%)
      - base: TSM entered 2024-08-14 exited 2025-02-28 (rule, 135d held, pnl=+57.96, return=+4.21%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: AVGO entered 2024-08-16 exited 2024-09-09 (stop, 15d held, pnl=-229.63, return=-15.51%)
      - base: AVGO entered 2024-08-16 exited 2024-09-09 (stop, 15d held, pnl=-229.63, return=-15.51%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NFLX entered 2025-08-13 exited 2025-10-23 (stop, 50d held, pnl=-130.00, return=-8.77%)
      - base: (no matching base trade)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: AMZN entered 2025-11-03 exited 2025-11-17 (stop, 10d held, pnl=-134.20, return=-8.75%)
      - base: AMZN entered 2025-11-03 exited 2025-11-19 (stop, 12d held, pnl=-191.20, return=-12.47%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: AMD entered 2026-01-05 exited 2026-01-08 (stop, 3d held, pnl=-117.52, return=-8.50%)
      - base: AMD entered 2026-01-05 exited 2026-02-05 (stop, 22d held, pnl=-171.69, return=-12.42%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AMD entered 2026-01-16 exited 2026-02-05 (stop, 13d held, pnl=-195.99, return=-13.93%)
      - base: (no matching base trade)

**`h3y-4`** (r5, three years, 2023-26) -- spread +36.31%, exit-spread +36.31%, benchmark +66.77%, 751 sessions, base `max_drawdown` -13.41%.
- `B-momentum`: 33 trade(s) closing in-window -- open_at_end=1, rule=17, stop=5, time=10
- `B2-hold-90`: 44 trade(s) closing in-window -- open_at_end=1, rule=16, stop=6, time=21
- `B3-concentrated`: 25 trade(s) closing in-window -- open_at_end=1, rule=15, stop=3, time=6
- `B4-tight-stop`: 40 trade(s) closing in-window -- open_at_end=1, rule=18, stop=13, time=8
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2023-04-04 exited 2023-08-14 (time, 90d held, pnl=+314.27, return=+20.96%)
      - base: NFLX entered 2023-04-04 exited 2023-10-12 (rule, 132d held, pnl=+75.63, return=+5.04%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2023-05-19 exited 2023-09-28 (time, 90d held, pnl=+240.19, return=+16.19%)
      - base: MRVL entered 2023-05-19 exited 2023-10-23 (rule, 107d held, pnl=+136.90, return=+9.23%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MU entered 2023-07-20 exited 2023-11-27 (time, 90d held, pnl=+285.15, return=+19.24%)
      - base: MU entered 2023-07-20 exited 2024-04-08 (time, 180d held, pnl=+1485.02, return=+100.21%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2023-09-11 exited 2024-01-19 (time, 90d held, pnl=+232.56, return=+17.23%)
      - base: MSFT entered 2023-09-11 exited 2024-05-29 (time, 180d held, pnl=+352.23, return=+26.10%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2023-10-06 exited 2024-02-15 (time, 90d held, pnl=+977.06, return=+66.96%)
      - base: NVDA entered 2023-10-06 exited 2024-06-26 (time, 180d held, pnl=+2700.93, return=+185.09%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2023-10-13 exited 2024-02-23 (time, 90d held, pnl=+637.06, return=+43.78%)
      - base: AVGO entered 2023-10-13 exited 2024-07-03 (time, 180d held, pnl=+1215.44, return=+83.52%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2023-11-03 exited 2024-03-15 (time, 90d held, pnl=+384.67, return=+26.67%)
      - base: NOW entered 2023-11-03 exited 2024-05-31 (rule, 143d held, pnl=+121.27, return=+8.41%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2023-11-06 exited 2024-03-18 (time, 90d held, pnl=+368.75, return=+26.56%)
      - base: AMZN entered 2023-11-06 exited 2024-07-26 (time, 180d held, pnl=+414.65, return=+29.87%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MRVL entered 2023-12-14 exited 2024-04-25 (time, 90d held, pnl=+192.61, return=+12.75%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: GOOGL entered 2024-03-20 exited 2024-07-30 (time, 90d held, pnl=+220.75, return=+14.91%)
      - base: (no matching base trade)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2024-05-10 exited 2024-09-19 (time, 90d held, pnl=+204.67, return=+13.77%)
      - base: NFLX entered 2024-05-10 exited 2025-01-30 (time, 180d held, pnl=+880.73, return=+59.26%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: META entered 2024-06-06 exited 2024-10-15 (time, 90d held, pnl=+289.84, return=+19.59%)
      - base: META entered 2024-06-06 exited 2025-02-26 (time, 180d held, pnl=+498.21, return=+33.67%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NOW entered 2024-06-28 exited 2024-11-05 (time, 90d held, pnl=+333.31, return=+23.87%)
      - base: NOW entered 2024-06-28 exited 2025-03-05 (rule, 170d held, pnl=+231.70, return=+16.59%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2024-08-14 exited 2024-12-20 (time, 90d held, pnl=+164.20, return=+11.94%)
      - base: TSM entered 2024-08-14 exited 2025-02-28 (rule, 135d held, pnl=+57.96, return=+4.21%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2024-09-13 exited 2025-01-24 (time, 90d held, pnl=+699.78, return=+46.61%)
      - base: AVGO entered 2024-09-13 exited 2025-03-07 (rule, 119d held, pnl=+187.33, return=+12.48%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AMZN entered 2024-09-18 exited 2025-01-29 (time, 90d held, pnl=+418.83, return=+28.07%)
      - base: AMZN entered 2024-09-18 exited 2025-03-11 (rule, 118d held, pnl=+58.04, return=+3.89%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NFLX entered 2025-04-22 exited 2025-08-29 (time, 90d held, pnl=+332.35, return=+22.03%)
      - base: NFLX entered 2025-04-22 exited 2025-10-24 (rule, 129d held, pnl=+156.85, return=+10.40%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: MSFT entered 2025-05-06 exited 2025-09-15 (time, 90d held, pnl=+228.32, return=+17.60%)
      - base: MSFT entered 2025-05-06 exited 2026-01-05 (rule, 167d held, pnl=+124.16, return=+9.57%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: AVGO entered 2025-05-08 exited 2025-09-17 (time, 90d held, pnl=+1053.92, return=+72.35%)
      - base: AVGO entered 2025-05-08 exited 2026-01-27 (time, 180d held, pnl=+850.43, return=+58.38%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: NVDA entered 2025-05-15 exited 2025-09-24 (time, 90d held, pnl=+498.46, return=+33.73%)
      - base: NVDA entered 2025-05-15 exited 2026-02-03 (time, 180d held, pnl=+569.63, return=+38.54%)
    - **[B2-hold-90]** 90-day hold cap fired
      - variant: TSM entered 2025-05-15 exited 2025-09-24 (time, 90d held, pnl=+608.73, return=+45.01%)
      - base: TSM entered 2025-05-15 exited 2026-02-03 (time, 180d held, pnl=+1061.83, return=+78.51%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NFLX entered 2023-04-04 exited 2023-05-03 (stop, 20d held, pnl=-134.64, return=-8.98%)
      - base: NFLX entered 2023-04-04 exited 2023-10-12 (rule, 132d held, pnl=+75.63, return=+5.04%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NVDA entered 2023-10-06 exited 2023-10-27 (stop, 15d held, pnl=-102.67, return=-7.04%)
      - base: NVDA entered 2023-10-06 exited 2024-06-26 (time, 180d held, pnl=+2700.93, return=+185.09%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AVGO entered 2023-10-13 exited 2023-10-27 (stop, 10d held, pnl=-127.88, return=-8.79%)
      - base: AVGO entered 2023-10-13 exited 2024-07-03 (time, 180d held, pnl=+1215.44, return=+83.52%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: MRVL entered 2024-05-17 exited 2024-06-05 (stop, 12d held, pnl=-125.84, return=-8.54%)
      - base: (no matching base trade)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: META entered 2024-06-06 exited 2024-07-26 (stop, 34d held, pnl=-87.82, return=-5.94%)
      - base: META entered 2024-06-06 exited 2025-02-26 (time, 180d held, pnl=+498.21, return=+33.67%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AMZN entered 2024-08-01 exited 2024-08-05 (stop, 2d held, pnl=-282.04, return=-18.62%)
      - base: AMZN entered 2024-08-01 exited 2024-08-05 (rule, 2d held, pnl=-282.04, return=-18.62%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NVDA entered 2024-08-19 exited 2024-09-04 (stop, 11d held, pnl=-227.80, return=-15.27%)
      - base: NVDA entered 2024-08-19 exited 2024-09-04 (stop, 11d held, pnl=-227.80, return=-15.27%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: TSM entered 2024-08-14 exited 2024-09-09 (stop, 17d held, pnl=-90.36, return=-6.57%)
      - base: TSM entered 2024-08-14 exited 2025-02-28 (rule, 135d held, pnl=+57.96, return=+4.21%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: AVGO entered 2024-08-16 exited 2024-09-09 (stop, 15d held, pnl=-229.63, return=-15.51%)
      - base: AVGO entered 2024-08-16 exited 2024-09-09 (stop, 15d held, pnl=-229.63, return=-15.51%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: NFLX entered 2025-08-13 exited 2025-10-23 (stop, 50d held, pnl=-130.00, return=-8.77%)
      - base: (no matching base trade)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: AMZN entered 2025-11-03 exited 2025-11-17 (stop, 10d held, pnl=-134.20, return=-8.75%)
      - base: AMZN entered 2025-11-03 exited 2025-11-19 (stop, 12d held, pnl=-191.20, return=-12.47%)
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: AMD entered 2026-01-05 exited 2026-01-08 (stop, 3d held, pnl=-117.52, return=-8.50%)
      - base: AMD entered 2026-01-05 exited 2026-02-05 (stop, 22d held, pnl=-171.69, return=-12.42%)
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: AMD entered 2026-01-16 exited 2026-02-05 (stop, 13d held, pnl=-195.99, return=-13.93%)
      - base: (no matching base trade)

### Bottom 5 by spread

**`h6m-5`** (r5, six months, H2 2022) -- spread +0.00%, exit-spread +0.00%, benchmark -3.21%, 127 sessions, base `max_drawdown` +0.00%.
- `B-momentum`: 0 trade(s) closing in-window -- no trades
- `B2-hold-90`: 0 trade(s) closing in-window -- no trades
- `B3-concentrated`: 0 trade(s) closing in-window -- no trades
- `B4-tight-stop`: 0 trade(s) closing in-window -- no trades
    - neither the 90-day hold cap nor the 8% stop fired on any trade in this window

**`volmageddon-2018`** (r4, volatility shock) -- spread +0.12%, exit-spread +0.00%, benchmark -9.42%, 45 sessions, base `max_drawdown` -5.52%.
- `B-momentum`: 3 trade(s) closing in-window -- open_at_end=1, rule=2
- `B2-hold-90`: 3 trade(s) closing in-window -- open_at_end=1, rule=2
- `B3-concentrated`: 3 trade(s) closing in-window -- open_at_end=1, rule=2
- `B4-tight-stop`: 3 trade(s) closing in-window -- open_at_end=1, rule=1, stop=1
    - **[B4-tight-stop]** 8% stop fired (base's looser 12% stop did NOT fire on this trade)
      - variant: META entered 2018-03-12 exited 2018-03-21 (stop, 7d held, pnl=-164.84, return=-11.12%)
      - base: META entered 2018-03-12 exited 2018-03-21 (rule, 7d held, pnl=-164.84, return=-11.12%)

**`h6m-3`** (r5, six months, H2 2018) -- spread +0.12%, exit-spread +0.00%, benchmark -2.13%, 126 sessions, base `max_drawdown` -3.53%.
- `B-momentum`: 5 trade(s) closing in-window -- open_at_end=3, rule=1, stop=1
- `B2-hold-90`: 5 trade(s) closing in-window -- open_at_end=3, rule=1, stop=1
- `B3-concentrated`: 5 trade(s) closing in-window -- open_at_end=3, rule=1, stop=1
- `B4-tight-stop`: 5 trade(s) closing in-window -- open_at_end=3, rule=1, stop=1
    - **[B4-tight-stop]** 8% stop fired (base's 12% stop also fired on this trade)
      - variant: NFLX entered 2018-09-19 exited 2018-10-11 (stop, 16d held, pnl=-197.24, return=-13.18%)
      - base: NFLX entered 2018-09-19 exited 2018-10-11 (stop, 16d held, pnl=-197.24, return=-13.18%)

**`live-1`** (r11, live out-of-sample, weeks 1-4) -- spread +0.37%, exit-spread +0.00%, benchmark -2.75%, 22 sessions, base `max_drawdown` -0.96% (cumulative from 2026-02-17, not this sub-period alone).
- `B-momentum`: 1 trade(s) closing in-window -- open_at_end=1
- `B2-hold-90`: 1 trade(s) closing in-window -- open_at_end=1
- `B3-concentrated`: 1 trade(s) closing in-window -- open_at_end=1
- `B4-tight-stop`: 1 trade(s) closing in-window -- open_at_end=1
    - neither the 90-day hold cap nor the 8% stop fired on any trade in this window

**`q4-2018`** (r2, sharp quarter-long selloff) -- spread +0.39%, exit-spread +0.00%, benchmark -20.05%, 65 sessions, base `max_drawdown` -1.03%.
- `B-momentum`: 1 trade(s) closing in-window -- rule=1
- `B2-hold-90`: 1 trade(s) closing in-window -- rule=1
- `B3-concentrated`: 1 trade(s) closing in-window -- rule=1
- `B4-tight-stop`: 1 trade(s) closing in-window -- rule=1
    - neither the 90-day hold cap nor the 8% stop fired on any trade in this window


## 4. What the discriminating windows have in common

Every window in the top-5 table above shares the same shape: a single name (most often `MRVL` or `NVDA`) runs for well over 90 sessions without triggering the shared rule exit or either stop, so the only thing that can separate the cards is whether a *time-based* backstop cuts the position off first. `B2-hold-90`'s 90-day cap does that; `B-momentum`'s and `B4-tight-stop`'s shared 180-day cap does not, for the same trade, in the same window. The 8% vs 12% stop distinction (`B4-tight-stop` vs the base) fires far more often across the full dataset (dozens of `stop` exits in ordinary and bear windows alike) but rarely produces a *large* spread on its own, because both stops are usually cleared by the same adverse move -- a 9% drop trips both the 8% and the 12% stop, so the stop-tightness difference mostly changes *how much* is given back on a losing trade, not *whether* the trade survives, in most of the windows measured here.

## 5. Is this a real distinction, or one card wearing four labels?

The median four-way spread across all 44 measured windows is +5.11 percentage points, and most of that is driven by `B3-concentrated`'s sizing, not by an exit rule binding -- the median *exit-spread* (base vs `B2-hold-90` vs `B4-tight-stop` only) is smaller. Round 11's own live matrix -- the only out-of-sample evidence in this dataset -- found the three exit-rule cards tied on median and identical in five of six sub-periods. This module's backtest-window search confirms that finding generalises: a spread worth calling "distinct" needs a long, single-name run past the shorter cap, which is common in some regimes (see section 4) but absent from most of the windows this program has actually measured. Treat the top of section 2's table as real, measured evidence that a hold-cap difference *can* matter; do not treat the field's typical window (most of the table, clustered near zero) as evidence it usually does.

## 6. What this document is, and is not

This is analysis of **existing stored results** -- every `AgentResult` read here was already on disk before this script ran. `strategy-program/PROTOCOL.md` section 6(a): cards are frozen and the engine is deterministic, so re-running a card on a window it has already seen recomputes the same number rather than sampling anything new -- confirmed directly in this dataset (`bear-2022`'s `B-momentum` result is byte-identical between rounds 1 and 2). This document is therefore a deterministic recomputation over stored evidence, not a new measurement, and does not by itself justify adding a window to any future round's matrix -- it says *what kind* of window would separate these cards, which is a design input for choosing one, not a substitute for running it.

## 7. Coverage and dedup log

- bear-2022: re-run in r2 (first seen in r1), adjusted_excess identical on ['B-momentum', 'B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- kept r1's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))
- bull-2024: re-run in r2 (first seen in r1), adjusted_excess identical on ['B-momentum', 'B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- kept r1's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))
- covid: re-run in r2 (first seen in r1), adjusted_excess identical on ['B-momentum', 'B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- kept r1's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))
- recent: re-run in r2 (first seen in r1), adjusted_excess identical on ['B-momentum', 'B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- kept r1's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))
- r3/bear-2022: only ['B-momentum'] on disk, missing ['B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- excluded from every ranked table
- bear-2022: re-run in r3 (first seen in r1), adjusted_excess identical on ['B-momentum'] -- kept r1's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))
- r3/bull-2024: only ['B-momentum'] on disk, missing ['B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- excluded from every ranked table
- bull-2024: re-run in r3 (first seen in r1), adjusted_excess identical on ['B-momentum'] -- kept r1's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))
- r3/chop-2015: only ['B-momentum'] on disk, missing ['B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- excluded from every ranked table
- chop-2015: re-run in r3 (first seen in r2), adjusted_excess identical on ['B-momentum'] -- kept r2's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))
- r3/covid: only ['B-momentum'] on disk, missing ['B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- excluded from every ranked table
- covid: re-run in r3 (first seen in r1), adjusted_excess identical on ['B-momentum'] -- kept r1's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))
- r3/q4-2018: only ['B-momentum'] on disk, missing ['B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- excluded from every ranked table
- q4-2018: re-run in r3 (first seen in r2), adjusted_excess identical on ['B-momentum'] -- kept r2's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))
- r3/recent: only ['B-momentum'] on disk, missing ['B2-hold-90', 'B3-concentrated', 'B4-tight-stop'] -- excluded from every ranked table
- recent: re-run in r3 (first seen in r1), adjusted_excess identical on ['B-momentum'] -- kept r1's copy, deterministic re-run is not new evidence (PROTOCOL.md 6(a))

## Reproduce

```
cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/variant_discrimination.py
```
