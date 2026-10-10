/**
 * Manager -- the deterministic change feed (Phase 1) plus the model-driven layer-C surfaces: a
 * grounded brief, its synthesis + commissions, and a chat.
 *
 * **Phase 1 (keep working with the model down).** Renders the rule-derived change feed
 * (`GET /api/manager/changes`) and the desk's own status (`GET /api/manager/config`) --
 * `agent_available: false` degrades the header's status pill and disables the model-driven sections
 * below, nothing else. The header (`config`) and the feed (`changes`) stay two independent
 * `useFetch` calls for exactly this reason: the config fetch failing, or resolving with
 * `agent_available: false`, must never block or hide the changes feed.
 *
 * **Phase C (this addition) -- everything below the changes feed:**
 *  - **Brief runner**: "Run brief" (`POST /briefs`) starts a `DeskRun`, polled every 2000ms
 *    (`GET /runs/{run_id}`, mirroring `AgentWorkflow.tsx`'s/`VibeTrading.tsx`'s own poll effect)
 *    while `isRunActive`; once terminal, `GET /briefs/latest` is refetched. Disabled while
 *    `agent_available` is false (tooltip = `agent_reason`) or a run is already in flight.
 *  - **Brief render**: synthesis (assessment/agreements/conflicts/risks/open_questions, each bullet's
 *    `source_refs` as chips via `RefChips`), the brief's own `caveat` (always rendered, unconditional
 *    -- the not-advice line for the brief specifically), `data_health` and the `degraded` flag.
 *  - **Commissions**: research the manager proposes handing to a child desk. `state === "proposed"`
 *    gets Approve/Decline buttons; approving spends that commission's own budget, stated plainly, not
 *    just implied by the click.
 *  - **Chat**: forks `PersonaChat.tsx`'s idioms (thread list, transcript, degraded callout, citation
 *    chips, composer) without importing it -- this page owns its own fetches directly (`managerApi.
 *    chats`/`createChat`/`chat`/`deleteChat`/`sendTurn`), the same split `PersonaDetail.tsx` makes
 *    for the persona version. A "refresh data first" checkbox passes `refresh: true`. Deleting a
 *    thread goes through `ConfirmSheet` (EXP-24) -- it destroys a transcript, which is exactly the
 *    half of `pages/data/UsersPanel.tsx`'s rule that always confirms.
 *
 * **Density is the whole point** (per the brief that commissioned this page): the attention panel
 * and the per-area lists are the tightest rows this app renders anywhere, no wasted vertical space,
 * reusing `.data-table`-adjacent primitives (`ScrollRegion`, `.tile-grid`, `.callout`) rather than
 * inventing new chrome. The Phase C sections below follow the same rule.
 *
 * Layout, top to bottom:
 *  1. A header strip: agent status pill, last snapshot time, spend today vs. daily cap, autonomy,
 *     a yesterday/week window toggle, and a "Snapshot now" button -- plus (EXP-04) the data-egress
 *     note, which says that real account, tax and activity figures go to the model provider. That
 *     note sits OUTSIDE `<Fetched>`: what leaves this machine is not conditional on the config
 *     fetch resolving, so a failed fetch must not take the notice down with it.
 *  2. The not-advice line -- pinned, rendered unconditionally, even before either fetch resolves.
 *  3. The Attention panel: `severity === "attention"` items, one dense row each.
 *  4. Changes by area: every other item, grouped by `Area` in the fixed order the wire contract
 *     enumerates it, one scrollable panel per area that has any items.
 *  5. Gaps: `sections_missing` and `warnings`, always visible in a `callout-warn`, never hidden --
 *     plus a distinct note when `since === null` ("activity only", never phrased as "no changes").
 *  6. An empty state naming the window and `since` when there are no items at all.
 *  7. The brief runner + brief render (synthesis, data health, commissions).
 *  8. The chat panel.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { ApiRequestError } from "@/api/client";
import {
  isRunActive,
  managerApi,
  type Area,
  type Brief,
  type BriefBullet,
  type ChangeItem,
  type ChangeSet,
  type Commission,
  type CommissionState,
  type DataHealth,
  type DeskRun,
  type ManagerChatThread,
  type ManagerChatTurn,
  type ManagerConfig,
  type SourceRef,
  type StageState,
  type Synthesis,
  type Window as ManagerWindow,
} from "@/api/manager";
import { Card, CardGrid } from "@/components/Card";
import Collapsible from "@/components/Collapsible";
import { ConfirmSheet } from "@/components/ConfirmSheet";
import Fetched from "@/components/Fetched";
import Glyph, { type GlyphName } from "@/components/Glyph";
import { InfoNote } from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import { formatMoney } from "@/format/money";
import { formatFetchError, useFetch } from "@/hooks/useFetch";
import { useT, type MessageKey, type Translator } from "@/i18n";

import "./Manager.css";

/** Matches the sibling desks' own poll interval (`AgentWorkflow.tsx`/`VibeTrading.tsx`) -- not tied
 *  to anything server-side. */
const POLL_INTERVAL_MS = 2000;

/** The fixed area order the wire contract enumerates -- "Changes by area" renders in this order,
 *  not insertion order, so the grid reads the same shape run to run regardless of which areas
 *  happened to produce a change today.
 *
 *  `"news"` and `"activity"` are deliberately absent: no rule in `app.manager.rules` emits either
 *  area, so a card for them could never have content. The `Area` type still carries them -- it
 *  mirrors the wire contract, which is not this page's to narrow. */
export const AREA_ORDER: readonly Area[] = [
  "account",
  "tax",
  "paperdesk",
  "persona_books",
  "persona_traders",
  "research",
  "desks",
  "live",
  "personas",
  "market",
  "events",
  "data",
];

const AREA_LABEL_KEY: Readonly<Record<Area, MessageKey>> = {
  account: "manager.area.account",
  tax: "manager.area.tax",
  paperdesk: "manager.area.paperdesk",
  persona_books: "manager.area.personaBooks",
  persona_traders: "manager.area.personaTraders",
  research: "manager.area.research",
  desks: "manager.area.desks",
  live: "manager.area.live",
  personas: "manager.area.personas",
  market: "manager.area.market",
  events: "manager.area.events",
  news: "manager.area.news",
  data: "manager.area.data",
  activity: "manager.area.activity",
};

