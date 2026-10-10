/**
 * What the pills on this page mean, in one line.
 *
 * Colour encoding only saves a reader effort once they know the code. A legend is how they learn it
 * without being told twice, and it is the second, non-colour channel for the whole system at once:
 * the words sit next to the swatch, so the page is still readable in greyscale.
 *
 * Deliberately not rendered when a page shows fewer than two tones -- a legend for one pill is noise
 * that costs the same vertical space this whole effort is trying to reclaim. Callers pass only the
 * tones actually present.
 */
import StatusPill, { type PillTone } from "@/components/StatusPill";

import "./StatusPill.css";

export interface PillLegendEntry {
  tone: PillTone;
  /** The pill's own words, exactly as they appear in the data above. */
  label: string;
  /** What it means, when the label alone is not self-evident. Two or three words. */
  gloss?: string | undefined;
}

export interface PillLegendProps {
  entries: readonly PillLegendEntry[];
  /** Accessible name, e.g. "Status legend". */
  label: string;
  className?: string | undefined;
  "data-testid"?: string | undefined;
}

export function PillLegend({ entries, label, className, "data-testid": dataTestId }: PillLegendProps) {
  if (entries.length < 2) return null;

  const classes = ["pill-legend"];
  if (className) classes.push(className);

  return (
    <div className={classes.join(" ")} role="list" aria-label={label} data-testid={dataTestId}>
      {entries.map((entry) => (
        <span className="pill-legend-item" role="listitem" key={`${entry.tone}-${entry.label}`}>
          <StatusPill tone={entry.tone} label={entry.label} />
          {entry.gloss && <span className="pill-legend-gloss">{entry.gloss}</span>}
        </span>
      ))}
    </div>
  );
}

export default PillLegend;
