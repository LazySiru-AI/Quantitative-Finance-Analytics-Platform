/**
 * Import panel: the affordance for the one thing this application could not do from its own UI.
 *
 * Until now every empty state in the app told the user to "drop broker exports into `data/` and
 * rebuild" — naming a step that existed nowhere. This panel is that step, and it is built around
 * three things the endpoint's shape makes necessary:
 *
 * **It shows the attribution before it applies it.** Which account a file belongs to is the one
 * input in this pipeline nothing can validate: a Robinhood taxable export and a Robinhood Roth
 * export are structurally identical, and only the user knows which is which. So the preview names
 * the account and tax treatment each file would land in, and it is deliberately the widest column
 * in the table.
 *
 * **"No account declared" is an instruction, not an error.** It is the normal first-run state. The
 * panel answers it with the command that fixes it rather than with a red row the user cannot act
 * on.
 *
 * **Conflicts are not a footnote.** A conflict means a stored row disagreed with the incoming one
 * and was left alone — possibly a figure already reported on a tax form. They render in full,
 * above the per-file table, and they make the run read as unsuccessful.
 *
 * There is no file picker, because there is no upload: the server imports what is already in its
 * data directory. Offering a picker would misrepresent what the button does.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { describeError } from "@/api/client";
import {
  importApi,
  statusLabel,
  statusTone,
  type FileDecision,
  type FileImport,
  type ImportPlan,
  type ImportRunResult,
  type PlannedFile,
} from "@/api/imports";
import ImportDecisionRow, {
  initialDecision,
  toDecision,
  type DecisionState,
} from "@/components/ImportDecisionRow";
import { t as translateNow, Trans, useT } from "@/i18n";

type Phase = "loading" | "ready" | "error";

export default function ImportPanel({ onImported }: { onImported?: () => void }) {
  const { t } = useT();
  const [plan, setPlan] = useState<ImportPlan | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [result, setResult] = useState<ImportRunResult | null>(null);
  const [running, setRunning] = useState(false);
  // Keyed by filename. Rebuilt whenever a preview lands, so a file that has since been declared
  // stops offering a choice it no longer needs.
  const [decisions, setDecisions] = useState<Record<string, DecisionState>>({});

  const load = useCallback((signal?: AbortSignal) => {
    setPhase("loading");
    importApi
      .preview(signal)
      .then((next) => {
        setPlan(next);
        setPhase("ready");
        setDecisions(
          Object.fromEntries(
            next.files
              .filter((file) => file.status === "undeclared")
              .map((file) => [file.filename, initialDecision(file)]),
          ),
        );
      })
      .catch((error: unknown) => {
        if (signal?.aborted) return;
        // `translateNow` rather than the hook's `t`: this closure is memoized with an empty
        // dependency list so `load` keeps one stable identity across the component's life (it is
        // also called imperatively from `runImport`, not just from the mount effect) -- closing
        // over the hook's `t` would either go stale after a language switch or, if added to the
        // dependency list, recreate `load` on every toggle and re-trigger the mount effect's fetch.
        // The module-level function reads the current language at call time instead.
        setMessage(describeError(error, translateNow("activity.import.error.generic")));
        setPhase("error");
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const undeclared = useMemo(
    () => (plan?.files ?? []).filter((file) => file.status === "undeclared"),
    [plan],
  );

  const pending: FileDecision[] = useMemo(
    () =>
      undeclared
        .map((file) => toDecision(file.filename, decisions[file.filename] ?? initialDecision(file)))
        .filter((decision): decision is FileDecision => decision !== null),
    [undeclared, decisions],
  );

  const runImport = useCallback(() => {
    setRunning(true);
    setMessage(null);
    // Only the files that already have an account, plus the ones being given one now. A file left
    // as "leave it alone" is not named, so it is not touched.
    const named = [
      ...(plan?.files ?? [])
        .filter((file) => file.status === "imported")
        .map((file) => file.filename),
      ...pending.map((decision) => decision.filename),
    ];
    importApi
      .run(named.length > 0 ? named : undefined, pending)
      .then((next) => {
        setResult(next);
        // Re-previewing is not cosmetic: files that imported now read "already imported", which is
        // what stops a second click from looking like it will do the same work again.
        load();
        if (next.inserted > 0) onImported?.();
      })
      .catch((error: unknown) =>
        setMessage(describeError(error, translateNow("activity.import.error.generic"))),
      )
      .finally(() => setRunning(false));
  }, [load, onImported, plan, pending]);

  return (
    <section className="panel import-panel">
      <div className="import-head">
        <h2>{t("activity.import.heading")}</h2>
        {plan && (
          <span className="muted import-dir" title={plan.data_dir}>
            {t("activity.import.readingDir", { dir: plan.data_dir })}
          </span>
        )}
      </div>

      {phase === "loading" && <div className="placeholder">{t("activity.import.looking")}</div>}
      {phase === "error" && <div className="placeholder">{message}</div>}

      {phase === "ready" && plan && (
        <>
          {plan.files.length === 0 ? (
            <div className="placeholder">
              <Trans k="activity.import.empty.body" values={{ dir: <code>{plan.data_dir}</code> }} />
            </div>
          ) : (
            <>
              <ManifestNotice plan={plan} />
              <PlanTable files={plan.files} />

              {undeclared.length > 0 && (
                <div className="import-decisions">
                  <h3>{t("activity.import.decisions.heading")}</h3>
                  <p className="muted import-decisions-intro">
                    <Trans
                      k="activity.import.decisions.intro"
                      values={{ can: <em>{t("activity.import.decisions.canWord")}</em> }}
                    />
                  </p>
                  {undeclared.map((file) => (
                    <ImportDecisionRow
                      key={file.filename}
                      file={file}
                      state={decisions[file.filename] ?? initialDecision(file)}
                      onChange={(next) =>
                        setDecisions((prev) => ({ ...prev, [file.filename]: next }))
                      }
                    />
                  ))}
                </div>
              )}

              <div className="import-actions">
                <button
                  type="button"
                  className="symbol-submit"
                  disabled={plan.importable + pending.length === 0 || running}
                  onClick={runImport}
                >
                  {running
                    ? t("activity.import.action.running")
                    : t(
                        plan.importable + pending.length === 1
                          ? "activity.import.action.file_one"
                          : "activity.import.action.file_other",
                        { count: plan.importable + pending.length },
                      )}
                </button>
                <span className="muted">{t("activity.import.action.hint")}</span>
              </div>
              {message && <div className="callout callout-danger panel">{message}</div>}
            </>
          )}

          {result && <RunResult result={result} />}
        </>
      )}
    </section>
  );
}

/**
 * The manifest's state, when it needs stating.
 *
 * Silent when the manifest is complete — a panel that explains a solved problem on every visit
 * trains the reader to skip the place the real problems appear.
 */
