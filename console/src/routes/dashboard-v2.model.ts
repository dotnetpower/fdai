import { resourceTypeLabelOf } from "../components/architecture-map.model";
import { ARCHITECTURE_RESOURCE_ABBREVIATIONS } from "../components/architecture-resource-abbreviations";

export type DashboardLens = "operation" | "availability" | "observation";
export type DashboardView = "honeycomb" | "list" | "groups";
export type DashboardState = "running" | "stopped" | "deallocated" | "transitioning" | "unknown" | "not-applicable" | "fresh" | "stale";
export type DashboardTone = "active" | "neutral" | "attention" | "unknown" | "na";

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
}

export interface DashboardSnapshot {
  readonly id: string | null;
  readonly at: string;
  readonly source: string | null;
  readonly scope: string | null;
  readonly freshness: "fresh" | "stale" | "unknown";
  readonly observationKind: "OBSERVED" | "EXPECTED" | null;
  readonly truncated: boolean;
  readonly limitations: readonly string[];
  readonly resources: readonly DashboardResource[];
  readonly excludedContainers: number;
  readonly pendingChanges: number | null;
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
  if (!/^\d{4}-\d{2}-\d{2}T/.test(result) || !Number.isFinite(Date.parse(result))) throw new Error(`Invalid inventory ${label}`);
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
  if (payload.execution_authority === true || payload.mutation_authority === true) throw new Error("Inventory projection cannot grant authority");
  if (!["fresh", "stale", "unknown"].includes(String(payload.freshness))) throw new Error("Invalid inventory freshness");
  if (typeof payload.truncated !== "boolean") throw new Error("Invalid inventory truncation");
  const kind = payload.observation_kind;
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
  const resources = rows.filter((row) => !containers.has(row.type)).map((row): DashboardResource => {
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
      if (ancestor.type === "resource-group") group = ancestor;
      if (ancestor.type === "subscription") subscription = ancestor;
      parent = ancestor.parentId;
    }
    return { ...row, group: group?.id ?? null, groupLabel: group?.name ?? null, subscription: subscription?.id ?? null, subscriptionLabel: subscription?.name ?? null };
  });
  const realtime = payload.realtime === undefined ? null : record(payload.realtime, "realtime metadata");
  const pending = realtime?.pending_changes;
  if (pending !== undefined && (typeof pending !== "number" || !Number.isSafeInteger(pending) || pending < 0)) throw new Error("Invalid inventory pending count");
  return {
    id: optionalText(payload.snapshot_id, "snapshot id"),
    at: timestamp(payload.snapshot_at, "snapshot time"),
    source: optionalText(payload.source, "source"),
    scope: optionalText(payload.scope, "scope"),
    freshness: payload.freshness as DashboardSnapshot["freshness"],
    observationKind: kind ?? null,
    truncated: payload.truncated,
    limitations: [...strings(payload.truncation_reasons, "truncation reasons"), ...strings(payload.coverage_gaps, "coverage gaps")],
    resources,
    excludedContainers: rows.length - resources.length,
    pendingChanges: typeof pending === "number" ? pending : null,
  };
}

/** Never equates provisioning success or generic health labels with running or availability. */
export function dashboardResourceState(resource: DashboardResource, snapshot: DashboardSnapshot, lens: DashboardLens): DashboardState {
  if (lens === "availability") return "unknown";
  if (lens === "observation") return snapshot.observationKind === "OBSERVED" ? snapshot.freshness : "unknown";
  const status = resource.status.trim().toLowerCase().replace(/^powerstate\//, "");
  if (status === "not-applicable") return "not-applicable";
  if (snapshot.freshness !== "fresh" || snapshot.observationKind !== "OBSERVED") return "unknown";
  if (status === "running" || status === "stopped" || status === "deallocated") return status;
  if (["starting", "stopping", "deallocating"].includes(status)) return "transitioning";
  return "unknown";
}

export function dashboardTypeLabel(resource: DashboardResource): string {
  const label = resourceTypeLabelOf(resource);
  return label === "Resource" ? resource.type : label;
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
  readonly status: DashboardState | "";
}

export const EMPTY_DASHBOARD_FILTERS: DashboardFilters = { subscription: "", group: "", type: "", query: "", status: "" };

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
