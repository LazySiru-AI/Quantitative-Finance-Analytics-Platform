# The evolution loop — pre-registration

Not investment advice. Every number this document anticipates is a backtest result on price-only
bars with no dividends, and the whole point of the machinery described below is that most of what it
proposes will be wrong.

Pre-registered 2026-08-24, before any generation has been run.

This document is to the evolution loop what `ROUND-N-PLAN.md` is to a hand-designed round. It exists
because `PROTOCOL.md` §2 makes pre-registration the integrity boundary of this whole programme — a
card edited after any result exists is not a strategy, it is a memory of one — and an autonomous
searcher that designs its own next round cannot write a plan file per round the way an analyst does.
So the search space, the gate, and the failure conditions are declared here, once, in advance, and
the loop is only permitted to move *within* what this document already describes. A generation that
would need a wider space than §3 declares is a change to this file, reviewed and committed before the
loop runs again — not something the loop may reach for on its own.

---

## 1. What this is

`app.tournament.jobs` runs one round of pre-authored cards. `app.evolution` is the layer above it: a
supervisor thread that proposes a generation of candidates, runs them through that same round
machinery, reads the leaderboard, and uses what it learned to propose the next generation —
indefinitely, until a human presses stop.

The user-facing surface is one button on the Competition page, beside "Plan the next round". Pressing
it starts the loop; pressing it again stops it.

One generation:

| # | phase | what happens |
|---|---|---|
| 0 | `proposing` | pick this generation's **lane**, mint a round id, optionally fetch a news bias, breed a population from that lane's elites |
| 1 | — | write `gen{N}/PLAN.md` **before any run exists** — the per-generation half of this pre-registration |
| 2 | `running` | run the selection windows into `<round_id>`, then the holdout windows into `<round_id>-holdout`, serially, holding the engine's single slot |
| 3 | `scoring` | `build_leaderboard` on each → standings → findings → ledger |
| 4 | `promoting` | apply the gate; a card that clears it twice on differing window sets is copied into `candidates/` and seated on the paper desk |
| 5 | `cooldown` | pause, then repeat |

Two details in that table were wrong in the first draft and are worth stating as facts about the
machinery rather than as choices, because in both cases the obvious implementation fails silently.

**A generation is one lane: one purpose, one card shape.** `build_leaderboard` refuses to rank a field
that mixes the `entry-notional` exposure basis (rules cards) with `invested-value` (allocation cards)
— they are not one field, and it ranks the larger group and lists the rest in `unscored_reason`
rather than print two orderings in one column. A generation holding both shapes therefore has half its
field run at full cost and then discarded: measured, 4 candidates proposed, 12 runs, 0 failures, **2
ranked**. Generations cycle through the lanes instead, each lane keeping its own elite lineage, so
both shapes get searched and every candidate gets a rank.

**The holdout needs its own round directory.** `build_leaderboard` takes no window filter — it ranks
every window with run files under the round it is given. Running both window sets into one directory
therefore puts the holdout *inside* the selection median it is supposed to check, which is the one
failure that makes the entire mechanism decorative. Two directories keep each board to its own
windows, and keep both numbers coming from the same code path rather than one of them being
recomputed by hand.

Nothing in phases 2–4 involves a language model. `AGENTS-INTEGRATION-PLAN.md` Phase F is explicit
that a model must never enter the scoring path, because the programme's entire value is
reproducibility and a model in that path destroys it. Proposal is generative; scoring is arithmetic
over run files the existing engine wrote.

---

## 2. The problem this design is mostly about

An endless search over a parameter space will eventually produce a card that looks excellent and is
not. This is not a risk to be mitigated; it is the *expected* behaviour of the mechanism, and it
arrives on a schedule set by how fast the loop can propose. A human analyst tests perhaps five cards
a round. This loop tests six per generation and never gets tired.

`PROTOCOL.md` §3's anti-overfitting constitution was written for the human cadence. Three of its
provisions do not survive automation unmodified, and the loop replaces each with something stronger:

