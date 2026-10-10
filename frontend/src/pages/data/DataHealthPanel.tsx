/**
 * Data health: status of the two background jobs `dataAdminApi` already exposed -- the market-data
 * refresh sweep and the social-snapshot scheduler -- plus, now, a way to trigger a fresh sweep and
 * a per-source freshness table (`GET /api/data/freshness`).
 *
 * The freshness table's `key`/`status` fields are closed unions today, but a value outside them
 * must never throw: see `@/api/dataAdmin`'s docstring and `closed-unions-over-server-data-kill-
 * pages` in this repo's memory (a throwing exhaustiveness check over a server string took a whole
 * page down before). Every lookup below falls back to a neutral rendering of the raw value instead.
 *
 * The freshness section fails soft, independently of the refresh/social section: those two load
 * exactly as before (loading/ready/error), and a `freshness()` failure only blanks its own panel
 * with its own error line rather than taking the rest of the tab down with it.
 */
import { useCallback, useEffect, useState } from "react";

import { describeError } from "@/api/client";
import {
  dataAdminApi,
  type FreshnessReport,
  type FreshnessSource,
  type RefreshStatus,
  type SocialStatus,
} from "@/api/dataAdmin";
import { telemetryApi, type NavRouteSummary } from "@/api/telemetry";
import { InfoNote } from "@/components/InfoNote";
import { ScrollRegion } from "@/components/ScrollPanel";
import { StatTile } from "@/components/StatGrid";
import StatusPill, { type PillTone } from "@/components/StatusPill";
import { type MessageKey, type Translator, useT } from "@/i18n";

type Phase = "loading" | "ready" | "error";

const SOURCE_LABEL_KEYS: Record<FreshnessSource["key"], MessageKey> = {
  bars_daily: "data.freshness.source.bars_daily",
  bars_intraday: "data.freshness.source.bars_intraday",
  macro_snapshot: "data.freshness.source.macro_snapshot",
  calendar_events: "data.freshness.source.calendar_events",
  fundamentals_edgar: "data.freshness.source.fundamentals_edgar",
  institutions_filings: "data.freshness.source.institutions_filings",
  news: "data.freshness.source.news",
  social_snapshots: "data.freshness.source.social_snapshots",
  live_quotes: "data.freshness.source.live_quotes",
  ledger: "data.freshness.source.ledger",
  persona_corpus: "data.freshness.source.persona_corpus",
};

const CLASS_LABEL_KEYS: Record<FreshnessSource["freshness_class"], MessageKey> = {
  day_frame: "data.freshness.class.day_frame",
  intraday: "data.freshness.class.intraday",
  local: "data.freshness.class.local",
};

const POLICY_LABEL_KEYS: Record<FreshnessSource["policy"], MessageKey> = {
  on_demand: "data.freshness.policy.on_demand",
  startup_sweep: "data.freshness.policy.startup_sweep",
  scheduled: "data.freshness.policy.scheduled",
  streaming: "data.freshness.policy.streaming",
  computed: "data.freshness.policy.computed",
  manual: "data.freshness.policy.manual",
};

const STATUS_LABEL_KEYS: Record<FreshnessSource["status"], MessageKey> = {
  fresh: "data.freshness.status.fresh",
  live: "data.freshness.status.live",
  stale: "data.freshness.status.stale",
  disabled: "data.freshness.status.disabled",
  unknown: "data.freshness.status.unknown",
};

const STATUS_TONE: Record<FreshnessSource["status"], PillTone> = {
  fresh: "ok",
  live: "special",
  stale: "warn",
  disabled: "neutral",
  unknown: "info",
};

/**
 * Looks a server-supplied string up in one of the maps above, falling back to the raw value when
 * it names something outside today's known set -- never an exhaustiveness throw. `Record<K, V>` is
 * only a compile-time promise that every *known* key is covered; `hasOwnProperty` is the runtime
 * check that a value claiming to be `K` actually is one.
 */
function lookupLabel<K extends string>(map: Record<K, MessageKey>, key: string, t: Translator): string {
  return Object.prototype.hasOwnProperty.call(map, key) ? t(map[key as K]) : key;
}

function statusTone(status: string): PillTone {
  return Object.prototype.hasOwnProperty.call(STATUS_TONE, status)
    ? STATUS_TONE[status as FreshnessSource["status"]]
    : "neutral";
}

/** "3m" / "5h" / "2d" -- the coarsest unit that keeps the number small and readable. */
function formatAge(seconds: number | null, t: Translator): string {
  if (seconds === null || seconds < 0) return t("data.freshness.age.none");
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return t("data.freshness.age.minutes", { n: Math.max(minutes, 0) });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t("data.freshness.age.hours", { n: hours });
  const days = Math.floor(hours / 24);
  return t("data.freshness.age.days", { n: days });
}

