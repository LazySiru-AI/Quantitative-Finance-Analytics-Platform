/**
 * The app's fixed glyph vocabulary (`docs/APP-UX-REFACTOR-ANALYSIS.md` §3.3): a small set of
 * Unicode geometric symbols, never emoji. Emoji render with different glyph sets per OS, cannot be
 * coloured by the tone tokens, and fight the monospace-uppercase label voice the rest of the app
 * uses (see `StatusPill.tsx`'s own docstring for the same reasoning applied to tone pills).
 *
 * Every glyph is **decorative by default**: `aria-hidden`, no role, because in every documented use
 * (§3.3's table) the glyph rides alongside text or a pill that already carries the meaning for
 * assistive tech -- a direction arrow next to a signed number, a live-dot next to a `StatusPill`, a
 * warn triangle next to a caveat sentence. Passing `label` switches it to `role="img"` +
 * `aria-label={label}` for the rare case where the glyph is the *only* signal (no adjacent text).
 * `label` is caller-supplied, not looked up here -- this component has no i18n dependency by design,
 * so it never needs its own catalog shard.
 */
import "./Glyph.css";

/**
 * One name per row of the §3.3 vocabulary table. `up`/`down` are the direction arrows for money and
 * percent deltas; `live`/`partial`/`idle` are the three section-rail/desk-card states; `pass`/`fail`
 * are gate results and reconcile matches; `warn` is the existing warn-pill glyph; `age` marks an
 * "as of" readout; `seat` marks a card seated on Paper Desk. `info`/`star` are listed in §3.3 as
 * "(existing) unchanged" -- included here so every glyph in the vocabulary has one home, not because
 * their call sites are migrating in this change.
 */
export type GlyphName =
  | "up"
  | "down"
  | "live"
  | "partial"
  | "idle"
  | "warn"
  | "pass"
  | "fail"
  | "age"
  | "seat"
  | "info"
  | "star";

const GLYPHS: Record<GlyphName, string> = {
  up: "▲", // ▲
  down: "▼", // ▼
  live: "●", // ●
  partial: "◐", // ◐
  idle: "○", // ○
  warn: "⚠", // ⚠
  pass: "✓", // ✓
  fail: "✗", // ✗
  age: "⏱", // ⏱
  seat: "◆", // ◆
  info: "ⓘ", // ⓘ
  star: "★", // ★
};

export interface GlyphProps {
  /** Which glyph from the fixed vocabulary to render. */
  name: GlyphName;
  /**
   * Present only when the glyph is the sole carrier of meaning (no adjacent text or pill already
   * says it). Supplying this switches the glyph from decorative (`aria-hidden`) to
   * `role="img"` + `aria-label={label}`. Caller-supplied so this component stays i18n-free.
   */
  label?: string | undefined;
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

export function Glyph({ name, label, className, "data-testid": dataTestId }: GlyphProps) {
  const classes = ["glyph", `glyph-${name}`];
  if (className) classes.push(className);

  if (label) {
    return (
      <span className={classes.join(" ")} role="img" aria-label={label} data-testid={dataTestId}>
        {GLYPHS[name]}
      </span>
    );
  }

  return (
    <span className={classes.join(" ")} aria-hidden="true" data-testid={dataTestId}>
      {GLYPHS[name]}
    </span>
  );
}

export default Glyph;
