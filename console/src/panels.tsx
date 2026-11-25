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
 * `ReadPanel` (`services/core-control-plane/src/fdai/delivery/operator_api/panels.py`).
 *
 * Every panel is read-only. A panel renders data fetched through the
 * GET-only `OperatorApiClient`; there is no mutating back-channel. Approvals
 * and actions still flow through ChatOps / remediation PRs, never a
 * console button (app-shape.instructions.md § Operator console).
 *
 * Groups reflect stable operator domains, not internal architecture layers:
 *  - `overview`   - KPIs, outcomes, and cost summaries
 *  - `operations` - Live operations, SRE/security risks, approvals, and automation runs
 *  - `agents`     - Agent fleet, roles, skills, and runtime activity
 *  - `governance` - Rules, ontology, safety controls, and governed knowledge
 *  - `evidence`   - Audit, trace, RCA, and reports
 */

import type { ComponentType } from "preact";
import { lazy } from "preact/compat";
import type { OperatorApiClient } from "./api";
import type { AuthContext } from "./auth";
import type { ConsoleDataMode } from "./console-data-mode";
import { t } from "./i18n";
import { alertQualityNavText } from "./routes/i18n/alert-quality-nav";
import { filterPanelsByStencil } from "./stencil-panels";

function lazyRoute<K extends string, M extends Record<K, ComponentType<PanelProps>>>(
  load: () => Promise<M>,
  name: K,
) {
  return lazy(async () => ({ default: (await load())[name] }));
}

