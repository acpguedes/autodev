"use client";

import * as React from "react";
import useSWR from "swr";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  disableExtensionV2,
  enableExtensionV2,
  listExtensionsV2,
  type ExtensionCatalogV2,
  type ExtensionItemV2,
  type ExtensionKindV2,
} from "@/lib/api_v2";
import { toast } from "@/lib/use-toast";

import { AgentFormDialog } from "./AgentFormDialog";
import { ExtensionCard } from "./ExtensionCard";
import { ExtensionDetailDialog } from "./ExtensionDetailDialog";
import { EXTENSION_KIND_LABELS } from "./utils";

/** The four extension kinds shown as tabs, in display order. */
const KINDS: readonly ExtensionKindV2[] = ["agent", "skill", "plugin", "mcp"];
/**
 * The largest single-page limit the backend accepts
 * (`backend/api/v2_common.py`'s `MAX_PAGE_LIMIT`), so the four tab counts
 * and card lists can be derived from one unfiltered `/v2/extensions` fetch
 * instead of four separate per-kind requests. A value above this cap makes
 * every catalog fetch fail request validation (422).
 */
const CATALOG_LIMIT = 200;
const CATALOG_KEY = "extensions:catalog";

/** Fetches the full, unfiltered unified extensions catalog. */
async function fetchCatalog(): Promise<ExtensionCatalogV2> {
  return listExtensionsV2(undefined, CATALOG_LIMIT, 0);
}

/**
 * Extensions hub screen content: an Agents / Skills / Plugins / MCP tab
 * bar, each tab labelled with a live item count, listing extension cards
 * backed by the unified `/v2/extensions` catalog (E16-S4). Agents get a
 * real create/edit modal (`PUT /v2/extensions/agents/{id}`); the other
 * kinds open a read-only detail dialog with an enable/disable action,
 * since only agents have an upsert endpoint on the backend.
 *
 * This renders screen content only — the E15 App Shell (sidebar rail and
 * contextual header) is provided by the routed page via `useShellHeader`.
 *
 * @returns The rendered hub.
 */
