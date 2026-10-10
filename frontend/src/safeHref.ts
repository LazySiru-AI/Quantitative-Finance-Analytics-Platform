/**
 * Guard against a `javascript:`/`data:`/other-scheme URL reaching an `href` attribute.
 *
 * React escapes text content and attribute values, but it does not judge the *meaning* of a URL --
 * `<a href={url}>` happily renders `href="javascript:alert(1)"` verbatim, and a click executes it.
 * Every URL this app renders into an anchor originates from a feed this app does not control
 * (Yahoo/GDELT/Reddit-sourced news items, an influencer's own note, an owner-typed manual drop) --
 * see `MacroNewsPanel.tsx`, `NewsPanel.tsx`, `PersonaTimeline.tsx`, `BackfillTasks.tsx`. A poisoned
 * or malformed upstream record is not a hypothetical here.
 *
 * The backend is adding the identical scheme check on the models that carry these URLs (see
 * `docs/AGENT-DESK-CONTRACT.md` and the wire types in `@/api/news` / `@/api/personas` /
 * `@/api/backfill`) -- this module is the belt to that suspender: even if a server-side check is
 * ever skipped, bypassed, or lags a new caller, nothing reaches a real `href` unless it parses as an
 * absolute `http:`/`https:` URL.
 */

const SAFE_PROTOCOLS = new Set(["http:", "https:"]);

/** `true` when `url` is safe to place directly into an `href` attribute. */
export function isSafeHref(url: string | null | undefined): boolean {
  return safeHref(url) !== null;
}

/**
 * Return `url` (trimmed) when it parses as an absolute URL whose scheme is `http:` or `https:`;
 * otherwise `null`. Relative URLs, `javascript:`, `data:`, `vbscript:`, and unparseable strings all
 * return `null` -- callers render the label as plain text instead of an anchor in that case.
 */
export function safeHref(url: string | null | undefined): string | null {
  if (url === null || url === undefined) return null;
  const trimmed = url.trim();
  if (trimmed === "") return null;
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }
  return SAFE_PROTOCOLS.has(parsed.protocol.toLowerCase()) ? trimmed : null;
}
