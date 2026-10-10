/**
 * The per-file choice: attach this export to an account you already have, or open a new one.
 *
 * This is the only input in the whole import pipeline that nothing can check for the user. A
 * Robinhood taxable export and a Robinhood Roth export are structurally identical, so the file
 * cannot say which it is — but the *ledger* can say a great deal, and this row's job is to put that
 * evidence in front of the person deciding rather than to decide for them.
 *
 * **What the evidence is.** `txn_id` is a deterministic hash that includes the account, so for each
 * candidate the server recomputes the ids this file would produce and looks them up. Nothing fuzzy,
 * no thresholds on dates or amounts: either these are the same transactions or they are not.
 *
 * **Which number to lead with.** Coverage of the *account*, not of the file. A new export can share many rows with one
 * account and a handful with another — both a small share of the file. As a share of each account:
 * 100% and a small fraction. The file contains one account whole and coincidentally repeats a few
 * of another's same-day, same-price trades. So the row
 * reads "contains all N of this account's transactions", which is the sentence that settles it.
 *
 * **Why a new account still asks for tax treatment.** It decides whether the account's gains are
 * reported at all and whether a repurchase inside it destroys a loss permanently under
 * Rev. Rul. 2008-5. Attaching inherits the existing account's treatment and never restates it; a
 * new one has to be told. There is no default, here or anywhere else in this application.
 */

import { useId, useState } from "react";

import type { AccountMatch, FileDecision, NewAccount, PlannedFile } from "@/api/imports";
import { Trans, useT, type MessageKey } from "@/i18n";

type Mode = "skip" | "attach" | "create";

const TREATMENTS: { value: NewAccount["tax_treatment"]; labelKey: MessageKey }[] = [
  { value: "taxable", labelKey: "activity.decision.treatment.taxable" },
  { value: "roth_ira", labelKey: "activity.decision.treatment.rothIra" },
  { value: "traditional_ira", labelKey: "activity.decision.treatment.traditionalIra" },
];

const TYPES: { value: NonNullable<NewAccount["account_type"]>; labelKey: MessageKey }[] = [
  { value: "cash", labelKey: "activity.decision.accountType.cash" },
  { value: "margin", labelKey: "activity.decision.accountType.margin" },
  { value: "retirement", labelKey: "activity.decision.accountType.retirement" },
];

export interface DecisionState {
  mode: Mode;
  accountId: string;
  newAccount: NewAccount;
}

/** A blank decision for a file, preselected from the server's suggestion where there is one. */
export function initialDecision(file: PlannedFile): DecisionState {
  const suggested = file.suggested_account_id;
  return {
    // Preselected, never pre-submitted: the user still has to press Import, and the evidence for
    // the suggestion is on screen next to it.
    mode: suggested ? "attach" : "skip",
    accountId: suggested ?? "",
    newAccount: {
      account_id: suggestAccountId(file),
      label: file.filename.replace(/\.csv$/i, ""),
      // Deliberately left as taxable in the *form* while the field stays required by the server —
      // see the module note. The select shows it, so the user reads it and changes it or does not.
      tax_treatment: "taxable",
      account_type: "cash",
    },
  };
}

/**
 * A slug from the filename, offered as a starting point.
 *
 * Safe to derive where the tax treatment is not: an id is a label the user can rewrite and no
 * calculation reads meaning out of it. Mirrors `_suggest_account_id` in `app.ingest.manifest`.
 */
