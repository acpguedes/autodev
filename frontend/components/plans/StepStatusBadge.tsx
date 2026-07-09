import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { PlanStepState } from "@/lib/plans_v2";

/**
 * Maps every {@link PlanStepState} to a `Badge` visual variant.
 *
 * Kept as an explicit lookup (rather than the generic substring-based
 * `statusVariant()` helper in `lib/utils.ts`) because the raw state strings
 * `"under_review"` and `"executing"` do not contain any of that helper's
 * matched substrings and would otherwise fall through to `"outline"`.
 */
const STATE_BADGE_VARIANT: Record<PlanStepState, NonNullable<BadgeProps["variant"]>> = {
  draft: "outline",
  under_review: "secondary",
  approved: "default",
  rejected: "destructive",
  executing: "secondary",
  completed: "default",
};

export interface StepStatusBadgeProps {
  /** The step's current approval-gate state. */
  state: PlanStepState;
  /** Localized label to display for `state`. */
  label: string;
}

/** Status pill for a plan step, colored by its approval-gate state. */
export function StepStatusBadge({ state, label }: StepStatusBadgeProps) {
  return <Badge variant={STATE_BADGE_VARIANT[state]}>{label}</Badge>;
}
