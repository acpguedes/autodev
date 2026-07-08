import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Guards the design tokens v2 contract (E15-S1). The v2 palette lands as an
 * additive layer in `styles/globals.css`; this test fails if the version
 * marker regresses or a required custom property is dropped, so downstream
 * shell/component work (E15-S2+) can rely on the tokens being present.
 */
const globalsCss = readFileSync(
  fileURLToPath(new URL("../../styles/globals.css", import.meta.url)),
  "utf8",
);

/** v2 custom properties every consumer depends on, per theme block. */
const REQUIRED_THEMED_PROPS = [
  "--ds-bg",
  "--ds-bg-2",
  "--ds-bg-3",
  "--ds-bg-4",
  "--ds-line",
  "--ds-line-strong",
  "--ds-fg",
  "--ds-fg-2",
  "--ds-fg-3",
  "--ds-accent",
  "--ds-accent-strong",
  "--ds-accent-fg",
  "--ds-success",
  "--ds-warn",
  "--ds-danger",
  "--ds-add-bg",
  "--ds-add-fg",
  "--ds-add-gut",
  "--ds-del-bg",
  "--ds-del-fg",
  "--ds-del-gut",
  "--ds-shadow-sm",
  "--ds-shadow-md",
  "--ds-shadow-lg",
] as const;

/** Theme-independent v2 tokens defined once under :root. */
const REQUIRED_ROOT_PROPS = [
  "--ds-radius-sm",
  "--ds-radius-md",
  "--ds-radius-lg",
  "--ds-radius-xl",
  "--ds-display-lg",
  "--ds-display-md",
  "--ds-display-sm",
] as const;

describe("design tokens v2 (E15-S1)", () => {
  it("declares token version 2.0.0", () => {
    expect(globalsCss).toContain('--ds-token-version: "2.0.0"');
    expect(globalsCss).not.toContain('--ds-token-version: "1.0.0"');
  });

  it("defines every themed v2 property in both light and dark blocks", () => {
    for (const prop of REQUIRED_THEMED_PROPS) {
      // One declaration under `:root, .light`, one under `.dark`.
      const count = globalsCss.split(`${prop}:`).length - 1;
      expect(count, `${prop} should be declared twice (light + dark)`).toBe(2);
    }
  });

  it("defines theme-independent v2 tokens once under :root", () => {
    for (const prop of REQUIRED_ROOT_PROPS) {
      const count = globalsCss.split(`${prop}:`).length - 1;
      expect(count, `${prop} should be declared once`).toBe(1);
    }
  });

  it("keeps the E10 token layer additive (v1 tokens still present)", () => {
    // E15-S3 removes these; until then S1 must not delete them.
    expect(globalsCss).toContain("--background:");
    expect(globalsCss).toContain("--foreground:");
  });
});