**One submission per analyst per round → a whole-loop correction denominator.** The multiple-
comparison denominator for an endless search is every candidate the loop has ever run, not the six in
the current generation. `app.evolution.ledger` is an append-only JSONL record of every genome ever
tested, and the Benjamini-Hochberg q-value attached to a standing is computed across that entire
history. A consequence worth stating plainly: **a candidate's q-value gets worse as the loop keeps
running, without that candidate being re-run**. That is correct. It is what "we looked at a thousand
things" means, and a searcher that reports a fresh q-value per generation has corrected for nothing.

**Information quarantine → a holdout window set.** An analyst is quarantined from prior rounds'
results. A breeding population cannot be — inheritance is the whole mechanism. So instead,
`LoopConfig.holdout_windows` reserves regimes that selection never sees: candidates are run over
them, the number is reported beside the selection number, and it feeds nothing but the gate. The
default holdout is `covid` and `q4-2018`, the two sharpest drawdowns in the main matrix, because the
failure mode a searcher most reliably manufactures is a card that is excellent right up until the
market falls.

**Promotion on two consecutive rounds → the same rule, with the window sets checked.**
`PROTOCOL.md` §6 already requires two consecutive qualifying rounds on window sets that differ, for a
reason this programme measured directly: re-running a frozen card on an already-seen window
recomputes the same number (`A-rotation` returned an identical +95.2786% twice), so two identical
window sets are one measurement counted twice. The loop enforces the set-difference check
mechanically rather than trusting an orchestrator to notice.

A fourth constraint carries over unchanged: **the ten-free-parameter budget**, enforced by
`Genome.traits`' own validator rather than by a reader, because a generative proposer has no
incentive to respect it — more knobs is strictly more search.

---

## 3. The declared search space

The loop may propose only what is described here. Two card shapes:

**`rules`** — an `app.tournament.models.StrategyCard`. Free parameters: `rule_shape`, `fast`, `slow`,
`regime_ma`, `stop_loss_pct`, `take_profit_pct`, `max_hold_days`, `max_positions`, `position_pct`,
`rank_key` — ten, which is the budget exactly. No eleventh may be added without editing this file.

`rule_shape` selects the *form* of the entry and exit rules from a closed vocabulary of eight
(`app.evolution.models.RULE_SHAPES`, rendered by `app.evolution.ruleforms.RENDERERS`), and the three
period parameters are read in that form's terms:

| `rule_shape` | entry | exit |
|---|---|---|
| `ma-crossover` | `close > sma(R) and ema(F) crosses_above ema(S)` | `ema(F) crosses_below ema(S)` |
| `momentum-state` | `close > sma(R) and ema(F) > ema(S) and rsi(F) > 55` | `ema(F) < ema(S)` |
| `rsi-pullback` | `close > sma(R) and rsi(F) < 40` | `rsi(F) > 60` |
| `band-reversion` | `close > sma(R) and close < bb_lower(S, 2)` | `close crosses_above bb_mid(S, 2)` |
| `channel-breakout` | `close crosses_above swing_high(F) and close > sma(R)` | `close crosses_below swing_low(F)` |
| `band-breakout` | `close crosses_above bb_upper(S, 2) and close > sma(R)` | `close crosses_below bb_mid(S, 2)` |
| `macd-cross` | `macd_macd(F, S, 9) crosses_above macd_signal(F, S, 9) and close > sma(R)` | `macd_macd(F, S, 9) crosses_below macd_signal(F, S, 9)` |
| `vol-compression` | `close > sma(R) and ema(F) > ema(S) and atr(F) / close < 0.02` | `atr(F) / close > 0.05 or close crosses_below sma(R)` |

`F`/`S`/`R` are `fast`/`slow`/`regime_ma`, still ordered `fast < slow < regime_ma` and now additionally
bounded (`app.evolution.models.RULES_PERIOD_BOUNDS`: 3–40, 10–90, 50–250). The bounds are new and are
load-bearing: `app.rules.grammar` does not range-check an indicator's parameters, so `sma(600)` parses
and then fails at *evaluation* time as a whole card lost mid-run, and `regime_ma`'s 250 ceiling is what
keeps the largest warmup a genome can demand under `app.evolution.universe.MIN_WARMUP_BARS`.

