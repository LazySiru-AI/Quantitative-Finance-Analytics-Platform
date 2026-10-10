/**
 * The evolution loop's rolling digest journal -- one Markdown digest per generation, newest first,
 * read from `GET /api/competition/loop/journal` (`evolutionApi.journal`). Mounted at the bottom of
 * `LoopPanel`, beside `GenerationsPanel`: where that panel is the field-wide *table* of what every
 * generation scored, this is the loop's own *prose* summary of what each generation taught and what
 * it left open -- the thing a person reads to follow the search without re-deriving it from run files.
 *
 * **Self-fetching, like `GenerationsPanel`.** It owns its own `FetchPhase` and fetches on mount rather
 * than taking data as props -- the journal exists and is worth reading whether or not the loop is
 * running right now, so it does not depend on the `LoopStatus` the parent happens to hold.
 *
 * **Markdown renders as plain pre-wrap text.** This codebase carries no Markdown renderer (checked
 * `frontend/package.json`), the same reason `LoopPanel`'s plan text and the desk pages' `output_md`
 * render inside a `<pre>` with `white-space: pre-wrap` rather than through a parser. A stray `<` in a
 * digest is shown as itself, never read as markup.
 *
 * **Never an error state for an empty journal.** The endpoint answers `{ total: 0, entries: [] }` for
 * a loop that has written no digest yet (a fresh checkout, or one not yet backfilled) -- rendered as a
 * designed "nothing yet" line, not the red error placeholder a real fetch failure gets.
 */
import { ApiRequestError } from "@/api/client";
import { evolutionApi, type JournalResponse } from "@/api/evolution";
import Fetched from "@/components/Fetched";
import { ScrollRegion } from "@/components/ScrollPanel";
import { useFetch } from "@/hooks/useFetch";
import { useT } from "@/i18n";

/** The first page is generous enough to read the recent search without a "load more": the journal is
 *  scanned newest-first and a reader rarely wants the 51st-oldest digest before the 1st. */
const PAGE_SIZE = 50;

export default function JournalPanel() {
  const { t, lang } = useT();
  const journal = useFetch<JournalResponse>(
    (signal) => evolutionApi.journal({ limit: PAGE_SIZE }, signal),
    // `lang` (not `t`) drives the re-fetch, matching the original effect's `[t]` dependency array --
    // `t`'s own identity already changes with `lang` (see `useT`'s docstring), and this hook reads its
    // `formatError` callback via a ref rather than as a dependency, so `lang` has to be named directly
    // to reproduce the original "toggling the language re-fetches the journal" behaviour.
    [lang],
    {
      formatError: (err) =>
        err instanceof ApiRequestError
          ? t("strategy.error.apiStatus", { status: err.status, message: err.message })
          : t("competition.journal.error"),
    },
  );

  return (
    <section className="panel">
      <h2 className="section-heading">{t("competition.journal.heading")}</h2>
      <p className="subtitle">{t("competition.journal.subtitle")}</p>

      <Fetched
        state={journal}
        loading={<div className="placeholder">{t("competition.journal.loading")}</div>}
        error={(message) => <div className="placeholder">{message}</div>}
        isEmpty={(res) => res.total === 0}
        empty={<div className="placeholder">{t("competition.journal.empty")}</div>}
      >
        {(res) => (
          <>
            {res.entries.length < res.total && (
              <p className="muted">
                {t("competition.journal.showingCount", { shown: res.entries.length, total: res.total })}
              </p>
            )}
            <ScrollRegion size="md" label={t("competition.journal.heading")}>
              <div className="comp-journal-list">
                {res.entries.map((entry) => (
                  <article className="comp-journal-entry" key={entry.generation}>
                    <h3 className="comp-journal-gen">
                      {t("competition.journal.generationLabel", { n: entry.generation })}
                    </h3>
                    <pre className="comp-journal-md">{entry.markdown}</pre>
                  </article>
                ))}
              </div>
            </ScrollRegion>
          </>
        )}
      </Fetched>
    </section>
  );
}
