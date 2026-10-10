/**
 * Data > About: what this instance stores, what leaves the machine, how long it is kept, and who can
 * sign in -- the plain-language counterpart to the rest of the Data page's operator tools. Every
 * signed-in user can open this tab (unlike four of its siblings, see `Data.tsx`'s own docstring),
 * because `GET /api/data/retention` is deliberately not owner-only -- see that endpoint's own
 * docstring in `backend/app/api/data_admin.py` for the "counts and generic names only, never a path
 * or an account label" contract every figure below is held to.
 *
 * **Static sections never depend on the fetch.** Where your data lives, what leaves this machine,
 * login/roles and the not-advice line are all fixed facts about this application, not numbers read
 * off disk -- they render immediately and stay up even if `/api/data/retention` fails. Only the
 * counts under "How long history is kept" (and the delete-control list, which rides along in the
 * same response) are gated on the fetch, and a failure there is a one-line note beside them, per this
 * panel's error-state contract -- never a page-wide blank.
 *
 * **`purge_endpoints` is rendered through a lookup with a raw fallback**, the same
 * `closed-unions-over-server-data-kill-pages` pattern `DataHealthPanel.tsx` already uses for
 * `FreshnessSource`: a route this panel does not recognise yet renders its own raw string linked to
 * `/data` rather than throwing or silently vanishing.
 */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { describeError } from "@/api/client";
import { dataAdminApi, type RetentionReport } from "@/api/dataAdmin";
import { useAuth } from "@/auth";
import { InfoNote } from "@/components/InfoNote";
import { StatTile } from "@/components/StatGrid";
import StatusPill from "@/components/StatusPill";
import { Trans, useT } from "@/i18n";

type Phase = "loading" | "ready" | "error";

/** One entry per `_PURGE_ENDPOINTS` route the backend documents today (`app.api.data_admin`). A
 *  route this panel has never seen renders its own raw string via the `default` branch below rather
 *  than throwing -- the same "known subset of a wider server string" contract `DataHealthPanel.tsx`
 *  already holds `FreshnessSource` to. */
function purgeEndpointInfo(endpoint: string, t: ReturnType<typeof useT>["t"]): { label: string; to: string } {
  switch (endpoint) {
    case "DELETE /api/manager/chats/{thread_id}":
      return { label: t("data.about.purge.managerChats"), to: "/manager" };
    case "DELETE /api/personas/{slug}":
      return { label: t("data.about.purge.personas"), to: "/personas" };
    case "DELETE /api/personas/{slug}/sources/{source_id}":
      return { label: t("data.about.purge.personaSources"), to: "/personas" };
    case "DELETE /api/personas/{slug}/chats/{thread_id}":
      return { label: t("data.about.purge.personaChats"), to: "/personas" };
    case "DELETE /api/personas/{slug}/trader":
      return { label: t("data.about.purge.personaTrader"), to: "/personas" };
    default:
      return { label: endpoint, to: "/data" };
  }
}

