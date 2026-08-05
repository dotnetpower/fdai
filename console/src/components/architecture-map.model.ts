import { routeHref } from "../router";
import { hasArchitectureResourceAbbreviation } from "./architecture-resource-abbreviations";

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
  readonly collapsed_count?: number;
  readonly network_plane_id?: string;
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
export const DEFAULT_ARCHITECTURE_CAMERA_VIEW: ArchitectureCameraView = "iso";

export interface ArchitectureDisplayOptions {
  readonly showConnections: boolean;
  readonly showReflections: boolean;
  readonly showLabels: boolean;
  readonly showGrid: boolean;
}

export const DEFAULT_ARCHITECTURE_DISPLAY_OPTIONS: ArchitectureDisplayOptions = {
  showConnections: true,
  showReflections: true,
  showLabels: true,
  showGrid: false,
};

export interface InventoryGraphResponse {
  readonly snapshot_at: string;
  readonly freshness: "fresh" | "stale" | "unknown";
  readonly source?: string;
  readonly scope: string | null;
  readonly root?: string | null;
  readonly depth: number;
  readonly limit?: number;
  readonly included_link_types: readonly string[];
  readonly resources: readonly InventoryResource[];
  readonly links: readonly InventoryLink[];
  readonly truncated: boolean;
  readonly truncation_reasons?: readonly string[];
  readonly cursor?: string | null;
  readonly cache?: {
    readonly status: "fresh" | "stale" | "refreshing";
    readonly age_seconds: number;
    readonly persistent: boolean;
  };
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
  | "network-interface"
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
  | "lane"
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
  "compute.container-app-job": "runtime",
  "compute.container-app-environment": "runtime",
  "function-app": "runtime",
  "app-service-plan": "runtime",
  "static-web-app": "runtime",
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
  "compute.vm-shutdown-schedule": "runtime",
  "compute.vm-scale-set": "runtime",
  "compute.container-app": "runtime",
  "compute.function": "runtime",
  "compute.web-app": "runtime",
  "workflow.logic-app": "runtime",
  "kubernetes-cluster": "runtime",
  "kubernetes-node-pool": "runtime",
  "llm-endpoint": "runtime",
  "network.vnet": "network",
  "network.subnet": "network",
  "network.nsg": "security",
  "network.firewall": "security",
  "network.interface": "network",
  "network.private-endpoint": "network",
  "network.load-balancer": "network",
  "network.application-gateway": "network",
  "api-gateway": "network",
  "network.dns-zone": "network",
  "network.public-ip": "network",
  "network.nat-gateway": "network",
  "network.private-dns-zone": "network",
  "network.private-dns-zone-link": "network",
  "network.dns-resolver": "network",
  "network.dns-resolver-inbound-endpoint": "network",
  "network.virtual-network-gateway": "network",
  "diagnostic-settings": "observability",
  "file-share": "data",
  disk: "data",
  "container-registry": "data",
  "nosql-database": "data",
  cache: "data",
  "redis-enterprise": "data",
  "managed-identity": "security",
  certificate: "security",
  "log-workspace": "observability",
  "metrics-workspace": "observability",
  "application-insights": "observability",
  "data-collection-rule": "observability",
  "event-grid-topic": "messaging",
  "communication-service": "messaging",
  "email-service": "messaging",
  "email-domain": "messaging",
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
  "compute.container-app-job": "container-app",
  "compute.container-app-environment": "container-app",
  "function-app": "function-app",
  "app-service-plan": "app-service",
  "static-web-app": "app-service",
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
  "compute.vm-shutdown-schedule": "virtual-machine",
  "compute.vm-scale-set": "vm-scale-set",
  "compute.container-app": "container-app",
  "compute.function": "function-app",
  "compute.web-app": "app-service",
  "workflow.logic-app": "app-service",
  "kubernetes-cluster": "aks",
  "kubernetes-node-pool": "aks",
  "llm-endpoint": "app-service",
  "network.vnet": "virtual-network",
  "network.subnet": "subnet",
  "network.nsg": "network-security",
  "network.firewall": "firewall",
  "network.interface": "network-interface",
  "network.private-endpoint": "private-endpoint",
  "network.load-balancer": "load-balancer",
  "network.application-gateway": "application-gateway",
  "api-gateway": "application-gateway",
  "network.dns-zone": "dns-zone",
  "network.public-ip": "public-ip",
  "network.nat-gateway": "load-balancer",
  "network.private-dns-zone": "dns-zone",
  "network.private-dns-zone-link": "dns-zone",
  "network.dns-resolver": "dns-zone",
  "network.dns-resolver-inbound-endpoint": "dns-zone",
  "network.virtual-network-gateway": "application-gateway",
  "diagnostic-settings": "diagnostic-settings",
  "file-share": "file-share",
  disk: "disk",
  "container-registry": "storage",
  "nosql-database": "cosmos-db",
  cache: "redis",
  "redis-enterprise": "redis",
  "managed-identity": "managed-identity",
  certificate: "certificate",
  "log-workspace": "log-analytics",
  "metrics-workspace": "azure-monitor",
  "application-insights": "azure-monitor",
  "data-collection-rule": "azure-monitor",
  "event-grid-topic": "event-hub",
  "communication-service": "service-bus",
  "email-service": "service-bus",
  "email-domain": "service-bus",
};

