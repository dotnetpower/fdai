import {
  architecturePresentationGraph,
  constrainGraph,
  geometryOf,
  isRegion,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";
import { layoutArchitectureNetworkFloors } from "./architecture-network-layout";

export function layoutArchitecturePresentation(
  graph: InventoryGraphResponse,
  selectedId: string | null,
): InventoryGraphResponse {
  const networkLayout = layoutArchitectureNetworkFloors(graph);
  const overview = constrainGraph(architecturePresentationGraph(networkLayout, null));
  if (selectedId === null) return overview;
  const presented = architecturePresentationGraph(networkLayout, selectedId);
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
  const revealed = presented.resources.filter((resource) => !overviewById.has(resource.id));
  for (const [revealIndex, resource] of revealed.entries()) {
    const anchor = architectureRevealAnchor(resource, selectedId, presented, positioned);
    const parent = (resource.network_plane_id
      ? positioned.get(resource.network_plane_id)
      : undefined) ?? (resource.parent_id ? positioned.get(resource.parent_id) : undefined);
    const placed = placeArchitectureNeighbor(resource, anchor, parent, occupied, revealIndex);
    positioned.set(resource.id, placed);
    occupied.push(placed);
  }

  return {
    ...presented,
    resources: presented.resources.map((resource) => positioned.get(resource.id) ?? resource),
  };
}

function architectureRevealAnchor(
  resource: InventoryResource,
  selectedId: string,
  graph: Pick<InventoryGraphResponse, "links">,
  positioned: ReadonlyMap<string, InventoryResource>,
): InventoryResource | undefined {
  const linkedOwnerId = graph.links
    .filter((link) => link.type !== "contains")
    .map((link) => link.source === resource.id
      ? link.target
      : link.target === resource.id ? link.source : null)
    .find((resourceId): resourceId is string => resourceId !== null && positioned.has(resourceId));
  return positioned.get(selectedId) ?? (linkedOwnerId ? positioned.get(linkedOwnerId) : undefined)
    ?? (resource.parent_id ? positioned.get(resource.parent_id) : undefined);
}

function placeArchitectureNeighbor(
  resource: InventoryResource,
  anchor: InventoryResource | undefined,
  parent: InventoryResource | undefined,
  occupied: readonly InventoryResource[],
  fallbackIndex: number,
): InventoryResource {
  if (!anchor || anchor.x === undefined || anchor.y === undefined) return resource;
  const offsets = [
    [1.65, 0], [3.3, 0], [0, 1.55], [-1.65, 0], [0, -1.55],
    [1.65, 1.55], [-1.65, 1.55], [1.65, -1.55], [-1.65, -1.55],
  ] as const;
  const geometry = geometryOf(resource);
  for (const [offsetX, offsetY] of offsets) {
    const minimumX = (parent?.x ?? Number.NEGATIVE_INFINITY) + geometry.width / 2 + .12;
    const maximumX = (parent?.x ?? 0) + (parent?.w ?? Number.POSITIVE_INFINITY) - geometry.width / 2 - .12;
    const minimumY = (parent?.y ?? Number.NEGATIVE_INFINITY) + geometry.depth / 2 + .12;
    const maximumY = (parent?.y ?? 0) + (parent?.h ?? Number.POSITIVE_INFINITY) - geometry.depth / 2 - .12;
    const x = clampLayout(anchor.x + offsetX, minimumX, maximumX);
    const y = clampLayout(anchor.y + offsetY, minimumY, maximumY);
    if (occupied.some((candidate) => architectureNodesOverlap(
      { ...resource, x, y }, candidate,
    ))) continue;
    return { ...resource, render_scale: Math.max(1, resource.render_scale ?? 1), x, y };
  }
  const [fallbackX, fallbackY] = offsets[fallbackIndex % offsets.length]!;
  return { ...resource, x: anchor.x + fallbackX, y: anchor.y + fallbackY };
}

function architectureNodesOverlap(first: InventoryResource, second: InventoryResource): boolean {
  const firstGeometry = geometryOf(first);
  const secondGeometry = geometryOf(second);
  return Math.abs((first.x ?? 0) - (second.x ?? 0)) <
      (firstGeometry.width + secondGeometry.width) / 2 + .18
    && Math.abs((first.y ?? 0) - (second.y ?? 0)) <
      (firstGeometry.depth + secondGeometry.depth) / 2 + .18;
}

function clampLayout(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}
