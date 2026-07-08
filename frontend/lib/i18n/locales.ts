/**
 * Supported UI locales for AutoDev Architect (E15-S4). `en` is the default
 * locale and the canonical source of truth for every translation key;
 * `pt-BR` is the first additional translation, per RFC-006's language
 * decision (English default, pt-BR as the first localization).
 */
export const DEFAULT_LOCALE = "en" as const;

/** Every locale the shell can render in, in switcher display order. */
export const SUPPORTED_LOCALES = ["en", "pt-BR"] as const;

/** A supported UI locale code. */
export type Locale = (typeof SUPPORTED_LOCALES)[number];

/** Human-readable label for each locale, shown in the sidebar locale switcher. */
export const LOCALE_LABELS: Record<Locale, string> = {
  en: "English",
  "pt-BR": "Português (BR)",
};

/** `localStorage` key used to persist the user's locale choice across sessions. */
export const LOCALE_STORAGE_KEY = "autodev.locale";

/**
 * Narrow an arbitrary string (e.g. read from `localStorage`) to a
 * {@link Locale}.
 *
 * @param value - Candidate locale string, or `null`/`undefined`.
 * @returns Whether `value` is one of {@link SUPPORTED_LOCALES}.
 */
export function isLocale(value: string | null | undefined): value is Locale {
  return !!value && (SUPPORTED_LOCALES as readonly string[]).includes(value);
}