const DashboardRoute = lazyRoute(() => import("./routes/dashboard"), "DashboardRoute");
const DashboardV2Route = lazy(() => import("./routes/dashboard-v2"));
const LiveRoute = lazyRoute(() => import("./routes/live"), "LiveRoute");
const GpuMonitoringRoute = lazyRoute(
  () => import("./routes/gpu-monitoring"),
  "GpuMonitoringRoute",
);
const IncidentsRoute = lazyRoute(() => import("./routes/incidents"), "IncidentsRoute");
const AgentsRoute = lazyRoute(() => import("./routes/agents"), "AgentsRoute");
const HilQueueRoute = lazyRoute(() => import("./routes/hil-queue"), "HilQueueRoute");
const ProvisionRoute = lazyRoute(() => import("./routes/provision"), "ProvisionRoute");
const ProcessesRoute = lazyRoute(() => import("./routes/processes"), "ProcessesRoute");
const WorkflowAppsRoute = lazyRoute(() => import("./routes/workflow-apps"), "WorkflowAppsRoute");
const ReportsRoute = lazyRoute(() => import("./routes/reports"), "ReportsRoute");
const AgentActivityRoute = lazyRoute(
  () => import("./routes/agent-activity"),
  "AgentActivityRoute",
);
const AuditRoute = lazyRoute(() => import("./routes/audit"), "AuditRoute");
const BrowserEvidenceRoute = lazyRoute(
  () => import("./routes/browser-evidence"),
  "BrowserEvidenceRoute",
);
const ForecastLearningRoute = lazyRoute(
  () => import("./routes/forecast-learning"),
  "ForecastLearningRoute",
);
const ConversationSearchRoute = lazyRoute(
  () => import("./routes/conversation-search"),
  "ConversationSearchRoute",
);
const RuleTraceRoute = lazyRoute(() => import("./routes/rule-trace"), "RuleTraceRoute");
const RcaRoute = lazyRoute(() => import("./routes/rca"), "RcaRoute");
const ArchitectureRoute = lazyRoute(
  () => import("./routes/architecture"),
  "ArchitectureRoute",
);
const OntologyRoute = lazyRoute(() => import("./routes/ontology"), "OntologyRoute");
const HandoverRoute = lazyRoute(() => import("./routes/handover"), "HandoverRoute");
const RuleCatalogRoute = lazyRoute(
  () => import("./routes/rule-catalog"),
  "RuleCatalogRoute",
);
const WorkflowBuilderRoute = lazyRoute(
  () => import("./routes/workflow-builder"),
  "WorkflowBuilderRoute",
);
const KnowledgeDomainRoute = lazy(() => import("./routes/knowledge-domain"));
const BlastRadiusRoute = lazyRoute(
  () => import("./routes/blast-radius"),
  "BlastRadiusRoute",
);
const PromotionGatesRoute = lazyRoute(
  () => import("./routes/promotion-gates"),
  "PromotionGatesRoute",
);
const ContextSelectionComparisonsRoute = lazyRoute(
  () => import("./routes/context-selection-comparisons"),
  "ContextSelectionComparisonsRoute",
);
const ScopeRoute = lazyRoute(() => import("./routes/scope"), "ScopeRoute");
const LlmCostRoute = lazyRoute(() => import("./routes/llm-cost"), "LlmCostRoute");
const CostGovernanceRoute = lazyRoute(
  () => import("./routes/cost-governance"),
  "CostGovernanceRoute",
);
const AksCommerceRoute = lazyRoute(
  () => import("./routes/aks-commerce"),
  "AksCommerceRoute",
);
const CapabilitiesRoute = lazyRoute(
  () => import("./routes/capabilities"),
  "CapabilitiesRoute",
);
const SkillsRoute = lazyRoute(() => import("./routes/skills"), "SkillsRoute");
const OnboardingRoute = lazyRoute(() => import("./routes/onboarding"), "OnboardingRoute");
const EnvironmentDeploymentRoute = lazyRoute(
  () => import("./routes/environment-deployment"),
  "EnvironmentDeploymentRoute",
);
const DetectionReadinessRoute = lazyRoute(
  () => import("./routes/detection-readiness"),
  "DetectionReadinessRoute",
);
const AlertQualityRoute = lazyRoute(
  () => import("./routes/alert-quality"),
  "AlertQualityRoute",
);
const ConfigurationBaselinesRoute = lazyRoute(
  () => import("./routes/configuration-baselines"),
  "ConfigurationBaselinesRoute",
);
const SchedulerRunsRoute = lazyRoute(
  () => import("./routes/scheduler-runs"),
  "SchedulerRunsRoute",
);
const BackgroundTasksRoute = lazyRoute(
  () => import("./routes/background-tasks"),
  "BackgroundTasksRoute",
);
const AutomationBlueprintsRoute = lazyRoute(
  () => import("./routes/automation-blueprints"),
  "AutomationBlueprintsRoute",
);
const ScheduledContinuationsRoute = lazyRoute(
  () => import("./routes/scheduled-continuations"),
  "ScheduledContinuationsRoute",
);
const ConversationDeliveryRoute = lazyRoute(
  () => import("./routes/conversation-delivery"),
  "ConversationDeliveryRoute",
);
const ConversationAssuranceRoute = lazyRoute(
  () => import("./routes/conversation-assurance"),
  "ConversationAssuranceRoute",
);
const AssuranceTwinRoute = lazyRoute(
  () => import("./routes/assurance-twin"),
  "AssuranceTwinRoute",
);
const CodeSecurityRoute = lazyRoute(
  () => import("./routes/code-security"),
  "CodeSecurityRoute",
);
const loadAnalyticsHubs = () => import("./routes/analytics-hubs");
const OperatingOutcomesRoute = lazyRoute(loadAnalyticsHubs, "OperatingOutcomesRoute");
const ControlAssuranceRoute = lazyRoute(loadAnalyticsHubs, "ControlAssuranceRoute");
const VerticalOutcomesRoute = lazyRoute(loadAnalyticsHubs, "VerticalOutcomesRoute");
const TrustRoutingRoute = lazyRoute(loadAnalyticsHubs, "TrustRoutingRoute");
const SettingsGeneralRoute = lazyRoute(
  () => import("./routes/settings"),
  "SettingsGeneralRoute",
);
const SettingsModelsRoute = lazyRoute(
  () => import("./routes/settings-models"),
  "SettingsModelsRoute",
);
const SettingsRuntimeRoute = lazyRoute(
  () => import("./routes/settings-runtime"),
  "SettingsRuntimeRoute",
);
const OperatorMemoryRoute = lazyRoute(
  () => import("./routes/operator-memory"),
  "OperatorMemoryRoute",
);
const SettingsIamRoute = lazyRoute(
  () => import("./routes/settings-iam"),
  "SettingsIamRoute",
);
const loadSettingsSystem = () => import("./routes/settings-system");
const SettingsIntegrationsRoute = lazyRoute(loadSettingsSystem, "SettingsIntegrationsRoute");
const SettingsDiagnosticsRoute = lazyRoute(loadSettingsSystem, "SettingsDiagnosticsRoute");
const LabsRoute = lazyRoute(() => import("./routes/labs"), "LabsRoute");

