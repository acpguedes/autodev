import type { Metadata } from "next";
import { Newsreader, Instrument_Sans, JetBrains_Mono } from "next/font/google";
import "../styles/globals.css";
import { ThemeProvider } from "@/components/ThemeProvider";
import { Toaster } from "@/components/ui/toaster";

/**
 * Design tokens v2 typefaces (E15-S1), self-hosted at build time via
 * `next/font/google` — no external font `<link>`, so no network FOUT. Each
 * font exposes a CSS variable consumed by the token layer and Tailwind
 * `font-{serif,sans,mono}` utilities.
 *
 * `adjustFontFallback` is disabled for Newsreader: Next 14 ships no
 * fallback-metric override for it, so the automatic size-adjusted fallback
 * cannot be generated; the serif is display-only, so the fallback-swap
 * shift is negligible.
 */
const fontSerif = Newsreader({
  subsets: ["latin"],
  variable: "--font-serif",
  display: "swap",
  adjustFontFallback: false,
});
const fontSans = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});
const fontMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AutoDev Architect",
  description: "Execution control center for configuring and orchestrating AutoDev Architect",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${fontSerif.variable} ${fontSans.variable} ${fontMono.variable}`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem={false}
        >
          {children}
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
