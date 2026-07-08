"use client";

import * as React from "react";

import { translate } from "./dictionaries";
import { DEFAULT_LOCALE, LOCALE_STORAGE_KEY, isLocale, type Locale } from "./locales";

/** Everything exposed through the i18n context. */
export interface I18nContextValue {
  /** Active UI locale. */
  locale: Locale;
  /** Switch the active locale and persist the choice. */
  setLocale: (locale: Locale) => void;
  /** Translate a dot-path key, interpolating any `{{placeholders}}`. */
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const I18nContext = React.createContext<I18nContextValue | null>(null);

/**
 * Provide the active UI locale and a `t()` translator to the whole app
 * (E15-S4). Renders as {@link DEFAULT_LOCALE} on the server and on first
 * client paint — matching the root layout's `<html lang="en">` so there is
 * no hydration mismatch — then hydrates the user's persisted choice from
 * `localStorage` on mount and keeps `document.documentElement.lang` in sync
 * with the active locale (WCAG 2.2 AA success criterion 3.1.1).
 *
 * @param props - Standard children.
 * @returns The context provider.
 */
export function I18nProvider({ children }: { children: React.ReactNode }): React.JSX.Element {
  const [locale, setLocaleState] = React.useState<Locale>(DEFAULT_LOCALE);

  React.useEffect(() => {
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
    if (isLocale(stored)) {
      setLocaleState(stored);
    }
    // Intentionally runs once: this only hydrates the persisted choice made
    // on a previous visit, it does not react to further changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  React.useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = React.useCallback((next: Locale) => {
    setLocaleState(next);
    window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
  }, []);

  const t = React.useCallback(
    (key: string, vars?: Record<string, string | number>) => translate(locale, key, vars),
    [locale]
  );

  const value = React.useMemo<I18nContextValue>(
    () => ({ locale, setLocale, t }),
    [locale, setLocale, t]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

/**
 * Access the active locale, the locale setter, and the `t()` translator.
 *
 * @returns The i18n context value.
 * @throws Error when called outside an {@link I18nProvider}.
 */
export function useTranslations(): I18nContextValue {
  const context = React.useContext(I18nContext);
  if (!context) {
    throw new Error("useTranslations must be used within an I18nProvider");
  }
  return context;
}
