/**
 * Typed API client.
 *
 * Money crosses the wire as a decimal *string*, never a JSON number. JSON numbers are IEEE doubles,
 * so a cost basis of 1234567.89012345 would arrive subtly wrong. Nothing in the UI does arithmetic
 * on these; they are formatted for display and computed server-side in Decimal.
 */

/** A decimal value serialised as text. Format it, do not do arithmetic on it. */
export type DecimalString = string;

/**
 * Expands a `DecimalString` written in scientific notation (`"6.5385669523052923658747931E-7"`,
 * `"1E+3"`) into plain positional notation (`"0.00000065385669523052923658747931"`, `"1000"`).
 * A value with no exponent is returned unchanged, verbatim -- this is the identity function on
 * every plain decimal this API ever sends.
 *
 * **Why this exists.** Python's `Decimal` switches to scientific notation for small magnitudes,
 * and every hand-rolled `DecimalString` parser in this codebase (there used to be five: this
 * module now owns the one, `parseDecimalString`/`compareDecimalStrings` below and every display
 * helper in `@/api/institutions` build on it) split on `"."` and never looked for an `E`/`e`. Fed
 * a weight like `Moog Inc`'s in ARK's holdings, `6.5385669523052923658747931E-7`, that produced
 * `BigInt("65385669523052923658747931E-7000")` -- the exponent text pasted straight onto the
 * padded fraction -- which throws. Four of the twenty-two tracked funds have diffuse enough books
 * that some weight crosses the threshold where `Decimal` switches notation, so this was not a
 * one-fund bug.
 *
 * **String/`BigInt` digit-shifting only**, per this module's rule against round-tripping a
 * `DecimalString` through an IEEE double: no `Number`, no `parseFloat`, no `Math`. The exponent
 * itself (`parseInt` below) is the one exception -- it is always a small integer *count of digit
 * positions to shift*, never the decimal value being represented, so parsing it as a number loses
 * nothing the value itself carries.
 */
export function expandScientific(value: DecimalString): DecimalString {
  const trimmed = value.trim();
  const match = /^([+-]?)(\d*)(?:\.(\d*))?[eE]([+-]?\d+)$/.exec(trimmed);
  if (!match) return trimmed; // no exponent -- already plain, unchanged
  const [, sign = "", wholeDigits = "", fracDigits = "", expRaw = "0"] = match;
  const exp = parseInt(expRaw, 10);
  const digits = wholeDigits + fracDigits;
  // Where the decimal point falls within `digits`, counting from its start, once shifted by `exp`.
  const pointPos = wholeDigits.length + exp;

  let whole: string;
  let frac: string;
  if (digits === "") {
    whole = "0";
    frac = "";
  } else if (pointPos <= 0) {
    whole = "0";
    frac = "0".repeat(-pointPos) + digits;
  } else if (pointPos >= digits.length) {
    whole = digits + "0".repeat(pointPos - digits.length);
    frac = "";
  } else {
    whole = digits.slice(0, pointPos);
    frac = digits.slice(pointPos);
  }
  // Collapses a run of leading zeros the shift above can introduce (e.g. shifting "0" right by a
  // positive exponent pads it to "000000") down to the canonical single "0".
  whole = whole.replace(/^0+/, "") || "0";

  const isZero = whole === "0" && /^0*$/.test(frac);
  const body = frac ? `${whole}.${frac}` : whole;
  return sign === "-" && !isZero ? `-${body}` : body;
}

/** A `DecimalString` split into its sign and digit runs, scientific notation already expanded. */
export interface ParsedDecimalString {
  negative: boolean;
  wholeRaw: string;
  fracRaw: string;
}

/**
 * Splits a `DecimalString` into sign + whole/fractional digit strings, running it through
 * `expandScientific` first so every caller gets a plain-decimal split without having to special-
 * case an exponent itself. The shared building block behind `compareDecimalStrings` below and the
 * display helpers in `@/api/institutions` (`formatWeight`, `formatShares`, `formatSignedShares`).
 */
