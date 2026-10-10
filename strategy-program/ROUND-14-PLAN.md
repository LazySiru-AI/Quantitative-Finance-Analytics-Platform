# Round 14 — naming the chooser

**Not investment advice.** Simulated books on a paper account. I am not a licensed financial adviser
and none of this is a recommendation about real capital.

**Pre-registered 2026-08-23, before any round-14 run exists.** The only computations reported below
are the slot-contention census and the parse check on the ranking keys — both properties of the
cards and the grammar, not of any result.

---

## 1. What this round is actually asking

A concurrent piece of work added `StrategyCard.rank_by`: a numeric expression deciding **which** of
the qualifying names takes a scarce slot. `app.tournament.runner._ordered_entry_candidates` is where
it lands, and its own docstring states the stake better than a plan could:

> The runner fills entries until the slots run out, so whichever order it walks the universe in *is*
> the selection rule whenever more names qualify than fit. Left unranked that order is the order the
> array was typed in, worth a measured **53.9-point spread over twelve orderings of one identical
> card**.

So this round is **not** asking "does a ranking key add alpha". It is asking something narrower and
more answerable:

> **Does naming the chooser reduce an arbitrariness that was already worth 53.9 points?**

Every number this programme has produced since round 1 carries that spread inside it. The universe
ordering was never a decision anybody made; it was the order symbols got typed into a JSON array,
and it has been silently selecting positions in every contested session of every round.

## 2. Why this is a new round and not a re-run

The obvious move — re-run rounds 1 through 5 with ranking keys and see what changes — is the wrong
one, and would do real damage.

Gate A reads round 5. Gate S′ reads rounds 2, 4 and 5. Rounds 6 through 12 are **selection** rounds
that scored over those frozen matrices, and two of them ended in owner overrides argued from specific
figures in them. Changing the engine underneath those matrices would retroactively invalidate seven
rounds of reasoning and both overrides, and every cross-round comparison the programme has made.

`PROTOCOL.md` §6(a) already forbids treating a re-run as new evidence. Round 14 therefore writes to
its own directory and **touches no existing results tree**.

## 3. The design: one decision isolated

`PROTOCOL.md` §7 requires that a variant isolate exactly one decision. Each entry below is a base
card, frozen and already scored in earlier rounds, plus variants **identical in every field except
`rank_by`**. The difference between a base and its variant is therefore the ranking key and nothing
else.

### The contenders

`rank_by` can only matter when more names qualify than there are slots, so the field is chosen on
measured headroom (universe size minus `max_positions`), not on preference:

| card | universe | slots | headroom | discipline |
|---|---|---|---|---|
| `B3-concentrated` | 12 | 4 | **8** | momentum |
| `c19-volatility` | 12 | 4 | **8** | volatility |
| `B-momentum` | 12 | 6 | 6 | momentum |
| `A-rotation` | 9 | 3 | 6 | pairs-rotation |
| `C-trend` | 9 | 5 | 4 | trend |

### The control, which is the part that makes the round falsifiable

| card | universe | slots | headroom |
|---|---|---|---|
| `c21-uncorrelated` | 6 | 6 | **0** |

A card with zero headroom can never have a contested slot, so a ranking key on it **must** produce
results byte-identical to its base. If the control diverges, the experiment is broken and no other
number in this round may be read. Stated in advance so it cannot be quietly dropped.

### The ranking keys

Three keys, chosen to express genuinely different theories of "which name deserves the slot", and
all three parse (`app.rules.grammar.parse_ranking`, checked before this document was written).
Highest key wins; unknown keys sort to the back, so a name whose indicator has not warmed up loses
the slot rather than silently taking it.

| suffix | key | the theory |
|---|---|---|
| `-rs` | `close / sma(200)` | relative strength — prefer the name furthest above its own long trend |
| `-lowvol` | `0 - atr(14) / close` | prefer the *calmest* qualifying name; negated because the sort takes the highest |
| `-stretch` | `(close - sma(20)) / atr(14)` | prefer the largest move measured in that name's own volatility |

That gives **5 contenders × 3 keys + 1 control × 1 key = 16 variant cards**, run against their
6 frozen bases.

## 4. The matrix

Round 2's eight main regime windows (`score.MAIN_WINDOW_TAGS`) — the matrix Gate S′ still reads, and
the programme's reference regime spread. Round 14 runs its own cards over those **window definitions**
into `data/rounds/r14-2026-08/`; round 2's own results tree is not opened for writing.

Eight windows × 22 cards = **176 runs expected.** A shortfall is a lost card, not a rounding detail.

## 5. What will be measured

The primary quantity is **not** which variant scores highest. It is the **spread between variants of
one base card** — because that spread is what the universe ordering was silently contributing all
along.

- **Per base card: the range of median adjusted excess across its three keyed variants and its
  unranked self.** A wide range means the choice of chooser matters a great deal on that card; a
  narrow one means the 53.9-point figure does not generalise to it.
- **Whether any key wins consistently across bases**, or whether each card prefers a different one —
  the latter would mean `rank_by` is a per-card parameter rather than a discoverable rule.
- **The control's divergence, which must be exactly zero.**

## 6. Pre-committed expectations

Written before running. A contradiction is reported, not quietly revised.

1. **The control diverges by exactly 0.00.** If not, stop and fix the harness.
2. **The spread between a base's variants is smaller than 53.9 points on most cards.** That figure
   came from twelve orderings sampled to be maximally different; three considered keys should land
   closer together than twelve arbitrary permutations. If the spread is *larger*, the ranking keys
   are doing something stronger than removing arbitrariness, and that is a finding.
3. **No single key wins on every base.** Relative strength and low-volatility are close to opposite
   theories; a field where one beat the other everywhere would suggest the key is proxying for
   something cruder, like exposure.
4. **At least one base shows a spread under 5 points**, meaning its slots were rarely contested in
   practice despite the headroom on paper — headroom is a precondition, not a guarantee.

## 7. What this round cannot settle

- **It measures eight regime windows, not the future.** Round 4's central finding stands: rankings
  are conditional on the window mix.
- **It cannot say the winning key is *right*** — only that it beat two alternatives and an arbitrary
  order on this matrix. A key chosen after seeing these results would be fitted to them.
- **It does not license re-running rounds 1–5.** If a key proves out, the honest use is on *new*
  cards from here, leaving the frozen record as the record of what was actually run.
- **The 53.9-point figure is itself one measurement** from `PROTOCOL.md` §7, on one card. This round
  will produce a second, independent estimate of the same effect on five more.
