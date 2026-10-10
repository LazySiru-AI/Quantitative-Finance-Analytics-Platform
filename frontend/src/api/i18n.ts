/**
 * Typed client for the on-display Korean translation endpoint (i18n rollout, Phase 4).
 *
 * `POST /api/i18n/translate` takes a batch of English prose strings and answers a same-length,
 * same-order array of Korean translations -- `null` in a slot means "not translated" (the server
 * flag is off, the model call failed, or the result was rejected by the backend's own grounding
 * check on the way out), never an error. `translateProse` below mirrors that: any transport failure
 * (network down, non-2xx, malformed body) is swallowed and reported as an all-`null` result rather
 * than thrown, because a translation is best-effort dressing on a page that must render in English
 * regardless -- see `@/i18n/useProseTranslation`'s docstring for how a caller falls back on `null`.
 *
 * Same five-line `requestJson` shape as every other API module here (`@/api/personas`,
 * `@/api/tradingagents`, ...) -- duplicated rather than imported, per this codebase's "one copy per
 * module" convention (see `@/api/personas`'s own docstring for why).
 */
import { ApiRequestError } from "@/api/client";

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
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

interface TranslateResponse {
  results: (string | null)[];
}

/**
 * Translates a batch of English prose strings to Korean. `texts` and the returned array are always
 * the same length and order -- a `null` element means the server did not translate that particular
 * string, and the caller must fall back to the original English for that one, not for the whole
 * batch.
 *
 * Never throws: any failure (network, non-2xx, an unparsable body) resolves to an all-`null` array
 * the same length as `texts`, so a caller can always fall back without a `try`/`catch` of its own.
 */
export async function translateProse(texts: string[], locale: "ko"): Promise<(string | null)[]> {
  try {
    const response = await requestJson<TranslateResponse>("/api/i18n/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ locale, texts }),
    });
    return response.results;
  } catch {
    return texts.map(() => null);
  }
}
