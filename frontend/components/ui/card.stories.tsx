import type { Meta, StoryObj } from "@storybook/nextjs-vite";

import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "./card";
import { Button } from "./button";

const meta: Meta<typeof Card> = {
  title: "UI/Card",
  component: Card,
};
export default meta;

type Story = StoryObj<typeof Card>;

export const Default: Story = {
  render: () => (
    <Card style={{ maxWidth: 360 }}>
      <CardHeader>
        <CardTitle>Plan review</CardTitle>
        <CardDescription>Approve or request changes before execution.</CardDescription>
      </CardHeader>
      <CardContent>
        <p>3 steps queued, 1 pending approval gate.</p>
      </CardContent>
      <CardFooter>
        <Button size="sm">Approve</Button>
      </CardFooter>
    </Card>
  ),
};

/**
 * Design tokens v2 showcase (E15-S1). Renders the "Execution Control Center"
 * surfaces, accent, status colors, and serif display type against the v2
 * background/foreground so every text pair honors WCAG 2.2 AA. Toggle the
 * Storybook theme control to compare warm-paper light and charcoal dark.
 */
function Swatch({ token, label }: { token: string; label: string }) {
  return (
    <figure style={{ margin: 0 }}>
      <div
        aria-hidden
        style={{
          height: 44,
          borderRadius: "var(--ds-radius-md)",
          background: `hsl(var(${token}))`,
          border: "1px solid hsl(var(--ds-line-strong))",
        }}
      />
      <figcaption
        style={{
          marginTop: 6,
          fontSize: 12,
          color: "hsl(var(--ds-fg-2))",
        }}
      >
        {label}
      </figcaption>
    </figure>
  );
}

export const TokensV2: Story = {
  name: "Design tokens v2",
  render: () => (
    <div
      style={{
        background: "hsl(var(--ds-bg))",
        color: "hsl(var(--ds-fg))",
        border: "1px solid hsl(var(--ds-line))",
        borderRadius: "var(--ds-radius-lg)",
        boxShadow: "var(--ds-shadow-md)",
        padding: 24,
        maxWidth: 560,
        display: "flex",
        flexDirection: "column",
        gap: 20,
      }}
    >
      <div>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--font-serif, Georgia, serif)",
            fontSize: "var(--ds-display-md)",
            lineHeight: "var(--ds-display-leading)",
          }}
        >
          Execution Control Center
        </p>
        <p style={{ margin: "4px 0 0", color: "hsl(var(--ds-fg-2))" }}>
          Design tokens v2 — warm paper and charcoal.
        </p>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
        }}
      >
        <Swatch token="--ds-bg-2" label="Surface 2" />
        <Swatch token="--ds-bg-3" label="Surface 3" />
        <Swatch token="--ds-bg-4" label="Surface 4" />
        <Swatch token="--ds-line-strong" label="Line strong" />
        <Swatch token="--ds-accent" label="Accent" />
        <Swatch token="--ds-accent-strong" label="Accent strong" />
        <Swatch token="--ds-success" label="Success" />
        <Swatch token="--ds-danger" label="Danger" />
      </div>

      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
        <span style={{ color: "hsl(var(--ds-success))", fontWeight: 600 }}>
          Success
        </span>
        <span style={{ color: "hsl(var(--ds-warn))", fontWeight: 600 }}>
          Warning
        </span>
        <span style={{ color: "hsl(var(--ds-danger))", fontWeight: 600 }}>
          Danger
        </span>
        <span
          style={{
            background: "hsl(var(--ds-accent))",
            color: "hsl(var(--ds-accent-fg))",
            padding: "4px 12px",
            borderRadius: "var(--ds-radius-full)",
            fontWeight: 600,
          }}
        >
          Accent chip
        </span>
      </div>
    </div>
  ),
};
