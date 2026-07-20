/**
 * Console panel registry - the frontend half of the fork extension seam.
 *
 * The upstream console ships a deliberately minimal UI grouped by
 * operator domain (Overview / Operations / Agents / Governance / Evidence), plus
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
 * Groups reflect stable operator domains, not internal architecture layers:
 *  - `overview`   - KPIs and cross-cutting summaries
 *  - `operations` - Live operations and operator attention
 *  - `agents`     - Agent organization and runtime activity
 *  - `governance` - Rules, ontology, scope, and safety controls
 *  - `evidence`   - Audit, RCA, traces, reports, and governed sources
 */

import type { ComponentType } from "preact";
import { lazy } from "preact/compat";
import type { ReadApiClient } from "./api";
import type { AuthContext } from "./auth";
import { t } from "./i18n";

const DashboardRoute = lazy(async () => ({ default: (await import("./routes/dashboard")).DashboardRoute }));
const LiveRoute = lazy(async () => ({ default: (await import("./routes/live")).LiveRoute }));
const IncidentsRoute = lazy(async () => ({ default: (await import("./routes/incidents")).IncidentsRoute }));
const AgentsRoute = lazy(async () => ({ default: (await import("./routes/agents")).AgentsRoute }));
const HilQueueRoute = lazy(async () => ({ default: (await import("./routes/hil-queue")).HilQueueRoute }));
const ProvisionRoute = lazy(async () => ({ default: (await import("./routes/provision")).ProvisionRoute }));
const ProcessesRoute = lazy(async () => ({ default: (await import("./routes/processes")).ProcessesRoute }));
const WorkflowAppsRoute = lazy(async () => ({ default: (await import("./routes/workflow-apps")).WorkflowAppsRoute }));
const ReportsRoute = lazy(async () => ({ default: (await import("./routes/reports")).ReportsRoute }));
const AgentActivityRoute = lazy(async () => ({ default: (await import("./routes/agent-activity")).AgentActivityRoute }));
const AuditRoute = lazy(async () => ({ default: (await import("./routes/audit")).AuditRoute }));
const BrowserEvidenceRoute = lazy(async () => ({ default: (await import("./routes/browser-evidence")).BrowserEvidenceRoute }));
const ConversationSearchRoute = lazy(async () => ({ default: (await import("./routes/conversation-search")).ConversationSearchRoute }));
const RuleTraceRoute = lazy(async () => ({ default: (await import("./routes/rule-trace")).RuleTraceRoute }));
const RcaRoute = lazy(async () => ({ default: (await import("./routes/rca")).RcaRoute }));
const ArchitectureRoute = lazy(async () => ({ default: (await import("./routes/architecture")).ArchitectureRoute }));
const OntologyRoute = lazy(async () => ({ default: (await import("./routes/ontology")).OntologyRoute }));
const PantheonRoute = lazy(async () => ({ default: (await import("./routes/pantheon")).PantheonRoute }));
const HandoverRoute = lazy(async () => ({ default: (await import("./routes/handover")).HandoverRoute }));
const RuleCatalogRoute = lazy(async () => ({ default: (await import("./routes/rule-catalog")).RuleCatalogRoute }));
const WorkflowBuilderRoute = lazy(async () => ({ default: (await import("./routes/workflow-builder")).WorkflowBuilderRoute }));
const DocumentIngestionRoute = lazy(async () => ({ default: (await import("./routes/document-ingestion")).DocumentIngestionRoute }));
const BlastRadiusRoute = lazy(async () => ({ default: (await import("./routes/blast-radius")).BlastRadiusRoute }));
const PromotionGatesRoute = lazy(async () => ({ default: (await import("./routes/promotion-gates")).PromotionGatesRoute }));
const ContextSelectionComparisonsRoute = lazy(async () => ({ default: (await import("./routes/context-selection-comparisons")).ContextSelectionComparisonsRoute }));
const ScopeRoute = lazy(async () => ({ default: (await import("./routes/scope")).ScopeRoute }));
const LlmCostRoute = lazy(async () => ({ default: (await import("./routes/llm-cost")).LlmCostRoute }));
const CapabilitiesRoute = lazy(async () => ({ default: (await import("./routes/capabilities")).CapabilitiesRoute }));
const SkillsRoute = lazy(async () => ({ default: (await import("./routes/skills")).SkillsRoute }));
const OnboardingRoute = lazy(async () => ({ default: (await import("./routes/onboarding")).OnboardingRoute }));
const SchedulerRunsRoute = lazy(async () => ({ default: (await import("./routes/scheduler-runs")).SchedulerRunsRoute }));
const AutomationBlueprintsRoute = lazy(async () => ({ default: (await import("./routes/automation-blueprints")).AutomationBlueprintsRoute }));
const ScheduledContinuationsRoute = lazy(async () => ({ default: (await import("./routes/scheduled-continuations")).ScheduledContinuationsRoute }));
const ConversationDeliveryRoute = lazy(async () => ({ default: (await import("./routes/conversation-delivery")).ConversationDeliveryRoute }));
const OperatingOutcomesRoute = lazy(async () => ({ default: (await import("./routes/analytics-hubs")).OperatingOutcomesRoute }));
const ControlAssuranceRoute = lazy(async () => ({ default: (await import("./routes/analytics-hubs")).ControlAssuranceRoute }));
const VerticalOutcomesRoute = lazy(async () => ({ default: (await import("./routes/analytics-hubs")).VerticalOutcomesRoute }));
const TrustRoutingRoute = lazy(async () => ({ default: (await import("./routes/analytics-hubs")).TrustRoutingRoute }));
const SettingsGeneralRoute = lazy(async () => ({ default: (await import("./routes/settings")).SettingsGeneralRoute }));
const SettingsModelsRoute = lazy(async () => ({ default: (await import("./routes/settings-models")).SettingsModelsRoute }));
const OperatorMemoryRoute = lazy(async () => ({ default: (await import("./routes/operator-memory")).OperatorMemoryRoute }));
const SettingsIamRoute = lazy(async () => ({ default: (await import("./routes/settings-iam")).SettingsIamRoute }));
const SettingsIntegrationsRoute = lazy(async () => ({ default: (await import("./routes/settings-system")).SettingsIntegrationsRoute }));
const SettingsDiagnosticsRoute = lazy(async () => ({ default: (await import("./routes/settings-system")).SettingsDiagnosticsRoute }));
const LabsRoute = lazy(async () => ({ default: (await import("./routes/labs")).LabsRoute }));

