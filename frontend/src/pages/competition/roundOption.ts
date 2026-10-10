/**
 * What a round is called *inside a `<select>`* — one shape, derived, for every round picker on the
 * Competition page.
 *
 * The pickers used to print `RoundSummary.label` verbatim, and `label` is authored per round by
 * whoever ran it. One live picker held all four of these at once:
 *
 *     r48 — Sep 2026
 *     Round 15 - three accounts, one ledger; does the split change anything?
 *     rerun — Aug 2026
 *     r46 — Sep 2026 — no scored results
 *
 * Four naming schemes, two of them carrying a whole essay title, one carrying a status marker in its
 * text. A `<select>` is a list a reader scans to *find a round*; a sentence per option is a list they
 * have to read instead. So the option text is derived from the round's own id — the one field with a
 * guaranteed shape — and the title moves out to a line under the select, where it can be as long as
 * it likes without widening the control or hiding the option next to it.
 *
 * `round_id` is `<token>-<yyyy>-<mm>` (`r48-2026-09`), which renders `r48 · Sep 2026`. The token is
 * kept verbatim rather than re-derived from `sequence`: an id like `rerun-2026-08` has no ordinal
 * (`sequence` is `-1` for it) and is still a round a reader picks by name. Anything that does not
 * parse falls back to the id itself — never to `label`, which is the thing this exists to keep out.
 *
 * The month goes through `toLocaleDateString` with the active language's tag, per this app's date
 * rule (see `api/calendar.ts` and `i18n/useT.ts`): dates are locale-formatted, not translated, so
 * this needs no catalog keys of its own and cannot drift out of sync with a hand-written month list.
 * `Date.UTC` for the same reason every other date helper here uses it — a bare `new Date("2026-09")`
 * read back west of Greenwich is August.
 */
import { localeTag, type Language } from "@/i18n";

/** `<token>-<yyyy>-<mm>`. The token is anything up to the trailing year-month, so `r48`, `rerun` and
 *  `r5-ladder` all keep whatever they are actually called. */
const ROUND_ID_RE = /^(.+)-(\d{4})-(\d{2})$/;

/** `2026`, `9` -> `Sep 2026` (`2026년 9월` under `ko`). */
export function formatRoundMonth(year: number, month: number, lang: Language): string {
  return new Date(Date.UTC(year, month - 1, 1)).toLocaleDateString(localeTag(lang), {
    year: "numeric",
    month: "short",
    timeZone: "UTC",
  });
}

/**
 * The `<option>` text for one round: `r48 · Sep 2026`.
 *
 * Takes the id rather than the whole `RoundSummary` so callers with only an id (and the tests) can
 * use it without building a fixture. Returns the id unchanged when it does not carry a year-month.
 */
export function roundOptionText(roundId: string, lang: Language): string {
  const match = ROUND_ID_RE.exec(roundId);
  if (!match) return roundId;
  const [, token, year, month] = match;
  const monthNumber = Number(month);
  if (monthNumber < 1 || monthNumber > 12) return roundId;
  return `${token} · ${formatRoundMonth(Number(year), monthNumber, lang)}`;
}
