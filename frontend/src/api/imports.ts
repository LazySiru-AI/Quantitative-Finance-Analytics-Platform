/**
 * Typed client for the import endpoint — the only write in this API.
 *
 * Mirrors `backend/app/api/imports.py`. Three properties of that endpoint shape everything the UI
 * built on it has to do:
 *
 * **There is no upload.** Files are read from the server's data directory where they already sit.
 * `filenames` names files the server has already told us about, via `preview()`; the UI never
 * constructs one. A file picker here would be a lie about what the request does.
 *
 * **A conflict is not a warning.** It means a stored row disagreed with the incoming one and was
 * *left alone* — the broker restated a figure, or an adapter changed its mind about one. The
 * stored value may already have been reported on a tax form. `ok` is false when any file
 * conflicted, and the UI must render conflicts as loudly as outright failures rather than folding
 * them into a success count.
 *
 * **"Undeclared" is the common first-run state, and it is not an error in the file.** It means the
 * account manifest does not say which account the file belongs to — the one input no validation can
 * supply, because a Robinhood taxable export and a Robinhood Roth export are structurally
 * identical. The fix is a line in `data/accounts.toml`, so the UI says that rather than reporting a
 * failure the user cannot act on.
 */

import { ApiRequestError } from "@/api/client";
import { t } from "@/i18n";

/** What became of one file. Mirrors `app.ingest.service.FileStatus`. */
export type FileStatus =
  | "imported"
  | "unchanged"
  | "conflicts"
  | "undeclared"
  | "no_adapter"
  | "ambiguous"
  | "failed";

export interface ManifestStatus {
  path: string;
  present: boolean;
  entries: number;
  /** Why it cannot be used. A malformed manifest and an absent one need different fixes. */
  error: string | null;
}

/** How much of an incoming file an existing account already holds. */
export interface AccountMatch {
  account_id: string;
  account_label: string;
  tax_treatment: string;
  /** Transactions this account already has, matched by id. Exact, not inferred. */
  overlapping: number;
  incoming_total: number;
  account_total: number;
  /** Rows this file would add if attached here. */
  new_rows: number;
  /**
   * Share of *this account* the file contains — the ratio that discriminates. A file holding an
   * account whole is a re-export of it; sharing a few of a larger account's same-price trades is
   * ordinary coincidence between two accounts at one broker.
   */
  account_coverage: number;
  /** Share of the *file* already stored. Reads low precisely when a match is certain. */
  overlap_fraction: number;
  /** Context only, never evidence: two accounts holding the same ETFs share every symbol. */
  shared_symbols: number;
  incoming_symbols: number;
}

export interface PlannedFile {
  filename: string;
  status: FileStatus;
  adapter: string | null;
  broker: string | null;
  account_id: string | null;
  account_label: string | null;
  tax_treatment: string | null;
  row_count: number | null;
  /** Rows that would become transactions — the denominator the match evidence is measured over. */
  usable_row_count: number | null;
  /** This exact content is already in the ledger under this account. */
  already_imported: boolean;
  detail: string | null;
  /** Same-broker accounts, best first. Present even when the file is undeclared — that is when it
   *  matters, because "is this an account I already have" is the question being asked. */
  matches: AccountMatch[];
  /** The one account this file shares transactions with, when one stands out. Preselect it; never
   *  submit it without the user having seen it. */
  suggested_account_id: string | null;
  /** Rows shared with several accounts and none standing out. Do not preselect. */
  match_is_ambiguous: boolean;
}

/** What to do with one file: attach it to an account, or open a new one. Exactly one. */
export type FileDecision =
  | { filename: string; account_id: string }
  | { filename: string; new_account: NewAccount };

export interface NewAccount {
  /** Lower-case slug: it is written into a TOML file and used as a key. */
  account_id: string;
  label: string;
  /**
   * Required, with no default, here as everywhere else: it decides whether an account's gains are
   * reported at all and whether a repurchase inside it destroys a loss permanently under
   * Rev. Rul. 2008-5. The UI must ask rather than pick.
   */
  tax_treatment: "taxable" | "roth_ira" | "traditional_ira";
  account_type?: "cash" | "margin" | "retirement";
}