/** Props every panel component receives. Read-only client only. */
export interface PanelProps {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
  readonly dataMode: ConsoleDataMode;
}

/** The five stable production navigation domains plus dev-only Labs and Settings.
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
  /** Optional combined label used in primary navigation when this panel
   * represents a multi-tab hub while preserving its own tab label. */
  readonly hubLabel?: string;
  /** Optional parent hub representative panel id. Child panels stay
   * routable on their permanent URLs and render inside the shared hub tabs. */
  readonly hubRootId?: string;
  /** Optional one-line panel description. */
  readonly subtitle?: string;
  /** Which stable navigation domain (or dev-only Labs) this panel belongs to. */
  readonly group: PanelGroup;
  /** Optional standalone Activity Bar placement. Omit to render in the Explorer. */
  readonly placement?: PanelPlacement;
  /** Preserve a stable route without showing it as a primary navigation destination. */
  readonly hiddenFromNavigation?: boolean;
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

function knowledgeSourcePanel(id: string, label: string, primary = false): ConsolePanel {
  return primary
    ? {
        id,
        label,
        hubLabel: t("nav.hub.knowledge"),
        subtitle: t("nav.panelSub.knowledge"),
        group: "governance",
        component: KnowledgeDomainRoute,
      }
    : {
        id,
        label,
        hubRootId: "knowledge",
        group: "governance",
        hiddenFromNavigation: true,
        component: KnowledgeDomainRoute,
      };
}

