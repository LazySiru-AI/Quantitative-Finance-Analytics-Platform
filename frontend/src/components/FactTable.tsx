/**
 * The fact bundle: every computed figure behind the report, in one place, each row answering
 * "where did that number come from". `source` names the engine and window that produced it,
 * `as_of` the timestamp it was current as of -- both travel with the value rather than living only
 * in a tooltip, since a screenshot of a single row should be self-describing.
 *
 * `formatFact` renders by the backend-declared `kind`, never `0` for `null` -- the same rule as
 * every other numeric column on this page.
 */
import { formatFact, type Fact, type FactBundle, type MarketWarning } from "@/api/report";
import { useT } from "@/i18n";

interface FactTableProps {
  bundle: FactBundle;
}

export default function FactTable({ bundle }: FactTableProps) {
  const { t } = useT();
  const facts = Object.values(bundle.facts);

  return (
    <div className="panel">
      <h2 className="section-heading">{t("desk.factTable.title")}</h2>
      <p className="subtitle">{t("desk.factTable.subtitle")}</p>

      <FactWarnings warnings={bundle.warnings} />

      {facts.length === 0 ? (
        <div className="placeholder">{t("desk.factTable.empty")}</div>
      ) : (
        <div className="table-wrap">
          <table className="data-table report-fact-table" aria-label={t("desk.factTable.tableAriaLabel", { symbol: bundle.symbol })}>
            <thead>
              <tr>
                <th scope="col">{t("desk.factTable.labelHeader")}</th>
                <th scope="col" className="num">
                  {t("common.value")}
                </th>
                <th scope="col">{t("common.source")}</th>
                <th scope="col">{t("desk.factTable.asOfHeader")}</th>
              </tr>
            </thead>
            <tbody>
              {facts.map((fact) => (
                <FactRow key={fact.id} fact={fact} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function FactRow({ fact }: { fact: Fact }) {
  return (
    <tr>
      <td>{fact.label}</td>
      <td className="num">{formatFact(fact)}</td>
      <td className="report-fact-source">{fact.source}</td>
      <td>{fact.as_of ?? "—"}</td>
    </tr>
  );
}

function FactWarnings({ warnings }: { warnings: MarketWarning[] }) {
  if (warnings.length === 0) return null;
  return (
    <div className="warnings-strip">
      {warnings.map((w, i) => (
        <div className="warning-chip" key={`${w.kind}-${i}`}>
          <span className="kind">{w.kind}</span>
          <span className="message">{w.message}</span>
        </div>
      ))}
    </div>
  );
}
