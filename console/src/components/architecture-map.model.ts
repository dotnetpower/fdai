import { routeHref } from "../router";

export interface InventoryResource {
  readonly id: string;
  readonly type: string;
  readonly name: string;
  readonly status: string;
  readonly parent_id?: string;
  readonly x?: number;
  readonly y?: number;
  readonly w?: number;
  readonly h?: number;
  readonly render_scale?: number;
}

export interface InventoryLink {
  readonly source: string;
  readonly target: string;
  readonly type: "contains" | "attached_to" | "depends_on";
}

export interface ArchitectureView {
  readonly id: string;
  readonly label: string;
  readonly kind: "fdai" | "service" | "resource_group";
  readonly classification: "ownership_tag" | "service_tag" | "resource_group_fallback";
  readonly description: string;
  readonly root_resource_id: string;
}

export type ArchitectureCameraView = "iso" | "top" | "front";

export interface ArchitectureDisplayOptions {
  readonly showConnections: boolean;
  readonly showReflections: boolean;
  readonly showLabels: boolean;
  readonly showGrid: boolean;
}

export interface InventoryGraphResponse {
  readonly snapshot_at: string;
  readonly freshness: "fresh" | "stale" | "unknown";
  readonly source?: string;
  readonly scope: string | null;
  readonly depth: number;
  readonly included_link_types: readonly string[];
  readonly resources: readonly InventoryResource[];
  readonly links: readonly InventoryLink[];
  readonly truncated: boolean;
  readonly cursor?: string | null;
  readonly realtime?: {
    readonly pending_changes: number;
    readonly latest_at: string | null;
  };
  readonly active_view?: string;
  readonly views?: readonly ArchitectureView[];
}

export type ArchitectureLayer =
  | "scope"
  | "network"
  | "security"
  | "runtime"
  | "data"
  | "messaging"
  | "observability";
export type ArchitectureResourceColorToken =
  | "generic"
  | "subscription"
  | "resource-group"
  | "virtual-network"
  | "subnet"
  | "front-door"
  | "application-gateway"
  | "load-balancer"
  | "firewall"
  | "network-security"
  | "key-vault"
  | "app-service"
  | "container-app"
  | "function-app"
  | "aks"
  | "database"
  | "redis"
  | "storage"
  | "event-hub"
  | "service-bus"
  | "virtual-machine"
  | "vm-scale-set"
  | "private-endpoint"
  | "dns-zone"
  | "public-ip"
  | "diagnostic-settings"
  | "file-share"
  | "disk"
  | "cosmos-db"
  | "managed-identity"
  | "certificate"
  | "log-analytics"
  | "azure-monitor";
export type ArchitectureNodeShape =
  | "block"
  | "compact"
  | "cylinder"
  | "gateway"
  | "hexagon"
  | "slab";

export interface ArchitectureNodeGeometry {
  readonly width: number;
  readonly depth: number;
  readonly height: number;
}

export const ARCHITECTURE_LAYERS: readonly ArchitectureLayer[] = [
  "scope",
  "network",
  "security",
  "runtime",
  "data",
  "messaging",
  "observability",
];

const TYPE_LAYER: Readonly<Record<string, ArchitectureLayer>> = {
  subscription: "scope",
  "resource-group": "scope",
  "virtual-network": "network",
  subnet: "network",
  "front-door": "network",
  "application-gateway": "network",
  "web-application-firewall": "security",
  waf: "security",
  firewall: "security",
  "key-vault": "security",
  "secret-store": "security",
  "network-security-group": "security",
  nsg: "security",
  "load-balancer": "network",
  "l4-load-balancer": "network",
  "app-service": "runtime",
  "container-app": "runtime",
  "function-app": "runtime",
  "aks-cluster": "runtime",
  postgresql: "data",
  "postgresql-server": "data",
  "mysql-server": "data",
  "sql-database": "data",
  redis: "data",
  "storage-account": "data",
  "object-storage": "data",
  "event-hub": "messaging",
  "event-hubs": "messaging",
  "service-bus": "messaging",
  queue: "messaging",
  "message-queue": "messaging",
  kafka: "messaging",
  "compute.vm": "runtime",
  "compute.vm-scale-set": "runtime",
  "compute.container-app": "runtime",
  "compute.function": "runtime",
  "kubernetes-cluster": "runtime",
  "kubernetes-node-pool": "runtime",
  "llm-endpoint": "runtime",
  "network.vnet": "network",
  "network.subnet": "network",
  "network.nsg": "security",
  "network.private-endpoint": "network",
  "network.load-balancer": "network",
  "network.application-gateway": "network",
  "api-gateway": "network",
  "network.dns-zone": "network",
  "network.public-ip": "network",
  "diagnostic-settings": "observability",
  "file-share": "data",
  disk: "data",
  "nosql-database": "data",
  cache: "data",
  "managed-identity": "security",
  certificate: "security",
  "log-workspace": "observability",
  "metrics-workspace": "observability",
};

