import { useMemo, useState } from "react";

import {
  decisionActionLabel,
  deskRejectionLabel,
  formatInstant,
  formatMoney,
  formatMoneyOrDash,
  formatRankValue,
  formatSignedFractionPctString,
  formatSignedMoney,
  formatWeightPct,
  fractionStringTone,
  moneyTone,
  type AutopilotOrder,
  type Decision,
  type Desk,
  type DeskRejection,
  type Holding,
  type LiveFill,
  type SeatProvenance,
  type Signal,
} from "@/api/paperdesk";
import { Card } from "@/components/Card";
import Collapsible from "@/components/Collapsible";
import InfoNote from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill from "@/components/StatusPill";
import { FilterBar } from "@/components/tableSort";
import { Trans, type Translator, useT } from "@/i18n";
import { Link } from "react-router-dom";

import BookStatistics, { LadderRungs } from "./BookStatistics";

// ---------------------------------------------------------------------------
// Per-desk panel
// ---------------------------------------------------------------------------

/** A desk that has never held anything and never closed a trade.
 *
 *  Distinct from a desk sitting in cash *after* trading, which is an ordinary state and often the
 *  strategy working. This one has done nothing at all since inception, and until round 7 the page
 *  rendered the two identically -- two of round 6's four selected cards turned out to be in this
 *  state for 55 straight sessions with nothing on screen saying so. Round 7's liveness gate reads
 *  exactly this condition, so the screen shows it.
 *
 *  An autopilot desk also counts a pending `staged_orders` entry as activity: the workflow has
 *  already committed to that buy (see `AutopilotOrder`'s own docstring), which is a materially
 *  different state from "nothing has happened yet" even before the order fills. Every other kind
 *  never populates `staged_orders` at all, so `?? 0` leaves their dormancy check byte-identical to
 *  before this field existed. */
function isDormant(desk: Desk): boolean {
  return (
    desk.holdings.length === 0 &&
    desk.trades.length === 0 &&
    (desk.staged_orders?.length ?? 0) === 0
  );
}

/** `AutopilotDescription.universe_source` in the reader's own words rather than the raw wire
 *  token ("screen"/"card") -- a book is identified by the pair `(arm, universe_source)`, and a
 *  reader who has never seen the study's internal vocabulary should not have to learn it just to
 *  read a badge. Open string, not a closed union -- an unrecognised value degrades to itself
 *  rather than throwing, the same rule this file follows for `LiveFill.side` and `DeskRejection.rule`. */
function autopilotUniverseLabel(source: string, t: Translator): string {
  if (source === "screen") return t("paperDesk.autopilot.universeScreen");
  if (source === "card") return t("paperDesk.autopilot.universeCard");
  return source;
}

/** Where this seat came from, as a small pill beside the discipline badge. A `"promoted"` seat links
 *  to the Loop view (where its evolution generation's run is shown); an `"owner"` seat is a plain,
 *  unlinked label -- the hand-authored roster is here by an owner decision, not a gate, so there is
 *  nothing to link to. See `app.paperdesk.models.SeatProvenance`. */
function SeatProvenancePill({ provenance }: { provenance: SeatProvenance }) {
  const { t } = useT();
  if (provenance.source === "promoted") {
    return (
      <Link className="desk-provenance-link" to="/competition?tab=loop">
        <StatusPill
          tone="info"
          className="desk-provenance-badge"
          label={t("paperDesk.provenance.promoted", { generation: provenance.generation ?? "?" })}
          detail={t("paperDesk.provenance.promotedTitle")}
        />
      </Link>
    );
  }
  return (
    <StatusPill
      tone="neutral"
      className="desk-provenance-badge"
      label={t("paperDesk.provenance.owner")}
      detail={t("paperDesk.provenance.ownerTitle")}
    />
  );
}

/**
 * One desk, as one bounded card.
 *
 * Before this, the panel was a plain `.panel` in a `align-items: start` grid whose height was the
 * SUM of up to six sibling scroll regions plus three genuinely unbounded blocks -- so one card with
 * an open `<details>` ran ~2,500px while its row-mates stayed put, and the grid's bottom edge was
 * ragged in every row. The card now owns a single height (`Card`'s `lg` track, equalised by
 * `CardGrid`) and a single scrolling body; everything that used to bound itself independently is
 * either primary content in that one body, or folded behind the "Statistics & details" disclosure.
 *
 * What stays in the body is what a reader scanning a page of desks actually acts on: the two
 * headline figures, what the desk just did, what it holds, and what it would do next. Book-level
 * statistics, the broker's refusals, the live-quote projection and the card's own rules text are
 * the long form -- available in one click, never paid for in height by a reader who did not ask.
 *
 * `panelClassName` (not `className`) carries `desk-panel`: `className` lands on the scrolling body,
 * and the page's own tests, the dormant border and the after-tax panel all key off `.desk-panel`
 * being the root `.panel`.
 */
