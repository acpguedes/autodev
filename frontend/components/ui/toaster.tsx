"use client";

import { useToast } from "@/lib/use-toast";
import { Toast } from "@/components/ui/toast";

/** Fixed-position stack that renders every currently open toast from `useToast`. */
export function Toaster() {
  const { toasts, dismiss } = useToast();

  return (
    <div
      className="pointer-events-none fixed bottom-0 right-0 z-[100] flex max-h-screen w-full flex-col gap-2 p-4 sm:max-w-sm"
      data-testid="toaster"
    >
      {toasts
        .filter((t) => t.open)
        .map((t) => (
          <Toast
            key={t.id}
            title={t.title}
            description={t.description}
            variant={t.variant}
            onDismiss={() => dismiss(t.id)}
          />
        ))}
    </div>
  );
}
