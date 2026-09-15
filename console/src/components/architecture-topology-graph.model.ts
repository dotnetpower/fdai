import {
  architectureNetworkOrthogonalRoute,
  architectureNetworkPeeringRoute,
  architectureNetworkRoutePath,
  type ArchitectureNetworkRouteBox,
} from "./architecture-network-route";
import {
  isRegion,
  type InventoryGraphResponse,
  type InventoryLink,
  type InventoryResource,
} from "./architecture-map.model";
import { architectureTopologyNodeDimensions } from "./architecture-topology-dimensions";
import { isArchitectureBoundaryResource } from "./architecture-boundaries";

export {
  ARCHITECTURE_TOPOLOGY_NODE_HEIGHT,
  ARCHITECTURE_TOPOLOGY_NODE_WIDTH,
} from "./architecture-topology-dimensions";

export interface ArchitectureTopologyBounds {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

export interface ArchitectureTopologyCanvasSize {
  readonly width: number;
  readonly height: number;
}

export interface ArchitectureTopologyScrollTarget {
  readonly left: number;
  readonly top: number;
}

export const ARCHITECTURE_TOPOLOGY_WORLD_UNIT = 64;
export const ARCHITECTURE_TOPOLOGY_MIN_SCALE = .28;
export const ARCHITECTURE_TOPOLOGY_MAX_SCALE = 1.8;
export const ARCHITECTURE_TOPOLOGY_SCALE_STEP = .2;

/** Returns records that cannot be represented without inventing an origin coordinate. */
export function architectureTopologyUnplacedIds(
  resources: readonly InventoryResource[],
): readonly string[] {
  return resources
    .filter((resource) => {
      if (!Number.isFinite(resource.x) || !Number.isFinite(resource.y)) return true;
      return isArchitectureBoundaryResource(resource)
        && (!Number.isFinite(resource.w) || !Number.isFinite(resource.h));
    })
    .map((resource) => resource.id);
}

/** Computes a stable world box for both scope and focused topology projections. */
export function architectureTopologyBounds(
  resources: readonly InventoryResource[],
): ArchitectureTopologyBounds {
  const boxes = resources.map(architectureTopologyResourceBox);
  const left = Math.min(0, ...boxes.map((box) => box.x)) - .5;
  const top = Math.min(0, ...boxes.map((box) => box.y)) - .8;
  const right = Math.max(1, ...boxes.map((box) => box.x + box.width)) + .5;
  const bottom = Math.max(1, ...boxes.map((box) => box.y + box.height)) + .8;
  return { x: left, y: top, width: right - left, height: bottom - top };
}

/** Converts world bounds to one deterministic unscaled SVG canvas. */
export function architectureTopologyCanvasSize(
  bounds: ArchitectureTopologyBounds,
): ArchitectureTopologyCanvasSize {
  return {
    width: Math.max(680, Math.round(bounds.width * ARCHITECTURE_TOPOLOGY_WORLD_UNIT)),
    height: Math.max(480, Math.round(bounds.height * ARCHITECTURE_TOPOLOGY_WORLD_UNIT)),
  };
}

/** Fits one complete topology without enlarging it above its authored scale. */
export function architectureTopologyFitScale(
  canvas: ArchitectureTopologyCanvasSize,
  viewportWidth: number,
  viewportHeight: number,
  padding = 24,
): number {
  return clampArchitectureTopologyScale(Math.min(
    1,
    Math.max(1, viewportWidth - padding) / canvas.width,
    Math.max(1, viewportHeight - padding) / canvas.height,
  ));
}

/** Preserves the viewport center while the operator changes topology scale. */
export function architectureTopologyZoomScrollTarget({
  scrollLeft,
  scrollTop,
  viewportWidth,
  viewportHeight,
  currentScale,
  nextScale,
}: {
  readonly scrollLeft: number;
  readonly scrollTop: number;
  readonly viewportWidth: number;
  readonly viewportHeight: number;
  readonly currentScale: number;
  readonly nextScale: number;
}): ArchitectureTopologyScrollTarget {
  const current = clampArchitectureTopologyScale(currentScale);
  const next = clampArchitectureTopologyScale(nextScale);
  const centerX = (scrollLeft + viewportWidth / 2) / current;
  const centerY = (scrollTop + viewportHeight / 2) / current;
  return {
    left: Math.max(0, centerX * next - viewportWidth / 2),
    top: Math.max(0, centerY * next - viewportHeight / 2),
  };
}

export function clampArchitectureTopologyScale(scale: number): number {
  return Math.max(
    ARCHITECTURE_TOPOLOGY_MIN_SCALE,
    Math.min(ARCHITECTURE_TOPOLOGY_MAX_SCALE, scale),
  );
}

/** Retains containment context for highlighted paths and impact scopes. */
export function architectureTopologyActiveIds(
  graph: Pick<InventoryGraphResponse, "links" | "resources">,
  highlightedIds: ReadonlySet<string> | undefined,
): ReadonlySet<string> | undefined {
  if (!highlightedIds) return undefined;
  const active = new Set(highlightedIds);
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  let changed = true;
  while (changed) {
    changed = false;
    for (const resourceId of [...active]) {
      const resource = byId.get(resourceId);
      for (const ancestorId of [resource?.network_plane_id, resource?.parent_id]) {
        if (ancestorId && !active.has(ancestorId)) {
          active.add(ancestorId);
          changed = true;
        }
      }
    }
    for (const link of graph.links) {
      if (link.type === "contains" && active.has(link.target) && !active.has(link.source)) {
        active.add(link.source);
        changed = true;
      }
    }
  }
  return active;
}

/** Routes one typed relationship between the current visual boundaries. */
export function architectureTopologyLinkRoute(
  source: InventoryResource,
  target: InventoryResource,
  resources: readonly InventoryResource[],
  relationshipType: InventoryLink["type"],
): {
  readonly path: string;
  readonly end: { readonly x: number; readonly y: number };
} {
  const sourceBox = architectureTopologyResourceBox(source);
  const targetBox = architectureTopologyResourceBox(target);
  const points = relationshipType === "peered_with" && isRegion(source) && isRegion(target)
    ? architectureNetworkPeeringRoute(sourceBox, targetBox)
    : architectureNetworkOrthogonalRoute(
        sourceBox,
        targetBox,
        resources.filter((resource) => !isRegion(resource))
          .map(architectureTopologyResourceBox),
      );
  const end = points.at(-1) ?? architectureTopologyResourcePoint(target);
  return { path: architectureNetworkRoutePath(points), end };
}

/** Splits a compact node label into no more than two bounded lines. */
export function architectureTopologyLabelLines(
  value: string,
  maximumCharacters = 16,
): readonly string[] {
  const normalized = value.trim();
  if (normalized.length <= maximumCharacters) return [normalized];
  const words = normalized.split(/\s+/);
  if (words.length === 1) return [`${normalized.slice(0, maximumCharacters - 3)}...`];
  let bestIndex = 1;
  let bestDifference = Number.POSITIVE_INFINITY;
  for (let index = 1; index < words.length; index += 1) {
    const first = words.slice(0, index).join(" ");
    const second = words.slice(index).join(" ");
    if (first.length > maximumCharacters || second.length > maximumCharacters) continue;
    const difference = Math.abs(first.length - second.length);
    if (difference < bestDifference) {
      bestIndex = index;
      bestDifference = difference;
    }
  }
  if (bestDifference < Number.POSITIVE_INFINITY) {
    return [words.slice(0, bestIndex).join(" "), words.slice(bestIndex).join(" ")];
  }
  return [
    `${normalized.slice(0, maximumCharacters - 3)}...`,
  ];
}

export function architectureTopologyRegionDepth(
  resource: InventoryResource,
  byId: ReadonlyMap<string, InventoryResource>,
): number {
  let depth = 0;
  let current = resource;
  while (current.parent_id && byId.has(current.parent_id)) {
    depth += 1;
    current = byId.get(current.parent_id)!;
  }
  return depth;
}

export function architectureTopologyResourcePoint(
  resource: InventoryResource,
): { readonly x: number; readonly y: number } {
  return {
    x: (resource.x ?? 0) + (isRegion(resource) ? (resource.w ?? 0) / 2 : 0),
    y: (resource.y ?? 0) + (isRegion(resource) ? (resource.h ?? 0) / 2 : 0),
  };
}

function architectureTopologyResourceBox(
  resource: InventoryResource,
): ArchitectureNetworkRouteBox {
  const position = architectureTopologyResourcePoint(resource);
  if (isRegion(resource)) {
    return {
      id: resource.id,
      x: resource.x ?? 0,
      y: resource.y ?? 0,
      width: resource.w ?? 2,
      height: resource.h ?? 2,
    };
  }
  const { width, height } = architectureTopologyNodeDimensions(resource.render_scale);
  return {
    id: resource.id,
    x: position.x - width / 2,
    y: position.y - height / 2,
    width,
    height,
  };
}
