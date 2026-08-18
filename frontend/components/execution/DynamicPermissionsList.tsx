"use client";

import { Button } from "@/components/ui/button";
import { useTranslations } from "@/lib/i18n";
import type { DynamicPermissionV2 } from "@/lib/execution_v2";

import { DecisionCategoryBadge } from "./DecisionCategoryBadge";

export interface DynamicPermissionsListProps {
  /** The tenant's currently granted dynamic permissions. */
  permissions: DynamicPermissionV2[];
  /** Permission ids with a revoke request in flight. */
  busyIds: ReadonlySet<string>;
  /** Revokes one permission. */
  onRevoke: (permissionId: string) => void;
}

/**
 * List/revoke panel for hybrid mode's "always" grants (E14-S5-T3).
 *
 * Each row mirrors the rule a `PendingDecision` resolved with
 * `persistAsRule: true` produced — category, scope, and the command/path
 * pattern it now auto-allows.
 */
export function DynamicPermissionsList({ permissions, busyIds, onRevoke }: DynamicPermissionsListProps) {
  const { t } = useTranslations();

  if (permissions.length === 0) {
    return <p className="text-sm text-ds-fg-2">{t("execution.emptyPermissions")}</p>;
  }

  return (
    <ul className="flex flex-col gap-2">
      {permissions.map((permission) => (
        <li
          key={permission.permissionId}
          className="flex items-center justify-between gap-3 rounded-ds-md border border-ds-line bg-ds-bg-2 px-3 py-2"
        >
          <div className="flex items-center gap-2">
            <DecisionCategoryBadge category={permission.category} />
            <span className="font-mono text-xs text-ds-fg-2">{permission.pattern ?? "*"}</span>
          </div>
          <Button
            size="sm"
            variant="ghost"
            className="text-ds-danger"
            onClick={() => onRevoke(permission.permissionId)}
            disabled={busyIds.has(permission.permissionId)}
          >
            {t("execution.permission.revoke")}
          </Button>
        </li>
      ))}
    </ul>
  );
}