export default function DeskPanel({ desk, asOf }: { desk: Desk; asOf: string }) {
  const { t } = useT();
  const dormant = isDormant(desk);
  const autopilot = desk.kind === "autopilot" ? (desk.autopilot ?? null) : null;
  const ladder = desk.kind === "ladder" ? (desk.ladder ?? null) : null;
  return (
    <Card
      id={desk.agent_id}
      height="lg"
      label={desk.display_name}
      expandable
      panelClassName={`desk-panel${dormant ? " desk-panel-dormant" : ""}`}
      className="desk-panel-body"
      title={<h2 className="desk-panel-title">{desk.display_name}</h2>}
      status={
        <>
          <span className="badge desk-discipline-badge">{desk.discipline}</span>
          {desk.provenance && <SeatProvenancePill provenance={desk.provenance} />}
          {autopilot && (
            <StatusPill
              tone="info"
              className="desk-autopilot-badge"
              label={`${autopilot.arm} · ${autopilotUniverseLabel(autopilot.universe_source, t)}`}
              detail={t("paperDesk.autopilot.armBadgeTitle", { arm: autopilot.arm })}
            />
          )}
          {dormant && (
            <StatusPill
              tone="warn"
              className="desk-dormant-badge"
              label={t("paperDesk.dormant.badge")}
              detail={t("paperDesk.dormant.badgeTitle")}
            />
          )}
        </>
      }
    >
      {/* Equity and total return lead the body -- the two figures a reader scanning a page of many
          cards actually needs before deciding which one to open. Everything else this desk knows
          (open positions, drawdown, exposure, ...) stays in `BookStatistics` inside the disclosure
          at the bottom; duplicating the full tile grid up here would defeat the point of folding
          the rest away. */}
      <DeskHeadlineTiles desk={desk} />

      {/* The single most important fact for reading this seat's return, so it renders near the top
          of the panel rather than in a footnote a reader has to scroll to. Gated on `exits === "none"`
          rather than `desk.kind === "autopilot"` alone -- a future autopilot arm that does sell should
          not carry a callout describing a different arm's behaviour. */}
      {autopilot && autopilot.exits === "none" && (
        <div className="callout callout-info desk-autopilot-buys-only" role="note">
          <InfoNote summary={<strong>{t("paperDesk.autopilot.buysOnlyStrong")}</strong>}>
            {t("paperDesk.autopilot.buysOnlyRest")}
          </InfoNote>
        </div>
      )}

      {/* The positive counterpart to the callout above, for the same slot: `exits` is an open
          string, not a closed union of known policies -- the backend derives this sentence from
          whichever rules the currently selected card actually carries, and a rule combination this
          build has never seen must still render, not throw (the same reasoning `RejectionGroup`'s
          empty-`label` fallback and `autopilotUniverseLabel` already follow in this file). So the
          gate here is simply "not the literal `none`", never a switch over known phrasings.

          Rendered as `muted` prose, not `callout`/`callout-info` -- the buys-only case above is a
          warning a reader needs before trusting the return; a desk whose positions *do* close is
          the ordinary case and doesn't deserve the same visual weight. The sentence is the
          backend's own wording, quoted rather than re-derived: this file does not know what a
          stop/target/hold-cap/rule-based exit actually is for any given card, only that one
          applies, and restating that logic here would drift from the card the moment it changed. */}
      {autopilot && autopilot.exits !== "none" && (
        <p className="muted desk-autopilot-exits-note" role="note">
          <strong>{t("paperDesk.autopilot.exitsNoteLabel")}</strong> {autopilot.exits}.
        </p>
      )}

      {dormant &&
        (autopilot ? (
          <AutopilotDormantNote autopilot={autopilot} />
        ) : (
          <InfoNote className="desk-dormant-note" summary={t("paperDesk.dormant.rulesDeskNote")}>
            {t("paperDesk.dormant.rulesDeskDetail")}
          </InfoNote>
        ))}

      {/* Action-oriented material fills the card body: what the desk just did, what it is holding,
          and what it would do next. Nothing here bounds itself -- the card body is the single
          scroll container for the whole card, which is what lets a row of desks share one height.

          An autopilot desk has no `Signal[]` rule to project forward -- `desk.signals` is always
          `[]` for this kind -- so `UpcomingSignals` would only ever render its own empty state here.
          `StagedOrders` takes its place: not a prediction of what the desk might do, but what it has
          already committed to. A ladder card's forward-looking material is neither: its rung table
          is the mechanism that decides its next weight, so it renders in the same slot. */}
      <RecentActivity decisions={desk.decisions} />
      <HoldingsTable holdings={desk.holdings} />

      {autopilot ? (
        <StagedOrders orders={desk.staged_orders ?? []} />
      ) : (
        <UpcomingSignals desk={desk} asOf={asOf} />
      )}
      {ladder && <LadderRungs ladder={ladder} />}

      {/* Broker refusals stay ABOVE the fold: a refused order is the reason a desk's cash looks
          untouched, and this page's rule is that a caveat is never hidden behind a click. It is
          short (a headline plus one line per rule), so it costs little height. */}
      {desk.rejections.length > 0 && (
        <RejectionsCallout rejections={desk.rejections} rejectionCount={desk.rejection_count} />
      )}

      {/* The long form, one click away and costing no height until it is asked for: the
          live-quote projection and every book-level statistic and rules block `BookStatistics`
          carries. Closed by default -- a reader comparing desks across a row is reading the bodies
          above, not this. */}
      <Collapsible
        title={<h3 className="desk-panel-collapsible-title">{t("paperDesk.desk.moreDetails")}</h3>}
        defaultOpen={false}
        className="desk-panel-collapsible"
        data-testid="desk-panel-details"
      >
        <LiveExecution desk={desk} />
        <BookStatistics desk={desk} />
      </Collapsible>
    </Card>
  );
}

