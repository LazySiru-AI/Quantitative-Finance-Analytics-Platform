/**
 * Reads the loop start form's `goal` prose looking for text *shaped like a config directive* --
 * `purposes=[...]`, `focus=NVDA,AMD`, a bare ticker list, "ranked by hit rate" -- and reports the ones
 * that will not happen, so the person about to press Start finds out before the run rather than
 * hundreds of generations later.
 *
 * **This does not read `goal` to steer the search, and must never be wired up to.** `LoopPanel.tsx`'s
 * own docstring forbids adding code that lets `goal`'s contents influence what gets proposed, and this
 * module does not: its output is addressed to the reader, never to the loop. Nothing here is reachable
 * from `buildLoopConfigFromDraft`, nothing here edits the draft, and the panel does not gate `onStart`
 * on it -- the goal field's freedom to hold any sentence at all is the point, and a warning that
 * blocked the button would take that away. The rule the helper text states ("the loop does not read
 * this text") stays literally true; what this adds is that the *form* now says so about the specific
 * sentence in front of you.
 *
 * **Why the check exists at all.** `data/loop/gen1873/PLAN.md` and `gen1877/PLAN.md` both record
 * `**Goal:** add saving as one of purpose as well` followed by `purposes=['trading', 'roth', 'saving']`.
 * Three separate faults, none of them surfaced anywhere: the directive was typed into a field nothing
 * parses; the field it was aiming at (`purposes`) is not on this form at all, so no amount of editing
 * the goal could have changed it; and `saving` is not a legal purpose in the first place
 * (`app.tournament.purposes.Purpose` is `savings`/`trading`/`roth`). Both generations then ran the
 * default lanes as though the request had never been made.
 *
 * **Two halves of a config, and only one of them is on this form.** `focus_symbols`/`avoid_symbols`
 * have fields here, so a directive naming them gets "set it in the field below" -- actionable advice.
 * `purposes`/`rank_by` do not: `POST /api/competition/loop/start` accepts them, this form has never
 * sent them, so their warning says the form cannot set them at all rather than pointing at a control
 * that does not exist. Deliberately, the unsettable-field warning does **not** name which default will
 * be used instead: `LoopConfig`'s defaults live in `app.evolution.models` and can change without this
 * file hearing about it, and a stale claim about what the run *will* do would be a worse lie than the
 * one this module exists to catch.
 *
 * **The Python twin.** `app.evolution.goal_directives` runs the same check server-side and writes its
 * findings into `gen{N}/PLAN.md`'s "What this generation is for" section, so the permanent record also
 * notes that a goal-embedded directive did not take effect. The two are deliberate duplicates (the
 * house convention `requestJson` and `PURPOSE_LABELS` already follow), not a shared contract: keep the
 * detected shapes and the wording in step by hand, and note that only this side can compare a
 * directive against a *draft* -- the backend sees only the config the loop was actually started with.
 */
import { RANK_BY_OPTIONS } from "@/api/competition";
import { PURPOSE_LABELS, parseSymbolListInput, type LoopFormDraft } from "@/api/evolution";
import { t, type MessageKey } from "@/i18n";

/** The config field a directive was aiming at. */
export type GoalDirectiveField = "purposes" | "focus_symbols" | "avoid_symbols" | "rank_by";

export interface GoalDirectiveWarning {
  field: GoalDirectiveField;
  /** The slice of goal text that triggered this, verbatim -- quoted back so the reader can see which
   * words are being talked about rather than having to guess. */
  quoted: string;
  /** The values the directive named, normalised for the field (tickers uppercased, the rest
   * lowercased). */
  values: string[];
  /** The subset of `values` that is not legal for this field. Empty when every value is legal, and
   * always empty for the two symbol fields -- the tradeable pool is the backend's to know, and it
   * already rejects an unknown ticker with a `422` this form surfaces. */
  illegal: string[];
  /** Every legal value for this field, when it has a closed set; `null` for the symbol fields. */
  legalValues: string[] | null;
  /** The main sentence: this text is recorded, it does not steer, here is what would. */
  message: string;
  /** The second sentence, present only when `illegal` is non-empty: which value is wrong and what the
   * legal ones are. Kept separate from `message` so a caller can render it with its own emphasis. */
  legalityMessage: string | null;
}