function suggestAccountId(file: PlannedFile): string {
  const prefix = { robinhood: "rh", webull: "wb", sofi: "sofi" }[file.broker ?? ""] ?? "acct";
  const slug = file.filename
    .replace(/\.csv$/i, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return slug.startsWith(prefix) ? slug : `${prefix}-${slug}`;
}

/** The decision as the API wants it, or `null` when this file is being left alone. */
export function toDecision(filename: string, state: DecisionState): FileDecision | null {
  if (state.mode === "attach" && state.accountId) {
    return { filename, account_id: state.accountId };
  }
  if (state.mode === "create") {
    return { filename, new_account: state.newAccount };
  }
  return null;
}

export default function ImportDecisionRow({
  file,
  state,
  onChange,
}: {
  file: PlannedFile;
  state: DecisionState;
  onChange: (next: DecisionState) => void;
}) {
  const { t } = useT();
  const [showAll, setShowAll] = useState(false);
  const groupId = useId();

  const exact = file.matches.filter((m) => m.overlapping > 0);
  const visible = showAll ? file.matches : exact;

  return (
    <div className="import-decision">
      <div className="import-decision-head">
        <strong>{file.filename}</strong>
        <span className="muted">
          {file.adapter} · {file.usable_row_count ?? file.row_count} transactions
        </span>
      </div>

      {file.match_is_ambiguous && (
        <div className="callout callout-warn import-notice">
          <strong>{t("activity.decision.ambiguous.title")}</strong>
          <p>{t("activity.decision.ambiguous.body")}</p>
        </div>
      )}

      <fieldset className="import-decision-modes">
        <legend className="visually-hidden">
          {t("activity.decision.legend", { filename: file.filename })}
        </legend>

        <label>
          <input
            type="radio"
            name={groupId}
            checked={state.mode === "skip"}
            onChange={() => onChange({ ...state, mode: "skip" })}
          />
          {t("activity.decision.mode.skip")}
        </label>

        <label>
          <input
            type="radio"
            name={groupId}
            checked={state.mode === "attach"}
            disabled={file.matches.length === 0}
            onChange={() => onChange({ ...state, mode: "attach" })}
          />
          {t("activity.decision.mode.attach")}
        </label>

        <label>
          <input
            type="radio"
            name={groupId}
            checked={state.mode === "create"}
            onChange={() => onChange({ ...state, mode: "create" })}
          />
          {t("activity.decision.mode.create")}
        </label>
      </fieldset>

      {state.mode === "attach" && (
        <div className="import-decision-body">
          {file.matches.length === 0 ? (
            <p className="muted">{t("activity.decision.noMatches")}</p>
          ) : (
            <>
              <div className="table-wrap">
                <table className="data-table import-match-table">
                  <thead>
                    <tr>
                      <th scope="col">
                        <span className="visually-hidden">{t("activity.decision.table.select")}</span>
                      </th>
                      <th scope="col">{t("activity.table.account")}</th>
                      <th scope="col">{t("activity.decision.table.evidence")}</th>
                      <th scope="col" className="num">
                        {t("activity.decision.table.wouldAdd")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible.map((match) => (
                      <MatchRow
                        key={match.account_id}
                        match={match}
                        checked={state.accountId === match.account_id}
                        name={`${groupId}-account`}
                        onSelect={() => onChange({ ...state, accountId: match.account_id })}
                      />
                    ))}
                  </tbody>
                </table>
              </div>

              {exact.length < file.matches.length && (
                <button
                  type="button"
                  className="import-decision-more"
                  onClick={() => setShowAll((v) => !v)}
                >
                  {showAll
                    ? t("activity.decision.showFiltered")
                    : t("activity.decision.showAll", { count: file.matches.length })}
                </button>
              )}
            </>
          )}
        </div>
      )}

      {state.mode === "create" && (
        <div className="import-decision-body import-new-account">
          {exact.length > 0 && (
            <div className="callout callout-warn import-notice">
              <strong>
                {t(
                  exact[0]!.overlapping === 1
                    ? "activity.decision.shareWarning_one"
                    : "activity.decision.shareWarning_other",
                  { count: exact[0]!.overlapping, account: exact[0]!.account_label },
                )}
              </strong>
              <p>{t("activity.decision.shareWarningBody")}</p>
            </div>
          )}

          <label>
            {t("activity.decision.field.accountId")}
            <input
              className="symbol-input"
              value={state.newAccount.account_id}
              onChange={(e) =>
                onChange({
                  ...state,
                  newAccount: { ...state.newAccount, account_id: e.target.value },
                })
              }
            />
          </label>

          <label>
            {t("activity.decision.field.label")}
            <input
              className="symbol-input"
              value={state.newAccount.label}
              onChange={(e) =>
                onChange({ ...state, newAccount: { ...state.newAccount, label: e.target.value } })
              }
            />
          </label>

          <label>
            {t("activity.decision.field.taxTreatment")}
            <select
              value={state.newAccount.tax_treatment}
              onChange={(e) =>
                onChange({
                  ...state,
                  newAccount: {
                    ...state.newAccount,
                    tax_treatment: e.target.value as NewAccount["tax_treatment"],
                  },
                })
              }
            >
              {TREATMENTS.map((treatment) => (
                <option key={treatment.value} value={treatment.value}>
                  {t(treatment.labelKey)}
                </option>
              ))}
            </select>
          </label>

          <label>
            {t("activity.decision.field.accountType")}
            <select
              value={state.newAccount.account_type ?? "cash"}
              onChange={(e) =>
                onChange({
                  ...state,
                  newAccount: {
                    ...state.newAccount,
                    account_type: e.target.value as NonNullable<NewAccount["account_type"]>,
                  },
                })
              }
            >
              {TYPES.map((accountType) => (
                <option key={accountType.value} value={accountType.value}>
                  {t(accountType.labelKey)}
                </option>
              ))}
            </select>
          </label>

          <p className="muted import-decision-note">
            <Trans
              k="activity.decision.note.body"
              values={{
                taxTreatmentLead: <strong>{t("activity.decision.note.taxTreatmentLead")}</strong>,
                accountTypeLead: <strong>{t("activity.decision.note.accountTypeLead")}</strong>,
              }}
            />
          </p>
        </div>
      )}
    </div>
  );
}

function MatchRow({
  match,
  checked,
  name,
  onSelect,
}: {
  match: AccountMatch;
  checked: boolean;
  name: string;
  onSelect: () => void;
}) {
  const { t } = useT();
  const pct = (value: number) => `${Math.round(value * 100)}%`;

  return (
    <tr className={checked ? "import-match-selected" : undefined}>
      <td>
        <input type="radio" name={name} checked={checked} onChange={onSelect} />
      </td>
      <td>
        {match.account_label}
        <div className="muted import-match-sub">
          {match.account_id} · {match.tax_treatment.replace("_", " ")}
        </div>
      </td>
      <td>
        {match.overlapping > 0 ? (
          <>
            {/* Coverage of the account leads: it is the ratio that separates "this file is that
                account" from "these two accounts hold the same ETFs". */}
            <strong>
              {t("activity.decision.match.contains", {
                overlapping: match.overlapping,
                total: match.account_total,
                pct: pct(match.account_coverage),
              })}
            </strong>
            <div className="muted import-match-sub">
              {t("activity.decision.match.storedHere", { pct: pct(match.overlap_fraction) })}
            </div>
          </>
        ) : (
          <span className="muted">
            {t("activity.decision.match.none")}
            {match.shared_symbols > 0 && (
              <>
                {" "}
                ·{" "}
                {t("activity.decision.match.sharedSymbols", {
                  shared: match.shared_symbols,
                  incoming: match.incoming_symbols,
                })}
              </>
            )}
          </span>
        )}
      </td>
      <td className="num">{match.new_rows.toLocaleString()}</td>
    </tr>
  );
}