const TYPE_COLOR_TOKEN: Readonly<Record<string, ArchitectureResourceColorToken>> = {
  subscription: "subscription",
  "resource-group": "resource-group",
  "virtual-network": "virtual-network",
  subnet: "subnet",
  "front-door": "front-door",
  "application-gateway": "application-gateway",
  "web-application-firewall": "application-gateway",
  waf: "application-gateway",
  "load-balancer": "load-balancer",
  "l4-load-balancer": "load-balancer",
  firewall: "firewall",
  "network-security-group": "network-security",
  nsg: "network-security",
  "key-vault": "key-vault",
  "secret-store": "key-vault",
  "app-service": "app-service",
  "container-app": "container-app",
  "function-app": "function-app",
  "aks-cluster": "aks",
  postgresql: "database",
  "postgresql-server": "database",
  "mysql-server": "database",
  "sql-database": "database",
  redis: "redis",
  "storage-account": "storage",
  "object-storage": "storage",
  "event-hub": "event-hub",
  "event-hubs": "event-hub",
  "service-bus": "service-bus",
  queue: "service-bus",
  "message-queue": "service-bus",
  kafka: "service-bus",
  "compute.vm": "virtual-machine",
  "compute.vm-scale-set": "vm-scale-set",
  "compute.container-app": "container-app",
  "compute.function": "function-app",
  "kubernetes-cluster": "aks",
  "kubernetes-node-pool": "aks",
  "llm-endpoint": "app-service",
  "network.vnet": "virtual-network",
  "network.subnet": "subnet",
  "network.nsg": "network-security",
  "network.private-endpoint": "private-endpoint",
  "network.load-balancer": "load-balancer",
  "network.application-gateway": "application-gateway",
  "api-gateway": "application-gateway",
  "network.dns-zone": "dns-zone",
  "network.public-ip": "public-ip",
  "diagnostic-settings": "diagnostic-settings",
  "file-share": "file-share",
  disk: "disk",
  "nosql-database": "cosmos-db",
  cache: "redis",
  "managed-identity": "managed-identity",
  certificate: "certificate",
  "log-workspace": "log-analytics",
  "metrics-workspace": "azure-monitor",
};

export const RESOURCE_COLOR_TOKENS: Readonly<
  Record<ArchitectureResourceColorToken, { readonly label: string; readonly color: string }>
> = {
  generic: { label: "Other resource", color: "#697586" },
  subscription: { label: "Subscription", color: "#FF9300" },
  "resource-group": { label: "Resource group", color: "#50E6FF" },
  "virtual-network": { label: "Virtual network", color: "#5E9624" },
  subnet: { label: "Subnet", color: "#1490DF" },
  "front-door": { label: "Front Door", color: "#5EA0EF" },
  "application-gateway": { label: "App Gateway", color: "#76BC2D" },
  "load-balancer": { label: "Load Balancer", color: "#5F9724" },
  firewall: { label: "Firewall", color: "#E62323" },
  "network-security": { label: "NSG", color: "#1490DF" },
  "key-vault": { label: "Key Vault", color: "#FF9300" },
  "app-service": { label: "App Service", color: "#0078D4" },
  "container-app": { label: "Container Apps", color: "#773ADC" },
  "function-app": { label: "Functions", color: "#C19C00" },
  aks: { label: "AKS", color: "#5C2D91" },
  database: { label: "SQL and PostgreSQL", color: "#005BA1" },
  redis: { label: "Redis", color: "#0071C8" },
  storage: { label: "Storage", color: "#37C2B1" },
  "event-hub": { label: "Event Hubs", color: "#76BC2D" },
  "service-bus": { label: "Service Bus", color: "#32BEDD" },
  "virtual-machine": { label: "Virtual machines", color: "#0078D4" },
  "vm-scale-set": { label: "VM scale sets", color: "#1490DF" },
  "private-endpoint": { label: "Private Endpoint", color: "#32BEDD" },
  "dns-zone": { label: "DNS Zone", color: "#5EA0EF" },
  "public-ip": { label: "Public IP", color: "#AD52E3" },
  "diagnostic-settings": { label: "Diagnostic settings", color: "#155EA1" },
  "file-share": { label: "File Share", color: "#773ADC" },
  disk: { label: "Managed disks", color: "#5EA0EF" },
  "cosmos-db": { label: "Cosmos DB", color: "#32BEDD" },
  "managed-identity": { label: "Managed Identity", color: "#1988D9" },
  certificate: { label: "Certificates", color: "#D15900" },
  "log-analytics": { label: "Log Analytics", color: "#A997E2" },
  "azure-monitor": { label: "Azure Monitor", color: "#155EA1" },
};

