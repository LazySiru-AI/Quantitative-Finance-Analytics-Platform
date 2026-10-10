/**
 * Cross-institution consensus: what tracked funds are buying and selling right now, ranked by how
 * many of them moved the same CUSIP the same direction since each fund's own last filing.
 *
 * Built against `@/api/consensus`'s already-fixed contract -- see that module's docstring for the
 * four things a naive "N funds bought X" headline would otherwise hide. This component's whole job
 * is to keep those four honest on screen rather than let the ranked tables read as more certain than
 * the underlying filings are:
 *
 *  1. `checked`/`unchecked` are rendered in `ProvenanceStrip`, always, in every non-error phase --
 *     never buried behind a click a reader has no reason to make. `ConsensusTable` repeats the
 *     `checked.length` denominator immediately above its own counts, because a reader who scrolled
 *     straight to the table without reading the strip above still needs it.
 *  2. Every mover in the `Collapsible` drill-down under each row shows its own `period` -- see
 *     `MoversList` -- because two movers on the same CUSIP can be filing for different quarters.
 *  3. Every mover shows its own `source` badge (13F vs NPORT) rather than folding both regimes into
 *     one undifferentiated count.
 *  4. The staleness caveat sits in a `.disclaimer` panel directly under the headline, before any
 *     data renders, matching where `Institutions.tsx` places its own equivalent -- so a reader
 *     cannot reach the ranked tables without passing it first.
 *
 * Phase state machine and fetch/error shape mirror `Institutions.tsx`: `"loading" | "loaded" |
 * "empty" | "error"`, each rendering a distinct, honest state rather than a shared spinner or blank
 * panel standing in for all four.
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiRequestError } from "@/api/client";
import {
  consensusApi,
  type ConsensusResponse,
  type ConsensusRow,
  type FundMove,
} from "@/api/consensus";
import { formatSharesPctChange, formatSignedShares } from "@/api/institutions";
import Collapsible from "@/components/Collapsible";
import Fetched from "@/components/Fetched";
import { ScrollRegion } from "@/components/ScrollPanel";
import { Skeleton } from "@/components/Skeleton";
import StatusPill from "@/components/StatusPill";
import { FilterBar, TableCaption } from "@/components/tableSort";
import { useFetch } from "@/hooks/useFetch";
import { Trans, useT, type MessageKey, type Translator } from "@/i18n";
import { ACTION_LABEL_KEY, IssuerCell } from "@/pages/filers/shared";

import "./Consensus.css";

type View = "buys" | "sells";

/** Placeholder row count for the cold-load `Skeleton`, sized to roughly fill the panel a loaded
 *  ranked table would occupy -- not a claim about how many rows will actually come back. There is
 *  no real progress figure to show here: the walk across tracked filers happens entirely inside one
 *  backend request/response, so this page never learns "N of 22 checked so far" mid-flight the way
 *  `Skeleton`'s `progress` prop is built for -- only the final `checked`/`unchecked` counts, which
 *  arrive at the same moment as everything else. */
const CONSENSUS_SKELETON_ROWS = 8;

// `ACTION_LABEL_KEY` and `IssuerCell` now live in `@/pages/filers/shared`, shared with
// `Institutions.tsx` -- this page used to keep an independent copy of both, byte-identical in
// English and Korean (finding E1 in the Filers merge task); see that module's docstring.

/** Turns a caught fetch failure into display copy. Mirrors `describeFetchError` in
 *  `Institutions.tsx`: the consensus endpoint hits the same live, SEC-derived pipeline and can fail
 *  the same three ways. */
function describeFetchError(t: Translator, e: unknown): string {
  if (e instanceof ApiRequestError) {
    if (e.status === 502 || e.status === 503) {
      return t("market.consensus.error.upstreamUnreachable", { status: e.status });
    }
    return t("market.consensus.error.apiError", { status: e.status, message: e.message });
  }
  return t("market.consensus.error.cannotReachApi");
}

/**
 * The Consensus tab body: the staleness disclaimer, the cross-link to Institutions, and the
 * cold-load fetch/phase machine feeding `ConsensusContent`. Exported (as of the Filers merge, UX
 * refactor 2.2) so `Filers.tsx` can mount it as the "Consensus" tab's content without a second
 * `<h1>`/subtitle -- `Filers.tsx` supplies the shared banner for the merged page; this component
 * supplies everything below it, unchanged from what `Consensus()` (below) has always rendered there.
 */
