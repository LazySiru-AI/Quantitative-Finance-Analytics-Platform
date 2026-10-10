/**
 * "Which tracked filers hold this symbol?" — the reverse of the Institutions page's fund-first view.
 *
 * `uat/feedback/BACKLOG.md` named `institutions-no-symbol-search-or-reverse-link-from-ticker-portfolio`
 * twice as the largest unbuilt thing the persona runs surfaced. The backend half is
 * `GET /api/institutions/holders/{symbol}`; this is the surface that asks it.
 *
 * **It does not fetch on mount, and that is deliberate.** The endpoint walks every filer in the
 * catalog — one EDGAR request each behind a six-hour cache — so a cold call takes tens of seconds
 * and a warm one several. Firing that automatically on every ticker page load would make an
 * otherwise fast page feel broken, and would spend a reader's SEC rate budget on a question they
 * did not ask. So the panel sits inert until the reader presses the button.
 *
 * **Two fields decide what an empty result means, and both are rendered.** `checked`/`total` say
 * how many filers could actually be read: an empty list with `checked < total` is "none of the ones
 * I could reach", not "nobody". `symbol_resolved` says whether the symbol resolved to a CUSIP at
 * all — CUSIP is the only bridge from a 13F to a ticker and it comes from the user's own ledger, so
 * a symbol they have never traded cannot match however many filers hold it. Showing the list
 * without these would let both cases read as a confident "no holders".
 */

import { useCallback, useState } from "react";

import { ApiRequestError } from "@/api/client";

import {
  formatWeight,
  institutionsApi,
  type HoldersResponse,
} from "@/api/institutions";
import { formatMoney } from "@/api/tax";
import { ScrollRegion } from "@/components/ScrollPanel";
import { Trans, useT, type Translator } from "@/i18n";

type Phase = "idle" | "loading" | "loaded" | "error";

export default function InstitutionalHolders({ symbol }: { symbol: string }) {
  const { t } = useT();
  const [data, setData] = useState<HoldersResponse | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => {
    setPhase("loading");
    setMessage(null);
    institutionsApi
      .holders(symbol)
      .then((response) => {
        setData(response);
        setPhase("loaded");
      })
      .catch((error: unknown) => {
        // Not `error.message` verbatim. `ApiRequestError` carries the response body, which for a
        // FastAPI error is the raw JSON `{"detail":"Not Found"}` -- rendering that at a reader
        // shows them a fragment of the wire protocol and tells them nothing they can act on. Seen
        // for real: a stale dev server without this route put exactly that string in the panel.
        setMessage(describeFailure(t, error, symbol));
        setPhase("error");
      });
    // Deliberately `[symbol]` only, matching `Portfolio.tsx`'s own fetch effects: the catch branch
    // above translates in whichever language was active when the button was pressed.
  }, [symbol]);

  return (
    <section className="panel holders-panel">
      <div className="holders-head">
        <h2 className="holders-title">{t("market.holders.title")}</h2>
        {phase === "idle" && (
          <button type="button" className="holders-ask" onClick={load}>
            {t("market.holders.askButton", { symbol })}
          </button>
        )}
        {phase === "loaded" && data && (
          <span className="holders-coverage">
            {t("market.holders.coverage", { checked: data.checked, total: data.total })}
          </span>
        )}
      </div>

      {phase === "idle" && <p className="muted holders-cost">{t("market.holders.costNote")}</p>}

      {phase === "loading" && (
        <div className="placeholder">{t("market.holders.loadingFor", { symbol })}</div>
      )}

      {phase === "error" && <div className="callout callout-warn">{message}</div>}

      {phase === "loaded" && data && <HoldersResult data={data} />}
    </section>
  );
}