const CYLINDER_TYPES = new Set([
  "postgresql",
  "postgresql-server",
  "mysql-server",
  "sql-database",
  "nosql-database",
]);
const GATEWAY_TYPES = new Set([
  "front-door",
  "application-gateway",
  "web-application-firewall",
  "waf",
  "load-balancer",
  "l4-load-balancer",
  "network.load-balancer",
  "network.application-gateway",
  "api-gateway",
]);
const SLAB_TYPES = new Set(["storage-account", "object-storage", "file-share", "disk"]);
const HEXAGON_TYPES = new Set([
  "event-hub",
  "event-hubs",
  "service-bus",
  "queue",
  "message-queue",
  "kafka",
]);
const COMPACT_TYPES = new Set([
  "key-vault",
  "secret-store",
  "firewall",
  "network-security-group",
  "nsg",
  "network.nsg",
  "network.private-endpoint",
  "network.public-ip",
  "managed-identity",
  "certificate",
]);
const SHAPE_GEOMETRY: Readonly<Record<ArchitectureNodeShape, ArchitectureNodeGeometry>> = {
  block: { width: 1.04, depth: .76, height: .34 },
  compact: { width: .88, depth: .72, height: .34 },
  cylinder: { width: .92, depth: .92, height: .34 },
  gateway: { width: 1.32, depth: .64, height: .22 },
  hexagon: { width: 1.02, depth: .88, height: .32 },
  slab: { width: 1.08, depth: .82, height: .22 },
};

export function layerOf(resource: InventoryResource): ArchitectureLayer {
  return TYPE_LAYER[resource.type] ?? "runtime";
}

export function resourceColorTokenOf(
  resource: InventoryResource,
): ArchitectureResourceColorToken {
  return TYPE_COLOR_TOKEN[resource.type] ?? "generic";
}

export function resourceColorOf(resource: InventoryResource): string {
  return RESOURCE_COLOR_TOKENS[resourceColorTokenOf(resource)].color;
}

export function relatedResourceIds(
  graph: Pick<InventoryGraphResponse, "resources" | "links">,
  selectedId: string | null,
): ReadonlySet<string> | undefined {
  if (selectedId === null || !graph.resources.some((resource) => resource.id === selectedId)) {
    return undefined;
  }
  const related = new Set<string>([selectedId]);
  const selected = graph.resources.find((resource) => resource.id === selectedId);
  if (selected?.parent_id) related.add(selected.parent_id);
  for (const resource of graph.resources) {
    if (resource.parent_id === selectedId) related.add(resource.id);
  }
  for (const link of graph.links) {
    if (link.source === selectedId) related.add(link.target);
    if (link.target === selectedId) related.add(link.source);
  }
  return related;
}

export function hasExplicitVisualMapping(type: string): boolean {
  return type in TYPE_LAYER && type in TYPE_COLOR_TOKEN;
}

export function isRegion(resource: InventoryResource): boolean {
  return resource.w !== undefined && resource.h !== undefined;
}

export function shapeOf(resource: InventoryResource): ArchitectureNodeShape {
  if (CYLINDER_TYPES.has(resource.type)) return "cylinder";
  if (GATEWAY_TYPES.has(resource.type)) return "gateway";
  if (SLAB_TYPES.has(resource.type)) return "slab";
  if (HEXAGON_TYPES.has(resource.type)) return "hexagon";
  if (COMPACT_TYPES.has(resource.type)) return "compact";
  return "block";
}

