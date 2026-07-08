import * as React from "react";
import { cva } from "class-variance-authority";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ToastItem } from "@/lib/use-toast";

const toastVariants = cva(
  "pointer-events-auto relative flex w-full items-start justify-between gap-3 overflow-hidden rounded-md border p-4 shadow-lg transition-all",
  {
    variants: {
      variant: {
        default: "border-border bg-background text-foreground",
        destructive:
          "border-destructive bg-destructive text-destructive-foreground",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface ToastProps extends Omit<ToastItem, "id" | "open"> {
  onDismiss?: () => void;
}

/** A single dismissible toast notification. Announces itself via `role="status"`. */
const Toast = React.forwardRef<HTMLDivElement, ToastProps>(
  ({ title, description, variant, onDismiss }, ref) => (
    <div
      ref={ref}
      role={variant === "destructive" ? "alert" : "status"}
      aria-live={variant === "destructive" ? "assertive" : "polite"}
      className={cn(toastVariants({ variant }))}
    >
      <div className="grid gap-1">
        {title && <div className="text-sm font-semibold">{title}</div>}
        {description && <div className="text-sm opacity-90">{description}</div>}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss notification"
        className="rounded-sm opacity-70 transition-opacity hover:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  )
);
Toast.displayName = "Toast";

export { Toast, toastVariants };