function HoldersResult({ data }: { data: HoldersResponse }) {
  const { t } = useT();
  const partial = data.checked < data.total;

  return (
    <>
      {!data.symbol_resolved && (
        <div className="callout callout-warn holders-unresolved">
          <strong>
            <Trans k="market.holders.unresolved.lead" values={{ symbol: data.symbol }} />
          </strong>{" "}
          <Trans k="market.holders.unresolved.body" values={{ symbol: data.symbol }} />
        </div>
      )}

      {partial && (
        <div className="callout callout-warn holders-partial">
          <strong>
            <Trans
              k="market.holders.partial.lead"
              values={{ unreadable: data.total - data.checked, total: data.total }}
            />
          </strong>{" "}
          <Trans k="market.holders.partial.body" values={{ checked: data.checked }} />
        </div>
      )}

      {data.holders.length === 0 ? (
        <div className="placeholder">
          {data.symbol_resolved && !partial
            ? t("market.holders.empty.resolved", { symbol: data.symbol })
            : t("market.holders.empty.unresolved")}
        </div>
      ) : (
        <ScrollRegion size="md" label={t("market.holders.title")}>
          <div className="table-wrap">
          <table className="data-table holders-table">
            <thead>
              <tr>
                <th>{t("market.holders.header.filer")}</th>
                <th>{t("market.holders.header.disclosedAs")}</th>
                <th className="num">{t("common.value")}</th>
                <th className="num">{t("common.weight")}</th>
                <th>{t("market.holders.header.period")}</th>
              </tr>
            </thead>
            <tbody>
              {data.holders.map((h) => (
                <tr key={`${h.key}-${h.cusip}`}>
                  <td className="holders-filer">{h.name}</td>
                  <td className="holders-issuer">
                    {h.issuer}
                    {h.value_units_rescaled && (
                      <span
                        className="badge holders-rescaled"
                        title={t("market.holders.rescaledBadge.title")}
                      >
                        {t("market.holders.rescaledBadge.label")}
                      </span>
                    )}
                  </td>
                  <td className="num">{formatMoney(h.value)}</td>
                  <td className="num">{formatWeight(h.weight)}</td>
                  <td className="holders-period">{h.period}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </ScrollRegion>
      )}

      {data.unchecked.length > 0 && (
        <details className="holders-unchecked">
          <summary>{t("market.holders.uncheckedSummary", { count: data.unchecked.length })}</summary>
          <ScrollRegion size="sm" label={t("market.holders.uncheckedSummary", { count: data.unchecked.length })}>
            <ul className="warning-list">
              {data.unchecked.map((u) => (
                <li key={u.key}>
                  <strong>{u.name}</strong> — {u.reason}{" "}
                  {/* `u.reason` is backend-written diagnostic text (an exception message), not UI
                      copy this shard owns -- it stays English regardless of `lang`, and the badge
                      says so plainly rather than leaving a Korean reader to wonder why. */}
                  <span className="badge" title={t("common.sourceEnglishTitle")}>
                    {t("common.sourceEnglish")}
                  </span>
                </li>
              ))}
            </ul>
          </ScrollRegion>
        </details>
      )}
    </>
  );
}


/**
 * Turn a failed lookup into something the reader can act on.
 *
 * **Split by status rather than one message for everything.** The first version had a single branch
 * reading "the service may be unavailable, or this build may be newer than the running backend" --
 * true for a 404 or a 502, and a misdiagnosis for a 422, which means the symbol the reader typed was
 * rejected before the service did any work at all. A UAT session caught it by typing a 31-character
 * ticker: three other panels on the same page named the real cause while this one blamed the
 * deployment.
 *
 * Never renders `error.message` verbatim. `ApiRequestError` carries the response body, so for a
 * FastAPI error that is the raw JSON `{"detail":"..."}` -- a fragment of the wire protocol shown to
 * someone who cannot act on it.
 */
function describeFailure(t: Translator, error: unknown, symbol: string): string {
  if (!(error instanceof ApiRequestError)) return t("market.holders.error.unreachable");
  if (error.status === 422) {
    return t("market.holders.error.invalidSymbol", { symbol });
  }
  if (error.status === 404) {
    return t("market.holders.error.missingEndpoint");
  }
  if (error.status >= 500) {
    return t("market.holders.error.serviceFailed");
  }
  return t("market.holders.error.otherStatus", { status: error.status });
}
