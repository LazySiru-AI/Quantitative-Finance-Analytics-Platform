/**
 * The list of `note_id` citations backing a persona claim.
 *
 * Every persona claim is validator-enforced to carry at least one citation, so this component
 * renders them plainly and always -- never behind a disclosure (unlike `InfoNote`'s long form,
 * which is exactly the kind of thing that must NOT happen to a citation). An empty array renders
 * nothing rather than an empty shell, since a claim with zero citations should never reach this
 * component in the first place and there is nothing useful to say about it here.
 *
 * When `onSelect` is supplied, each citation becomes a `<button>` so a caller can wire it to, say,
 * scrolling to the underlying note; without it, citations render as plain text for a context that
 * has nowhere to send the click.
 */
import { useT } from "@/i18n/useT";

import "./CitationList.css";

export interface CitationListProps {
  citations: readonly string[];
  /** Optional: turn a note_id into a click handler (e.g. scroll to the note). */
  onSelect?: ((noteId: string) => void) | undefined;
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

export function CitationList({ citations, onSelect, className, "data-testid": dataTestId }: CitationListProps) {
  const { t } = useT();

  if (citations.length === 0) return null;

  const classes = ["citation-list"];
  if (className) classes.push(className);

  return (
    <ul className={classes.join(" ")} aria-label={t("personaAtoms.citationList.ariaLabel")} data-testid={dataTestId}>
      {citations.map((noteId, i) => (
        <li key={`${noteId}-${i}`} className="citation-list-item">
          {onSelect ? (
            <button
              type="button"
              className="citation-list-button"
              aria-label={t("personaAtoms.citationList.selectAria", { noteId })}
              onClick={() => onSelect(noteId)}
            >
              {noteId}
            </button>
          ) : (
            <span className="citation-list-text">{noteId}</span>
          )}
        </li>
      ))}
    </ul>
  );
}

export default CitationList;