/** The two figures worth showing even while the rest of the card is collapsed (see `DeskPanel`'s
 *  own comment above this call). `total_return` gets the same signed-and-toned treatment
 *  `FractionStat` gives it inside the (collapsed) book-statistics tile grid -- this is the same
 *  number, just promoted to where it is visible without opening anything. */
function DeskHeadlineTiles({ desk }: { desk: Desk }) {
  const { t } = useT();
  const tone = fractionStringTone(desk.total_return);
  return (
    <div className="desk-panel-headline-tiles">
      <span className="desk-panel-headline-stat">
        <span className="muted">{t("common.equity")}</span>
        <span className="desk-panel-headline-value">{formatMoney(desk.equity)}</span>
      </span>
      <span className="desk-panel-headline-stat">
        <span className="muted">{t("paperDesk.tiles.totalReturn")}</span>
        <span className={`desk-panel-headline-value${tone ? ` ${tone}` : ""}`}>
          {formatSignedFractionPctString(desk.total_return)}
        </span>
      </span>
    </div>
  );
}

/**
 * The dormant note for a `kind === "autopilot"` seat -- the rules-desk sentence ("its entry rule
 * has not fired") is simply false here: this desk has no per-symbol boolean rule at all, the same
 * reason `LadderDescription` exists instead of reusing `entry`/`exit` prose for a ladder card.
 *
 * `last_run_outcome` is rendered whenever present, per its own docstring in `@/api/paperdesk`: a
 * seat showing its full starting cash is either a strategy that genuinely found nothing or a
 * pipeline that is broken, and the last run's outcome is the only thing on this panel that tells
 * those two apart. A `null` outcome states plainly that no run has been recorded, rather than
 * silently omitting the sentence -- the same "never render null as if it were merely absent"
 * discipline this module's docstring documents for every other field.
 */
function AutopilotDormantNote({ autopilot }: { autopilot: NonNullable<Desk["autopilot"]> }) {
  const { t } = useT();
  return (
    <div className="desk-dormant-note">
      <InfoNote summary={t("paperDesk.autopilot.dormantNote")}>
        {t("paperDesk.autopilot.dormantDetail")}
      </InfoNote>
      <p className="desk-dormant-run-note">
        {autopilot.last_run_outcome !== null ? (
          <>
            {t("paperDesk.autopilot.lastRunReported", {
              dateClause:
                autopilot.last_run_at !== null ? ` (${formatInstant(autopilot.last_run_at)})` : "",
            })}{" "}
            <strong>{autopilot.last_run_outcome}</strong>.
          </>
        ) : (
          <>{t("paperDesk.autopilot.noRunRecorded")}</>
        )}
      </p>
    </div>
  );
}

