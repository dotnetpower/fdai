/**
 * Console panel registry - the frontend half of the fork extension seam.
 *
 * The upstream console ships a deliberately minimal UI grouped by
 * operator intent (Now / History / Knowledge / Safety / Overview), plus
 * standalone global utilities pinned to the bottom of the rail. A fork
 * that wants a vertical-specific surface (a FinOps cost dashboard,
 * a drift board, a DR-drill history) does NOT edit `app.tsx` or
 * `shell.tsx`. It appends a `ConsolePanel` to `EXTRA_PANELS` (or injects
 * one at build time) and, on the API side, registers a matching
 * `ReadPanel` (`src/fdai/delivery/read_api/panels.py`).
 *
 * Every panel is read-only. A panel renders data fetched through the
 * GET-only `ReadApiClient`; there is no mutating back-channel. Approvals
 * and actions still flow through ChatOps / remediation PRs, never a
 * console button (app-shape.instructions.md § Operator console).
 *
 * Groups reflect operator personas, not internal architecture layers:
 *  - `now`       - Live cockpit, waiting approvals, active attention
 *  - `history`   - Audit and post-hoc reconstruction
 *  - `knowledge` - What the system knows (ontology, agents, rules)
 *  - `safety`    - Promotion / blast-radius / what-if decisions
 *  - `overview`  - KPIs and cross-cutting summaries
 */

import type { ComponentType } from "preact";
import { lazy } from "preact/compat";
import type { ReadApiClient } from "./api";
import { t } from "./i18n";
import { DashboardRoute } from "./routes/dashboard";

const LiveRoute = lazy(async () => ({ default: (await import("./routes/live")).LiveRoute }));
const IncidentsRoute = lazy(async () => ({ default: (await import("./routes/incidents")).IncidentsRoute }));
const AgentsRoute = lazy(async () => ({ default: (await import("./routes/agents")).AgentsRoute }));
const HilQueueRoute = lazy(async () => ({ default: (await import("./routes/hil-queue")).HilQueueRoute }));
const ProvisionRoute = lazy(async () => ({ default: (await import("./routes/provision")).ProvisionRoute }));
const ProcessesRoute = lazy(async () => ({ default: (await import("./routes/processes")).ProcessesRoute }));
const AgentActivityRoute = lazy(async () => ({ default: (await import("./routes/agent-activity")).AgentActivityRoute }));
const AuditRoute = lazy(async () => ({ default: (await import("./routes/audit")).AuditRoute }));
const RuleTraceRoute = lazy(async () => ({ default: (await import("./routes/rule-trace")).RuleTraceRoute }));
const ArchitectureRoute = lazy(async () => ({ default: (await import("./routes/architecture")).ArchitectureRoute }));
const OntologyRoute = lazy(async () => ({ default: (await import("./routes/ontology")).OntologyRoute }));
const PantheonRoute = lazy(async () => ({ default: (await import("./routes/pantheon")).PantheonRoute }));
const HandoverRoute = lazy(async () => ({ default: (await import("./routes/handover")).HandoverRoute }));
const RuleCatalogRoute = lazy(async () => ({ default: (await import("./routes/rule-catalog")).RuleCatalogRoute }));
const WorkflowBuilderRoute = lazy(async () => ({ default: (await import("./routes/workflow-builder")).WorkflowBuilderRoute }));
const DocumentIngestionRoute = lazy(async () => ({ default: (await import("./routes/document-ingestion")).DocumentIngestionRoute }));
const BlastRadiusRoute = lazy(async () => ({ default: (await import("./routes/blast-radius")).BlastRadiusRoute }));
const PromotionGatesRoute = lazy(async () => ({ default: (await import("./routes/promotion-gates")).PromotionGatesRoute }));
const LlmCostRoute = lazy(async () => ({ default: (await import("./routes/llm-cost")).LlmCostRoute }));
const SettingsRoute = lazy(async () => ({ default: (await import("./routes/settings")).SettingsRoute }));

/** Props every panel component receives. Read-only client only. */
export interface PanelProps {
  readonly client: ReadApiClient;
}

