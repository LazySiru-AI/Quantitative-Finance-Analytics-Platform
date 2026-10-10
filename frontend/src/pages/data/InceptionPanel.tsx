/**
 * Paper Desk inception: set or clear the override date every book trades from.
 *
 * Reuses `paperdeskApi` (`@/api/paperdesk`) unchanged -- `state()` to read the current/default/
 * earliest/latest dates, `setInception`/`resetInception` to mutate. `PaperDesk.tsx` already has an
 * inline inception control built on the same client; this panel is a second, operator-page surface
 * over the same endpoint, not a new one, per the Data page's contract (`PUT`/`DELETE
 * /api/paperdesk/inception`).
 *
 * A `ConfirmSheet` gates the mutating action, same as `PaperDesk.tsx`'s own control: this
 * recomputes every book on every purpose, and that is not something a stray click should trigger.
 */
import { useEffect, useState } from "react";

import { describeError } from "@/api/client";
import { paperdeskApi, type PaperDeskState } from "@/api/paperdesk";
import { ConfirmSheet } from "@/components/ConfirmSheet";
import { useT } from "@/i18n";

import type { ToastPusher } from "./types";

type Phase = "loading" | "ready" | "error";
type PendingAction = { kind: "set"; date: string } | { kind: "reset" } | null;

export default function InceptionPanel({ onToast }: { onToast: ToastPusher }) {
  const { t } = useT();
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState<string | null>(null);
  const [state, setState] = useState<PaperDeskState | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<PendingAction>(null);

  useEffect(() => {
    const controller = new AbortController();
    paperdeskApi
      .state(controller.signal)
      .then((next) => {
        setState(next);
        setDraft(next.inception);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setMessage(describeError(error, t("data.inception.error.generic")));
        setPhase("error");
      });
    return () => controller.abort();
  }, [t]);

  function confirmSet() {
    if (!draft) return;
    setPending({ kind: "set", date: draft });
  }

  function confirmReset() {
    setPending({ kind: "reset" });
  }

  function cancelPending() {
    setPending(null);
  }

  async function runPending() {
    if (!pending) return;
    setBusy(true);
    try {
      const next =
        pending.kind === "set"
          ? await paperdeskApi.setInception(pending.date)
          : await paperdeskApi.resetInception();
      setState(next);
      setDraft(next.inception);
      setMessage(null);
      onToast({
        message:
          pending.kind === "set"
            ? t("data.inception.appliedToast", { date: next.inception })
            : t("data.inception.resetToast", { date: next.inception }),
        tone: "ok",
      });
    } catch (error: unknown) {
      onToast({ message: describeError(error, t("data.inception.error.generic")), tone: "bad" });
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  return (
    <section className="panel">
      <h2>{t("data.inception.heading")}</h2>
      <p className="subtitle">{t("data.inception.subtitle")}</p>

      {phase === "loading" && <div className="placeholder">{t("data.inception.loading")}</div>}
      {phase === "error" && <div className="placeholder">{message}</div>}

      {phase === "ready" && state && (
        <>
          <div className="status-grid">
            <div className="stat">
              <span className="label">{t("data.inception.current")}</span>
              <span className="value">{state.inception}</span>
              {state.inception_is_custom && (
                <span className="badge warn">{t("data.inception.customBadge")}</span>
              )}
            </div>
            <div className="stat">
              <span className="label">{t("data.inception.default")}</span>
              <span className="value">{state.inception_default}</span>
            </div>
          </div>

          <label className="year-select">
            {t("data.inception.dateLabel")}
            <input
              type="date"
              value={draft}
              min={state.earliest_inception}
              max={state.latest_inception}
              disabled={busy}
              onChange={(e) => setDraft(e.target.value)}
            />
          </label>
          <p className="muted">
            {t("data.inception.range", { earliest: state.earliest_inception, latest: state.latest_inception })}
          </p>

          <div className="import-actions">
            <button type="button" className="symbol-submit" disabled={busy || !draft} onClick={confirmSet}>
              {busy ? t("data.inception.applying") : t("data.inception.apply")}
            </button>
            <button
              type="button"
              disabled={busy || !state.inception_is_custom}
              onClick={confirmReset}
            >
              {t("data.inception.reset")}
            </button>
          </div>
          {message && <div className="callout callout-danger panel">{message}</div>}
        </>
      )}

      <ConfirmSheet
        open={pending !== null}
        question={
          pending?.kind === "set"
            ? t("data.inception.confirmQuestion", { date: pending.date })
            : t("data.inception.resetConfirmQuestion", { date: state?.inception_default ?? "" })
        }
        preview={pending?.kind === "set" ? t("data.inception.confirmPreview") : undefined}
        busy={busy}
        tone="warn"
        onConfirm={() => void runPending()}
        onCancel={cancelPending}
      />
    </section>
  );
}