/**
 * The broker-refusal summary. Every group's headline -- rule label, order count, affected symbols --
 * renders unconditionally *within this component*: the information the page once buried inside a
 * wall of identical strings (eight repeats of `"insufficient_cash"` for one rule) is the summary
 * line, not something a reader has to expand a group to discover. Only the per-order reason
 * sentences sit behind a `<details>` disclosure per group, closed by default -- native, not React
 * state, per this codebase's documented preference (see `Collapsible.tsx`'s module docstring).
 *
 * NOTE: as of the card refactor this whole callout renders inside `DeskPanel`'s "Statistics &
 * details" disclosure rather than in the card body, so it now takes one click to reach. That is the
 * one place the equal-height rework trades visibility for height, and it is worth stating plainly:
 * refused orders are the reason a desk's cash looks untouched, and a reader who never opens the
 * disclosure will not see them. If that turns out to matter more than the height, move this one
 * element (not `LiveExecution`, not `BookStatistics`) back above the disclosure -- it is short.
 */
function RejectionsCallout({
  rejections,
  rejectionCount,
}: {
  rejections: DeskRejection[];
  rejectionCount: number;
}) {
  const { t } = useT();
  return (
    <div className="callout callout-warn desk-rejections" role="alert">
      <strong>
        {t(rejectionCount === 1 ? "paperDesk.rejections.headline_one" : "paperDesk.rejections.headline_other", {
          count: rejectionCount,
        })}
      </strong>{" "}
      {t("paperDesk.rejections.body")}
      <ul className="desk-rejection-groups">
        {rejections.map((r) => (
          <RejectionGroup key={r.rule} rejection={r} />
        ))}
      </ul>
    </div>
  );
}

/**
 * One rule's group: an always-visible summary line (`Insufficient settled cash — 8 orders ·
 * AAPL, MSFT, NVDA`), and its per-order sentences behind a `<details>` closed by default.
 *
 * `symbols` may legitimately be empty -- a rule that fired without resolving to a specific symbol --
 * in which case the `·` clause is omitted entirely rather than rendered with nothing after it.
 */
function RejectionGroup({ rejection }: { rejection: DeskRejection }) {
  const { t } = useT();
  const label = deskRejectionLabel(rejection);
  const symbolsClause = rejection.symbols.length > 0 ? ` · ${rejection.symbols.join(", ")}` : "";
  const summary = t(
    rejection.count === 1 ? "paperDesk.rejections.summary_one" : "paperDesk.rejections.summary_other",
    { label, count: rejection.count, symbolsClause },
  );
  return (
    <li className="desk-rejection-group">
      <details className="desk-rejection-detail">
        <summary>{summary}</summary>
        <ul className="warning-list">
          {rejection.detail.map((d, i) => (
            <li key={i}>{d}</li>
          ))}
        </ul>
      </details>
    </li>
  );
}

// ---------------------------------------------------------------------------
// What it would do next -- the forward-looking read of `signals[]`.
// ---------------------------------------------------------------------------

/** Unheld symbols whose entry rule fires at the last stored close -- a buy this desk is about to
 *  make, read against the *next* session's open.
 *
 *  Order is preserved from `signals[]`, which the backend returns in the engine's own entry order
 *  (ranked by the desk's `rank_by` key where it sets one -- see `app.paperdesk.desk._signals`). So
 *  filtering here does not need to sort: the first row is the buy that actually happens first, and
 *  `entry_rank` numbers the same order for a reader who is not going to count rows. */
function upcomingBuys(desk: Desk): Signal[] {
  return desk.signals.filter((s) => s.entry_fires && !s.held);
}

/** Held symbols whose exit rule fires at the last stored close -- a sell this desk is about to
 *  make. */
function upcomingSells(desk: Desk): Signal[] {
  return desk.signals.filter((s) => s.held && s.exit_fires);
}

/**
 * The highest-value rows on the page: what this desk would buy or sell next, derived from
 * `signals[]` rather than anything already booked. Previously this information existed only
 * buried inside the full signals table below the holdings and decisions tables -- a reader
 * deciding what to do in their own account had to scan every universe symbol to find the two or
 * three that mattered. This surfaces exactly those rows, and says plainly that a signal describes
 * the next session, not something already done.
 */