Every threshold inside a form — RSI's 40/60, Bollinger's 2 deviations, MACD's 9-bar signal, the 2%/5%
ATR band — is a **structural constant of that hypothesis, not a free parameter**. It is the textbook
setting the form is conventionally stated at, it is identical across every candidate of that shape, and
no search step can move it. That is `PROTOCOL.md` §3.4 applied to the shape vocabulary itself: a form
whose canonical setting does not work is a finding; a form with a tunable threshold is an invitation to
fit one.

**Why this section changed.** Until 2026-08-26 the entry and exit were a single hardcoded f-string in
`app.evolution.proposer._rules_card`, and this file described that one template as the search space. It
was accurate, and that was the problem: the completed 231-generation, 2,374-candidate run explored
exactly one strategy form and varied only its numbers and its universe, and masking the numbers out of
all 25 of its outstanding seat requests yields exactly one distinct entry/exit template
(`docs/research/loop/01-what-the-search-found.md`). No amount of window-matrix or gate tuning changes
what a search that cannot emit a second rule shape is able to find.

**There is no `discipline` parameter, and the tenth slot it used to occupy is what paid for
`rule_shape`.** `discipline` was drawn with `rng.choice(list(Discipline))`, was a mutable trait a
mutation could flip on its own, and reached nothing but `StrategyCard(discipline=...)` for display —
26 of 673 single-parent mutations produced a child behaviourally identical to its parent, 15 of them
differing in nothing but that label, and two of the 25 outstanding seat requests are byte-identical
strategies under different discipline names. A card's `discipline` is now **derived from its emitted
rule** by `app.evolution.ruleforms.classify`, which parses the rule and reads the label off the AST, so
two identical rules cannot carry two labels and a rule the classifier does not recognise is a refused
proposal rather than a card wearing an invented category. Two `Discipline` members are consequently
unreachable from this loop: `pairs-rotation` (the engine evaluates `entry` per symbol against that
symbol's own bars, so the grammar cannot express a pair — it was nonetheless the completed run's most
common label, on 348 of 934 rules genomes) and `risk-managed` (a statement about the brackets, not the
rule).

Genomes written before `rule_shape` existed carry `discipline` and no `rule_shape`. They are read as
`ma-crossover` — which is what they emitted — and translated on their next mutation or crossover, so the
finished run's elites keep breeding across the change rather than being refused.

**`allocation`** — an `app.tournament.allocation.AllocationCard`. Continuous sleeve weights with
drift-band rebalancing. Free parameters: `weights`, `band_pct`, `tilt` — three. This is the only
shape that can express the thing the owner actually asked for, which was not another QLD/SSO pair
but a *blend*: mostly trend, a few per cent semiconductors, the rest stability. Sleeve weights must
sum to exactly `Decimal(1)`; the model refuses anything else rather than silently normalising.

Ladder cards are readable by the scorer but are **not** generated. Their parameter space is a rung
schedule, and mutating a rung schedule under a search that never stops is the most direct route to an
overfit available in this codebase.

### The ticker partition

The owner's constraint — "you have to divide tickers if it is Roth IRA and a regular taxable" — is
enforced structurally rather than by a check that runs afterwards. `app.evolution.universe` declares
two pools that are disjoint by construction, so a Roth candidate cannot draw a taxable ticker even in
principle:

| sleeve | taxable (trading, savings) | Roth |
|---|---|---|
| growth | NVDA TSM MU AMD QCOM MSFT GOOGL AMZN NFLX ORCL INTC TXN | AAPL ADBE CRM AMAT LRCX KLAC INTU CSCO |
| leveraged | QLD | SSO |
| satellite | **SOXX SMH** XLK | IGV VUG |
| stability | DVY XLP XLU AGG GLD IEF | VIG TIP SHY VTV RSP VNQ |

