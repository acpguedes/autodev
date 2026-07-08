import en from "@/locales/en.json";
import ptBR from "@/locales/pt-BR.json";

import { DEFAULT_LOCALE, type Locale } from "./locales";

/**
 * Shape every locale dictionary must satisfy, inferred from `en.json` — the
 * canonical source of truth for every translation key.
 */
export type Dictionary = typeof en;

// Assigning the imported `pt-BR.json` to the `Dictionary` type makes a
// missing key a compile-time error: TypeScript rejects the assignment unless
// every key required by `en.json` is present. This is what backs E15-S4's
// "no missing-key fallback text visible" requirement for the two locales
// this story ships.
const ptBRDictionary: Dictionary = ptBR;

/** Locale -> dictionary map covering every {@link Locale}. */
export const dictionaries: Record<Locale, Dictionary> = {
  en,
  "pt-BR": ptBRDictionary,
};

/**
 * Resolve a dot-separated key path (e.g. `"chat.errors.sendMessage"`) within
 * a dictionary.
 *
 * @param dictionary - Dictionary to search.
 * @param path - Dot-separated key path.
 * @returns The string at `path`, or `undefined` if any segment is missing or
 *   the resolved value is not a string.
 */
function resolvePath(dictionary: Dictionary, path: string): string | undefined {
  const value = path.split(".").reduce<unknown>((node, segment) => {
    if (node && typeof node === "object" && segment in (node as Record<string, unknown>)) {
      return (node as Record<string, unknown>)[segment];
    }
    return undefined;
  }, dictionary);
  return typeof value === "string" ? value : undefined;
}

/**
 * Substitute `{{name}}` placeholders in `template` with values from `vars`.
 * Placeholders with no matching entry in `vars` are left untouched.
 *
 * @param template - String possibly containing `{{name}}` placeholders.
 * @param vars - Values to interpolate, keyed by placeholder name.
 * @returns The interpolated string.
 */
function interpolate(template: string, vars?: Record<string, string | number>): string {
  if (!vars) {
    return template;
  }
  return template.replace(/\{\{(\w+)\}\}/g, (match, key: string) =>
    key in vars ? String(vars[key]) : match
  );
}

/**
 * Translate a dot-path key for the given locale, interpolating any
 * `{{placeholders}}` in the resolved string.
 *
 * Resolution order: the requested `locale`, then {@link DEFAULT_LOCALE} as a
 * fallback. A key missing from both dictionaries is a real authoring bug
 * (every locale is statically checked against `en.json`'s shape), so this
 * only guards dynamically-constructed keys; it never surfaces the raw key to
 * the user in the two shipped locales.
 *
 * @param locale - Active UI locale.
 * @param key - Dot-separated translation key, e.g. `"chat.send"`.
 * @param vars - Optional values to interpolate into the resolved string.
 * @returns The translated, interpolated string.
 */
export function translate(
  locale: Locale,
  key: string,
  vars?: Record<string, string | number>
): string {
  const primary = resolvePath(dictionaries[locale], key);
  if (primary !== undefined) {
    return interpolate(primary, vars);
  }

  if (locale !== DEFAULT_LOCALE) {
    if (typeof window !== "undefined") {
      console.warn(`[i18n] Missing key "${key}" for locale "${locale}"; falling back to "en".`);
    }
    const fallback = resolvePath(dictionaries[DEFAULT_LOCALE], key);
    if (fallback !== undefined) {
      return interpolate(fallback, vars);
    }
  }

  if (typeof window !== "undefined") {
    console.warn(`[i18n] Missing translation key "${key}".`);
  }
  return key;
}