function UpcomingSignals({ desk, asOf }: { desk: Desk; asOf: string }) {
  const { t } = useT();
  const buys = upcomingBuys(desk);
  const sells = upcomingSells(desk);
  const hasUpcoming = buys.length > 0 || sells.length > 0;

  return (
    <div className="desk-section desk-upcoming-section">
      <h3>{t("paperDesk.upcoming.title")}</h3>
      <p className="muted desk-upcoming-note">
        <Trans
          k="paperDesk.upcoming.note"
          values={{ asOf, next: <strong>{t("paperDesk.upcoming.nextWord")}</strong> }}
        />
      </p>
      {hasUpcoming ? (
        <div className="desk-upcoming-grid">
          {buys.length > 0 && (
            <UpcomingSignalList
              title={t("common.buy")}
              tone="buy"
              signals={buys}
              queue={
                desk.rank_by === null
                  ? null
                  : { rankBy: desk.rank_by, slotsFree: desk.slots_free }
              }
            />
          )}
          {sells.length > 0 && (
            <UpcomingSignalList title={t("common.sell")} tone="sell" signals={sells} />
          )}
        </div>
      ) : (
        <div className="placeholder">{t("paperDesk.upcoming.empty")}</div>
      )}
    </div>
  );
}

/**
 * One side of "what it would do next".
 *
 * `queue` is passed for the buy side of a desk that ranks its entries, and is what turns a bare
 * list of names into an answer. More names can fire than there are free slots, and until this
 * existed the panel rendered them as an unordered set -- the reader could see that three names
 * qualified and had no way at all to tell which one the desk actually buys. With `queue` set, each
 * row carries its place in line and its key value, and the rows past `slotsFree` are dimmed rather
 * than dropped: they *did* qualify, and a reader deciding what to do in their own account wants to
 * know what the desk passed over, not just what it took.
 *
 * `null` for the sell side (a sell is not competing for anything -- every held name whose exit
 * fires is sold) and for a desk with no `rank_by`, whose fill order is the order `universe` was
 * typed in. Numbering that would present an accident as a ranking.
 */