export function ConsensusView() {
  const { t } = useT();
  const [view, setView] = useState<View>("buys");
  // Deliberately `[]` deps, matching `Portfolio.tsx`'s own fetch effect: this runs once at mount, and
  // `formatError` translates in whichever language is active when the request actually fails.
  const result = useFetch<ConsensusResponse>((signal) => consensusApi.get({}, signal), [], {
    formatError: (e) => describeFetchError(t, e),
  });

  return (
    <>
      {/* Honesty requirement 4: the staleness caveat, plain, near the headline, before any ranked
          data can render -- so a reader cannot reach the tables without passing it first. */}
      <div className="panel disclaimer" role="note">
        <StatusPill
          tone="warn"
          label={t("ui.pill.filingLag")}
          detail={t("market.consensus.disclaimer.body")}
        />{" "}
        <strong>{t("market.consensus.disclaimer.lead")}</strong>{" "}
        {t("market.consensus.disclaimer.body")}
      </div>

      {/* Institutions <-> Consensus cross-link (`nav.ts` already declares the two adjacent).
          Rendered in every phase, same as the disclaimer above -- a reader who lands here wanting
          one filer's own book, not the cross-fund ranking, should not have to wait for this page's
          slow cold-cache walk to finish before finding the door out. Points at `/filers` (the merged
          page's By-filer tab) rather than the old `/institutions` path: that route still resolves,
          but only as a redirect, and a link that costs the reader an extra hop is a link that will
          eventually cost them the page when the redirect is retired. */}
      <p className="muted">
        <Trans
          k="market.consensus.crossLink"
          values={{ link: <Link to="/filers">{t("market.consensus.crossLink.linkText")}</Link> }}
        />
      </p>

      <Fetched
        state={result}
        loading={
          <div className="panel">
            <Skeleton
              variant="rows"
              rows={CONSENSUS_SKELETON_ROWS}
              what={t("market.consensus.noun.filers")}
            />
          </div>
        }
        error={(message) => (
          <div className="panel">
            <div className="placeholder">{message}</div>
          </div>
        )}
        isEmpty={(d) => d.buys.length === 0 && d.sells.length === 0}
        empty={(d) => (
          <>
            <ProvenanceStrip data={d} />
            <div className="panel">
              <div className="placeholder">{t("market.consensus.empty")}</div>
            </div>
          </>
        )}
      >
        {(data) => <ConsensusContent data={data} view={view} onViewChange={setView} />}
      </Fetched>
    </>
  );
}

/** Cross-institution consensus: what tracked funds are buying and selling right now.
 *
 *  Standalone page chrome (`<h1>`/subtitle) plus `ConsensusView` above. Kept as the route's default
 *  export for now -- the orchestrator removes this once `/consensus` redirects to `/filers`, per the
 *  Filers merge task's scope fence. */
export default function Consensus() {
  const { t } = useT();
  return (
    <>
      <h1>{t("market.consensus.title")}</h1>
      <p className="subtitle">{t("market.consensus.subtitle")}</p>
      <ConsensusView />
    </>
  );
}

function ConsensusContent({
  data,
  view,
  onViewChange,
}: {
  data: ConsensusResponse;
  view: View;
  onViewChange: (view: View) => void;
}) {
  const { t } = useT();
  const rows = view === "buys" ? data.buys : data.sells;

  return (
    <>
      <ProvenanceStrip data={data} />

      <div className="panel consensus-view-panel">
        <div className="view-tabs" role="tablist" aria-label={t("market.consensus.tabs.ariaLabel")}>
          <button
            type="button"
            role="tab"
            aria-selected={view === "buys"}
            className={`timeframe-tab${view === "buys" ? " active" : ""}`}
            onClick={() => onViewChange("buys")}
          >
            {t("market.consensus.tabs.buying")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "sells"}
            className={`timeframe-tab${view === "sells" ? " active" : ""}`}
            onClick={() => onViewChange("sells")}
          >
            {t("market.consensus.tabs.selling")}
          </button>
        </div>
      </div>

      <ConsensusTable rows={rows} view={view} checkedCount={data.checked.length} />
    </>
  );
}

/**
 * Honesty requirement 1, rendered where a reader cannot avoid it: `generated_at`, the `checked`
 * count against the full tracked universe (`checked.length + unchecked.length`), and the unchecked
 * funds themselves with their reasons. Rendered once per non-error phase (`ConsensusContent` for
 * `"loaded"`, `Consensus` itself for `"empty"`) rather than folded into either -- so an empty result
 * still shows a reader exactly what was and was not measured, instead of reading as "nothing to
 * report" with no way to tell that from "6 of 22 funds failed to load."
 */
