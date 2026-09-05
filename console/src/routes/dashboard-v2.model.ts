import { resourceColorTokenOf, resourceTypeLabelOf } from "../components/architecture-map.model";
import { ARCHITECTURE_RESOURCE_ABBREVIATIONS } from "../components/architecture-resource-abbreviations";
import { isRfc3339Timestamp } from "../time-format";
import { isOperationalResourceType } from "../resource-presentation";
import type { RecordedResourceStates, RecordedStateFact } from "../recorded-resource-state";

export type DashboardLens = "operation" | "provisioning" | "availability" | "observation";
export type DashboardView = "honeycomb" | "list" | "groups";
export type DashboardState = "running" | "stopped" | "deallocated" | "transitioning" | "unknown" | "not-applicable" | "fresh" | "stale" | "enabled" | "disabled" | "active" | "online" | "offline" | "ready" | "paused" | "succeeded" | "failed" | "available" | "degraded" | "unavailable" | "recorded";
export type DashboardTone = "active" | "neutral" | "attention" | "unknown" | "na" | "negative";

export interface DashboardResource {
  readonly id: string;
  readonly name: string;
  readonly type: string;
  readonly status: string;
  readonly parentId: string | null;
  readonly group: string | null;
  readonly groupLabel: string | null;
  readonly subscription: string | null;
  readonly subscriptionLabel: string | null;
  readonly observedAt: string | null;
  readonly states?: RecordedResourceStates;
}

export interface DashboardSnapshot {
  readonly id: string | null;
  readonly ontologyGeneration?: string;
  readonly ontologyManifestDigest?: string;
  readonly at: string;
  readonly source: string | null;
  readonly scope: string | null;
  readonly freshness: "fresh" | "stale" | "unknown";
  readonly observationKind: "OBSERVED" | "EXPECTED" | null;
  readonly truncated: boolean;
  readonly limitations: readonly string[];
  readonly resources: readonly DashboardResource[];
  readonly excludedContainers: number;
  readonly excludedAuthorization: number;
  readonly pendingChanges: number | null;
  readonly recordedStates?: boolean;
  readonly totalCount?: number;
}

export const STATE_STYLE: Readonly<Record<DashboardState, { readonly tone: DashboardTone; readonly symbol: string }>> = {
  running: { tone: "active", symbol: ">" },
  stopped: { tone: "neutral", symbol: "II" },
  deallocated: { tone: "neutral", symbol: "D" },
  transitioning: { tone: "attention", symbol: "~" },
  unknown: { tone: "unknown", symbol: "?" },
  "not-applicable": { tone: "na", symbol: "-" },
  fresh: { tone: "active", symbol: "+" },
  stale: { tone: "attention", symbol: "~" },
  enabled: { tone: "active", symbol: "E" }, disabled: { tone: "neutral", symbol: "D" },
  active: { tone: "active", symbol: "A" }, online: { tone: "active", symbol: "O" },
  offline: { tone: "neutral", symbol: "O" }, ready: { tone: "neutral", symbol: "R" },
  paused: { tone: "neutral", symbol: "II" }, succeeded: { tone: "neutral", symbol: "+" },
  failed: { tone: "negative", symbol: "X" }, available: { tone: "active", symbol: "+" },
  degraded: { tone: "attention", symbol: "!" }, unavailable: { tone: "negative", symbol: "X" },
  recorded: { tone: "neutral", symbol: "=" },
};

function record(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error(`Invalid inventory ${label}`);
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim() || value.length > 4096) throw new Error(`Invalid inventory ${label}`);
  return value;
}

function optionalText(value: unknown, label: string): string | null {
  return value === null || value === undefined ? null : text(value, label);
}

function timestamp(value: unknown, label: string): string {
  const result = text(value, label);
  if (!isRfc3339Timestamp(result)) throw new Error(`Invalid inventory ${label}`);
  return result;
}

function strings(value: unknown, label: string): readonly string[] {
  if (value === undefined) return [];
  if (!Array.isArray(value) || value.length > 1000) throw new Error(`Invalid inventory ${label}`);
  return value.map((entry) => text(entry, label));
}

