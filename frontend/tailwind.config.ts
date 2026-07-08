import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["class"],
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--background))",
          foreground: "hsl(var(--foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--background))",
          foreground: "hsl(var(--foreground))",
        },
        // Design tokens v2 (E15-S1). Namespaced under `ds` so E10 colors
        // above stay intact until E15-S3. The `<alpha-value>` placeholder
        // lets Tailwind alpha modifiers (e.g. `bg-ds-success/12`) produce
        // the prototype's status/accent tints.
        ds: {
          bg: "hsl(var(--ds-bg) / <alpha-value>)",
          "bg-2": "hsl(var(--ds-bg-2) / <alpha-value>)",
          "bg-3": "hsl(var(--ds-bg-3) / <alpha-value>)",
          "bg-4": "hsl(var(--ds-bg-4) / <alpha-value>)",
          line: "hsl(var(--ds-line) / <alpha-value>)",
          "line-strong": "hsl(var(--ds-line-strong) / <alpha-value>)",
          fg: "hsl(var(--ds-fg) / <alpha-value>)",
          "fg-2": "hsl(var(--ds-fg-2) / <alpha-value>)",
          "fg-3": "hsl(var(--ds-fg-3) / <alpha-value>)",
          accent: "hsl(var(--ds-accent) / <alpha-value>)",
          "accent-strong": "hsl(var(--ds-accent-strong) / <alpha-value>)",
          "accent-fg": "hsl(var(--ds-accent-fg) / <alpha-value>)",
          success: "hsl(var(--ds-success) / <alpha-value>)",
          warn: "hsl(var(--ds-warn) / <alpha-value>)",
          danger: "hsl(var(--ds-danger) / <alpha-value>)",
          "add-bg": "hsl(var(--ds-add-bg) / <alpha-value>)",
          "add-fg": "hsl(var(--ds-add-fg) / <alpha-value>)",
          "add-gut": "hsl(var(--ds-add-gut) / <alpha-value>)",
          "del-bg": "hsl(var(--ds-del-bg) / <alpha-value>)",
          "del-fg": "hsl(var(--ds-del-fg) / <alpha-value>)",
          "del-gut": "hsl(var(--ds-del-gut) / <alpha-value>)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
        // Design tokens v2 radius scale (E15-S1).
        "ds-sm": "var(--ds-radius-sm)",
        "ds-md": "var(--ds-radius-md)",
        "ds-lg": "var(--ds-radius-lg)",
        "ds-xl": "var(--ds-radius-xl)",
        "ds-full": "var(--ds-radius-full)",
      },
      boxShadow: {
        sm: "var(--shadow-sm)",
        DEFAULT: "var(--shadow-md)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        // Design tokens v2 elevation scale (E15-S1).
        "ds-sm": "var(--ds-shadow-sm)",
        "ds-md": "var(--ds-shadow-md)",
        "ds-lg": "var(--ds-shadow-lg)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
        // Design tokens v2 serif display family (E15-S1, Newsreader).
        serif: ["var(--font-serif)", "Georgia", "serif"],
      },
    },
  },
  plugins: [],
};

export default config;
