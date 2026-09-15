import {
  architecturePresentationGraph,
  constrainGraph,
  isRegion,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";
import { layoutArchitectureNetworkFloors } from "./architecture-network-layout";
import {
  architectureLandscapeOverviewGraph,
  architectureScopeDetailGraph,
  layoutGeometrylessArchitectureGraph,
} from "./architecture-landscape-layout";
import {
  ARCHITECTURE_TOPOLOGY_COLUMN_PITCH,
  ARCHITECTURE_TOPOLOGY_ROW_PITCH,
  architectureTopologyNodeDimensions,
} from "./architecture-topology-dimensions";

export function layoutArchitecturePresentation(
  graph: InventoryGraphResponse,
  selectedId: string | null,
): InventoryGraphResponse {
  const sourceGraph = selectedId === null
    ? architectureLandscapeOverviewGraph(graph)
    : architectureScopeDetailGraph(graph, selectedId);
  const networkLayout = layoutArchitectureNetworkFloors(
    layoutGeometrylessArchitectureGraph(sourceGraph),
  );
  const overview = constrainGraph(architecturePresentationGraph(networkLayout, null));
  if (selectedId === null) return overview;
  const presented = architecturePresentationGraph(networkLayout, selectedId);
  return positionArchitecturePresentation(overview, presented, new Set([selectedId]));
}

/** Keeps every impacted Resource and its bounded context in one shared SVG layout. */
export function layoutArchitectureImpactPresentation(
  graph: InventoryGraphResponse,
  impactedIds: ReadonlySet<string>,
): InventoryGraphResponse {
  const networkLayout = layoutArchitectureNetworkFloors(
    layoutGeometrylessArchitectureGraph(graph),
  );
  const overview = constrainGraph(architecturePresentationGraph(networkLayout, null));
  const visibleIds = new Set(overview.resources.map((resource) => resource.id));
  for (const resourceId of impactedIds) {
    for (const resource of architecturePresentationGraph(networkLayout, resourceId).resources) {
      visibleIds.add(resource.id);
    }
  }
  const presented = {
    ...networkLayout,
    resources: networkLayout.resources.filter((resource) => visibleIds.has(resource.id)),
    links: networkLayout.links.filter((link) =>
      visibleIds.has(link.source) && visibleIds.has(link.target)),
  };
  return positionArchitecturePresentation(overview, presented, impactedIds);
}

function positionArchitecturePresentation(
  overview: InventoryGraphResponse,
  presented: InventoryGraphResponse,
  preferredIds: ReadonlySet<string>,
): InventoryGraphResponse {
  const overviewById = new Map(overview.resources.map((resource) => [resource.id, resource]));
  const presentedById = new Map(presented.resources.map((resource) => [resource.id, resource]));
  const positioned = new Map<string, InventoryResource>();
  for (const resource of overview.resources) {
    const current = presentedById.get(resource.id);
    if (!current) continue;
    const { collapsed_count: _overviewCollapsedCount, ...overviewGeometry } = resource;
    positioned.set(resource.id, current.collapsed_count === undefined
      ? { ...current, ...overviewGeometry }
      : { ...current, ...overviewGeometry, collapsed_count: current.collapsed_count });
  }

  const occupied = [...positioned.values()].filter((resource) => !isRegion(resource));
  const revealed = presented.resources
    .filter((resource) => !overviewById.has(resource.id))
    .sort((first, second) =>
      Number(!preferredIds.has(first.id)) - Number(!preferredIds.has(second.id)));
  for (const resource of revealed) {
    const anchor = architectureRevealAnchor(resource, preferredIds, presented, positioned);
    const placed = placeArchitectureNeighbor(resource, anchor, occupied);
    positioned.set(resource.id, placed);
    occupied.push(placed);
  }

  return constrainGraph({
    ...presented,
    resources: presented.resources.map((resource) => positioned.get(resource.id) ?? resource),
  });
}

function architectureRevealAnchor(
  resource: InventoryResource,
  preferredIds: ReadonlySet<string>,
  graph: Pick<InventoryGraphResponse, "links">,
  positioned: ReadonlyMap<string, InventoryResource>,
): InventoryResource | undefined {
  const relatedIds = graph.links
    .filter((link) => link.type !== "contains")
    .map((link) => link.source === resource.id
      ? link.target
      : link.target === resource.id ? link.source : null)
    .filter((resourceId): resourceId is string => resourceId !== null);
  const preferredAnchorId = relatedIds.find((resourceId) =>
    preferredIds.has(resourceId) && positioned.has(resourceId));
  const linkedOwnerId = relatedIds.find((resourceId) => positioned.has(resourceId));
  const anyPreferredId = [...preferredIds].find((resourceId) => positioned.has(resourceId));
  return (preferredAnchorId ? positioned.get(preferredAnchorId) : undefined)
    ?? (linkedOwnerId ? positioned.get(linkedOwnerId) : undefined)
    ?? (resource.parent_id ? positioned.get(resource.parent_id) : undefined)
    ?? (anyPreferredId ? positioned.get(anyPreferredId) : undefined);
}

function placeArchitectureNeighbor(
  resource: InventoryResource,
  anchor: InventoryResource | undefined,
  occupied: readonly InventoryResource[],
): InventoryResource {
  if (!anchor || anchor.x === undefined || anchor.y === undefined) return resource;
  const anchorX = anchor.x;
  const anchorY = anchor.y;
  const candidate = (column: number, row: number): InventoryResource => ({
    ...resource,
    render_scale: Math.max(1, resource.render_scale ?? 1),
    x: anchorX + column * ARCHITECTURE_TOPOLOGY_COLUMN_PITCH,
    y: anchorY + row * ARCHITECTURE_TOPOLOGY_ROW_PITCH,
  });
  const available = (placed: InventoryResource): boolean =>
    !occupied.some((existing) => architectureNodesOverlap(placed, existing));
  for (let ring = 1; ring <= occupied.length * 2 + 2; ring += 1) {
    for (let row = -ring; row <= ring; row += 1) {
      for (let column = -ring; column <= ring; column += 1) {
        if (Math.abs(column) !== ring && Math.abs(row) !== ring) continue;
        const placed = candidate(column, row);
        if (available(placed)) return placed;
      }
    }
  }
  let column = occupied.length * 2 + 3;
  while (!available(candidate(column, 0))) column += 1;
  return candidate(column, 0);
}

function architectureNodesOverlap(first: InventoryResource, second: InventoryResource): boolean {
  const firstGeometry = architectureTopologyNodeDimensions(first.render_scale);
  const secondGeometry = architectureTopologyNodeDimensions(second.render_scale);
  return Math.abs((first.x ?? 0) - (second.x ?? 0)) <
      (firstGeometry.width + secondGeometry.width) / 2 + .18
    && Math.abs((first.y ?? 0) - (second.y ?? 0)) <
      (firstGeometry.height + secondGeometry.height) / 2 + .18;
}