export function ExtensionsHub(): React.JSX.Element {
  const { data, error, isLoading, mutate } = useSWR(CATALOG_KEY, fetchCatalog);
  const [activeKind, setActiveKind] = React.useState<ExtensionKindV2>("agent");
  // Keyed as `${kind}:${id}`, matching the card `key` below — an item's bare
  // `id` is not unique across kinds (e.g. a skill and its MCP exposure can
  // share the same id), so a bare-id key would lock/unlock unrelated cards
  // in other tabs while a toggle mutation is in flight.
  const [togglingKey, setTogglingKey] = React.useState<string | null>(null);
  const [agentDialogOpen, setAgentDialogOpen] = React.useState(false);
  const [editingAgentId, setEditingAgentId] = React.useState<string | null>(null);
  const [detailItem, setDetailItem] = React.useState<ExtensionItemV2 | null>(null);
  const [detailOpen, setDetailOpen] = React.useState(false);

  const itemsByKind = React.useMemo(() => {
    const grouped = new Map<ExtensionKindV2, ExtensionItemV2[]>();
    for (const kind of KINDS) {
      grouped.set(kind, []);
    }
    for (const item of data?.items ?? []) {
      const bucket = grouped.get(item.kind as ExtensionKindV2);
      if (bucket) {
        bucket.push(item);
      }
    }
    return grouped;
  }, [data]);

  function openItem(kind: ExtensionKindV2, item: ExtensionItemV2): void {
    if (kind === "agent") {
      setEditingAgentId(item.id);
      setAgentDialogOpen(true);
    } else {
      setDetailItem(item);
      setDetailOpen(true);
    }
  }

  async function handleToggle(item: ExtensionItemV2, nextEnabled: boolean): Promise<void> {
    if (!data) {
      return;
    }
    const kind = item.kind as ExtensionKindV2;
    const key = `${item.kind}:${item.id}`;
    setTogglingKey(key);

    const optimisticItems = data.items.map((existing) =>
      existing.kind === item.kind && existing.id === item.id
        ? { ...existing, enabled: nextEnabled }
        : existing
    );

    try {
      await mutate(
        (async () => {
          const result = nextEnabled
            ? await enableExtensionV2(kind, item.id)
            : await disableExtensionV2(kind, item.id);
          return {
            ...data,
            items: data.items.map((existing) =>
              existing.kind === item.kind && existing.id === item.id ? result.item : existing
            ),
          };
        })(),
        {
          optimisticData: { ...data, items: optimisticItems },
          rollbackOnError: true,
          revalidate: false,
        }
      );
      toast({ title: nextEnabled ? "Enabled" : "Disabled", description: item.name });
      // Mirrors AgentFormDialog's close-after-save pattern: a successful
      // enable/disable from the read-only detail dialog closes it. When the
      // toggle came from a card's inline switch instead, the detail dialog
      // is already closed, so these are no-ops.
      const isOpenDetailItem = detailItem?.kind === item.kind && detailItem?.id === item.id;
      if (isOpenDetailItem) {
        setDetailOpen(false);
        setDetailItem(null);
      }
    } catch {
      toast({
        title: "Action failed",
        description: `Could not ${nextEnabled ? "enable" : "disable"} ${item.name}.`,
        variant: "destructive",
      });
    } finally {
      setTogglingKey((current) => (current === key ? null : current));
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <Tabs value={activeKind} onValueChange={(value) => setActiveKind(value as ExtensionKindV2)}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <TabsList>
            {KINDS.map((kind) => (
              <TabsTrigger key={kind} value={kind}>
                {EXTENSION_KIND_LABELS[kind]}
                {data ? ` (${itemsByKind.get(kind)?.length ?? 0})` : ""}
              </TabsTrigger>
            ))}
          </TabsList>
          {activeKind === "agent" ? (
            <Button
              type="button"
              onClick={() => {
                setEditingAgentId(null);
                setAgentDialogOpen(true);
              }}
            >
              Create agent
            </Button>
          ) : null}
        </div>

        {error ? (
          <p
            role="alert"
            className="mt-4 rounded-ds-md border border-ds-danger/40 bg-ds-danger/10 px-4 py-3 text-sm text-ds-danger"
          >
            Failed to load the extensions catalog.
          </p>
        ) : null}

        {KINDS.map((kind) => (
          <TabsContent key={kind} value={kind} className="mt-4">
            {isLoading ? (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {Array.from({ length: 3 }).map((_, index) => (
                  <Skeleton key={index} className="h-28 rounded-ds-lg" />
                ))}
              </div>
            ) : (itemsByKind.get(kind)?.length ?? 0) === 0 ? (
              <p className="text-sm text-ds-fg-2">
                No {EXTENSION_KIND_LABELS[kind].toLowerCase()} registered yet.
              </p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {itemsByKind.get(kind)!.map((item) => (
                  <ExtensionCard
                    key={`${item.kind}:${item.id}`}
                    kind={kind}
                    item={item}
                    onOpen={(target) => openItem(kind, target)}
                    onToggle={handleToggle}
                    toggling={togglingKey === `${item.kind}:${item.id}`}
                  />
                ))}
              </div>
            )}
          </TabsContent>
        ))}
      </Tabs>

      <AgentFormDialog
        open={agentDialogOpen}
        onOpenChange={setAgentDialogOpen}
        agentId={editingAgentId}
        onSaved={() => void mutate()}
      />
      <ExtensionDetailDialog
        open={detailOpen}
        onOpenChange={setDetailOpen}
        kind={(detailItem?.kind as ExtensionKindV2) ?? "skill"}
        item={detailItem}
        onToggle={handleToggle}
        toggling={
          detailItem !== null && togglingKey === `${detailItem.kind}:${detailItem.id}`
        }
      />
    </div>
  );
}
