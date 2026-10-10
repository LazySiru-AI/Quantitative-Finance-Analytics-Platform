/**
 * Live Decisions: the live-quote daemon's own status, its recent decisions, and a manual "Decide
 * now" for one symbol -- mounted at the bottom of `TradingAgents.tsx`.
 *
 * **Fails soft.** `GET /api/agentdesk/live/status` and `GET /api/agentdesk/live/decisions` are new
 * routes -- if the backend serving this session has not been restarted yet, they 404, and this
 * panel renders a single muted line (`agentDesk.live.unavailable`) instead of a red error callout
 * that would otherwise sit at the bottom of an unrelated page. Any failure on the initial load is
 * treated the same way, not just a 404: there is nothing actionable a reader can do about either
 * one, and the run form above already works without this panel.
 *
 * **`stance`/`source` are closed unions of today's known wire values, but a value outside either
 * must never throw** -- this repo has already lost a whole page once to a throwing exhaustiveness
 * check over a server-supplied string (see `closed-unions-over-server-data-kill-pages` in this
 * repo's own history, and `@/pages/data/DataHealthPanel.tsx`'s `lookupLabel`/`statusTone`, whose
 * `hasOwnProperty` fallback pattern this file copies for the same reason). An unknown value renders
 * as a neutral pill labelled with the raw string, never a crash.
 *
 * **Status re-polls every 60s** while this panel stays mounted -- coarser than the two desks' own
 * 2000ms run-progress poll, because a background daemon's status changes on the order of minutes
 * (`interval_minutes`), not seconds. A transient poll failure is swallowed and the last-known
 * status stays on screen, same pattern `TradingAgents.tsx`'s/`VibeTrading.tsx`'s own run-poll
 * effects already use.
 *
 * Nothing in this panel places a trade, and none of it is investment advice -- see
 * `agentDesk.live.note`, always visible via `InfoNote`.
 */
import { useCallback, useEffect, useState } from "react";

import { describeError } from "@/api/client";
import { liveDecisionsApi, type LiveDecisionRecord, type LiveStatus } from "@/api/liveDecisions";
import { InfoNote } from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import { StatTile } from "@/components/StatGrid";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import { formatMoney, formatMoneyOrDash } from "@/format/money";
import { useFetch } from "@/hooks/useFetch";
import { type MessageKey, type Translator, useT } from "@/i18n";

/** Coarser than the two desks' own 2000ms run-progress poll -- see this module's own docstring. */
const STATUS_POLL_MS = 60_000;

/** How many recent decisions the initial load asks for. Not user-adjustable today -- there is no
 *  pager on this panel, only the bounded `ScrollRegion` below. */
const DECISIONS_LIMIT = 20;

interface LiveData {
  status: LiveStatus;
  decisions: LiveDecisionRecord[];
}

const STANCE_LABEL_KEYS: Record<LiveDecisionRecord["stance"], MessageKey> = {
  buy: "agentDesk.live.stance.buy",
  sell: "agentDesk.live.stance.sell",
  hold: "agentDesk.live.stance.hold",
  no_action: "agentDesk.live.stance.noAction",
};

const STANCE_TONE: Record<LiveDecisionRecord["stance"], PillTone> = {
  buy: "ok",
  sell: "bad",
  hold: "info",
  no_action: "neutral",
};

const SOURCE_LABEL_KEYS: Record<LiveDecisionRecord["source"], MessageKey> = {
  daemon: "agentDesk.live.source.daemon",
  manual: "agentDesk.live.source.manual",
};

/** Looks a server-supplied string up in one of the maps above, falling back to the raw value when
 *  it names something outside today's known set -- never an exhaustiveness throw. Copied from
 *  `@/pages/data/DataHealthPanel.tsx`'s own `lookupLabel` (same shape, same reason). */
function lookupLabel<K extends string>(map: Record<K, MessageKey>, key: string, t: Translator): string {
  return Object.prototype.hasOwnProperty.call(map, key) ? t(map[key as K]) : key;
}

function stanceTone(stance: string): PillTone {
  return Object.prototype.hasOwnProperty.call(STANCE_TONE, stance)
    ? STANCE_TONE[stance as LiveDecisionRecord["stance"]]
    : "neutral";
}

