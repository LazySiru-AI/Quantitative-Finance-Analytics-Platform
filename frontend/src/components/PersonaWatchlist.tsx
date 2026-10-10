/**
 * The cross-persona bullish watchlist -- every symbol currently backed by at least one followed
 * influencer, ranked by how many personas back it. Sits alongside `PersonaRegime.tsx` as the two
 * cross-persona consensus panels on `/personas`, both fed by `@/api/personas`'s `watchlist`/`regime`
 * endpoints.
 *
 * **Presentational only -- this component fetches nothing.** The page owns fetching
 * `GET /watchlist`, the point-in-time `asOf` filter value, and re-fetching when it changes;
 * `state` is the discriminated union below so "still loading" / "the fetch actually failed" is
 * never confused with a loaded (possibly empty) watchlist -- the same split `PersonaScorecard.tsx`
 * uses for `ScorecardFetchState`.
 *
 * This file exists to enforce the product guardrails, not merely style them:
 *
 * 1. **Entries render in backend order, never re-sorted here.** The backend already ranks by
 *    backing count; re-sorting client-side would silently diverge from that ranking the moment the
 *    tie-break rule changes server-side. The live symbol filter below (`FilterBar`, same live-as-
 *    you-type contract as `ByInstrumentView.tsx`'s own symbol filter) only narrows which of
 *    `entries` render -- it is a `.filter()` over the backend's array, never a `.sort()`, so the
 *    relative order of whatever remains visible is untouched.
 * 2. **`entries: []` renders an empty note, not an error and not a loading spinner.** "No symbol is
 *    currently backed" is a valid, real answer.
 * 3. **`latest_reasoning` renders verbatim.** It is the influencer's own paraphrase, not summarised
 *    or truncated further here.
 * 4. **Non-equity symbols get an `InstrumentBadge`; plain equities get none.** `InstrumentBadge`
 *    itself already encodes "equity renders nothing" -- this component just passes `instrument`
 *    through unconditionally.
 * 5. **`caveat` always renders, whenever a watchlist is loaded** -- "descriptive reference, never a
 *    buy list" -- regardless of whether `entries` is empty.
 * 6. **The `asOf` date filter is a controlled input the page owns.** This component never tracks its
 *    own copy of the filter value: it renders `props.asOf` and calls `props.onAsOfChange` on
 *    change, clearing the native date input maps to `null` ("latest").
 * 7. **Each symbol links to `/symbol/{symbol}`**, matching `PersonaScorecard.tsx`'s ticker chips.
 * 8. **`latest_reasoning` is marked as what it is** (EXP-08). It is model-written prose that
 *    attributes a view to a named real person, so the column carries a `Model summary` pill and the
 *    panel carries one line saying it is a summary of a dated note, not a quote and not a position.
 *    Each row prints the date of the note it came from (`entry.as_of`); rows with no date say so
 *    rather than borrowing the panel's. **No source link is rendered because the wire has none** --
 *    `WatchlistEntry` carries no URL and no video id (see `@/api/personas`), and a fabricated link
 *    would be worse than an absent one. If the backend ever adds one, this is where it goes.
 * 9. **Backer handles resolve to display names when the caller supplies the map** (`personaNames`).
 *    The wire sends slugs; an unmapped slug still renders verbatim rather than being dropped.
 *
 * Internationalised through `personaConsensus.watchlist.*`; numbers stay in en-US formatting (plain
 * counts, not currency) and `latest_reasoning` is never routed through `t()`.
 */
import { useMemo, useState, type JSX } from "react";

import { Link } from "react-router-dom";

import type { InfluencerWatchlist, WatchlistEntry } from "@/api/personas";
import { InstrumentBadge } from "@/components/InstrumentBadge";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill from "@/components/StatusPill";
import { FilterBar } from "@/components/tableSort";
import { useT } from "@/i18n";
import type { Language } from "@/i18n/types";
import { localeTag } from "@/i18n/useT";

import "./PersonaConsensus.css";

