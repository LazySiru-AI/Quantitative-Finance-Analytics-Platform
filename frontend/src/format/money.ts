/**
 * Single home for `formatMoney`/`formatMoneyOrDash`, the app's one rendering rule for a
 * `DecimalString` as `$X.XX`.
 *
 * This used to be three byte-identical local copies (`api/personas.ts`, `api/tax.ts`,
 * `api/tradingagents.ts`, each commented as a deliberate "one copy per module" duplicate) plus
 * `api/portfolio.ts`'s null-tolerant `formatMoneyOrDash` built on top of `api/tax.ts`'s copy. All
 * four call sites across the app import `formatMoney`/`formatMoneyOrDash` from their original
 * `@/api/*` module paths, so those modules now re-export from here rather than each defining their
 * own copy -- one behaviour, still reachable at every import path that already existed.
 */

import { parseDecimalString, type DecimalString } from "@/api/client";

/** Plain `$X.XX`, via the shared string/BigInt digit-shifting rule built on `parseDecimalString`
 * (`@/api/client`) -- never `Number`/`parseFloat` on a `DecimalString`. */
export function formatMoney(value: DecimalString): string {
  const { negative, wholeRaw, fracRaw } = parseDecimalString(value);
  const whole = wholeRaw.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = (fracRaw + "00").slice(0, 2);
  return `${negative && whole + frac !== "000" ? "-" : ""}$${whole}.${frac}`;
}

/**
 * Money that may be absent. Renders `—` on `null`, never `$0.00`.
 *
 * Exists because several fields are legitimately `null` -- an unpriced position's `market_value`,
 * a withheld account's `balance` -- and `formatMoney` takes a non-null `DecimalString`. Reaching
 * for `formatMoney(x ?? "0")` at a call site would satisfy the compiler and silently violate the
 * rule that `null` is not `0`: rendering it as zero understates the portfolio rather than merely
 * failing to help. Having the null-tolerant version here makes the honest option the convenient one.
 */
export function formatMoneyOrDash(value: DecimalString | null | undefined): string {
  // `== null`, not `=== null`: an absent figure arrives as `undefined` whenever the field is simply
  // not on the wire, which the declared types do not describe and cannot prevent -- a backend model
  // that stops serialising a field compiles clean on this side and produces `undefined` at runtime.
  // The strict check made *that* case throw inside `formatMoney`, taking down the whole page, which
  // is a worse answer than the em dash this function exists to render. Both absences are absences.
  return value == null ? "—" : formatMoney(value);
}
