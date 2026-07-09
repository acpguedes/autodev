import type { Route } from "next";
import { redirect } from "next/navigation";

/**
 * Legacy `/agents` route. Agents were unified into the Extensions hub in
 * E17-S5 (ADR-012 §5); this permanently redirects to `/extensions` instead
 * of rendering its own screen.
 *
 * @returns Never returns; always redirects.
 */
export default function AgentsPage(): never {
  redirect("/extensions" as Route);
}