function ManifestNotice({ plan }: { plan: ImportPlan }) {
  const { t } = useT();
  const undeclared = plan.files.filter((f) => f.status === "undeclared").length;

  if (plan.manifest.error) {
    return (
      <div className="callout callout-danger import-notice">
        <strong>{t("activity.import.manifest.readError", { path: plan.manifest.path })}</strong>
        <p>{plan.manifest.error}</p>
      </div>
    );
  }

  if (!plan.manifest.present) {
    return (
      <div className="callout callout-warn import-notice">
        <strong>{t("activity.import.manifest.noneTitle")}</strong>
        <p>
          <Trans
            k="activity.import.manifest.noneBody"
            values={{ path: <code>{plan.manifest.path}</code> }}
          />
        </p>
        <pre className="import-command">python -m app.ingest --init</pre>
        <p className="muted">
          <Trans
            k="activity.import.manifest.noneHint"
            values={{ field: <code>tax_treatment</code> }}
          />
        </p>
      </div>
    );
  }

  if (undeclared > 0) {
    return (
      <div className="callout callout-warn import-notice">
        <strong>
          {t(undeclared === 1 ? "activity.import.manifest.undeclared_one" : "activity.import.manifest.undeclared_other", {
            count: undeclared,
            path: plan.manifest.path,
          })}
        </strong>
        <p>
          <Trans
            k="activity.import.manifest.undeclaredHint"
            values={{ entry: <code>[[account]]</code> }}
          />
        </p>
      </div>
    );
  }

  return null;
}