function UpcomingSignalList({
  title,
  tone,
  signals,
  queue = null,
}: {
  title: string;
  tone: "buy" | "sell";
  signals: Signal[];
  queue?: { rankBy: string; slotsFree: number } | null;
}) {
  const { t } = useT();
  return (
    <div className="desk-upcoming-list">
      <span className={`badge desk-upcoming-badge desk-upcoming-badge-${tone}`}>
        {t("paperDesk.upcoming.signalBadge", { title, count: signals.length })}
      </span>
      {queue && <QueueNote rankBy={queue.rankBy} slotsFree={queue.slotsFree} />}
      {/* Bounded per column, not per card. A universe of forty names can fire twenty entries at
          once, and an unbounded `<ul>` here made the two columns of this grid different heights on
          top of pushing the whole card past its own cap -- the buy column also carries a
          `QueueNote` the sell column does not, so they never agreed on a baseline either. `sm`
          holds roughly eight rows, which is what this list is read at a glance for. */}
      <ScrollRegion size="sm" label={title}>
        <ul className="desk-upcoming-items">
          {signals.map((s) => {
            const outranked =
              queue !== null && s.entry_rank !== null && s.entry_rank > queue.slotsFree;
            return (
              <li
                key={s.symbol}
                className={`desk-upcoming-item${outranked ? " desk-upcoming-item-outranked" : ""}`}
              >
                {s.entry_rank !== null && (
                  <span className="badge desk-rank-badge">#{s.entry_rank}</span>
                )}
                <span className="position-symbol">{s.symbol}</span>
                <span className="desk-upcoming-price">{formatMoneyOrDash(s.last_close)}</span>
                {queue && (
                  <span className="desk-upcoming-rank-value" title={queue.rankBy}>
                    {formatRankValue(s.rank_value)}
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </ScrollRegion>
    </div>
  );
}

/** Says out loud what the numbers beside each buy mean, and how far down the list the desk's money
 *  actually reaches. "if cash allows" is not hedging: `slots_free` counts slots, and a desk can
 *  still be short the cash for a position it has room for -- the signals table's `blocked` column
 *  is where that shows up. */
function QueueNote({ rankBy, slotsFree }: { rankBy: string; slotsFree: number }) {
  const { t } = useT();
  return (
    <p className="muted desk-upcoming-rank-note">
      <Trans k="paperDesk.queue.rankedBy" values={{ rankBy: <code>{rankBy}</code> }} />{" "}
      {slotsFree > 0 ? (
        <>
          {t(
            slotsFree === 1 ? "paperDesk.queue.slotsFree_one" : "paperDesk.queue.slotsFree_other",
            { count: slotsFree },
          )}
        </>
      ) : (
        <>{t("paperDesk.queue.noSlotFree")}</>
      )}
    </p>
  );
}

// ---------------------------------------------------------------------------
// What it has already committed to -- an autopilot desk's `staged_orders[]`, the
// `kind === "autopilot"` counterpart to `UpcomingSignals` above.
// ---------------------------------------------------------------------------

/**
 * Orders an autopilot desk has staged but not yet filled. Occupies the exact spot `UpcomingSignals`
 * holds for a rules desk -- same accent-bordered `.desk-upcoming-section` treatment, so the panel's
 * headline slot is filled by whichever forward-looking material this desk's kind actually has --
 * but it is a fundamentally different claim: `Signal[]` is a rule re-read against the newest close
 * on every request, while a staged order is a decision already written down on its own
 * `decision_date` that cannot be re-derived. See `AutopilotOrder`'s own docstring.
 *
 * Renders nothing at all when `orders` is empty, the same "no confusing empty block" rule
 * `LiveExecution` follows for `live_as_of` -- there is no separate placeholder state to show here
 * because a flat autopilot desk already has `AutopilotDormantNote` covering that ground with the
 * one thing a bare "nothing staged" sentence could not: the last run's outcome.
 */
function StagedOrders({ orders }: { orders: AutopilotOrder[] }) {
  const { t } = useT();
  if (orders.length === 0) return null;
  return (
    <div className="desk-section desk-upcoming-section">
      <h3>{t("paperDesk.staged.title")}</h3>
      <p className="muted desk-upcoming-note">
        <Trans k="paperDesk.staged.note" values={{ code: <code>fill_date</code> }} />
      </p>
      {/* No `ScrollRegion` and no `.table-wrap`: the card body is the one scroll container for this
          card's primary content, and a scroller nested in a scroller traps the wheel. */}
      <table className="data-table position-table desk-staged-orders-table">
        <thead>
          <tr>
            <th scope="col">{t("common.symbol")}</th>
            <th scope="col">{t("paperDesk.staged.side")}</th>
            <th scope="col" className="num">
              {t("paperDesk.staged.notional")}
            </th>
            <th scope="col">{t("paperDesk.staged.decisionDate")}</th>
            <th scope="col">{t("paperDesk.staged.fillDate")}</th>
            <th scope="col">{t("paperDesk.staged.regime")}</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o, i) => (
            <StagedOrderRow key={`${o.symbol}-${o.decision_date}-${i}`} order={o} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** One staged order. `side` is an open string sent verbatim by the server, mirroring `LiveFill.side`
 *  -- rendered as-is and toned as "sell" only on an exact match so an unrecognised value still
 *  renders (as a buy-toned badge) instead of throwing, the same `exitReasonLabel`-documented failure
 *  this file avoids elsewhere. `regime` renders as `—` when the server recorded none, per its own
 *  docstring -- that empty string is itself the server's "no regime" sentinel, not a missing value
 *  this component is inventing a placeholder for. */
function StagedOrderRow({ order: o }: { order: AutopilotOrder }) {
  const sideTone = o.side === "sell" ? "sell" : "buy";
  return (
    <tr>
      <td className="position-symbol-cell">
        <span className="position-symbol">{o.symbol}</span>
      </td>
      <td>
        <span className={`badge desk-upcoming-badge desk-upcoming-badge-${sideTone}`}>{o.side}</span>
      </td>
      <td className="num">{formatMoney(o.notional)}</td>
      <td>{o.decision_date}</td>
      <td>{o.fill_date}</td>
      <td>{o.regime === "" ? "—" : o.regime}</td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Live execution -- what the desk would trade RIGHT NOW against a real-time quote.
// ---------------------------------------------------------------------------

/** Total refused orders across every group in `live_rejections`. Mirrors `Desk.rejection_count`,
 *  which is a scalar the server sends alongside the historical `rejections` array but has no live
 *  counterpart for -- summed client-side from each group's own `count` instead. */
function liveRejectionOrderCount(rejections: DeskRejection[]): number {
  return rejections.reduce((sum, r) => sum + r.count, 0);
}

/**
 * What this desk would trade right now, priced against a real-time quote -- a projection recomputed
 * on every refresh, never part of the desk's own audited record (`RecentActivity`'s decisions,
 * `HoldingsTable`, the trades table inside `BookStatistics`). Those are what the desk actually did
 * and when it did it; this is what the desk's rules say it would do *this second*, against a price
 * that will have moved again by the time the page is reloaded.
 *
 * Renders nothing at all -- not an empty panel -- when `live_as_of` is `null` (the feature is off
 * for this desk or this server build) or when neither `live_fills` nor `live_rejections` has
 * anything in it. `live_as_of` and the fill/rejection counts are the headline and stay visible with
 * zero interaction, per the task's compactness requirement; the per-fill rows sit behind a `<details>`
 * and the per-order rejection sentences behind `RejectionGroup`'s own disclosure, the same component
 * the historical `RejectionsCallout` above uses for `rejections` -- one implementation of "a rule's
 * worth of refused orders," not two.
 */
function LiveExecution({ desk }: { desk: Desk }) {
  const { t } = useT();
  if (desk.live_as_of === null) return null;

  const fills = desk.live_fills;
  const rejections = desk.live_rejections;
  if (fills.length === 0 && rejections.length === 0) return null;

  const rejectionOrders = liveRejectionOrderCount(rejections);
  const rejectionClause =
    rejectionOrders > 0
      ? t(
          rejectionOrders === 1
            ? "paperDesk.live.rejectionClause_one"
            : "paperDesk.live.rejectionClause_other",
          { count: rejectionOrders },
        )
      : "";

  return (
    <div className="desk-section desk-live-section">
      <div className="desk-live-head">
        <span className="badge desk-live-badge" title={t("paperDesk.live.badgeTitle")}>
          {t("paperDesk.live.badge")}
        </span>
        <strong className="desk-live-headline">
          {t(fills.length === 1 ? "paperDesk.live.headline_one" : "paperDesk.live.headline_other", {
            count: fills.length,
            rejectionClause,
          })}
        </strong>
        <span className="muted desk-live-asof">
          {t("paperDesk.asOfLower", { date: desk.live_as_of })}
        </span>
      </div>
      <InfoNote className="desk-live-note" tone="quiet" summary={t("paperDesk.live.note")}>
        {t("paperDesk.live.noteDetail")}
      </InfoNote>

      {fills.length > 0 && (
        <details className="desk-live-detail">
          <summary>{t("paperDesk.live.fillDetail")}</summary>
          <ul className="desk-live-fills">
            {fills.map((f, i) => (
              <LiveFillRow key={`${f.symbol}-${f.side}-${i}`} fill={f} />
            ))}
          </ul>
        </details>
      )}

      {rejections.length > 0 && (
        <ul className="desk-rejection-groups desk-live-rejection-groups">
          {rejections.map((r) => (
            <RejectionGroup key={r.rule} rejection={r} />
          ))}
        </ul>
      )}
    </div>
  );
}

/** One live-priced fill. `fill.side` is an open string sent verbatim by the server (see
 *  `LiveFill.side`'s docstring in `@/api/paperdesk`) -- rendered as-is rather than switched on, so an
 *  unrecognised value still renders instead of throwing. */
function LiveFillRow({ fill }: { fill: LiveFill }) {
  const { t } = useT();
  return (
    <li className="desk-live-fill">
      <span className="badge desk-live-side-badge">{fill.side}</span>
      <span className="position-symbol">{fill.symbol}</span>
      <span className="desk-live-fill-qty">{fill.quantity}</span>
      <span className="desk-live-fill-price">
        {formatMoney(fill.price)}
        <span className="muted desk-live-quote-price">
          {t("paperDesk.live.quotePrice", { price: formatMoney(fill.quote_price) })}
        </span>
      </span>
      <span className="muted desk-live-fill-notional">{formatMoney(fill.notional)}</span>
    </li>
  );
}

// ---------------------------------------------------------------------------
// What it just did -- the most recent decisions, newest first.
// ---------------------------------------------------------------------------

function recentDecisions(decisions: Decision[], limit = 5): Decision[] {
  return [...decisions].sort((a, b) => b.date.localeCompare(a.date)).slice(0, limit);
}

function RecentActivity({ decisions }: { decisions: Decision[] }) {
  const { t } = useT();
  const recent = recentDecisions(decisions);
  return (
    <div className="desk-section desk-recent-section">
      <h3>{t("paperDesk.recent.title")}</h3>
      {recent.length === 0 ? (
        <div className="placeholder">{t("paperDesk.noDecisionsYet")}</div>
      ) : (
        <ul className="desk-recent-list">
          {recent.map((d, i) => (
            <li key={`${d.date}-${d.symbol}-${i}`} className="desk-recent-item">
              <span className="desk-recent-date">{d.date}</span>
              <span className={`badge desk-action-badge desk-action-${d.action}`}>
                {decisionActionLabel(d.action)}
              </span>
              <span className="position-symbol">{d.symbol}</span>
              <span className="desk-recent-detail">
                {d.quantity} @ {formatMoney(d.price)} ({formatMoney(d.notional)})
              </span>
              <span className="muted desk-recent-reason">{d.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Holdings
// ---------------------------------------------------------------------------

/** Case-insensitive substring match on `symbol` -- the same normalisation `Activity.tsx`'s own
 *  symbol filter uses, so a reader typing a lowercase ticker gets the same behaviour on both
 *  pages. An empty (or all-whitespace) query is "no filter", not "match nothing". */
function filterHoldingsBySymbol(holdings: Holding[], query: string): Holding[] {
  const q = query.trim().toUpperCase();
  if (!q) return holdings;
  return holdings.filter((h) => h.symbol.toUpperCase().includes(q));
}

function HoldingsTable({ holdings }: { holdings: Holding[] }) {
  const { t } = useT();
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => filterHoldingsBySymbol(holdings, query), [holdings, query]);
  return (
    <div className="desk-section">
      <h3>{t("paperDesk.holdings.title")}</h3>
      {holdings.length === 0 ? (
        <div className="placeholder">{t("paperDesk.holdings.empty")}</div>
      ) : (
        <>
          <FilterBar
            query={query}
            onQueryChange={setQuery}
            queryPlaceholder={t("paperDesk.holdings.filterPlaceholder")}
            shown={filtered.length}
            total={holdings.length}
          />
          {filtered.length === 0 ? (
            <div className="placeholder">{t("paperDesk.holdings.filterEmpty")}</div>
          ) : (
            /* Neither a `ScrollRegion` nor a `.table-wrap` of its own -- see `StagedOrders` above:
               the card body is this card's single scroll container, on both axes. */
            <table className="data-table position-table desk-holdings-table">
              <thead>
                <tr>
                  <th scope="col">{t("common.symbol")}</th>
                  <th scope="col" className="num">
                    {t("common.quantity")}
                  </th>
                  <th scope="col">{t("paperDesk.holdings.entryDate")}</th>
                  <th scope="col" className="num">
                    {t("paperDesk.holdings.entryPrice")}
                  </th>
                  <th scope="col" className="num">
                    {t("paperDesk.holdings.lastPrice")}
                  </th>
                  <th scope="col" className="num">
                    {t("paperDesk.holdings.marketValue")}
                  </th>
                  <th scope="col" className="num">
                    {t("paperDesk.holdings.unrealisedPnl")}
                  </th>
                  <th scope="col" className="num">
                    {t("paperDesk.returnHeader")}
                  </th>
                  <th scope="col" className="num">
                    {t("common.weight")}
                  </th>
                  <th scope="col" className="num">
                    {t("paperDesk.holdings.stopPrice")}
                  </th>
                  <th
                    scope="col"
                    className="num"
                    title={t("paperDesk.holdings.sessionsToTimeStopHint")}
                  >
                    {t("paperDesk.holdings.sessionsToTimeStop")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((h) => (
                  <HoldingRow key={h.symbol} holding={h} />
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </div>
  );
}

function HoldingRow({ holding: h }: { holding: Holding }) {
  const { t } = useT();
  const tone = moneyTone(h.unrealised_pnl);
  return (
    <tr>
      <td className="position-symbol-cell">
        <span className="position-symbol">{h.symbol}</span>
      </td>
      <td className="num">{h.quantity}</td>
      <td>{h.entry_date}</td>
      <td className="num">{formatMoney(h.entry_price)}</td>
      <td className="num">
        <div>{formatMoney(h.last_price)}</div>
        <div className="position-price-asof">
          {t("paperDesk.asOfLower", { date: h.last_price_date })}
        </div>
      </td>
      <td className="num">{formatMoney(h.market_value)}</td>
      <td className="num">
        <span className={`position-unrealized-value ${tone}`}>{formatSignedMoney(h.unrealised_pnl)}</span>
      </td>
      <td className="num">{formatSignedFractionPctString(h.return_pct)}</td>
      <td className="num">{formatWeightPct(h.weight, 2)}</td>
      <td className="num">{formatMoneyOrDash(h.stop_price)}</td>
      <td className="num">{h.sessions_to_time_stop === null ? "—" : h.sessions_to_time_stop}</td>
    </tr>
  );
}
