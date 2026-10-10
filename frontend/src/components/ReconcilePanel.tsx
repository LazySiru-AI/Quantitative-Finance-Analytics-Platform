/**
 * 1099-B reconciliation.
 *
 * The application has said from its first commit that its tax output is *a calculation, not tax
 * advice*, and that it must be reconciled against the broker's own 1099-B before it informs a
 * filing. The engine to do that comparison was written in Phase 3 and had no way to be run from
 * the application — `POST /api/tax/reconcile` was the only endpoint in the API with no consumer.
 *
 * That mattered more than an ordinary unwired route. `docs/reports/defects-2.md` found the
 * permanently-disallowed figure understated for a tax year, and said in as many words
 * that this reconciliation "is what would have caught it".
 *
 * Two things this panel is careful about:
 *
 * **A clean result is a real result, and a limited one.** Every line agreeing to the cent means the
 * lines the user *transcribed* agree. It says nothing about a disposal that appears on neither
 * side, which is precisely the shape of an export missing rows. So a clean run reports what it
 * compared, and never renders as "your taxes are correct".
 *
 * **The two "missing" statuses are opposites.** Missing from the engine means the broker reported a
 * disposal that was not computed — usually rows absent from the imported export, so the ledger is
 * incomplete. Missing from the 1099-B is the reverse. Collapsing them into one "mismatch" count
 * would hide which side to go and look at.
 */

import { useState } from "react";

import { describeError } from "@/api/client";
import {
  formatMoney,
  RECONCILE_CSV_TEMPLATE,
  taxApi,
  type ReconcileLine,
  type ReconcileReport,
  type ReconcileStatus,
} from "@/api/tax";
import { t as translateNow, Trans, useT, type MessageKey, type Translator } from "@/i18n";

/**
 * Backend `ReconcileLine.note_code` → catalog key. The server sends a language-neutral code and the
 * interpolation values (`note_params`); we render our own translation. A code we do not recognise --
 * a backend newer than this build -- falls through to the English `note`, so the two can be deployed
 * in either order without a blank cell. See `app/tax/reconcile.py`.
 */
const RECONCILE_NOTE_KEYS: Record<string, MessageKey> = {
  missing_from_1099b: "activity.reconcile.note.missingFrom1099b",
  missing_from_engine_generic: "activity.reconcile.note.missingFromEngineGeneric",
  missing_from_engine_webull: "activity.reconcile.note.missingFromEngineWebull",
  amount_differs_wash_higher: "activity.reconcile.note.amountDiffersWashHigher",
  amount_differs_wash_lower: "activity.reconcile.note.amountDiffersWashLower",
};

/** The localised note for one line, or its raw English `note`, or null when there is none. */
function reconcileNoteText(t: Translator, line: ReconcileLine): string | null {
  const key = line.note_code ? RECONCILE_NOTE_KEYS[line.note_code] : undefined;
  if (key) return t(key, line.note_params ?? {});
  return line.note;
}

export default function ReconcilePanel({ year }: { year: number }) {
  const { t } = useT();
  const [csvText, setCsvText] = useState(RECONCILE_CSV_TEMPLATE);
  const [report, setReport] = useState<ReconcileReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState(false);

  const hasRows = csvText.trim().split(/\r?\n/).filter((line) => line.trim()).length > 1;

  function run() {
    setRunning(true);
    setError(null);
    taxApi
      .reconcile(year, csvText)
      .then((next) => {
        setReport(next);
        setError(null);
      })
      .catch((err: unknown) => {
        setReport(null);
        setError(describeError(err, t("activity.reconcile.error.generic")));
      })
      .finally(() => setRunning(false));
  }

  return (
    <section className="panel">
      <div className="reconcile-head">
        <h2>{t("activity.reconcile.heading")}</h2>
        <button type="button" onClick={() => setOpen((was) => !was)}>
          {open ? t("activity.reconcile.hide") : t("activity.reconcile.open")}
        </button>
      </div>

      <p className="reconcile-intro">{t("activity.reconcile.intro")}</p>

      {open && (
        <>
          <p className="muted reconcile-help">
            <Trans
              k="activity.reconcile.help"
              values={{
                cols: <code>Symbol, Account, Term, Proceeds, Cost Basis</code>,
                wsd: <code>Wash Sale Disallowed</code>,
                desc: <code>Description</code>,
                short: <code>short</code>,
                long: <code>long</code>,
                ex1: <code>$1,234.56</code>,
                ex2: <code>(123.45)</code>,
              }}
            />
          </p>

          <textarea
            className="reconcile-input"
            value={csvText}
            spellCheck={false}
            rows={8}
            aria-label={t("activity.reconcile.textareaAriaLabel")}
            onChange={(event) => setCsvText(event.target.value)}
          />

          <div className="reconcile-actions">
            <button type="button" className="symbol-submit" disabled={!hasRows || running} onClick={run}>
              {running
                ? t("activity.reconcile.action.running")
                : t("activity.reconcile.action.compare", { year })}
            </button>
            <span className="muted">{t("activity.reconcile.action.hint")}</span>
          </div>

          {error && (
            <div className="callout callout-danger reconcile-notice">
              <strong>{t("activity.reconcile.error.title")}</strong>
              <p>{error}</p>
            </div>
          )}

          {report && <ReconcileResult report={report} year={year} />}
        </>
      )}
    </section>
  );
}

