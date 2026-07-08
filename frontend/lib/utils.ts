import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Map a session/run/step status onto a design-system badge variant.
 *
 * @param status - Raw status string from the control plane.
 * @returns The badge variant conveying the status severity.
 */
export function statusVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
  const value = status.toLowerCase();
  if (value.includes("fail") || value.includes("error") || value.includes("reject")) {
    return "destructive";
  }
  if (value.includes("complete") || value.includes("success") || value.includes("approved")) {
    return "default";
  }
  if (value.includes("run") || value.includes("active") || value.includes("progress")) {
    return "secondary";
  }
  return "outline";
}
