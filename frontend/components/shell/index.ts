// Public surface of the Execution Control Center shell (E15-S2).

export { AppShell } from "./AppShell";
export { ContextHeader } from "./ContextHeader";
export { ExecutionPanelSlot } from "./ExecutionPanelSlot";
export { SidebarRail } from "./SidebarRail";
export {
  ShellProvider,
  ShellHeaderPortal,
  useShell,
  useShellHeader,
  useExecutionPanel,
  type ShellContextValue,
  type ShellHeaderContent,
  type ShellHeaderOptions,
} from "./ShellProvider";
export {
  SHELL_PRIMARY_NAV,
  SHELL_LEGACY_NAV,
  resolveActiveNav,
  type ShellNavItem,
  type NavBadgeSource,
} from "./navModel";
