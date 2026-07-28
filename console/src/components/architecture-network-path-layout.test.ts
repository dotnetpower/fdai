import { describe, expect, it } from "vitest";
import { layoutArchitecturePathComponents } from "./architecture-network-path-layout";
import type { InventoryLink, InventoryResource } from "./architecture-map.model";

function component(suffix: string): InventoryResource[] {
  return [
    { id: `disk-${suffix}`, type: "disk", name: `Disk ${suffix}`, status: "healthy" },
    { id: `vm-${suffix}`, type: "compute.vm", name: `VM ${suffix}`, status: "healthy" },
    { id: `nic-${suffix}`, type: "network.interface", name: `NIC ${suffix}`, status: "healthy" },
    { id: `nsg-${suffix}`, type: "network.nsg", name: `NSG ${suffix}`, status: "healthy" },
    { id: `pip-${suffix}`, type: "network.public-ip", name: `PIP ${suffix}`, status: "healthy" },
  ];
}

function links(suffix: string): InventoryLink[] {
  return [
    { source: `nic-${suffix}`, target: `pip-${suffix}`, type: "attached_to" },
    { source: `nic-${suffix}`, target: `nsg-${suffix}`, type: "attached_to" },
    { source: `vm-${suffix}`, target: `nic-${suffix}`, type: "attached_to" },
    { source: `vm-${suffix}`, target: `disk-${suffix}`, type: "attached_to" },
  ];
}

describe("architecture path lane layout", () => {
  it("places ingress nearest, storage farthest, and keeps components in separate lanes", () => {
    const layout = layoutArchitecturePathComponents(
      [...component("a"), ...component("b")],
      [...links("a"), ...links("b")],
    );
    const byId = new Map(layout.placements.map((placement) => [placement.resource.id, placement]));

    expect(layout.componentCount).toBe(2);
    expect(byId.get("pip-a")!.y).toBeLessThan(byId.get("nsg-a")!.y);
    expect(byId.get("nsg-a")!.y).toBeLessThan(byId.get("nic-a")!.y);
    expect(byId.get("nic-a")!.y).toBeLessThan(byId.get("vm-a")!.y);
    expect(byId.get("vm-a")!.y).toBeLessThan(byId.get("disk-a")!.y);
    expect(byId.get("pip-a")!.x).toBeLessThan(byId.get("pip-b")!.x);
    expect(byId.get("vm-a")!.renderScale).toBe(1.2);
    expect(byId.get("nic-a")!.renderScale).toBe(1);
  });
});