function ProvenanceStrip({ data }: { data: ConsensusResponse }) {
  const { t } = useT();
  const total = data.checked.length + data.unchecked.length;
  const hasAsOf = data.as_of != null;
  const hasUnchecked = data.unchecked.length > 0;
  // One full sentence per combination of (as_of present?) x (unchecked present?) -- the Korean word
  // order for "generated ... as of ..." and for the trailing "N could not be compared" clause both
  // differ from English, so each shape gets its own catalog entry rather than being reassembled
  // from fragments around the two conditionals. See `messages/portfolio.ts`'s module docstring for
  // the same rule applied to its own multi-variant sentences.
  const provenanceKey: MessageKey =
    hasAsOf && hasUnchecked
      ? "market.consensus.provenance.withAsOfAndUnchecked"
      : hasAsOf
        ? "market.consensus.provenance.withAsOf"
        : hasUnchecked
          ? "market.consensus.provenance.withUnchecked"
          : "market.consensus.provenance.base";

  return (
    <section className="panel consensus-provenance">
      <p className="muted consensus-provenance-line">
        <Trans
          k={provenanceKey}
          values={{
            generatedAt: <strong>{data.generated_at}</strong>,
            asOf: <strong>{data.as_of}</strong>,
            checkedOfTotal: (
              <strong>
                {data.checked.length} of {total}
              </strong>
            ),
            uncheckedCount: <strong>{data.unchecked.length}</strong>,
          }}
        />
      </p>

      {data.unchecked.length > 0 && (
        <Collapsible
          title={
            <span className="consensus-unchecked-title">
              {t("market.consensus.uncheckedTitle", { count: data.unchecked.length })}
            </span>
          }
          defaultOpen={false}
          className="consensus-unchecked"
        >
          <ScrollRegion size="md" label={t("market.consensus.uncheckedTitle", { count: data.unchecked.length })}>
            <ul className="consensus-unchecked-list">
              {data.unchecked.map((u) => (
                <li key={u.key}>
                  <strong>{u.name}</strong> <span className="muted">({u.key})</span> -- {u.reason}{" "}
                  {/* `u.reason` is backend-written diagnostic text (e.g. an exception message), not
                      UI copy this shard owns -- it stays English regardless of `lang`, and the badge
                      says so plainly rather than leaving a Korean reader to wonder why. */}
                  <span className="badge" title={t("common.sourceEnglishTitle")}>
                    {t("common.sourceEnglish")}
                  </span>
                </li>
              ))}
            </ul>
          </ScrollRegion>
        </Collapsible>
      )}
    </section>
  );
}