/** The 5 operator-intent groups the upstream console ships. Fork
 * panels MUST pick one; the LeftRail groups by this key. Adding a new
 * group is a design decision (docs update required); do not extend
 * this union in a fork without upstreaming the change. */
export type PanelGroup = "now" | "history" | "knowledge" | "safety" | "overview";

/** Optional visual placement for panels that are global utilities rather
 * than members of an operator-intent flyout. Grouped placement is the
 * default so fork panels keep their existing behavior. */
export type PanelPlacement = "bottom";

export interface PanelGroupMeta {
  readonly id: PanelGroup;
  /** Display label on the rail, e.g. "Now". */
  readonly label: string;
  /** Short helper shown in the hover popover heading. */
  readonly hint: string;
}

export const PANEL_GROUPS: readonly PanelGroupMeta[] = [
  { id: "overview", label: t("nav.group.overview"), hint: t("nav.groupHint.overview") },
  { id: "now", label: t("nav.group.now"), hint: t("nav.groupHint.now") },
  { id: "history", label: t("nav.group.history"), hint: t("nav.groupHint.history") },
  { id: "knowledge", label: t("nav.group.knowledge"), hint: t("nav.groupHint.knowledge") },
  { id: "safety", label: t("nav.group.safety"), hint: t("nav.groupHint.safety") },
];

export interface ConsolePanel {
  /** Hash-route segment and stable id, e.g. `"dashboard"`, `"finops"`.
   * IDs are permanent - existing links and audit references depend on
   * them. Renaming an id is a breaking change; add an alias route
   * instead. */
  readonly id: string;
  /** Operator-facing label shown in the rail popover and page header.
   * May be renamed freely. */
  readonly label: string;
  /** Optional one-line description shown in the hover popover as a
   * subtitle. */
  readonly subtitle?: string;
  /** Which of the 5 operator-intent groups this panel belongs to. */
  readonly group: PanelGroup;
  /** Optional standalone rail placement. Omit to render in the group flyout. */
  readonly placement?: PanelPlacement;
  /** The view component, rendered with {@link PanelProps}. */
  readonly component: ComponentType<PanelProps>;
}

const DASHBOARD_PANEL: ConsolePanel = {
  id: "dashboard",
  label: t("nav.panel.dashboard"),
  subtitle: t("nav.panelSub.dashboard"),
  group: "overview",
  component: DashboardRoute,
};