/** Derived from `PURPOSE_LABELS` rather than restated, so this file cannot drift out of agreement with
 * the rest of the frontend about how many purposes exist -- the same reason
 * `app.tournament.results._PURPOSE_VALUES` reads the enum instead of listing its values. */
const LEGAL_PURPOSES: string[] = Object.keys(PURPOSE_LABELS);

/** Likewise from `RANK_BY_OPTIONS` (`api/competition.ts`), which mirrors
 * `app.tournament.results.RANK_BY_CHOICES`. */
const LEGAL_RANK_BY: string[] = RANK_BY_OPTIONS.map((o) => o.value);

/** Which form control, if any, actually sets each field. `null` means this form has no control for it
 * -- see this module's docstring on why that case gets its own wording. Translated via the catalog
 * (`competitionRounds.goalDirective.control.*`) rather than kept as a literal here -- these strings
 * end up in the message a reader sees, and this module follows the house rule of translating chrome
 * text, not just component JSX. */
const FIELD_CONTROL_KEY: Record<GoalDirectiveField, MessageKey | null> = {
  purposes: "competitionRounds.goalDirective.control.purposes",
  rank_by: null,
  focus_symbols: "competitionRounds.goalDirective.control.focusSymbols",
  avoid_symbols: "competitionRounds.goalDirective.control.avoidSymbols",
};

/** Reads as "this form has no ___ field", so it carries no article. */
const FIELD_NOUN_KEY: Record<GoalDirectiveField, MessageKey> = {
  purposes: "competitionRounds.goalDirective.fieldNoun.purposes",
  rank_by: "competitionRounds.goalDirective.fieldNoun.rankBy",
  focus_symbols: "competitionRounds.goalDirective.fieldNoun.focusSymbols",
  avoid_symbols: "competitionRounds.goalDirective.fieldNoun.avoidSymbols",
};

/** Reads as `"saving" is not ___` -- singular for one bad value, plural for several. Only the two
 * closed-set fields ever reach this: a symbol's legality is the backend's to judge. */
const FIELD_VALUE_NOUN_KEY: Record<GoalDirectiveField, { one: MessageKey; many: MessageKey }> = {
  purposes: {
    one: "competitionRounds.goalDirective.valueNoun.purposesOne",
    many: "competitionRounds.goalDirective.valueNoun.purposesMany",
  },
  rank_by: {
    one: "competitionRounds.goalDirective.valueNoun.rankByOne",
    many: "competitionRounds.goalDirective.valueNoun.rankByMany",
  },
  focus_symbols: {
    one: "competitionRounds.goalDirective.valueNoun.tickerOne",
    many: "competitionRounds.goalDirective.valueNoun.tickerMany",
  },
  avoid_symbols: {
    one: "competitionRounds.goalDirective.valueNoun.tickerOne",
    many: "competitionRounds.goalDirective.valueNoun.tickerMany",
  },
};

/** Every `key=` spelling worth recognising, mapped to the config field it is aiming at. Keys are
 * matched case-insensitively, with `_`/`-`/spaces stripped first by `normaliseKey`. */
const KEY_ALIASES: Record<string, GoalDirectiveField> = {
  purpose: "purposes",
  purposes: "purposes",
  book: "purposes",
  books: "purposes",
  focus: "focus_symbols",
  focussymbols: "focus_symbols",
  include: "focus_symbols",
  mustinclude: "focus_symbols",
  avoid: "avoid_symbols",
  avoidsymbols: "avoid_symbols",
  exclude: "avoid_symbols",
  mustavoid: "avoid_symbols",
  rank: "rank_by",
  rankby: "rank_by",
  rankedby: "rank_by",
  sortby: "rank_by",
  metric: "rank_by",
};

/**
 * `key = value` only -- never `key: value`. A colon is ordinary punctuation in the kind of sentence
 * this field is *supposed* to hold ("what I want to know: does a semiconductor tilt survive a
 * drawdown"), and matching it would turn every well-written goal into a false alarm. An `=` in prose
 * is essentially always someone reaching for a config knob, which is exactly the mistake being caught.
 *
 * **The key may not contain a space**, and that is load-bearing rather than tidiness: an earlier
 * version allowed one, so `"plus avoid=TSLA"` matched with the key `"plus avoid"`, resolved to no
 * known field, and was skipped -- swallowing the `avoid=` directive sitting inside it. The leading
 * `\b` is the other half: without it `"myfocus=NVDA"` would match on the tail of somebody's word.
 */
