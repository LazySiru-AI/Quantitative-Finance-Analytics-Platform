/**
 * The one place the app says something back after a mutation finishes.
 *
 * Before this, "it worked" was communicated by a page-specific inline banner, a status pill that
 * changed colour, or nothing at all -- three different answers to "did that just work?" depending
 * on which page you were on. `ToastRegion` is the single surface; `useToasts` is the queue behind
 * it. Neither is wired into the app shell here -- a later worker mounts one `<ToastRegion>` near the
 * root and everything else calls `push()`.
 *
 * **Why a monotonic counter and not `crypto.randomUUID()` or `Math.random()`.** Ids only need to be
 * unique within one tab's lifetime, never across reloads or machines, so a UUID is more entropy than
 * the problem needs. `Math.random().toString(36)` is the usual shortcut but is a birthday-paradox
 * collision waiting to happen under fast-firing toasts (two mutations resolving in the same tick),
 * and a collision here is not cosmetic -- `dismiss(id)` would remove or re-key the wrong toast. A
 * counter closed over module state can't collide and makes test assertions on toast order and
 * identity deterministic instead of probabilistic.
 *
 * **Why timers are keyed by id, not by array index.** The bug this specifically guards against: a
 * toast at index 2 auto-dismisses and is spliced out, a new toast is pushed and lands at index 2,
 * and the *old* toast's timer -- which captured "index 2" rather than an id -- fires and dismisses
 * the new arrival instead. Every timer here closes over the id it was set up for and is looked up
 * and cleared by that id, so a slot being reused by a different toast can't cross-wire it.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { useT } from "@/i18n/useT";

import "./Toast.css";

export type ToastTone = "ok" | "warn" | "bad" | "info";

export type ToastSpec = {
  id: string;
  message: string;
  tone?: ToastTone | undefined;
  /** When given, the toast offers an Undo button that calls this. */
  onUndo?: (() => void) | undefined;
  /** Auto-dismiss delay in ms. Default 6000. Pass 0 to require a manual dismiss. */
  durationMs?: number | undefined;
};

export interface ToastRegionProps {
  toasts: readonly ToastSpec[];
  onDismiss: (id: string) => void;
}

const DEFAULT_DURATION_MS = 6000;

/**
 * The fixed-corner stack. Purely presentational -- it owns no state of its own, including the
 * auto-dismiss timers, which live in `useToasts` so that a caller managing its own toast array
 * (rather than using the hook) still gets correct auto-dismiss behaviour for free by wiring
 * `onDismiss` to whatever removes an entry from that array.
 */
export function ToastRegion({ toasts, onDismiss }: ToastRegionProps) {
  const { t } = useT();
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());

  useEffect(() => {
    const active = timers.current;
    const liveIds = new Set(toasts.map((toast) => toast.id));

    // Clear timers for toasts that are no longer in the list -- a manual dismiss, or an ancestor
    // clearing the queue -- so a stale timer can never fire for an id that has already left.
    for (const [id, handle] of active) {
      if (!liveIds.has(id)) {
        clearTimeout(handle);
        active.delete(id);
      }
    }

    for (const toast of toasts) {
      if (active.has(toast.id)) continue;
      const duration = toast.durationMs ?? DEFAULT_DURATION_MS;
      if (duration <= 0) continue; // 0 means "manual dismiss only" -- no timer at all.
      const handle = setTimeout(() => {
        active.delete(toast.id);
        onDismiss(toast.id);
      }, duration);
      active.set(toast.id, handle);
    }

    return () => {
      // Unmount: every pending timer is cleared so none can fire after the region is gone.
      for (const handle of active.values()) clearTimeout(handle);
      active.clear();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed by the toast list's identity
    // (ids + durations), re-running per render would defeat the "only set a timer once" guard above.
  }, [toasts, onDismiss]);

  function handleDismiss(id: string) {
    const handle = timers.current.get(id);
    if (handle !== undefined) {
      clearTimeout(handle);
      timers.current.delete(id);
    }
    onDismiss(id);
  }

  function handleUndo(toast: ToastSpec) {
    toast.onUndo?.();
    handleDismiss(toast.id);
  }

  return (
    <div className="toast-region" role="region" aria-live="polite" aria-label={t("interaction.toast.region")}>
      {toasts.map((toast) => {
        const tone = toast.tone ?? "info";
        return (
          <div key={toast.id} className={`toast toast-${tone}`}>
            <p className="toast-message">{toast.message}</p>
            <div className="toast-actions">
              {toast.onUndo && (
                <button type="button" className="toast-undo" onClick={() => handleUndo(toast)}>
                  {t("interaction.toast.undo")}
                </button>
              )}
              <button
                type="button"
                className="toast-dismiss"
                aria-label={t("interaction.toast.dismiss")}
                onClick={() => handleDismiss(toast.id)}
              >
                ×
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// Module-level, not per-hook-instance: two independent `useToasts()` callers in the same tab (two
// panels, each with its own toast queue) must still never mint the same id.
let nextId = 0;

/** The queue behind `ToastRegion`. A caller can also build its own array and skip this entirely. */
export function useToasts() {
  const [toasts, setToasts] = useState<readonly ToastSpec[]>([]);

  const push = useCallback((spec: Omit<ToastSpec, "id">): string => {
    const id = `toast-${nextId++}`;
    setToasts((current) => [...current, { ...spec, id }]);
    return id;
  }, []);

  const dismiss = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  return { toasts, push, dismiss };
}
