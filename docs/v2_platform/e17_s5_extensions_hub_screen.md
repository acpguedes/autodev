# E17-S5 — Extensions hub screen

Status: implemented. Scope: `frontend/app/extensions/`, `frontend/app/agents/`,
`frontend/app/skills/`, `frontend/components/extensions/`,
`frontend/components/shell/navModel.ts`, `frontend/components/shell/SidebarRail.tsx`.

## Why

Agents and Skills previously lived on two separate, near-identical
screens (`/agents`, `/skills`) with no shared visual treatment for
Plugins or MCP exposures, even though all four are the same conceptual
thing from an operator's point of view: an installable extension with a
manifest, a version, and an on/off switch. E17-S5 unifies all four kinds
into a single tabbed **Extensions hub** at `/extensions`
(ADR-012 §5), replacing the two standalone routes.

## Route and layout

- `frontend/app/extensions/page.tsx` — the hub screen. Publishes its
  contextual header via `useShellHeader` (E15 App Shell) and renders
  `ExtensionsHub` as routed content; the shell itself (sidebar rail,
  header, execution panel) is untouched.
- `frontend/app/agents/page.tsx` and `frontend/app/skills/page.tsx` —
  now permanent redirects to `/extensions` (`next/navigation`'s
  `redirect`), so any bookmarked or externally linked legacy URL still
  resolves.
- `frontend/components/shell/navModel.ts` — the sidebar's "Extensions"
  entry is enabled (previously `disabled: true`, no live badge) and now
  carries a `badge: "extensions"` count; `SHELL_LEGACY_NAV` no longer
  lists `agents`/`skills`, leaving only `/panels` under the temporary
  "Legacy" group. `SidebarRail.tsx`'s `useNavBadgeCounts()` sources that
  badge from `listExtensionsV2()`'s `page.total`.

## Screen structure

`ExtensionsHub` (`frontend/components/extensions/ExtensionsHub.tsx`) is a
single `"use client"` component:

- A `Tabs` bar (`components/ui/tabs`) with one trigger per
  `ExtensionKindV2` (`agent` / `skill` / `plugin` / `mcp`), each label
  suffixed with a live count derived from one unfiltered
  `GET /v2/extensions` catalog fetch (`useSWR`, cache key
  `extensions:catalog`) rather than four separate per-kind requests.
- Below the tab bar, a "Create agent" button appears only on the Agents
  tab (only agents have a create endpoint).
- Each tab's content is a responsive card grid
  (`ExtensionCard.tsx`), one card per catalog item: name, manifest
  filename + version + owning plugin id (`agent.yaml · v1.2.0`), a
  kind-appropriate one-line description derived from the item's
  `detail` bag (`utils.ts`'s `extensionDescription`), an Active/Inactive
  `Badge`, and an `ExtensionToggle` enable/disable switch
  (`role="switch"`, hand-rolled per `components/extensions/
  ExtensionToggle.tsx` — there is no `Switch` primitive in
  `components/ui/`).
- Clicking a card (outside the toggle) opens it for editing:
  - **Agents** open `AgentFormDialog` in edit mode
    (`GET /v2/extensions/agents/{id}` prefills the form).
  - **Skills / Plugins / MCP** open `ExtensionDetailDialog`, a read-only
    manifest viewer with the raw `detail` JSON and an enable/disable
    action, since the backend (`backend/api/routers/extensions_v2.py`)
    exposes enable/disable for every kind but an upsert route for agents
    only.
- Enable/disable is optimistic: `handleToggle` updates the SWR cache
  immediately, calls `enableExtensionV2`/`disableExtensionV2`, and rolls
  back on failure (`mutate(..., { optimisticData, rollbackOnError:
  true, revalidate: false })`), with a toast confirming the outcome
  either way.

## Create/edit agent form

`AgentFormDialog.tsx` is the one per-type create/install form required
by this story (agents are the only kind with a manifest rich enough to
justify one — system prompt, model, allowed tools). Fields: agent id
(read-only once editing), display name, model, version, comma-separated
allowed tools, and the system prompt (multiline). Submission builds an
`AgentUpsertPayloadV2` and calls `PUT /v2/extensions/agents/{agentId}`
(create and edit share the same endpoint and dialog; edit mode is
detected from a non-null `agentId` prop).

## API surface (E16-S4, all under `/v2/extensions`)

| Function (`lib/api_v2.ts`) | Endpoint |
| --- | --- |
| `listExtensionsV2(kind?, limit, offset)` | `GET /v2/extensions` |
| `enableExtensionV2(kind, id)` / `disableExtensionV2(kind, id)` | `POST /v2/extensions/{kind}/{id}/enable\|disable` |
| `getAgentExtensionV2(agentId, version?)` | `GET /v2/extensions/agents/{agentId}` |
| `upsertAgentExtensionV2(agentId, payload)` | `PUT /v2/extensions/agents/{agentId}` |

No screen in this story touches the State Store or any other backend
internal directly (API-first, §2.13).

## Testing

- **Storybook**: `ExtensionCard.stories.tsx` (agent/skill/plugin/mcp,
  enabled/disabled, toggling), `AgentFormDialog.stories.tsx` (create,
  edit-with-prefill), `ExtensionDetailDialog.stories.tsx`
  (skill/plugin/mcp, toggling), `ExtensionsHub.stories.tsx` (loaded,
  empty catalog, load error). Network-backed stories install a shared
  `window.fetch` stub (`storybook-mocks.ts`'s
  `installExtensionsFetchMock()`) synchronously inside a decorator's
  render body, so it is active before any child component's mount-time
  SWR fetch fires. `.storybook/preview.tsx` fails any story on an
  axe-core violation (`a11y: { test: "error" }`), covering the WCAG 2.2
  AA DoD requirement.
- **e2e**: `frontend/e2e/extensions-hub.spec.ts` intercepts every
  `/v2/extensions*` request with `page.route` against an in-memory
  fixture and drives: the `/agents`/`/skills` → `/extensions` redirects,
  tab counts and switching, toggling a card's switch, the full
  create-agent modal flow (fill, submit, catalog refresh), and opening a
  read-only detail dialog. `frontend/e2e/shell-navigation.spec.ts`'s
  route table was updated to assert `/extensions` (not `/agents`/
  `/skills`) renders inside the three-region shell with the correct
  active nav highlight.
