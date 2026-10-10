/**
 * Sortable-table-header and filter-bar primitives shared by every positions table on the Account
 * page (`frontend/src/pages/Portfolio.tsx`) -- by-instrument and by-account both need one sort
 * state and one filter bar, and two call sites do not each get to reinvent them.
 *
 * `useTableSort` / `SortHeader` are modelled directly on the private `SortHeader` and
 * `nextSortState` in `frontend/src/pages/Institutions.tsx` (~line 455 and ~line 819): a fresh
 * column starts at ITS OWN default direction (`defaultDirs[key]`); the already-active column just
 * flips. That file is left untouched -- this is an extraction, not a refactor of it.
 *
 * One deliberate improvement over the Institutions original: `aria-sort` on the `<th>`
 * (`"ascending" | "descending" | "none"`), which that version lacks and which is the only way a
 * screen reader learns the table's sort state at all. The arrow glyph stays `aria-hidden` and a
 * visually-hidden word inside the button restates the same state for a reader that announces
 * button contents rather than `<th>` attributes when tabbing through header buttons directly.
 */
import { useCallback, useState, type JSX } from "react";

import { useT } from "@/i18n/useT";

import "./tableSort.css";

export interface SortState<K extends string> {
  key: K;
  dir: "asc" | "desc";
}

/** Advances a column's sort state on click: a fresh key starts at that column's own default
 *  direction; the already-active column just flips. Exported so a caller that manages its own
 *  `useState` (rather than `useTableSort`) can still get identical toggle behaviour. */
export function nextSortState<K extends string>(
  prev: SortState<K>,
  key: K,
  defaultDirs: Record<K, "asc" | "desc">,
): SortState<K> {
  return prev.key === key
    ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
    : { key, dir: defaultDirs[key] };
}

export function useTableSort<K extends string>(
  initialKey: K,
  defaultDirs: Record<K, "asc" | "desc">,
): { sort: SortState<K>; toggle: (key: K) => void } {
  const [sort, setSort] = useState<SortState<K>>({
    key: initialKey,
    dir: defaultDirs[initialKey],
  });
  // Stable across renders as long as the caller's `defaultDirs` reference is (a module-level
  // record, same as `CHANGE_DEFAULT_DIR`/`HOLDING_DEFAULT_DIR` in Institutions.tsx) -- `setSort`
  // from `useState` is itself stable, so this never needs to change identity for that case.
  const toggle = useCallback(
    (key: K) => setSort((prev) => nextSortState(prev, key, defaultDirs)),
    [defaultDirs],
  );
  return { sort, toggle };
}

export interface SortHeaderProps<K extends string> {
  label: string;
  sortKey: K;
  sort: SortState<K>;
  onSort: (key: K) => void;
  numeric?: boolean;
  title?: string;
}

export function SortHeader<K extends string>({
  label,
  sortKey,
  sort,
  onSort,
  numeric,
  title,
}: SortHeaderProps<K>): JSX.Element {
  const { t } = useT();
  const active = sort.key === sortKey;
  const arrow = active ? (sort.dir === "asc" ? "▲" : "▼") : "";
  const ariaSort: "ascending" | "descending" | "none" = !active
    ? "none"
    : sort.dir === "asc"
      ? "ascending"
      : "descending";
  const stateWord = !active
    ? t("ui.table.sortNone")
    : sort.dir === "asc"
      ? t("ui.table.sortAscending")
      : t("ui.table.sortDescending");
  return (
    <th scope="col" className={numeric ? "num" : undefined} title={title} aria-sort={ariaSort}>
      <button type="button" className="tbl-sort-button" onClick={() => onSort(sortKey)}>
        {label}
        <span className="tbl-sort-arrow" aria-hidden="true">
          {arrow}
        </span>
        <span className="visually-hidden">{`, ${stateWord}`}</span>
      </button>
    </th>
  );
}

/**
 * Applies a per-column comparator record in the current direction and returns a NEW array --
 * `rows` is never mutated, because it is React state (or derived from it) at every call site.
 *
 * `Array.prototype.sort` is guaranteed stable since ES2019: two rows the comparator calls equal
 * (returns 0) keep their original relative order. That is what makes a re-sort idempotent on ties
 * rather than reshuffling them on every render.
 */
