import type { InventoryGraphResponse, InventoryResource } from "./architecture-map.model";
import {
  isArchitectureBoundaryResource,
  isArchitectureRenderedBoundary,
} from "./architecture-boundaries";
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
export const ARCHITECTURE_LANDSCAPE_GROUP_LIMIT = 16;
export const ARCHITECTURE_SCOPE_DETAIL_LIMIT = 36;

interface LayoutPlan extends RectangleItem {
  readonly resource: InventoryResource;
  readonly boundary: boolean;
  readonly children: readonly PackedItem<LayoutPlan>[];
}

/** Reduces the unselected view to authoritative scope boundaries with descendant counts. */
export function architectureLandscapeOverviewGraph(
  graph: InventoryGraphResponse,
): InventoryGraphResponse {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const parentById = architecturePresentationParentById(graph, byId);
  const groups = graph.resources.filter((resource) => resource.type === "resource-group");
  if (groups.length === 0) return graph;
  const descendants = new Map(groups.map((group) => [
    group.id,
    descendantCount(group.id, graph.resources, parentById),
  ]));
  const externalLinks = externalLinkCounts(graph, parentById, byId);
  const visibleGroups = [...groups]
    .sort((first, second) =>
      (descendants.get(second.id) ?? 0) - (descendants.get(first.id) ?? 0)
      || first.name.localeCompare(second.name)
      || first.id.localeCompare(second.id))
    .slice(0, ARCHITECTURE_LANDSCAPE_GROUP_LIMIT);
  const visibleIds = new Set(visibleGroups.map((resource) => resource.id));
  for (const group of visibleGroups) {
    let parentId = parentById.get(group.id);
    while (parentId && byId.has(parentId)) {
      visibleIds.add(parentId);
      parentId = parentById.get(parentId);
    }
  }
  return {
    ...graph,
    resources: graph.resources
      .filter((resource) => visibleIds.has(resource.id))
      .map((resource) => {
        const count = resource.type === "resource-group"
          ? descendants.get(resource.id)
          : descendantCount(resource.id, graph.resources, parentById);
        if (count === undefined) return resource;
        const {
          x: _x,
          y: _y,
          w: _w,
          h: _h,
          render_scale: _renderScale,
          ...semanticResource
        } = resource;
        const counted = { ...semanticResource, collapsed_count: count };
        return resource.type === "resource-group"
          ? {
              ...counted,
              external_link_count: externalLinks.get(resource.id) ?? 0,
              presentation_role: "summary" as const,
            }
          : counted;
      }),
    links: graph.links.filter((link) =>
      visibleIds.has(link.source) && visibleIds.has(link.target)),
  };
}

