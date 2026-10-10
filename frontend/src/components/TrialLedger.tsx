/**
 * The trial ledger: every thesis ever registered for a ticker, oldest first, whatever became of it.
 *
 * `app/thesis/__init__.py`'s hazard statement names "the trial count is invisible" as the first of
 * three properties that make an unguarded generate-and-test loop worse than ordinary multiple
 * testing -- a human running two hundred rule combinations knows they ran two hundred, but a loop
 * that discards weak theses mid-iteration and never mentions them leaves no denominator behind. This
 * table is that denominator made visible, and it is a first-class section of the thesis page, not an
 * appendix below the results: `LedgerStats.total_trials` renders as prominently as any other figure
 * here, and it includes `abandoned` -- theses dropped mid-run without completing, which still occupy
 * a slot in the Benjamini-Hochberg family for this ticker.
 *
 * Verdicts get equal visual weight by construction, not just by color choice. `survived`,
 * `rejected` and `inconclusive` are exported as a single `VerdictBadge` with one shared size and
 * weight, differing only in accent color -- `inconclusive` is the expected outcome for most theses
 * on most tickers, per `Verdict.INCONCLUSIVE`'s docstring, and must never read as smaller, dimmer or
 * more apologetic than `survived`. `ThesisCard` reuses the same badge for the same reason: a
 * ticker's summary table and its detail cards must never disagree about how much weight a verdict
 * carries.
 */
import { formatQ } from "@/api/backtest";
import { verdictLabel, type LedgerStats, type ThesisRecord, type ThesisStatus, type Verdict } from "@/api/thesis";
import { type Translator, useT } from "@/i18n";

type Phase = "idle" | "loading" | "loaded" | "error" | "notfound";

interface TrialLedgerProps {
  symbol: string;
  stats: LedgerStats | null;
  records: ThesisRecord[];
  phase: Phase;
  message: string | null;
}

export default function TrialLedger({ symbol, stats, records, phase, message }: TrialLedgerProps) {
  const { t } = useT();
  return (
    <div className="panel">
      <h2 className="section-heading">{t("strategy.trialLedger.title", { symbol })}</h2>
      <p className="subtitle">{t("strategy.trialLedger.subtitle", { symbol })}</p>

      {phase === "loading" && (
        <div className="placeholder">{t("strategy.trialLedger.loading", { symbol })}</div>
      )}
      {(phase === "error" || phase === "notfound") && (
        <div className="callout callout-danger">{message}</div>
      )}

      {phase === "loaded" && (
        <>
          <LedgerStatsGrid stats={stats} />

          {records.length === 0 ? (
            <div className="placeholder">{t("strategy.trialLedger.empty", { symbol })}</div>
          ) : (
            <div className="table-wrap">
              <table className="data-table thesis-ledger-table">
                <thead>
                  <tr>
                    <th scope="col">{t("strategy.trialLedger.header.registered")}</th>
                    <th scope="col">{t("strategy.trialLedger.header.hypothesis")}</th>
                    <th scope="col">{t("strategy.trialLedger.header.status")}</th>
                    <th scope="col">{t("strategy.trialLedger.header.verdict")}</th>
                    <th scope="col" className="num">
                      {t("strategy.trialLedger.header.inSampleQ")}
                    </th>
                    <th scope="col" className="num">
                      {t("strategy.trialLedger.header.holdoutQ")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {[...records]
                    .sort((a, b) => a.registered_at.localeCompare(b.registered_at))
                    .map((record) => (
                      <LedgerRow key={record.thesis_hash} record={record} />
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function LedgerStatsGrid({ stats }: { stats: LedgerStats | null }) {
  const { t } = useT();
  if (stats === null) {
    return <div className="placeholder">{t("strategy.trialLedger.noStats")}</div>;
  }
  return (
    <div className="status-grid thesis-ledger-stats">
      <div className="stat">
        <span className="label">{t("strategy.trialLedger.stat.totalTrials")}</span>
        <span className="value thesis-total-trials">{stats.total_trials.toLocaleString()}</span>
      </div>
      <div className="stat">
        <span className="label">{t("strategy.trialLedger.stat.survived")}</span>
        <span className="value">{stats.survived.toLocaleString()}</span>
      </div>
      <div className="stat">
        <span className="label">{t("strategy.trialLedger.stat.rejected")}</span>
        <span className="value">{stats.rejected.toLocaleString()}</span>
      </div>
      <div className="stat">
        <span className="label">{t("strategy.trialLedger.stat.inconclusive")}</span>
        <span className="value">{stats.inconclusive.toLocaleString()}</span>
      </div>
      <div className="stat">
        <span className="label">{t("strategy.trialLedger.stat.abandoned")}</span>
        <span className="value">{stats.abandoned.toLocaleString()}</span>
      </div>
      <div className="stat">
        <span className="label">{t("strategy.trialLedger.stat.firstLastRegistered")}</span>
        <span className="value thesis-ledger-dates">
          {stats.first_registered ?? "—"} → {stats.last_registered ?? "—"}
        </span>
      </div>
    </div>
  );
}

function LedgerRow({ record }: { record: ThesisRecord }) {
  const { t } = useT();
  return (
    <tr>
      <td>{record.registered_at}</td>
      <td className="thesis-ledger-hypothesis">{record.thesis.hypothesis}</td>
      <td>
        <span className="badge">{statusLabel(record.status, t)}</span>
      </td>
      <td>
        {record.verdict ? (
          <VerdictBadge verdict={record.verdict} />
        ) : (
          <span className="badge none">{t("strategy.trialLedger.pendingVerdict")}</span>
        )}
      </td>
      <td className="num">
        {record.in_sample ? (
          <>
            {formatQ(record.in_sample.q_value)}
            <div className="bt-cell-sub">
              {t("strategy.trialLedger.ofTrials", { count: record.in_sample.trials_at_evaluation })}
            </div>
          </>
        ) : (
          "—"
        )}
      </td>
      <td className="num">
        {record.holdout ? (
          <>
            {formatQ(record.holdout.q_value)}
            <div className="bt-cell-sub">
              {t("strategy.trialLedger.ofTrials", { count: record.holdout.trials_at_evaluation })}
            </div>
          </>
        ) : (
          "—"
        )}
      </td>
    </tr>
  );
}

function statusLabel(status: ThesisStatus, t: Translator): string {
  switch (status) {
    case "registered":
      return t("strategy.thesisStatus.registered");
    case "in_sample_tested":
      return t("strategy.thesisStatus.inSampleTested");
    case "holdout_tested":
      return t("strategy.thesisStatus.holdoutTested");
    case "abandoned":
      return t("strategy.thesisStatus.abandoned");
    default:
      return status;
  }
}

/**
 * Shared by `TrialLedger` and `ThesisCard` so a ticker's summary row and its detail card can never
 * disagree about how a verdict is weighted. All three variants share size, weight and padding
 * (`.badge`); only the accent color differs, and `inconclusive` deliberately does not reuse
 * `.badge.none`'s muted treatment -- that class means "absent", and inconclusive is a completed,
 * reportable result.
 */
export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  const cls =
    verdict === "survived"
      ? "verdict-survived"
      : verdict === "rejected"
        ? "verdict-rejected"
        : "verdict-inconclusive";
  return <span className={`badge ${cls}`}>{verdictLabel(verdict)}</span>;
}
