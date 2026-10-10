# Round 14 — naming the chooser

**Not investment advice.** Simulated books on a paper account. I am not a licensed financial adviser
and none of this is a recommendation about real capital.

**Run 2026-08-23** against `strategy-program/ROUND-14-PLAN.md`, committed as `8767fa1` *before any
round-14 run existed*. Reproducible:

```
cd "<repo root>" && PYTHONPATH="backend;." .venv/Scripts/python.exe strategy-program/tools/round14.py --json data/rounds/r14-2026-08/scorecard.json
```

`run.txt` is that command's output verbatim; `scorecard.json` its machine-readable form;
`contention.txt` the census from `strategy-program/tools/r14_contention.py`.

**This round selects nothing.** It seats no card, changes no gate and touches no earlier results
tree. It measures one property of the engine. The desk roster is unchanged.

---

## 1. The control passed, so the rest may be read

Pre-registered: *"If the control diverges, the experiment is broken and no other number in this round
may be read."*

```
== CONTROL -- c21-uncorrelated, 6 names in 6 slots, no slot can be contested ==
  base   -0.59
  ranked -0.59
  divergence +0.00  ->  PASS
```

The check is `==` on `Decimal`, not a rounded display: the divergence is exactly zero, over all eight
windows.

**It nearly read as a failure, and the reason is worth recording.** The first contention census
compared trade logs *in order* and reported the control's tape moving in 2 of 8 windows — which, taken
at face value, would have falsified the round on its own pre-registered terms. It was order only:

| window | trade sets | ending equity, base vs ranked |
|---|---|---|
| `chop-2015` | identical (6 = 6) | 10602.52 = 10602.52 |
| `recent` | identical (19 = 19) | 11265.18 = 11265.18 |

`rank_by` sorts the rows of the trade log even where it cannot change which rows exist. That is
economically nothing, but a census counting row order as contention overstates it everywhere.
`r14_contention.py` compares sorted sets and cross-checks ending equity for exactly this reason, and
its docstring records why. Under that comparison the control is contested in **0 of 8** windows.

## 2. What the round was asking

Not "does a ranking key add alpha". `app.tournament.runner._ordered_entry_candidates` decides which
qualifying name takes a scarce slot, and left unranked that decision *is* the order symbols were typed
into a JSON array — worth a measured **53.9-point spread over twelve orderings of one identical card**
(`PROTOCOL.md` §7). Every number this programme has produced carries that arbitrariness inside it.
The question is how large it actually is.

## 3. The spread — a second, independent estimate

Median adjusted excess, in points. Each base and its three variants ran **the same windows** (§5), so
each row compares like with like.

| base card | unranked | rel. strength | low vol | stretch | **spread** | best |
|---|---|---|---|---|---|---|
| `B3-concentrated` | +13.89 | +14.52 | +13.89 | +13.89 | **0.62** | rel. strength |
| `c19-volatility` | −2.64 | −2.06 | −2.21 | −2.40 | **0.58** | rel. strength |
| `B-momentum` | +12.16 | +11.30 | +10.86 | +11.86 | **1.29** | unranked |
| `A-rotation` | −7.16 | **+0.72** | −8.16 | −5.88 | **8.88** | rel. strength |
| `C-trend` | +5.03 | +4.36 | +5.03 | +5.03 | **0.67** | unranked |

### All four pre-committed expectations held

1. **Control diverges by exactly 0.00** — held, `+0.00`.
2. **Spread under 53.9 points on most cards** — held, **5 of 5**; max 8.88, median 0.67.
3. **No single key wins on every base** — held; relative strength 3, unranked 2.
4. **At least one base spreads under 5 points** — held, **4 of 5**.

Four for four is a weaker result than it looks, and should be read that way: expectations 2 and 4 were
one-sided and generously bounded. The informative part is *how far* under 53.9 the answer landed.

## 4. What the numbers actually say

**The 53.9-point figure does not generalise.** On four of five cards the entire choice of chooser —
including making no choice at all — is worth **under 1.3 points** of median adjusted excess.
`PROTOCOL.md` §7 sampled twelve orderings *selected to be maximally different*; three considered keys
and the as-typed order land far closer together. The arbitrariness is real but, on this field, small.

**Headroom does not predict contention.** This is the finding worth keeping:

