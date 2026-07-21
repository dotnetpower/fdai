import type { ReadDataSourcesPayload, ReadSourceAvailability } from "./api-data-sources";
import { sourceForRoute } from "./api-data-sources";

const PANEL_SOURCE_ROUTES: Readonly<Record<string, readonly string[]>> = {
  dashboard: ["/kpi", "/finops", "/kpi/promotion-gates", "/kpi/autonomy"],
  "operating-outcomes": ["/kpi/autonomy"],
  "control-assurance": ["/kpi/autonomy", "/kpi/promotion-gates", "/hil-queue"],
  verticals: ["/kpi/autonomy"],
  "trust-routing": ["/kpi/autonomy"],
  "llm-cost": ["/kpi/llm-cost"],
  live: ["/live/stream"],
  incidents: ["/incidents"],
  "hil-queue": ["/hil-queue"],
  provision: ["/provision/stream"],
  onboarding: ["/onboarding"],
  processes: ["/views/process"],
  "workflow-apps": ["/views/workflow-apps"],
  "scheduler-runs": ["/scheduler-runs"],
  "automation-blueprints": ["/automation-blueprints"],
  "conversation-delivery": ["/conversation-delivery"],
  agents: ["/incidents", "/agents/stream"],
  pantheon: ["/pantheon/graph", "/pantheon/workflows"],
  "agent-activity": ["/agents/stream"],
  handover: ["/stewardship"],
  architecture: ["/inventory/graph"],
  ontology: ["/ontology/graph"],
  rules: ["/rules"],
  capabilities: ["/capabilities"],
  "promotion-gates": ["/kpi/promotion-gates"],
  "context-selection-comparisons": ["/context-selection-comparisons"],
  "blast-radius": ["/inventory/graph"],
  scope: ["/scope"],
  audit: ["/audit"],
  trace: ["/audit"],
  rca: ["/rca"],
  "browser-evidence": ["/browser-evidence"],
  reports: ["/reports", "/reports/registry"],
  "conversation-search": ["/me/conversations/search"],
  "scheduled-continuations": ["/me/context"],
  "workflow-builder": ["/workflows/catalog", "/workflows/action-types"],
  skills: ["/skills"],
  "settings-general": ["/me/context"],
  "settings-models": ["/models/settings"],
  "settings-memory": ["/operator-memory"],
  "settings-iam": ["/iam"],
};

const SEPARATE_CLIENT_PANELS = new Set(["documents"]);
const SOURCE_INDEPENDENT_PANELS = new Set([
  "labs",
  "settings-diagnostics",
  "settings-integrations",
]);

export type PanelSourceClassification = "read-api" | "separate-client" | "independent";

export function panelSourceClassification(panelId: string): PanelSourceClassification | null {
  if (PANEL_SOURCE_ROUTES[panelId] !== undefined) return "read-api";
  if (SEPARATE_CLIENT_PANELS.has(panelId)) return "separate-client";
  if (SOURCE_INDEPENDENT_PANELS.has(panelId)) return "independent";
  return null;
}

export function panelSourceAvailability(
  panelId: string,
  payload: ReadDataSourcesPayload,
): ReadSourceAvailability | null {
  const routes = PANEL_SOURCE_ROUTES[panelId];
  if (routes === undefined) return null;
  const resolved = routes.map((route) => sourceForRoute(payload, route));
  const sources = resolved.filter((source) => source !== null);
  if (sources.some((source) => source.availability === "unavailable" || !source.authoritative)) {
    return "unavailable";
  }
  if (resolved.some((source) => source === null)) return "unknown";
  return sources.every((source) => source.availability === "available")
    ? "available"
    : "unknown";
}
