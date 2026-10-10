/**
 * 404. Names the path that failed and offers the real destinations.
 *
 * Replaces a silent `<Navigate to="/portfolio">` catch-all. That redirect was indistinguishable from
 * a feature that had never been built: a UAT persona typed `/rules`, landed on the portfolio, and
 * concluded the rule engine did not exist — when it did, one nav entry away. A guessed URL is a
 * question, and answering it by quietly showing something else is the one response that cannot be
 * told apart from "no".
 *
 * The destinations come from `@/nav`, not from a list kept here. This file used to hold its own
 * copy, and it drifted exactly as a second copy does: it named nine pages when the app had thirteen,
 * so Competition, Paper Desk, Institutions and Wash Sales were unreachable from the page whose whole
 * job is telling someone where to go. Grouping them by section costs nothing and answers "what kind
 * of thing was I looking for" as well as "where is it".
 */

import { Link, useLocation } from "react-router-dom";

import { Trans, useT } from "@/i18n";
import { NAV, pageBlurbKey, pageLabelKey, sectionLabelKey } from "@/nav";

export default function NotFound() {
  const { pathname } = useLocation();
  const { t } = useT();

  return (
    <>
      <h1>{t("shell.notFound.title")}</h1>
      {/* `Trans` rather than two `t()` calls around the `<code>`: the path sits mid-sentence in
          English and takes a trailing particle in Korean, so the sentence has to stay one catalog
          entry that the translator can reorder around the slot. */}
      <p className="subtitle">
        <Trans k="shell.notFound.path" values={{ path: <code>{pathname}</code> }} />
      </p>

      <section className="panel">
        <h2>{t("shell.notFound.destinations")}</h2>
        {NAV.map((section) => (
          <div key={section.id} className="destination-group">
            <h3 className="destination-group-title">{t(sectionLabelKey(section.id))}</h3>
            <ul className="destination-list">
              {section.items.map((item) => (
                <li key={item.to}>
                  <Link to={item.to}>{t(pageLabelKey(item.to))}</Link>{" "}
                  <span className="muted">— {t(pageBlurbKey(item.to))}</span>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>
    </>
  );
}
