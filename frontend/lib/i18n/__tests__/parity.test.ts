import { describe, expect, it } from "vitest";

// Relative paths: the vitest `unit` project does not resolve the `@/` alias.
import en from "../../../locales/en.json";
import ptBR from "../../../locales/pt-BR.json";

/**
 * Collect every dot-path key of a nested dictionary whose leaves are strings.
 *
 * @param node - Dictionary subtree to walk.
 * @param prefix - Dot-path accumulated so far.
 * @returns All leaf key paths under `node`, sorted.
 */
function collectKeys(node: unknown, prefix = ""): string[] {
  if (typeof node === "string") {
    return [prefix];
  }
  if (node === null || typeof node !== "object") {
    throw new Error(`Non-string, non-object dictionary leaf at "${prefix}"`);
  }
  return Object.entries(node as Record<string, unknown>)
    .flatMap(([key, value]) => collectKeys(value, prefix ? `${prefix}.${key}` : key))
    .sort();
}

// The compile-time `Dictionary = typeof en` check only catches keys missing
// from pt-BR; this runtime walk also rejects extra keys and non-string leaves
// in either direction, protecting future locale additions (E18-S4).
describe("locale dictionary parity", () => {
  it("en and pt-BR expose exactly the same key set", () => {
    expect(collectKeys(ptBR)).toEqual(collectKeys(en));
  });

  it("shell namespace exists with the E18-S4 chrome strings", () => {
    const keys = collectKeys(en);
    for (const key of [
      "shell.nav.groupWorkspace",
      "shell.nav.items.chat",
      "shell.sidebar.theme",
      "shell.header.newSession",
      "shell.panel.title",
      "shell.skipToContent",
    ]) {
      expect(keys).toContain(key);
    }
  });
});
