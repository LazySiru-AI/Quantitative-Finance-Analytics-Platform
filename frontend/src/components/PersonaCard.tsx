/**
 * One influencer's digest card -- display name, platform/handle, note count, how fresh the digest
 * is, their headline take, their themes, and a ticker chip per name they mentioned. Plus the two
 * per-persona actions the page wires up: starting an ingest and removing the persona.
 *
 * **Presentational only -- this component fetches nothing.** Every value renders straight from
 * `card` (a `DigestCard`) and the ingest-job/pending/error props `Personas.tsx` owns and polls, the
 * same split `NewsPanel.tsx` establishes between a fetch-free component and the hook/page that feeds
 * it.
 *
 * This file exists to enforce the product guardrails `docs/INFLUENCER-CONTRACT.md` states for a
 * card, not merely style it:
 *
 * 1. **Everything reads as the influencer's own view, never this application's signal or
 *    recommendation.** "Their view" / "what they said", not "signal". A reader must not be able to
 *    mistake a card for advice.
 * 2. **`unclear` renders as "no clear stance"**, not folded into "neutral" -- `neutral` is a real,
 *    distinct stance an influencer can hold. See `STANCE_LABELS` (`@/api/personas`).
 * 3. **A persona with no notes yet is a valid state**, rendered as an empty-state invitation to
 *    ingest -- never an error, never a spinner.
 * 4. **`grounding.degraded` is always visible when true**, worded as a fact-check failure the card
 *    is shown despite, never hidden. Per the contract amendment, `card.grounding` is an *aggregate*
 *    over the card's notes (only `ok`/`degraded` are meaningful -- `issues`/`attempts`/
 *    `checked_tokens` sit at their zero/empty defaults and are deliberately not rendered here, since
 *    showing e.g. "0 tokens checked" from an aggregate default would present it as a real
 *    measurement). `latest_note.degraded` is the one place a single note's own fact-check result is
 *    shown, if a reader wants to know whether the freshest note specifically was the one that failed.
 * 5. **Non-empty `warnings` are always rendered**, never swallowed -- same rule `NewsPanel.tsx`'s
 *    own `WarningsList` enforces.
 *
 * **The ingest panel (`IngestPanel` below) offers the three mutually-exclusive request shapes
 * `POST /{slug}/ingest` accepts** -- recent-videos backfill (`{limit}`), specific videos
 * (`{video_urls}`), and a pasted-text drop (`{drop}`). It builds the request body from its own local
 * form state and hands it to `onIngest`; it never calls `personasApi` itself -- `Personas.tsx` still
 * owns every fetch, per this component's "presentational only" rule above. Its own guardrails only
 * *mirror* the server's: it never submits an empty `video_urls` list or a `drop` missing `text`
 * (disabling the submit button instead), but the server is the authority on everything else (a
 * `video_urls` entry it cannot resolve to an id, a second ingest while one is already running) --
 * those rejections surface through `ingestError` exactly like any other, never swallowed here.
 */
import { useState } from "react";
import { Link } from "react-router-dom";

import {
  buildDropRequest,
  formatMoney,
  formatRelativeAge,
  isIngestActive,
  parseVideoUrlLines,
  stanceLabel,
  type DigestCard,
  type IngestJob,
  type IngestMode,
  type IngestRequest,
} from "@/api/personas";
import { Card } from "@/components/Card";
import StatusPill from "@/components/StatusPill";
import { useT, type MessageKey } from "@/i18n";

export interface PersonaCardProps {
  card: DigestCard;
  /** The persona's current ingest job, if one has been started this session -- `null` until
   * `onIngest` is fired at least once, or a stale one from a previous page state a caller chooses
   * not to keep. */
  ingestJob: IngestJob | null;
  /** `true` while the `POST /ingest` request itself is in flight, before a job id even exists. */
  ingestPending: boolean;
  ingestError: string | null;
  /** Fired with the request body `IngestPanel` built from whichever mode the user had selected. */
  onIngest: (body: IngestRequest) => void;
  deletePending: boolean;
  deleteError: string | null;
  onDelete: () => void;
}

