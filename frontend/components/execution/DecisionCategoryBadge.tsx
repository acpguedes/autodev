import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { PendingDecisionV2 } from "@/lib/execution_v2";

/** Maps every execution policy category to a `Badge` visual variant. */
const CATEGORY_BADGE_VARIANT: Record<string, NonNullable<BadgeProps["variant"]>> = {
  shell: "secondary",
  "fs-write": "default",
  patch: "default",
  network: "destructive",
  "secrets-read": "destructive",
  validation: "outline",
};

export interface DecisionCategoryBadgeProps {
  /** The policy category of the blocked action. */
  category: PendingDecisionV2["category"];
}

/** Category pill for a pending execution-action decision. */
export function DecisionCategoryBadge({ category }: DecisionCategoryBadgeProps) {
  return <Badge variant={CATEGORY_BADGE_VARIANT[category] ?? "outline"}>{category}</Badge>;
}
