/**
 * Backfill Tasks: the manual bridge between this app's persona notes and an external LLM.
 *
 * The pipeline is deliberately half outside this app. A task packet (source video + prompt,
 * assembled server-side) is copied to the clipboard here, pasted into an external agent
 * (Gemini/ChatGPT) by hand, and that agent's reply is pasted back into this page. Nothing this app
 * runs can see what happened in between -- `validate`/ingest are the only checks it can perform, and
 * only against whatever text actually comes back.
 *
 * Four things happen on this page, per `docs/AGENT-DESK-CONTRACT.md`'s pinned `/api/backfill`
 * contract (`api/backfill.ts`):
 *
 * 1. **List** pending task packets (`GET /tasks`).
 * 2. **Generate** new ones (`POST /generate`) -- slow, since it fetches fresh source video on the
 *    backend, so this renders a busy state rather than assuming it returns promptly.
 * 3. **Copy** one packet's full markdown to the clipboard (`GET /tasks/{video_id}`, then
 *    `navigator.clipboard.writeText`). A page with no clipboard access (an insecure context, an
 *    older browser, a locked-down test runner) falls back to a selectable textarea instead of
 *    failing silently.
 * 4. **Validate** and **ingest** a pasted reply (`POST /validate`, `POST /tasks/{video_id}/result`).
 *    A successful ingest removes the task from the list and shows how many tickers it mentioned; a
 *    422 shows the backend's own `reasons` rather than a generic failure line.
 *
 * **Every server string renders through a lookup with a fallback, never a throwing `switch`.** The
 * fields this page renders (`persona_name`, `title`, `published`, error `detail`, validation
 * `reasons`) are all open strings the backend can extend or leave empty at any time -- exactly the
 * shape `docs/closed-unions-over-server-data-kill-pages` warns a throwing exhaustiveness check takes
 * a whole page down over. Nothing here switches on a server value; everything renders it, or a
 * placeholder, directly.
 */
import { useCallback, useState } from "react";

import {
  backfillApi,
  BackfillIngestError,
  type TaskRef,
  type ValidateResult,
} from "@/api/backfill";
import InfoNote from "@/components/InfoNote";
import PanelBoundary from "@/components/PanelBoundary";
import ScrollPanel from "@/components/ScrollPanel";
import StatusPill from "@/components/StatusPill";
import { formatFetchError as errorMessage, useFetch } from "@/hooks/useFetch";
import { useT, type Translator } from "@/i18n";
import { safeHref } from "@/safeHref";

import "./BackfillTasks.css";

/**
 * The whole queue -- generate, list, copy, paste back, validate, ingest -- with no `<h1>`.
 *
 * Backfill is no longer its own nav destination: it is a panel on `/personas` (`Personas.tsx`),
 * opened from a button beside that page's heading, because it feeds the same per-influencer notes
 * that page lists rather than being a desk of its own. The heading moved to the default export
 * below; nothing else about the flow changed.
 */
