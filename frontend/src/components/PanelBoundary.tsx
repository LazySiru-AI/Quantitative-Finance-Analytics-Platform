/**
 * Catches a render crash in one section of a page instead of losing the whole page to it.
 *
 * `ErrorBoundary` (this file's sibling) is the *only* net today: `App.tsx` wraps the entire
 * `<Routes>` tree in one, keyed on pathname. That stops a crash from taking down every page, but
 * not from taking down the page it happened on -- a bad value in one panel still blanks every other
 * panel above and below it on the same page, including figures that rendered fine. `ErrorBoundary`'s
 * own docstring names the concrete incident this was written against: an undefined money field in
 * one part of the Tax page took the whole page, navigation included, to a white screen.
 *
 * `PanelBoundary` is the finer-grained net: wrap one self-contained panel (a table, a chart, a
 * summary block -- anything that fetches or computes its own data) so a throw inside it degrades to
 * a small inline message in that panel's spot, and every sibling panel keeps rendering normally.
 *
 * Deliberately the same three decisions `ErrorBoundary` makes, at panel scale instead of page scale:
 *
 * - **It does not retry.** A render that threw once on the same props throws again.
 * - **It shows the error text.** Same audience as `ErrorBoundary` -- a local, single-user developer
 *   tool where the person looking at the screen is the person who can fix it.
 * - **It resets on `Try again`,** so a panel that crashed while its data was in a transient bad
 *   state does not need a full page reload to recover once new data arrives.
 *
 * Reuses `ErrorBoundary`'s own CSS (`.panel`, `.callout`, `.callout-danger`,
 * `.error-boundary-message`) rather than inventing a second visual language for the same kind of
 * failure -- a reader who has already learned what a callout-danger box means on this app should not
 * have to learn a second box shape that means the same thing.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

import { useT } from "@/i18n";

interface Props {
  children: ReactNode;
  /** Names the failing panel in the fallback and in the console log -- e.g. "Holdings" or
   *  "Wash sales by symbol". Optional: a panel with no obvious short name can omit it rather than
   *  force a vague one. */
  label?: string;
}

interface State {
  error: Error | null;
}

export default class PanelBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // Same rationale as `ErrorBoundary`: the component stack says *which* component threw, and
    // React only hands it to this method.
    console.error(
      `Panel failed to render${this.props.label ? ` (${this.props.label})` : ""}:`,
      error,
      info.componentStack,
    );
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <PanelBoundaryFallback
        error={error}
        label={this.props.label}
        onRetry={() => this.setState({ error: null })}
      />
    );
  }
}

/**
 * The fallback UI, split out as a function component purely so it can hold a hook -- same reason as
 * `ErrorBoundary`'s.
 *
 * The labelled and unlabelled headings are two separate catalog entries rather than one entry with
 * the label appended. English can glue ` — Holdings` onto the end of its sentence; Korean puts the
 * qualifier in front of the noun it modifies, so the two forms are genuinely different sentences and
 * a translator has to own both.
 */
function PanelBoundaryFallback({
  error,
  label,
  onRetry,
}: {
  error: Error;
  // `string | undefined`, not `label?: string`. Under this project's `exactOptionalPropertyTypes`
  // the two are different: the optional form forbids an explicit `undefined` value, but the caller
  // passes `this.props.label`, which is exactly `string | undefined`. Widening the type to admit
  // `undefined` is correct here -- an absent label and a `undefined` label mean the same thing to
  // this component, and both take the unlabelled heading.
  label: string | undefined;
  onRetry: () => void;
}) {
  const { t } = useT();

  return (
    <div className="panel callout callout-danger panel-boundary" role="alert">
      <strong>
        {label
          ? t("shell.panelBoundary.titleLabeled", { label })
          : t("shell.panelBoundary.title")}
      </strong>{" "}
      <span className="muted">{t("shell.panelBoundary.rest")}</span>
      {/* Never translated: the runtime's own message, wanted verbatim. */}
      <pre className="error-boundary-message">{error.message || String(error)}</pre>
      <button type="button" onClick={onRetry}>
        {t("shell.errorBoundary.retry")}
      </button>
    </div>
  );
}