export function parseDecimalString(value: DecimalString): ParsedDecimalString {
  const expanded = expandScientific(value).trim();
  const negative = expanded.startsWith("-");
  const digits = expanded.replace(/^[+-]/, "");
  const [wholeRaw, fracRaw = ""] = digits.split(".");
  return { negative, wholeRaw: wholeRaw || "0", fracRaw };
}

/**
 * Ordering comparator for two decimal strings that never parses either into a float. Every
 * sortable money/shares/weight column in this app is the same `DecimalString` wire type, and this
 * app's rule against `parseFloat` on one (see this module's docstring above) covers ordering as
 * much as it covers display -- a real filing's share count or dollar value can exceed what an
 * IEEE double represents exactly. Pads both fractional parts to the same length and compares as
 * `BigInt` rather than converting either side to `Number`.
 *
 * The single shared implementation for what used to be four hand-copied versions of this function
 * across `frontend/src/pages/Institutions.tsx`, `frontend/src/components/HoldingsPieChart.tsx`,
 * and `frontend/src/components/RecentMoves.tsx` -- see `expandScientific`'s docstring for why that
 * duplication let the same bug reach four places at once.
 */
export function compareDecimalStrings(a: DecimalString, b: DecimalString): number {
  const pa = parseDecimalString(a);
  const pb = parseDecimalString(b);
  const fracLen = Math.max(pa.fracRaw.length, pb.fracRaw.length);
  const scale = (p: ParsedDecimalString): bigint => {
    const magnitude = BigInt(p.wholeRaw + p.fracRaw.padEnd(fracLen, "0"));
    return p.negative ? -magnitude : magnitude;
  };
  const sa = scale(pa);
  const sb = scale(pb);
  return sa < sb ? -1 : sa > sb ? 1 : 0;
}

/**
 * Rounds a single `DecimalString` to integer cents, ties away from zero (ROUND_HALF_UP) -- matching
 * the backend's `app.core.money.quantize_money`. Never truncates: a value with more precision than
 * cents (a cost basis like `4159.2533333333333`) is real precision the server sent, and dropping it
 * instead of rounding it is exactly the kind of silent one-cent drift `api/portfolio.ts`'s `sumMoney`
 * docstring documents a real, live defect from.
 *
 * The shared building block behind every pairwise money operation across the API layer --
 * `subtractMoney`/`compareMoneyDesc` (`@/api/portfolio`) and `addMoney` (`@/api/tax`) -- so the
 * rounding rule can only drift by editing this one function, not by three call sites each
 * re-implementing "round a decimal string to cents" slightly differently (two of them used to
 * truncate instead of round, which is exactly the kind of divergence this function exists to close).
 * `sumMoney`/`multiplyMoneyByQuantity` deliberately do NOT build on this: they round once, at full
 * precision, over the whole calculation, and converting each *input* to cents first would reintroduce
 * the per-term truncation bug `sumMoney`'s own docstring describes.
 */
export function decimalStringToCents(value: DecimalString): bigint {
  const { negative, wholeRaw, fracRaw } = parseDecimalString(value);
  const scale = Math.max(fracRaw.length, 2);
  const fracPadded = fracRaw.padEnd(scale, "0");
  const magnitude = BigInt(wholeRaw + fracPadded);
  const divisor = 10n ** BigInt(scale - 2);
  const quotient = magnitude / divisor;
  const remainder = magnitude % divisor;
  // Half-up on the unsigned magnitude, ties away from zero -- same rule as `quantize_money`, not
  // JavaScript's round-half-toward-positive-infinity.
  const cents = remainder * 2n >= divisor ? quotient + 1n : quotient;
  return negative ? -cents : cents;
}

/**
 * The inverse of `decimalStringToCents` -- a signed integer-cents `bigint` back to a `DecimalString`
 * (`-150n` -> `"-1.50"`). Shared final-formatting step for every money helper in this module's
 * callers, replacing what used to be five near-identical `whole`/`frac`/sign-string assemblies
 * (`sumMoney`, `subtractMoney`, `multiplyMoneyByQuantity`, `compareMoneyDesc`'s own copy, `addMoney`).
 */
