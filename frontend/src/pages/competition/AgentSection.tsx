// ---------------------------------------------------------------------------
// 2. Agent drill-down
// ---------------------------------------------------------------------------
import {
  absDecimalString,
  compareDecimalStrings,
  formatPctFraction,
  formatRatio,
  formatRatioString,
  formatSignedDecimalMoney,
  formatSignedPctFraction,
  fractionTone,
  type AgentDetailResponse,
  type AgentWindowDetail,
  type TradeDetail,
} from "@/api/competition";
import { ScrollRegion } from "@/components/ScrollPanel";
import { Trans, useT } from "@/i18n";
import { numCell } from "@/pages/competition/cells";

type Phase = "loading" | "loaded" | "error";

export interface AgentSectionProps {
  roundId: string | null;
  agentId: string | null;
  detail: AgentDetailResponse | null;
  phase: Phase;
  message: string | null;
  /**
   * Collapses the inline drawer back to the bare leaderboard. This section used to be its own
   * top-level tab (`view === "agent"`) that showed nothing but `competitionRounds.agent.selectPrompt`
   * until a leaderboard row was clicked -- a dead tab a reader could open and find empty. It now
   * renders directly under the Leaderboard table instead, so it needs its own way back rather than
   * relying on a tab rail to switch away from it. Optional so a render with nothing to close (the
   * `!roundId || !agentId` guard below, which the parent should not reach in practice since it only
   * mounts this once an agent is selected) does not require callers to pass a no-op.
   */
  onClose?: (() => void) | undefined;
}

/** The one button every branch below renders once there is a drawer open to close -- kept as its own
 *  component rather than repeated JSX so "close" always reads the same regardless of which phase
 *  (loading/error/loaded) the drawer happens to be in. Renders nothing when `onClose` was not
 *  supplied, matching the prop's own optionality. */
function CloseDrawerButton({ onClose }: { onClose?: (() => void) | undefined }) {
  const { t } = useT();
  if (!onClose) return null;
  return (
    <button type="button" className="comp-agent-close" onClick={onClose}>
      {t("common.close")}
    </button>
  );
}

export default function AgentSection({ roundId, agentId, detail, phase, message, onClose }: AgentSectionProps) {
  const { t } = useT();
  if (!roundId || !agentId) {
    return (
      <div className="panel">
        <div className="placeholder">{t("competitionRounds.agent.selectPrompt")}</div>
      </div>
    );
  }

  if (phase === "loading") {
    return (
      <div className="panel">
        <div className="comp-agent-panel-head">
          <div className="placeholder">{t("competitionRounds.agent.loading", { agentId })}</div>
          <CloseDrawerButton onClose={onClose} />
        </div>
      </div>
    );
  }
  if (phase === "error") {
    // `.callout-danger`, not `.placeholder`. A failure and an empty state are different facts, and
    // this branch was rendering them in identical styling -- so `r15-2026-08` answering a bare
    // "Internal Server Error" for every one of its cards read as "this agent has nothing to show"
    // rather than as something being broken. `role="alert"` for the same reason: a reader who does
    // not look at colour still gets told which of the two this is.
    return (
      <div className="panel">
        <div className="comp-agent-panel-head">
          <div className="callout callout-danger" role="alert">
            {message ?? t("competitionRounds.agent.loadError")}
          </div>
          <CloseDrawerButton onClose={onClose} />
        </div>
      </div>
    );
  }
  if (!detail) return null;

  return (
    <>
      <div className="panel">
        <div className="comp-agent-panel-head">
          <h2 className="section-heading">
            {t("competitionRounds.agent.heading", { name: detail.display_name, roundId: detail.round_id })}
          </h2>
          <CloseDrawerButton onClose={onClose} />
        </div>
        <div className="comp-agent-meta">
          <span className="badge">{detail.card.discipline}</span>
          <span className="comp-agent-universe">{detail.card.universe.join(", ") || "—"}</span>
        </div>
        {/* Not `.placeholder`: this is the card's actual thesis, real content. It borrowed that
            class for its muted styling, and once `.placeholder` gained a designed "nothing here"
            treatment the thesis started rendering as though the card had no thesis at all. */}
        <p className="comp-agent-thesis">{detail.card.thesis}</p>
      </div>

      {detail.windows.length === 0 && (
        <div className="panel">
          <div className="placeholder">{t("competitionRounds.agent.noWindows")}</div>
        </div>
      )}

      {detail.windows.length > 0 && (
        <ScrollRegion
          size="md"
          label={t("competitionRounds.agent.heading", { name: detail.display_name, roundId: detail.round_id })}
        >
          {detail.windows.map((w) => (
            <AgentWindowBlock key={w.window} agentWindow={w} />
          ))}
        </ScrollRegion>
      )}
    </>
  );
}

