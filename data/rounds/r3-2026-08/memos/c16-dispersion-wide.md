# c16-dispersion-wide — Full-Breadth Sector Rotation

Discipline: pairs-rotation. Written before any trading-window result exists (designed through 2026-02-13).

## 1. Mechanism, and who is on the other side

The rule engine has no cross-sectional operator: an entry or exit rule is evaluated against one
symbol's own bars, never against another symbol's. So "rotation" in this system cannot mean "buy
the strongest of N names" — it can only mean "apply one absolute filter to N names and let
`max_positions` plus the universe's fill order decide which of the qualifying names actually get
bought." The filter here is `close > sma(50) and rsi(14) > 55 and rsi(14) < 80` (a confirmed,
non-extreme uptrend), the same filter the incumbent semis-rotation card (`A-rotation`) used against
9 highly correlated chip names.

This card changes exactly one thing relative to that incumbent: the correlation structure of the
universe. If breadth is worth anything, holding a capped basket across genuinely different economic
drivers should behave differently — smoother, more consistently exposed to *some* uptrend somewhere
— than holding a capped basket of one correlated cluster. If breadth is worth nothing, this basket
should just track the broad market: the entry condition fires when "the market is going up," and a
name-by-name absolute filter across 8+ sectors is a slow, capped substitute for buying SPY, not a
source of edge.

Who is on the other side: momentum and trend traders in each of these sectors independently, who
already positioned before a 50-day-average-and-RSI confirmation fires; mean-reversion sellers who
fade strength inside a still-intact uptrend in any one of these names and get run over while it
persists; and, in the failure case, nobody in particular — if this basket just reproduces the index
at higher friction (stop/target/time-stop churn, one entry per session instead of continuous
exposure), the "edge" is an illusion of activity around a buy-and-hold position.

## 2. Names and order — the ordering argument

**Universe (in fill order):** `MSFT, JNJ, VZ, KO, CAT, MCD, NEE, XOM, JPM, HD, PLD, LIN`

One name per GICS sector, except Consumer Discretionary gets two (HD, MCD — housing/home-improvement
spend vs. restaurant/quick-service spend, different enough drivers that treating them as one sector
seemed wrong for a card whose entire premise is dispersion): Energy (XOM), Industrials (CAT),
Consumer Discretionary (HD, MCD), Consumer Staples (KO), Health Care (JNJ), Financials (JPM),
Information Technology (MSFT), Communication Services (VZ), Utilities (NEE), Materials (LIN), Real
Estate (PLD).

**Ordering argument, one sentence:** names are ordered by ascending trailing-253-session average
pairwise correlation to the rest of the book (MSFT lowest at 0.12, LIN highest at 0.36), so that
when more than 4 of 12 qualify on the same session — measured at ~71% of sessions over the trailing
two years — the broker's fixed fill order fills the *most diversifying* names first, which is the
one ordering rule available in this system that is actually about the thing this card is testing
(breadth) rather than an arbitrary tiebreak dressed up as a decision. I built the ranking this way
specifically because the round brief flagged that ordering alone moved a prior card's return by a
53.9-point spread (sigma 21.2) — an alphabetical or hand-picked order here would be exactly that kind
of accident, and I wanted the order itself to be defensible as a portfolio-construction choice, not
just a parameter I didn't think about.

I originally considered `PLD` and `SPG` (mall REITs) as an intentional "same sector, opposite
driver" pair (industrial/logistics REIT as an e-commerce beneficiary vs. retail/mall REIT as an
e-commerce victim). Measuring it killed the idea: PLD/SPG trailing pairwise correlation was 0.722 —
the single highest pair in that candidate set, higher than most same-sector pairs in the incumbent
semis card. Both trade primarily as rate-sensitive REITs; the retail-theme divergence I expected
does not show up in daily returns. I dropped SPG and used MCD instead, which brought the basket's
mean pairwise correlation down from 0.265 to 0.245 and its single highest pair down from 0.722
(PLD/SPG) to 0.566 (HD/PLD). This is exactly the trap the round brief warned about generally —
verify the claim against data before it goes in the memo — applied to my own hypothesis, not just
the incumbent's.

## 3. Is this selection index-derived? Stated plainly

**No, by the test the brief itself sets out.** The 12 names were chosen and ordered by measured
correlation structure and liquidity — not by the rule "take the largest constituent of each S&P
sector," which is the specific mechanical selection the brief gates. I did not consult sector
weightings or market-cap rankings when picking within a sector; I picked well-known, highly liquid,
long-listed names and then let the correlation matrix (not the index) decide which one to drop
(SPG) and how to order the survivors.

