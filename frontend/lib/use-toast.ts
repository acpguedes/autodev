"use client";

import * as React from "react";

/** Maximum number of toasts kept in the visible stack at once. */
const TOAST_LIMIT = 3;
/** Milliseconds a toast stays mounted after being dismissed (exit animation window). */
const TOAST_REMOVE_DELAY = 1000;
/** Default milliseconds a toast stays open before auto-dismissing. */
const TOAST_AUTO_DISMISS_MS = 5000;

export interface ToastItem {
  id: string;
  title?: React.ReactNode;
  description?: React.ReactNode;
  variant?: "default" | "destructive";
  open: boolean;
}

type ToastInput = Omit<ToastItem, "id" | "open"> & {
  /** Auto-dismiss delay in ms; pass `Infinity` to keep the toast open. */
  duration?: number;
};

type Action =
  | { type: "ADD_TOAST"; toast: ToastItem }
  | { type: "DISMISS_TOAST"; toastId: string }
  | { type: "REMOVE_TOAST"; toastId: string };

let count = 0;
/** Generates a unique, incrementing toast id for the lifetime of the session. */
function genId(): string {
  count = (count + 1) % Number.MAX_SAFE_INTEGER;
  return count.toString();
}

const listeners: Array<(state: ToastItem[]) => void> = [];
let memoryState: ToastItem[] = [];
const removeTimeouts = new Map<string, ReturnType<typeof setTimeout>>();
const autoDismissTimeouts = new Map<string, ReturnType<typeof setTimeout>>();

function dispatch(action: Action): void {
  memoryState = reducer(memoryState, action);
  listeners.forEach((listener) => listener(memoryState));
}

function reducer(state: ToastItem[], action: Action): ToastItem[] {
  switch (action.type) {
    case "ADD_TOAST":
      return [action.toast, ...state].slice(0, TOAST_LIMIT);
    case "DISMISS_TOAST":
      clearAutoDismiss(action.toastId);
      scheduleRemoval(action.toastId);
      return state.map((t) =>
        t.id === action.toastId ? { ...t, open: false } : t
      );
    case "REMOVE_TOAST":
      return state.filter((t) => t.id !== action.toastId);
    default:
      return state;
  }
}

function clearAutoDismiss(toastId: string): void {
  const pending = autoDismissTimeouts.get(toastId);
  if (pending !== undefined) {
    clearTimeout(pending);
    autoDismissTimeouts.delete(toastId);
  }
}

function scheduleRemoval(toastId: string): void {
  if (removeTimeouts.has(toastId)) return;
  const timeout = setTimeout(() => {
    removeTimeouts.delete(toastId);
    dispatch({ type: "REMOVE_TOAST", toastId });
  }, TOAST_REMOVE_DELAY);
  removeTimeouts.set(toastId, timeout);
}

/**
 * Enqueues a toast notification that auto-dismisses after `duration` ms
 * (default {@link TOAST_AUTO_DISMISS_MS}; pass `Infinity` to disable).
 *
 * @param toast - Toast content, variant and optional auto-dismiss duration.
 * @returns Handle with the generated id and a `dismiss` function.
 */
function toast(toast: ToastInput) {
  const { duration = TOAST_AUTO_DISMISS_MS, ...content } = toast;
  const id = genId();
  dispatch({ type: "ADD_TOAST", toast: { ...content, id, open: true } });
  if (Number.isFinite(duration) && duration > 0) {
    autoDismissTimeouts.set(
      id,
      setTimeout(() => {
        autoDismissTimeouts.delete(id);
        dispatch({ type: "DISMISS_TOAST", toastId: id });
      }, duration)
    );
  }
  return {
    id,
    dismiss: () => dispatch({ type: "DISMISS_TOAST", toastId: id }),
  };
}

/**
 * React hook exposing the current toast stack and helpers to create or
 * dismiss toasts.
 *
 * @returns Object with the live `toasts` array, `toast()` and `dismiss()`.
 */
function useToast() {
  const [state, setState] = React.useState<ToastItem[]>(memoryState);

  React.useEffect(() => {
    listeners.push(setState);
    return () => {
      const index = listeners.indexOf(setState);
      if (index > -1) listeners.splice(index, 1);
    };
  }, []);

  return {
    toasts: state,
    toast,
    dismiss: (toastId: string) => dispatch({ type: "DISMISS_TOAST", toastId }),
  };
}

export { useToast, toast };