/** Props every panel component receives. Read-only client only. */
export interface PanelProps {
  readonly client: ReadApiClient;
  readonly auth: AuthContext;
}

/** The five stable production navigation domains plus dev-only Labs.
 * Fork panels MUST pick one; the Explorer groups by this key. Adding a
 * new group is a design decision (docs update required); do not extend
 * this union in a fork without upstreaming the change. */
export type PanelGroup = "overview" | "operations" | "agents" | "governance" | "evidence" | "labs" | "settings";

/** Optional visual placement for panels that are global utilities rather
 * than members of an Explorer domain. Grouped placement is the
 * default so fork panels keep their existing behavior. */
export type PanelPlacement = "bottom";

export interface PanelGroupMeta {
  readonly id: PanelGroup;
  /** Display label for the Activity Bar tooltip and Explorer heading. */
  readonly label: string;
  /** Short helper shown beneath the Explorer heading. */
  readonly hint: string;
  readonly placement?: "bottom";
  readonly devOnly?: boolean;
}

export const PANEL_GROUPS: readonly PanelGroupMeta[] = [
  { id: "overview", label: t("nav.group.overview"), hint: t("nav.groupHint.overview") },
  { id: "operations", label: t("nav.group.operations"), hint: t("nav.groupHint.operations") },
  { id: "agents", label: t("nav.group.agents"), hint: t("nav.groupHint.agents") },
  { id: "governance", label: t("nav.group.governance"), hint: t("nav.groupHint.governance") },
  { id: "evidence", label: t("nav.group.evidence"), hint: t("nav.groupHint.evidence") },
  {
    id: "labs",
    label: t("nav.group.labs"),
    hint: t("nav.groupHint.labs"),
    placement: "bottom",
    devOnly: true,
  },
  {
    id: "settings",
    label: t("nav.group.settings"),
    hint: t("nav.groupHint.settings"),
    placement: "bottom",
  },
];