| card | universe | slots | headroom | windows contested |
|---|---|---|---|---|
| `A-rotation` | 9 | 3 | 6 | **7 of 7** |
| `c19-volatility` | 12 | 4 | 8 | 7 of 8 |
| `B3-concentrated` | 12 | 4 | **8** | 2 of 6 |
| `B-momentum` | 12 | 6 | 6 | 2 of 6 |
| `C-trend` | 9 | 5 | 4 | 1 of 6 |
| `c21-uncorrelated` | 6 | 6 | 0 | 0 of 8 |

The two cards with the *most* headroom on paper sit at opposite ends: `c19-volatility` is contested in
7 of 8 windows, `B3-concentrated` in 2 of 6 — same universe size, same slot count. Headroom is a
precondition; whether enough names *qualify at once* is a property of the entry rule and the regime,
and it is not visible from the card. Round 14's field was chosen on headroom, which was the best
available proxy and a measurably poor one.

**`A-rotation` is the one card where the chooser decides the answer.** 8.88 points of spread, contested
in every window it ran, and the only card where a key flips the *sign*: −7.16 unranked to **+0.72**
under relative strength. It has the fewest slots in the field (3), so a slot is scarcer there than
anywhere else — the mechanism is at least consistent with the effect.

That figure deserves a caution rather than a conclusion. `A-rotation` is a seated desk card, seated in
round 10 over an owner override argued from its live record. Round 14 says that had it been run with a
different, equally defensible slot rule, its backtest record would have read nine points differently.
It does **not** say the seated card is mis-scored: the card that is seated is the unranked one, which
is the one that was actually run.

**No key is a discoverable rule.** Relative strength wins 3 bases, the as-typed order wins 2, and
low-volatility wins none — but on three of the five bases the winner leads by under a point, which is
noise against an 8-window median. `rank_by` reads here as a per-card parameter, not a setting with a
right value.

## 5. Reconciliation: 164 runs, not the 176 expected

The plan said *"a shortfall is a lost card, not a rounding detail."* It was neither, and the
distinction is checkable rather than argued:

| window | ran | failed | cause |
|---|---|---|---|
| `chop-2011` | 10 | 12 | `META` — first stored bar 2012-05-17, window opens 2011-05-26 |
| `gfc` | 6 | 16 | `AVGO` — first stored bar 2009-08-05, window closes 2009-03-09 |

Every failure is a `GuardFailed` from the lookahead guard, refusing to certify causality against a
symbol with no post-warmup region. **No `IOException` appears in either log**, so no card was lost to
store contention (`DEFECTS.md` D3). These are honest refusals on a universe that did not exist yet.

Read the guard's wording precisely, because the two cases are not the same and the store was checked
rather than assumed. `AVGO` has **0 bars** anywhere in `gfc`. `META` has **14 bars** inside
`chop-2011` — the guard's "only 0 bars" is the count *after* a 19-bar warmup, so the symbol is
present but entirely consumed by warmup. The distinction matters if anyone later tries to fix this by
widening the window: a few weeks earlier recovers nothing for `AVGO`, and would need ~5 more weeks of
pre-window history to give `META` a post-warmup region.

The shortfall does not bias the spread, because it falls on **whole families**: a base and its three
variants share a universe, so they fail together. `r14_coverage.py` verifies this rather than assuming
it — all six families are `UNIFORM`, and the control ran all eight windows. Within-row comparisons in
§3 are therefore like-with-like; *between-row* comparisons are not, since `A-rotation` is a 7-window
median and `B3-concentrated` a 6-window one against `c19-volatility`'s 8.

## 6. What this round does not settle

- **It measures eight regime windows, not the future.** Round 4's finding stands: rankings are
  conditional on the window mix, and this round's own §5 shows two of the eight windows dropping three
  families between them.
- **It does not license re-running rounds 1–5.** Gate A reads round 5; Gate S′ reads rounds 2, 4 and 5;
  rounds 6–12 scored over those frozen matrices and two ended in owner overrides argued from specific
  figures in them. `PROTOCOL.md` §6(a) forbids treating a re-run as new evidence. If a key proves out,
  the honest use is on *new* cards from here.
- **It cannot say relative strength is right** — only that it beat two alternatives and an as-typed
  order on this matrix, usually by under a point. A key chosen after seeing this table would be fitted
  to it.
- **Five bases is a small field**, and it was selected on headroom — which §4 just showed does not
  predict the thing that matters. A field selected on measured contention would be the better
  experiment, and that ordering was not available before running.