export function sortRows<T, K extends string>(
  rows: readonly T[],
  sort: SortState<K>,
  compare: Record<K, (a: T, b: T) => number>,
): T[] {
  const dir = sort.dir === "asc" ? 1 : -1;
  const cmp = compare[sort.key];
  return rows.slice().sort((a, b) => cmp(a, b) * dir);
}

export interface TableCaptionProps {
  /** The caption text -- already translated by the caller (`t(...)`, or a template built from it),
   *  since captions differ per table (which table, how many rows are actually rendered right now,
   *  and which account/scope/page the surrounding view is showing) in a way no shared component
   *  can compute on its own. */
  caption: string;
  /** Render the caption on screen instead of visually-hiding it. Defaults to `false`: a caption is
   *  an accessible name a screen reader needs (WCAG 1.3.1, finding EXP-15), not new copy a sighted
   *  reader asked for -- every table's heading already states the same fact in visible text one
   *  level up (`<h2>{t("...title")}</h2>`), so showing both would just repeat it. */
  captionVisible?: boolean;
}

/**
 * `<caption>` for a `<table>`, visually-hidden by default.
 *
 * This file exposes sort/filter primitives (`SortHeader`, `FilterBar`, `useTableSort`) that pages
 * compose around their OWN `<table>` markup -- it renders no `<table>` itself, so there is no single
 * place here to inject a caption automatically the way a table-owning component could. This is the
 * caption half of that same contract instead: one `<caption>` element every call site can drop in as
 * the table's first child, styled identically everywhere (`.visually-hidden` when hidden, matching
 * the pre-existing captions in `ByInstrumentView.tsx`'s account breakdown and `DecisionTable.tsx`;
 * `.muted` when shown, matching `BookStatistics.tsx`'s visible caption) instead of every page
 * reinventing the same `<caption className={...}>{...}</caption>` line and drifting on which class
 * name means "hidden" first.
 */
export function TableCaption({ caption, captionVisible = false }: TableCaptionProps): JSX.Element {
  return <caption className={captionVisible ? "muted" : "visually-hidden"}>{caption}</caption>;
}

export interface FilterBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  queryPlaceholder: string;
  choices?: { value: string; label: string }[];
  choice?: string;
  onChoiceChange?: (v: string) => void;
  choiceAllLabel?: string;
  /** Accessible name for the choice `<select>` (rendered as `aria-label`) -- the select otherwise
   *  has no text content of its own to announce (A11Y-05). Falls back to `choiceAllLabel` when
   *  omitted, since that is already the caller's own label for the same filter category. */
  choiceLabel?: string;
  shown: number;
  total: number;
}

/**
 * A controlled symbol-text-plus-optional-category filter row, shared by both positions tables on
 * the Account page. Fully controlled: this component owns no state of its own, so a caller that
 * also wants to filter the same rows some other way (e.g. an account picker) stays in sync for
 * free -- it is reading the same `query`/`choice` this renders.
 */
export function FilterBar({
  query,
  onQueryChange,
  queryPlaceholder,
  choices,
  choice,
  onChoiceChange,
  choiceAllLabel,
  choiceLabel,
  shown,
  total,
}: FilterBarProps): JSX.Element {
  const { t } = useT();

  const handleClear = useCallback(() => {
    onQueryChange("");
    if (onChoiceChange) onChoiceChange("");
  }, [onQueryChange, onChoiceChange]);

  return (
    <div className="filter-bar tbl-filter-bar">
      {/* No visible label for the search field -- the placeholder carries the visible hint, per
          this component's brief, so the accessible name is supplied directly via aria-label
          rather than a redundant visually-hidden <label>. */}
      <input
        type="search"
        value={query}
        placeholder={queryPlaceholder}
        aria-label={queryPlaceholder}
        onChange={(e) => onQueryChange(e.target.value)}
      />
      {choices !== undefined && choices.length > 0 && onChoiceChange !== undefined && (
        <select
          value={choice ?? ""}
          aria-label={choiceLabel ?? choiceAllLabel}
          onChange={(e) => onChoiceChange(e.target.value)}
        >
          {choiceAllLabel !== undefined && <option value="">{choiceAllLabel}</option>}
          {choices.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
      )}
      <button type="button" className="tbl-filter-clear" onClick={handleClear}>
        {t("ui.table.filterClear")}
      </button>
      <span className="tbl-filter-note muted">
        {t("ui.table.filterShowing", { shown, total })}
      </span>
    </div>
  );
}
