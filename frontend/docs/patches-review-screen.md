# Patches review screen — E17-S3

Route: `frontend/app/patches/page.tsx` (`/patches`). Reproduces the
"Patches" view from the Execution Control Center redesign prototype
(`layout_prototype_brainstorm/`), wired exclusively to the E16-S3 `/v2`
patch-review endpoints (API-first, `docs/architecture/v2_platform_reference.md`
§2.13) via `frontend/lib/api_patches_v2.ts`.

## Layout

- **Session picker** (top-right, `Select` sourced from `listSessionsV2()`):
  chooses which session's changed files are reviewed.
- **Left file panel** (`components/patches/PatchFileList.tsx`): one row per
  changed file (`ChangedFileV2`), fed by `listChangedFilesV2(sessionId)`.
  Each row shows the file's directory, name, status dot
  (proposed/applied/discarded), and per-file `+added -removed` line counts;
  a summary line totals them across all files.
- **Right segmented viewer** (`components/patches/PatchSegmentedViewer.tsx`):
  a Diff/Edit Radix `Tabs` segmented control, fed by
  `getPatchDiffV2(sessionId, patchId)`:
  - **Diff** (`components/patches/PatchDiffView.tsx`): read-only unified diff
    with a line-number gutter and add/del row highlighting via the
    `ds-add-*`/`ds-del-*` design tokens (`lib/diff.ts::parseUnifiedDiff`).
  - **Edit**: a monospace `textarea` holding the file's resulting content,
    seeded from the patch detail's `updated` field (the exact resulting
    file content, provided by the API) and lifted to the page component so
    it survives switching back to Diff and forth (Radix unmounts inactive
    `TabsContent`, but the value itself is a controlled prop from the
    parent, not local state).
  - A **dry-run badge** ("Dry-run · nothing written yet") is shown whenever
    the patch's status is `proposed`, signaling that nothing has been
    written to disk yet.
- **Actions** (below the viewer): **Discard** (`discardPatchV2`, whose
  returned `PatchDetailV2` — now `status: "discarded"` — replaces the local
  patch state so the buttons disable immediately) and **Apply approved
  patch** (green-styled `Button`). Apply first calls
  `overridePatchContentV2` if the Edit segment's content differs from the
  patch's `updated` field (persisting the manual edit and recomputing the
  diff server-side), then `applyPatchV2(sessionId, patchId, apply: true)` to
  perform the real (non-dry-run) write. Both actions are disabled once a
  patch is no longer `proposed`.

## API contract (E16-S3)

| Client function | Endpoint |
| --- | --- |
| `listChangedFilesV2` | `GET /v2/sessions/{id}/patches` |
| `getPatchDiffV2` | `GET /v2/sessions/{id}/patches/{patchId}` |
| `overridePatchContentV2` | `PUT /v2/sessions/{id}/patches/{patchId}/content` |
| `applyPatchV2` | `POST /v2/sessions/{id}/patches/{patchId}/apply` (`{apply: boolean}`, dry-run by default) |
| `discardPatchV2` | `POST /v2/sessions/{id}/patches/{patchId}/discard` |

## Accessibility

- The file panel is a `nav[aria-label="Changed files"]` of focusable
  `button`s; the diff view uses `role="table"`/`role="row"`/`role="cell"`
  with a screen-reader-only "(added/removed/unchanged)" suffix per row so
  add/remove state isn't conveyed by color alone.
- The Edit segment's `textarea` has an associated (visually hidden) label.
- Segmented control triggers and file rows are reachable and operable via
  keyboard (native `button`/Radix `Tabs` semantics); no custom key handling
  was required.

## Testing

- Unit: `frontend/lib/__tests__/diff.test.ts` covers `parseUnifiedDiff` and
  `foldDiffToUpdatedContent`.
- Storybook: `components/patches/PatchFileList.stories.tsx`,
  `PatchDiffView.stories.tsx`, `PatchSegmentedViewer.stories.tsx` (empty,
  populated, selected, diff/edit mode, dry-run badge shown/hidden), run
  under the `storybook` Vitest project for automated a11y checks (axe).
- e2e: `frontend/e2e/patches-review.spec.ts` mocks the `/v2` endpoints above
  and exercises diff view -> switch to Edit (edit preserved across segment
  switches) -> Apply, and the Discard action.
