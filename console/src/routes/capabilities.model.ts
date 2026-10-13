import type { IamRole } from "./settings-iam.model";
import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelStringArray,
} from "./panel-decode";

const CAPABILITY_SIDE_EFFECT_CLASSES = [
  "read",
  "simulate",
  "approve",
  "execute",
  "breakglass",
] as const;
export type CapabilitySideEffectClass = typeof CAPABILITY_SIDE_EFFECT_CLASSES[number];

const CAPABILITY_MODES = ["shadow", "enforce"] as const;
export type CapabilityMode = typeof CAPABILITY_MODES[number];

const CAPABILITY_PARITY = ["native", "safer-alternative", "external-binding"] as const;
export type CapabilityParity = typeof CAPABILITY_PARITY[number];

const CAPABILITY_SORTS = ["category", "name", "effect", "role"] as const;
export type CapabilitySort = typeof CAPABILITY_SORTS[number];

export const CAPABILITY_PAGE_SIZE = 20;

export interface Capability {
  readonly capability_id: string;
  readonly name: string;
  readonly category: string;
  readonly summary: string;
  readonly side_effect_class: CapabilitySideEffectClass;
  readonly default_mode: CapabilityMode;
  readonly required_role: string;
  readonly slide_ref: string | null;
  readonly tags: readonly string[];
  readonly parity: CapabilityParity;
  readonly official_source: string | null;
  readonly evidence_refs: readonly string[];
}

export interface CapabilityResponse {
  readonly source: string;
  readonly execution_eligibility: false;
  readonly count: number;
  readonly capabilities: readonly Capability[];
}

export interface CapabilityRouteState {
  readonly query: string;
  readonly category: string;
  readonly effect: string;
  readonly role: string;
  readonly sort: CapabilitySort;
  readonly page: number;
  readonly selectedId: string | null;
}

export interface CapabilityDestination {
  readonly routeId: string;
  readonly labelKey: string;
}

export type CapabilityRoleMatch = "meets" | "does-not-meet" | "unavailable";

const DESTINATIONS: Readonly<Record<string, CapabilityDestination>> = {
  "chaos.run_experiment": destination("blast-radius", "impactScope"),
  "cost.metering": destination("llm-cost", "llmCost"),
  "observability.resource-discovery": destination("architecture", "architecture"),
  "observability.topology": destination("architecture", "architecture"),
  "observability.activity-log": destination("audit", "audit"),
  "observability.trace-query": destination("trace", "trace"),
  "investigation.background": destination("background-tasks", "backgroundTasks"),
  "knowledge.user-memory": destination("settings-memory", "userMemory"),
  "knowledge.auto-learning": destination("forecast-learning", "forecastLearning"),
  "devops.github": destination("github", "github"),
  "devops.azure-devops": destination("azure-devops", "azureDevOps"),
  "operations.typed-mutation": destination("promotion-gates", "promotionGates"),
  "operations.kubectl": destination("promotion-gates", "promotionGates"),
  "safety.human-approval": destination("hil-queue", "approvals"),
  "measurement.dora": destination("operating-outcomes", "operatingOutcomes"),
  "measurement.slo": destination("operating-outcomes", "operatingOutcomes"),
  "audit.append-only": destination("audit", "audit"),
  "communication.teams": destination("conversation-delivery", "conversationDelivery"),
  "automation.specialists": destination("agents", "agents"),
  "scheduling.history": destination("scheduler-runs", "schedulerRuns"),
  "scheduling.lifecycle": destination("scheduler-runs", "schedulerRuns"),
  "scheduler.create_task": destination("workflow-builder", "workflowBuilder"),
};

const PREFIX_DESTINATIONS: readonly [string, CapabilityDestination][] = [
  ["observability.", destination("detection-readiness", "detectionCoverage")],
  ["paging.", destination("incidents", "incidents")],
  ["incident.", destination("incidents", "incidents")],
  ["investigation.", destination("rca", "rootCauseAnalysis")],
  ["operations.azure-cli-", destination("rca", "rootCauseAnalysis")],
  ["knowledge.", destination("documents", "documents")],
  ["extensibility.", destination("skills", "skills")],
  ["reporting.", destination("reports", "reports")],
  ["communication.", destination("reports", "reports")],
  ["irp.", destination("workflow-builder", "workflowBuilder")],
  ["automation.", destination("workflow-builder", "workflowBuilder")],
  ["scheduler.", destination("scheduler-runs", "schedulerRuns")],
  ["scheduling.", destination("scheduler-runs", "schedulerRuns")],
];

const CATEGORY_DESTINATIONS: Readonly<Record<string, CapabilityDestination>> = {
  chaos: destination("blast-radius", "impactScope"),
  cost: destination("llm-cost", "llmCost"),
  detection: destination("detection-readiness", "detectionCoverage"),
  incident: destination("incidents", "incidents"),
  investigation: destination("rca", "rootCauseAnalysis"),
  knowledge: destination("documents", "documents"),
  remediation: destination("promotion-gates", "promotionGates"),
  reporting: destination("reports", "reports"),
  response_plan: destination("workflow-builder", "workflowBuilder"),
  scheduling: destination("scheduler-runs", "schedulerRuns"),
};

const ROLE_RANK: Readonly<Record<string, number>> = {
  Reader: 0,
  Contributor: 1,
  Approver: 2,
  Owner: 3,
};

function destination(routeId: string, labelKey: string): CapabilityDestination {
  return { routeId, labelKey };
}

