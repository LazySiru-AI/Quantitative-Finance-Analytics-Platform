// ---------------------------------------------------------------------------
// 4. Selection
// ---------------------------------------------------------------------------
import {
  formatIntOrDash,
  seatedByLabel,
  type GateOutcome,
  type RoundSummary,
  type SelectionResponse,
  type SelectionSeat,
} from "@/api/competition";
import { ScrollRegion } from "@/components/ScrollPanel";
import { useT } from "@/i18n";

import { roundOptionText } from "./roundOption";

type Phase = "loading" | "loaded" | "error";

/** The three ranking gates, in the fixed order the desk keeps them -- matching the contract's own
 * "keys 'A', 'L', 'C', in that order" note on `SelectionResponse.gates` rather than trusting
 * `Object.keys` to preserve it if a future round ever reorders the response. Any gate key the backend
 * sends that is not one of these three still renders -- see `SelectionGates` below -- just after the
 * three known ones, so an unrecognised gate is visible rather than silently dropped. */
const GATE_ORDER = ["A", "L", "C"];

/** The round picker, rendered here as well as in the Leaderboard.
 *
 * Both views read the same `selectedRoundId`, which is right -- one source of truth. But the control
 * that *changes* it used to render only inside `LeaderboardSection`, so a reader who opened Selection
 * was stuck with whatever round the leaderboard had defaulted to.
 *
 * That is a dead end in practice, not just in principle: the default is the newest round, and a
 * scoring round (one that re-reads an earlier round's evidence under a new rule) has no live matrix
 * of its own, so the endpoint correctly 404s and this view correctly says "no selection recorded" --
 * with nothing on screen to reach a round that does have one.
 *
 * Duplicated rather than hoisted into a shared control bar because the two views want different
 * neighbours: the leaderboard pairs the round with a "rank by" control that means nothing to a
 * selection.
 */
function SelectionRoundPicker({
  rounds,
  roundsPhase,
  selectedRoundId,
  onSelectRound,
}: {
  rounds: RoundSummary[];
  roundsPhase: Phase;
  selectedRoundId: string | null;
  onSelectRound: (roundId: string) => void;
}) {
  const { t, lang } = useT();
  const selectedRound = rounds.find((r) => r.round_id === selectedRoundId) ?? null;
  return (
    <div className="panel filter-bar comp-controls">
      <label className="bt-control-label" htmlFor="selection-round-select">
        {t("competitionRounds.roundLabel")}
        {roundsPhase === "loaded" && (
          <select
            id="selection-round-select"
            className="bt-entry-select"
            value={selectedRoundId ?? ""}
            onChange={(e) => onSelectRound(e.target.value)}
          >
            {rounds.length === 0 && <option value="">{t("competitionRounds.noRoundsYet")}</option>}
            {/* Derived option text, never the authored `label` -- see `roundOption.ts`. */}
            {rounds.map((r) => (
              <option key={r.round_id} value={r.round_id}>
                {roundOptionText(r.round_id, lang)}
              </option>
            ))}
          </select>
        )}
      </label>
      {selectedRound && <p className="muted comp-round-title">{selectedRound.label}</p>}
    </div>
  );
}

export interface SelectionSectionProps {
  roundId: string | null;
  rounds: RoundSummary[];
  roundsPhase: Phase;
  onSelectRound: (roundId: string) => void;
  selection: SelectionResponse | null;
  phase: Phase;
  message: string | null;
  notFound: boolean;
}