export function geometryOf(resource: InventoryResource): ArchitectureNodeGeometry {
  const geometry = SHAPE_GEOMETRY[shapeOf(resource)];
  const scale = resource.render_scale ?? 1;
  return {
    width: geometry.width * scale,
    depth: geometry.depth * scale,
    height: geometry.height * scale,
  };
}

export function architectureHref(resourceId?: string, viewId?: string | null): string {
  return routeHref("architecture", {
    params: { resource: resourceId, view: viewId },
  });
}

export function selectedResourceIdFromHash(value: string): string | null {
  const queryIndex = value.indexOf("?");
  const search = queryIndex >= 0 ? value.slice(queryIndex + 1) : value.replace(/^\?/, "");
  return new URLSearchParams(search).get("resource");
}

export function architectureViewFromHash(value: string): string | null {
  const queryIndex = value.indexOf("?");
  const search = queryIndex >= 0 ? value.slice(queryIndex + 1) : value.replace(/^\?/, "");
  return new URLSearchParams(search).get("view");
}

export function architectureViewKindLabel(view: ArchitectureView): string {
  if (view.kind === "fdai") return "FDAI";
  if (view.kind === "service") return "Service";
  return "Resource group";
}

export function graphSubset(
  graph: InventoryGraphResponse,
  visibleLayers: ReadonlySet<ArchitectureLayer>,
): InventoryGraphResponse {
  const resources = graph.resources.filter((resource) => visibleLayers.has(layerOf(resource)));
  const ids = new Set(resources.map((resource) => resource.id));
  return {
    ...graph,
    resources,
    links: graph.links.filter((link) => ids.has(link.source) && ids.has(link.target)),
  };
}

export function constrainGraph(graph: InventoryGraphResponse): InventoryGraphResponse {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const resolved = new Map<string, InventoryResource>();

  function constrain(resource: InventoryResource, trail = new Set<string>()): InventoryResource {
    const cached = resolved.get(resource.id);
    if (cached) return cached;
    if (!resource.parent_id || trail.has(resource.id)) {
      resolved.set(resource.id, resource);
      return resource;
    }
    const rawParent = byId.get(resource.parent_id);
    if (!rawParent || rawParent.x === undefined || rawParent.y === undefined ||
        rawParent.w === undefined || rawParent.h === undefined) {
      resolved.set(resource.id, resource);
      return resource;
    }
    const nextTrail = new Set(trail);
    nextTrail.add(resource.id);
    const parent = constrain(rawParent, nextTrail);
    const parentX = parent.x ?? rawParent.x;
    const parentY = parent.y ?? rawParent.y;
    const parentW = parent.w ?? rawParent.w;
    const parentH = parent.h ?? rawParent.h;
    if (isRegion(resource)) {
      const inset = .12;
      const x = clamp(resource.x ?? parentX, parentX + inset, parentX + parentW - inset);
      const y = clamp(resource.y ?? parentY, parentY + inset, parentY + parentH - inset);
      const w = clamp(resource.w ?? 1, .5, parentX + parentW - inset - x);
      const h = clamp(resource.h ?? 1, .5, parentY + parentH - inset - y);
      const constrained = { ...resource, x, y, w, h };
      resolved.set(resource.id, constrained);
      return constrained;
    }
    const geometry = SHAPE_GEOMETRY[shapeOf(resource)];
    const availableWidth = Math.max(.1, parentW - .12);
    const availableDepth = Math.max(.1, parentH - .12);
    const renderScale = Math.min(
      1,
      availableWidth / geometry.width,
      availableDepth / geometry.depth,
    );
    const scaledWidth = geometry.width * renderScale;
    const scaledDepth = geometry.depth * renderScale;
    const halfWidth = scaledWidth / 2 + .06;
    const halfDepth = scaledDepth / 2 + .06;
    const constrained = {
      ...resource,
      render_scale: renderScale,
      x: clamp(resource.x ?? parentX, parentX + halfWidth, parentX + parentW - halfWidth),
      y: clamp(resource.y ?? parentY, parentY + halfDepth, parentY + parentH - halfDepth),
    };
    resolved.set(resource.id, constrained);
    return constrained;
  }

  return { ...graph, resources: graph.resources.map((resource) => constrain(resource)) };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}