That said, I want to be honest about the residual issue rather than let the technical distinction
paper over it: every name in this universe is, as a matter of fact, a company that survived to be
listed on an index today. My selection process didn't consult the index, but the *store* that
supplied my candidates is dominated by current constituents, so I could not have picked a name that
failed in 2008 even if my correlation-based logic had wanted to. This card is not claiming to have
solved survivorship — it is claiming to have used a selection *method* that isn't the specific
mechanical shortcut the brief flags, while still being subject to the same underlying limitation
every stock-picking card in this store has. If the round's judges read "index-derived" more broadly
than the brief's own carve-out, I'd rather this paragraph exist than not.

## 4. What I measured through 2026-02-13

- **Cross-sector correlation, the headline claim:** trailing 253-session daily-return pairwise
  correlation across the 12 names (through 2026-02-13): **mean 0.245**, min −0.116 (JNJ vs. MSFT),
  max 0.566 (HD vs. PLD). The incumbent semis card measured mean 0.589 (range 0.286–0.824) across
  its 9 names. This basket is roughly **2.4x less correlated on average**, which is the entire bet
  this card is placing: if diversification helps a rotation-by-cap-and-order mechanism, it should
  show up as a smoother equity curve and fewer simultaneous drawdowns, for the same rule logic.
- **Breadth actually binding:** over the trailing ~504 sessions (~2 years), the median number of
  the 12 names satisfying the entry filter on any given day is **5 of 12**; at least 4 qualify on
  **71.2%** of sessions, at least 6 qualify on **42.7%**. The 4-slot cap is not a formality — on
  most sessions there are more qualifying names than slots, so the fill-order ranking actually does
  work rather than rubber-stamping whatever qualifies.
- **History depth:** all 12 names have continuous daily bars back to at least 1997 (PLD, the
  shortest), most back to 1970–1986, so the card is eligible on all 8 regime windows including
  `gfc`, with no data-availability gating.

## 5. Every parameter, and why

- **Entry `close > sma(50) and rsi(14) > 55 and rsi(14) < 80`, exit `close < sma(50) or rsi(14) <
  45`, `stop_loss_pct 0.12`, `take_profit_pct 0.20`, `max_hold_days 120`** — identical, digit for
  digit, to the incumbent semis-rotation card. This is deliberate, not laziness: holding the rule
  logic fixed and changing only the universe's correlation structure is what makes this card a
  controlled comparison rather than a second, differently-tuned idea. Any performance delta between
  this card and the incumbent is attributable to universe breadth, not to a different RSI band or a
  tighter stop that I chose after looking at which one back-tested better (I did not look at either
  card's trading-window results — both were designed pre-cutoff).
- **`max_positions = 4`, `position_pct = 0.25`** (4 × 0.25 = 1.00, full book when the cap binds).
  The incumbent used 3 of 9 (33% of universe). I used 4 of 12, which is also 33% of universe — the
  same concentration ratio, scaled to the larger universe, so that "how much of the available
  breadth gets captured at once" is held constant between the two cards as well. This is the last
  free parameter and I fixed it by that ratio rather than picking a number that looked good.
- **Universe size 12** — the maximum the card format allows, used in full so the breadth question
  gets the largest test this format permits.

No parameter was chosen by looking at the 2026-02-17→2026-08-18 trading window; all measurements
above stop at 2026-02-13.

## 6. What would falsify the thesis

If this card's median excess return and worst-window excess are statistically indistinguishable
from a card that runs the identical rule against a single-sector or high-correlation universe (i.e.,
against the incumbent `A-rotation`, or against a naively-alphabetical version of this same
12-name book), the conclusion is that correlation structure did not matter here — the absolute
entry filter is broad enough that "confirmed uptrend" just means "the market," and diversifying the
universe bought smoother optics without buying real edge. A second falsification: if performance is
highly sensitive to reordering this same 12-name universe (which the round brief has already shown
can move a return by 50+ points on an identical card), then the "ordering by correlation" logic
isn't actually doing useful work either, and the fill-order mechanism is just noise regardless of
how thoughtfully it's justified.

## 7. Predicted worst window

**`gfc` (2007-10-09 → 2009-03-09) is my predicted worst window**, and I expect it to be worse than
the other seven, not just nominally negative. My reasoning: this card's entry logic requires
`close > sma(50)`, which by construction only opens positions in names that are already trending up
— during a systemic, correlated crash, mean pairwise correlation across sectors rises sharply
(this is a well-documented feature of the GFC specifically, not something I need the trading window
to show me), so the very diversification this card is built on collapses exactly when a name-by-name
trend filter would otherwise protect capital by simply refusing to enter. I expect most or all 12
names to fail the entry filter simultaneously for extended stretches, the book to sit in cash (which
is not a loss but also not the diversification benefit being tested), and any positions entered
near the 2007 highs before the crash to be caught by the 12% stop rather than the 20% target. My
rough guess: excess return versus SPY in `gfc` in the -5 to -15 point range, driven mostly by
being stopped out of positions opened on the way down rather than by holding through a full-basket
selloff, since the card's own exit rule (`close < sma(50) or rsi(14) < 45`) should get most
positions closed reasonably early once the trend breaks.