export default function AboutPanel() {
  const { t } = useT();
  const { authEnabled, role } = useAuth();
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [retention, setRetention] = useState<RetentionReport | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    dataAdminApi
      .retention(controller.signal)
      .then((report) => {
        setRetention(report);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setMessage(describeError(error, t("data.about.error.generic")));
        setPhase("error");
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot load, `t` is stable enough here
  }, []);

  const totalChats = retention ? retention.manager_chats.count + retention.persona_chats.count : 0;
  const totalDeskRuns = retention
    ? Object.values(retention.desk_runs).reduce((sum, n) => sum + n, 0)
    : 0;
  const deskRunsHint = retention
    ? Object.entries(retention.desk_runs)
        .map(([kind, n]) => `${kind} ${n}`)
        .join(", ")
    : "";

  return (
    <section className="panel">
      <h2>{t("data.about.heading")}</h2>
      <p className="subtitle">{t("data.about.subtitle")}</p>

      <div className="panel">
        <h3>{t("data.about.location.heading")}</h3>
        <InfoNote summary={t("data.about.location.summary")}>
          <p>{t("data.about.location.detail")}</p>
        </InfoNote>
      </div>

      <div className="panel">
        <h3>{t("data.about.egress.heading")}</h3>
        <InfoNote summary={t("data.about.egress.summary")}>
          <p>{t("data.about.egress.detail")}</p>
          <p>
            <Link to="/manager">{t("data.about.egress.managerLink")}</Link>
          </p>
        </InfoNote>
      </div>

      <div className="panel">
        <h3>{t("data.about.retention.heading")}</h3>
        <InfoNote summary={t("data.about.retention.summary")}>
          <p>{t("data.about.retention.detail")}</p>
          <p>
            <Trans
              k="data.about.retention.manage"
              values={{
                manager: <Link to="/manager">{t("nav.page./manager.label")}</Link>,
                personas: <Link to="/personas">{t("nav.page./personas.label")}</Link>,
              }}
            />
          </p>
        </InfoNote>

        {phase === "loading" && <div className="placeholder">{t("data.about.loading")}</div>}
        {phase === "error" && <p className="muted">{message}</p>}

        {phase === "ready" && retention && (
          <>
            <div className="tile-grid">
              <StatTile
                label={t("data.about.stat.ledger")}
                value={String(retention.ledger.transactions)}
              />
              <StatTile label={t("data.about.stat.users")} value={String(retention.auth.users)} />
              <StatTile
                label={t("data.about.stat.managerBriefs")}
                value={String(retention.manager_briefs.count)}
                hint={
                  retention.manager_briefs.count > 0
                    ? t("data.about.retention.briefRange", {
                        oldest: retention.manager_briefs.oldest ?? "",
                        newest: retention.manager_briefs.newest ?? "",
                      })
                    : t("data.about.retention.noBriefs")
                }
              />
              <StatTile
                label={t("data.about.stat.chatThreads")}
                value={String(totalChats)}
                hint={t("data.about.stat.chatThreads.hint", {
                  manager: retention.manager_chats.count,
                  persona: retention.persona_chats.count,
                })}
              />
              <StatTile
                label={t("data.about.stat.personaNotes")}
                value={String(retention.persona_vault_notes.count)}
              />
              <StatTile
                label={t("data.about.stat.deskRuns")}
                value={String(totalDeskRuns)}
                hint={deskRunsHint}
              />
              <StatTile
                label={t("data.about.stat.paperdeskBooks")}
                value={String(retention.paperdesk_books.count)}
              />
              <StatTile
                label={t("data.about.cache.label")}
                value={
                  retention.i18n_cache.present
                    ? t("data.about.cache.present")
                    : t("data.about.cache.absent")
                }
              />
            </div>

            <p className="muted">
              <StatusPill tone="neutral" label={t("data.freshness.policy.manual")} />
            </p>

            <h4>{t("data.about.purge.heading")}</h4>
            <ul>
              {retention.purge_endpoints.map((endpoint) => {
                const info = purgeEndpointInfo(endpoint, t);
                return (
                  <li key={endpoint}>
                    <Link to={info.to}>{info.label}</Link>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      <div className="panel">
        <h3>{t("data.about.auth.heading")}</h3>
        <div className="status-grid">
          <div className="stat">
            <span className="label">{t("data.about.auth.roleLabel")}</span>
            <span className="value">
              {role === "member" ? t("data.users.role.member") : t("data.users.role.owner")}
            </span>
          </div>
          <div className="stat">
            <span className="label">{t("data.about.auth.enabledLabel")}</span>
            {authEnabled ? (
              <span className="value">{t("data.about.auth.on")}</span>
            ) : (
              <StatusPill tone="warn" label={t("auth.gateOff")} detail={t("auth.gateOff.detail")} />
            )}
          </div>
        </div>
      </div>

      <div className="panel">
        <h3>{t("data.about.notAdvice.heading")}</h3>
        <p>
          <StatusPill tone="neutral" label={t("ui.pill.notAdvice")} /> {t("tax.disclaimer.title")}
        </p>
      </div>
    </section>
  );
}