export default function PersonaCard({
  card,
  ingestJob,
  ingestPending,
  ingestError,
  onIngest,
  deletePending,
  deleteError,
  onDelete,
}: PersonaCardProps) {
  const { t } = useT();
  const persona = card.persona;
  const primarySource = persona.sources[0];
  const hasNotes = card.note_count > 0;
  const ingestActive = ingestJob !== null && isIngestActive(ingestJob.state);

  return (
    <Card
      id={`persona-${persona.slug}`}
      height="md"
      label={persona.display_name}
      panelClassName="persona-card"
      className="persona-card-scroll-body"
      expandable
      title={
        <div>
          <h2 className="persona-card-name">{persona.display_name}</h2>
          <p className="muted persona-card-handle">
            {primarySource
              ? `${primarySource.platform} · ${primarySource.handle}`
              : t("misc.personas.card.noSourceConfigured")}
          </p>
        </div>
      }
      status={
        <>
          <span className="badge">
            {t(card.note_count === 1 ? "misc.personas.card.noteCount_one" : "misc.personas.card.noteCount_other", {
              count: card.note_count,
            })}
          </span>{" "}
          <span className="muted persona-card-asof">
            {card.as_of
              ? t("misc.personas.card.updatedAge", { age: formatRelativeAge(card.as_of) })
              : t("misc.personas.card.noNotesYet")}
          </span>
        </>
      }
      footer={
        <>
          {ingestJob && <IngestProgress job={ingestJob} />}
          {ingestError && (
            <div className="callout callout-danger persona-card-ingest-error" role="alert">
              {ingestError}
            </div>
          )}

          <IngestPanel onIngest={onIngest} pending={ingestPending} active={ingestActive} />

          {deleteError && (
            <div className="callout callout-danger persona-card-delete-error" role="alert">
              {deleteError}
            </div>
          )}

          <div className="persona-card-actions">
            <button
              type="button"
              className="persona-card-remove"
              onClick={onDelete}
              disabled={deletePending}
            >
              {deletePending ? t("misc.personas.card.removing") : t("misc.personas.card.removeButton")}
            </button>
          </div>
        </>
      }
    >
      {card.grounding.degraded && (
        <div className="callout callout-warn persona-card-degraded" role="alert">
          <StatusPill tone="warn" label={t("ui.pill.unverified")} />{" "}
          <strong>{t("misc.personas.card.factCheckFailed")}</strong>{" "}
          {t("misc.personas.card.factCheckDetail", { name: persona.display_name })}
        </div>
      )}

      {!hasNotes && (
        <div className="placeholder persona-card-empty">
          {t("misc.personas.card.noNotesEmpty", { name: persona.display_name })}
        </div>
      )}

      {hasNotes && (
        <>
          {card.headline && (
            <p className="persona-card-headline">
              <span className="persona-card-headline-label muted">
                {t("misc.personas.card.recentTakeLabel")}
              </span>{" "}
              {card.headline}{" "}
              {/* The headline is a model impression built from the influencer's own notes, not this
                  application's copy -- it stays in English regardless of `lang` (rule 9), and the
                  badge says so rather than leaving a Korean reader to wonder why it did not switch. */}
              <span className="badge" title={t("common.sourceEnglishTitle")}>
                {t("common.sourceEnglish")}
              </span>
            </p>
          )}

          {card.themes.length > 0 && (
            <div className="persona-card-section">
              <h3 className="persona-card-subhead">{t("misc.personas.card.focusedOnHeader")}</h3>
              <ul className="persona-card-themes">
                {card.themes.map((theme, i) => (
                  <li key={i}>{theme}</li>
                ))}
              </ul>
            </div>
          )}

          {card.mentions.length > 0 && (
            <div className="persona-card-section">
              <h3 className="persona-card-subhead">{t("misc.personas.card.viewByTickerHeader")}</h3>
              <ul className="persona-card-tickers">
                {card.mentions.map((mention) => (
                  <li key={mention.symbol}>
                    <Link
                      className="persona-ticker-chip"
                      to={`/symbol/${encodeURIComponent(mention.symbol)}`}
                      title={mention.reasoning}
                    >
                      <span className="position-symbol">{mention.symbol}</span>
                      <span className={`persona-ticker-stance persona-ticker-stance-${mention.stance}`}>
                        {stanceLabel(mention.stance)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {card.latest_note?.degraded && (
            <p className="muted persona-card-note-degraded">{t("misc.personas.card.noteDegraded")}</p>
          )}
        </>
      )}

      {card.warnings.length > 0 && (
        <ul className="warning-list persona-card-warnings">
          {card.warnings.map((w, i) => (
            <li key={`${w.source}-${i}`}>
              <span className="kind">{w.source}</span> {w.reason}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const INGEST_TABS: { key: IngestMode; labelKey: MessageKey }[] = [
  { key: "recent", labelKey: "misc.personas.ingest.tabRecent" },
  { key: "specific", labelKey: "misc.personas.ingest.tabSpecific" },
  { key: "drop", labelKey: "misc.personas.ingest.tabDrop" },
];

const DEFAULT_LIMIT = 20;
const MIN_LIMIT = 1;
const MAX_LIMIT = 50;

/** Clamps a `limit` input value into `[MIN_LIMIT, MAX_LIMIT]`, falling back to `DEFAULT_LIMIT` for
 * anything that does not round to a usable positive integer (an emptied field parses to `NaN`,
 * which `Math.round` also turns into `NaN` -- `Number.isFinite` catches both `NaN` and `Infinity`
 * before they reach `Math.max`/`Math.min`, which would otherwise happily propagate a `NaN`). */
function clampLimit(value: number): number {
  const rounded = Math.round(value);
  if (!Number.isFinite(rounded)) return DEFAULT_LIMIT;
  return Math.min(MAX_LIMIT, Math.max(MIN_LIMIT, rounded));
}

/** The three-mode ingest control described in this file's own docstring above. Local form state
 * only -- it fetches nothing, and resets to nothing on mode switch beyond what the user already
 * typed in each mode's own fields (switching tabs to look and switching back does not lose a draft). */
function IngestPanel({
  onIngest,
  pending,
  active,
}: {
  onIngest: (body: IngestRequest) => void;
  pending: boolean;
  active: boolean;
}) {
  const { t } = useT();
  const [mode, setMode] = useState<IngestMode>("recent");
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [videoUrlsText, setVideoUrlsText] = useState("");
  const [dropText, setDropText] = useState("");
  const [dropTitle, setDropTitle] = useState("");
  const [dropUrl, setDropUrl] = useState("");

  const videoUrls = parseVideoUrlLines(videoUrlsText);
  const drop = buildDropRequest(dropText, dropTitle, dropUrl);

  // Client-side guardrails mirroring the server's own: never submit an empty `video_urls` list or
  // a drop missing `text` (the server would reject the latter with a 422 anyway). The server stays
  // the authority on everything else -- an unparseable video url, a 409 double-ingest -- so this is
  // deliberately not a full validation layer, just enough to keep an obviously-empty submit from
  // round-tripping to the backend at all.
  const modeReady =
    mode === "recent" ? true : mode === "specific" ? videoUrls.length > 0 : drop !== null;
  const busy = pending || active;

  const handleSubmit = () => {
    if (!modeReady) return;
    if (mode === "recent") {
      onIngest({ limit: clampLimit(limit) });
    } else if (mode === "specific") {
      if (videoUrls.length === 0) return;
      onIngest({ video_urls: videoUrls });
    } else {
      if (drop === null) return;
      onIngest({ drop });
    }
  };

  return (
    <div className="persona-ingest-panel">
      <div className="view-tabs persona-ingest-tabs" role="tablist" aria-label={t("misc.personas.ingest.modeAriaLabel")}>
        {INGEST_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={mode === tab.key}
            className={`timeframe-tab${mode === tab.key ? " active" : ""}`}
            onClick={() => setMode(tab.key)}
          >
            {t(tab.labelKey)}
          </button>
        ))}
      </div>

      {mode === "recent" && (
        <label className="persona-ingest-field">
          <span>{t("misc.personas.ingest.limitLabel")}</span>
          <input
            type="number"
            min={MIN_LIMIT}
            max={MAX_LIMIT}
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          />
        </label>
      )}

      {mode === "specific" && (
        <label className="persona-ingest-field">
          <span>{t("misc.personas.ingest.urlsLabel")}</span>
          <textarea
            rows={3}
            value={videoUrlsText}
            onChange={(e) => setVideoUrlsText(e.target.value)}
            placeholder={t("misc.personas.ingest.urlsPlaceholder")}
          />
        </label>
      )}

      {mode === "drop" && (
        <div className="persona-ingest-drop-fields">
          <label className="persona-ingest-field">
            <span>{t("misc.personas.ingest.titleLabel")}</span>
            <input value={dropTitle} onChange={(e) => setDropTitle(e.target.value)} />
          </label>
          <label className="persona-ingest-field">
            <span>{t("misc.personas.ingest.urlLabel")}</span>
            <input value={dropUrl} onChange={(e) => setDropUrl(e.target.value)} />
          </label>
          <label className="persona-ingest-field">
            <span>{t("misc.personas.ingest.textLabel")}</span>
            <textarea
              rows={4}
              value={dropText}
              onChange={(e) => setDropText(e.target.value)}
              placeholder={t("misc.personas.ingest.textPlaceholder")}
            />
          </label>
        </div>
      )}

      <button type="button" onClick={handleSubmit} disabled={!modeReady || busy}>
        {pending
          ? t("misc.personas.ingest.starting")
          : active
            ? t("misc.personas.ingest.active")
            : t("misc.personas.ingest.submit")}
      </button>
    </div>
  );
}

/** Job-state badge text, translated via the shared backend-enum vocabulary (`common.status.*`)
 * rather than the raw lowercase `IngestState` value -- `IngestState`'s five values are exactly the
 * five `status.*` keys already in `messages/common.ts`. */
const INGEST_STATE_KEYS: Record<IngestJob["state"], MessageKey> = {
  queued: "status.queued",
  running: "status.running",
  succeeded: "status.succeeded",
  failed: "status.failed",
  cancelled: "status.cancelled",
};

/** `spent_usd` is a `DecimalString` -- `formatMoney` (`@/api/personas`) is the only thing that ever
 * touches it, never a raw template of the string or a `Number()` coercion. */
function IngestProgress({ job }: { job: IngestJob }) {
  const { t } = useT();
  const pct = job.items_total > 0 ? Math.min(100, Math.round((job.items_done / job.items_total) * 100)) : 0;
  const stateLabel = t(INGEST_STATE_KEYS[job.state]);
  return (
    <div className="persona-ingest-progress">
      <div className="persona-ingest-progress-row">
        <span>
          {job.items_failed > 0
            ? t("misc.personas.ingest.progressFailed", {
                state: stateLabel,
                done: job.items_done,
                total: job.items_total,
                failed: job.items_failed,
              })
            : t("misc.personas.ingest.progress", {
                state: stateLabel,
                done: job.items_done,
                total: job.items_total,
              })}
        </span>
        <span>{t("misc.personas.ingest.spent", { amount: formatMoney(job.spent_usd) })}</span>
      </div>
      <span
        className="persona-ingest-bar"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span className="persona-ingest-bar-fill" style={{ width: `${pct}%` }} />
      </span>
      {job.state === "failed" && job.error && (
        <div className="callout callout-danger persona-ingest-job-error" role="alert">
          {job.error}
        </div>
      )}
    </div>
  );
}
