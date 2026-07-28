import type { InventoryLink, InventoryResource } from "./architecture-map.model";

export function architectureNetworkPathRank(resource: InventoryResource): number {
  if (resource.type === "network.public-ip") return 0;
  if ([
    "firewall",
    "network-security-group",
    "network.nsg",
    "network.private-endpoint",
    "network.application-gateway",
    "network.load-balancer",
  ].includes(resource.type)) return 1;
  if (resource.type === "network.interface") return 2;
  if (
    resource.type.startsWith("compute.")
    || resource.type.includes("container-app")
    || resource.type.includes("function")
    || resource.type.includes("app-service")
  ) return 3;
  if (["postgresql", "postgresql-server", "sql-database", "object-storage"].includes(
    resource.type,
  )) return 4;
  if (["disk", "file-share", "storage-account"].includes(resource.type)) return 4;
  return 3;
}

export function compareArchitectureNetworkPathNodes(
  first: InventoryResource,
  second: InventoryResource,
): number {
  return architectureNetworkPathRank(first) - architectureNetworkPathRank(second)
    || first.name.localeCompare(second.name);
}

export function orderArchitectureNetworkPathNodes(
  nodes: readonly InventoryResource[],
  links: readonly InventoryLink[],
): InventoryResource[] {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const adjacency = new Map<string, Set<string>>();
  for (const link of links) {
    if (link.type !== "attached_to" || !byId.has(link.source) || !byId.has(link.target)) {
      continue;
    }
    addNeighbor(adjacency, link.source, link.target);
    addNeighbor(adjacency, link.target, link.source);
  }

  const components: InventoryResource[][] = [];
  const visited = new Set<string>();
  for (const node of nodes) {
    if (visited.has(node.id)) continue;
    const component: InventoryResource[] = [];
    const queue = [node.id];
    visited.add(node.id);
    while (queue.length > 0) {
      const currentId = queue.shift()!;
      const current = byId.get(currentId);
      if (current) component.push(current);
      for (const neighbor of adjacency.get(currentId) ?? []) {
        if (visited.has(neighbor)) continue;
        visited.add(neighbor);
        queue.push(neighbor);
      }
    }
    components.push(component.sort(compareArchitectureNetworkPathNodes));
  }

  return components
    .sort((first, second) => pathComponentKey(first).localeCompare(pathComponentKey(second)))
    .flat();
}

function pathComponentKey(component: readonly InventoryResource[]): string {
  const workload = component.find((resource) => architectureNetworkPathRank(resource) === 3);
  return workload?.name ?? component.map((resource) => resource.name).sort()[0] ?? "";
}

function addNeighbor(adjacency: Map<string, Set<string>>, source: string, target: string): void {
  const neighbors = adjacency.get(source) ?? new Set<string>();
  neighbors.add(target);
  adjacency.set(source, neighbors);
}
