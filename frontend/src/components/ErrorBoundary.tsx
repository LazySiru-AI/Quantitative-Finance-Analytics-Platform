/**
 * Catches a render crash in one page instead of blanking the whole application.
 *
 * Added after a concrete incident rather than as a precaution. While wiring the 1099-B panel, a
 * backend field that had not yet been redeployed arrived as `undefined`, `formatMoney` called
 * `.trim()` on it, and React unmounted the entire tree — the Tax page, the navigation, everything —
 * to a white screen with the reason visible only in the console. The figures further up that page
 * were fine and the user could no longer see any of them.
 *
 * Nothing in the type system would have stopped it. `tsc` checks the *declared* shape of a
 * response; what arrives is whatever the running server sends, and the two can disagree across a
 * deploy, a version skew, or a field that was quietly renamed.
 *
 * Deliberately not clever:
 *
 * - **It does not retry.** A render that threw once on the same props throws again, and a
 *   spinner-then-crash loop is harder to diagnose than a stopped page. `Try again` resets the
 *   boundary only because navigating away and back should not require a browser reload.
 * - **It shows the error text.** This is a local, single-user developer tool; the person looking at
 *   the screen is the person who can fix it, and hiding the message behind "something went wrong"
 *   would cost them the one useful fact.
 * - **It is per route, not per app.** The navigation stays usable, so a crash in one page does not
 *   strand the user on it.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

import { useT } from "@/i18n";

interface Props {
  children: ReactNode;
  /** Names the failing area in the message — the route, usually. */
  area?: string;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Kept: the component stack says *which* component threw, which the message alone does not, and
    // React only hands it to this method.
    console.error(`Render failed${this.props.area ? ` in ${this.props.area}` : ""}:`, error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return <ErrorBoundaryFallback error={error} onRetry={() => this.setState({ error: null })} />;
  }
}

/**
 * The fallback UI, split out as a function component purely so it can hold a hook.
 *
 * A class cannot call `useT()`, and the alternative -- reading the language store directly in
 * `render()` -- would produce text that is correct on first paint and then stale forever, because
 * nothing would subscribe the class to the store. Every language change would leave the crash
 * message in the previous language while the rest of the app switched.
 */
function ErrorBoundaryFallback({ error, onRetry }: { error: Error; onRetry: () => void }) {
  const { t } = useT();

  return (
    <div className="panel callout callout-danger error-boundary">
      <h2>{t("shell.errorBoundary.title")}</h2>
      <p>{t("shell.errorBoundary.body")}</p>
      {/* The thrown message itself is never translated: it is the runtime's own text, and it is the
          one fact the person reading this screen needs verbatim to search for or paste. */}
      <pre className="error-boundary-message">{error.message || String(error)}</pre>
      <p className="muted">{t("shell.errorBoundary.hint")}</p>
      <button type="button" onClick={onRetry}>
        {t("shell.errorBoundary.retry")}
      </button>
    </div>
  );
}