function PlanTable({ files }: { files: PlannedFile[] }) {
  const { t } = useT();
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">{t("activity.table.file")}</th>
            <th scope="col">{t("activity.table.format")}</th>
            <th scope="col">{t("activity.table.account")}</th>
            <th scope="col" className="num">
              {t("activity.table.rows")}
            </th>
            <th scope="col">{t("activity.table.state")}</th>
          </tr>
        </thead>
        <tbody>
          {files.map((file) => (
            <tr key={file.filename}>
              <td>{file.filename}</td>
              <td className="muted">{file.adapter ?? "—"}</td>
              <td>
                {file.account_id ? (
                  <>
                    {file.account_label ?? file.account_id}
                    <span className="muted"> · {file.tax_treatment}</span>
                  </>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td className="num">{file.row_count ?? "—"}</td>
              <td>
                {file.status === "imported" ? (
                  file.already_imported ? (
                    <span className="badge none">{t("activity.import.status.unchanged")}</span>
                  ) : (
                    <span className="badge ok">{t("activity.badge.ready")}</span>
                  )
                ) : (
                  <span className="badge bad" title={file.detail ?? undefined}>
                    {statusLabel(file.status)}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunResult({ result }: { result: ImportRunResult }) {
  const { t } = useT();
  const conflicted = result.files.filter((f) => f.conflicts.length > 0);
  const warned = result.files.filter((f) => f.warnings.length > 0);

  return (
    <div className="import-result">
      <h3>
        {t(result.inserted === 1 ? "activity.import.result.rowsAdded_one" : "activity.import.result.rowsAdded_other", {
          count: result.inserted.toLocaleString(),
        })}
        <span className="muted">
          {" "}
          ·{" "}
          {t("activity.import.result.ledgerHolds", { count: result.txn_count.toLocaleString() })}
        </span>
      </h3>

      {conflicted.length > 0 && (
        <div className="callout callout-danger import-notice">
          <strong>{t("activity.import.result.conflicts.title")}</strong>
          <p>{t("activity.import.result.conflicts.body")}</p>
          {conflicted.map((file) => (
            <div key={file.filename}>
              <strong>{file.filename}</strong>
              <ul className="warning-list">
                {file.conflicts.map((conflict) => (
                  <li key={conflict}>
                    <code>{conflict}</code>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {warned.length > 0 && (
        <div className="callout callout-warn import-notice">
          {warned.map((file) => (
            <div key={file.filename}>
              <strong>{file.filename}</strong>
              <ul className="warning-list">
                {file.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th scope="col">{t("activity.table.file")}</th>
              <th scope="col">{t("activity.table.result")}</th>
              <th scope="col" className="num">
                {t("activity.table.added")}
              </th>
              <th scope="col" className="num">
                {t("activity.table.alreadyThere")}
              </th>
              <th scope="col" className="num">
                {t("activity.table.notTransaction")}
              </th>
              <th scope="col">{t("activity.table.account")}</th>
            </tr>
          </thead>
          <tbody>
            {result.files.map((file) => (
              <tr key={file.filename}>
                <td>{file.filename}</td>
                <td>
                  <span className={`badge ${badgeClass(file)}`}>{statusLabel(file.status)}</span>
                  {file.detail && <div className="muted import-detail">{file.detail}</div>}
                </td>
                <td className="num">{file.inserted.toLocaleString()}</td>
                <td className="num">{file.duplicates.toLocaleString()}</td>
                <td className="num" title={skippedTitle(file)}>
                  {(file.row_count - file.usable_row_count).toLocaleString()}
                </td>
                <td className="muted">{file.account_id ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function badgeClass(file: FileImport): string {
  const tone = statusTone(file.status);
  if (tone === "good") return "ok";
  if (tone === "neutral") return "none";
  return "bad";
}

/**
 * The skip breakdown, as a tooltip on the count.
 *
 * Worth surfacing at all because the gap between rows in the file and rows in the ledger is the
 * adapter's regression signature — some adapters discard cancelled and failed orders — and a user
 * seeing "N of M" with no explanation would reasonably assume data loss.
 */
function skippedTitle(file: FileImport): string {
  const entries = Object.entries(file.skipped);
  if (entries.length === 0) return translateNow("activity.import.skipped.none");
  return entries.map(([reason, count]) => `${count} ${reason.replace(/_/g, " ")}`).join(", ");
}
