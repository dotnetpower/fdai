import type { InventoryGraphResponse, InventoryResource } from "./architecture-map.model";
import {
  ARCHITECTURE_TOPOLOGY_COLUMN_PITCH,
  ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE,
  ARCHITECTURE_TOPOLOGY_ROW_PITCH,
  architectureTopologyNodeDimensions,
} from "./architecture-topology-dimensions";
import { architecturePresentationParentById } from "./architecture-landscape-layout";

/** Packs overlapping targets and expands nested regions before final clamping. */
export function normalizeArchitectureTopologyContainment(
  graph: InventoryGraphResponse,
): InventoryGraphResponse {
  return expandTopologyContainmentRegions(packTopologyInteractionTargets(graph));
}

export function architectureVisualParentById(
  graph: Pick<InventoryGraphResponse, "links" | "resources">,
  byId: ReadonlyMap<string, InventoryResource>,
): ReadonlyMap<string, string> {
  return architecturePresentationParentById(graph, byId);
}

function packTopologyInteractionTargets(
  graph: InventoryGraphResponse,
): InventoryGraphResponse {
  const resources = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const visualParentById = architectureVisualParentById(graph, resources);
  const regions = graph.resources.filter(isTopologyRegion);

  for (const rawRegion of regions) {
    const region = resources.get(rawRegion.id) ?? rawRegion;
    const children = graph.resources
      .filter((resource) =>
        visualParentById.get(resource.id) === region.id && !isTopologyRegion(resource))
      .map((resource) => resources.get(resource.id) ?? resource)
      .sort(compareTopologyChildren);
    if (children.length === 0 || !topologyChildrenNeedPacking(region, children)) continue;
    const columns = Math.min(6, Math.max(1, Math.ceil(Math.sqrt(children.length))));
    const rows = Math.ceil(children.length / columns);
    const sideInset = .3;
    const topInset = .7;
    const bottomInset = .3;
    const requiredWidth = sideInset * 2
      + (columns - 1) * ARCHITECTURE_TOPOLOGY_COLUMN_PITCH
      + ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE;
    const requiredHeight = topInset + bottomInset
      + (rows - 1) * ARCHITECTURE_TOPOLOGY_ROW_PITCH
      + ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE;
    const x = region.x ?? 0;
    const y = region.y ?? 0;
    resources.set(region.id, {
      ...region,
      w: Math.max(region.w ?? 0, requiredWidth),
      h: Math.max(region.h ?? 0, requiredHeight),
    });
    children.forEach((child, index) => {
      const column = index % columns;
      const row = Math.floor(index / columns);
      resources.set(child.id, {
        ...child,
        x: x + sideInset + ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE / 2
          + column * ARCHITECTURE_TOPOLOGY_COLUMN_PITCH,
        y: y + topInset + ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE / 2
          + row * ARCHITECTURE_TOPOLOGY_ROW_PITCH,
      });
    });
  }

  return {
    ...graph,
    resources: graph.resources.map((resource) => resources.get(resource.id) ?? resource),
  };
}

function topologyChildrenNeedPacking(
  region: InventoryResource,
  children: readonly InventoryResource[],
): boolean {
  const regionX = region.x ?? 0;
  const regionY = region.y ?? 0;
  const regionRight = regionX + (region.w ?? 0);
  const regionBottom = regionY + (region.h ?? 0);
  for (const [index, child] of children.entries()) {
    if (child.x === undefined || child.y === undefined) return true;
    const dimensions = architectureTopologyNodeDimensions(child.render_scale);
    const width = Math.max(dimensions.width, ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE);
    const height = Math.max(dimensions.height, ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE);
    if (
      child.x - width / 2 < regionX
      || child.x + width / 2 > regionRight
      || child.y - height / 2 < regionY
      || child.y + height / 2 > regionBottom
    ) return true;
    for (const sibling of children.slice(index + 1)) {
      if (sibling.x === undefined || sibling.y === undefined) return true;
      const siblingDimensions = architectureTopologyNodeDimensions(sibling.render_scale);
      const siblingWidth = Math.max(
        siblingDimensions.width,
        ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE,
      );
      const siblingHeight = Math.max(
        siblingDimensions.height,
        ARCHITECTURE_TOPOLOGY_HIT_TARGET_SIZE,
      );
      if (
        Math.abs(child.x - sibling.x) < (width + siblingWidth) / 2
        && Math.abs(child.y - sibling.y) < (height + siblingHeight) / 2
      ) return true;
    }
  }
  return false;
}

function expandTopologyContainmentRegions(
  graph: InventoryGraphResponse,
): InventoryGraphResponse {
  const resources = new Map(graph.resources.map((resource) => [resource.id, resource]));
  const visualParentById = architectureVisualParentById(graph, resources);
  const regionDepth = (resource: InventoryResource): number => {
    let depth = 0;
    let current: InventoryResource | undefined = resource;
    const visited = new Set<string>();
    while (current && !visited.has(current.id)) {
      visited.add(current.id);
      const parentId = visualParentById.get(current.id);
      if (!parentId) break;
      current = resources.get(parentId);
      if (current) depth += 1;
    }
    return depth;
  };
  const regions = graph.resources
    .filter(isTopologyRegion)
    .sort((first, second) => regionDepth(second) - regionDepth(first));

  for (const rawRegion of regions) {
    const region = resources.get(rawRegion.id) ?? rawRegion;
    let minimumWidth = .5;
    let minimumHeight = .5;
    for (const rawChild of graph.resources) {
      if (visualParentById.get(rawChild.id) !== region.id) continue;
      const child = resources.get(rawChild.id) ?? rawChild;
      if (isTopologyRegion(child)) {
        minimumWidth = Math.max(minimumWidth, (child.w ?? .5) + .24);
        minimumHeight = Math.max(minimumHeight, (child.h ?? .5) + .24);
        continue;
      }
      const dimensions = architectureTopologyNodeDimensions(child.render_scale);
      minimumWidth = Math.max(minimumWidth, dimensions.width + .24);
      minimumHeight = Math.max(minimumHeight, dimensions.height + .78);
    }
    resources.set(region.id, {
      ...region,
      w: Math.max(region.w ?? 0, minimumWidth),
      h: Math.max(region.h ?? 0, minimumHeight),
    });
  }

  return {
    ...graph,
    resources: graph.resources.map((resource) => resources.get(resource.id) ?? resource),
  };
}

function compareTopologyChildren(
  first: InventoryResource,
  second: InventoryResource,
): number {
  return first.type.localeCompare(second.type)
    || first.name.localeCompare(second.name)
    || first.id.localeCompare(second.id);
}

function isTopologyRegion(resource: InventoryResource): boolean {
  return resource.w !== undefined && resource.h !== undefined;
}
