/**
 * Sector classification: the read + write UI over `GET/PUT /api/portfolio/sectors`.
 *
 * Reuses `portfolioApi.sectors()`/`portfolioApi.setSector()` (`@/api/portfolio`) rather than a new
 * client -- `SectorBadgeEditor.tsx` already calls the exact same endpoints for the Account page's
 * inline row editor, and this panel is the same contract at a different grain (every classified
 * symbol in one table, for an operator doing bulk cleanup, rather than one row's badge). No new
 * fetch code is added for this tab; see the Data-page-level report for why.
 *
 * Each row edits independently: picking a new sector from the vocabulary enables that row's own
 * Save button, and only that row's `PUT` fires. A save that succeeds updates local state directly
 * (no re-fetch) since the response already echoes the stored `{symbol, sector}` pair back.
 */
import { useEffect, useMemo, useState } from "react";

import { describeError } from "@/api/client";
import { portfolioApi } from "@/api/portfolio";
import { FilterBar } from "@/components/tableSort";
import { useT } from "@/i18n";

import type { ToastPusher } from "./types";

type Phase = "loading" | "ready" | "error";

export default function SectorsPanel({ onToast }: { onToast: ToastPusher }) {
  const { t } = useT();
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [vocabulary, setVocabulary] = useState<string[]>([]);
  const [map, setMap] = useState<Record<string, string>>({});
  // Per-symbol draft value, only populated once a row's select differs from its stored sector --
  // an absent entry means "unchanged", which is what gates that row's own Save button.
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    portfolioApi
      .sectors(controller.signal)
      .then((result) => {
        setVocabulary(result.vocabulary);
        setMap(result.map);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setMessage(describeError(error, t("data.sectors.error.generic")));
        setPhase("error");
      });
    return () => controller.abort();
  }, [t]);

  const symbols = useMemo(() => Object.keys(map).sort(), [map]);
  const q = query.trim().toUpperCase();
  const filtered = q ? symbols.filter((symbol) => symbol.includes(q)) : symbols;

  async function save(symbol: string) {
    const next = drafts[symbol];
    if (next === undefined) return;
    setSaving(symbol);
    try {
      const result = await portfolioApi.setSector(symbol, next);
      setMap((prev) => ({ ...prev, [result.symbol]: result.sector }));
      setDrafts((prev) => {
        const { [symbol]: _removed, ...rest } = prev;
        return rest;
      });
      onToast({ message: t("data.sectors.savedToast", { symbol: result.symbol, sector: result.sector }), tone: "ok" });
    } catch (error: unknown) {
      onToast({ message: describeError(error, t("data.sectors.saveError")), tone: "bad" });
    } finally {
      setSaving(null);
    }
  }

  return (
    <section className="panel">
      <h2>{t("data.sectors.heading")}</h2>
      <p className="subtitle">{t("data.sectors.subtitle")}</p>

      {phase === "loading" && <div className="placeholder">{t("data.sectors.loading")}</div>}
      {phase === "error" && <div className="placeholder">{message}</div>}

      {phase === "ready" && (
        <>
          {symbols.length === 0 ? (
            <div className="placeholder">{t("data.sectors.empty")}</div>
          ) : (
            <>
              <FilterBar
                query={query}
                onQueryChange={setQuery}
                queryPlaceholder={t("data.sectors.filterPlaceholder")}
                shown={filtered.length}
                total={symbols.length}
              />
              <div className="table-wrap">
                <table className="data-table" data-testid="sectors-table">
                  <thead>
                    <tr>
                      <th scope="col">{t("common.symbol")}</th>
                      <th scope="col">{t("data.sectors.table.sector")}</th>
                      <th scope="col">{t("common.action")}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filtered.map((symbol) => {
                      const current = map[symbol] ?? "";
                      const draft = drafts[symbol] ?? current;
                      const dirty = drafts[symbol] !== undefined && drafts[symbol] !== current;
                      const options = vocabulary.includes(current) ? vocabulary : [current, ...vocabulary];
                      return (
                        <tr key={symbol}>
                          <td>{symbol}</td>
                          <td>
                            <select
                              aria-label={t("data.sectors.selectLabel", { symbol })}
                              value={draft}
                              disabled={saving === symbol}
                              onChange={(e) =>
                                setDrafts((prev) => ({ ...prev, [symbol]: e.target.value }))
                              }
                            >
                              {options.map((option) => (
                                <option key={option} value={option}>
                                  {option}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td>
                            <button
                              type="button"
                              disabled={!dirty || saving === symbol}
                              onClick={() => void save(symbol)}
                            >
                              {saving === symbol ? t("data.sectors.saving") : t("data.sectors.save")}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