/** Decodes only display-safe fields of the existing authenticated inventory projection. */
export function decodeDashboardSnapshot(value: unknown): DashboardSnapshot {
  const payload = record(value, "projection");
  if ([payload.execution_authority, payload.mutation_authority].some((field) => field !== undefined && field !== false)) throw new Error("Inventory projection cannot grant authority");
  const freshness = payload.freshness;
  if (freshness !== "fresh" && freshness !== "stale" && freshness !== "unknown") throw new Error("Invalid inventory freshness");
  if (typeof payload.truncated !== "boolean") throw new Error("Invalid inventory truncation");
  const kind = typeof payload.observation_kind === "string" ? payload.observation_kind.toUpperCase() : payload.observation_kind;
  if (kind !== undefined && kind !== null && kind !== "OBSERVED" && kind !== "EXPECTED") throw new Error("Invalid inventory observation kind");
  if (!Array.isArray(payload.resources) || payload.resources.length > 20000) throw new Error("Inventory projection exceeds the 20000-record client boundary");
  const rows = payload.resources.map((value) => {
    const row = record(value, "resource");
    return {
      id: text(row.id, "resource id"),
      name: text(row.name, "resource name"),
      type: text(row.type, "resource type"),
      status: optionalText(row.status, "resource status") ?? "",
      parentId: optionalText(row.parent_id, "parent id"),
      observedAt: row.last_seen === undefined || row.last_seen === null ? null : timestamp(row.last_seen, "last seen"),
    };
  });
  const byId = new Map(rows.map((row) => [row.id, row]));
  if (byId.size !== rows.length) throw new Error("Inventory projection contains duplicate resource ids");
  const containers = new Set(["subscription", "resource-group"]);
  const resources = rows.filter((row) => !containers.has(row.type) && isOperationalResourceType(row.type)).map((row): DashboardResource => {
    let group: (typeof rows)[number] | undefined;
    let subscription: (typeof rows)[number] | undefined;
    const visited = new Set([row.id]);
    let parent = row.parentId;
    while (parent !== null) {
      if (visited.has(parent)) throw new Error("Inventory projection contains a parent cycle");
      if (visited.size > 16) throw new Error("Inventory projection exceeds the parent depth boundary");
      visited.add(parent);
      const ancestor = byId.get(parent);
      if (ancestor === undefined) break;
      if (ancestor.type === "resource-group" && group === undefined) group = ancestor;
      if (ancestor.type === "subscription") subscription = ancestor;
      parent = ancestor.parentId;
    }
    return { ...row, group: group?.id ?? null, groupLabel: group?.name ?? null, subscription: subscription?.id ?? null, subscriptionLabel: subscription?.name ?? null };
  });
  const realtime = payload.realtime === undefined || payload.realtime === null ? null : record(payload.realtime, "realtime metadata");
  const pending = realtime?.pending_changes;
  if (pending !== undefined && (typeof pending !== "number" || !Number.isSafeInteger(pending) || pending < 0)) throw new Error("Invalid inventory pending count");
  return {
    id: optionalText(payload.snapshot_id, "snapshot id"),
    at: timestamp(payload.snapshot_at, "snapshot time"),
    source: optionalText(payload.source, "source"),
    scope: optionalText(payload.scope, "scope") ?? optionalText(payload.active_view, "active view"),
    freshness,
    observationKind: kind ?? null,
    truncated: payload.truncated,
    limitations: [...strings(payload.truncation_reasons, "truncation reasons"), ...strings(payload.coverage_gaps, "coverage gaps"), ...(payload.degraded === true ? ["source_degraded"] : [])],
    resources,
    excludedContainers: rows.filter((row) => containers.has(row.type)).length,
    excludedAuthorization: rows.filter((row) => !isOperationalResourceType(row.type)).length,
    pendingChanges: typeof pending === "number" ? pending : null,
  };
}