export default function LiveDecisionsPanel() {
  const { t } = useT();

  const initial = useFetch<LiveData>(async (signal) => {
    const [status, decisionsRes] = await Promise.all([
      liveDecisionsApi.status(signal),
      liveDecisionsApi.decisions(undefined, DECISIONS_LIMIT, signal),
    ]);
    return { status, decisions: decisionsRes.decisions };
  }, []);
  const { phase, data, setData } = initial;

  // Re-poll status every 60s while this panel stays mounted -- see the module docstring. Only once
  // the initial combined load has actually landed: polling on top of a still-`"loading"`/`"error"`
  // phase would either race the first request or keep hammering an endpoint already known to fail.
  useEffect(() => {
    if (phase !== "loaded") return;
    const id = setInterval(() => {
      liveDecisionsApi
        .status()
        .then((status) => {
          setData((prev) => (prev ? { ...prev, status } : prev));
        })
        .catch(() => {
          // Transient poll failure -- keep the last-known status on screen and try again next tick.
        });
    }, STATUS_POLL_MS);
    return () => clearInterval(id);
  }, [phase, setData]);

  // --- decide now ------------------------------------------------------------------------------
  const [symbolInput, setSymbolInput] = useState("");
  const [deciding, setDeciding] = useState(false);
  const [decideError, setDecideError] = useState<string | null>(null);

  const handleDecideNow = useCallback(() => {
    const symbol = symbolInput.trim().toUpperCase();
    if (!symbol) return;
    setDeciding(true);
    setDecideError(null);
    liveDecisionsApi
      .decideNow(symbol)
      .then((res) => {
        // Prepend rather than re-fetching the whole list -- the endpoint already handed back the
        // one record that changed.
        setData((prev) => (prev ? { ...prev, decisions: [res.decision, ...prev.decisions] } : prev));
        setSymbolInput("");
      })
      .catch((err: unknown) => {
        setDecideError(describeError(err, t("agentDesk.live.decideNow.error")));
      })
      .finally(() => setDeciding(false));
  }, [symbolInput, setData, t]);

  if (phase === "loading") {
    return (
      <section className="panel">
        <h2>{t("agentDesk.live.heading")}</h2>
        <div className="placeholder">{t("agentDesk.live.loading")}</div>
      </section>
    );
  }

  if (phase === "error" || !data) {
    return (
      <section className="panel">
        <h2>{t("agentDesk.live.heading")}</h2>
        <p className="muted">{t("agentDesk.live.unavailable")}</p>
      </section>
    );
  }

  const { status, decisions } = data;

  return (
    <section className="panel">
      <h2>{t("agentDesk.live.heading")}</h2>
      <InfoNote summary={t("agentDesk.live.note")} />

      <div className="tile-grid">
        <StatusPill
          tone={status.enabled ? "ok" : "neutral"}
          label={status.enabled ? t("agentDesk.live.status.enabled") : t("agentDesk.live.status.disabled")}
        />
        <StatusPill
          tone={status.running ? "info" : "neutral"}
          label={status.running ? t("agentDesk.live.status.running") : t("agentDesk.live.status.stopped")}
        />
        <StatusPill
          tone={status.healthy === null ? "neutral" : status.healthy ? "ok" : "bad"}
          label={
            status.healthy === null
              ? t("agentDesk.live.status.healthUnknown")
              : status.healthy
                ? t("agentDesk.live.status.healthy")
                : t("agentDesk.live.status.unhealthy")
          }
        />
      </div>

      <div className="tile-grid">
        <StatTile label={t("agentDesk.live.stat.marketState")} value={status.market_state ?? t("common.none")} />
        <StatTile label={t("agentDesk.live.stat.lastTick")} value={status.last_tick_at ?? t("common.none")} />
        <StatTile label={t("agentDesk.live.stat.nextWake")} value={status.next_wake_at ?? t("common.none")} />
        <StatTile label={t("agentDesk.live.stat.ticks")} value={String(status.ticks)} />
        <StatTile label={t("agentDesk.live.stat.decisionsToday")} value={String(status.decisions_today)} />
        <StatTile label={t("agentDesk.live.stat.failures")} value={String(status.consecutive_failures)} />
        <StatTile
          label={t("agentDesk.live.stat.interval")}
          value={t("agentDesk.live.stat.intervalValue", { n: status.interval_minutes })}
        />
        <StatTile label={t("agentDesk.live.stat.cap")} value={formatMoney(status.cap_usd)} />
      </div>
      {status.symbols.length > 0 && (
        <p className="muted">{t("agentDesk.live.stat.symbols", { symbols: status.symbols.join(", ") })}</p>
      )}

      <div className="filter-bar">
        <label>
          <span>{t("common.symbol")}</span>
          <input
            className="symbol-input"
            value={symbolInput}
            onChange={(e) => setSymbolInput(e.target.value.toUpperCase())}
            placeholder="NVDA"
            disabled={deciding}
          />
        </label>
        <button
          type="button"
          className="symbol-submit"
          onClick={handleDecideNow}
          disabled={deciding || !symbolInput.trim()}
        >
          {deciding ? t("agentDesk.live.decideNow.deciding") : t("agentDesk.live.decideNow.action")}
        </button>
      </div>
      {decideError && <p className="callout callout-danger">{decideError}</p>}

      {decisions.length === 0 ? (
        <div className="placeholder">{t("agentDesk.live.decisions.empty")}</div>
      ) : (
        <ScrollRegion size="md" label={t("agentDesk.live.decisions.title")}>
          <table className="data-table">
            <thead>
              <tr>
                <th>{t("agentDesk.live.decisions.col.time")}</th>
                <th>{t("agentDesk.live.decisions.col.symbol")}</th>
                <th>{t("agentDesk.live.decisions.col.stance")}</th>
                <th>{t("agentDesk.live.decisions.col.confidence")}</th>
                <th>{t("agentDesk.live.decisions.col.price")}</th>
                <th>{t("agentDesk.live.decisions.col.source")}</th>
                <th>{t("agentDesk.live.decisions.col.model")}</th>
                <th>{t("agentDesk.live.decisions.col.cost")}</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((d, i) => (
                <tr key={`${d.symbol}-${d.decided_at}-${i}`}>
                  <td>{d.decided_at}</td>
                  <td>{d.symbol}</td>
                  <td>
                    <StatusPill
                      tone={stanceTone(d.stance)}
                      label={lookupLabel(STANCE_LABEL_KEYS, d.stance, t)}
                      detail={d.rationale}
                    />
                    {d.degraded && (
                      <StatusPill tone="warn" label={t("agentDesk.live.decisions.degraded")} />
                    )}
                  </td>
                  <td>{d.confidence.toFixed(2)}</td>
                  <td>{formatMoneyOrDash(d.price)}</td>
                  <td>{lookupLabel(SOURCE_LABEL_KEYS, d.source, t)}</td>
                  <td>{d.model}</td>
                  <td>{formatMoney(d.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollRegion>
      )}
    </section>
  );
}
