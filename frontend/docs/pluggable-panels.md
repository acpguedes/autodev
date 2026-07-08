# Pluggable panels (UI Extension Points) — E10-S4

The Web UI exposes a **UI Extension Point** that lets plugins contribute
panels mounted into registered slots. The contract is implemented in
`frontend/lib/panels/` and rendered by `frontend/components/panels/`.

## Contract (`HOST_CONTRACT_VERSION = 1.0.0`)

A panel is a `PanelManifest` plus a React component receiving `PanelProps`:

```ts
// lib/panels/registry.ts
type PanelManifest = {
  id: string;          // "<publisher>/<name>", e.g. "acme/coder-plus.panel"
  title: string;       // rendered in the panel chrome
  slot: PanelSlotId;   // "dashboard.main" | "run.detail.sidebar" | "session.footer"
  contract: string;    // SemVer range vs. HOST_CONTRACT_VERSION, e.g. "^1.0"
  description?: string;
  permissions?: { network?: { egress: string[] } };
};

type PanelProps = { manifest: PanelManifest; host: PanelHost };
```

This mirrors the `ui_panel` plugin asset in
`docs/architecture/v2_platform_reference.md` (§ Extension Points):

```yaml
- kind: ui_panel
  id: acme/coder-plus.panel
  contract: "^1.0"
  slot: "run.detail.sidebar"
  entry: "ui/panel.js"
```

## Registry and slots (T1)

- `createPanelRegistry()` / `panelRegistry` — validates manifests
  (`validatePanelManifest`), checks `contract` compatibility
  (`isContractCompatible`), rejects duplicates, and notifies subscribers.
- `<PanelSlotOutlet slot="…" />` mounts every **enabled** panel registered for
  a slot inside design-system `Card` chrome, so panels inherit theme tokens
  and a11y from E10-S1 (no hardcoded colors).
- `<PanelManager />` lists panels and lets the user enable/disable them;
  the choice is persisted in `localStorage` (`autodev.panels.disabled`).
- The `/panels` route shows the manager plus all registered slots.

## Sandbox and permissions (T2)

> **Scope note:** this is API-level permission gating, not a security
> boundary. Panels run in the same JS realm as the host page and can still
> reach `window`/globals directly; true isolation (iframe/worker sandbox)
> is deferred to the E1 plugin-host integration.

- Panels do not receive raw platform capabilities via the contract; they get a `PanelHost`
  created by `createPanelHost(manifest)` (`lib/panels/host.ts`).
- **Deny by default:** `host.fetch` throws `PanelPermissionError` unless the
  target origin matches the manifest's `permissions.network.egress`
  allowlist. `https://*.atlassian.net` style wildcards match subdomains;
  protocol and port must match; only http(s) is allowed.
- **Failure isolation:** every panel renders inside `PanelErrorBoundary`;
  a panel that throws is replaced by an inline alert and cannot break the
  page (see the "FaultyPanelIsIsolated" story).

## Discovery via Plugin Host (T3)

`installPluginPanels(registry, bundles)` (`lib/panels/discovery.ts`) installs
panels handed over by the Plugin Host (E1): one `PluginPanelBundle` per plugin
declaring a `ui-panel` extension point. It checks the plugin `hostApi` range,
validates each manifest, and returns a `PanelDiscoveryReport` — it never
throws, so a broken plugin cannot block others. Loading remote `entry`
modules is E1 integration work; until then bundles come from a local module
map (the built-in example uses `installExamplePanels()`).

## Example panel and tests (DoD)

- Example panel: `components/panels/ExampleRunSummaryPanel.tsx`
  (`autodev/example.run-summary`, slot `run.detail.sidebar`).
- Contract tests: `lib/panels/__tests__/registry.test.ts` (validation,
  version compatibility, enable/disable persistence, sandbox permissions,
  discovery isolation) — run with `npm test`.
- Stories with axe-core a11y checks: `components/panels/panels.stories.tsx`.
