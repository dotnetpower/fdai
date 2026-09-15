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

/** Distinguishes a rendered boundary from a Landscape summary of that boundary. */
export function isArchitectureRenderedBoundary(
  resource: Pick<InventoryResource, "presentation_role" | "type">,
): boolean {
  return resource.presentation_role !== "summary" && isArchitectureBoundaryResource(resource);
}
