export const SDK_CONTRACT_VERSION = "1.0.0" as const;

export type ExtensionPointKind =
  | "agent"
  | "skill"
  | "tool"
  | "reasoning"
  | "router"
  | "selector"
  | "evaluator"
  | "context_provider"
  | "retriever"
  | "validation_gate"
  | "ui_panel"
  | "event_handler";

export interface PluginExtensionPoint {
  kind: ExtensionPointKind;
  id: string;
  contract: string;
  entrypoint?: string;
  manifest?: string;
}

export interface PluginManifest {
  schemaVersion: string;
  id: string;
  version: string;
  hostApi: string;
  runtime: {
    loader: "in-process" | "subprocess" | "wasm";
    entrypoint: string;
    isolation?: string;
  };
  permissions?: Record<string, unknown>;
  extensionPoints: PluginExtensionPoint[];
}

export interface UiPanelRegistration {
  pluginId: string;
  extensionId: string;
  slot: string;
  entry: string;
}