export default function SelectionSection({
  roundId,
  rounds,
  roundsPhase,
  onSelectRound,
  selection,
  phase,
  message,
  notFound,
}: SelectionSectionProps) {
  const { t } = useT();
  const picker = (
    <SelectionRoundPicker
      rounds={rounds}
      roundsPhase={roundsPhase}
      selectedRoundId={roundId}
      onSelectRound={onSelectRound}
    />
  );

  if (!roundId) {
    return (
      <>
        {picker}
        <div className="panel">
          <div className="placeholder">{t("competitionRounds.selection.pickRound")}</div>
        </div>
      </>
    );
  }
  if (phase === "loading") {
    return (
      <>
        {picker}
        <div className="panel">
          <div className="placeholder">
            {t("competitionRounds.selection.loadingRound", { roundId })}
          </div>
        </div>
      </>
    );
  }
  if (phase === "error") {
    return (
      <>
        {picker}
        <div className="panel">
          <div className="placeholder">
            {message ?? t("competitionRounds.selection.loadError")}
          </div>
        </div>
      </>
    );
  }
  if (notFound || !selection) {
    // A round can legitimately have no selection: the current rule ranks on the live out-of-sample
    // record, so a round that predates that record, or one that only re-scored an earlier round's
    // evidence, has nothing of its own to rank. Say which round, and keep the picker on screen --
    // this state is reached by *default* on the newest round, so an empty panel with no control
    // would be the first thing most readers ever saw of this view.
    return (
      <>
        {picker}
        <div className="panel">
          <div className="placeholder">
            {t("competitionRounds.selection.notFound", { roundId })}
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      {picker}
      <div className="panel">
        <h2 className="section-heading">
          {t("competitionRounds.selection.heading", { roundId: selection.round_id })}
        </h2>
        <div className="comp-agent-meta">
          <span className="badge">
            {t("competitionRounds.selection.rulesBadge", { version: selection.rule_version })}
          </span>
        </div>
      </div>

      {/* Rendered first and unavoidably visible -- never inside a collapsed section -- because these
          carry the evidence's own limitations and the roster/gates below are misleading without them. */}
      <SelectionNotes notes={selection.notes} />

      {/* The roster comes first among the data sections: it is the answer this view exists to show,
          with the gates and full ranking underneath it as the working. */}
      <SelectionRoster seats={selection.seats} />
      <SelectionGates gates={selection.gates} />
      <SelectionRanking ranking={selection.ranking} />
    </>
  );
}

function SelectionNotes({ notes }: { notes: string[] }) {
  const { t } = useT();
  if (notes.length === 0) return null;
  return (
    <div className="panel">
      <div className="callout callout-warn selection-notes">
        <strong>{t("competitionRounds.selection.notesHeading")}</strong>
        <ul className="warning-list">
          {notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function SelectionRoster({ seats }: { seats: SelectionSeat[] }) {
  const { t } = useT();
  return (
    <div className="panel">
      <h2 className="section-heading">{t("competitionRounds.selection.rosterHeading")}</h2>
      {seats.length === 0 ? (
        <div className="placeholder">{t("competitionRounds.selection.noSeats")}</div>
      ) : (
        <ScrollRegion size="md" label={t("competitionRounds.selection.rosterHeading")}>
          <div className="table-wrap">
            <table className="data-table selection-roster-table">
              <thead>
                <tr>
                  <th>{t("competitionRounds.selection.table.rank")}</th>
                  <th>{t("competitionRounds.table.agent")}</th>
                  <th className="num">{t("competitionRounds.selection.table.liveMedian")}</th>
                  <th className="num">{t("competitionRounds.selection.table.hits")}</th>
                  <th className="num">{t("competitionRounds.selection.table.novelNames")}</th>
                  <th>{t("competitionRounds.selection.table.seatedBy")}</th>
                  <th>{t("competitionRounds.selection.table.note")}</th>
                </tr>
              </thead>
              <tbody>
                {seats.map((seat) => (
                  <SelectionSeatRow key={seat.agent_id} seat={seat} showSeatedColumn={false} />
                ))}
              </tbody>
            </table>
          </div>
        </ScrollRegion>
      )}
    </div>
  );
}

function SelectionRanking({ ranking }: { ranking: SelectionSeat[] }) {
  const { t } = useT();
  return (
    <div className="panel">
      <h2 className="section-heading">{t("competitionRounds.selection.rankingHeading")}</h2>
      {ranking.length === 0 ? (
        <div className="placeholder">{t("competitionRounds.selection.noRanking")}</div>
      ) : (
        <ScrollRegion size="md" label={t("competitionRounds.selection.rankingHeading")}>
          <div className="table-wrap">
            <table className="data-table selection-ranking-table">
              <thead>
                <tr>
                  <th>{t("competitionRounds.selection.table.rank")}</th>
                  <th>{t("competitionRounds.table.agent")}</th>
                  <th className="num">{t("competitionRounds.selection.table.liveMedian")}</th>
                  <th className="num">{t("competitionRounds.selection.table.hits")}</th>
                  <th className="num">{t("competitionRounds.selection.table.novelNames")}</th>
                  <th>{t("competitionRounds.selection.table.seated")}</th>
                  <th>{t("competitionRounds.selection.table.seatedBy")}</th>
                  <th>{t("competitionRounds.selection.table.note")}</th>
                </tr>
              </thead>
              <tbody>
                {ranking.map((seat) => (
                  <SelectionSeatRow key={seat.agent_id} seat={seat} showSeatedColumn={true} />
                ))}
              </tbody>
            </table>
          </div>
        </ScrollRegion>
      )}
    </div>
  );
}

/**
 * One row shared by the roster and full-ranking tables -- both are `SelectionSeat[]`, differing only
 * in whether every row is already known to be seated (the roster) or not (the ranking, which is why
 * it gets its own "Seated" column). `live_median`/`live_hits`/`novel_names` are rendered exactly as
 * the server sent them -- preformatted strings, never reparsed -- per the module docstring.
 *
 * A seat whose `seated_by` is not `"rule"` gets a visibly different badge and a tinted row: the whole
 * point of carrying `seated_by` down to render time is that a card seated outside the rule must never
 * be mistaken for one that won it.
 */
function SelectionSeatRow({ seat, showSeatedColumn }: { seat: SelectionSeat; showSeatedColumn: boolean }) {
  const { t } = useT();
  const wonByRule = seat.seated_by === "rule";
  return (
    <tr className={wonByRule ? "" : "selection-seat-nonrule-row"}>
      <td className="num comp-num">{formatIntOrDash(seat.rank)}</td>
      <td>{seat.agent_id}</td>
      <td className="num comp-num">{seat.live_median ?? "—"}</td>
      <td className="num comp-num">{seat.live_hits ?? "—"}</td>
      <td className="num comp-num">{seat.novel_names ?? "—"}</td>
      {showSeatedColumn && (
        <td>
          <span className={`state-pill ${seat.seated ? "state-true" : "state-false"}`}>
            {seat.seated ? t("competitionRounds.selection.table.seated") : t("competitionRounds.selection.notSeated")}
          </span>
        </td>
      )}
      <td>
        <span className={`badge selection-seated-by-${seat.seated_by}`}>{seatedByLabel(seat.seated_by)}</span>
      </td>
      <td className="selection-note-cell">{seat.note}</td>
    </tr>
  );
}

function SelectionGates({ gates }: { gates: Record<string, GateOutcome[]> }) {
  const { t } = useT();
  const keys = [
    ...GATE_ORDER.filter((k) => k in gates),
    ...Object.keys(gates).filter((k) => !GATE_ORDER.includes(k)),
  ];
  if (keys.length === 0) {
    return (
      <div className="panel">
        <div className="placeholder">{t("competitionRounds.selection.gates.noResults")}</div>
      </div>
    );
  }
  return (
    <>
      {keys.map((key) => (
        <SelectionGateTable key={key} gateKey={key} outcomes={gates[key] ?? []} />
      ))}
    </>
  );
}

function SelectionGateTable({ gateKey, outcomes }: { gateKey: string; outcomes: GateOutcome[] }) {
  // The column set is the union of every outcome's own `detail` keys at this gate, in first-seen
  // order -- a gate's evidence can differ agent to agent (a card rejected early may lack a figure one
  // that passed reports), so the table adapts to whatever this round actually produced rather than
  // assuming a fixed shape the contract does not promise.
  const { t } = useT();
  const detailKeys: string[] = [];
  for (const outcome of outcomes) {
    for (const key of Object.keys(outcome.detail)) {
      if (!detailKeys.includes(key)) detailKeys.push(key);
    }
  }

  return (
    <div className="panel">
      <h2 className="section-heading">{t("competitionRounds.selection.gates.heading", { gateKey })}</h2>
      {outcomes.length === 0 ? (
        <div className="placeholder">{t("competitionRounds.selection.gates.noAgents")}</div>
      ) : (
        <ScrollRegion size="md" label={t("competitionRounds.selection.gates.heading", { gateKey })}>
          <div className="table-wrap">
            <table className="data-table selection-gate-table">
              <thead>
                <tr>
                  <th>{t("competitionRounds.table.agent")}</th>
                  <th>{t("competitionRounds.selection.gates.result")}</th>
                  <th>{t("competitionRounds.selection.gates.reason")}</th>
                  {detailKeys.map((key) => (
                    <th key={key}>{key}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {outcomes.map((outcome) => (
                  <tr
                    key={outcome.agent_id}
                    className={outcome.passed ? "" : "selection-gate-fail-row"}
                  >
                    <td>{outcome.agent_id}</td>
                    <td>
                      <span
                        className={`state-pill ${outcome.passed ? "state-true" : "state-false selection-gate-fail-pill"}`}
                      >
                        {outcome.passed
                          ? t("competitionRounds.selection.gates.pass")
                          : t("competitionRounds.selection.gates.fail")}
                      </span>
                    </td>
                    <td>{outcome.reason}</td>
                    {detailKeys.map((key) => (
                      <td key={key}>{outcome.detail[key] ?? "—"}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ScrollRegion>
      )}
    </div>
  );
}
