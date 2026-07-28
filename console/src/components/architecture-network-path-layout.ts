import type { InventoryLink, InventoryResource } from "./architecture-map.model";
import {
  architectureNetworkPathComponents,
  architectureNetworkPathRank,
} from "./architecture-network-path";

const STAGE_DEPTH = 1.75;
const BRANCH_WIDTH = 1.55;
const MINIMUM_LANE_WIDTH = 3.6;
const COMPONENT_GAP = 1.8;

export interface ArchitecturePathPlacement {
  readonly resource: InventoryResource;
  readonly x: number;
  readonly y: number;
  readonly renderScale: number;
}

export interface ArchitecturePathLayout {
  readonly width: number;
  readonly height: number;
  readonly placements: readonly ArchitecturePathPlacement[];
  readonly componentCount: number;
}

export function layoutArchitecturePathComponents(
  nodes: readonly InventoryResource[],
  links: readonly InventoryLink[],
): ArchitecturePathLayout {
  const components = architectureNetworkPathComponents(nodes, links);
  const placements: ArchitecturePathPlacement[] = [];
  let originX = 0;
  let maximumHeight = 0;

  for (const component of components) {
    const byRank = groupPathStages(component);
    const maximumStageWidth = Math.max(
      1,
      ...[...byRank.values()].map((stage) => stage.length),
    );
    const laneWidth = Math.max(MINIMUM_LANE_WIDTH, maximumStageWidth * BRANCH_WIDTH);
    const maximumRank = Math.max(0, ...component.map(architectureNetworkPathRank));
    const laneHeight = (maximumRank + 1) * STAGE_DEPTH;
    maximumHeight = Math.max(maximumHeight, laneHeight);

    for (const [rank, stage] of byRank) {
      const orderedStage = [...stage].sort((first, second) => first.name.localeCompare(second.name));
      orderedStage.forEach((resource, index) => {
        placements.push({
          resource,
          x: originX + laneWidth / 2 + (index - (orderedStage.length - 1) / 2) * BRANCH_WIDTH,
          y: (rank + .5) * STAGE_DEPTH,
          renderScale: architecturePathRenderScale(resource),
        });
      });
    }
    originX += laneWidth + COMPONENT_GAP;
  }

  return {
    width: Math.max(0, originX - (components.length > 0 ? COMPONENT_GAP : 0)),
    height: maximumHeight,
    placements,
    componentCount: components.length,
  };
}

function groupPathStages(
  component: readonly InventoryResource[],
): ReadonlyMap<number, readonly InventoryResource[]> {
  const stages = new Map<number, InventoryResource[]>();
  for (const resource of component) {
    const rank = architectureNetworkPathRank(resource);
    const stage = stages.get(rank) ?? [];
    stage.push(resource);
    stages.set(rank, stage);
  }
  return stages;
}

export function architecturePathRenderScale(resource: InventoryResource): number {
  if (
    resource.type.startsWith("compute.")
    || resource.type.includes("container-app")
    || resource.type.includes("function")
    || resource.type.includes("app-service")
  ) return 1.2;
  if ([
    "firewall",
    "network.application-gateway",
    "network.load-balancer",
    "network.private-endpoint",
    "network.nsg",
    "network-security-group",
  ].includes(resource.type)) return 1.1;
  return 1;
}
