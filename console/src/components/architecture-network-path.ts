import type { InventoryResource } from "./architecture-map.model";

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
  return 3;
}

export function compareArchitectureNetworkPathNodes(
  first: InventoryResource,
  second: InventoryResource,
): number {
  return architectureNetworkPathRank(first) - architectureNetworkPathRank(second)
    || first.name.localeCompare(second.name);
}