function ReconcileResult({ report, year }: { report: ReconcileReport; year: number }) {
  const { t } = useT();
  const clean = report.differing_count === 0;
  const differing = report.lines.filter((line) => line.status !== "matched");

  return (
    <div className="reconcile-result">
      <div className={`callout ${clean ? "callout-warn" : "callout-danger"} reconcile-notice`}>
        {clean ? (
          <>
            <strong>
              {t(
                report.matched_count === 1
                  ? "activity.reconcile.clean.title_one"
                  : "activity.reconcile.clean.title_other",
                { count: report.matched_count },
              )}
            </strong>
            <p>
              {t(
                report.matched_count === 1
                  ? "activity.reconcile.clean.body_one"
                  : "activity.reconcile.clean.body_other",
                { count: report.matched_count },
              )}
            </p>
          </>
        ) : (
          <>
            <strong>
              {t(
                report.differing_count === 1
                  ? "activity.reconcile.differ.title_one"
                  : "activity.reconcile.differ.title_other",
                { count: report.differing_count },
              )}
            </strong>
            <p>
              <Trans
                k="activity.reconcile.differ.body"
                values={{
                  delta: <strong>{formatMoney(report.total_gain_delta)}</strong>,
                  year,
                }}
              />
            </p>
          </>
        )}
      </div>

      {differing.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">{t("common.symbol")}</th>
                <th scope="col">{t("activity.table.account")}</th>
                <th scope="col">{t("activity.reconcile.table.term")}</th>
                <th scope="col">{t("common.status")}</th>
                <th scope="col" className="num">
                  {t("activity.reconcile.table.computedGain")}
                </th>
                <th scope="col" className="num">
                  {t("activity.reconcile.table.formGain")}
                </th>
                <th scope="col" className="num">
                  {t("activity.reconcile.table.difference")}
                </th>
              </tr>
            </thead>
            <tbody>
              {differing.map((line) => {
                const note = reconcileNoteText(t, line);
                return (
                  <tr key={`${line.symbol}-${line.account_id}-${line.term}`}>
                    <td>{line.symbol}</td>
                    <td className="muted">{line.account_id}</td>
                    <td>
                      {line.term === "short"
                        ? t("activity.reconcile.term.short")
                        : t("activity.reconcile.term.long")}
                    </td>
                    <td>
                      <span className="badge bad">{statusLabel(line.status)}</span>
                      {note && <div className="muted reconcile-note">{note}</div>}
                    </td>
                    <td className="num">{sideOrDash(line, "engine")}</td>
                    <td className="num">{sideOrDash(line, "form")}</td>
                    <td className="num">{formatMoney(line.gain_delta)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {report.matched_count > 0 && !clean && (
        <p className="muted reconcile-matched">
          {t(
            report.matched_count === 1
              ? "activity.reconcile.otherMatched_one"
              : "activity.reconcile.otherMatched_other",
            { count: report.matched_count },
          )}
        </p>
      )}
    </div>
  );
}

/**
 * A side's gain, or an em dash where that side has nothing.
 *
 * The absent side of a "missing from" line serialises as `0.00` — a real zero and an absent figure
 * are the same value on the wire, and the status is what tells them apart. Rendering `$0.00` for
 * "the broker did not report this at all" would state a number the form does not contain, which is
 * the one thing this application's money-formatting convention exists to prevent.
 */
function sideOrDash(line: ReconcileLine, side: "engine" | "form"): string {
  if (side === "engine" && line.status === "missing_from_engine") return "—";
  if (side === "form" && line.status === "missing_from_1099b") return "—";
  return formatMoney(side === "engine" ? line.engine_gain : line.form_gain);
}

/**
 * Exhaustive at compile time, forgiving at runtime — the pattern pinned by `exitReasonLabel` in
 * `@/api/paperdesk`. `ReconcileStatus` describes data this page receives from `POST
 * /api/tax/reconcile`, not a value this code constructs itself, so a throwing default here would take
 * down the whole Tax page — 8949, disposals, wash sales, all of it — over one unrecognised status in
 * one reconciliation row, exactly the failure `exitReasonLabel`'s docstring records happening for real
 * on Paper Desk. This used to throw via a private `assertNever`; it now renders the raw wire value
 * instead.
 */
export function statusLabel(status: ReconcileStatus): string {
  switch (status) {
    case "matched":
      return translateNow("activity.reconcile.status.matched");
    case "amount_differs":
      return translateNow("activity.reconcile.status.amountDiffers");
    case "missing_from_engine":
      return translateNow("activity.reconcile.status.missingFromEngine");
    case "missing_from_1099b":
      return translateNow("activity.reconcile.status.missingFrom1099b");
    default: {
      const _exhaustive: never = status;
      void _exhaustive;
      return String(status);
    }
  }
}

