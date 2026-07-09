"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";
import useSWR from "swr";

import { StatusGlowDot } from "@/components/StatusGlowDot";
import { ThemeToggle } from "@/components/ThemeToggle";
import {
  getAgentCatalogV2,
  getProviderStatusV2,
  getRuntimeConfigV2,
  getSkillCatalogV2,
  listExtensionsV2,
  listSessionsV2,
} from "@/lib/api_v2";
import { useTranslations } from "@/lib/i18n";

import { LocaleSwitcher } from "./LocaleSwitcher";
import {
  SHELL_LEGACY_NAV,
  SHELL_PRIMARY_NAV,
  resolveActiveNav,
  type NavBadgeSource,
  type ShellNavItem,
} from "./navModel";
import { useShell } from "./ShellProvider";

/** Fixed rail width in CSS pixels (prototype's 250px rail). */
const RAIL_WIDTH = 250;

/**
 * Fetch the live count backing each badge source. Each request fails softly:
 * on error the count is `undefined`, so the item renders badge-less rather than
 * showing a stale or error value. No backend endpoints are added — every count
 * comes from an existing `lib/api_v2.ts` catalog/list endpoint.
 *
 * @returns A map from badge source to its current count (or `undefined`).
 */
function useNavBadgeCounts(): Record<NavBadgeSource, number | undefined> {
  const sessions = useSWR("shell:sessions-count", () => listSessionsV2(1, 0), {
    shouldRetryOnError: false,
  });
  const agents = useSWR("shell:agents-count", () => getAgentCatalogV2(), {
    shouldRetryOnError: false,
  });
  const skills = useSWR("shell:skills-count", () => getSkillCatalogV2(), {
    shouldRetryOnError: false,
  });
  const extensions = useSWR("shell:extensions-count", () => listExtensionsV2(), {
    shouldRetryOnError: false,
  });

  return {
    sessions: sessions.data?.page.total,
    agents: agents.data?.agents.length,
    skills: skills.data?.skills.length,
    extensions: extensions.data?.page.total,
  };
}

/** Small count pill shown beside a nav label. */
function NavBadge({ count }: { count: number }): React.JSX.Element {
  return (
    <span className="ml-auto min-w-[1.25rem] rounded-ds-sm bg-ds-bg-4 px-1.5 py-px text-center font-mono text-[10.5px] font-bold text-ds-fg-2">
      {count}
    </span>
  );
}

/** One navigable rail item, or a disabled stub. */
function NavLink({
  item,
  active,
  count,
}: {
  item: ShellNavItem;
  active: boolean;
  count: number | undefined;
}): React.JSX.Element {
  const { t } = useTranslations();
  const label = (
    <>
      <span className="truncate">{t(item.labelKey)}</span>
      {typeof count === "number" ? <NavBadge count={count} /> : null}
    </>
  );

  const base =
    "flex items-center gap-3 rounded-ds-md px-3 py-2.5 text-[13.5px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent";

  if (item.disabled) {
    return (
      <span
        aria-disabled="true"
        title={t("shell.nav.extensionsTooltip")}
        className={`${base} cursor-not-allowed text-ds-fg-2 opacity-70`}
      >
        {label}
      </span>
    );
  }

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`${base} ${
        active
          ? "bg-ds-accent/10 text-ds-accent shadow-[inset_3px_0_0_hsl(var(--ds-accent))]"
          : "text-ds-fg-2 hover:bg-ds-bg-3 hover:text-ds-fg"
      }`}
    >
      {label}
    </Link>
  );
}

/**
 * The 250px sidebar rail: brand block, workspace switcher, primary and legacy
 * navigation with live count badges, a provider status card, and the theme
 * toggle. Renders as a `complementary`-free `aside` labelled "Primary" so
 * screen readers announce it as the primary navigation region.
 *
 * @returns The sidebar rail.
 */
