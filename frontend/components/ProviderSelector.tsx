import * as React from "react";

import { cn } from "@/lib/utils";

/** Identifier for a supported LLM provider. */
export type ProviderId = "stub" | "ollama" | "openai";

/** One selectable provider option (id, display label, default model). */
export interface ProviderOption {
  id: ProviderId;
  label: string;
  model: string;
}

/**
 * The supported providers, matching the redesign prototype's provider chips
 * (`layout_prototype_brainstorm/Autodev Redesing.html`) exactly: id, display
 * label, and the default model each provider suggests when first selected.
 */
export const PROVIDER_OPTIONS: readonly ProviderOption[] = [
  { id: "stub", label: "Stub (offline)", model: "deterministic-stub" },
  { id: "ollama", label: "Ollama", model: "qwen2.5-coder:14b" },
  { id: "openai", label: "OpenAI", model: "gpt-4o-mini" },
];

/**
 * Look up the default model suggested for a provider id.
 *
 * @param providerId - Raw provider identifier (may be unrecognized).
 * @returns The provider's default model, or `undefined` if unrecognized.
 */
export function defaultModelFor(providerId: string): string | undefined {
  return PROVIDER_OPTIONS.find((option) => option.id === providerId)?.model;
}

export interface ProviderSelectorProps {
  /** Currently selected provider id. */
  value: string;
  /** Called with the newly selected provider id. */
  onChange: (providerId: ProviderId) => void;
  /** Disables all pills (e.g. while saving). */
  disabled?: boolean;
  /** Extra classes applied to the wrapping `radiogroup`. */
  className?: string;
}

/**
 * Segmented pill selector for the active LLM provider (Stub offline / Ollama
 * / OpenAI), matching the redesign prototype's provider chips. Renders as a
 * `radiogroup` of `radio` buttons so assistive tech announces the
 * single-select semantics.
 *
 * @param props - Current value, change handler, and optional styling.
 * @returns The rendered provider selector.
 */
export function ProviderSelector({
  value,
  onChange,
  disabled,
  className,
}: ProviderSelectorProps): React.JSX.Element {
  return (
    <div
      role="radiogroup"
      aria-label="LLM provider"
      className={cn("flex flex-wrap gap-2", className)}
    >
      {PROVIDER_OPTIONS.map((option) => {
        const selected = option.id === value;
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(option.id)}
            className={cn(
              "rounded-ds-full border px-3.5 py-1.5 text-[13px] font-semibold transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent",
              "disabled:cursor-not-allowed disabled:opacity-50",
              selected
                ? "border-ds-accent bg-ds-accent/10 text-ds-accent"
                : "border-ds-line bg-ds-bg-3 text-ds-fg-2 hover:border-ds-line-strong hover:text-ds-fg"
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export default ProviderSelector;