export function decodeCapabilities(value: unknown): CapabilityResponse {
  const root = panelRecord(value, "capabilities");
  const capabilities = panelArray(root["capabilities"], "capabilities.items").map((raw, index) => {
    const item = panelRecord(raw, `capabilities.items[${index}]`);
    return {
      capability_id: panelNonEmptyString(item, "capability_id", "capability"),
      name: panelNonEmptyString(item, "name", "capability"),
      category: panelNonEmptyString(item, "category", "capability"),
      summary: panelNonEmptyString(item, "summary", "capability"),
      side_effect_class: decodeCapabilitySideEffectClass(item),
      default_mode: decodeCapabilityMode(item),
      required_role: panelNonEmptyString(item, "required_role", "capability"),
      slide_ref: panelNullableString(item, "slide_ref", "capability"),
      tags: panelStringArray(item["tags"], "capability.tags"),
      parity: decodeCapabilityParity(item),
      official_source: panelNullableString(item, "official_source", "capability"),
      evidence_refs: panelStringArray(item["evidence_refs"], "capability.evidence_refs"),
    };
  });
  const count = panelNonNegativeInteger(root, "count", "capabilities");
  if (count !== capabilities.length) {
    throw new Error("invalid Operator API response: capabilities.count MUST match items");
  }
  const ids = capabilities.map((item) => item.capability_id);
  if (new Set(ids).size !== ids.length) {
    throw new Error("invalid Operator API response: capability ids MUST be unique");
  }
  if (panelBoolean(root, "execution_eligibility", "capabilities")) {
    throw new Error("invalid Operator API response: capability catalog MUST NOT grant execution");
  }
  return {
    source: panelNonEmptyString(root, "source", "capabilities"),
    execution_eligibility: false,
    count,
    capabilities,
  };
}

function decodeCapabilitySideEffectClass(
  item: Readonly<Record<string, unknown>>,
): CapabilitySideEffectClass {
  const value = panelNonEmptyString(item, "side_effect_class", "capability");
  if (!CAPABILITY_SIDE_EFFECT_CLASSES.some((candidate) => candidate === value)) {
    throw new Error("invalid Operator API response: capability.side_effect_class is invalid");
  }
  return value as CapabilitySideEffectClass;
}

function decodeCapabilityMode(item: Readonly<Record<string, unknown>>): CapabilityMode {
  const value = panelNonEmptyString(item, "default_mode", "capability");
  if (!CAPABILITY_MODES.some((candidate) => candidate === value)) {
    throw new Error("invalid Operator API response: capability.default_mode is invalid");
  }
  return value as CapabilityMode;
}

function decodeCapabilityParity(item: Readonly<Record<string, unknown>>): CapabilityParity {
  const value = panelNonEmptyString(item, "parity", "capability");
  if (!CAPABILITY_PARITY.some((candidate) => candidate === value)) {
    throw new Error("invalid Operator API response: capability.parity is invalid");
  }
  return value as CapabilityParity;
}

export function capabilityRouteStateFromSearch(search: URLSearchParams): CapabilityRouteState {
  const sort = search.get("sort");
  const rawPage = Number(search.get("page") ?? "1");
  return {
    query: search.get("q") ?? "",
    category: search.get("category") ?? "all",
    effect: search.get("effect") ?? "all",
    role: search.get("role") ?? "all",
    sort: CAPABILITY_SORTS.some((candidate) => candidate === sort)
      ? sort as CapabilitySort
      : "category",
    page: Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1,
    selectedId: search.get("capability"),
  };
}

export function sortCapabilities(
  capabilities: readonly Capability[],
  sort: CapabilitySort,
): readonly Capability[] {
  const key = (item: Capability): string => {
    if (sort === "name") return item.name;
    if (sort === "effect") return item.side_effect_class;
    if (sort === "role") return item.required_role;
    return item.category;
  };
  return [...capabilities].sort((left, right) =>
    key(left).localeCompare(key(right), "en")
    || left.name.localeCompare(right.name, "en")
    || left.capability_id.localeCompare(right.capability_id, "en"));
}

export function capabilityDestination(capability: Capability): CapabilityDestination {
  const exact = DESTINATIONS[capability.capability_id];
  if (exact) return exact;
  const prefixed = PREFIX_DESTINATIONS.find(([prefix]) =>
    capability.capability_id.startsWith(prefix));
  return prefixed?.[1]
    ?? CATEGORY_DESTINATIONS[capability.category]
    ?? destination("workflow-builder", "workflowBuilder");
}

export function capabilityRoleMatch(
  requiredRole: string,
  roles: readonly IamRole[] | null,
): CapabilityRoleMatch {
  if (roles === null) return "unavailable";
  const requiredRank = ROLE_RANK[titleCase(requiredRole)];
  if (requiredRank === undefined) return "unavailable";
  return roles.some((role) => (ROLE_RANK[role] ?? -1) >= requiredRank)
    ? "meets"
    : "does-not-meet";
}

export function isMutatingCapability(sideEffectClass: CapabilitySideEffectClass): boolean {
  return sideEffectClass === "execute" || sideEffectClass === "breakglass";
}

export function capabilityRequestPath(sideEffectClass: CapabilitySideEffectClass): Readonly<{
  key: "directRead" | "governedRequest" | "humanApproval" | "ownerBreakGlass";
  tone: "info" | "shadow" | "hil" | "danger";
}> {
  if (sideEffectClass === "read") return { key: "directRead", tone: "info" };
  if (sideEffectClass === "simulate") return { key: "governedRequest", tone: "shadow" };
  if (sideEffectClass === "breakglass") return { key: "ownerBreakGlass", tone: "danger" };
  return { key: "humanApproval", tone: "hil" };
}

function titleCase(value: string): string {
  return value.length === 0 ? value : value.charAt(0).toUpperCase() + value.slice(1).toLowerCase();
}