export function SidebarRail(): React.JSX.Element {
  const pathname = usePathname() ?? "/";
  const { t } = useTranslations();
  const { activeNav, setActiveNav } = useShell();
  const counts = useNavBadgeCounts();
  const config = useSWR("shell:runtime-config-v2", getRuntimeConfigV2, {
    shouldRetryOnError: false,
  });
  const providerStatus = useSWR("shell:provider-status", getProviderStatusV2, {
    shouldRetryOnError: false,
  });

  const resolved = resolveActiveNav(pathname);

  // Keep the store's activeNav aligned with the route for downstream consumers.
  React.useEffect(() => {
    if (resolved !== activeNav) {
      setActiveNav(resolved);
    }
  }, [resolved, activeNav, setActiveNav]);

  const repositoryLabel = config.data?.config.repository.repository_label || "workspace";
  const provider = providerStatus.data?.name || config.data?.config.llm.provider || "unconfigured";
  const model = providerStatus.data?.model || config.data?.config.llm.model || "—";
  const providerTone = !providerStatus.data
    ? "neutral"
    : providerStatus.data.healthy
      ? "success"
      : providerStatus.data.configured
        ? "warn"
        : "danger";
  const providerStatusLabel = !providerStatus.data
    ? t("shell.sidebar.providerStatus.unknown")
    : providerStatus.data.healthy
      ? t("shell.sidebar.providerStatus.healthy")
      : providerStatus.data.configured
        ? t("shell.sidebar.providerStatus.unverified")
        : t("shell.sidebar.providerStatus.offline");

  return (
    <aside
      aria-label="Primary"
      style={{ width: RAIL_WIDTH }}
      className="flex h-full shrink-0 flex-col gap-5 border-r border-ds-line bg-ds-bg-2 px-4 pb-4 pt-5"
    >
      <div className="flex items-center gap-3 px-1">
        <span
          aria-hidden="true"
          className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-ds-md bg-ds-accent"
        >
          <span className="h-3 w-3 rotate-45 rounded-[4px] border-[2.4px] border-ds-accent-fg" />
        </span>
        <span className="font-serif text-[17px] font-semibold leading-tight text-ds-fg">
          {/* Brand name — deliberately not translated. */}
          {"AutoDev"}
        </span>
      </div>

      <Link
        href="/config"
        className="flex items-center gap-2.5 rounded-ds-md border border-ds-line bg-ds-bg-3 px-2.5 py-2 text-left transition-colors hover:border-ds-line-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ds-accent"
      >
        <span
          aria-hidden="true"
          className="flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-ds-sm bg-ds-accent/15 font-mono text-[11px] font-bold text-ds-accent"
        >
          {repositoryLabel.charAt(0).toLowerCase()}
        </span>
        <span className="min-w-0 flex-1 leading-tight">
          <span className="block truncate text-[13px] font-semibold text-ds-fg">
            {repositoryLabel}
          </span>
          <span className="block truncate text-[11px] text-ds-fg-2">
            {t("shell.sidebar.workspaceMeta")}
          </span>
        </span>
      </Link>

      <nav aria-label={t("shell.nav.groupWorkspace")} className="flex flex-col gap-2">
        <p className="px-2.5 text-[10.5px] font-bold uppercase tracking-[0.11em] text-ds-fg-2">
          {t("shell.nav.groupWorkspace")}
        </p>
        <div className="flex flex-col gap-0.5">
          {SHELL_PRIMARY_NAV.map((item) => (
            <NavLink
              key={item.key}
              item={item}
              active={resolved === item.key}
              count={item.badge ? counts[item.badge] : undefined}
            />
          ))}
        </div>
      </nav>

      <nav aria-label={t("shell.nav.groupLegacy")} className="flex flex-col gap-2">
        <p className="px-2.5 text-[10.5px] font-bold uppercase tracking-[0.11em] text-ds-fg-2">
          {t("shell.nav.groupLegacy")}
        </p>
        <div className="flex flex-col gap-0.5">
          {SHELL_LEGACY_NAV.map((item) => (
            <NavLink
              key={item.key}
              item={item}
              active={resolved === item.key}
              count={item.badge ? counts[item.badge] : undefined}
            />
          ))}
        </div>
      </nav>

      <div className="mt-auto flex flex-col gap-3">
        <div className="rounded-ds-lg border border-ds-line bg-ds-bg-3 p-3">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-[0.09em] text-ds-fg-2">
              {t("shell.sidebar.provider")}
            </span>
            <StatusGlowDot
              tone={providerTone}
              label={providerStatusLabel}
              labelClassName="text-[11px]"
            />
          </div>
          <div className="mt-2 flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="flex h-[26px] w-[26px] items-center justify-center rounded-ds-sm border border-ds-line bg-ds-bg-2 font-mono text-[12px] text-ds-accent"
            >
              {"◇"}
            </span>
            <span className="min-w-0 flex-1 leading-tight">
              <span className="block truncate text-[13px] font-semibold text-ds-fg">
                {provider}
              </span>
              <span className="block truncate font-mono text-[11px] text-ds-fg-2">{model}</span>
            </span>
          </div>
        </div>

        <div className="flex items-center justify-between gap-2 rounded-ds-md border border-ds-line bg-ds-bg-2 px-2 py-1.5">
          <span className="text-[12.5px] font-semibold text-ds-fg-2">
            {t("shell.sidebar.theme")}
          </span>
          <ThemeToggle />
        </div>

        <div className="flex items-center justify-between gap-2 rounded-ds-md border border-ds-line bg-ds-bg-2 px-2 py-1.5">
          <span className="text-[12.5px] font-semibold text-ds-fg-2">
            {t("shell.sidebar.language")}
          </span>
          <LocaleSwitcher />
        </div>
      </div>
    </aside>
  );
}

export default SidebarRail;