**A ticker's price history is a hard constraint here, and the first version of this table ignored
it.** Ten of the tickers originally listed could not cover the windows the loop runs. The engine's
lookahead guard refuses a whole *card* for a window when any one of its symbols cannot demonstrate
causality over an indicator warmup, and it records the refusal as an ordinary card failure — so
nothing surfaces as an error. The first live loop logged `chop-2011: 0 run file(s) written, 6 run(s)
attempted`, every candidate finished below the five-window eligibility floor, and the round reported
`0 of 0 eligible candidate(s) cleared the margin`. It was not producing weak candidates; it could not
produce a rankable one, and would not have at any point in the future.

Measured bars available before `gfc` (2007-10-09), the oldest window: META 0, SCHD 0, AVGO 0, ANET 0,
PANW 0, MTUM 0, USMV 0, QUAL 0, **SGOV 0 — and zero before four more windows, five of eight** — plus
two that look fine on a first-bar check and are not: BIL 93 and BND 128, against the 200 an
`sma(200)` rank key needs.

Every sleeve is now screened against `MIN_WARMUP_BARS` = 300 (the largest fixed warmup in the
genome's vocabulary, plus room for `regime_ma` to mutate upward), measured off the real bar store,
with `tests/test_evolution_proposer.py` asserting no gaps across all eight main windows. When that
test fails the rule is to substitute the ticker, never to lower the threshold — the threshold is
derived from what the engine will actually accept, so lowering it just re-admits cards it refuses.
The binding survivors are QLD and SSO at 328 bars before `gfc`, which is why the leveraged sleeves
live and the 2011-vintage factor ETFs do not.

**Both semiconductor ETFs sit on the taxable side, and the first draft of this table had that
wrong.** The obvious split -- SOXX taxable, SMH Roth, one per book -- is the one that cannot ship:
SMH is already traded by `retired/c10-momentum.json`, a `trading`-purpose card, and
`app.tournament.results.load_library` loads `retired/` alongside the other three tiers, so a Roth
candidate holding SMH would fail `find_disjointness_violations` and take every Roth generation down
with it. The same check killed the originally-drafted XLV (in `candidates/c07-chop.json`,
`candidates/c20-rotation.json`, `retired/c01-meanrev.json`) and TLT (in `candidates/c09-convex.json`,
`candidates/c11-breakout.json`, `candidates/c14-riskmanaged-wide.json`). IGV, MTUM and TIP replaced
them because nothing in the library trades those at all.

Putting SOXX and SMH together costs nothing: taxable-to-taxable overlap is legal, because the rule
binds only between `roth` and the two taxable purposes. The Roth book still gets a sector tilt, from
its own satellite sleeve rather than by sharing one of these. Whether SOXX and SMH are "substantially
identical" to each other under IRC section 1091 is a live question this table does not answer; what
makes it harmless in this direction is that both sit in taxable accounts, where the worst case is a
deferred loss rather than a destroyed one.

The same library check later removed SCHD, BIL, BND, SGOV, USMV, SPLV, QUAL, MTUM, ANET, PANW, META
and AVGO for a different reason — history, not disjointness — and their replacements (INTC, TXN, DVY,
INTU, CSCO, VUG, SHY, VTV, RSP, VNQ) were each confirmed absent from every committed card at the same
time, so the disjointness guarantee above still holds against the real library and not merely between
the two pools.

This is a stronger condition than the law requires and a weaker one than the law asks about. IRC
§1091 turns on whether two securities are "substantially identical", and the IRS has never ruled on
ETF pairs of this kind. Ticker disjointness is a *necessary* condition this partition satisfies, not
a *sufficient* one any backtest can prove — the same caveat `ROTH-DISJOINT-LADDER.md` already
records. What makes it worth enforcing anyway is the asymmetry of the downside: Rev. Rul. 2008-5
holds that a loss sold in a taxable account and replaced inside an IRA is disallowed with no basis
adjustment anywhere, which is strictly worse than an ordinary wash sale, which merely defers.

`app.tournament.purposes.find_disjointness_violations` is still run over every proposed generation,
and again before any promotion, as a second line of defence on top of the partition.

### The news bias

`LoopConfig.use_news` lets a fraction of each generation draw its universe from what the news layer
currently has coverage for, rather than from what was already in the pool. This is the owner's
"maybe tracking some newly added stocks instead of what other influencers usually had".

What it does *not* do is score anything. `app.evolution.news_signal` returns an ordered list of
symbols and the counts that ordered them, and nothing else — no sentiment score, no signal strength,
no predicted return. `AGENTS-INTEGRATION-PLAN.md` §0 is unambiguous that an agent may propose, name,
argue and select, and may never emit a number, and `news_models.py` says a provider may report only
what it counted, never what it concluded. News decides *what gets tested*; price decides whether it
was worth testing.

Two honest limitations. `AGENTS-INTEGRATION-PLAN.md` Phase D — "measure before believing" — has not
been completed, so there is at present **no evidence in this programme that news attention predicts
returns**, and this feature is a way of choosing hypotheses rather than a signal. And the social half
of Phase D cannot be run yet at all: StockTwits and Reddit serve only a live window with no
historical query, so a sentiment history has to accumulate forward before it can be studied. With
`use_news=True` the loop's proposals also stop being reproducible from the seed alone, since they
depend on what the providers returned at proposal time; a news-derived genome therefore records the
symbols it was handed and why. The determinism claim is scoped to `use_news=False`.

---

## 4. The gate

A candidate qualifies in a generation when **all** of:

- it is `eligible` (ran at least `MIN_ELIGIBLE_MAIN_WINDOWS` = 5 of the selection windows),
- its median adjusted excess exceeds `promotion_margin_pp`, default **21.2 points**,
- it took at least one trade,
- and its holdout median is **not negative**.

The 21.2 is not a taste. `PROTOCOL.md` §7 measured it: one identical card re-run under twelve
`universe` orderings moved its three-year return across a 53.9-point spread, σ = 21.2 points. A
margin below that floor is not evidence of anything, and a searcher generating thousands of
candidates will clear a smaller bar by luck alone on a schedule.

The margin is compared in percentage points against a median that arrives as a **fraction**, so the
gate converts before comparing. This is stated because getting it wrong does not mis-tune the gate,
it closes it: comparing `0.0676` against `21.2` asks for a +2120-point excess, and the loop would
search forever, report entirely reasonable-looking standings, and never promote anything.

A candidate is **promoted** when it qualifies in `promotion_consecutive` (default 2) consecutive
generations whose window sets differ.

**Amendment, 2026-08-29 — "differ" was satisfied by one window in five, and nothing said so.** This
clause is unchanged in force; what changed is that the gate now records how much its two measurements
actually had in common, and can be told to require more. §3's rotation drops exactly one window from a
six-window pool per lane appearance, so two consecutive appearances share four of five **by
construction** — every promotion this loop has ever made cleared a 21.2-point margin twice on window
sets that were 80% the same measurement, and that figure appeared in no artifact.
`docs/research/loop/01-what-the-search-found.md` point 2 had to reconstruct it from the ledger.

Two things follow, and only one of them is a change to the gate:

- **The overlap is now written into every promotion's `reason`** ("sharing at most 4 window(s)"),
  and into the `PendingSeat` a person approves from. This is not a gate change; it is the number the
  gate was always deciding on, stated. Nothing already promoted is re-judged — this document's
  amendments are not retroactive.
- **`LoopConfig.promotion_max_shared_windows` may cap that overlap**, and defaults to `None`, which
  is the rule above exactly as pre-registered. Set to an integer, a later generation counts as a
  second piece of evidence only when it shares at most that many windows with **every** set already
  counted.

**The honest reading of the second bullet is that the shipped window pool cannot yet satisfy a strict
ceiling.** Eight main windows minus a two-window holdout is six; a selection set must hold at least
`MIN_ELIGIBLE_MAIN_WINDOWS` = 5; so two distinct sets of five drawn from six always share four, and a
ceiling of 3 or less is arithmetically unreachable. `app.evolution.loop.achievable_shared_windows`
computes that floor and `start_loop` **refuses** a ceiling below it — a `400`, before any thread
starts. That refusal is the point of building the knob now rather than later: the alternative failure
is the one `holdout_windows`' docstring already records from the other direction, where widening the
holdout to three windows would have left an unrotatable five-window pool and made promotion impossible
*silently*, with the loop searching forever and printing entirely reasonable standings. A gate nothing
can clear must announce itself when it is set.

So the real remedy for point 2 is the pool, not the ceiling: `WINDOWS.md` would need more eligible
main windows before `promotion_max_shared_windows` can be set anywhere useful. Until then this ships
as an enforced, reported constraint with the default that changes nothing, and the 4-of-5 figure is on
the record where a reader will meet it.

**Observed on the first real multi-generation run:** with `live-6` as the holdout, every candidate
across two generations posted a *negative* holdout median and nothing was promoted — even with the
margin dropped to 0.5 points to try to force one through. That is the gate doing its job rather than a
defect, but it is also the first evidence that a single recent 28-day window is a very sharp holdout,
and it means promotions will be rare. Whether that sharpness is the right calibration is an open
question this document does not settle; the thing to resist is loosening the gate because promotions
turn out to be rare, since "rare" is what a floor set at the measured noise level is supposed to
produce. Promotion copies the card into `backend/app/paper/library/candidates/`
— never straight into `base/`, which is the human programme's standing field and requires a second,
differently-evidenced step. Roth disjointness is re-checked against the whole library at promotion
time; a violation refuses the promotion outright, and no margin overrides it.

When `seat_on_paper_desk` (default on), a promoted card is also added to
`data/loop/roster_overlay.json`, which `app.paperdesk.desk` reads additively at request time. The
overlay never removes a hand-authored seat, and deleting the file restores exactly the hand-authored
desk. The desk is simulated and holds no real money; nothing in this loop places a real order, and
nothing in it is a recommendation to.

---

## 5. Falsifiable predictions

Stated in advance, so this document can be wrong rather than merely descriptive.

1. **Most candidates will fail the gate.** If more than a third of proposed candidates clear a
   21.2-point margin in any generation, the margin is not doing its job, or the window set is too
   easy, and the gate must be re-examined before any promotion from that generation is trusted.
2. **Selection medians will exceed holdout medians on average.** This is the signature of a searcher
   working as designed — it optimises what it can see. If the two are indistinguishable across ten
   generations, the holdout is not adversarial enough to be worth the runtime it costs.
3. **Allocation candidates will beat rules candidates on the drawdown windows and lose on the trend
   windows.** If they do not, the stability sleeves are not doing what the blend was designed to do,
   and the satellite weighting range in §3 is the first thing to re-derive.
4. **News-biased candidates will be indistinguishable from pool-drawn candidates.** This is the null
   `AGENTS-INTEGRATION-PLAN.md` Phase D predicts, and the loop is the cheapest way this programme has
   to test it. If it holds over enough generations to say so, `use_news` should default to off and
   the feature should be reported as measured-and-not-useful rather than quietly kept.
5. **Q-values will degrade monotonically as the loop runs.** If a candidate's q-value ever improves
   without new runs, the ledger's denominator is wrong and every promotion made under it is suspect.

## 6. What this does not do

It does not amend any committed round's numbers. It does not write into `base/`, `variants/`, or
`retired/`. It does not run concurrently with a manually launched round — `DEFECTS.md` D3 records
what two concurrent processes do to the bar store (135 card-runs, zero results, silently recorded as
ordinary card failures), so the loop takes the same single slot `app.tournament.jobs` holds and waits
rather than racing. It does not survive a server restart: like `app.tournament.jobs`, the supervisor
is in-process with no detached process to orphan, and a restart stops the loop. It does not place a
real trade, and it does not produce investment advice.
