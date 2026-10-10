/**
 * The regression guard the catalog itself cannot give: **find English still on screen in Korean.**
 *
 * `tsc` proves every key in the catalog has a Korean string. It says nothing about a string that
 * never made it into the catalog -- a heading left as a JSX literal, a `title=` attribute skipped
 * because it looked like markup, a label built by concatenation in a helper nobody thought to
 * check. Those are invisible to the type system and invisible to the existing test suite, which
 * runs in English and asserts on exactly that English.
 *
 * So this walks the rendered DOM in Korean and reports Latin words that survived. It is a lint, not
 * a proof: it will not catch a *mistranslation*, and it deliberately allows a long list of things
 * that are correctly Latin in Korean. What it does catch is the common case, which is a whole
 * sentence nobody extracted.
 *
 * Usage in a page test:
 *
 * ```ts
 * setLanguage("ko");
 * render(<Portfolio />);
 * expect(englishLeftovers(document.body)).toEqual([]);
 * ```
 */

/**
 * Latin runs that are correct in a Korean UI and must not be reported.
 *
 * Three kinds live here, and the distinction matters when adding to it:
 *
 * 1. **Identifiers** -- ticker symbols, indicator names, series ids, arm and card names. These are
 *    the same token in every language by definition; translating one would break the link back to
 *    the data.
 * 2. **Acronyms Korean writes in Latin** -- CAGR, GDP, CPI, ETF. A Korean trading desk writes these
 *    exactly this way, so seeing them is correct, not a leak.
 * 3. **Upstream provider names** -- FRED, SEC, EDGAR, and the official series titles they publish.
 *
 * What must NEVER be added here is an ordinary English word that happens to be hard to translate.
 * The moment this list starts absorbing vocabulary, the scan stops meaning anything.
 */
const ALLOWED = new Set(
  [
    // Acronyms and units written in Latin by Korean readers
    "CAGR", "GDP", "CPI", "PCE", "ETF", "REIT", "IPO", "USD", "KRW", "EPS", "PER", "PBR", "ROE",
    "RSI", "MACD", "SMA", "EMA", "ATR", "VWAP", "ADX", "OHLC", "NAV", "AUM", "PnL", "YTD", "TTM",
    "API", "CSV", "JSON", "URL", "UTC", "HTTP", "HTTPS", "ISO",
    // Providers, filings and venues
    "FRED", "SEC", "EDGAR", "NYSE", "NASDAQ", "CBOE", "OPEC", "FOMC", "FED",
    // Product names this app keeps in Latin on purpose
    "Claude", "Anthropic", "Sonnet", "Opus", "Haiku",
  ].map((word) => word.toUpperCase()),
);

/** A run of Latin letters four or more long. Shorter runs are almost all tickers and units. */
const LATIN_WORD = /[A-Za-z][A-Za-z'’-]{3,}/g;

export type ScanOptions = {
  /**
   * Extra allowed words for one page -- rule expressions, agent ids, a provider that only appears
   * there. Prefer this over widening the module-level list, so an exception stays visible next to
   * the page that needed it.
   */
  allow?: readonly string[];
  /**
   * Selectors whose subtree is skipped entirely. Use for regions that render backend-authored
   * English on purpose: a model-written narrative, a news headline from a feed, a raw error message.
   * Pass the same selector the component marks that region with.
   */
  skip?: readonly string[];
};

/**
 * Latin words still visible in the rendered tree, de-duplicated and in document order.
 *
 * Reads `textContent` of the surviving nodes plus the human-facing attributes -- `title`,
 * `aria-label`, `placeholder`, `alt`. An untranslated tooltip is exactly as broken as an
 * untranslated heading and exactly as easy to miss, since it never appears in `textContent`.
 */
export function englishLeftovers(root: HTMLElement, options: ScanOptions = {}): string[] {
  const extra = new Set((options.allow ?? []).map((word) => word.toUpperCase()));
  const skipped = new Set<Element>();
  for (const selector of options.skip ?? []) {
    for (const node of root.querySelectorAll(selector)) skipped.add(node);
  }

  const isSkipped = (node: Element | null): boolean => {
    for (let cursor = node; cursor; cursor = cursor.parentElement) {
      if (skipped.has(cursor)) return true;
    }
    return false;
  };

  const found = new Set<string>();
  const collect = (source: string | null): void => {
    if (!source) return;
    for (const match of source.matchAll(LATIN_WORD)) {
      const word = match[0];
      const upper = word.toUpperCase();
      if (ALLOWED.has(upper) || extra.has(upper)) continue;
      found.add(word);
    }
  };

  // `<script>`, `<style>` and the like carry no user-visible text; walking into them would report
  // every identifier in an inlined stylesheet.
  const IGNORED_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "CODE", "PRE"]);

  const walk = (node: Node): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      if (!isSkipped(node.parentElement)) collect(node.textContent);
      return;
    }
    if (!(node instanceof Element)) return;
    if (IGNORED_TAGS.has(node.tagName) || isSkipped(node)) return;
    for (const attribute of ["title", "aria-label", "placeholder", "alt"]) {
      collect(node.getAttribute(attribute));
    }
    for (const child of node.childNodes) walk(child);
  };

  walk(root);
  return [...found];
}