export interface ImportPlan {
  data_dir: string;
  manifest: ManifestStatus;
  files: PlannedFile[];
  importable: number;
}

export interface FileImport {
  filename: string;
  status: FileStatus;
  adapter: string | null;
  broker: string | null;
  account_id: string | null;
  import_id: string | null;
  row_count: number;
  /** Rows that became transactions. The gap from `row_count` is `skipped`, broken down by reason. */
  usable_row_count: number;
  inserted: number;
  duplicates: number;
  /** Stored rows that disagreed with the incoming ones. **Nothing was overwritten.** */
  conflicts: string[];
  skipped: Record<string, number>;
  instruments: number;
  detail: string | null;
  warnings: string[];
}

export interface ImportRunResult {
  files: FileImport[];
  inserted: number;
  /** True only when every file landed and nothing conflicted. */
  ok: boolean;
  ledger_fingerprint: string;
  txn_count: number;
  started_at: string;
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
 * FastAPI wraps an `HTTPException` message in `{"detail": ...}`. Unwrapping it here means the
 * actionable sentence the endpoint wrote — "no account manifest at …, run `python -m app.ingest
 * --init`" — reaches the screen instead of a JSON blob the user has to read around.
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

export const importApi = {
  /** What a run would do. Writes nothing, and works with no manifest. */
  preview: (signal?: AbortSignal) =>
    requestJson<ImportPlan>("/api/import", { signal: signal ?? null }),

  /**
   * Import. `filenames` must come from `preview()`; omit it to import everything found.
   *
   * `decisions` assign an account to files the manifest does not yet declare. Each is written into
   * `data/accounts.toml` before the import runs, so a choice made here is the choice the CLI sees
   * next time — the manifest stays the single record of file-to-account attribution.
   */
  run: (filenames?: string[], decisions?: FileDecision[], signal?: AbortSignal) =>
    requestJson<ImportRunResult>("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...(filenames ? { filenames } : {}),
        ...(decisions && decisions.length > 0 ? { decisions } : {}),
      }),
      signal: signal ?? null,
    }),
};

/**
 * How a status should read on screen.
 *
 * `conflicts` is deliberately grouped with the failures rather than with the successes it
 * numerically resembles — see the module note above.
 *
 * Exhaustive at compile time, forgiving at runtime -- see `exitReasonLabel` in `@/api/paperdesk` for
 * the concrete failure this pattern exists to prevent: a `default` that *throws* over a server-
 * supplied value takes the whole page down the moment the backend sends a status this build has not
 * been updated for, rather than rendering one merely-unstyled badge. An unrecognised status degrades
 * to `"neutral"` here -- the least alarming reading available, since this function cannot know
 * whether an unforeseen status is good or bad news.
 */
export function statusTone(status: FileStatus): "good" | "neutral" | "bad" {
  switch (status) {
    case "imported":
      return "good";
    case "unchanged":
      return "neutral";
    case "conflicts":
    case "undeclared":
    case "no_adapter":
    case "ambiguous":
    case "failed":
      return "bad";
    default: {
      const _exhaustive: never = status;
      void _exhaustive;
      return "neutral";
    }
  }
}

/** Exhaustive at compile time, forgiving at runtime -- see `statusTone` above. An unrecognised status
 *  renders its own raw wire value rather than throwing. */
export function statusLabel(status: FileStatus): string {
  switch (status) {
    case "imported":
      return t("activity.import.status.imported");
    case "unchanged":
      return t("activity.import.status.unchanged");
    case "conflicts":
      return t("activity.import.status.conflicts");
    case "undeclared":
      return t("activity.import.status.undeclared");
    case "no_adapter":
      return t("activity.import.status.noAdapter");
    case "ambiguous":
      return t("activity.import.status.ambiguous");
    case "failed":
      return t("activity.import.status.failed");
    default: {
      const _exhaustive: never = status;
      void _exhaustive;
      return String(status);
    }
  }
}
