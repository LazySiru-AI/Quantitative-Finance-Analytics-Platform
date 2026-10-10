/**
 * "A card must be readable before it is decidable" -- `SPEC.md`'s own heading for this rule. Never
 * show a bare `g1859-fd7c2c196f35` as a candidate's primary name; compose something a person can read
 * without opening the dossier.
 *
 * Two functions:
 *  - `shortId(genome_id)` -- `"g1859-fd7c2c196f35"` -> `"g1859·fd7c"`, a subordinate id chip.
 *    Pure string parsing, no server round trip: the generation and the first four hex digits of the
 *    hash are already sitting in the id every screen in this app already has.
 *  - `headline(input)` -- `"EMA 13/21 crossover, 135-day regime filter · CSCO/AMAT/LRCX +3 · Roth"`,
 *    a purpose-only-placeholder builder, used only as a last resort -- see below.
 *
 * **The server now composes the real headline; this module mostly just holds the fallback.**
 * `PendingSeat.headline` and `Dossier.headline` (`api/evolution.ts`) are both already composed
 * server-side from the parsed rule, and the backend guarantees the two are byte-identical for the same
 * genome (it has its own test asserting exactly that). `PendingSeatsPanel.tsx`'s `CandidateRow`
 * prefers those server strings directly and does not recompose them from this module. `headline()`
 * below exists for the one case neither is available: no dossier fetched yet AND no `PendingSeat.headline`
 * on the row (an older/degraded deployment, or a genuinely missing value) -- in which case it degrades
 * to an honest purpose-only placeholder, never a guess.
 *
 * **Why the placeholder must never lead with `discipline_label`, even though it exists on the wire
 * (2026-08-26 correction).** The first version of this function led with `discipline`
 * ("Mean-reversion", "Breakout", ...), matching an early draft of the contract. That was wrong, and
 * verified wrong against the frozen ledger snapshot, not just in theory:
 *
 *   - All 25 of the cards actually sitting in the seat-request queue share exactly ONE entry/exit
 *     template (numbers masked): entry `close > sma(N) and ema(N) crosses_above ema(N)`, exit
 *     `ema(N) crosses_below ema(N)`. One distinct template, twenty-five different discipline labels on
 *     top of it.
 *   - `g1815-d05786e4c611` was mutated into `g1823-e2a3d5060b09`. The *only* fields that differ
 *     between parent and child are `agent_id`, `display_name`, and the discipline label
 *     (`"breakout"` -> `"mean-reversion"`) -- universe, entry, exit, stop, sizing, every numeric
 *     trait, byte-identical.
 *
 * `Dossier.discipline_label` (`api/evolution.ts`) is a self-declared label the genome (or whatever
 * proposed it) attached to itself; it is not derived from the rule and a mutation can flip it without
 * touching a single trading parameter. Leading a card's name with it states something about the
 * strategy the data does not support -- exactly the sin `SPEC.md`'s "null is never zero" and "copy,
 * never recompute" house rules exist to prevent for numbers, now shown to apply to labels too. It
 * renders only in `CandidateDossier.tsx`'s dedicated `discipline-label` block, paired with the
 * backend's own `discipline_label_note` caveat, never as a name anywhere in this module.
 *
 * **What the placeholder uses instead: `ruleSummary`.** A short, rule-derived phrase -- e.g. "EMA
 * 13/21 crossover, 135-day regime filter" -- for a caller that has rule text but no full composed
 * headline string. In the app's actual current call sites this is always `null` (a real rule-derived
 * summary is only ever available already bundled inside a full `headline` string), so `headline()`
 * effectively always returns the purpose-only line in practice; the parameter is kept so this function
 * stays honest and testable rather than silently reading a discipline label if one is ever passed in.
 * If someone is tempted to plug `discipline_label` in here to fill the gap: don't -- read the
 * g1815/g1823 case above first.
 *
 * **The purpose word here is short-form** (`"Roth"`, not `PURPOSE_LABELS.roth`'s `"Roth IRA"`) --
 * matching the server's own `headline` composition verbatim. `PURPOSE_LABELS` (`api/evolution.ts`) is
 * a different, longer label used for the standalone purpose badge elsewhere on the row; the two are
 * not meant to be interchangeable and this module keeps its own copy rather than importing one to
 * stand in for the other.
 */

import type { Purpose } from "@/api/evolution";
import { t, type MessageKey } from "@/i18n";

const HEADLINE_PURPOSE_KEYS: Record<Purpose, MessageKey> = {
  savings: "competitionRounds.candidateName.purpose.savings",
  trading: "competitionRounds.candidateName.purpose.trading",
  roth: "competitionRounds.candidateName.purpose.roth",
};

export interface HeadlineInput {
  /** A short, rule-derived description of what the strategy actually does -- e.g. "EMA 13/21
   * crossover, 135-day regime filter" -- never a discipline label; see the module docstring for why.
   * `null` when the caller has neither a server-supplied `headline` string nor rule text of its own
   * (the common case -- see the module docstring on why this is effectively always `null` today). */
  ruleSummary: string | null;
  /** The card's universe, in the card's own order -- only the first three are shown by name. */
  tickers: string[];
  purpose: Purpose;
}

/** `["CSCO","AMAT","LRCX","KLAC","INTU","IGV"]` -> `"CSCO/AMAT/LRCX +3"` -- the first three tickers by
 * name, then a count of the rest. A universe of three or fewer names shows every ticker and no `+N`. */
function tickerSummary(tickers: string[]): string {
  if (tickers.length === 0) return t("competitionRounds.candidateName.noTickers");
  const top3 = tickers.slice(0, 3).join("/");
  const extra = tickers.length > 3 ? ` +${tickers.length - 3}` : "";
  return `${top3}${extra}`;
}

/**
 * `"{rule-derived description} · {top3 tickers}{+N} · {Purpose}"`, or, when no rule-derived
 * description is available yet, a purpose-only line that says plainly that more detail is one click
 * away rather than guessing at a description this function was never given. Never composes from
 * `discipline` -- see the module docstring.
 */
export function headline(input: HeadlineInput): string {
  const purposeWord = t(HEADLINE_PURPOSE_KEYS[input.purpose]);
  const rule = input.ruleSummary?.trim();
  if (!rule) {
    return t("competitionRounds.candidateName.placeholder", { purpose: purposeWord });
  }
  return t("competitionRounds.candidateName.headline", {
    rule,
    tickers: tickerSummary(input.tickers),
    purpose: purposeWord,
  });
}

/**
 * `"g1859-fd7c2c196f35"` -> `"g1859·fd7c"` -- the generation prefix already in the id, plus the
 * first four hex characters of its hash, lower-cased. A `genome_id` that does not match the expected
 * `g<digits>-<hex>` shape is returned unchanged rather than guessed at -- an unrecognised id rendered
 * verbatim is honest; a shortened id built from a wrong assumption about its shape is not.
 */
export function shortId(genomeId: string): string {
  const trimmed = genomeId.trim();
  const match = /^(g\d+)-([0-9a-fA-F]+)/.exec(trimmed);
  const generation = match?.[1];
  const hash = match?.[2];
  if (!generation || !hash) return trimmed;
  return `${generation}·${hash.slice(0, 4).toLowerCase()}`;
}