/** The panels the upstream console always ships, grouped by intent. */
export const CORE_PANELS: readonly ConsolePanel[] = [
  // ── Overview ────────────────────────────────────────────────────────
  DASHBOARD_PANEL,
  {
    id: "dashboard-v2",
    label: t("nav.panel.dashboard"),
    group: "overview",
    hiddenFromNavigation: true,
    component: DashboardV2Route,
  },
  {
    id: "operating-outcomes",
    label: t("nav.panel.operatingOutcomes"),
    hubLabel: t("nav.hub.outcomes"),
    subtitle: t("nav.panelSub.operatingOutcomes"),
    group: "overview",
    component: OperatingOutcomesRoute,
  },
  {
    id: "control-assurance",
    label: t("nav.panel.controlAssurance"),
    subtitle: t("nav.panelSub.controlAssurance"),
    group: "overview",
    hubRootId: "operating-outcomes",
    hiddenFromNavigation: true,
    component: ControlAssuranceRoute,
  },
  {
    id: "verticals",
    label: t("nav.panel.verticalOutcomes"),
    subtitle: t("nav.panelSub.verticalOutcomes"),
    group: "overview",
    hubRootId: "operating-outcomes",
    hiddenFromNavigation: true,
    component: VerticalOutcomesRoute,
  },
  {
    id: "cost-governance",
    label: t("nav.panel.costGovernance"),
    hubLabel: t("nav.hub.costGovernance"),
    subtitle: t("nav.panelSub.costGovernance"),
    group: "overview",
    component: CostGovernanceRoute,
  },
  {
    id: "llm-cost",
    label: t("nav.panel.llmCost"),
    subtitle: t("nav.panelSub.llmCost"),
    group: "overview",
    hubRootId: "cost-governance",
    hiddenFromNavigation: true,
    component: LlmCostRoute,
  },
  // ── Operations ──────────────────────────────────────────────────────
  {
    id: "live",
    label: t("nav.panel.live"),
    hubLabel: t("nav.hub.liveOperations"),
    subtitle: t("nav.panelSub.live"),
    group: "operations",
    component: LiveRoute,
  },
  {
    id: "gpu",
    label: t("nav.panel.gpu"),
    subtitle: t("nav.groupHint.operations"),
    group: "operations",
    hubRootId: "live",
    hiddenFromNavigation: true,
    component: GpuMonitoringRoute,
  },
  {
    id: "incidents",
    label: t("nav.panel.incidents"),
    subtitle: t("nav.panelSub.incidents"),
    group: "operations",
    component: IncidentsRoute,
  },
  {
    id: "code-security",
    label: t("nav.panel.codeSecurity"),
    hubLabel: t("nav.hub.securityBaselines"),
    subtitle: t("nav.panelSub.codeSecurity"),
    group: "operations",
    component: CodeSecurityRoute,
  },
  {
    id: "configuration-baselines",
    label: t("nav.panel.configurationBaselines"),
    subtitle: t("nav.panelSub.configurationBaselines"),
    group: "operations",
    hubRootId: "code-security",
    hiddenFromNavigation: true,
    component: ConfigurationBaselinesRoute,
  },
  {
    id: "hil-queue",
    label: t("nav.panel.hilQueue"),
    hubLabel: t("nav.hub.approvalsAlerts"),
    subtitle: t("nav.panelSub.hilQueue"),
    group: "operations",
    component: HilQueueRoute,
  },
  {
    id: "alert-quality",
    get label() { return alertQualityNavText("title"); },
    get subtitle() { return alertQualityNavText("subtitle"); },
    group: "operations",
    hubRootId: "hil-queue",
    hiddenFromNavigation: true,
    component: AlertQualityRoute,
  },
  {
    id: "detection-readiness",
    label: t("nav.panel.detectionReadiness"),
    subtitle: t("nav.panelSub.detectionReadiness"),
    group: "operations",
    hubRootId: "hil-queue",
    hiddenFromNavigation: true,
    component: DetectionReadinessRoute,
  },
  {
    id: "conversation-delivery",
    label: t("nav.panel.conversationDelivery"),
    subtitle: t("nav.panelSub.conversationDelivery"),
    group: "operations",
    hubRootId: "hil-queue",
    hiddenFromNavigation: true,
    component: ConversationDeliveryRoute,
  },
  {
    id: "workflow-apps",
    label: t("nav.panel.workflowApps"),
    hubLabel: t("nav.hub.automationRuns"),
    subtitle: t("nav.panelSub.workflowApps"),
    group: "operations",
    component: WorkflowAppsRoute,
  },
  {
    id: "automation-blueprints",
    label: t("nav.panel.automationBlueprints"),
    subtitle: t("nav.panelSub.automationBlueprints"),
    group: "operations",
    hubRootId: "workflow-apps",
    hiddenFromNavigation: true,
    component: AutomationBlueprintsRoute,
  },
  {
    id: "processes",
    label: t("nav.panel.processes"),
    subtitle: t("nav.panelSub.processes"),
    group: "operations",
    hubRootId: "workflow-apps",
    hiddenFromNavigation: true,
    component: ProcessesRoute,
  },
  {
    id: "scheduler-runs",
    label: t("nav.panel.schedulerRuns"),
    subtitle: t("nav.panelSub.schedulerRuns"),
    group: "operations",
    hubRootId: "workflow-apps",
    hiddenFromNavigation: true,
    component: SchedulerRunsRoute,
  },
  {
    id: "background-tasks",
    label: t("nav.panel.backgroundTasks"),
    subtitle: t("nav.panelSub.backgroundTasks"),
    group: "operations",
    hubRootId: "workflow-apps",
    hiddenFromNavigation: true,
    component: BackgroundTasksRoute,
  },
  {
    id: "scheduled-continuations",
    label: t("nav.panel.scheduledContinuations"),
    subtitle: t("nav.panelSub.scheduledContinuations"),
    group: "operations",
    hubRootId: "workflow-apps",
    hiddenFromNavigation: true,
    component: ScheduledContinuationsRoute,
  },
  {
    id: "provision",
    label: t("nav.panel.provision"),
    subtitle: t("nav.panelSub.provision"),
    group: "operations",
    hiddenFromNavigation: true,
    component: ProvisionRoute,
  },
  {
    id: "onboarding",
    label: t("nav.panel.onboarding"),
    subtitle: t("nav.panelSub.onboarding"),
    group: "operations",
    hiddenFromNavigation: true,
    component: OnboardingRoute,
  },
  // ── Agents ──────────────────────────────────────────────────────────
  {
    id: "agents",
    label: t("nav.panel.agents"),
    subtitle: t("nav.panelSub.agents"),
    group: "agents",
    component: AgentsRoute,
  },
  {
    id: "pantheon",
    label: t("nav.panel.pantheon"),
    hubLabel: t("nav.hub.rolesHandover"),
    subtitle: t("nav.panelSub.pantheon"),
    group: "agents",
    component: AgentsRoute,
  },
  {
    id: "handover",
    label: t("nav.panel.handover"),
    subtitle: t("nav.panelSub.handover"),
    group: "agents",
    hubRootId: "pantheon",
    hiddenFromNavigation: true,
    component: HandoverRoute,
  },
  {
    id: "agent-activity",
    label: t("nav.panel.agentActivity"),
    subtitle: t("nav.panelSub.agentActivity"),
    group: "agents",
    component: AgentActivityRoute,
  },
  {
    id: "skills",
    label: t("nav.panel.skills"),
    hubLabel: t("nav.hub.skillsCapabilities"),
    subtitle: t("nav.panelSub.skills"),
    group: "agents",
    component: SkillsRoute,
  },
  {
    id: "capabilities",
    label: t("nav.panel.capabilities"),
    subtitle: t("nav.panelSub.capabilities"),
    group: "agents",
    hubRootId: "skills",
    hiddenFromNavigation: true,
    component: CapabilitiesRoute,
  },
  // ── Governance (includes Knowledge) ─────────────────────────────────
  {
    id: "rules",
    label: t("nav.panel.rules"),
    hubLabel: t("nav.hub.rulesTrustRouting"),
    subtitle: t("nav.panelSub.rules"),
    group: "governance",
    component: RuleCatalogRoute,
  },
  {
    id: "trust-routing",
    label: t("nav.panel.trustRouting"),
    subtitle: t("nav.panelSub.trustRouting"),
    group: "governance",
    hubRootId: "rules",
    hiddenFromNavigation: true,
    component: TrustRoutingRoute,
  },
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
    hubLabel: t("nav.hub.ontologyScope"),
    subtitle: t("nav.panelSub.ontology"),
    group: "governance",
    component: OntologyRoute,
  },
  {
    id: "scope",
    label: t("nav.panel.scope"),
    subtitle: t("nav.panelSub.scope"),
    group: "governance",
    hubRootId: "ontology",
    hiddenFromNavigation: true,
    component: ScopeRoute,
  },
  {
    id: "blast-radius",
    label: t("nav.panel.blastRadius"),
    hubLabel: t("nav.hub.blastRadiusGates"),
    subtitle: t("nav.panelSub.blastRadius"),
    group: "governance",
    component: BlastRadiusRoute,
  },
  {
    id: "promotion-gates",
    label: t("nav.panel.promotionGates"),
    subtitle: t("nav.panelSub.promotionGates"),
    group: "governance",
    hubRootId: "blast-radius",
    hiddenFromNavigation: true,
    component: PromotionGatesRoute,
  },
  {
    id: "workflow-builder",
    label: t("nav.panel.workflowBuilder"),
    subtitle: t("nav.panelSub.workflowBuilder"),
    group: "governance",
    component: WorkflowBuilderRoute,
  },
  knowledgeSourcePanel("knowledge", t("nav.panel.knowledge"), true),
  {
    id: "documents",
    label: t("nav.panel.documents"),
    subtitle: t("nav.panelSub.documents"),
    group: "governance",
    hubRootId: "knowledge",
    hiddenFromNavigation: true,
    component: KnowledgeDomainRoute,
  },
  knowledgeSourcePanel("github", "GitHub"),
  knowledgeSourcePanel("gitlab", "GitLab"),
  knowledgeSourcePanel("azure-devops", "Azure DevOps"),
  // ── Evidence ────────────────────────────────────────────────────────
  {
    id: "audit",
    label: t("nav.panel.audit"),
    subtitle: t("nav.panelSub.audit"),
    group: "evidence",
    component: AuditRoute,
  },
  {
    id: "trace",
    label: t("nav.panel.trace"),
    hubLabel: t("nav.hub.traceRca"),
    subtitle: t("nav.panelSub.trace"),
    group: "evidence",
    component: RuleTraceRoute,
  },
  {
    id: "rca",
    label: t("nav.panel.rca"),
    subtitle: t("nav.panelSub.rca"),
    group: "evidence",
    hubRootId: "trace",
    hiddenFromNavigation: true,
    component: RcaRoute,
  },
  {
    id: "browser-evidence",
    label: t("nav.panel.browserEvidence"),
    subtitle: t("nav.panelSub.browserEvidence"),
    group: "evidence",
    hubRootId: "trace",
    hiddenFromNavigation: true,
    component: BrowserEvidenceRoute,
  },
  {
    id: "reports",
    label: t("nav.panel.reports"),
    subtitle: t("nav.panelSub.reports"),
    group: "evidence",
    component: ReportsRoute,
  },
  {
    id: "conversation-search",
    label: t("nav.panel.conversationSearch"),
    subtitle: t("nav.panelSub.conversationSearch"),
    group: "evidence",
    component: ConversationSearchRoute,
  },
  // ── Labs & Evaluation Hubs (dev-only rail) ──────────────────────────
  {
    id: "labs",
    label: t("nav.panel.labs"),
    subtitle: t("nav.panelSub.labs"),
    group: "labs",
    component: LabsRoute,
  },
  {
    id: "aks-commerce",
    label: t("nav.panel.aksCommerce"),
    subtitle: t("nav.panelSub.aksCommerce"),
    group: "labs",
    hubRootId: "labs",
    hiddenFromNavigation: true,
    component: AksCommerceRoute,
  },
  {
    id: "assurance-twin",
    label: t("nav.panel.assuranceTwin"),
    hubLabel: t("nav.hub.assuranceEvals"),
    subtitle: t("nav.panelSub.assuranceTwin"),
    group: "labs",
    component: AssuranceTwinRoute,
  },
  {
    id: "forecast-learning",
    label: t("nav.panel.forecastLearning"),
    subtitle: t("nav.panelSub.forecastLearning"),
    group: "labs",
    hubRootId: "assurance-twin",
    hiddenFromNavigation: true,
    component: ForecastLearningRoute,
  },
  {
    id: "conversation-assurance",
    label: t("nav.panel.conversationAssurance"),
    subtitle: t("nav.panelSub.conversationAssurance"),
    group: "labs",
    hubRootId: "assurance-twin",
    hiddenFromNavigation: true,
    component: ConversationAssuranceRoute,
  },
  {
    id: "context-selection-comparisons",
    label: t("nav.panel.contextSelectionComparisons"),
    subtitle: t("nav.panelSub.contextSelectionComparisons"),
    group: "labs",
    hubRootId: "assurance-twin",
    hiddenFromNavigation: true,
    component: ContextSelectionComparisonsRoute,
  },
  // ── Settings ────────────────────────────────────────────────────────
  {
    id: "settings-general",
    label: t("nav.panel.settingsGeneral"),
    hubLabel: t("nav.hub.settingsGeneralEnv"),
    subtitle: t("nav.panelSub.settingsGeneral"),
    group: "settings",
    component: SettingsGeneralRoute,
  },
  {
    id: "settings-environment",
    label: t("nav.panel.settingsEnvironment"),
    subtitle: t("nav.panelSub.settingsEnvironment"),
    group: "settings",
    hubRootId: "settings-general",
    hiddenFromNavigation: true,
    component: EnvironmentDeploymentRoute,
  },
  {
    id: "settings-models",
    label: t("nav.panel.settingsModels"),
    hubLabel: t("nav.hub.settingsModelsRuntime"),
    subtitle: t("nav.panelSub.settingsModels"),
    group: "settings",
    component: SettingsModelsRoute,
  },
  {
    id: "settings-runtime",
    label: t("nav.panel.settingsRuntime"),
    subtitle: t("nav.panelSub.settingsRuntime"),
    group: "settings",
    hubRootId: "settings-models",
    hiddenFromNavigation: true,
    component: SettingsRuntimeRoute,
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
    hubLabel: t("nav.hub.settingsDiagnosticsMemory"),
    subtitle: t("nav.panelSub.settingsDiagnostics"),
    group: "settings",
    component: SettingsDiagnosticsRoute,
  },
  {
    id: "settings-memory",
    label: t("nav.panel.operatorMemory"),
    subtitle: t("nav.panelSub.operatorMemory"),
    group: "settings",
    hubRootId: "settings-diagnostics",
    hiddenFromNavigation: true,
    component: OperatorMemoryRoute,
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
  return filterPanelsByStencil(validatePanelRegistry([...CORE_PANELS, ...EXTRA_PANELS]));
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

/** Primary navigation label for a panel (uses combined hub label when present). */
export function navLabelForPanel(panel: ConsolePanel): string {
  return panel.hubLabel ?? panel.label;
}

/** Resolve the primary navigation representative panel id for any panel or child hub tab. */
export function hubRootIdForPanel(panelId: string): string {
  const panels = resolvePanels();
  const panel = panels.find((candidate) => candidate.id === panelId);
  if (!panel) return panelId;
  const rootKey = panel.hubRootId ?? panel.id;
  const directRoot = panels.find((candidate) => candidate.id === rootKey);
  if (directRoot && directRoot.hiddenFromNavigation !== true) return directRoot.id;
  const promotedChild = panels.find(
    (candidate) => candidate.hubRootId === rootKey && candidate.group === panel.group,
  );
  return promotedChild?.id ?? panel.id;
}

/** Return the ordered tab panels for a multi-view hub, or an empty array for single views. */
export function hubPanelsFor(panelId: string): readonly ConsolePanel[] {
  const panels = resolvePanels();
  const panel = panels.find((candidate) => candidate.id === panelId);
  if (!panel) return [];
  const rootKey = panel.hubRootId ?? panel.id;
  const members = panels.filter(
    (candidate) =>
      candidate.group === panel.group &&
      (candidate.id === rootKey || candidate.hubRootId === rootKey),
  );
  return members.length > 1 ? members : [];
}

/** Panels filtered to a single group, in registration order.
 * If a Stencil disables a hub representative while keeping a child tab enabled,
 * the first enabled child in that hub is promoted so no active surface is orphaned. */
export function panelsInGroup(group: PanelGroup): readonly ConsolePanel[] {
  const panels = resolvePanels().filter(
    (panel) => panel.group === group && panel.placement === undefined,
  );
  const visibleIds = new Set(
    panels
      .filter((panel) => panel.hiddenFromNavigation !== true)
      .map((panel) => panel.id),
  );
  const promotedHubRoots = new Set<string>();
  const result: ConsolePanel[] = [];
  for (const panel of panels) {
    if (panel.hiddenFromNavigation !== true) {
      result.push(panel);
      continue;
    }
    if (
      panel.hubRootId !== undefined &&
      !visibleIds.has(panel.hubRootId) &&
      !promotedHubRoots.has(panel.hubRootId)
    ) {
      promotedHubRoots.add(panel.hubRootId);
      result.push(panel);
    }
  }
  return result;
}

/** Standalone global utilities pinned to the bottom of the left rail. */
export function bottomRailPanels(): readonly ConsolePanel[] {
  return resolvePanels().filter(
    (panel) => panel.placement === "bottom" && panel.hiddenFromNavigation !== true,
  );
}

/** The default panel id: Overview - the approver's landing (health /
 * risk / cost at a glance). It is the first group on the rail, so the
 * landing and the rail order agree. */
export const DEFAULT_PANEL_ID = "dashboard";

/** Resolve the panel for a hash-route segment, or the default panel. */
export function panelForId(id: string): ConsolePanel {
  return resolvePanels().find((p) => p.id === id) ?? DASHBOARD_PANEL;
}