const WINDOW_OPTIONS: readonly { value: ManagerWindow; labelKey: MessageKey }[] = [
  { value: "yesterday", labelKey: "manager.window.yesterday" },
  { value: "week", labelKey: "manager.window.week" },
];

const SEVERITY_GLYPH: Record<ChangeItem["severity"], GlyphName> = {
  attention: "warn",
  notable: "partial",
  fyi: "info",
};

const SEVERITY_TONE: Record<ChangeItem["severity"], PillTone> = {
  attention: "bad",
  notable: "warn",
  fyi: "neutral",
};

const SEVERITY_LABEL_KEY: Record<ChangeItem["severity"], MessageKey> = {
  attention: "manager.severity.attention",
  notable: "manager.severity.notable",
  fyi: "manager.severity.fyi",
};

const STAGE_TONE: Record<StageState, PillTone> = {
  pending: "neutral",
  running: "info",
  succeeded: "ok",
  degraded: "warn",
  failed: "bad",
  blocked: "special",
  skipped: "neutral",
};

const STAGE_LABEL_KEY: Record<StageState, MessageKey> = {
  pending: "manager.stage.pending",
  running: "manager.stage.running",
  succeeded: "manager.stage.succeeded",
  degraded: "manager.stage.degraded",
  failed: "manager.stage.failed",
  blocked: "manager.stage.blocked",
  skipped: "manager.stage.skipped",
};

const COMMISSION_TONE: Record<CommissionState, PillTone> = {
  proposed: "neutral",
  approved: "info",
  running: "info",
  succeeded: "ok",
  failed: "bad",
  cancelled: "neutral",
  declined: "neutral",
};

const COMMISSION_LABEL_KEY: Record<CommissionState, MessageKey> = {
  proposed: "manager.commission.state.proposed",
  approved: "manager.commission.state.approved",
  running: "manager.commission.state.running",
  succeeded: "manager.commission.state.succeeded",
  failed: "manager.commission.state.failed",
  cancelled: "manager.commission.state.cancelled",
  declined: "manager.commission.state.declined",
};

/**
 * UX-05 -- server vocabulary rendered as labels, never as variable names.
 *
 * `DataHealth.stale`/`.unknown` are `string[]` on the wire, not a closed union: they carry the
 * freshness catalog's own source keys (`app/market/freshness.py`'s `SOURCE_KEYS`) plus the two ids
 * the manager's own data section adds on top of it (`sweep:refresh`, `daemon:social`). The eleven
 * catalog sources already have en/ko labels in `messages/data.ts`, rendered by
 * `pages/data/DataHealthPanel.tsx` -- reused verbatim here rather than written a second time
 * (docs/COPY-STYLE.md rule 2: one explanation per fact, app-wide, one key, reused).
 *
 * A key outside this map falls through to `humaniseKey`, NEVER to an exhaustiveness throw -- a
 * server string this build has not seen is a new data source, not a reason to blank the page (see
 * `closed-unions-over-server-data-kill-pages` in this repo's memory, and `DataHealthPanel.tsx`'s
 * own docstring making the same argument for the same keys).
 */
const SOURCE_LABEL_KEY: Readonly<Record<string, MessageKey>> = {
  bars_daily: "data.freshness.source.bars_daily",
  bars_intraday: "data.freshness.source.bars_intraday",
  macro_snapshot: "data.freshness.source.macro_snapshot",
  calendar_events: "data.freshness.source.calendar_events",
  fundamentals_edgar: "data.freshness.source.fundamentals_edgar",
  institutions_filings: "data.freshness.source.institutions_filings",
  news: "data.freshness.source.news",
  social_snapshots: "data.freshness.source.social_snapshots",
  live_quotes: "data.freshness.source.live_quotes",
  ledger: "data.freshness.source.ledger",
  persona_corpus: "data.freshness.source.persona_corpus",
  "sweep:refresh": "manager.source.sweep_refresh",
  "daemon:social": "manager.source.daemon_social",
};

/** Word-level fixes `humaniseKey` applies so a wire name does not read as one when it is spelled
 *  out -- `weight_pct` is "Weight %", not "Weight pct". */
const KEY_WORDS: Readonly<Record<string, string>> = {
  pct: "%",
  usd: "USD",
  ytd: "YTD",
  edgar: "EDGAR",
  id: "ID",
};

/** A wire key rendered as a label of last resort: separators become spaces, known abbreviations are
 *  spelled the way this app spells them, and the result is sentence case. Not a translation -- it is
 *  what an unmapped `macro_snapshot` should look like while someone adds the real label. */
function humaniseKey(key: string): string {
  const words = key
    .split(/[:_\-.]+/)
    .filter((word) => word !== "")
    .map((word) => KEY_WORDS[word.toLowerCase()] ?? word);
  const joined = words.join(" ");
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

function sourceLabel(t: Translator, key: string): string {
  const labelKey = SOURCE_LABEL_KEY[key];
  return labelKey ? t(labelKey) : humaniseKey(key);
}

/** One `ChangeItem.figures` entry as a readable chip. `figures` is an open `Record<string, string>`
 *  of wire names (`FIGURE_KEYS` in `app/manager/models.py` lists ~50 across fourteen areas), so the
 *  general case is a humanised key; `unpriced_count` gets a real sentence because it is a claim
 *  about the book ("0 unpriced_count" was rendering a variable name mid-sentence). */
function figureText(t: Translator, key: string, value: string): string {
  if (key === "unpriced_count") return t("manager.figure.unpricedCount", { value });
  return t("manager.figure.generic", { label: humaniseKey(key), value });
}

/** Anything that looks like a session or request id, in either `session_id: "abc123"` /
 *  `"req-id"="..."` form or a bare `req_...`/`session_...` token. Stripped before a failed
 *  commission's payload is put on screen: the reader cannot act on it and it is the one part of a
 *  provider error that identifies a specific call. */
const ID_ASSIGNMENT = /["']?\b(?:session|sess|request|req)(?:[_\-]?id)?\b["']?\s*[:=]\s*["']?[A-Za-z0-9._-]+["']?/gi;
const ID_TOKEN = /\b(?:session|sess|req|request)_[A-Za-z0-9]{6,}\b/gi;

function scrubIds(text: string, placeholder: string): string {
  return text.replace(ID_ASSIGNMENT, placeholder).replace(ID_TOKEN, placeholder);
}

/** The first `"detail"`/`"message"`/`"error"`/`"reason"` string in a JSON-ish payload -- the half of
 *  a child desk's error a reader can actually act on. Regex rather than `JSON.parse` alone because
 *  the payload arrives truncated often enough that parsing it is the uncommon case. */
const REASON_FIELD = /"(?:detail|message|error|reason)"\s*:\s*"((?:[^"\\]|\\.)*)"/i;