/**
 * Owner-only rollup of `GET /api/telemetry/nav/summary` -- which pages and tabs are actually used.
 * A member gets a 403 from the gate; that, and any other failure, renders nothing rather than a
 * callout, because "you can't see this" is not a data-health finding worth a member's attention.
 * Loads independently of the refresh/social/freshness panels above: it neither waits on their
 * `phase` nor can break them, matching the freshness panel's own "fails soft, on its own" pattern.
 */
function NavTelemetryPanel() {
  const { t } = useT();
  const [routes, setRoutes] = useState<NavRouteSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    telemetryApi
      .summary(30)
      .then((result) => {
        if (!cancelled) setRoutes(result.routes);
      })
      .catch(() => {
        // Owner-only (403 for a member) or any other failure -- stay hidden, nothing to render.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (routes === null) return null;

  return (
    <div className="panel">
      <h3>{t("data.health.nav.heading")}</h3>
      <ScrollRegion size="md" label={t("data.health.nav.heading")}>
        <table className="data-table">
          <thead>
            <tr>
              <th>{t("data.health.nav.page")}</th>
              <th>{t("data.health.nav.tab")}</th>
              <th>{t("data.health.nav.hits")}</th>
              <th>{t("data.health.nav.lastSeen")}</th>
            </tr>
          </thead>
          <tbody>
            {routes.length === 0 ? (
              <tr>
                <td colSpan={4}>{t("data.health.nav.empty")}</td>
              </tr>
            ) : (
              routes.map((route) => (
                <tr key={`${route.path}::${route.tab ?? ""}`}>
                  <td>{route.path}</td>
                  <td>{route.tab ?? t("common.none")}</td>
                  <td>{route.hits}</td>
                  <td>{route.last_ts}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </ScrollRegion>
    </div>
  );
}

export default function DataHealthPanel() {
  const { t } = useT();
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [refresh, setRefresh] = useState<RefreshStatus | null>(null);
  const [social, setSocial] = useState<SocialStatus | null>(null);
  const [freshness, setFreshness] = useState<FreshnessReport | null>(null);
  const [freshnessError, setFreshnessError] = useState<string | null>(null);

  const [triggering, setTriggering] = useState(false);
  const [triggerNote, setTriggerNote] = useState<string | null>(null);
  const [triggerError, setTriggerError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([
      dataAdminApi.refreshStatus(controller.signal),
      dataAdminApi.socialStatus(controller.signal),
      dataAdminApi.freshness(controller.signal).then(
        (report) => ({ ok: true as const, report }),
        (error: unknown) => ({ ok: false as const, error }),
      ),
    ])
      .then(([refreshResult, socialResult, freshnessResult]) => {
        setRefresh(refreshResult);
        setSocial(socialResult);
        setPhase("ready");
        if (freshnessResult.ok) {
          setFreshness(freshnessResult.report);
          setFreshnessError(null);
        } else {
          setFreshnessError(describeError(freshnessResult.error, t("data.freshness.loading.error")));
        }
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setMessage(describeError(error, t("data.health.error.generic")));
        setPhase("error");
      });
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one-shot load, `t` is stable enough here
  }, []);

  // Poll the sweep's own status while it runs, stop the moment it doesn't. Only ever one interval
  // instance per "running" stretch: the effect is keyed on the boolean, not the whole `refresh`
  // object, so a tick that leaves `running` true does not tear down and restart the timer.
  useEffect(() => {
    if (!refresh?.running) return;
    const id = setInterval(() => {
      dataAdminApi
        .refreshStatus()
        .then((status) => {
          setRefresh(status);
          if (!status.running) {
            // The sweep just finished -- ages in the freshness table are now stale by definition;
            // pull it once more so they reflect what the sweep just did.
            dataAdminApi
              .freshness()
              .then((report) => {
                setFreshness(report);
                setFreshnessError(null);
              })
              .catch(() => {
                // Transient failure on this one re-fetch -- leave the last-known table on screen.
              });
          }
        })
        .catch(() => {
          // Transient poll failure -- keep the last-known status on screen and try again in 2s.
        });
    }, 2000);
    return () => clearInterval(id);
  }, [refresh?.running]);

  const handleFetchNow = useCallback(() => {
    setTriggering(true);
    setTriggerNote(null);
    setTriggerError(null);
    dataAdminApi
      .triggerRefresh()
      .then((result) => {
        setRefresh(result.status);
        if (!result.started) {
          setTriggerNote(t("data.health.fetch.alreadyRunning"));
        }
      })
      .catch((error: unknown) => {
        setTriggerError(describeError(error, t("data.health.fetch.error")));
      })
      .finally(() => setTriggering(false));
  }, [t]);

  const fetchDisabled = triggering || phase === "loading" || Boolean(refresh?.running);

  return (
    <section className="panel">
      <h2>{t("data.health.heading")}</h2>
      <p className="subtitle">{t("data.health.subtitle")}</p>

      <div className="tile-grid">
        <button
          type="button"
          className="symbol-submit"
          onClick={handleFetchNow}
          disabled={fetchDisabled}
        >
          {triggering || refresh?.running ? t("data.health.fetch.fetching") : t("data.health.fetch.action")}
        </button>
      </div>
      {triggerNote && <p className="muted">{triggerNote}</p>}
      {triggerError && <p className="callout callout-danger">{triggerError}</p>}

      {phase === "loading" && <div className="placeholder">{t("data.health.loading")}</div>}
      {phase === "error" && <div className="placeholder">{message}</div>}

      {phase === "ready" && refresh && social && (
        <>
          <div className="panel">
            <h3>
              {t("data.health.refresh.heading")}{" "}
              <StatusPill
                tone={refresh.running ? "info" : refresh.complete ? "ok" : "warn"}
                label={
                  refresh.running
                    ? t("data.health.refresh.running")
                    : refresh.complete
                      ? t("data.health.refresh.complete")
                      : t("data.health.refresh.incomplete")
                }
              />
            </h3>
            <div className="tile-grid">
              <StatTile
                label={t("data.health.refresh.processed")}
                value={`${refresh.processed} / ${refresh.queued}`}
              />
              <StatTile label={t("data.health.refresh.failed")} value={String(refresh.failed)} />
              <StatTile
                label={t("data.health.refresh.macroSnapshot")}
                value={refresh.macro_snapshot ?? t("common.none")}
              />
              <StatTile
                label={t("data.health.refresh.socialSnapshots")}
                value={refresh.social_snapshots}
              />
            </div>
            {refresh.started_at ? (
              <p className="muted">
                {t("data.health.refresh.lastRun", {
                  started: refresh.started_at,
                  finished: refresh.finished_at ?? t("common.none"),
                })}
              </p>
            ) : (
              <p className="muted">{t("data.health.refresh.neverRun")}</p>
            )}
            {refresh.failed_symbols.length > 0 && (
              <p className="muted">
                {t("data.health.refresh.failedSymbols")}: {refresh.failed_symbols.join(", ")}
              </p>
            )}
          </div>

          <div className="panel">
            <h3>
              {t("data.health.social.heading")}{" "}
              <StatusPill
                tone={social.healthy ? "ok" : "bad"}
                label={social.healthy ? t("data.health.social.healthy") : t("data.health.social.unhealthy")}
              />
            </h3>
            <div className="tile-grid">
              <StatTile label={t("data.health.social.totalTicks")} value={String(social.total_ticks)} />
              <StatTile
                label={t("data.health.social.failureStreak")}
                value={`${social.consecutive_all_failed_ticks} / ${social.max_consecutive_all_failed_ticks}`}
                hint={t("data.health.social.consecutiveFailures", {
                  count: social.consecutive_all_failed_ticks,
                  max: social.max_consecutive_all_failed_ticks,
                })}
              />
            </div>
            {social.last_tick_at ? (
              <p className="muted">{t("data.health.social.lastTick", { when: social.last_tick_at })}</p>
            ) : (
              <p className="muted">{t("data.health.social.neverTicked")}</p>
            )}
            {social.last_error && (
              <p className="callout callout-danger panel">
                {t("data.health.social.lastError", { error: social.last_error })}
              </p>
            )}
          </div>

          <div className="panel">
            <h3>{t("data.freshness.heading")}</h3>
            {freshnessError && <p className="callout callout-warn">{freshnessError}</p>}
            {freshness && (
              <>
                <ScrollRegion size="md" label={t("data.freshness.table.label")}>
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th>{t("data.freshness.table.source")}</th>
                        <th>{t("data.freshness.table.class")}</th>
                        <th>{t("data.freshness.table.policy")}</th>
                        <th>{t("data.freshness.table.lastUpdated")}</th>
                        <th>{t("data.freshness.table.age")}</th>
                        <th>{t("data.freshness.table.status")}</th>
                        <th>{t("data.freshness.table.refreshable")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {freshness.sources.map((source) => (
                        <tr key={source.key}>
                          <td>{lookupLabel(SOURCE_LABEL_KEYS, source.key, t)}</td>
                          <td>{lookupLabel(CLASS_LABEL_KEYS, source.freshness_class, t)}</td>
                          <td>{lookupLabel(POLICY_LABEL_KEYS, source.policy, t)}</td>
                          <td>{source.last_updated ?? t("common.none")}</td>
                          <td>{formatAge(source.age_seconds, t)}</td>
                          <td>
                            <StatusPill
                              tone={statusTone(source.status)}
                              label={lookupLabel(STATUS_LABEL_KEYS, source.status, t)}
                              detail={source.detail}
                            />
                          </td>
                          <td>
                            {source.refreshable
                              ? t("data.freshness.refreshable.yes")
                              : t("data.freshness.refreshable.no")}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </ScrollRegion>
                <InfoNote summary={t("data.freshness.note.summary")}>
                  <p>{t("data.freshness.note.dayFrame")}</p>
                  <p>{t("data.freshness.note.intraday")}</p>
                  <p>{t("data.freshness.note.local")}</p>
                </InfoNote>
              </>
            )}
          </div>
        </>
      )}

      <NavTelemetryPanel />
    </section>
  );
}
