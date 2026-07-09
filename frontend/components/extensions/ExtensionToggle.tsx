"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

/** Props accepted by {@link ExtensionToggle}. */
export interface ExtensionToggleProps {
  /** Current enabled state. */
  checked: boolean;
  /** Called with the next desired state when the toggle is activated. */
  onCheckedChange: (checked: boolean) => void;
  /** Accessible name announcing which extension this toggle controls. */
  label: string;
  /** Disables interaction while a mutation is in flight. */
  disabled?: boolean;
  /** Additional class names merged onto the root button. */
  className?: string;
}

/**
 * A small accessible enable/disable switch for extension cards.
 *
 * There is no `Switch` primitive in `components/ui/`, so this implements
 * the WAI-ARIA switch pattern directly: a `role="switch"` button with
 * `aria-checked` reflecting state and a visible pill/knob affordance driven
 * by the `ds-*` design tokens.
 *
 * @param props - See {@link ExtensionToggleProps}.
 * @returns The rendered switch button.
 */
export function ExtensionToggle({
  checked,
  onCheckedChange,
  label,
  disabled = false,
  className,
}: ExtensionToggleProps): React.JSX.Element {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-ds-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        checked
          ? "border-ds-accent bg-ds-accent"
          : "border-ds-line-strong bg-ds-bg-3",
        className
      )}
    >
      <span
        className={cn(
          "inline-block h-3.5 w-3.5 transform rounded-ds-full bg-white shadow-ds-sm transition-transform",
          checked ? "translate-x-[18px]" : "translate-x-[3px]"
        )}
      />
    </button>
  );
}
