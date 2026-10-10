/**
 * The first thing in the tab order: a link past the sidebar.
 *
 * The shell puts roughly twenty controls -- the language switch, the privacy switch, the symbol
 * search, three nav rails, a star beside every page -- between the top of the document and the page
 * itself. A keyboard or switch user arriving at `/tax` has to tab through all of them on every
 * navigation before reaching the first figure. WCAG 2.4.1 calls that a bypass failure, and it is one
 * link to fix.
 *
 * **Visually hidden until focused, not `display: none`.** A skip link that is never rendered is
 * never reachable; the standard trick is to park it off-canvas and bring it back on `:focus`, which
 * `.skip-link` in `styles.css` does. It stays in the DOM and in the tab order the whole time.
 *
 * **`href="#content"` and nothing else.** The target is `<main id="content" tabIndex={-1}>` in
 * `App.tsx`. The negative `tabindex` is what makes the jump actually move focus rather than only
 * scrolling -- without it several browsers move the scroll position and leave focus behind in the
 * sidebar, so the next Tab lands back on the second nav link and the link appears to do nothing.
 */
import { useT } from "@/i18n/useT";

export default function SkipLink() {
  const { t } = useT();
  return (
    <a className="skip-link" href="#content">
      {t("shell.skipToContent")}
    </a>
  );
}
