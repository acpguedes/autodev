import * as React from "react";

import { cn, statusVariant } from "@/lib/utils";

/** Semantic color tone driving a glow dot's hue. */
export type StatusTone = "success" | "warn" | "danger" | "neutral";

const TONE_DOT_CLASSES: Record<StatusTone, string> = {
  success: "bg-ds-success shadow-[0_0_0_3px_hsl(var(--ds-success)/0.25)]",
  warn: "bg-ds-warn shadow-[0_0_0_3px_hsl(var(--ds-warn)/0.25)]",
  danger: "bg-ds-danger shadow-[0_0_0_3px_hsl(var(--ds-danger)/0.25)]",
  neutral: "bg-ds-fg-2 shadow-[0_0_0_3px_hsl(var(--ds-fg-2)/0.2)]",
};

/** Maps `lib/utils#statusVariant`'s badge variants onto glow-dot tones. */
const VARIANT_TONE: Record<ReturnType<typeof statusVariant>, StatusTone> = {
  destructive: "danger",
  default: "success",
  secondary: "warn",
  outline: "neutral",
};

/**
 * Map a raw session/run status string onto a glow-dot tone.
 *
 * Delegates to `lib/utils#statusVariant` so the glow dot (used in the
 * sessions list and sidebar) and the status `Badge` (used in the session
 * detail screen) always agree on how a given status string is classified,
 * rather than maintaining two divergent keyword tables.
 *
 * @param status - Raw status string from the control plane (e.g. "running",
 *   "completed", "failed").
 * @returns The tone conveying that status's severity.
 */
export function statusToTone(status: string): StatusTone {
  return VARIANT_TONE[statusVariant(status)];
}

export interface StatusGlowDotProps {
  /** Color tone for the dot. */
  tone: StatusTone;
  /**
   * Human-readable status text rendered next to the dot, so the state is
   * conveyed non-visually (for color-blind and screen-reader users) as well
   * as via color.
   */
  label: string;
  /** Extra classes applied to the wrapping element. */
  className?: string;
  /** Extra classes applied to the visible text label. */
  labelClassName?: string;
}

/**
 * A small glowing status indicator paired with a visible text label. The dot
 * itself is `aria-hidden`; the adjacent text is what makes the status
 * perceivable without relying on color alone (WCAG 1.4.1).
 *
 * @param props - Tone, label, and optional styling overrides.
 * @returns The rendered status indicator.
 */
export function StatusGlowDot({
  tone,
  label,
  className,
  labelClassName,
}: StatusGlowDotProps): React.JSX.Element {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span
        aria-hidden="true"
        className={cn("h-[7px] w-[7px] shrink-0 rounded-full", TONE_DOT_CLASSES[tone])}
      />
      <span className={cn("text-[12.5px] font-medium text-ds-fg-2", labelClassName)}>
        {label}
      </span>
    </span>
  );
}

export default StatusGlowDot;