/**
 * A wire timestamp as a readable local date, plus `HH:MM` when the value actually carries a time
 * (EXP-14 -- the panel used to print `2026-09-10T04:31:07.884512Z` verbatim).
 *
 * There is no shared date formatter in `@/format` to reuse: it holds money helpers only, and the two
 * existing date helpers (`api/macro.ts`'s `formatObservationDate`, `api/calendar.ts`'s) both exist
 * specifically to force a *bare* `YYYY-MM-DD` through UTC so it does not shift a day west of
 * Greenwich. Neither renders a time, which is the whole requirement here, so this formats locally
 * instead of bending one of them.
 *
 * A bare date takes the same UTC-pinned path those two helpers take, for the same reason: `new
 * Date("2026-09-10")` is midnight UTC, and printing it locally shows the 9th in New York.
 */
export function formatWatchlistAsOf(value: string, lang: Language): string | null {
  const bare = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (bare) {
    const [, y, m, d] = bare;
    return new Date(Date.UTC(Number(y), Number(m) - 1, Number(d))).toLocaleDateString(localeTag(lang), {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  const date = parsed.toLocaleDateString(localeTag(lang), {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
  // `hour12: false` on purpose: the requirement is HH:MM, and an "AM"/"PM" suffix is one more token
  // in a cell that exists to be glanced at.
  const time = parsed.toLocaleTimeString(localeTag(lang), {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  return `${date} ${time}`;
}

/** Distinguishes "still loading" / "the fetch actually failed" from a loaded (possibly empty)
 * watchlist. The page is the only producer. */
export type WatchlistState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "loaded"; watchlist: InfluencerWatchlist };

export interface PersonaWatchlistProps {
  state: WatchlistState;
  /** Current as_of filter value (YYYY-MM-DD) or null for "latest". */
  asOf: string | null;
  onAsOfChange: (asOf: string | null) => void;
  /** Backing-handle -> display name, when the caller has the persona list (EXP-08). An unmapped
   * handle renders verbatim; omitting the prop entirely renders every handle verbatim. */
  personaNames?: Record<string, string> | undefined;
}

export default function PersonaWatchlist({
  state,
  asOf,
  onAsOfChange,
  personaNames,
}: PersonaWatchlistProps): JSX.Element {
  const { t } = useT();

  return (
    <div className="panel persona-watchlist">
      <div className="persona-watchlist-header">
        <div>
          <h3 className="persona-card-subhead">{t("personaConsensus.watchlist.heading")}</h3>
          <p className="muted persona-watchlist-subtitle">{t("personaConsensus.watchlist.subtitle")}</p>
        </div>
        <label className="persona-watchlist-asof-field">
          <span className="persona-watchlist-asof-label">{t("personaConsensus.watchlist.asOfInputLabel")}</span>
          <input
            type="date"
            value={asOf ?? ""}
            onChange={(event) => onAsOfChange(event.target.value === "" ? null : event.target.value)}
          />
        </label>
      </div>

      {state.phase === "loading" && (
        <div className="placeholder persona-watchlist-loading">{t("personaConsensus.watchlist.loading")}</div>
      )}

      {state.phase === "error" && (
        <div className="callout callout-danger persona-watchlist-error" role="alert">
          {state.message}
        </div>
      )}

      {state.phase === "loaded" && (
        <WatchlistBody watchlist={state.watchlist} personaNames={personaNames} />
      )}
    </div>
  );
}

function WatchlistBody({
  watchlist,
  personaNames,
}: {
  watchlist: InfluencerWatchlist;
  personaNames: Record<string, string> | undefined;
}) {
  const { t, lang } = useT();
  const { entries, caveat, as_of } = watchlist;
  // Live, client-side only -- `entries` is already the whole (typically short) fetched list, so
  // there is no server round-trip to debounce, matching `ByInstrumentView.tsx`'s own symbol filter
  // over an already-fetched `report.positions`. See the module docstring's rule 1 note: this
  // narrows `entries`, it never reorders them.
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((entry) => entry.symbol.toLowerCase().includes(q));
  }, [entries, query]);

  return (
    <div className="persona-watchlist-body">
      {/* EXP-14: `as_of` is a `dt.datetime` on the wire, so it arrives as an ISO string with
          microseconds and a zone designator. Formatted, never printed raw. */}
      <p className="muted persona-watchlist-asof-note">
        {t("personaConsensus.watchlist.asOfNote", {
          asOf: formatWatchlistAsOf(as_of, lang) ?? t("personaConsensus.watchlist.asOfUnknown"),
        })}
      </p>
      {/* Rule 5: always rendered, whenever a watchlist is loaded -- independent of `entries.length`. */}
      <p className="muted persona-watchlist-caveat">{caveat}</p>
      {/* Rule 8 (EXP-08): the reasoning column is a model's prose about named real people. Say so
          once, in the open, next to the pill that marks the column itself. */}
      <p className="muted persona-watchlist-summary-note" data-testid="watchlist-summary-note">
        <StatusPill tone="info" label={t("personaConsensus.pill.modelSummary")} />{" "}
        {t("personaConsensus.watchlist.summaryNote")}
      </p>

      {entries.length === 0 ? (
        <p className="muted persona-watchlist-empty">{t("personaConsensus.watchlist.empty")}</p>
      ) : (
        <>
          <FilterBar
            query={query}
            onQueryChange={setQuery}
            queryPlaceholder={t("personaConsensus.watchlist.filterPlaceholder")}
            shown={filtered.length}
            total={entries.length}
          />
          {filtered.length === 0 ? (
            <p className="muted persona-watchlist-empty">{t("personaConsensus.watchlist.noMatch")}</p>
          ) : (
            <ScrollRegion size="md" label={t("personaConsensus.watchlist.heading")}>
              <div className="table-wrap">
                <table className="data-table persona-watchlist-table">
                  <thead>
                    <tr>
                      <th>{t("personaConsensus.watchlist.columnSymbol")}</th>
                      <th className="num">{t("personaConsensus.watchlist.columnBullish")}</th>
                      <th className="num">{t("personaConsensus.watchlist.columnBearish")}</th>
                      <th>{t("personaConsensus.watchlist.columnBackers")}</th>
                      <th>
                        {t("personaConsensus.watchlist.columnReasoning")}{" "}
                        <StatusPill tone="info" label={t("personaConsensus.pill.modelSummary")} />
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((entry) => (
                      <WatchlistRow key={entry.symbol} entry={entry} personaNames={personaNames} />
                    ))}
                  </tbody>
                </table>
              </div>
            </ScrollRegion>
          )}
        </>
      )}
    </div>
  );
}

/** Rule 1: rendered in the order the backend sent -- no client-side sort. */
function WatchlistRow({
  entry,
  personaNames,
}: {
  entry: WatchlistEntry;
  personaNames: Record<string, string> | undefined;
}) {
  const { t, lang } = useT();
  // Rule 9: resolve when the caller gave us a name for the handle, else print the handle. Never
  // drop a backer this build cannot name -- the count above it would then not add up.
  const backers = entry.personas.map((handle) => personaNames?.[handle] ?? handle).join(", ");
  // Rule 8: the date of the note this prose came from. `as_of` is `dt.datetime | None` on the wire.
  const noted = entry.as_of === null ? null : formatWatchlistAsOf(entry.as_of, lang);

  return (
    <tr className="persona-watchlist-row">
      <td className="persona-watchlist-symbol-cell">
        <Link className="persona-ticker-chip" to={`/symbol/${encodeURIComponent(entry.symbol)}`}>
          <span className="position-symbol">{entry.symbol}</span>
        </Link>
        <InstrumentBadge instrument={entry.instrument} />
      </td>
      <td className="num persona-watchlist-bullish">{entry.bullish_count}</td>
      <td className="num persona-watchlist-bearish">{entry.bearish_count}</td>
      <td className="persona-watchlist-backers">{backers}</td>
      <td className="persona-watchlist-reasoning">
        {entry.latest_reasoning}
        {/* A `div` rather than a `span`: this belongs on its own line under the prose, and block
            layout is the default -- no stylesheet edit needed to get it (`PersonaConsensus.css` is
            not this task's to touch). */}
        <div className="muted persona-watchlist-provenance">
          {noted === null
            ? t("personaConsensus.watchlist.noteUndated")
            : t("personaConsensus.watchlist.noteDated", { date: noted })}
        </div>
      </td>
    </tr>
  );
}
