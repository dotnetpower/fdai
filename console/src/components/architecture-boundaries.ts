import type { InventoryResource } from "./architecture-map.model";

const ARCHITECTURE_BOUNDARY_TYPES = new Set([
  "subscription",
  "resource-group",
  "virtual-network",
  "network.vnet",
  "subnet",
  "network.subnet",
]);

/** Identifies authoritative containment roles without relying on presentation geometry. */
export function isArchitectureBoundaryResource(
  resource: Pick<InventoryResource, "type">,
): boolean {
  return ARCHITECTURE_BOUNDARY_TYPES.has(resource.type);
}
