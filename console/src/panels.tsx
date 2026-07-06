/**
 * Console panel registry - the frontend half of the fork extension seam.
 *
 * The upstream console ships a deliberately minimal UI: three core panels
 * (dashboard, audit, HIL queue). A fork that wants a vertical-specific
 * surface (a FinOps cost dashboard, a drift board, a DR-drill history)
 * does NOT edit `app.tsx` or `shell.tsx`. It appends a `ConsolePanel` to
 * `EXTRA_PANELS` (or injects one at build time) and, on the API side,
 * registers a matching `ReadPanel`
 * (`src/aiopspilot/delivery/read_api/panels.py`).
 *
 * Every panel is read-only. A panel renders data fetched through the
 * GET-only `ReadApiClient`; there is no mutating back-channel. Approvals
 * and actions still flow through ChatOps / remediation PRs, never a
 * console button (app-shape.instructions.md § Operator console).
 */

import type { ComponentType } from "preact";
import type { ReadApiClient } from "./api";
import { AuditRoute } from "./routes/audit";
import { DashboardRoute } from "./routes/dashboard";
import { HilQueueRoute } from "./routes/hil-queue";

/** Props every panel component receives. Read-only client only. */
export interface PanelProps {
  readonly client: ReadApiClient;
}

export interface ConsolePanel {
  /** Hash-route segment and stable id, e.g. `"dashboard"`, `"finops"`. */
  readonly id: string;
  /** Nav label shown in the top bar. */
  readonly label: string;
  /** The view component, rendered with {@link PanelProps}. */
  readonly component: ComponentType<PanelProps>;
}

/** The three panels the upstream console always ships. */
const DASHBOARD_PANEL: ConsolePanel = {
  id: "dashboard",
  label: "Dashboard",
  component: DashboardRoute,
};

export const CORE_PANELS: readonly ConsolePanel[] = [
  DASHBOARD_PANEL,
  { id: "audit", label: "Audit", component: AuditRoute },
  { id: "hil-queue", label: "HIL Queue", component: HilQueueRoute },
];

/**
 * Fork extension point. Empty upstream so the UI stays minimal. A fork
 * appends its panels here - see `routes/example-finops.tsx` for a
 * copy-paste-ready reference (kept out of this list on purpose):
 *
 * ```ts
 * import { ExampleFinOpsPanel } from "./routes/example-finops";
 * export const EXTRA_PANELS: readonly ConsolePanel[] = [
 *   { id: "finops", label: "Cost", component: ExampleFinOpsPanel },
 * ];
 * ```
 */
export const EXTRA_PANELS: readonly ConsolePanel[] = [];

/** All panels the running console exposes (core first, then fork panels). */
export function resolvePanels(): readonly ConsolePanel[] {
  return [...CORE_PANELS, ...EXTRA_PANELS];
}

/** The default panel id (first core panel) used when the hash is empty. */
export const DEFAULT_PANEL_ID = DASHBOARD_PANEL.id;

/** Resolve the panel for a hash-route segment, or the default panel. */
export function panelForId(id: string): ConsolePanel {
  return resolvePanels().find((p) => p.id === id) ?? DASHBOARD_PANEL;
}
