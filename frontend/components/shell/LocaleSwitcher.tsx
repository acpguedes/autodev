"use client";

import * as React from "react";
import { Languages } from "lucide-react";

import { Button } from "@/components/ui/button";
import { LOCALE_LABELS, SUPPORTED_LOCALES, useTranslations } from "@/lib/i18n";

/**
 * Cycle the active UI locale through {@link SUPPORTED_LOCALES} (E15-S4).
 * Mirrors {@link ThemeToggle}'s mounted-guard pattern so the button's label
 * never flashes a locale different from what the server rendered.
 *
 * @returns The locale-switcher button.
 */
export function LocaleSwitcher(): React.JSX.Element {
  const { locale, setLocale } = useTranslations();
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => setMounted(true), []);

  const activeLocale = mounted ? locale : SUPPORTED_LOCALES[0];
  const currentIndex = SUPPORTED_LOCALES.indexOf(activeLocale);
  const nextLocale = SUPPORTED_LOCALES[(currentIndex + 1) % SUPPORTED_LOCALES.length];

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      aria-label={`Switch language to ${LOCALE_LABELS[nextLocale]}`}
      onClick={() => setLocale(nextLocale)}
      className="h-7 gap-1.5 px-2 text-[12.5px]"
    >
      <Languages className="h-3.5 w-3.5" aria-hidden="true" />
      {LOCALE_LABELS[activeLocale]}
    </Button>
  );
}

export default LocaleSwitcher;
