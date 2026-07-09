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

const RELATIVE_TIME_UNITS: ReadonlyArray<{ suffix: string; seconds: number }> = [
  { suffix: "y", seconds: 31536000 },
  { suffix: "mo", seconds: 2592000 },
  { suffix: "d", seconds: 86400 },
  { suffix: "h", seconds: 3600 },
  { suffix: "m", seconds: 60 },
];

/**
 * Format an ISO timestamp as a short relative-time string (e.g. "3h ago",
 * "just now"). Falls back to "unknown" for missing/unparseable input so
 * callers never render `Invalid Date`.
 *
 * @param isoTimestamp - An ISO-8601 timestamp string, or a falsy value.
 * @param now - The reference time to compare against (defaults to `Date.now()`).
 * @returns A short, human-readable relative-time label.
 */
export function formatRelativeTime(isoTimestamp: string | undefined | null, now: number = Date.now()): string {
  if (!isoTimestamp) {
    return "unknown";
  }
  const then = Date.parse(isoTimestamp);
  if (Number.isNaN(then)) {
    return "unknown";
  }
  const diffSeconds = Math.round((now - then) / 1000);
  if (diffSeconds < 0) {
    return "just now";
  }
  if (diffSeconds < 60) {
    return "just now";
  }
  for (const { suffix, seconds } of RELATIVE_TIME_UNITS) {
    const count = Math.floor(diffSeconds / seconds);
    if (count >= 1) {
      return `${count}${suffix} ago`;
    }
  }
  return "just now";
}
