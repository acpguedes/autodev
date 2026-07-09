import { Button } from "@/components/ui/button";

export interface ExecuteApprovedFooterProps {
  /** Number of steps currently in the `approved` state. */
  approvedCount: number;
  /** True while the execute-approved request is in flight. */
  executing: boolean;
  /** Triggers execution of every currently-approved step. */
  onExecute: () => void;
  /** Button label shown while idle. */
  label: string;
  /** Button label shown while `executing` is true. */
  executingLabel: string;
  /** Helper text shown when there is nothing approved to execute. */
  needsApprovalLabel: string;
}

/**
 * Sticky footer action for running every approved step in one call to
 * `POST /v2/plans/{sessionId}/execute-approved`. Disabled until at least one
 * step is approved (prototype §5.2 gating rule).
 */
export function ExecuteApprovedFooter({
  approvedCount,
  executing,
  onExecute,
  label,
  executingLabel,
  needsApprovalLabel,
}: ExecuteApprovedFooterProps) {
  const disabled = approvedCount === 0 || executing;

  return (
    <div className="sticky bottom-0 z-10 flex items-center justify-between gap-4 border-t border-ds-line bg-ds-bg-2/95 px-4 py-3 shadow-ds-sm backdrop-blur">
      <p className="text-sm text-ds-fg-3">{approvedCount === 0 ? needsApprovalLabel : null}</p>
      <Button className="ml-auto" onClick={onExecute} disabled={disabled}>
        {executing ? executingLabel : label}
      </Button>
    </div>
  );
}
