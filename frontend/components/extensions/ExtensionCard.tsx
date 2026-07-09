"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { ExtensionItemV2, ExtensionKindV2 } from "@/lib/api_v2";
import { cn } from "@/lib/utils";

import { ExtensionToggle } from "./ExtensionToggle";
import { EXTENSION_KIND_MANIFEST, extensionDescription, extensionVersion } from "./utils";

/** Props accepted by {@link ExtensionCard}. */
export interface ExtensionCardProps {
  /** The extension's kind (drives the manifest label and description shape). */
  kind: ExtensionKindV2;
  /** The catalog item to render. */
  item: ExtensionItemV2;
  /** Called when the card is clicked (opens the create/edit or detail dialog). */
  onOpen: (item: ExtensionItemV2) => void;
  /** Called with the desired next enabled state when the toggle is flipped. */
  onToggle: (item: ExtensionItemV2, nextEnabled: boolean) => void;
  /** True while an enable/disable mutation for this item is in flight. */
  toggling?: boolean;
}

/**
 * A single extension card: name, manifest/version, a kind-appropriate
 * description, an active/inactive status pill, and an enable/disable
 * toggle. Clicking anywhere on the card (outside the toggle) opens it for
 * editing or, for kinds without an edit endpoint, opens its read-only
 * detail dialog.
 *
 * @param props - See {@link ExtensionCardProps}.
 * @returns The rendered card.
 */
export function ExtensionCard({
  kind,
  item,
  onOpen,
  onToggle,
  toggling = false,
}: ExtensionCardProps): React.JSX.Element {
  const version = extensionVersion(item);
  const description = extensionDescription(kind, item);

  return (
    <Card
      data-testid="extension-card"
      className={cn(
        "relative border-ds-line bg-ds-bg-2 transition-colors hover:border-ds-line-strong"
      )}
    >
      {/*
       * The "open for edit/detail" action is a real button stretched over
       * the whole card (the "stretched button" pattern), rather than an
       * interactive role on the Card element itself. axe-core's
       * `nested-interactive` rule forbids a focusable control — here,
       * ExtensionToggle's own `role="switch"` button — from living inside
       * another element with interactive semantics, so the open action and
       * the toggle must be siblings, not ancestor and descendant.
       * `pointer-events-none` on the header/content layers lets clicks fall
       * through to this button everywhere except the badge/toggle region,
       * whose `pointer-events-auto` reclaims those pixels for itself.
       */}
      <button
        type="button"
        aria-label={`Open ${item.name}`}
        onClick={() => onOpen(item)}
        className="absolute inset-0 z-0 cursor-pointer rounded-[inherit] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent"
      />
      <CardHeader className="relative z-10 flex flex-row items-start justify-between gap-3 space-y-0 pb-2 pointer-events-none">
        <div className="min-w-0">
          <p className="truncate font-serif text-[15px] font-medium text-ds-fg">{item.name}</p>
          <p className="mt-0.5 truncate font-mono text-[11.5px] text-ds-fg-2">
            {EXTENSION_KIND_MANIFEST[kind]}
            {version ? ` · v${version}` : ""}
            {item.pluginId ? ` · ${item.pluginId}` : ""}
          </p>
        </div>
        <div className="pointer-events-auto flex shrink-0 items-center gap-2">
          <Badge variant={item.enabled ? "default" : "outline"}>
            {item.enabled ? "Active" : "Inactive"}
          </Badge>
          <ExtensionToggle
            checked={item.enabled}
            disabled={toggling}
            label={`${item.enabled ? "Disable" : "Enable"} ${item.name}`}
            onCheckedChange={(next) => onToggle(item, next)}
          />
        </div>
      </CardHeader>
      <CardContent className="relative z-10 pb-4 pt-0 pointer-events-none">
        <p className="line-clamp-2 text-[12.5px] leading-relaxed text-ds-fg-2">
          {description ?? "No manifest details reported."}
        </p>
      </CardContent>
    </Card>
  );
}
