# Round 29 — the fair test: cross-sectional information on a diversified universe

Pre-registered 2026-08-30, before any measurement in this round exists. **Not investment advice.**

Round 28's null was on two *concentrated* universes (pairwise correlation 0.46–0.83), which its §2
flagged as close to the worst case for cross-sectional selection. This is the fair test it named: the
same measurement on a genuinely low-correlation universe.

---

## 1. Why this is the decisive version

Round 28 found no cross-sectional rank information on the seated tech/semiconductor universes and
concluded the blocked engine change is not justified *for the book that exists*. It fixed one caveat in
advance: a concentrated universe has little dispersion to rank, so that null is about the concentrated
book, not selection in general.

**This round removes that caveat.** If a diversified, low-correlation universe *also* shows no
cross-sectional edge, the cross-symbol line closes for good — the engine change §3a describes is not
worth building for any universe this programme can reach. If it shows an edge, the change is justified,
and this round names the signal and horizon.

**It is genuinely new ground, verified against what exists.** The Discovery module tested cross-sectional
ranking only on **ETF** baskets (`SECTOR_ETF_ROSTER` = the 11 sector SPDRs; IC −0.0073, q=0.186). Round
28 tested only **concentrated single-name** universes. **No prior study tested diversified single
names**, which is what this round does.

## 2. The universe — one liquid name per sector

Ten single names, each the longest-history large-cap in its GICS sector, balanced panel from the common
start:

| sector | name | first bar |
|---|---|---|
| Technology | `MSFT` | 1986-03-12 |
| Financials | `JPM` | 1980-03-16 |
| Energy | `XOM` | 1970-01-01 |
| Health Care | `JNJ` | 1970-01-01 |
| Consumer Staples | `PG` | 1970-01-01 |
| Industrials | `CAT` | 1970-01-01 |
| Consumer Discretionary | `MCD` | 1970-01-01 |
| Utilities | `NEE` | 1973-02-20 |
| Communication Services | `DIS` | 1970-01-01 |
| Materials | `LIN` | 1992-06-16 |

**Balanced panel from 1992-06-16** (LIN's first bar), ~34 years. Measured pairwise daily-return
correlation since 2010 is **mean 0.393, max 0.580** — roughly half the seated universes' 0.6–0.8, and
the point of the round: real cross-sectional dispersion to rank.

## 3. The measurement — identical to round 28, with Amendment 1's fix built in

Same five signals (`mom_12_1`, `mom_6`, `vol_60`, `reversal_1m`, `dist_sma200`), same de-meaned forward
return (§3c of round 28), same Spearman rank IC, same block bootstrap and Benjamini-Hochberg.

**One change, adopted from round 28's Amendment 1 and fixed here before any run:** each horizon
rebalances at its own interval so forward windows never overlap — `h=21` every 21 sessions, `h=63`
every 63 — because overlapping windows inflate significance (round 28 §2, which manufactured that
round's one false survivor). No overlapping-window cell will be computed in this round at all.

Horizons `h ∈ {21, 63}`. **Ten cells** (5 signals × 2 horizons × 1 universe); BH over the ten.

## 4. Falsifiable predictions

1. **Mean `|IC|` is higher here than round 28's** (0.042–0.052). A less-correlated universe has more
   genuine relative structure, so ranks should carry more — almost mechanical, stated so the round is
   anchored.
2. **`vol_60` is the strongest signal** (largest mean `|IC|`). The low-volatility anomaly is the most
   robust cross-sectional effect in the literature and the one most likely to appear across sectors.
3. **`reversal_1m`'s IC is negative at `h=21`** — and, unlike round 28 where reversal was absent on the
   tight cluster, it *does* appear here. Cross-sector short-term reversal is a documented effect; a
   diversified universe is where it should show if anywhere.
4. **Zero cells survive Benjamini-Hochberg at q < 0.10.** The honest prior after twenty-eight nulls —
   but this is stated with less confidence than round 28's version. This is the fair test, and it is the
   round where a survivor is most plausible. A survivor here is a real finding, not an artifact to
   explain away, because the overlap defect is fixed in advance.

## 5. The decision rule, fixed here

- **If zero cells survive:** the cross-symbol line closes. Cross-sectional selection carries no
  measurable information even on a diversified universe, so the engine change §3a describes is not worth
  building for any reachable universe, and recommendation 11's non-price inputs are the remaining
  frontier. Stated as the round's recommendation.
- **If any cell survives:** cross-sectional information exists on diversified names. The engine change
  is justified for that signal/horizon, and the next round pre-registers building it — with the caveat
  that a diversified universe is not one the seated cards currently trade, so a positive result opens a
  new book rather than improving the existing one.

A surviving cell is a licence to build, not a strategy (round 28 §5).

## 6. What this round cannot settle

- **Breadth, not just correlation.** Ten names is a narrow cross-section; a Spearman IC on ten points
  is noisy per date, and the literature's cross-sectional effects are measured on hundreds of names.
  This round improves the *correlation* profile over round 28 but not the *breadth*. A null here is
  therefore "no edge on a diversified but narrow universe", and a genuinely broad universe (hundreds of
  names) remains a distinct, unrun question — limited by what the store holds with long history.
- **One name per sector**, chosen by history length, not by any return. A different representative is a
  different draw.
- **Rank IC, not return**; **nothing promotable**; **nothing here is a card.**