export interface ConsolePanel {
  /** Hash-route segment and stable id, e.g. `"dashboard"`, `"finops"`.
   * IDs are permanent - existing links and audit references depend on
   * them. Renaming an id is a breaking change; add an alias route
   * instead. */
  readonly id: string;
  /** Operator-facing label shown in the Explorer and page header.
   * May be renamed freely. */
  readonly label: string;
  /** Optional one-line panel description. */
  readonly subtitle?: string;
  /** Which stable navigation domain (or dev-only Labs) this panel belongs to. */
  readonly group: PanelGroup;
  /** Optional standalone Activity Bar placement. Omit to render in the Explorer. */
  readonly placement?: PanelPlacement;
  /** The view component, rendered with {@link PanelProps}. */
  readonly component: ComponentType<PanelProps>;
}

const DASHBOARD_PANEL: ConsolePanel = {
  id: "dashboard",
  label: t("nav.panel.dashboard"),
  subtitle: t("overview.subtitle"),
  group: "overview",
  component: DashboardRoute,
};

/** The panels the upstream console always ships, grouped by intent. */
export const CORE_PANELS: readonly ConsolePanel[] = [
  // Operations
  {
    id: "live",
    label: t("nav.panel.live"),
    subtitle: t("nav.panelSub.live"),
    group: "operations",
    component: LiveRoute,
  },
  {
    id: "incidents",
    label: t("nav.panel.incidents"),
    subtitle: t("nav.panelSub.incidents"),
    group: "operations",
    component: IncidentsRoute,
  },
  {
    id: "agents",
    label: t("nav.panel.agents"),
    subtitle: t("nav.panelSub.agents"),
    group: "agents",
    component: AgentsRoute,
  },
  {
    id: "hil-queue",
    label: t("nav.panel.hilQueue"),
    subtitle: t("nav.panelSub.hilQueue"),
    group: "operations",
    component: HilQueueRoute,
  },
  {
    id: "provision",
    label: t("nav.panel.provision"),
    subtitle: t("nav.panelSub.provision"),
    group: "operations",
    component: ProvisionRoute,
  },
  {
    id: "onboarding",
    label: t("nav.panel.onboarding"),
    subtitle: t("nav.panelSub.onboarding"),
    group: "operations",
    component: OnboardingRoute,
  },
  {
    id: "processes",
    label: t("nav.panel.processes"),
    subtitle: t("nav.panelSub.processes"),
    group: "operations",
    component: ProcessesRoute,
  },
  {
    id: "workflow-apps",
    label: t("nav.panel.workflowApps"),
    subtitle: t("nav.panelSub.workflowApps"),
    group: "operations",
    component: WorkflowAppsRoute,
  },
  {
    id: "scheduler-runs",
    label: t("nav.panel.schedulerRuns"),
    subtitle: t("nav.panelSub.schedulerRuns"),
    group: "operations",
    component: SchedulerRunsRoute,
  },
  {
    id: "automation-blueprints",
    label: t("nav.panel.automationBlueprints"),
    subtitle: t("nav.panelSub.automationBlueprints"),
    group: "operations",
    component: AutomationBlueprintsRoute,
  },
  {
    id: "scheduled-continuations",
    label: t("nav.panel.scheduledContinuations"),
    subtitle: t("nav.panelSub.scheduledContinuations"),
    group: "operations",
    component: ScheduledContinuationsRoute,
  },
  {
    id: "conversation-delivery",
    label: t("nav.panel.conversationDelivery"),
    subtitle: t("nav.panelSub.conversationDelivery"),
    group: "operations",
    component: ConversationDeliveryRoute,
  },
  // Agents and evidence
  {
    id: "audit",
    label: t("nav.panel.audit"),
    subtitle: t("nav.panelSub.audit"),
    group: "evidence",
    component: AuditRoute,
  },
  {
    id: "browser-evidence",
    label: t("nav.panel.browserEvidence"),
    subtitle: t("nav.panelSub.browserEvidence"),
    group: "evidence",
    component: BrowserEvidenceRoute,
  },
  {
    id: "conversation-search",
    label: t("nav.panel.conversationSearch"),
    subtitle: t("nav.panelSub.conversationSearch"),
    group: "evidence",
    component: ConversationSearchRoute,
  },
  {
    id: "reports",
    label: t("nav.panel.reports"),
    subtitle: t("nav.panelSub.reports"),
    group: "evidence",
    component: ReportsRoute,
  },
  {
    id: "trace",
    label: t("nav.panel.trace"),
    subtitle: t("nav.panelSub.trace"),
    group: "evidence",
    component: RuleTraceRoute,
  },
  {
    id: "rca",
    label: t("nav.panel.rca"),
    subtitle: t("nav.panelSub.rca"),
    group: "evidence",
    component: RcaRoute,
  },
  // Governance and evidence sources
  {
    id: "architecture",
    label: t("nav.panel.architecture"),
    subtitle: t("nav.panelSub.architecture"),
    group: "governance",
    component: ArchitectureRoute,
  },
  {
    id: "ontology",
    label: t("nav.panel.ontology"),
    subtitle: t("nav.panelSub.ontology"),
    group: "governance",
    component: OntologyRoute,
  },
  {
    id: "pantheon",
    label: t("nav.panel.pantheon"),
    subtitle: t("nav.panelSub.pantheon"),
    group: "agents",
    component: PantheonRoute,
  },
  {
    id: "agent-activity",
    label: t("nav.panel.agentActivity"),
    subtitle: t("nav.panelSub.agentActivity"),
    group: "agents",
    component: AgentActivityRoute,
  },
  {
    id: "handover",
    label: t("nav.panel.handover"),
    subtitle: t("nav.panelSub.handover"),
    group: "agents",
    component: HandoverRoute,
  },
  {
    id: "rules",
    label: t("nav.panel.rules"),
    subtitle: t("nav.panelSub.rules"),
    group: "governance",
    component: RuleCatalogRoute,
  },
  {
    id: "workflow-builder",
    label: t("nav.panel.workflowBuilder"),
    subtitle: t("nav.panelSub.workflowBuilder"),
    group: "governance",
    component: WorkflowBuilderRoute,
  },
  {
    id: "capabilities",
    label: t("nav.panel.capabilities"),
    subtitle: t("nav.panelSub.capabilities"),
    group: "governance",
    component: CapabilitiesRoute,
  },
  {
    id: "skills",
    label: t("nav.panel.skills"),
    subtitle: t("nav.panelSub.skills"),
    group: "governance",
    component: SkillsRoute,
  },
  {
    id: "documents",
    label: t("nav.panel.documents"),
    subtitle: t("nav.panelSub.documents"),
    group: "evidence",
    component: DocumentIngestionRoute,
  },
  // Governance controls
  {
    id: "blast-radius",
    label: t("nav.panel.blastRadius"),
    subtitle: t("nav.panelSub.blastRadius"),
    group: "governance",
    component: BlastRadiusRoute,
  },
  {
    id: "promotion-gates",
    label: t("nav.panel.promotionGates"),
    subtitle: t("nav.panelSub.promotionGates"),
    group: "governance",
    component: PromotionGatesRoute,
  },
  {
    id: "context-selection-comparisons",
    label: t("nav.panel.contextSelectionComparisons"),
    subtitle: t("nav.panelSub.contextSelectionComparisons"),
    group: "governance",
    component: ContextSelectionComparisonsRoute,
  },
  {
    id: "scope",
    label: t("nav.panel.scope"),
    subtitle: t("nav.panelSub.scope"),
    group: "governance",
    component: ScopeRoute,
  },
  // ── Overview ────────────────────────────────────────────────────────
  DASHBOARD_PANEL,
  {
    id: "operating-outcomes",
    label: t("nav.panel.operatingOutcomes"),
    subtitle: t("nav.panelSub.operatingOutcomes"),
    group: "overview",
    component: OperatingOutcomesRoute,
  },
  {
    id: "control-assurance",
    label: t("nav.panel.controlAssurance"),
    subtitle: t("nav.panelSub.controlAssurance"),
    group: "overview",
    component: ControlAssuranceRoute,
  },
  {
    id: "verticals",
    label: t("nav.panel.verticalOutcomes"),
    subtitle: t("nav.panelSub.verticalOutcomes"),
    group: "overview",
    component: VerticalOutcomesRoute,
  },
  {
    id: "trust-routing",
    label: t("nav.panel.trustRouting"),
    subtitle: t("nav.panelSub.trustRouting"),
    group: "overview",
    component: TrustRoutingRoute,
  },
  {
    id: "llm-cost",
    label: t("nav.panel.llmCost"),
    subtitle: t("nav.panelSub.llmCost"),
    group: "overview",
    component: LlmCostRoute,
  },
  {
    id: "labs",
    label: t("nav.panel.labs"),
    subtitle: t("nav.panelSub.labs"),
    group: "labs",
    component: LabsRoute,
  },
  {
    id: "settings-general",
    label: t("nav.panel.settingsGeneral"),
    subtitle: t("nav.panelSub.settingsGeneral"),
    group: "settings",
    component: SettingsGeneralRoute,
  },
  {
    id: "settings-models",
    label: t("nav.panel.settingsModels"),
    subtitle: t("nav.panelSub.settingsModels"),
    group: "settings",
    component: SettingsModelsRoute,
  },
  {
    id: "settings-memory",
    label: t("nav.panel.operatorMemory"),
    subtitle: t("nav.panelSub.operatorMemory"),
    group: "settings",
    component: OperatorMemoryRoute,
  },
  {
    id: "settings-iam",
    label: t("nav.panel.settingsIam"),
    subtitle: t("nav.panelSub.settingsIam"),
    group: "settings",
    component: SettingsIamRoute,
  },
  {
    id: "settings-integrations",
    label: t("nav.panel.settingsIntegrations"),
    subtitle: t("nav.panelSub.settingsIntegrations"),
    group: "settings",
    component: SettingsIntegrationsRoute,
  },
  {
    id: "settings-diagnostics",
    label: t("nav.panel.settingsDiagnostics"),
    subtitle: t("nav.panelSub.settingsDiagnostics"),
    group: "settings",
    component: SettingsDiagnosticsRoute,
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
  return validatePanelRegistry([...CORE_PANELS, ...EXTRA_PANELS]);
}

export function validatePanelRegistry(panels: readonly ConsolePanel[]): readonly ConsolePanel[] {
  const ids = new Set<string>();
  const groupIds = new Set(PANEL_GROUPS.map((group) => group.id));
  for (const panel of panels) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(panel.id)) {
      throw new Error(`Console panel id MUST be lowercase kebab-case: ${panel.id}`);
    }
    if (ids.has(panel.id)) throw new Error(`Duplicate console panel id: ${panel.id}`);
    if (!panel.label.trim()) throw new Error(`Console panel label MUST NOT be empty: ${panel.id}`);
    if (!groupIds.has(panel.group)) throw new Error(`Unknown console panel group: ${panel.group}`);
    ids.add(panel.id);
  }
  return panels;
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