function AgentWindowBlock({ agentWindow: w }: { agentWindow: AgentWindowDetail }) {
  const { t } = useT();
  // Sorted by |contribution| descending without ever parsing the decimal string into a float --
  // `compareDecimalStrings`/`absDecimalString` compare exact digit strings via `BigInt`.
  const sortedTrades = [...w.trades].sort((a, b) =>
    compareDecimalStrings(absDecimalString(b.contribution), absDecimalString(a.contribution)),
  );

  return (
    <div className="panel comp-drilldown-window">
      <h3>{w.window}</h3>
      <div className="status-grid">
        <div className="stat">
          <span className="label">{t("competitionRounds.agent.stat.totalReturn")}</span>
          <span className={`value ${numCell(fractionTone(w.total_return))}`}>
            {formatSignedPctFraction(w.total_return)}
          </span>
        </div>
        <div className="stat">
          <span className="label">{t("competitionRounds.agent.stat.spyBenchmark")}</span>
          <span className="value comp-num">{formatSignedPctFraction(w.benchmark_return)}</span>
        </div>
        <div className="stat">
          <span className="label">{t("competitionRounds.agent.stat.excess")}</span>
          <span className={`value ${numCell(fractionTone(w.excess))}`}>
            {formatSignedPctFraction(w.excess)}
          </span>
        </div>
        <div className="stat">
          <span className="label">{t("competitionRounds.agent.stat.adjustedExcess")}</span>
          <span className={`value ${numCell(fractionTone(w.adjusted_excess))}`}>
            {formatSignedPctFraction(w.adjusted_excess)}
          </span>
        </div>
        <div className="stat">
          <span className="label">{t("competitionRounds.agent.stat.capitalExposure")}</span>
          <span className="value comp-num">{formatRatio(w.capital_exposure)}</span>
        </div>
        <div className="stat">
          <span className="label">{t("competitionRounds.agent.stat.maxDrawdown")}</span>
          <span className={`value ${numCell(fractionTone(w.max_drawdown))}`}>
            {formatSignedPctFraction(w.max_drawdown)}
          </span>
        </div>
        <div className="stat">
          <span className="label">{t("competitionRounds.agent.stat.winRate")}</span>
          <span className="value comp-num">{formatRatio(w.win_rate)}</span>
        </div>
        <div className="stat">
          <span className="label">{t("competitionRounds.agent.stat.profitFactor")}</span>
          <span className="value comp-num">{formatRatioString(w.profit_factor)}</span>
        </div>
        <div className="stat">
          <span className="label">{t("competitionRounds.agent.stat.unrealisedShare")}</span>
          <span className="value comp-num">{formatPctFraction(w.unrealised_share)}</span>
        </div>
      </div>

      <div className="callout callout-info comp-concentration">
        <Trans
          k="competitionRounds.agent.concentration"
          values={{
            ratio: formatRatio(w.top3_share_of_gross_wins),
            strongReturn: <strong>{formatSignedPctFraction(w.return_without_top3_winners)}</strong>,
            totalReturn: formatSignedPctFraction(w.total_return),
          }}
        />
      </div>

      {w.rejections.length > 0 && (
        // No dedicated "rejections" heading exists in `competitionRounds.agent.*` -- reusing
        // `strategy.thesis.warningsHeading` ("Warnings"), the same generic label already attached to
        // this app's other `.warning-list` instances, rather than inventing a new i18n key.
        // `warning-list`/`comp-rejections` stay on the `<ul>` itself (list-item padding is an
        // element-level default the wrapping `ScrollRegion` div cannot inherit around).
        <ScrollRegion size="md" label={t("strategy.thesis.warningsHeading")}>
          <ul className="warning-list comp-rejections">
            {w.rejections.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </ScrollRegion>
      )}

      <TradesTable trades={sortedTrades} />
    </div>
  );
}

function TradesTable({ trades }: { trades: TradeDetail[] }) {
  const { t } = useT();
  if (trades.length === 0) {
    return <div className="placeholder">{t("competitionRounds.agent.noTrades")}</div>;
  }
  return (
    <ScrollRegion size="md" label={t("competitionRounds.dossier.table.trades")}>
      <div className="table-wrap">
        <table className="data-table comp-trades-table">
          <thead>
          <tr>
            <th>{t("common.symbol")}</th>
            <th>{t("competitionRounds.label.entry")}</th>
            <th>{t("competitionRounds.label.exit")}</th>
            <th className="num">{t("competitionRounds.agent.table.barsHeld")}</th>
            <th>{t("competitionRounds.agent.table.exitReason")}</th>
            <th className="num">{t("competitionRounds.agent.table.return")}</th>
            <th className="num">P&amp;L</th>
            <th className="num">{t("competitionRounds.agent.table.shareOfReturn")}</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((tr, i) => (
            <tr
              key={`${tr.symbol}-${tr.entry_date}-${i}`}
              className={tr.unrealised ? "comp-unrealised-row" : ""}
            >
              <td>{tr.symbol}</td>
              <td>{tr.entry_date}</td>
              <td>{tr.exit_date}</td>
              <td className="num comp-num">{tr.bars_held}</td>
              <td>{tr.exit_reason}</td>
              <td className={numCell(fractionTone(tr.return_pct))}>
                {formatSignedPctFraction(tr.return_pct)}
              </td>
              <td className={numCell(fractionTone(tr.pnl))}>
                {formatSignedDecimalMoney(tr.pnl)}
                {tr.unrealised && (
                  <span className="badge comp-mark-badge" title={t("competitionRounds.agent.markBadgeTitle")}>
                    {t("competitionRounds.agent.markBadge")}
                  </span>
                )}
              </td>
              <td className={numCell(fractionTone(tr.contribution))}>
                {formatSignedPctFraction(tr.contribution)}
              </td>
            </tr>
          ))}
          </tbody>
        </table>
      </div>
    </ScrollRegion>
  );
}