/** One line, collapsed and clipped -- a row is not the place for a paragraph. */
function oneLine(text: string, max = 100): string {
  const first = text.trim().split(/\r?\n/, 1)[0] ?? "";
  const collapsed = first.replace(/\s+/g, " ").trim();
  return collapsed.length > max ? `${collapsed.slice(0, max - 1)}…` : collapsed;
}

/** A failed commission's payload reduced to the sentence that says what went wrong. */
function failureReason(scrubbed: string): string {
  const trimmed = scrubbed.trim();
  if (trimmed.startsWith("{")) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (parsed !== null && typeof parsed === "object") {
        for (const field of ["detail", "message", "error", "reason"]) {
          const value = (parsed as Record<string, unknown>)[field];
          if (typeof value === "string" && value.trim() !== "") return oneLine(value);
        }
      }
    } catch {
      // Truncated or otherwise unparseable -- the regex below is the fallback, not an error path.
    }
    const matched = REASON_FIELD.exec(trimmed);
    if (matched?.[1] !== undefined && matched[1].trim() !== "") return oneLine(matched[1]);
  }
  return oneLine(trimmed);
}

/** Above this many characters across a synthesis group's bullets, the group is a wall of prose:
 *  the first paragraph stays visible and the rest move behind "Read more". */
const SYNTHESIS_WALL_CHARS = 200;

/** The five bullet groups `Synthesis` always carries, in the order the contract enumerates them --
 *  a group with zero bullets renders no heading at all, same rule the area grid uses for an area
 *  with no items. */
const SYNTHESIS_GROUPS: readonly { key: keyof Omit<Synthesis, "caveat">; labelKey: MessageKey }[] = [
  { key: "assessment", labelKey: "manager.synthesis.assessment" },
  { key: "agreements", labelKey: "manager.synthesis.agreements" },
  { key: "conflicts", labelKey: "manager.synthesis.conflicts" },
  { key: "risks", labelKey: "manager.synthesis.risks" },
  { key: "open_questions", labelKey: "manager.synthesis.openQuestions" },
];

