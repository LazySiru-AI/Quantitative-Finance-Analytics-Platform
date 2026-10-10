/**
 * The page-wide tax-warnings box. Same shape and layout as `Tax.tsx`'s own warnings section,
 * duplicated rather than shared so this page has no dependency on `Tax.tsx`'s internals (see
 * `warningKindLabel` in `api/portfolio.ts`).
 *
 * Collapsed by default, showing only the headline count and a chevron -- nothing else (the group
 * table, the "show all" list, and `WarningsChart`) is mounted until the reader opens it. An expensive
 * child (a chart that computes a per-account colour assignment and a top-symbols ranking) stays
 * lazy-mounted rather than rendered-but-hidden, matching `MacroTile.tsx`'s own chart-disclosure
 * precedent.
 */
import { useId, useState } from "react";

import { warningKindLabel, type TaxWarning, type WarningGroup } from "@/api/portfolio";
import { ScrollRegion } from "@/components/ScrollPanel";
import WarningsChart from "@/components/WarningsChart";
import { useT } from "@/i18n";

export function WarningsSection({
  warnings,
  warningGroups,
}: {
  warnings: TaxWarning[];
  warningGroups: WarningGroup[];
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const panelId = useId();
  if (warnings.length === 0) return null;
  return (
    <div className="panel callout callout-danger">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={t("portfolio.warnings.toggleAriaLabel")}
        onClick={() => setOpen((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.4rem",
          width: "100%",
          background: "none",
          border: "none",
          padding: 0,
          margin: 0,
          font: "inherit",
          color: "inherit",
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        <strong>
          {t(
            warnings.length === 1 ? "portfolio.warnings.headline_one" : "portfolio.warnings.headline_other",
            { count: warnings.length },
          )}
        </strong>
      </button>

      {open && (
        <div id={panelId}>
          <WarningsChart warningGroups={warningGroups} warnings={warnings} />
          {/* Not inside a `ScrollRegion` -- this table is bounded by the number of DISTINCT
              (kind, account) groups, never the row-count kind `ScrollRegion` exists to cap -- so the
              scrollable-region role and keyboard tab stop (A11Y-03) are supplied directly. */}
          <div
            className="table-wrap"
            tabIndex={0}
            role="region"
            aria-label={t("portfolio.warnings.groupsTableRegionLabel")}
          >
            <table className="data-table warning-group-table">
              <thead>
                <tr>
                  <th scope="col">{t("portfolio.header.kind")}</th>
                  <th scope="col">{t("portfolio.header.account")}</th>
                  <th scope="col">{t("common.count")}</th>
                  <th scope="col">{t("portfolio.header.example")}</th>
                </tr>
              </thead>
              <tbody>
                {warningGroups.map((g) => (
                  <tr key={`${g.kind}:${g.account_id ?? ""}`}>
                    <td>{warningKindLabel(g.kind)}</td>
                    <td>
                      {g.account_id ?? "—"}
                      {g.broker ? ` (${g.broker})` : ""}
                    </td>
                    <td>{g.count}</td>
                    <td className="warning-sample">{g.sample_detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="warning-detail">
            <summary>{t("portfolio.warnings.showAll", { count: warnings.length })}</summary>
            <ScrollRegion size="sm" label={t("portfolio.warnings.showAll", { count: warnings.length })}>
              <ul className="warning-list">
                {warnings.map((w, i) => (
                  <li key={i}>
                    {warningKindLabel(w.kind)}
                    {w.account_id ? ` (${w.account_id})` : ""}: {w.detail}
                  </li>
                ))}
              </ul>
            </ScrollRegion>
          </details>
        </div>
      )}
    </div>
  );
}

export default WarningsSection;