/** Never equates provisioning success or generic health labels with running or availability. */
export function dashboardResourceState(resource: DashboardResource, snapshot: DashboardSnapshot, lens: DashboardLens): DashboardState {
  if (resource.states) {
    const fact = dashboardStateFact(resource, lens)!;
    if (lens === "observation") return fact.freshness === "fresh" ? "fresh" : fact.freshness === "stale" ? "stale" : "unknown";
    if (fact.value === null) return "unknown";
    const raw = fact.value.trim().toLowerCase().replace(/^powerstate\//, "");
    if (["starting", "stopping", "deallocating", "updating", "creating", "deleting"].includes(raw)) return "transitioning";
    return Object.hasOwn(STATE_STYLE, raw) ? raw as DashboardState : "recorded";
  }
  if (lens === "provisioning") return "unknown";
  if (lens === "availability") return "unknown";
  const observed = snapshot.observationKind === "OBSERVED" && snapshot.id !== null && snapshot.source !== null;
  if (lens === "observation") return observed ? snapshot.freshness : "unknown";
  const status = resource.status.trim().toLowerCase().replace(/^powerstate\//, "");
  if (snapshot.freshness !== "fresh" || !observed || (snapshot.pendingChanges ?? 0) > 0) return "unknown";
  if (status === "not-applicable") return "not-applicable";
  if (status === "running" || status === "stopped" || status === "deallocated") return status;
  if (["starting", "stopping", "deallocating"].includes(status)) return "transitioning";
  return "unknown";
}

export function dashboardStateFact(resource: DashboardResource, lens: DashboardLens): RecordedStateFact | null {
  if (!resource.states) return null;
  return resource.states[lens === "operation" || lens === "observation" ? "operational" : lens];
}

export type DashboardUnknownReason =
  | "missingProvenance"
  | "oldSnapshot"
  | "pendingChanges"
  | "noState"
  | "unclassifiedState"
  | "resourceTypeUnclassified"
  | "stateNotRecorded"
  | "stateSourceNotRecorded"
  | "stateApplicabilityUnknown"
  | "stateMetadataNotRecorded"
  | "stateMetadataInvalid"
  | "stateAfterCutoff";

export function dashboardUnknownReason(
  resource: DashboardResource,
  snapshot: DashboardSnapshot,
): DashboardUnknownReason | null {
  if (resource.states) {
    const fact = resource.states.operational;
    if (fact.value !== null) return null;
    if (fact.reason === "resource_type_unclassified") return "resourceTypeUnclassified";
    if (fact.reason === "state_source_not_recorded") return "stateSourceNotRecorded";
    if (fact.reason === "state_applicability_unknown") return "stateApplicabilityUnknown";
    if (fact.reason === "state_metadata_not_recorded") return "stateMetadataNotRecorded";
    if (fact.reason === "state_metadata_invalid") return "stateMetadataInvalid";
    if (fact.reason === "state_after_cutoff") return "stateAfterCutoff";
    return fact.reason === "state_not_recorded" ? "stateNotRecorded" : "noState";
  }
  if (dashboardResourceState(resource, snapshot, "operation") !== "unknown") return null;
  if (snapshot.observationKind !== "OBSERVED" || snapshot.id === null || snapshot.source === null) return "missingProvenance";
  if ((snapshot.pendingChanges ?? 0) > 0) return "pendingChanges";
  if (snapshot.freshness !== "fresh") return "oldSnapshot";
  return !resource.status || resource.status.toLowerCase() === "unknown" ? "noState" : "unclassifiedState";
}

export function dashboardUnknownCounts(
  resources: readonly DashboardResource[],
  snapshot: DashboardSnapshot,
): ReadonlyMap<DashboardUnknownReason, number> {
  const result = new Map<DashboardUnknownReason, number>();
  for (const resource of resources) {
    const reason = dashboardUnknownReason(resource, snapshot);
    if (reason !== null) result.set(reason, (result.get(reason) ?? 0) + 1);
  }
  return result;
}

export function dashboardTypeLabel(resource: DashboardResource): string {
  const label = resourceTypeLabelOf(resource);
  return resourceColorTokenOf(resource) === "generic" ? resource.type : label;
}

/** Match the CSS pitch and half-column stagger; density never changes resource identities. */
export function dashboardMapColumns(width: number, density: "dense" | "comfortable"): number {
  const pitch = density === "dense" ? 26 : 56;
  const padding = density === "dense" ? 19 : 32;
  return Math.max(1, Math.min(34, Math.floor((width - padding) / pitch)));
}

export function dashboardTypeKeywords(type: string): readonly string[] {
  const aliases: Readonly<Record<string, string>> = ARCHITECTURE_RESOURCE_ABBREVIATIONS;
  return aliases[type] ? [type, aliases[type]] : [type];
}

export interface DashboardFilters {
  readonly subscription: string;
  readonly group: string | null;
  readonly type: string;
  readonly query: string;
  readonly status: DashboardState | "known" | "";
}

export const EMPTY_DASHBOARD_FILTERS: DashboardFilters = { subscription: "", group: "", type: "", query: "", status: "" };

export function dashboardStatusFilter(value: string | null): DashboardFilters["status"] {
  return value === "known" || (value !== null && Object.hasOwn(STATE_STYLE, value))
    ? value as DashboardFilters["status"] : "";
}

export function dashboardScope(resources: readonly DashboardResource[], filters: DashboardFilters, includeType = true): readonly DashboardResource[] {
  const query = filters.query.trim().toLowerCase();
  return resources.filter((resource) =>
    (!filters.subscription || resource.subscription === filters.subscription)
    && (filters.group === "" || resource.group === filters.group)
    && (!includeType || !filters.type || resource.type === filters.type)
    && `${resource.name} ${resource.id}`.toLowerCase().includes(query));
}

export function dashboardCounts(resources: readonly DashboardResource[], snapshot: DashboardSnapshot, lens: DashboardLens): ReadonlyMap<DashboardState, number> {
  const result = new Map<DashboardState, number>();
  for (const resource of resources) {
    const key = dashboardResourceState(resource, snapshot, lens);
    result.set(key, (result.get(key) ?? 0) + 1);
  }
  return result;
}