export function BackfillSection() {
  const { t, lang } = useT();

  // --- task list ---------------------------------------------------------------------------------
  // `lang` (not `t`) drives the re-fetch, matching the original `loadTasks` `useCallback`'s own `[t]`
  // dependency array -- `t`'s own identity already changes with `lang`, and `useFetch` reads
  // `formatError` via a ref rather than as a dependency, so `lang` is named directly here.
  const tasksResult = useFetch(() => backfillApi.listTasks().then((res) => res.tasks), [lang], {
    formatError: (err) => errorMessage(err, t("backfill.errors.list")),
  });
  const tasks = tasksResult.data ?? [];
  const listPhase = tasksResult.phase;
  const listError = tasksResult.error;
  const loadTasks = tasksResult.reload;

  // --- generate ------------------------------------------------------------------------------------
  const [limit, setLimit] = useState("");
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generateMessage, setGenerateMessage] = useState<string | null>(null);

  const handleGenerate = async () => {
    setGenerating(true);
    setGenerateError(null);
    setGenerateMessage(null);
    try {
      const parsedLimit = limit.trim() !== "" ? Number.parseInt(limit, 10) : NaN;
      const result = await backfillApi.generate(
        Number.isFinite(parsedLimit) ? { limit: parsedLimit } : {},
      );
      setGenerateMessage(t("backfill.toolbar.generatedCount", { written: result.written }));
      loadTasks();
    } catch (err) {
      setGenerateError(errorMessage(err, t("backfill.errors.generate")));
    } finally {
      setGenerating(false);
    }
  };

  // A task disappears from the list the moment it is ingested (handled by each `TaskCard` calling
  // back up here) -- this banner is the one place that confirms it happened and by how much.
  const [ingestedMessage, setIngestedMessage] = useState<string | null>(null);
  const handleIngested = useCallback((videoId: string, mentionCount: number) => {
    tasksResult.setData((prev) => (prev ?? []).filter((task) => task.video_id !== videoId));
    setIngestedMessage(t("backfill.ingest.success", { count: mentionCount }));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `tasksResult.setData` is stable.
  }, [t]);

  return (
    <>
      <p className="subtitle">{t("backfill.subtitle")}</p>

      <PanelBoundary label={t("backfill.list.heading")}>
        <section className="panel">
          <div className="wf-book-toolbar">
            {/* `<label htmlFor>` next to the input, not a `<label>` wrapped around a `<span>` and
                the field. The wrapped form left both children as inline boxes sharing one line box,
                so the label text sat on the FIELD's baseline -- fine for a one-line input, and the
                reason the identical construction under "Agent reply" put its label at the foot of an
                eight-row textarea. Explicit `htmlFor`/`id` also survives any later CSS that reorders
                the pair, which a wrapper does not. */}
            <div className="backfill-field backfill-field-inline">
              <label className="backfill-field-label" htmlFor="backfill-limit">
                {t("backfill.toolbar.limitLabel")}
              </label>
              <input
                id="backfill-limit"
                type="text"
                inputMode="numeric"
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
              />
            </div>
            <button type="button" onClick={() => void handleGenerate()} disabled={generating}>
              {generating ? t("backfill.toolbar.generating") : t("backfill.toolbar.generate")}
            </button>
          </div>
          {generateError && <p className="callout callout-danger">{generateError}</p>}
          {generateMessage && <p className="callout callout-warn">{generateMessage}</p>}
          {ingestedMessage && <p className="callout callout-warn">{ingestedMessage}</p>}

          <h2>
            {t("backfill.list.heading")}
            {listPhase === "loaded" && (
              <span className="muted"> {t("backfill.list.countLabel", { count: tasks.length })}</span>
            )}
          </h2>

          {listPhase === "loading" && <p className="muted">{t("backfill.list.loading")}</p>}
          {listPhase === "error" && <p className="callout callout-danger">{listError}</p>}
          {listPhase === "loaded" && tasks.length === 0 && (
            <p className="muted">{t("backfill.list.empty")}</p>
          )}

          {listPhase === "loaded" && tasks.length > 0 && (
            <ScrollPanel label={t("backfill.list.heading")} size="lg">
              {tasks.map((task) => (
                <TaskCard key={task.video_id} task={task} onIngested={handleIngested} t={t} />
              ))}
            </ScrollPanel>
          )}
        </section>
      </PanelBoundary>
    </>
  );
}

/**
 * The standalone page form: the heading plus the section above.
 *
 * `/backfill` now redirects to `/personas?panel=backfill` (see `App.tsx`), so nothing routes here.
 * Kept for the same reason `WashSales.tsx` and `Thesis.tsx` keep theirs -- the page's `<h1>` is a
 * separate thing from the surface that moved.
 */
export default function BackfillTasks() {
  const { t } = useT();
  return (
    <>
      <h1>{t("backfill.title")}</h1>
      <BackfillSection />
    </>
  );
}

type CopyPhase = "idle" | "loading" | "copied" | "error";

/**
 * One pending task: its identity, the copy-to-clipboard action, and the paste-back / validate /
 * ingest flow. Kept as its own component (rather than inlined in the list) because each task carries
 * a full set of independent state -- a reader may have five packets copied and be mid-paste on two
 * of them at once, and none of that can live on the parent without keying half a dozen state maps by
 * `video_id`.
 */
