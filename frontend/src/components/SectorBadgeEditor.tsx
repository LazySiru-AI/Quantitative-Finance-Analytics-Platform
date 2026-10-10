/**
 * A sector badge that turns into a `<select>` on double-click, so a miscategorised symbol
 * (`data/sectors.toml` maps by hand and misses things) can be fixed inline on the Account page
 * rather than requiring an edit to that file and a restart.
 *
 * The vocabulary is a prop, not a fetch this component makes itself: `Portfolio.tsx` loads
 * `portfolioApi.sectors()` once and passes the same array down to every row's editor, so opening
 * N rows costs one request, not N.
 *
 * Double-click, not single-click, to enter edit mode -- a sector badge is read constantly (every
 * row of every positions table renders one) and a single accidental click must never swap it into
 * an editable control the reader did not ask for. Enter or blur commits; Escape cancels and restores
 * the badge without saving. While a save is in flight the control disables itself and shows a
 * "Saving…" state; a rejected save (e.g. the server's 422 for a label outside the vocabulary)
 * surfaces an inline error rather than silently reverting or throwing.
 *
 * On a successful save this calls `onChanged()` rather than updating its own local `sector` --
 * `sector` is a prop derived from the page's `PortfolioReport`, and this component has no authority
 * to say what the "real" sector is now. `onChanged` is expected to trigger `usePortfolio()`'s
 * `refresh()`, which re-fetches the report and flows the new sector back down through props --
 * keeping every view (by instrument, by account, by tax treatment) and the by-instrument sector
 * filter in sync with the one write, rather than each row growing its own optimistic local state
 * that could disagree with a filter built from the stale `report.positions`.
 */
import { useEffect, useRef, useState } from "react";

import { portfolioApi } from "@/api/portfolio";
import { useT } from "@/i18n";

import "./SectorBadgeEditor.css";

export interface SectorBadgeEditorProps {
  symbol: string;
  sector: string;
  /** The full sector vocabulary, fetched once by the page and shared across every row's editor. */
  vocabulary: string[];
  /** Called after a successful save. Expected to trigger a report refresh -- see the module
   *  docstring for why this component never tries to reflect the new sector itself. */
  onChanged: () => void;
}

export default function SectorBadgeEditor({ symbol, sector, vocabulary, onChanged }: SectorBadgeEditorProps) {
  const { t } = useT();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(sector);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selectRef = useRef<HTMLSelectElement | null>(null);
  // Set right before an Escape-triggered cancel unmounts the <select>, and checked (then cleared) in
  // the blur handler -- without this, cancelling via Escape can still fire `onBlur` as focus leaves
  // the about-to-vanish control, which would silently re-save the very value Escape just discarded.
  const cancellingRef = useRef(false);

  useEffect(() => {
    if (editing) {
      setValue(sector);
      setError(null);
      selectRef.current?.focus();
    }
  }, [editing, sector]);

  function startEditing() {
    setEditing(true);
  }

  function cancel() {
    cancellingRef.current = true;
    setEditing(false);
    setError(null);
  }

  async function save() {
    if (value === sector) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await portfolioApi.setSector(symbol, value);
      setSaving(false);
      setEditing(false);
      onChanged();
    } catch {
      setSaving(false);
      setError(t("portfolio.sectorEditor.saveError"));
    }
  }

  if (!editing) {
    return (
      <span
        className="badge sector-badge"
        title={t("portfolio.sectorEditor.doubleClickHint")}
        onDoubleClick={startEditing}
      >
        {sector}
      </span>
    );
  }

  // The current sector might not itself be in the vocabulary (an older label, or one this page's
  // filter derives straight from `report.positions` rather than from the vocabulary endpoint) --
  // included as an extra option rather than silently dropped, so opening the editor never jumps the
  // selection to some other value before the reader has touched anything.
  const options = vocabulary.includes(sector) ? vocabulary : [sector, ...vocabulary];

  return (
    <span className="sector-badge-editing">
      <select
        ref={selectRef}
        className="sector-badge-select"
        aria-label={t("portfolio.sectorEditor.selectLabel", { symbol })}
        value={value}
        disabled={saving}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => {
          if (cancellingRef.current) {
            cancellingRef.current = false;
            return;
          }
          void save();
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void save();
          } else if (e.key === "Escape") {
            e.preventDefault();
            cancel();
          }
        }}
      >
        {options.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </select>
      {saving && <span className="sector-badge-saving">{t("portfolio.sectorEditor.saving")}</span>}
      {error && <span className="sector-badge-error">{error}</span>}
    </span>
  );
}
