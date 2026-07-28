import { describe, expect, it } from "vitest";
import { orderArchitectureNetworkPathNodes } from "./architecture-network-path";
import type { InventoryLink, InventoryResource } from "./architecture-map.model";

function pathNodes(suffix: string, workloadName: string): InventoryResource[] {
  return [
    { id: `disk-${suffix}`, type: "disk", name: `Disk ${suffix}`, status: "healthy" },
    { id: `nic-${suffix}`, type: "network.interface", name: `NIC ${suffix}`, status: "healthy" },
    { id: `pip-${suffix}`, type: "network.public-ip", name: `Public IP ${suffix}`, status: "healthy" },
    { id: `vm-${suffix}`, type: "compute.vm", name: workloadName, status: "healthy" },
    { id: `nsg-${suffix}`, type: "network.nsg", name: `Security ${suffix}`, status: "healthy" },
  ];
}

function pathLinks(suffix: string): InventoryLink[] {
  return [
    { source: `nic-${suffix}`, target: `pip-${suffix}`, type: "attached_to" },
    { source: `nic-${suffix}`, target: `nsg-${suffix}`, type: "attached_to" },
    { source: `vm-${suffix}`, target: `nic-${suffix}`, type: "attached_to" },
    { source: `vm-${suffix}`, target: `disk-${suffix}`, type: "attached_to" },
  ];
}

describe("architecture network path ordering", () => {
  it("keeps observed workload chains contiguous from edge to disk", () => {
    const nodes = [
      ...pathNodes("b", "App 2"),
      ...pathNodes("a", "App 1"),
    ];
    const links = [...pathLinks("a"), ...pathLinks("b")];

    expect(orderArchitectureNetworkPathNodes(nodes, links).map((node) => node.id)).toEqual([
      "pip-a", "nsg-a", "nic-a", "vm-a", "disk-a",
      "pip-b", "nsg-b", "nic-b", "vm-b", "disk-b",
    ]);
  });
});
