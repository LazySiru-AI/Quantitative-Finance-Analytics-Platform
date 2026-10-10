/**
 * A translated sentence with React nodes in its placeholder slots.
 *
 * For the sites that read `<strong>{n}</strong> bars evaluated` -- a sentence whose emphasis sits in
 * the middle of it. Splitting that into two `t()` calls around a `<strong>` puts the word order back
 * in the call site's hands, which is exactly what the catalog exists to take away from it: Korean
 * would need the number and the noun in the other order and has no way to ask for it.
 *
 * So the whole sentence stays one entry -- `"{count} bars evaluated"` / `"{count}개 봉 평가됨"` --
 * and this component substitutes a node instead of a string. The translator moves `{count}`
 * wherever Korean wants it and the `<strong>` follows.
 *
 * Prefer plain `t()`. Reach for this only when a slot genuinely has to carry markup.
 */
import { Fragment, type ReactNode } from "react";

import type { MessageKey } from "@/i18n/catalog";
import { template } from "@/i18n/t";
import { useLanguage } from "@/i18n/useT";

const PLACEHOLDER = /\{(\w+)\}/g;

export type TransProps = {
  /** The catalog key. Named `k` because `key` is React's own reserved prop. */
  k: MessageKey;
  /** Node (or plain value) per placeholder name. A name with no entry is left verbatim. */
  values?: Readonly<Record<string, ReactNode>>;
};

export default function Trans({ k, values }: TransProps): ReactNode {
  const lang = useLanguage();
  const source = template(lang, k);
  if (!values) return source;

  const parts: ReactNode[] = [];
  let cursor = 0;
  // `matchAll` rather than `replace`: the whole point is to emit nodes, and `replace` can only
  // build a string. The literal text between matches is pushed as-is.
  for (const match of source.matchAll(PLACEHOLDER)) {
    const at = match.index;
    const name = match[1];
    if (at === undefined || name === undefined) continue;
    if (at > cursor) parts.push(source.slice(cursor, at));
    const value = values[name];
    parts.push(value === undefined ? match[0] : value);
    cursor = at + match[0].length;
  }
  if (cursor < source.length) parts.push(source.slice(cursor));

  // Keys are positional and the array is rebuilt whole on every render, so index keys are correct
  // here -- there is no reordering or identity to preserve between renders.
  return parts.map((part, i) => <Fragment key={i}>{part}</Fragment>);
}
