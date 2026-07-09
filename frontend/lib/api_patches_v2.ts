// Typed client for the E16-S3 patch review lifecycle
// (`/v2/sessions/{session_id}/patches`), consumed by the E17-S3 Patches
// review screen. Kept in its own module (rather than growing `api_v2.ts`)
// to stay under the repository's 500-line-per-file limit, mirroring the
// backend's own split of `patches_review_v2_models.py` out of
// `patches_review_v2.py`.

import { requestJson } from "./api_ext";
import type { PageMetaV2 } from "./api_v2";

/** Lifecycle state of a reviewed patch. */
export type PatchStatusV2 = "proposed" | "applied" | "discarded";

/** One audit trail entry recorded against a patch (propose/override/apply/discard). */
export type PatchAuditEntryV2 = {
  actor: string;
  timestamp: string;
  action: string;
  result: string;
  message: string;
};

/** A changed file summary row, as returned by the changed-files list. */
export type ChangedFileV2 = {
  schemaVersion: string;
  patch_id: string;
  path: string;
  status: PatchStatusV2;
  added_lines: number;
  removed_lines: number;
};

/** Paginated collection of changed files for a session. */
export type ChangedFileListV2 = {
  schemaVersion: string;
  session_id: string;
  items: ChangedFileV2[];
  page: PageMetaV2;
};

/** Full detail for a single patch, including its unified diff and audit trail. */
export type PatchDetailV2 = {
  schemaVersion: string;
  patch_id: string;
  session_id: string;
  path: string;
  status: PatchStatusV2;
  original: string;
  updated: string;
  diff: string;
  added_lines: number;
  removed_lines: number;
  audit: PatchAuditEntryV2[];
};

/** Result of an apply attempt (dry-run or real). */
export type PatchApplyResultV2 = {
  schemaVersion: string;
  patch_id: string;
  session_id: string;
  path: string;
  applied: boolean;
  dry_run: boolean;
  message: string;
  audit: PatchAuditEntryV2;
};

/**
 * Propose a new patch for review by diffing `original` against `updated`.
 *
 * @param sessionId - Session the patch is scoped to.
 * @param path - Logical file path used as the diff label.
 * @param original - Original file content.
 * @param updated - New file content.
 * @returns The newly proposed patch, including its computed diff.
 * @throws Error when the request fails.
 */
export async function proposePatchV2(
  sessionId: string,
  path: string,
  original: string,
  updated: string
): Promise<PatchDetailV2> {
  return requestJson<PatchDetailV2>(
    `v2/sessions/${encodeURIComponent(sessionId)}/patches`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, original, updated }),
    }
  );
}

/**
 * List the changed files (proposed/applied/discarded patches) for a session.
 *
 * @param sessionId - Session identifier.
 * @param limit - Maximum number of files to return.
 * @param offset - Zero-based offset into the collection.
 * @returns The paginated changed-file list.
 * @throws Error when the request fails.
 */
export async function listChangedFilesV2(
  sessionId: string,
  limit = 100,
  offset = 0
): Promise<ChangedFileListV2> {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  return requestJson<ChangedFileListV2>(
    `v2/sessions/${encodeURIComponent(sessionId)}/patches?${params.toString()}`
  );
}

/**
 * Fetch a single patch's unified diff, content, and audit trail.
 *
 * @param sessionId - Session identifier.
 * @param patchId - Patch identifier.
 * @returns The patch detail.
 * @throws Error when the request fails (including 404 for an unknown patch).
 */
export async function getPatchDiffV2(sessionId: string, patchId: string): Promise<PatchDetailV2> {
  return requestJson<PatchDetailV2>(
    `v2/sessions/${encodeURIComponent(sessionId)}/patches/${encodeURIComponent(patchId)}`
  );
}

/**
 * Override a proposed patch's content, folding a manual edit back into the
 * patch and recomputing its unified diff.
 *
 * @param sessionId - Session identifier.
 * @param patchId - Patch identifier.
 * @param updated - The edited file content to diff against the original.
 * @returns The patch detail after the override, with its recomputed diff.
 * @throws Error when the request fails (404 unknown patch, 409 not proposed).
 */
export async function overridePatchContentV2(
  sessionId: string,
  patchId: string,
  updated: string
): Promise<PatchDetailV2> {
  return requestJson<PatchDetailV2>(
    `v2/sessions/${encodeURIComponent(sessionId)}/patches/${encodeURIComponent(patchId)}/content`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updated }),
    }
  );
}

/**
 * Apply a proposed patch, in dry-run mode by default.
 *
 * @param sessionId - Session identifier.
 * @param patchId - Patch identifier.
 * @param apply - `true` to write to disk; `false` (default) to dry-run.
 * @returns The apply result, including whether it was a dry run.
 * @throws Error when the request fails (404 unknown patch, 409 not proposed,
 *   400 when the target path escapes the workspace root).
 */
export async function applyPatchV2(
  sessionId: string,
  patchId: string,
  apply = false
): Promise<PatchApplyResultV2> {
  return requestJson<PatchApplyResultV2>(
    `v2/sessions/${encodeURIComponent(sessionId)}/patches/${encodeURIComponent(patchId)}/apply`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apply }),
    }
  );
}

/**
 * Discard a proposed patch, removing it from the review queue.
 *
 * @param sessionId - Session identifier.
 * @param patchId - Patch identifier.
 * @returns The patch detail after being marked discarded.
 * @throws Error when the request fails (404 unknown patch, 409 not proposed).
 */
export async function discardPatchV2(sessionId: string, patchId: string): Promise<PatchDetailV2> {
  return requestJson<PatchDetailV2>(
    `v2/sessions/${encodeURIComponent(sessionId)}/patches/${encodeURIComponent(patchId)}/discard`,
    { method: "POST" }
  );
}