export const RESOURCE_COLOR_TOKENS: Readonly<
  Record<ArchitectureResourceColorToken, { readonly label: string; readonly color: string }>
> = {
  generic: { label: "Other resource", color: "#697586" },
  subscription: { label: "Subscription", color: "#FF9300" },
  "resource-group": { label: "Resource group", color: "#50E6FF" },
  "virtual-network": { label: "Virtual network", color: "#5E9624" },
  "network-interface": { label: "Network interface", color: "#3A7D44" },
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
  "network.nat-gateway",
  "network.virtual-network-gateway",
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
  "network.interface",
  "network.private-dns-zone",
  "network.private-dns-zone-link",
  "network.dns-resolver",
  "network.dns-resolver-inbound-endpoint",
  "managed-identity",
  "certificate",
]);
const NETWORK_LANE_TYPES = new Set([
  "subnet",
  "virtual-network",
  "network.subnet",
  "network.vnet",
]);
const AUXILIARY_TYPES = new Set([
  "app-service-plan",
  "application-insights",
  "certificate",
  "compute.container-app-job",
  "diagnostic-settings",
  "email-domain",
  "file-share",
  "kubernetes-node-pool",
  "managed-identity",
  "network.dns-resolver-inbound-endpoint",
  "network.private-dns-zone-link",
]);
const SHAPE_GEOMETRY: Readonly<Record<ArchitectureNodeShape, ArchitectureNodeGeometry>> = {
  block: { width: 1.04, depth: .76, height: .34 },
  compact: { width: .88, depth: .72, height: .34 },
  cylinder: { width: .92, depth: .92, height: .34 },
  gateway: { width: 1.32, depth: .64, height: .22 },
  hexagon: { width: 1.02, depth: .88, height: .32 },
  lane: { width: 2.5, depth: .72, height: .05 },
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

export function resourceTypeLabelOf(resource: InventoryResource): string {
  return RESOURCE_COLOR_TOKENS[resourceColorTokenOf(resource)].label;
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
  return type in TYPE_LAYER && type in TYPE_COLOR_TOKEN
    && hasArchitectureResourceAbbreviation(type);
}

export const ARCHITECTURE_VISUAL_RESOURCE_TYPES = Object.freeze(Object.keys(TYPE_LAYER));

export function isRegion(resource: InventoryResource): boolean {
  return resource.w !== undefined && resource.h !== undefined;
}

export function shapeOf(resource: InventoryResource): ArchitectureNodeShape {
  if (NETWORK_LANE_TYPES.has(resource.type)) return "lane";
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

export function architectureViewIsFocused(
  graph: Pick<InventoryGraphResponse, "active_view" | "views">,
): boolean {
  const activeView = graph.views?.find((view) => view.id === graph.active_view);
  return activeView !== undefined && activeView.kind !== "fdai";
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

export function isAuxiliaryArchitectureResource(resource: InventoryResource): boolean {
  return AUXILIARY_TYPES.has(resource.type);
}

export function architecturePresentationGraph(
  graph: InventoryGraphResponse,
  selectedId: string | null,
): InventoryGraphResponse {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const visibleIds = new Set(
    graph.resources
      .filter((resource) => isRegion(resource) || !isAuxiliaryArchitectureResource(resource))
      .map((resource) => resource.id),
  );
  if (selectedId && byId.has(selectedId)) {
    visibleIds.add(selectedId);
    for (const resource of graph.resources) {
      if (resource.parent_id === selectedId) visibleIds.add(resource.id);
    }
    for (const link of graph.links) {
      if (link.source === selectedId) visibleIds.add(link.target);
      if (link.target === selectedId) visibleIds.add(link.source);
    }
  }

  const collapsedByOwner = new Map<string, number>();
  for (const resource of graph.resources) {
    if (!isAuxiliaryArchitectureResource(resource) || visibleIds.has(resource.id)) continue;
    const semanticOwner = graph.links
      .filter((link) => link.type !== "contains")
      .map((link) => link.source === resource.id
        ? link.target
        : link.target === resource.id ? link.source : null)
      .find((resourceId): resourceId is string =>
        resourceId !== null && visibleIds.has(resourceId));
    const ownerId = semanticOwner ?? resource.parent_id;
    if (ownerId && visibleIds.has(ownerId)) {
      collapsedByOwner.set(ownerId, (collapsedByOwner.get(ownerId) ?? 0) + 1);
    }
  }

  return {
    ...graph,
    resources: graph.resources
      .filter((resource) => visibleIds.has(resource.id))
      .map((resource) => {
        const collapsedCount = collapsedByOwner.get(resource.id);
        return collapsedCount === undefined
          ? resource
          : { ...resource, collapsed_count: collapsedCount };
      }),
    links: graph.links.filter((link) =>
      visibleIds.has(link.source) && visibleIds.has(link.target)),
  };
}

interface ArchitectureChildPlacement {
  readonly child: InventoryResource;
  readonly column: number;
  readonly row: number;
  readonly span: number;
}

function packArchitectureChildren(
  children: readonly InventoryResource[],
  columns: number,
): { readonly placements: readonly ArchitectureChildPlacement[]; readonly rows: number } {
  const placements: ArchitectureChildPlacement[] = [];
  let slot = 0;
  for (const child of children) {
    const span = shapeOf(child) === "lane"
      ? 2
      : 1 + Math.min(2, child.collapsed_count ?? 0);
    if (slot % columns + span > columns) slot += columns - slot % columns;
    placements.push({ child, column: slot % columns, row: Math.floor(slot / columns), span });
    slot += span;
  }
  return { placements, rows: Math.max(1, Math.ceil(slot / columns)) };
}

function compareArchitectureChildren(
  first: InventoryResource,
  second: InventoryResource,
): number {
  const layerDifference = ARCHITECTURE_LAYERS.indexOf(layerOf(first)) -
    ARCHITECTURE_LAYERS.indexOf(layerOf(second));
  if (layerDifference !== 0) return layerDifference;
  const laneDifference = Number(shapeOf(second) === "lane") - Number(shapeOf(first) === "lane");
  if (laneDifference !== 0) return laneDifference;
  return first.type.localeCompare(second.type) || first.name.localeCompare(second.name);
}

export function expandSimpleResourceGroupPanels(
  graph: InventoryGraphResponse,
): InventoryGraphResponse {
  const resources = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const regions = graph.resources.filter(isRegion);

  for (const parent of regions.filter((resource) => resource.type === "subscription")) {
    const groups = graph.resources
      .filter((resource) => resource.type === "resource-group" && resource.parent_id === parent.id)
      .sort((first, second) => (first.y ?? 0) - (second.y ?? 0) || (first.x ?? 0) - (second.x ?? 0));
    if (groups.length === 0) continue;
    const directChildren = groups.map((group) => graph.resources
      .filter((resource) => resource.parent_id === group.id)
      .sort(compareArchitectureChildren));
    if (directChildren.some((children) => children.some(isRegion))) continue;

    const parentX = parent.x ?? 0;
    const parentY = parent.y ?? 0;
    const panelGap = .45;
    const parentInsetX = .45;
    const parentInsetTop = .85;
    const parentInsetBottom = .4;
    const childInsetX = .45;
    const childInsetTop = .75;
    const childInsetBottom = .35;
    const cellWidth = 1.65;
    const cellHeight = 1.2;
    const panels = groups.map((group, index) => {
      const children = directChildren[index] ?? [];
      const occupiedSlots = children.reduce(
        (total, child) => total + (shapeOf(child) === "lane"
          ? 2
          : 1 + Math.min(2, child.collapsed_count ?? 0)),
        0,
      );
      const childColumns = Math.min(6, Math.max(2, Math.ceil(Math.sqrt(occupiedSlots))));
      const packed = packArchitectureChildren(children, childColumns);
      return {
        group,
        placements: packed.placements,
        childColumns,
        width: Math.max(4.8, childInsetX * 2 + childColumns * cellWidth),
        height: Math.max(
          3.4,
          childInsetTop + childInsetBottom + packed.rows * cellHeight,
        ),
      };
    }).sort((first, second) =>
      second.width * second.height - first.width * first.height ||
      first.group.name.localeCompare(second.group.name));
    const targetContentWidth = Math.max(
      ...panels.map((panel) => panel.width),
      Math.sqrt(panels.reduce((total, panel) => total + panel.width * panel.height, 0)) * 1.9,
    );
    const innerX = parentX + parentInsetX;
    let x = innerX;
    let y = parentY + parentInsetTop;
    let rowHeight = 0;
    let maximumRight = innerX;
    let maximumBottom = y;

    for (const panel of panels) {
      if (x > innerX && x + panel.width > innerX + targetContentWidth) {
        x = innerX;
        y += rowHeight + panelGap;
        rowHeight = 0;
      }
      resources.set(panel.group.id, {
        ...panel.group,
        x,
        y,
        w: panel.width,
        h: panel.height,
      });
      panel.placements.forEach(({ child, column, row, span }) => {
          const centerOffset = shapeOf(child) === "lane" ? span / 2 : .5;
          resources.set(child.id, {
            ...child,
            render_scale: Math.max(1, child.render_scale ?? 1),
            x: x + childInsetX + (column + centerOffset) * cellWidth,
            y: y + childInsetTop + (row + .5) * cellHeight,
          });
        });
      maximumRight = Math.max(maximumRight, x + panel.width);
      maximumBottom = Math.max(maximumBottom, y + panel.height);
      rowHeight = Math.max(rowHeight, panel.height);
      x += panel.width + panelGap;
    }
    resources.set(parent.id, {
      ...parent,
      w: architectureViewIsFocused(graph)
        ? maximumRight - parentX + parentInsetX
        : Math.max(parent.w ?? 0, maximumRight - parentX + parentInsetX),
      h: architectureViewIsFocused(graph)
        ? maximumBottom - parentY + parentInsetBottom
        : Math.max(parent.h ?? 0, maximumBottom - parentY + parentInsetBottom),
    });
  }

  return { ...graph, resources: graph.resources.map((resource) => resources.get(resource.id)!) };
}

export function constrainGraph(graph: InventoryGraphResponse): InventoryGraphResponse {
  const expandedGraph = expandSimpleResourceGroupPanels(graph);
  const byId = new Map(expandedGraph.resources.map((resource) => [resource.id, resource]));
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
      resource.render_scale ?? 1,
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

  return {
    ...expandedGraph,
    resources: expandedGraph.resources.map((resource) => constrain(resource)),
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}
