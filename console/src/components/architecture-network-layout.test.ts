import { describe, expect, it } from "vitest";
import {
  architectureSubnetMembership,
  isArchitectureNetworkPlane,
  layoutArchitectureNetworkFloors,
} from "./architecture-network-layout";
import type { InventoryGraphResponse } from "./architecture-map.model";
import { layoutArchitecturePresentation } from "./architecture-map-layout";

const GRAPH: InventoryGraphResponse = {
  snapshot_at: "2026-07-28T00:00:00Z",
  freshness: "fresh",
  scope: null,
  depth: 4,
  included_link_types: ["contains", "attached_to", "depends_on"],
  resources: [
    { id: "sub", type: "subscription", name: "Subscription", status: "healthy", x: 0, y: 0, w: 18, h: 12 },
    { id: "rg", type: "resource-group", name: "App", status: "healthy", parent_id: "sub", x: 1, y: 1, w: 5, h: 4 },
    { id: "vnet", type: "network.vnet", name: "Core", status: "healthy", parent_id: "rg" },
    { id: "snet", type: "network.subnet", name: "App subnet", status: "healthy", parent_id: "rg" },
    { id: "vm", type: "compute.vm", name: "Worker", status: "healthy", parent_id: "rg" },
    { id: "nic", type: "network.interface", name: "Worker NIC", status: "healthy", parent_id: "rg" },
    { id: "nsg", type: "network.nsg", name: "App NSG", status: "healthy", parent_id: "rg" },
    { id: "db", type: "postgresql-server", name: "Database", status: "healthy", parent_id: "rg" },
  ],
  links: [
    { source: "sub", target: "rg", type: "contains" },
    { source: "rg", target: "vnet", type: "contains" },
    { source: "rg", target: "snet", type: "contains" },
    { source: "vnet", target: "snet", type: "contains" },
    { source: "vm", target: "nic", type: "attached_to" },
    { source: "nic", target: "snet", type: "attached_to" },
    { source: "nic", target: "nsg", type: "attached_to" },
  ],
  truncated: false,
};

describe("architecture network floor layout", () => {
  it("places resources reached through observed attachments on their subnet floor", () => {
    const membership = architectureSubnetMembership(GRAPH);
    expect(membership.get("vm")).toBe("snet");
    expect(membership.get("nic")).toBe("snet");
    expect(membership.get("nsg")).toBe("snet");
    expect(membership.has("db")).toBe(false);

    const laidOut = layoutArchitectureNetworkFloors(GRAPH);
    const byId = new Map(laidOut.resources.map((resource) => [resource.id, resource]));
    const vnet = byId.get("vnet")!;
    const subnet = byId.get("snet")!;
    const vm = byId.get("vm")!;
    const nsg = byId.get("nsg")!;
    const database = byId.get("db")!;

    expect(isArchitectureNetworkPlane(vnet)).toBe(true);
    expect(isArchitectureNetworkPlane(subnet)).toBe(true);
    expect(vm.network_plane_id).toBe("snet");
    expect(nsg.network_plane_id).toBe("snet");
    expect(database.network_plane_id).toBeUndefined();
    expect(vm.x).toBeGreaterThan(subnet.x!);
    expect(vm.x).toBeLessThan(subnet.x! + subnet.w!);
    expect(vm.y).toBeGreaterThan(subnet.y!);
    expect(vm.y).toBeLessThan(subnet.y! + subnet.h!);
  });

  it("leaves ambiguous attachment paths off every subnet floor", () => {
    const ambiguous: InventoryGraphResponse = {
      ...GRAPH,
      resources: [
        ...GRAPH.resources,
        { id: "snet-2", type: "network.subnet", name: "Other", status: "healthy", parent_id: "rg" },
      ],
      links: [
        ...GRAPH.links,
        { source: "vnet", target: "snet-2", type: "contains" },
        { source: "nic", target: "snet-2", type: "attached_to" },
      ],
    };

    const membership = architectureSubnetMembership(ambiguous);
    expect(membership.has("nic")).toBe(false);
    expect(membership.has("vm")).toBe(false);
    expect(membership.has("nsg")).toBe(false);
  });

  it("reveals hidden network auxiliaries inside the same subnet plane", () => {
    const overview = layoutArchitecturePresentation(GRAPH, null);
    const focused = layoutArchitecturePresentation(GRAPH, "vm");
    const overviewVm = overview.resources.find((resource) => resource.id === "vm")!;
    const focusedVm = focused.resources.find((resource) => resource.id === "vm")!;
    const nic = focused.resources.find((resource) => resource.id === "nic")!;
    const subnet = focused.resources.find((resource) => resource.id === "snet")!;

    expect(overview.resources.some((resource) => resource.id === "nic")).toBe(false);
    expect(focusedVm).toMatchObject({ x: overviewVm.x, y: overviewVm.y });
    expect(nic.network_plane_id).toBe("snet");
    expect(nic.x).toBeGreaterThan(subnet.x!);
    expect(nic.x).toBeLessThan(subnet.x! + subnet.w!);
    expect(nic.y).toBeGreaterThan(subnet.y!);
    expect(nic.y).toBeLessThan(subnet.y! + subnet.h!);
  });
});
