import type { InventoryGraphResponse, InventoryResource } from "./architecture-map.model";
import { isArchitectureBoundaryResource } from "./architecture-boundaries";
import {
  architectureLayoutTargetWidth,
  packArchitectureRectangles,
  type PackedItem,
  type RectangleItem,
} from "./architecture-rectangle-pack";
import {
  ARCHITECTURE_TOPOLOGY_COLUMN_PITCH,
  ARCHITECTURE_TOPOLOGY_ROW_PITCH,
} from "./architecture-topology-dimensions";

const BOUNDARY_INSET_X = .45;
const BOUNDARY_HEADER = .85;
const BOUNDARY_BOTTOM = .4;
const ITEM_GAP = .45;

interface LayoutPlan extends RectangleItem {
  readonly resource: InventoryResource;
  readonly boundary: boolean;
  readonly children: readonly PackedItem<LayoutPlan>[];
}

/** Generates presentation-only geometry when an inventory projection provides none. */
export function layoutGeometrylessArchitectureGraph(
  graph: InventoryGraphResponse,
): InventoryGraphResponse {
  if (graph.resources.every(resourceHasCompleteGeometry)) return graph;
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const parentById = architecturePresentationParentById(graph, byId);
  const childrenById = new Map<string, InventoryResource[]>();
  for (const resource of graph.resources) {
    const parentId = parentById.get(resource.id);
    if (!parentId || !byId.has(parentId) || parentId === resource.id) continue;
    const children = childrenById.get(parentId) ?? [];
    children.push(resource);
    childrenById.set(parentId, children);
  }
  const childIds = new Set([...childrenById.values()].flatMap((resources) =>
    resources.map((resource) => resource.id)));
  const roots = graph.resources.filter((resource) => !childIds.has(resource.id));
  const plans = roots.map((resource) =>
    buildLayoutPlan(resource, childrenById, new Set<string>()));
  const packedRoots = packArchitectureRectangles(
    plans,
    architectureLayoutTargetWidth(plans),
    .8,
  );
  const positioned = new Map<string, InventoryResource>();
  for (const placement of packedRoots.items) {
    applyLayoutPlan(placement.item, placement.x, placement.y, positioned);
  }
  let orphanX = packedRoots.width + 1;
  for (const resource of graph.resources) {
    if (positioned.has(resource.id)) continue;
    positioned.set(resource.id, {
      ...resource,
      x: orphanX + ARCHITECTURE_TOPOLOGY_COLUMN_PITCH / 2,
      y: ARCHITECTURE_TOPOLOGY_ROW_PITCH / 2,
    });
    orphanX += ARCHITECTURE_TOPOLOGY_COLUMN_PITCH;
  }
  return {
    ...graph,
    resources: graph.resources.map((resource) => positioned.get(resource.id) ?? resource),
  };
}

export function architecturePresentationParentById(
  graph: Pick<InventoryGraphResponse, "links" | "resources">,
  byId = new Map(graph.resources.map((resource) => [resource.id, resource])),
): ReadonlyMap<string, string> {
  const reportedParents = new Map<string, string>();
  for (const link of graph.links) {
    const source = byId.get(link.source);
    if (
      link.type !== "contains"
      || !source
      || !isArchitectureBoundaryResource(source)
    ) continue;
    const current = reportedParents.get(link.target);
    if (!current || boundaryPriority(source) > boundaryPriority(byId.get(current))) {
      reportedParents.set(link.target, link.source);
    }
  }
  return new Map(graph.resources.flatMap((resource) => {
    const parentId = resource.network_plane_id
      ?? reportedParents.get(resource.id)
      ?? resource.parent_id;
    return parentId ? [[resource.id, parentId] as const] : [];
  }));
}

function buildLayoutPlan(
  resource: InventoryResource,
  childrenById: ReadonlyMap<string, readonly InventoryResource[]>,
  trail: ReadonlySet<string>,
): LayoutPlan {
  const boundary = isArchitectureBoundaryResource(resource);
  if (!boundary || trail.has(resource.id)) {
    return {
      resource,
      boundary: false,
      children: [],
      width: ARCHITECTURE_TOPOLOGY_COLUMN_PITCH,
      height: ARCHITECTURE_TOPOLOGY_ROW_PITCH,
    };
  }
  const nextTrail = new Set(trail);
  nextTrail.add(resource.id);
  const childPlans = [...(childrenById.get(resource.id) ?? [])]
    .sort(compareResources)
    .map((child) => buildLayoutPlan(child, childrenById, nextTrail));
  const packed = packArchitectureRectangles(
    childPlans,
    architectureLayoutTargetWidth(childPlans),
    ITEM_GAP,
  );
  return {
    resource,
    boundary: true,
    children: packed.items,
    width: Math.max(4.8, packed.width + BOUNDARY_INSET_X * 2),
    height: Math.max(3.4, packed.height + BOUNDARY_HEADER + BOUNDARY_BOTTOM),
  };
}

function applyLayoutPlan(
  plan: LayoutPlan,
  x: number,
  y: number,
  positioned: Map<string, InventoryResource>,
): void {
  if (!plan.boundary) {
    positioned.set(plan.resource.id, {
      ...plan.resource,
      x: x + plan.width / 2,
      y: y + plan.height / 2,
    });
    return;
  }
  positioned.set(plan.resource.id, {
    ...plan.resource,
    x,
    y,
    w: plan.width,
    h: plan.height,
  });
  for (const placement of plan.children) {
    applyLayoutPlan(
      placement.item,
      x + BOUNDARY_INSET_X + placement.x,
      y + BOUNDARY_HEADER + placement.y,
      positioned,
    );
  }
}

function resourceHasCompleteGeometry(resource: InventoryResource): boolean {
  if (!Number.isFinite(resource.x) || !Number.isFinite(resource.y)) return false;
  return !isArchitectureBoundaryResource(resource)
    || (Number.isFinite(resource.w) && Number.isFinite(resource.h));
}

function boundaryPriority(resource: InventoryResource | undefined): number {
  if (!resource) return 0;
  if (resource.type === "subnet" || resource.type === "network.subnet") return 4;
  if (resource.type === "virtual-network" || resource.type === "network.vnet") return 3;
  if (resource.type === "resource-group") return 2;
  if (resource.type === "subscription") return 1;
  return 0;
}

function compareResources(first: InventoryResource, second: InventoryResource): number {
  return Number(!isArchitectureBoundaryResource(first))
    - Number(!isArchitectureBoundaryResource(second))
    || first.type.localeCompare(second.type)
    || first.name.localeCompare(second.name)
    || first.id.localeCompare(second.id);
}
