"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ExtensionItemV2, ExtensionKindV2 } from "@/lib/api_v2";

import { EXTENSION_KIND_MANIFEST, extensionDescription, extensionVersion } from "./utils";

const codeBlockClass =
  "overflow-x-auto whitespace-pre-wrap rounded-ds-md border border-ds-line bg-ds-bg-3 p-4 font-mono text-[12px] text-ds-fg-2";

/** Props accepted by {@link ExtensionDetailDialog}. */
export interface ExtensionDetailDialogProps {
  /** Whether the dialog is open. */
  open: boolean;
  /** Called when the dialog should open or close. */
  onOpenChange: (open: boolean) => void;
  /** The extension's kind. */
  kind: ExtensionKindV2;
  /** The catalog item to display, or `null` while nothing is selected. */
  item: ExtensionItemV2 | null;
  /** Called with the desired next enabled state when the action button is used. */
  onToggle: (item: ExtensionItemV2, nextEnabled: boolean) => void;
  /** True while an enable/disable mutation for this item is in flight. */
  toggling?: boolean;
}

/**
 * Read-only manifest detail modal for extension kinds without a create/edit
 * endpoint (skill, plugin, mcp — see `backend/api/routers/extensions_v2.py`,
 * which exposes `enable`/`disable` actions for these kinds but no upsert
 * route). Surfaces every manifest fact the catalog reported for the item
 * plus its enable/disable action, so "clicking a card opens it" still does
 * something useful without fabricating a save flow with no backing endpoint.
 *
 * @param props - See {@link ExtensionDetailDialogProps}.
 * @returns The rendered dialog, or an empty dialog shell when `item` is `null`.
 */
export function ExtensionDetailDialog({
  open,
  onOpenChange,
  kind,
  item,
  onToggle,
  toggling = false,
}: ExtensionDetailDialogProps): React.JSX.Element {
  const version = item ? extensionVersion(item) : null;
  const description = item ? extensionDescription(kind, item) : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg bg-ds-bg-2 text-ds-fg">
        {item ? (
          <>
            <DialogHeader>
              <div className="flex items-center gap-2">
                <DialogTitle className="font-serif">{item.name}</DialogTitle>
                <Badge variant={item.enabled ? "default" : "outline"}>
                  {item.enabled ? "Active" : "Inactive"}
                </Badge>
              </div>
              <DialogDescription className="font-mono text-[12px] text-ds-fg-2">
                {EXTENSION_KIND_MANIFEST[kind]}
                {version ? ` · v${version}` : ""}
                {item.pluginId ? ` · ${item.pluginId}` : ""}
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col gap-3">
              <p className="text-sm text-ds-fg-2">
                {description ?? "No manifest details reported."}
              </p>
              <div>
                <p className="mb-1 text-sm font-medium text-ds-fg-2">Manifest detail</p>
                <pre className={codeBlockClass}>{JSON.stringify(item.detail, null, 2)}</pre>
              </div>
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Close
              </Button>
              <Button
                type="button"
                variant={item.enabled ? "destructive" : "default"}
                disabled={toggling}
                onClick={() => onToggle(item, !item.enabled)}
              >
                {item.enabled ? "Disable" : "Enable"}
              </Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
