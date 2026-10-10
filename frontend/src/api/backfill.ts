/**
 * Typed client for the Backfill Tasks endpoint (`/api/backfill/*`).
 *
 * The workflow this contract exists for happens partly outside this app: a task packet is copied
 * to the clipboard, pasted into an external agent (Gemini/ChatGPT) by hand, and the agent's reply is
 * pasted back in. Nothing here can verify what happened on the clipboard or in that external tool --
 * `validate`/`ingestResult` are the only checks this app can actually run, against whatever text the
 * owner pastes back.
 *
 * **`POST .../result`'s 422 carries `reasons` alongside `detail`; every other error response on this
 * contract carries only `detail`.** That is the one place a generic "throw `ApiRequestError` with the
 * unwrapped detail" helper is not enough, so `ingestResult` below parses its own error body and
 * throws `BackfillIngestError`, which is the one shape on this module a caller must check
 * `instanceof` for. Every other call goes through the plain `requestJson` helper.
 */
import { ApiRequestError } from "@/api/client";

// --- wire shapes ------------------------------------------------------------------------------------

/** One pending task packet. Mirrors the backend's own `TaskRef`. */
export interface TaskRef {
  persona_slug: string;
  persona_name: string;
  video_id: string;
  title: string;
  url: string;
  /** `"YYYY-MM-DD"`, or `""` when the source video carries no publish date. Never render `""` as a
   *  date -- show a dash instead. */
  published: string;
  filename: string;
}

/** A `TaskRef` plus the full packet text to copy into an external agent. */
export interface TaskDetail extends TaskRef {
  markdown: string;
}

export interface GenerateRequest {
  persona_slug?: string;
  limit?: number;
}

export interface GenerateResult {
  written: number;
  tasks: TaskRef[];
}

export interface ValidateRequest {
  video_id: string;
  text: string;
}

/** Always the 200 shape, even when `ok` is `false` -- a failed validation is not an HTTP error on
 *  this endpoint, only "no such task" (404) and "could not parse" (422) are. */
export interface ValidateResult {
  ok: boolean;
  reasons: string[];
  dropped_symbols: string[];
  ungrounded_numbers: string[];
}

export interface IngestResult {
  note_id: string;
  persona_slug: string;
  mention_count: number;
  summary_source: "external";
}

// --- requests ---------------------------------------------------------------------------------------

/**
 * FastAPI wraps an `HTTPException` message in `{"detail": ...}` -- unwrapping it here is what lets a
 * 404's specific reason ("no such task") reach the screen instead of a raw JSON blob. The same
 * pattern as `api/paperdesk.ts`'s own private `detailOf`; kept as its own copy per that module's
 * documented preference for one clear implementation per contract over a shared cross-module helper
 * for a three-line parse.
 */
function detailOf(body: string): string {
  if (!body) return "";
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string") return detail;
      return JSON.stringify(detail);
    }
  } catch {
    // Not JSON. The raw body is still the best thing to show.
  }
  return body;
}

/** `body.reasons` as a string array, or `[]` for anything else -- server data, treated as untrusted. */
function reasonsOf(body: string): string[] {
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "reasons" in parsed) {
      const reasons = (parsed as { reasons: unknown }).reasons;
      if (Array.isArray(reasons)) return reasons.filter((r): r is string => typeof r === "string");
    }
  } catch {
    // Not JSON, or no reasons array -- no reasons to show.
  }
  return [];
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { Accept: "application/json", ...init?.headers },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    throw new ApiRequestError(response.status, detailOf(body) || response.statusText);
  }
  return (await response.json()) as T;
}

/**
 * Thrown only by `ingestResult`, only on a 422 -- the one response on this contract whose error body
 * carries more than `detail`. Every other failure from this module is a plain `ApiRequestError`.
 */
export class BackfillIngestError extends ApiRequestError {
  readonly reasons: string[];

  constructor(status: number, message: string, reasons: string[]) {
    super(status, message);
    this.name = "BackfillIngestError";
    this.reasons = reasons;
  }
}

/**
 * Pastes the agent's reply back for one task. On a 422 ("reply could not be parsed" or failed
 * validation) the backend sends `reasons` alongside `detail` -- surfaced via `BackfillIngestError`
 * rather than folded into the generic `ApiRequestError` message, so the caller can render the list
 * rather than one run-on sentence. A 404 ("no such task") or 409 ("already ingested") carries only
 * `detail` and is a plain `ApiRequestError`.
 */
async function ingestResult(videoId: string, text: string): Promise<IngestResult> {
  const response = await fetch(`/api/backfill/tasks/${encodeURIComponent(videoId)}/result`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    const message = detailOf(body) || response.statusText;
    if (response.status === 422) {
      throw new BackfillIngestError(response.status, message, reasonsOf(body));
    }
    throw new ApiRequestError(response.status, message);
  }
  return (await response.json()) as IngestResult;
}

export const backfillApi = {
  listTasks: (signal?: AbortSignal) =>
    requestJson<{ tasks: TaskRef[] }>("/api/backfill/tasks", { signal: signal ?? null }),

  /** The full packet, including `markdown`, for one task. 404s (as an `ApiRequestError`) when the
   *  task no longer exists -- already ingested and removed elsewhere, or the file was deleted. */
  getTask: (videoId: string, signal?: AbortSignal) =>
    requestJson<TaskDetail>(`/api/backfill/tasks/${encodeURIComponent(videoId)}`, {
      signal: signal ?? null,
    }),

  /** Fetches fresh source videos and writes new task packets to disk. Slow -- it hits YouTube per
   *  persona -- so every caller must render a busy state rather than assume it returns promptly. */
  generate: (body: GenerateRequest) =>
    requestJson<GenerateResult>("/api/backfill/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  /** Checks a pasted reply without ingesting it. `ok: false` is a normal response, not a thrown
   *  error -- only "no such task" and "could not parse" reject. */
  validate: (body: ValidateRequest) =>
    requestJson<ValidateResult>("/api/backfill/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),

  ingestResult,
};
