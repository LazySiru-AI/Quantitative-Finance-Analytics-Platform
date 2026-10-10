/**
 * Agent Desk landing -- the section rail's first stop now, not `/trading-agents`.
 *
 * Same reasoning as `pages/StrategyLanding.tsx`: `nav.ts` puts this route first in the `agents`
 * section's `items`, so it is what a click on "Agent Desk" in the sidebar now opens (see `App.tsx`'s
 * `Sidebar`). Before this page existed, that click landed cold on a run form for one specific desk,
 * with nothing naming the other three or saying whether the agent layer could even run today.
 *
 * One cheap fetch backs this page, `tradingAgentsApi.config()` -- the same config endpoint
 * `pages/TradingAgents.tsx` already calls on mount, read here only for `agent_available` /
 * `agent_reason`. It is a fair proxy for the whole agent layer: every desk on this section shares
 * the same underlying client (`app.agents.client.is_available()`, per `docs/AGENT-DESK-CONTRACT.md`),
 * so one config call answers "can any of these four desks run right now" without a second request
 * per desk.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { tradingAgentsApi, type TradingAgentsConfig } from "@/api/tradingagents";
import { useT } from "@/i18n";
import { sectionLabelKey } from "@/nav";
import StatusPill, { type PillTone } from "@/components/StatusPill";

import "./AgentDeskLanding.css";

type Phase = "loading" | "loaded" | "error";

function useAgentAvailability(): { config: TradingAgentsConfig | null; phase: Phase } {
  const [config, setConfig] = useState<TradingAgentsConfig | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");

  useEffect(() => {
    const controller = new AbortController();
    tradingAgentsApi
      .config(controller.signal)
      .then((data) => {
        setConfig(data);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setConfig(null);
        setPhase("error");
      });
    return () => controller.abort();
  }, []);

  return { config, phase };
}

const FUNNEL_KEYS = [
  "landing.agents.funnel.ask",
  "landing.agents.funnel.orchestrate",
  "landing.agents.funnel.measure",
  "landing.agents.funnel.follow",
] as const;

/** The pill + line pair, one branch per fetch outcome. Loading reads as "unknown" rather than a
 *  premature "offline" -- a slow config call must not flash a false negative before it resolves. */
function AvailabilityNote({ config, phase }: { config: TradingAgentsConfig | null; phase: Phase }) {
  const { t } = useT();

  if (phase !== "loaded" || config === null) {
    return (
      <>
        <StatusPill tone="neutral" label={t("landing.agents.pill.unknown")} />
        <p className="adl-availability-text">{t("landing.agents.line.unknown")}</p>
      </>
    );
  }

  const tone: PillTone = config.agent_available ? "ok" : "bad";
  const pillLabel = config.agent_available
    ? t("landing.agents.pill.available")
    : t("landing.agents.pill.unavailable");
  const line = config.agent_available
    ? t("landing.agents.line.available")
    : t("landing.agents.line.unavailable", { reason: config.agent_reason });

  return (
    <>
      <StatusPill tone={tone} label={pillLabel} />
      <p className="adl-availability-text">{line}</p>
    </>
  );
}

export default function AgentDeskLanding() {
  const { t } = useT();
  const { config, phase } = useAgentAvailability();

  return (
    <div className="adl-page">
      <h1>{t(sectionLabelKey("agents"))}</h1>
      <p className="subtitle">{t("landing.agents.subtitle")}</p>

      <section className="panel adl-availability">
        <AvailabilityNote config={config} phase={phase} />
      </section>

      <section className="panel">
        <h2>{t("landing.agents.funnel.heading")}</h2>
        <div className="adl-funnel" role="list">
          {FUNNEL_KEYS.map((key, i) => (
            <span className="adl-funnel-step" role="listitem" key={key}>
              {i > 0 && (
                <span className="adl-funnel-arrow" aria-hidden="true">
                  →
                </span>
              )}
              {t(key)}
            </span>
          ))}
        </div>
      </section>

      <section className="panel">
        <h2>{t("landing.agents.tryThis.heading")}</h2>
        <div className="adl-cards">
          {/* Both cards now point at `/research-desk` -- the analyst-pipeline and committee desks
              live behind one page's toggle since `ResearchDesk.tsx` folded the two nav entries
              together. The cards themselves stay distinct: each still names its own desk. */}
          <Link to="/research-desk" className="adl-card">
            <span className="adl-card-title">{t("landing.agents.card.researchTicker.title")}</span>
            <span className="adl-card-blurb">{t("landing.agents.card.researchTicker.blurb")}</span>
          </Link>
          <Link to="/research-desk" className="adl-card">
            <span className="adl-card-title">{t("landing.agents.card.askCommittee.title")}</span>
            <span className="adl-card-blurb">{t("landing.agents.card.askCommittee.blurb")}</span>
          </Link>
          <Link to="/agent-workflow" className="adl-card">
            <span className="adl-card-title">{t("landing.agents.card.runWorkflow.title")}</span>
            <span className="adl-card-blurb">{t("landing.agents.card.runWorkflow.blurb")}</span>
          </Link>
        </div>
      </section>
    </div>
  );
}

// Re-exported for the page's own test, which asserts the funnel renders every step in order
// without duplicating the key list.
export { FUNNEL_KEYS as AGENT_DESK_FUNNEL_KEYS };
