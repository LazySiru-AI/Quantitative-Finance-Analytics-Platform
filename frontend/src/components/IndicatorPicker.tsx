/**
 * Overlay controls built from the server's indicator registry, not a hardcoded list.
 *
 * Each catalog entry carries its own `params` (kind, default, min, max), so the inputs rendered here
 * are exactly the parameters the backend will accept — there is no way for this UI to emit a spec
 * string the server would reject on shape.
 *
 * The unit of control is an **instance**, not an indicator. One indicator can be added several times
 * with different parameters, each in its own colour: `sma:20 / 50 / 100 / 200` is a moving-average
 * ribbon, and reading it depends entirely on telling the four lines apart. Toggling an indicator on
 * or off, the obvious design, cannot express that at all.
 *
 * An entry whose `intervals` excludes the current timeframe is shown disabled with the reason
 * (anchored VWAP on daily bars is the case that matters) — greying it out and saying why teaches
 * more than hiding it would.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ApiRequestError } from "@/api/client";
import { marketApi, type IndicatorCatalogEntry, type Interval, type ParamSpec } from "@/api/market";
import { OVERLAY_PALETTE, paletteColor, type Overlay } from "@/components/overlays";
import { useT } from "@/i18n";

interface IndicatorPickerProps {
  /** `null` disables nothing — used by the four-timeframe view, where each panel filters its own. */
  interval: Interval | null;
  onChange: (overlays: Overlay[]) => void;
}

type Phase = "loading" | "loaded" | "error";
type ParamValues = Record<string, string | number>;

interface Instance {
  id: string;
  entryName: string;
  values: ParamValues;
  color: string;
}

function buildSpec(entry: IndicatorCatalogEntry, values: ParamValues): string {
  if (entry.params.length === 0) return entry.name;
  const parts = entry.params.map((p) => String(values[p.name] ?? p.default));
  return `${entry.name}:${parts.join(",")}`;
}

function defaults(entry: IndicatorCatalogEntry): ParamValues {
  return Object.fromEntries(entry.params.map((p) => [p.name, p.default]));
}