const DIRECTIVE_RE =
  /\b([A-Za-z][A-Za-z_-]{1,15}?)\s*=\s*(\[[^\]\n]*\]?|\([^)\n]*\)?|"[^"\n]*"|'[^'\n]*'|[A-Za-z0-9._-]+(?:\s*,\s*['"]?[A-Za-z0-9._-]+['"]?)*)/g;

/** A run of two or more comma-separated all-caps tokens: `NVDA, AMD, MU`. Two, not one, because a
 * single capitalised word in a sentence is far more often an acronym than a ticker list, and this
 * warning has to be worth reading. */
const TICKER_RUN_RE = /\b[A-Z]{1,5}\b(?:\s*,\s*\b[A-Z]{1,5}\b)+/g;

/** All-caps words that turn up in goal prose and are not tickers. A false positive here costs the
 * reader a warning about their own English, so the list errs towards silence. */
const NOT_TICKERS = new Set([
  "A", "I", "AI", "ML", "LLM", "US", "USA", "EU", "UK", "ETF", "ETFS", "IRA", "ROTH", "CAGR", "IRR",
  "TWR", "PNL", "YTD", "MTD", "QTD", "EOD", "OK", "NO", "YES", "TODO", "FIFO", "LIFO", "MA", "EMA",
  "SMA", "RSI", "ATR", "AND", "OR", "NOT", "VS", "TBD", "NA", "PP", "BPS", "MAX", "MIN",
]);

/** The phrases that mean "rank by" in prose. Deliberately narrow: a bare mention of the word "median"
 * in a sentence about medians is not a directive, and treating it as one would make this noise. */
const METRIC_CUE_RE =
  /\b(?:rank(?:ed|ing)?\s+by|sort(?:ed)?\s+by|scored?\s+on|selected?\s+on|optimi[sz]e\s+for)\s+((?:the\s+|a\s+|its\s+)?[A-Za-z][A-Za-z-]*(?:\s+[A-Za-z][A-Za-z-]*){0,2})/gi;

const LEADING_ARTICLE_RE = /^(?:the|a|an|its)\s+/i;

function normaliseKey(raw: string): string {
  return raw.toLowerCase().replace(/[\s_-]/g, "");
}

/** `"['trading', 'roth']"` -> `["trading", "roth"]`. Strips one layer of brackets/parens, then quotes,
 * then splits on commas -- the shapes a person actually types when half-remembering Python. */
function splitDirectiveValue(raw: string): string[] {
  const unwrapped = raw.trim().replace(/^[[(]/, "").replace(/[\])]$/, "");
  return unwrapped
    .split(",")
    .map((part) => part.trim().replace(/^["']/, "").replace(/["']$/, "").trim())
    .filter((part) => part.length > 0);
}

function normaliseValue(field: GoalDirectiveField, raw: string): string {
  if (field === "focus_symbols" || field === "avoid_symbols") return raw.toUpperCase();
  if (field === "rank_by") return raw.toLowerCase().replace(/\s+/g, "-");
  return raw.toLowerCase();
}

function legalValuesFor(field: GoalDirectiveField): string[] | null {
  if (field === "purposes") return LEGAL_PURPOSES;
  if (field === "rank_by") return LEGAL_RANK_BY;
  return null;
}

/** What the draft's machine-readable half already carries for this field. `null` means the form has no
 * such field at all -- not "empty", *absent*; see this module's docstring. */
function draftValuesFor(field: GoalDirectiveField, draft: LoopFormDraft): string[] | null {
  if (field === "focus_symbols") return parseSymbolListInput(draft.focusSymbolsInput);
  if (field === "avoid_symbols") return parseSymbolListInput(draft.avoidSymbolsInput);
  // `purposes` used to return `null` here -- "the form has no such field" -- and that was true until
  // the checkbox group landed. It is now a real control, so a goal that names exactly the books
  // already ticked is redundant rather than misleading and is not warned about, the same rule the two
  // ticker fields follow.
  if (field === "purposes") return [...draft.purposes];
  return null;
}

function buildWarning(
  field: GoalDirectiveField,
  quoted: string,
  values: string[],
): GoalDirectiveWarning {
  const legalValues = legalValuesFor(field);
  const illegal = legalValues === null ? [] : values.filter((v) => !legalValues.includes(v));
  const controlKey = FIELD_CONTROL_KEY[field];
  const message =
    controlKey === null
      ? t("competitionRounds.goalDirective.messageNoControl", { fieldNoun: t(FIELD_NOUN_KEY[field]) })
      : t("competitionRounds.goalDirective.messageWithControl", {
          values: values.join(", "),
          control: t(controlKey),
        });
  const nounKeys = FIELD_VALUE_NOUN_KEY[field];
  const legalityMessage =
    illegal.length === 0 || legalValues === null
      ? null
      : t(
          illegal.length === 1
            ? "competitionRounds.goalDirective.illegalValues_one"
            : "competitionRounds.goalDirective.illegalValues_other",
          {
            illegalQuoted: illegal.map((v) => `"${v}"`).join(", "),
            noun: t(illegal.length === 1 ? nounKeys.one : nounKeys.many),
            legalValues: legalValues.join(", "),
          },
        );
  return { field, quoted, values, illegal, legalValues, message, legalityMessage };
}

/**
 * Every directive-shaped thing in `goal` that the draft does not already reflect.
 *
 * Returns `[]` for the ordinary case -- a goal that reads like a question, which is what the field is
 * for. A directive whose values the draft *does* already carry (`focus=NVDA,AMD` typed above a
 * must-include field holding `NVDA, AMD`) is not reported either: that text is redundant, not
 * misleading, and warning about it would train the reader to ignore this callout.
 */
export function detectGoalDirectives(goal: string, draft: LoopFormDraft): GoalDirectiveWarning[] {
  if (!goal.trim()) return [];
  const warnings: GoalDirectiveWarning[] = [];
  const seen = new Set<string>();
  const push = (w: GoalDirectiveWarning) => {
    const key = `${w.field}::${w.values.join(",")}`;
    if (seen.has(key)) return;
    seen.add(key);
    warnings.push(w);
  };

  // Blanked as each `key=value` is consumed, so the metric-cue and ticker-run passes below cannot
  // report the same words a second time under a different heading.
  let residue = goal;
  const blank = (start: number, length: number) => {
    residue = residue.slice(0, start) + " ".repeat(length) + residue.slice(start + length);
  };

  for (const match of goal.matchAll(DIRECTIVE_RE)) {
    // Both groups are mandatory in `DIRECTIVE_RE`, so neither can be absent in a match -- the guard
    // is what `noUncheckedIndexedAccess` wants to see instead of a `!`, and costs nothing.
    const [key, rawValue] = [match[1], match[2]];
    if (key === undefined || rawValue === undefined) continue;
    const field = KEY_ALIASES[normaliseKey(key)];
    if (field === undefined) continue;
    const values = splitDirectiveValue(rawValue).map((v) => normaliseValue(field, v));
    if (values.length === 0) continue;
    blank(match.index, match[0].length);
    const draftValues = draftValuesFor(field, draft);
    if (draftValues !== null && values.every((v) => draftValues.includes(v))) continue;
    push(buildWarning(field, match[0].trim(), values));
  }

  for (const match of residue.matchAll(METRIC_CUE_RE)) {
    const captured = match[1];
    if (captured === undefined) continue;
    const phrase = captured.trim().replace(LEADING_ARTICLE_RE, "");
    const words = phrase.split(/\s+/);
    // Longest legal prefix wins, so "ranked by excess per exposure over the matrix" resolves to
    // `excess-per-exposure` rather than being reported as an illegal four-word metric.
    let value = normaliseValue("rank_by", words[0] ?? phrase);
    for (let n = words.length; n >= 1; n -= 1) {
      const candidate = normaliseValue("rank_by", words.slice(0, n).join(" "));
      if (LEGAL_RANK_BY.includes(candidate)) {
        value = candidate;
        break;
      }
    }
    push(buildWarning("rank_by", match[0].trim(), [value]));
  }

  const focus = parseSymbolListInput(draft.focusSymbolsInput);
  const avoid = parseSymbolListInput(draft.avoidSymbolsInput);
  for (const match of residue.matchAll(TICKER_RUN_RE)) {
    const tickers = match[0]
      .split(",")
      .map((s) => s.trim())
      .filter((s) => s.length > 0 && !NOT_TICKERS.has(s));
    if (tickers.length < 2) continue;
    if (tickers.every((t) => focus.includes(t) || avoid.includes(t))) continue;
    push(buildWarning("focus_symbols", match[0].trim(), tickers));
  }

  return warnings;
}