function TaskCard({
  task,
  onIngested,
  t,
}: {
  task: TaskRef;
  onIngested: (videoId: string, mentionCount: number) => void;
  t: Translator;
}) {
  // --- copy ----------------------------------------------------------------------------------------
  const [copyPhase, setCopyPhase] = useState<CopyPhase>("idle");
  const [copyError, setCopyError] = useState<string | null>(null);
  const [fallbackMarkdown, setFallbackMarkdown] = useState<string | null>(null);

  const handleCopy = async () => {
    setCopyPhase("loading");
    setCopyError(null);
    setFallbackMarkdown(null);
    try {
      const detail = await backfillApi.getTask(task.video_id);
      const clipboard = typeof navigator === "undefined" ? undefined : navigator.clipboard;
      if (clipboard && typeof clipboard.writeText === "function") {
        await clipboard.writeText(detail.markdown);
        setCopyPhase("copied");
      } else {
        // No clipboard access (insecure context, an older browser, a locked-down runner) -- the
        // packet is still shown, just not auto-copied, so the flow degrades instead of failing.
        setFallbackMarkdown(detail.markdown);
        setCopyPhase("idle");
      }
    } catch (err) {
      setCopyError(errorMessage(err, t("backfill.errors.copy")));
      setCopyPhase("error");
    }
  };

  // --- paste back / validate / ingest ---------------------------------------------------------------
  const [pasteText, setPasteText] = useState("");

  const [validating, setValidating] = useState(false);
  const [validateResult, setValidateResult] = useState<ValidateResult | null>(null);
  const [validateError, setValidateError] = useState<string | null>(null);

  const handleValidate = async () => {
    setValidating(true);
    setValidateError(null);
    setValidateResult(null);
    try {
      const result = await backfillApi.validate({ video_id: task.video_id, text: pasteText });
      setValidateResult(result);
    } catch (err) {
      setValidateError(errorMessage(err, t("backfill.errors.validate")));
    } finally {
      setValidating(false);
    }
  };

  const [ingesting, setIngesting] = useState(false);
  const [ingestError, setIngestError] = useState<string | null>(null);
  const [ingestReasons, setIngestReasons] = useState<string[]>([]);

  const handleIngest = async () => {
    setIngesting(true);
    setIngestError(null);
    setIngestReasons([]);
    try {
      const result = await backfillApi.ingestResult(task.video_id, pasteText);
      onIngested(task.video_id, result.mention_count);
    } catch (err) {
      // `BackfillIngestError` (a 422) carries `reasons` alongside `detail`; every other failure
      // (404 already-gone, 409 already-ingested, a network error) is a plain message.
      if (err instanceof BackfillIngestError) {
        setIngestError(err.message);
        setIngestReasons(err.reasons);
      } else {
        setIngestError(errorMessage(err, t("backfill.errors.ingest")));
      }
    } finally {
      setIngesting(false);
    }
  };

  const pasteEmpty = pasteText.trim() === "";
  const taskHref = safeHref(task.url);

  return (
    <div className="panel backfill-task-card">
      <h3>{task.title || t("backfill.list.untitled")}</h3>
      <p className="muted">
        {task.persona_name} · {task.published || t("backfill.list.noDate")}
      </p>
      <p>
        {taskHref === null ? (
          <span>{task.url}</span>
        ) : (
          <a href={taskHref} target="_blank" rel="noopener noreferrer">
            {task.url}
          </a>
        )}
      </p>

      <div className="backfill-task-copy-row">
        <button type="button" onClick={() => void handleCopy()} disabled={copyPhase === "loading"}>
          {copyPhase === "loading" ? t("backfill.task.copying") : t("backfill.task.copyButton")}
        </button>
        {copyPhase === "copied" && <StatusPill tone="ok" label={t("backfill.task.copied")} />}
      </div>
      {copyError && <p className="callout callout-danger">{copyError}</p>}
      {fallbackMarkdown !== null && (
        <InfoNote summary={t("backfill.task.copyFallbackNote")} defaultOpen>
          <textarea
            readOnly
            rows={8}
            value={fallbackMarkdown}
            aria-label={t("backfill.task.copyFallbackNote")}
            onFocus={(e) => e.currentTarget.select()}
          />
        </InfoNote>
      )}

      {/* Per-card id: several `TaskCard`s are on the page at once, and a duplicated `htmlFor`
          target points every label at whichever textarea rendered first. `video_id` is the list's
          own key, so it is already unique here. */}
      <div className="backfill-field backfill-task-paste">
        <label className="backfill-field-label" htmlFor={`backfill-paste-${task.video_id}`}>
          {t("backfill.task.pasteLabel")}
        </label>
        <textarea
          id={`backfill-paste-${task.video_id}`}
          rows={8}
          placeholder={t("backfill.task.pastePlaceholder")}
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
        />
      </div>

      <div className="backfill-task-actions">
        <button type="button" onClick={() => void handleValidate()} disabled={validating || pasteEmpty}>
          {validating ? t("backfill.task.validating") : t("backfill.task.validateButton")}
        </button>
        <button type="button" onClick={() => void handleIngest()} disabled={ingesting || pasteEmpty}>
          {ingesting ? t("backfill.task.ingesting") : t("backfill.task.ingestButton")}
        </button>
      </div>

      {validateError && <p className="callout callout-danger">{validateError}</p>}
      {validateResult && (
        <div className={`callout ${validateResult.ok ? "callout-warn" : "callout-danger"}`}>
          <strong>
            {validateResult.ok ? t("backfill.validate.ok") : t("backfill.validate.failed")}
          </strong>
          <ReasonList heading={t("backfill.validate.reasonsHeading")} items={validateResult.reasons} />
          <ReasonList
            heading={t("backfill.validate.droppedSymbolsHeading")}
            items={validateResult.dropped_symbols}
          />
          <ReasonList
            heading={t("backfill.validate.ungroundedNumbersHeading")}
            items={validateResult.ungrounded_numbers}
          />
        </div>
      )}

      {ingestError && (
        <div className="callout callout-danger">
          <p>{ingestError}</p>
          <ReasonList heading={t("backfill.ingest.reasonsHeading")} items={ingestReasons} />
        </div>
      )}
    </div>
  );
}

/** A labelled bullet list, or nothing at all when there is nothing to show -- shared by the
 *  validate and ingest error panels above, which between them render three server-supplied string
 *  arrays (`reasons`, `dropped_symbols`, `ungrounded_numbers`) in the identical shape. */
function ReasonList({ heading, items }: { heading: string; items: readonly string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      <p>{heading}</p>
      <ul>
        {items.map((item, i) => (
          <li key={`${i}-${item}`}>{item}</li>
        ))}
      </ul>
    </>
  );
}