export default function IndicatorPicker({ interval, onChange }: IndicatorPickerProps) {
  const { t } = useT();
  const [catalog, setCatalog] = useState<IndicatorCatalogEntry[] | null>(null);
  const [phase, setPhase] = useState<Phase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [instances, setInstances] = useState<Instance[]>([]);
  const [openSwatch, setOpenSwatch] = useState<string | null>(null);
  const nextId = useRef(0);
  const nextColor = useRef(0);

  useEffect(() => {
    let cancelled = false;
    marketApi
      .catalog()
      .then((entries) => {
        if (cancelled) return;
        setCatalog(entries);
        setPhase("loaded");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(
          e instanceof ApiRequestError
            ? t("ticker.error.apiStatus", { status: e.status, message: e.message })
            : t("ticker.error.unreachable"),
        );
        setPhase("error");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Holding the latest `onChange` in a ref keeps it out of the emit effect's dependency array, so a
  // parent passing a fresh closure each render cannot cause a loop.
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const overlays = useMemo<Overlay[]>(() => {
    if (!catalog) return [];
    const byName = new Map(catalog.map((e) => [e.name, e]));
    return instances.flatMap((inst) => {
      const entry = byName.get(inst.entryName);
      if (!entry) return [];
      return [
        {
          id: inst.id,
          name: entry.name,
          title: entry.title,
          spec: buildSpec(entry, inst.values),
          color: inst.color,
          intervals: entry.intervals,
        },
      ];
    });
  }, [catalog, instances]);

  const overlayKey = overlays.map((o) => `${o.spec}@${o.color}`).join("|");
  useEffect(() => {
    onChangeRef.current(overlays);
    // `overlayKey` is the stable dependency; `overlays` is rebuilt on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [overlayKey]);

  const add = useCallback((entry: IndicatorCatalogEntry) => {
    const id = `ov-${nextId.current++}`;
    const color = paletteColor(nextColor.current++);
    setInstances((prev) => [...prev, { id, entryName: entry.name, values: defaults(entry), color }]);
  }, []);

  const remove = useCallback((id: string) => {
    setInstances((prev) => prev.filter((i) => i.id !== id));
  }, []);

  const setParam = useCallback((id: string, paramName: string, value: string | number) => {
    setInstances((prev) =>
      prev.map((i) => (i.id === id ? { ...i, values: { ...i.values, [paramName]: value } } : i)),
    );
  }, []);

  const setColor = useCallback((id: string, color: string) => {
    setInstances((prev) => prev.map((i) => (i.id === id ? { ...i, color } : i)));
    setOpenSwatch(null);
  }, []);

  if (phase === "loading") return <div className="placeholder">{t("ticker.indicator.loadingCatalog")}</div>;
  if (phase === "error" || !catalog) return <div className="placeholder">{error}</div>;

  return (
    <div className="indicator-picker">
      <div className="indicator-grid">
        {catalog.map((entry) => {
          const unavailable =
            interval !== null && entry.intervals !== null && !entry.intervals.includes(interval);
          const mine = instances.filter((i) => i.entryName === entry.name);
          return (
            <div
              key={entry.name}
              className={`indicator-toggle${mine.length > 0 ? " active" : ""}${unavailable ? " disabled" : ""}`}
            >
              <div className="indicator-toggle-row">
                <span className="indicator-name">{entry.title}</span>
                <button
                  type="button"
                  className="indicator-add"
                  disabled={unavailable}
                  onClick={() => add(entry)}
                  title={t("ticker.indicator.addLine", { title: entry.title })}
                  aria-label={t("ticker.indicator.addLine", { title: entry.title })}
                >
                  +
                </button>
              </div>
              <span className="indicator-reason">
                {unavailable
                  ? `${t("ticker.indicator.unavailable", {
                      interval: interval ?? "",
                      list: entry.intervals?.join(` ${t("ticker.indicator.orJoiner")} `) ?? "",
                    })} ${entry.description}`
                  : entry.description}
              </span>

              {mine.length > 0 && (
                <div className="instance-list">
                  {mine.map((inst) => (
                    <div className="instance" key={inst.id}>
                      <div className="instance-row">
                        <button
                          type="button"
                          className="swatch"
                          style={{ background: inst.color }}
                          onClick={() => setOpenSwatch(openSwatch === inst.id ? null : inst.id)}
                          aria-label={t("ticker.indicator.changeColor", {
                            title: entry.title,
                            spec: buildSpec(entry, inst.values),
                          })}
                          aria-expanded={openSwatch === inst.id}
                        />
                        <span className="instance-spec">{buildSpec(entry, inst.values)}</span>
                        <button
                          type="button"
                          className="instance-remove"
                          onClick={() => remove(inst.id)}
                          aria-label={t("ticker.indicator.remove", { spec: buildSpec(entry, inst.values) })}
                        >
                          ×
                        </button>
                      </div>

                      {openSwatch === inst.id && (
                        <div className="swatch-row" role="group" aria-label={t("ticker.indicator.lineColorGroup")}>
                          {OVERLAY_PALETTE.map((c) => (
                            <button
                              key={c}
                              type="button"
                              className={`swatch small${c === inst.color ? " chosen" : ""}`}
                              style={{ background: c }}
                              onClick={() => setColor(inst.id, c)}
                              aria-label={t("ticker.indicator.useColor", { color: c })}
                            />
                          ))}
                        </div>
                      )}

                      {entry.params.length > 0 && (
                        <div className="indicator-params">
                          {entry.params.map((param) => (
                            <ParamInput
                              key={param.name}
                              param={param}
                              value={inst.values[param.name] ?? param.default}
                              onChange={(value) => setParam(inst.id, param.name, value)}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function ParamInput({
  param,
  value,
  onChange,
}: {
  param: ParamSpec;
  value: string | number;
  onChange: (value: string | number) => void;
}) {
  const { t } = useT();
  if (param.kind === "choice") {
    return (
      <label className="indicator-param">
        {param.label}
        <select value={String(value)} onChange={(e) => onChange(e.target.value)}>
          {param.choices.map((choice) => (
            <option key={choice} value={choice}>
              {choice}
            </option>
          ))}
        </select>
      </label>
    );
  }

  // A fixed token or an arbitrary date. Rendered as a token select plus a date field rather than
  // one free-text box, because "session or YYYY-MM-DD" as a typing instruction invites exactly the
  // malformed values the backend then rejects.
  if (param.kind === "choice_or_date") {
    const isToken = param.choices.includes(String(value));
    return (
      <label className="indicator-param">
        {param.label}
        <span className="param-split">
          <select
            value={isToken ? String(value) : "__date"}
            onChange={(e) => onChange(e.target.value === "__date" ? todayIso() : e.target.value)}
          >
            {param.choices.map((choice) => (
              <option key={choice} value={choice}>
                {choice}
              </option>
            ))}
            <option value="__date">{t("ticker.indicator.fromDate")}</option>
          </select>
          {!isToken && (
            <input type="date" value={String(value)} onChange={(e) => onChange(e.target.value)} />
          )}
        </span>
      </label>
    );
  }

  if (param.kind === "date") {
    return (
      <label className="indicator-param">
        {param.label}
        <input type="date" value={String(value)} onChange={(e) => onChange(e.target.value)} />
      </label>
    );
  }

  return (
    <label className="indicator-param">
      {param.label}
      <input
        type="number"
        value={value}
        min={param.minimum ?? undefined}
        max={param.maximum ?? undefined}
        step={param.kind === "int" ? 1 : "any"}
        onChange={(e) =>
          onChange(param.kind === "int" ? Math.round(Number(e.target.value)) : Number(e.target.value))
        }
      />
    </label>
  );
}