export function centsToDecimalString(cents: bigint): DecimalString {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const whole = abs / 100n;
  const frac = (abs % 100n).toString().padStart(2, "0");
  return `${negative ? "-" : ""}${whole.toString()}.${frac}`;
}

export interface ApiError {
  status: number;
  message: string;
}

/**
 * The window event fired whenever the API answers 401. The auth provider listens for it and
 * re-checks the session, so one expired session flips the whole app back to the login screen
 * without a reload -- from *any* page, because every API module funnels a non-OK response through
 * `ApiRequestError` (below), which is the single place this fires.
 */
export const UNAUTHENTICATED_EVENT = "invdash:unauthenticated";

export class ApiRequestError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    // Dispatched from the constructor rather than at each call site because this is the one funnel
    // every module's fetch already passes through on failure -- see `UNAUTHENTICATED_EVENT`. The
    // provider's handler re-fetches `/api/auth/me` (which never 401s), so a 401 thrown by a failed
    // login while already anonymous is harmless: `me` simply reconfirms anonymous.
    if (status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent(UNAUTHENTICATED_EVENT));
    }
  }
}

/**
 * Turns a caught `unknown` into a string worth showing a user, with a caller-supplied fallback for
 * anything that isn't an `Error` with a real message.
 *
 * Was three private copies -- `ImportPanel.tsx`, `Activity.tsx`, `ReconcilePanel.tsx` -- differing
 * only in their fallback string. One of them (`ReconcilePanel.tsx`) also special-cased
 * `ApiRequestError` before falling through to the general `Error` branch below it; that branch
 * already returns `.message` for any `Error`, and `ApiRequestError extends Error`, so the extra
 * branch never did anything the one below it wouldn't have.
 *
 * Distinct from `describeError` in `@/hooks/useChartSeries.ts`, which the various `use*` data hooks
 * share (`useBacktest`, `useDecisionTable`, `useReport`, `useThesis`, `Ticker.tsx`) -- that one
 * exists for a different call shape and is left alone here.
 */
export function describeError(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, body || response.statusText);
  }
  return (await response.json()) as T;
}

// --- health -----------------------------------------------------------------

export interface LedgerStatus {
  path: string;
  exists: boolean;
  account?: number;
  instrument?: number;
  raw_import?: number;
  txn?: number;
  transactions?: number;
}

export interface BarsStatus {
  path: string;
  exists: boolean;
  symbols?: Record<string, number>;
}

export interface StoreStatus {
  ledger: LedgerStatus;
  bars: BarsStatus;
  // No `derived`. The endpoint reported one — never_built / current / stale — from a table that
  // recorded rebuilds of materialised lots and gains. Those tables were never built: every derived
  // figure is recomputed from the ledger per request, so "stale" is not a state this application
  // can be in, and the status read "never built" forever. Dropped in schema version 3.
}

export interface ProviderStatus {
  name: string;
  role: "bars" | "profile" | "fundamentals";
  intervals: string[];
  usable: boolean;
  /** Why it cannot serve. Present exactly when `usable` is false. */
  degraded_reason: string | null;
}

export interface ProviderHealth {
  providers: ProviderStatus[];
  bars: {
    registered: number;
    usable: number;
    /**
     * The single provider every price depends on, when there is only one that can serve. `null`
     * when there are two or more — or none, which is a different problem and not this field's job
     * to describe.
     */
    single_point_of_failure: string | null;
  };
}

export const api = {
  health: () => request<{ status: string }>("/api/health"),
  stores: (signal?: AbortSignal) =>
    request<StoreStatus>("/api/health/stores", { signal: signal ?? null }),
  /** Which upstreams are registered and how many can actually serve. Reported, not probed. */
  providers: (signal?: AbortSignal) =>
    request<ProviderHealth>("/api/health/providers", { signal: signal ?? null }),
};