/** The panels the upstream console always ships, grouped by intent. */
export const CORE_PANELS: readonly ConsolePanel[] = [
  // ── Now ─────────────────────────────────────────────
  {
    id: "live",
    label: t("nav.panel.live"),
    subtitle: t("nav.panelSub.live"),
    group: "now",
    component: LiveRoute,
  },
  {
    id: "incidents",
    label: t("nav.panel.incidents"),
    subtitle: t("nav.panelSub.incidents"),
    group: "now",
    component: IncidentsRoute,
  },
  {
    id: "agents",
    label: t("nav.panel.agents"),
    subtitle: t("nav.panelSub.agents"),
    group: "now",
    component: AgentsRoute,
  },
  {
    id: "hil-queue",
    label: t("nav.panel.hilQueue"),
    subtitle: t("nav.panelSub.hilQueue"),
    group: "now",
    component: HilQueueRoute,
  },
  {
    id: "provision",
    label: t("nav.panel.provision"),
    subtitle: t("nav.panelSub.provision"),
    group: "now",
    component: ProvisionRoute,
  },
  {
    id: "processes",
    label: t("nav.panel.processes"),
    subtitle: t("nav.panelSub.processes"),
    group: "now",
    component: ProcessesRoute,
  },
  // ── History ─────────────────────────────────────────────────────────
  {
    id: "agent-activity",
    label: t("nav.panel.agentActivity"),
    subtitle: t("nav.panelSub.agentActivity"),
    group: "history",
    component: AgentActivityRoute,
  },
  {
    id: "audit",
    label: t("nav.panel.audit"),
    subtitle: t("nav.panelSub.audit"),
    group: "history",
    component: AuditRoute,
  },
  {
    id: "trace",
    label: t("nav.panel.trace"),
    subtitle: t("nav.panelSub.trace"),
    group: "history",
    component: RuleTraceRoute,
  },
  // ── Knowledge ───────────────────────────────────────────────────────
  {
    id: "architecture",
    label: t("nav.panel.architecture"),
    subtitle: t("nav.panelSub.architecture"),
    group: "knowledge",
    component: ArchitectureRoute,
  },
  {
    id: "ontology",
    label: t("nav.panel.ontology"),
    subtitle: t("nav.panelSub.ontology"),
    group: "knowledge",
    component: OntologyRoute,
  },
  {
    id: "pantheon",
    label: t("nav.panel.pantheon"),
    subtitle: t("nav.panelSub.pantheon"),
    group: "knowledge",
    component: PantheonRoute,
  },
  {
    id: "handover",
    label: t("nav.panel.handover"),
    subtitle: t("nav.panelSub.handover"),
    group: "knowledge",
    component: HandoverRoute,
  },
  {
    id: "rules",
    label: t("nav.panel.rules"),
    subtitle: t("nav.panelSub.rules"),
    group: "knowledge",
    component: RuleCatalogRoute,
  },
  {
    id: "workflow-builder",
    label: t("nav.panel.workflowBuilder"),
    subtitle: t("nav.panelSub.workflowBuilder"),
    group: "knowledge",
    component: WorkflowBuilderRoute,
  },
  {
    id: "documents",
    label: t("nav.panel.documents"),
    subtitle: t("nav.panelSub.documents"),
    group: "knowledge",
    component: DocumentIngestionRoute,
  },
  // ── Safety ──────────────────────────────────────────────────────────
  {
    id: "blast-radius",
    label: t("nav.panel.blastRadius"),
    subtitle: t("nav.panelSub.blastRadius"),
    group: "safety",
    component: BlastRadiusRoute,
  },
  {
    id: "promotion-gates",
    label: t("nav.panel.promotionGates"),
    subtitle: t("nav.panelSub.promotionGates"),
    group: "safety",
    component: PromotionGatesRoute,
  },
  // ── Overview ────────────────────────────────────────────────────────
  DASHBOARD_PANEL,
  {
    id: "llm-cost",
    label: t("nav.panel.llmCost"),
    subtitle: t("nav.panelSub.llmCost"),
    group: "overview",
    component: LlmCostRoute,
  },
  {
    id: "settings",
    label: t("nav.panel.settings"),
    subtitle: t("nav.panelSub.settings"),
    group: "overview",
    placement: "bottom",
    component: SettingsRoute,
  },
];

/**
 * Fork extension point. Empty upstream so the UI stays minimal. A fork
 * appends its panels here - see `routes/example-finops.tsx` for a
 * copy-paste-ready reference (kept out of this list on purpose):
 *
 * ```ts
 * import { ExampleFinOpsPanel } from "./routes/example-finops";
 * export const EXTRA_PANELS: readonly ConsolePanel[] = [
 *   { id: "finops", label: "Cost", group: "overview", component: ExampleFinOpsPanel },
 * ];
 * ```
 */
export const EXTRA_PANELS: readonly ConsolePanel[] = [];

/** All panels the running console exposes (core first, then fork panels). */
export function resolvePanels(): readonly ConsolePanel[] {
  return [...CORE_PANELS, ...EXTRA_PANELS];
}

/** Panels filtered to a single group, in registration order. */
export function panelsInGroup(group: PanelGroup): readonly ConsolePanel[] {
  return resolvePanels().filter((p) => p.group === group && p.placement === undefined);
}

/** Standalone global utilities pinned to the bottom of the left rail. */
export function bottomRailPanels(): readonly ConsolePanel[] {
  return resolvePanels().filter((p) => p.placement === "bottom");
}

/** The default panel id: Overview - the approver's landing (health /
 * risk / cost at a glance). It is the first group on the rail, so the
 * landing and the rail order agree. */
export const DEFAULT_PANEL_ID = "dashboard";

/** Resolve the panel for a hash-route segment, or the default panel. */
export function panelForId(id: string): ConsolePanel {
  return resolvePanels().find((p) => p.id === id) ?? DASHBOARD_PANEL;
}