function ConsensusTable({
  rows,
  view,
  checkedCount,
}: {
  rows: ConsensusRow[];
  view: View;
  checkedCount: number;
}) {
  const { t } = useT();
  // Live issuer/ticker substring filter (1.10) -- `rows` is already the whole ranked list for this
  // `view` (buys or sells), never paginated, so this filters client-side over the full set rather
  // than one page of it. Reset is implicit: switching `view` remounts nothing here, but a rank list
  // for the OTHER direction rarely shares the same issuer a reader was just searching for, so the
  // query is deliberately kept rather than cleared on that switch -- same as `Activity.tsx`'s own
  // symbol filter surviving its `tradesOnly` toggle.
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const filteredRows = q
    ? rows.filter(
        (row) => row.issuer.toLowerCase().includes(q) || (row.ticker ?? "").toLowerCase().includes(q),
      )
    : rows;
  const heading =
    view === "buys" ? t("market.consensus.table.mostBought") : t("market.consensus.table.mostSold");

  return (
    <section className="panel">
      <h2>{heading}</h2>
      <p className="muted consensus-denominator">
        <Trans
          k="market.consensus.table.denominator"
          values={{ checkedCount: <strong>{checkedCount}</strong> }}
        />
      </p>

      {rows.length === 0 ? (
        <div className="placeholder">
          {view === "buys"
            ? t("market.consensus.table.noBuyConsensus")
            : t("market.consensus.table.noSellConsensus")}
        </div>
      ) : (
        <>
          <FilterBar
            query={query}
            onQueryChange={setQuery}
            queryPlaceholder={t("tax.disposals.filterPlaceholder")}
            shown={filteredRows.length}
            total={rows.length}
          />
          {filteredRows.length === 0 ? (
            // Reused from `Activity.tsx` -- no dedicated "no rows match this filter" string exists
            // for Consensus's own rows, and `i18n/catalog.ts` (where one would be added) is out of
            // this task's scope fence. The wording is generic enough ("match these filters") to read
            // correctly here despite naming "transactions" nowhere in it.
            <div className="placeholder">{t("activity.empty.filtered")}</div>
          ) : (
            <ScrollRegion size="md" label={heading}>
              <div className="table-wrap">
              <table className="data-table consensus-table">
                <TableCaption
                  caption={t("market.consensus.table.caption", { heading, count: filteredRows.length })}
                />
                <thead>
                  <tr>
                    <th scope="col">{t("market.consensus.header.rank")}</th>
                    <th scope="col">{t("market.consensus.header.issuer")}</th>
                    <th scope="col" className="num">
                      {view === "buys"
                        ? t("market.consensus.header.fundsBuying")
                        : t("market.consensus.header.fundsSelling")}
                    </th>
                    <th scope="col" className="num">
                      {t("market.consensus.header.weightDeltaSummed")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {/* `rank` is this row's position in the FULL ranked list, not its index in the
                      filtered one -- a reader searching for one issuer must still see "#7", not a
                      renumbered "#1", or the rank would silently mean something different filtered
                      than it does on the unfiltered table right above this state. */}
                  {filteredRows.map((row) => (
                    <ConsensusRowGroup
                      key={row.cusip}
                      rank={rows.indexOf(row) + 1}
                      row={row}
                      view={view}
                    />
                  ))}
                </tbody>
              </table>
              </div>
            </ScrollRegion>
          )}
        </>
      )}
    </section>
  );
}

/**
 * One CUSIP's ranked row plus its expandable mover detail. Two `<tr>`s, not one -- `Collapsible`
 * renders a `<details>`, which cannot itself be a table row, so the drill-down lives in a second row
 * whose single cell spans every column, matching the sibling-row pattern this codebase already uses
 * for `<details>`-in-a-table elsewhere (e.g. the empty-accounts disclosure in `Portfolio.tsx`).
 */
function ConsensusRowGroup({
  rank,
  row,
  view,
}: {
  rank: number;
  row: ConsensusRow;
  view: View;
}) {
  const { t } = useT();
  const count = view === "buys" ? row.buyer_count : row.seller_count;
  return (
    <>
      <tr>
        <td className="num">{rank}</td>
        <td>
          <IssuerCell issuer={row.issuer} ticker={row.ticker} />
        </td>
        <td className="num">{count}</td>
        <td className="num">{formatSharesPctChange(row.total_weight_delta)}</td>
      </tr>
      <tr className="consensus-movers-row">
        <td colSpan={4}>
          <Collapsible
            title={
              <span className="consensus-movers-title">
                {t("market.consensus.moversTitle", { count: row.movers.length })}
              </span>
            }
            defaultOpen={false}
          >
            <MoversList movers={row.movers} />
          </Collapsible>
        </td>
      </tr>
    </>
  );
}

/**
 * Honesty requirements 2 and 3 in one place: every mover shows its own filing `period` (never a
 * shared date for the row -- two movers on the same CUSIP can be filing for different quarters) and
 * its own `source` (13F vs NPORT are different regimes over different portfolios, never blended into
 * one count).
 */
function MoversList({ movers }: { movers: FundMove[] }) {
  const { t } = useT();
  return (
    <ul className="consensus-movers-list">
      {movers.map((m) => (
        <li key={`${m.key}-${m.period}`} className="consensus-mover-row">
          {/* The principal leads where one exists, matching `Institutions.tsx`'s fund selector --
              "Cathie Wood" is findable, "ARK Investment Management LLC" alone often is not. The firm
              name is never dropped; it always follows. */}
          <span className="consensus-mover-name">
            {m.principal ? `${m.principal} — ${m.name}` : m.name}
          </span>
          <span className={`badge consensus-action-${m.action}`}>{t(ACTION_LABEL_KEY[m.action])}</span>
          <span
            className="badge consensus-source-badge"
            title={
              m.source === "13F"
                ? t("market.consensus.mover.tooltip13F")
                : t("market.consensus.mover.tooltipNport")
            }
          >
            {m.source}
          </span>
          <span className="consensus-mover-weight">{formatSharesPctChange(m.weight_delta)}</span>
          <span className="consensus-mover-shares">{formatSignedShares(m.shares_delta)}</span>
          <span className="muted consensus-mover-period">
            {t("market.consensus.mover.asOf", { period: m.period })}
          </span>
        </li>
      ))}
    </ul>
  );
}

// `IssuerCell` now lives in `@/pages/filers/shared` (imported above) -- see that module's docstring.
