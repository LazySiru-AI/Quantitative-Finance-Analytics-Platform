/**
 * One line naming the single source every price on this page depends on.
 *
 * The provider registry walks a two-provider chain for bars and one of them — Stooq — has been
 * unable to answer since Phase 4, so in practice there is no fallback. The failure itself is
 * handled honestly: an exhausted walk raises with what every provider said, so an outage is never
 * silently reported as "no data". What was missing is the *structural* fact, which is only
 * discoverable today by reading the registry's source: there is one working source of market data.
 *
 * Rendered as a muted line rather than a banner, and only when the count is actually one. A warning
 * that appears on every visit and describes a condition the user cannot change stops being read
 * within a week, and takes the genuinely actionable warnings beside it down with it.
 */

import { useEffect, useState } from "react";

import { api, type ProviderHealth } from "@/api/client";
import { Trans, useT } from "@/i18n";

export default function ProviderNote() {
  const { t } = useT();
  const [health, setHealth] = useState<ProviderHealth | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .providers(controller.signal)
      .then(setHealth)
      .catch(() => {
        // Silent. This is a footnote about data sources; a failure to fetch the footnote is not
        // something to put on screen above the data it annotates.
      });
    return () => controller.abort();
  }, []);

  const single = health?.bars.single_point_of_failure;
  if (!health || !single) return null;

  const degraded = health.providers.filter((p) => p.role === "bars" && !p.usable);

  return (
    <p className="provider-note muted">
      <Trans k="desk.providerNote.main" values={{ single: <strong>{single}</strong> }} />
      {degraded.length > 0 &&
        t(degraded.length === 1 ? "desk.providerNote.degraded_one" : "desk.providerNote.degraded_other", {
          names: degraded.map((p) => p.name).join(", "),
        })}
      {t("desk.providerNote.outage")}
    </p>
  );
}