/** Selects one bounded, type-diverse scope around the requested Resource. */
export function architectureScopeDetailGraph(
  graph: InventoryGraphResponse,
  selectedId: string,
): InventoryGraphResponse {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const selected = byId.get(selectedId);
  if (!selected) return architectureLandscapeOverviewGraph(graph);
  const parentById = architecturePresentationParentById(graph, byId);
  const requiredIds = new Set([selectedId]);
  addAncestors(selectedId, parentById, byId, requiredIds);
  const directIds = new Set<string>();
  for (const resource of graph.resources) {
    if (parentById.get(resource.id) === selectedId) directIds.add(resource.id);
  }
  for (const link of graph.links) {
    if (link.source === selectedId) directIds.add(link.target);
    if (link.target === selectedId) directIds.add(link.source);
  }
  const scopeRootId = nearestScopeRootId(selectedId, parentById, byId);
  const scopeCandidates = graph.resources.filter((resource) =>
    resource.id !== selectedId
    && isDescendantOf(resource.id, scopeRootId, parentById));
  const directResources = typeDiverseResources(
    scopeCandidates.filter((resource) => directIds.has(resource.id)),
  );
  const selectedDirect = directResources.slice(0, ARCHITECTURE_SCOPE_DETAIL_LIMIT);
  for (const resource of selectedDirect) {
    requiredIds.add(resource.id);
    addAncestors(resource.id, parentById, byId, requiredIds);
  }
  const fillerLimit = Math.max(0, ARCHITECTURE_SCOPE_DETAIL_LIMIT - selectedDirect.length);
  const fillers = typeDiverseResources(
    scopeCandidates.filter((resource) => !directIds.has(resource.id)),
  ).slice(0, fillerLimit);
  for (const resource of fillers) {
    requiredIds.add(resource.id);
    addAncestors(resource.id, parentById, byId, requiredIds);
  }
  const selectedScopeIds = new Set([...selectedDirect, ...fillers].map((resource) => resource.id));
  return {
    ...graph,
    presentation: {
      omitted_resources: scopeCandidates.filter((resource) =>
        !selectedScopeIds.has(resource.id)).length,
      omitted_direct_relationships: Math.max(
        0,
        directResources.length - selectedDirect.length,
      ),
    },
    resources: graph.resources.filter((resource) => requiredIds.has(resource.id)),
    links: graph.links.filter((link) =>
      requiredIds.has(link.source) && requiredIds.has(link.target)),
  };
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
  byId: ReadonlyMap<string, InventoryResource> = new Map(
    graph.resources.map((resource) => [resource.id, resource]),
  ),
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
  const boundary = isArchitectureRenderedBoundary(resource);
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
    const {
      w: _w,
      h: _h,
      ...nodeResource
    } = plan.resource;
    positioned.set(plan.resource.id, {
      ...nodeResource,
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
  return !isArchitectureRenderedBoundary(resource)
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

function descendantCount(
  rootId: string,
  resources: readonly InventoryResource[],
  parentById: ReadonlyMap<string, string>,
): number {
  let count = 0;
  for (const resource of resources) {
    if (resource.id === rootId) continue;
    let parentId = parentById.get(resource.id);
    const visited = new Set<string>();
    while (parentId && !visited.has(parentId)) {
      if (parentId === rootId) {
        count += 1;
        break;
      }
      visited.add(parentId);
      parentId = parentById.get(parentId);
    }
  }
  return count;
}

function nearestScopeRootId(
  selectedId: string,
  parentById: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, InventoryResource>,
): string {
  let currentId = selectedId;
  let nearestBoundaryId = selectedId;
  const visited = new Set<string>();
  while (!visited.has(currentId)) {
    visited.add(currentId);
    const current = byId.get(currentId);
    if (current?.type === "resource-group") return currentId;
    if (current && isArchitectureBoundaryResource(current)) nearestBoundaryId = currentId;
    const parentId = parentById.get(currentId);
    if (!parentId || !byId.has(parentId)) break;
    currentId = parentId;
  }
  return nearestBoundaryId;
}

function addAncestors(
  resourceId: string,
  parentById: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, InventoryResource>,
  ids: Set<string>,
): void {
  let parentId = parentById.get(resourceId);
  const visited = new Set<string>();
  while (parentId && byId.has(parentId) && !visited.has(parentId)) {
    visited.add(parentId);
    ids.add(parentId);
    parentId = parentById.get(parentId);
  }
}

function isDescendantOf(
  resourceId: string,
  rootId: string,
  parentById: ReadonlyMap<string, string>,
): boolean {
  if (resourceId === rootId) return true;
  let parentId = parentById.get(resourceId);
  const visited = new Set<string>();
  while (parentId && !visited.has(parentId)) {
    if (parentId === rootId) return true;
    visited.add(parentId);
    parentId = parentById.get(parentId);
  }
  return false;
}

function typeDiverseResources(
  resources: readonly InventoryResource[],
): readonly InventoryResource[] {
  const byType = new Map<string, InventoryResource[]>();
  for (const resource of resources) {
    const items = byType.get(resource.type) ?? [];
    if (!items.some((item) => item.id === resource.id)) items.push(resource);
    byType.set(resource.type, items);
  }
  for (const items of byType.values()) {
    items.sort((first, second) =>
      first.name.localeCompare(second.name) || first.id.localeCompare(second.id));
  }
  const ordered: InventoryResource[] = [];
  const types = [...byType.keys()].sort();
  let index = 0;
  while (ordered.length < resources.length) {
    let added = false;
    for (const type of types) {
      const item = byType.get(type)?.[index];
      if (!item) continue;
      ordered.push(item);
      added = true;
    }
    if (!added) break;
    index += 1;
  }
  return ordered;
}

function externalLinkCounts(
  graph: Pick<InventoryGraphResponse, "links" | "resources">,
  parentById: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, InventoryResource>,
): ReadonlyMap<string, number> {
  const counts = new Map<string, number>();
  for (const link of graph.links) {
    if (link.type === "contains") continue;
    const sourceGroup = owningGroupId(link.source, parentById, byId);
    const targetGroup = owningGroupId(link.target, parentById, byId);
    if (!sourceGroup || !targetGroup || sourceGroup === targetGroup) continue;
    counts.set(sourceGroup, (counts.get(sourceGroup) ?? 0) + 1);
    counts.set(targetGroup, (counts.get(targetGroup) ?? 0) + 1);
  }
  return counts;
}

function owningGroupId(
  resourceId: string,
  parentById: ReadonlyMap<string, string>,
  byId: ReadonlyMap<string, InventoryResource>,
): string | null {
  let currentId: string | undefined = resourceId;
  const visited = new Set<string>();
  while (currentId && !visited.has(currentId)) {
    visited.add(currentId);
    if (byId.get(currentId)?.type === "resource-group") return currentId;
    currentId = parentById.get(currentId);
  }
  return null;
}