export default function Manager() {
  const { t } = useT();
  const [window_, setWindow] = useState<ManagerWindow>("yesterday");

  const configState = useFetch(
    (signal) => managerApi.config(signal),
    [],
    { formatError: (err) => formatFetchError(err, t("manager.config.errorFallback")) },
  );

  const changesState = useFetch(
    (signal) => managerApi.changes({ window: window_ }, signal),
    [window_],
    { formatError: (err) => formatFetchError(err, t("manager.changes.errorFallback")) },
  );

  const agentAvailable = configState.data?.agent_available ?? false;
  const agentReason = configState.data?.agent_reason ?? "";

  // --- Brief runner + poll (Phase C) --------------------------------------------------------------
  const [run, setRun] = useState<DeskRun | null>(null);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  // `GET /briefs/latest` 404s when no brief has ever run yet -- that is "no brief", not an error to
  // surface as a red banner, so the fetcher itself resolves `null` for that one status, matching the
  // "fetcher may resolve to a sentinel instead of rejecting" pattern `useFetch`'s own docstring names.
  const briefState = useFetch<Brief | null>(
    async (signal) => {
      try {
        return await managerApi.latestBrief(signal);
      } catch (err) {
        if (err instanceof ApiRequestError && err.status === 404) return null;
        throw err;
      }
    },
    [],
    { formatError: (err) => formatFetchError(err, t("manager.brief.errorFallback")) },
  );

  // Polls `run` every 2000ms while active -- mirrors `VibeTrading.tsx`'s/`AgentWorkflow.tsx`'s own
  // poll effect line for line. The dependency array (`run_id`, `state`) clears the interval the
  // moment `state` settles.
  useEffect(() => {
    if (!run || !isRunActive(run.state)) return;
    const runId = run.run_id;
    const id = setInterval(() => {
      managerApi
        .run(runId)
        .then((updated) => setRun(updated))
        .catch(() => {
          // A transient poll failure is not fatal -- the board keeps its last known state and the
          // next tick tries again.
        });
    }, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [run?.run_id, run?.state]);

  // Once the run settles, the brief it produced is stale -- refetch exactly once per terminal
  // transition.
  useEffect(() => {
    if (run && !isRunActive(run.state)) {
      briefState.reload();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `briefState.reload` is stable
    // (`useFetch`'s own `useCallback`); this effect keys on the run's own identity/state only,
    // mirroring `AgentWorkflow.tsx`'s identical terminal-transition effect.
  }, [run?.run_id, run?.state]);

  async function handleRunBrief() {
    setStarting(true);
    setStartError(null);
    try {
      const started = await managerApi.startBrief({ window: window_ });
      setRun(started);
    } catch (err) {
      setStartError(formatFetchError(err, t("manager.brief.startErrorFallback")));
    } finally {
      setStarting(false);
    }
  }

  const briefRunning = starting || (run !== null && isRunActive(run.state));

  return (
    <>
      <h1>{t("manager.title")}</h1>
      <p className="subtitle">{t("manager.subtitle")}</p>

      {/* Pinned: rendered unconditionally, before either fetch below has resolved, and unaffected
          by `agent_available`. Never gated behind a disclosure -- see this file's own docstring. */}
      <p className="disclaimer" data-testid="manager-not-advice">
        {t("manager.notAdvice")}
      </p>

      <section className="panel">
        <Fetched
          state={configState}
          loading={<p className="muted">{t("manager.config.loading")}</p>}
          error={(message) => <p className="callout callout-danger">{message}</p>}
        >
          {(config) => <ManagerHeader config={config} />}
        </Fetched>

        {/* EXP-04. Rendered OUTSIDE `<Fetched>` on purpose: what leaves this machine does not
            depend on the config fetch resolving, so the notice must not disappear when it fails.
            Visible summary, elaboration one click away -- never the other way round. */}
        <InfoNote
          className="mgr-egress"
          data-testid="manager-egress"
          summary={t("manager.egress")}
        >
          {t("manager.egress.detail")}
        </InfoNote>

        <div className="mgr-controls">
          <div
            className="mgr-window-toggle"
            role="tablist"
            aria-label={t("manager.window.ariaLabel")}
          >
            {WINDOW_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                role="tab"
                aria-selected={window_ === option.value}
                className={`timeframe-tab${window_ === option.value ? " active" : ""}`}
                onClick={() => setWindow(option.value)}
              >
                {t(option.labelKey)}
              </button>
            ))}
          </div>
          <SnapshotButton onSnapshotted={changesState.reload} />
        </div>
      </section>

      <Fetched
        state={changesState}
        loading={<p className="muted">{t("manager.changes.loading")}</p>}
        error={(message) => <p className="callout callout-danger">{message}</p>}
      >
        {(changeSet) => <ChangesView changeSet={changeSet} window={window_} />}
      </Fetched>

      <section className="panel" data-testid="manager-brief-section">
        <h2>{t("manager.brief.heading")}</h2>
        <div className="mgr-brief-controls">
          <button
            type="button"
            onClick={() => void handleRunBrief()}
            disabled={!agentAvailable || briefRunning}
            title={!agentAvailable ? agentReason : undefined}
          >
            {briefRunning ? t("manager.brief.running") : t("manager.brief.run")}
          </button>
          {run !== null && isRunActive(run.state) && <BriefProgress run={run} />}
          {startError && (
            <p className="callout callout-danger" role="alert">
              {startError}
            </p>
          )}
        </div>

        <Fetched
          state={briefState}
          loading={<p className="muted">{t("manager.brief.loading")}</p>}
          error={(message) => <p className="callout callout-danger">{message}</p>}
        >
          {(brief) =>
            brief === null ? (
              <p className="placeholder" data-testid="manager-brief-empty">
                {t("manager.brief.empty")}
              </p>
            ) : (
              <BriefView brief={brief} onCommissionChanged={briefState.reload} />
            )
          }
        </Fetched>
      </section>

      <ManagerChatPanel agentAvailable={agentAvailable} agentReason={agentReason} />
    </>
  );
}

/** Compact progress while a brief run is active: `{done}/{total}` plus one pill per stage
 *  (`MANAGER_STAGES`: collect, triage, synthesis, research_plan, commission, brief). */
function BriefProgress({ run }: { run: DeskRun }) {
  const { t } = useT();
  const total = run.stages.length;
  const done = run.stages.filter((s) => s.state === "succeeded" || s.state === "degraded").length;
  return (
    <div className="mgr-brief-progress" data-testid="manager-brief-progress">
      <span className="muted">{t("manager.brief.progress", { done, total })}</span>
      <div className="mgr-brief-stage-list">
        {run.stages.map((stage) => (
          <StatusPill
            key={stage.stage_id}
            tone={STAGE_TONE[stage.state]}
            label={`${stage.label || stage.role || stage.stage_id} · ${t(STAGE_LABEL_KEY[stage.state])}`}
          />
        ))}
      </div>
    </div>
  );
}

/** The loaded brief: header stats, synthesis, data health, commissions. */
function BriefView({ brief, onCommissionChanged }: { brief: Brief; onCommissionChanged: () => void }) {
  const { t } = useT();
  return (
    <div className="mgr-brief-view" data-testid="manager-brief-view">
      <div className="mgr-brief-meta">
        <StatusPill
          tone={brief.degraded ? "warn" : "ok"}
          label={t(brief.degraded ? "manager.brief.degraded" : "manager.brief.grounded")}
        />
        {/* UX-03. Every figure below -- the wash-sale counts especially -- is read off THIS
            snapshot, which is routinely older than the live Tax/Wash Sales pages. Without the date
            the two disagreeing reads look like a defect in one of them. `as_of` is the snapshot's
            own date, not `generated_at` (when the model wrote the brief about it). */}
        <span className="muted" data-testid="manager-brief-asof">
          {t("manager.brief.asOf", { date: brief.as_of })}
        </span>
        <span className="muted">{t("manager.brief.generatedAt", { at: brief.generated_at })}</span>
        <span className="muted">{t("manager.brief.cost", { cost: formatMoney(brief.cost_usd) })}</span>
      </div>

      <SynthesisView synthesis={brief.synthesis} />
      <DataHealthView dataHealth={brief.data_health} />
      <CommissionsView commissions={brief.commissions} onChanged={onCommissionChanged} />
    </div>
  );
}

/**
 * The brief's body.
 *
 * **Every word below this heading was written by the model, in English.** The bullets, their group
 * headings' contents and the caveat are grounded English prose keyed by nothing -- there is no id to
 * translate them by, and machine-translating a grounded artifact in place would put numbers through a
 * paraphrase. So the boundary is *labelled* instead: under 한국어 the section carries an "English
 * only" pill, and a Korean reader is told before reading rather than after. The flag-gated
 * on-display translation path (`TranslatedProse` / INVDASH_TRANSLATE_NARRATIVES, default off) is a
 * separate decision and is not wired here.
 */
function SynthesisView({ synthesis }: { synthesis: Synthesis }) {
  const { t, lang } = useT();
  return (
    <section className="mgr-synthesis" data-testid="manager-synthesis">
      <div className="mgr-synthesis-head">
        <h3>{t("manager.synthesis.heading")}</h3>
        {lang === "ko" && (
          <StatusPill
            tone="neutral"
            label={t("misc.pill.englishOnly")}
            detail={t("misc.pill.englishOnlyDetail")}
            data-testid="manager-synthesis-english-only"
          />
        )}
      </div>
      {SYNTHESIS_GROUPS.map((group) => (
        <SynthesisGroupView key={group.key} labelKey={group.labelKey} bullets={synthesis[group.key]} />
      ))}
      {/* Always rendered, unconditionally -- the not-advice line for this specific brief, same rule
          as `manager.notAdvice` for the page as a whole. */}
      <p className="callout" data-testid="manager-synthesis-caveat">
        {synthesis.caveat}
      </p>
    </section>
  );
}

/**
 * One synthesis group. A group with no bullets renders no heading at all (same rule the area grid
 * uses for an area with no items).
 *
 * **Density.** The model routinely writes three 200+ character paragraphs into a single group, which
 * rendered as one undifferentiated block -- the reader gets the first one and scrolls past the rest.
 * Past `SYNTHESIS_WALL_CHARS` across the group, the first bullet stays visible and the remainder move
 * into a collapsed "Read more". Nothing is deleted, and this never touches `Synthesis.caveat`, which
 * is rendered outside every group, unconditionally (docs/COPY-STYLE.md rules 5 and 6).
 */
function SynthesisGroupView({ labelKey, bullets }: { labelKey: MessageKey; bullets: BriefBullet[] }) {
  const { t } = useT();
  const first = bullets[0];
  if (first === undefined) return null;

  const rest = bullets.slice(1);
  const totalChars = bullets.reduce((sum, bullet) => sum + bullet.text.length, 0);
  const collapse = rest.length > 0 && totalChars > SYNTHESIS_WALL_CHARS;

  return (
    <div className="mgr-synthesis-group">
      <h4>{t(labelKey)}</h4>
      <ul className="mgr-synthesis-list">
        <SynthesisBulletRow bullet={first} />
        {!collapse && rest.map((bullet, i) => <SynthesisBulletRow key={i} bullet={bullet} />)}
      </ul>
      {collapse && (
        <Collapsible
          className="mgr-synthesis-more"
          data-testid="manager-synthesis-more"
          defaultOpen={false}
          title={<span className="mgr-synthesis-more-label">{t("manager.brief.readMore")}</span>}
        >
          <ul className="mgr-synthesis-list">
            {rest.map((bullet, i) => (
              <SynthesisBulletRow key={i} bullet={bullet} />
            ))}
          </ul>
        </Collapsible>
      )}
    </div>
  );
}

function SynthesisBulletRow({ bullet }: { bullet: BriefBullet }) {
  return (
    <li className="mgr-synthesis-bullet">
      <span>{bullet.text}</span>
      <RefChips refs={bullet.source_refs} />
    </li>
  );
}

/** `stale`/`unknown` source lists -- renders nothing when both are empty, matching the changes
 *  feed's own "no gaps panel when there is nothing missing" rule. */
function DataHealthView({ dataHealth }: { dataHealth: DataHealth }) {
  const { t } = useT();
  if (dataHealth.stale.length === 0 && dataHealth.unknown.length === 0) return null;
  return (
    <section className="mgr-data-health callout callout-warn" data-testid="manager-data-health">
      <h3>{t("manager.dataHealth.heading")}</h3>
      {/* UX-05: these are wire keys (`macro_snapshot`, `calendar_events`), not labels -- mapped
          through the freshness catalog's own en/ko labels, humanised when this build has not seen
          the key before, never thrown on. */}
      {dataHealth.stale.length > 0 && (
        <p>
          {t("manager.dataHealth.stale", {
            list: dataHealth.stale.map((key) => sourceLabel(t, key)).join(", "),
          })}
        </p>
      )}
      {dataHealth.unknown.length > 0 && (
        <p>
          {t("manager.dataHealth.unknown", {
            list: dataHealth.unknown.map((key) => sourceLabel(t, key)).join(", "),
          })}
        </p>
      )}
    </section>
  );
}

/** Research the manager proposes handing to a child desk -- renders nothing when there are none. */
function CommissionsView({
  commissions,
  onChanged,
}: {
  commissions: Commission[];
  onChanged: () => void;
}) {
  const { t } = useT();
  if (commissions.length === 0) return null;
  return (
    <section className="mgr-commissions" data-testid="manager-commissions">
      <h3>{t("manager.commissions.heading")}</h3>
      <p className="muted">{t("manager.commissions.note")}</p>
      <div className="mgr-commission-list">
        {commissions.map((commission) => (
          <CommissionRow key={commission.commission_id} commission={commission} onChanged={onChanged} />
        ))}
      </div>
    </section>
  );
}

function CommissionRow({ commission, onChanged }: { commission: Commission; onChanged: () => void }) {
  const { t } = useT();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function respond(action: "approve" | "decline") {
    setPending(true);
    setError(null);
    try {
      if (action === "approve") await managerApi.approveCommission(commission.commission_id);
      else await managerApi.declineCommission(commission.commission_id);
      onChanged();
    } catch (err) {
      setError(formatFetchError(err, t("manager.commissions.errorFallback")));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mgr-commission-row" data-testid="manager-commission-row">
      <div className="mgr-commission-head">
        {/* `kind` is a closed union of four known desk kinds -- rendered verbatim (no label map yet
            needed at four values), never a throwing exhaustiveness check over it. */}
        <span className="badge">{commission.kind}</span>
        <StatusPill tone={COMMISSION_TONE[commission.state]} label={t(COMMISSION_LABEL_KEY[commission.state])} />
      </div>
      <p className="mgr-commission-rationale">{commission.rationale}</p>
      {commission.child_summary !== "" &&
        (commission.state === "failed" ? (
          <CommissionFailure raw={commission.child_summary} />
        ) : (
          <p className="muted">{commission.child_summary}</p>
        ))}
      <RefChips refs={commission.source_refs} />
      {commission.state === "proposed" && (
        <div className="mgr-commission-actions">
          <button type="button" onClick={() => void respond("approve")} disabled={pending}>
            {t("manager.commissions.approve")}
          </button>
          <button type="button" onClick={() => void respond("decline")} disabled={pending}>
            {t("manager.commissions.decline")}
          </button>
        </div>
      )}
      {error && (
        <p className="callout callout-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * A failed commission's own account of what happened (UX-05).
 *
 * `child_summary` on a failure is whatever the child desk died with -- in practice a raw, often
 * truncated JSON payload carrying a provider message and a session id, which is what the row used
 * to print verbatim. The reader gets one sentence; the payload stays available (COPY-STYLE rule 5 --
 * the long form is moved, not deleted) behind the `InfoNote` disclosure, with session/request ids
 * stripped from BOTH the sentence and the payload, since neither the summary nor the disclosure is
 * a place for a call identifier.
 */
function CommissionFailure({ raw }: { raw: string }) {
  const { t } = useT();
  const scrubbed = scrubIds(raw, t("manager.commission.redacted"));
  const reason = failureReason(scrubbed) || t("manager.commission.state.failed");
  return (
    <InfoNote
      className="mgr-commission-failure"
      data-testid="manager-commission-failure"
      summary={t("manager.commission.failed", { reason })}
    >
      <pre className="mgr-commission-raw">{scrubbed}</pre>
    </InfoNote>
  );
}

/**
 * The manager chat -- forks `PersonaChat.tsx`'s idioms (thread list, transcript, degraded callout,
 * citation chips, composer) without importing it. Unlike `PersonaChat`, this component owns its own
 * fetches directly rather than taking them as props, the same split `PersonaDetail.tsx` makes for
 * the persona version but folded into this one page instead of a second owner component, since
 * Manager has no other place for it to live.
 */
function ManagerChatPanel({ agentAvailable, agentReason }: { agentAvailable: boolean; agentReason: string }) {
  const { t } = useT();
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [refreshFirst, setRefreshFirst] = useState(false);
  const [turnPending, setTurnPending] = useState(false);
  const [turnError, setTurnError] = useState<string | null>(null);
  // EXP-24: the thread a `ConfirmSheet` is currently asking about, or null. Deleting a thread
  // destroys its transcript, which is the half of `UsersPanel.tsx`'s rule that always confirms.
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const threadsState = useFetch(
    (signal) => managerApi.chats(signal),
    [],
    { formatError: (err) => formatFetchError(err, t("manager.chat.errorFallback")) },
  );

  const activeThreadState = useFetch<ManagerChatThread | null>(
    (signal) => (activeThreadId ? managerApi.chat(activeThreadId, signal) : Promise.resolve(null)),
    [activeThreadId],
    { formatError: (err) => formatFetchError(err, t("manager.chat.errorFallback")) },
  );

  async function handleNewThread() {
    setTurnError(null);
    try {
      const thread = await managerApi.createChat();
      threadsState.reload();
      setActiveThreadId(thread.thread_id);
    } catch (err) {
      setTurnError(formatFetchError(err, t("manager.chat.errorFallback")));
    }
  }

  async function handleDeleteThread(threadId: string) {
    setTurnError(null);
    setDeleting(true);
    try {
      await managerApi.deleteChat(threadId);
      if (activeThreadId === threadId) setActiveThreadId(null);
      threadsState.reload();
      setConfirmingDelete(null);
    } catch (err) {
      setTurnError(formatFetchError(err, t("manager.chat.errorFallback")));
      setConfirmingDelete(null);
    } finally {
      setDeleting(false);
    }
  }

  async function handleSend() {
    const trimmed = question.trim();
    if (!trimmed || !activeThreadId || turnPending) return;
    setTurnPending(true);
    setTurnError(null);
    try {
      await managerApi.sendTurn(activeThreadId, {
        question: trimmed,
        ...(refreshFirst ? { refresh: true } : {}),
      });
      setQuestion("");
      activeThreadState.reload();
      threadsState.reload();
    } catch (err) {
      setTurnError(formatFetchError(err, t("manager.chat.errorFallback")));
    } finally {
      setTurnPending(false);
    }
  }

  const threads = threadsState.data ?? [];
  const activeThread = activeThreadState.data ?? null;
  const canSend = activeThreadId !== null && question.trim().length > 0 && !turnPending && agentAvailable;

  return (
    <section className="panel mgr-chat" data-testid="manager-chat">
      <h2>{t("manager.chat.heading")}</h2>
      {/* Always visible, never behind a disclosure -- a reader sees the framing before an answer. */}
      <p className="muted mgr-chat-caveat">{t("manager.chat.caveat")}</p>

      {!agentAvailable && (
        <p className="callout callout-warn" data-testid="manager-chat-agent-down">
          {t("manager.chat.agentDown", { reason: agentReason })}
        </p>
      )}

      <div className="mgr-chat-thread-bar">
        <button type="button" onClick={() => void handleNewThread()} disabled={!agentAvailable}>
          {t("manager.chat.newThread")}
        </button>
        {threads.length > 0 && (
          <select
            className="mgr-chat-thread-select"
            aria-label={t("manager.chat.threadSelectLabel")}
            value={activeThreadId ?? ""}
            onChange={(e) => {
              if (e.target.value) setActiveThreadId(e.target.value);
            }}
          >
            <option value="" disabled>
              {t("manager.chat.threadSelectLabel")}
            </option>
            {threads.map((thread) => (
              <option key={thread.thread_id} value={thread.thread_id}>
                {thread.title || t("manager.chat.untitledThread")}
              </option>
            ))}
          </select>
        )}
        {activeThreadId !== null && (
          <button type="button" onClick={() => setConfirmingDelete(activeThreadId)}>
            {t("manager.chat.deleteThread")}
          </button>
        )}
      </div>

      <ConfirmSheet
        open={confirmingDelete !== null}
        question={t("manager.thread.deleteConfirm.title")}
        preview={t("manager.thread.deleteConfirm.body")}
        confirmLabel={t("manager.thread.deleteConfirm.confirm")}
        busy={deleting}
        tone="bad"
        onConfirm={() => {
          if (confirmingDelete !== null) void handleDeleteThread(confirmingDelete);
        }}
        onCancel={() => setConfirmingDelete(null)}
      />

      <ScrollRegion size="md" label={t("manager.chat.heading")}>
        {(activeThread?.turns ?? []).map((turn) => (
          <ManagerChatTurnView key={turn.turn_id} turn={turn} />
        ))}
        {turnPending && (
          <p className="placeholder" data-testid="manager-chat-pending">
            {t("manager.chat.pending")}
          </p>
        )}
        {turnError && (
          <p className="callout callout-danger" role="alert">
            {turnError}
          </p>
        )}
      </ScrollRegion>

      <div className="mgr-chat-composer">
        <label className="mgr-chat-field">
          <span>{t("manager.chat.questionLabel")}</span>
          <textarea
            rows={2}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={t("manager.chat.questionPlaceholder")}
            disabled={!activeThreadId || turnPending || !agentAvailable}
          />
        </label>
        <label className="mgr-chat-refresh">
          <input
            type="checkbox"
            checked={refreshFirst}
            onChange={(e) => setRefreshFirst(e.target.checked)}
            disabled={!activeThreadId || turnPending}
          />
          {t("manager.chat.refreshFirst")}
        </label>
        <div className="mgr-chat-send-row">
          <button type="button" onClick={() => void handleSend()} disabled={!canSend}>
            {t("manager.chat.send")}
          </button>
        </div>
      </div>
    </section>
  );
}

/** One question/answer exchange. `turn.degraded` gates the fact-check-failure callout, same rule
 *  `PersonaChat.tsx`'s `ChatTurnView` uses for its own `ChatTurn.degraded`/`.grounding` pair. */
function ManagerChatTurnView({ turn }: { turn: ManagerChatTurn }) {
  const { t } = useT();
  return (
    <div className="mgr-chat-turn" data-testid="manager-chat-turn">
      <p className="mgr-chat-question">
        <span className="muted">{t("manager.chat.youAsked")}:</span> {turn.question}
      </p>

      {turn.degraded && (
        <div className="callout callout-warn mgr-chat-degraded" role="alert" data-testid="manager-chat-degraded">
          <StatusPill tone="warn" label={t("ui.pill.unverified")} />{" "}
          <strong>{t("manager.chat.factCheckFailed")}</strong>
          {turn.grounding.issues.length > 0 && (
            <ul className="mgr-chat-grounding-issues">
              {turn.grounding.issues.map((issue, i) => (
                <li key={i}>{issue.detail}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <p className="mgr-chat-answer">{turn.answer}</p>

      <RefChips refs={turn.source_refs} />

      {turn.commissions.length > 0 && (
        <div className="mgr-chat-turn-commissions">
          {turn.commissions.map((commission) => (
            <span key={commission.commission_id} className="badge">
              {commission.kind}: {t(COMMISSION_LABEL_KEY[commission.state])}
            </span>
          ))}
        </div>
      )}

      <p className="muted mgr-chat-turn-cost">
        {t("manager.chat.turnCost", { cost: formatMoney(turn.cost_usd) })}
      </p>
    </div>
  );
}

/** The header's stat strip: agent status, last snapshot, spend vs. cap, autonomy. Split out of
 *  `Manager` so it can be handed straight to `<Fetched>` as the loaded-state renderer. */
function ManagerHeader({ config }: { config: ManagerConfig }) {
  const { t } = useT();
  return (
    <div className="mgr-header-stats">
      <StatusPill
        tone={config.agent_available ? "ok" : "warn"}
        label={t(config.agent_available ? "manager.header.agentConnected" : "manager.header.agentDown")}
        detail={config.agent_available ? undefined : config.agent_reason}
      />
      <div className="stat">
        <span className="label">{t("manager.header.lastSnapshot")}</span>
        <span className="value">{config.last_snapshot_at ?? t("manager.header.never")}</span>
      </div>
      <div className="stat">
        <span className="label">{t("manager.header.spentToday")}</span>
        <span className="value">
          {t("manager.header.spentTodayValue", {
            spent: formatMoney(config.spent_today_usd),
            cap: formatMoney(config.caps.daily_usd),
          })}
        </span>
      </div>
      <div className="stat">
        <span className="label">{t("manager.header.autonomy")}</span>
        {/* `autonomy` is an arbitrary backend-supplied string, not a closed union this build knows
            every member of -- rendered verbatim rather than mapped through a switch, matching this
            codebase's rule for server-supplied vocabulary (see `UniverseMode`'s doc comment in
            `@/api/workflow`). */}
        <span className="value">{config.autonomy}</span>
      </div>
      {/* This page is the delta -- what moved since the last snapshot. The standing state it moved
          FROM lives on Overview, and a reader who wants "so where does that leave me" had no way
          across from here. */}
      <Link className="mgr-header-link" to="/overview">
        {t("manager.header.overviewLink")}
      </Link>
    </div>
  );
}

function SnapshotButton({ onSnapshotted }: { onSnapshotted: () => void }) {
  const { t } = useT();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick() {
    setPending(true);
    setError(null);
    try {
      await managerApi.snapshot();
      onSnapshotted();
    } catch (err) {
      setError(formatFetchError(err, t("manager.snapshot.errorFallback")));
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <button type="button" onClick={() => void handleClick()} disabled={pending}>
        {pending ? t("manager.snapshot.pending") : t("manager.snapshot.button")}
      </button>
      {error && (
        <p className="callout callout-danger" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

/** The loaded change feed: attention panel, per-area grid, gaps, and the empty state -- all derived
 *  from one `ChangeSet`, never gated on `config`/`agent_available`. */
function ChangesView({ changeSet, window: activeWindow }: { changeSet: ChangeSet; window: ManagerWindow }) {
  const { t } = useT();
  const attentionItems = changeSet.items.filter((item) => item.severity === "attention");
  const otherItems = changeSet.items.filter((item) => item.severity !== "attention");
  const hasGaps = changeSet.sections_missing.length > 0 || changeSet.warnings.length > 0;
  const windowLabel = t(
    WINDOW_OPTIONS.find((w) => w.value === activeWindow)?.labelKey ?? "manager.window.yesterday",
  );
  // The heading names the delta this panel actually shows. Overview's own "Attention" panel answers
  // a different question -- what the standing portfolio looks like right now -- and two panels on
  // two pages sharing one word made them read as the same list. `since` is the comparison point the
  // feed was built against; with no prior snapshot there is none, so the window itself is the
  // honest stand-in (the `manager.since.none` callout above already says the comparison is missing).
  const attentionHeading = t("manager.attention.heading", {
    since: changeSet.since ?? windowLabel,
  });

  return (
    <>
      {changeSet.since === null && (
        <p className="callout callout-warn" data-testid="manager-since-none">
          {t("manager.since.none")}
        </p>
      )}

      <section className="panel">
        <h2>{attentionHeading}</h2>
        {attentionItems.length === 0 ? (
          <p className="placeholder">{t("manager.attention.empty")}</p>
        ) : (
          <ScrollRegion size="sm" label={attentionHeading}>
            <div className="mgr-attention-list">
              {attentionItems.map((item) => (
                <AttentionRow key={item.id} item={item} />
              ))}
            </div>
          </ScrollRegion>
        )}
      </section>

      {changeSet.items.length === 0 ? (
        <p className="placeholder" data-testid="manager-empty">
          {t("manager.empty", {
            window: windowLabel,
            since: changeSet.since ?? t("manager.header.never"),
          })}
        </p>
      ) : (
        <>
          <h2>{t("manager.byArea.heading")}</h2>
          <CardGrid height="md">
            {AREA_ORDER.map((area) => {
              const items = otherItems.filter((item) => item.area === area);
              if (items.length === 0) return null;
              return <AreaCard key={area} area={area} items={items} />;
            })}
          </CardGrid>
        </>
      )}

      {hasGaps && (
        <section className="panel callout callout-warn" data-testid="manager-gaps">
          <h2>{t("manager.gaps.heading")}</h2>
          {changeSet.sections_missing.length > 0 && (
            <>
              <h3>{t("manager.gaps.sectionsMissing")}</h3>
              <ul className="mgr-gaps-list">
                {changeSet.sections_missing.map((section) => (
                  <li key={section}>{section}</li>
                ))}
              </ul>
            </>
          )}
          {changeSet.warnings.length > 0 && (
            <>
              <h3>{t("manager.gaps.warnings")}</h3>
              <ul className="mgr-gaps-list">
                {changeSet.warnings.map((warning, i) => (
                  // Warning strings have no stable id on the wire -- index is safe here because this
                  // list is never reordered or individually removed, only replaced wholesale on refetch.
                  <li key={i}>{warning}</li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
    </>
  );
}

function AttentionRow({ item }: { item: ChangeItem }) {
  const { t } = useT();
  return (
    <div className="mgr-attention-row">
      {/* Decorative: every row in this panel is `severity === "attention"` by construction (the
          panel's own heading already says so), so the glyph is not the sole signal here -- see
          `Glyph.tsx`'s own docstring on when `label` is warranted and when it is not. */}
      <Glyph name={SEVERITY_GLYPH[item.severity]} />
      <span className="mgr-attention-headline">{item.headline}</span>
      <span className="badge">{t(AREA_LABEL_KEY[item.area])}</span>
      <RefChips refs={item.source_refs} />
    </div>
  );
}

/** One area's changes as a `Card` in the shared grid: the head (heading + expand) stays put, the
 *  list scrolls inside the track height the grid hands every card in the row. `id` is what keys the
 *  grid's one-at-a-time expansion into `?card=`, so an expanded area survives a reload. */
function AreaCard({ area, items }: { area: Area; items: ChangeItem[] }) {
  const { t } = useT();
  const label = t(AREA_LABEL_KEY[area]);
  return (
    <Card
      id={`area-${area}`}
      height="md"
      label={label}
      title={<h3>{t("manager.area.heading", { label, count: items.length })}</h3>}
      expandable
    >
      <div className="mgr-area-list">
        {items.map((item) => (
          <ChangeRow key={item.id} item={item} />
        ))}
      </div>
    </Card>
  );
}

function ChangeRow({ item }: { item: ChangeItem }) {
  const { t } = useT();
  const figureEntries = Object.entries(item.figures);
  return (
    <div className="mgr-change-row">
      <div className="mgr-change-headline">
        <StatusPill tone={SEVERITY_TONE[item.severity]} label={t(SEVERITY_LABEL_KEY[item.severity])} />{" "}
        {item.headline}
      </div>
      {item.detail && <p className="mgr-change-detail muted">{item.detail}</p>}
      {figureEntries.length > 0 && (
        <div className="mgr-change-figures">
          {figureEntries.map(([key, value]) => (
            <span key={key}>{figureText(t, key, value)}</span>
          ))}
        </div>
      )}
      <RefChips refs={item.source_refs} />
    </div>
  );
}

/**
 * Renders each `SourceRef` as a small chip -- a real link when this build knows the target has a
 * page, a plain (non-link) chip otherwise. Never renders a link to a route this app does not
 * actually register: `symbol` links to `/symbol/:symbol` (the real registered route -- see
 * `App.tsx`; NOT `/symbol?symbol=`, which is not a route this app has), `persona` links to the
 * `/personas` list page. Every other `kind` (`run`, `note`, `event`, `gen`, `snapshot`, `txn`,
 * `seat`) has no confirmed destination in this phase, so it renders as plain text rather than a
 * broken link.
 */
function RefChips({ refs }: { refs: SourceRef[] }) {
  if (refs.length === 0) return null;
  return (
    <div className="mgr-ref-chips">
      {refs.map((ref) => {
        const key = `${ref.kind}:${ref.id}`;
        if (ref.kind === "symbol") {
          return (
            <Link key={key} to={`/symbol/${encodeURIComponent(ref.id)}`} className="mgr-ref-chip">
              {ref.label}
            </Link>
          );
        }
        if (ref.kind === "persona") {
          return (
            <Link key={key} to="/personas" className="mgr-ref-chip">
              {ref.label}
            </Link>
          );
        }
        return (
          <span key={key} className="mgr-ref-chip">
            {ref.label}
          </span>
        );
      })}
    </div>
  );
}
