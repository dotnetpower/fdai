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
}

export interface InventoryLink {
  readonly source: string;
  readonly target: string;
  readonly type: "contains" | "attached_to" | "depends_on";
}

export interface ArchitectureView {
  readonly id: string;
  readonly label: string;
  readonly kind: "fdai" | "application";
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
  readonly active_view?: string;
  readonly views?: readonly ArchitectureView[];
}

export type ArchitectureLayer = "scope" | "network" | "security" | "compute" | "data";
export type ArchitectureNodeShape = "block" | "cylinder";

export const ARCHITECTURE_LAYERS: readonly ArchitectureLayer[] = [
  "scope",
  "network",
  "security",
  "compute",
  "data",
];

const TYPE_LAYER: Readonly<Record<string, ArchitectureLayer>> = {
  subscription: "scope",
  "resource-group": "scope",
  "virtual-network": "network",
  subnet: "network",
  "front-door": "security",
  "application-gateway": "security",
  firewall: "security",
  "key-vault": "security",
  "load-balancer": "network",
  "app-service": "compute",
  "container-app": "compute",
  "function-app": "compute",
  "aks-cluster": "compute",
  postgresql: "data",
  redis: "data",
  "storage-account": "data",
};

export function layerOf(resource: InventoryResource): ArchitectureLayer {
  return TYPE_LAYER[resource.type] ?? "compute";
}

export function isRegion(resource: InventoryResource): boolean {
  return resource.w !== undefined && resource.h !== undefined;
}

export function shapeOf(resource: InventoryResource): ArchitectureNodeShape {
  return resource.type === "postgresql" ? "cylinder" : "block";
}

export function architectureHref(resourceId?: string, viewId?: string | null): string {
  const params = new URLSearchParams();
  if (resourceId) params.set("resource", resourceId);
  if (viewId) params.set("view", viewId);
  const query = params.toString();
  return query ? `#/architecture?${query}` : "#/architecture";
}

export function selectedResourceIdFromHash(hash: string): string | null {
  const queryIndex = hash.indexOf("?");
  if (queryIndex < 0) return null;
  return new URLSearchParams(hash.slice(queryIndex + 1)).get("resource");
}

export function architectureViewFromHash(hash: string): string | null {
  const queryIndex = hash.indexOf("?");
  if (queryIndex < 0) return null;
  return new URLSearchParams(hash.slice(queryIndex + 1)).get("view");
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
    const halfWidth = .58;
    const halfDepth = .44;
    const constrained = {
      ...resource,
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