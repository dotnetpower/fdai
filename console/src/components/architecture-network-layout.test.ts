import { describe, expect, it } from "vitest";
import {
  architectureSubnetMembership,
  isArchitectureNetworkPlane,
  layoutArchitectureNetworkFloors,
} from "./architecture-network-layout";
import { architectureNetworkPathRank } from "./architecture-network-path";
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
    const nic = byId.get("nic")!;
    const nsg = byId.get("nsg")!;
    const database = byId.get("db")!;

    expect(isArchitectureNetworkPlane(vnet)).toBe(true);
    expect(isArchitectureNetworkPlane(subnet)).toBe(true);
    expect(vm.network_plane_id).toBe("snet");
    expect(nsg.network_plane_id).toBe("snet");
    expect(database.network_plane_id).toBeUndefined();
    expect(architectureNetworkPathRank(nsg)).toBeLessThan(architectureNetworkPathRank(nic));
    expect(architectureNetworkPathRank(nic)).toBeLessThan(architectureNetworkPathRank(vm));
    expect(nsg.x).toBeLessThan(nic.x!);
    expect(nic.x).toBeLessThan(vm.x!);
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

  it("keeps visible network interfaces stable inside the same subnet plane", () => {
    const overview = layoutArchitecturePresentation(GRAPH, null);
    const focused = layoutArchitecturePresentation(GRAPH, "vm");
    const overviewVm = overview.resources.find((resource) => resource.id === "vm")!;
    const overviewNic = overview.resources.find((resource) => resource.id === "nic")!;
    const focusedVm = focused.resources.find((resource) => resource.id === "vm")!;
    const nic = focused.resources.find((resource) => resource.id === "nic")!;
    const subnet = focused.resources.find((resource) => resource.id === "snet")!;

    expect(overview.resources.some((resource) => resource.id === "nic")).toBe(true);
    expect(focusedVm).toMatchObject({ x: overviewVm.x, y: overviewVm.y });
    expect(nic).toMatchObject({ x: overviewNic.x, y: overviewNic.y });
    expect(nic.network_plane_id).toBe("snet");
    expect(nic.x).toBeGreaterThan(subnet.x!);
    expect(nic.x).toBeLessThan(subnet.x! + subnet.w!);
    expect(nic.y).toBeGreaterThan(subnet.y!);
    expect(nic.y).toBeLessThan(subnet.y! + subnet.h!);
  });

  it("uses a single wide row for three networks in a focused scope", () => {
    const focused: InventoryGraphResponse = {
      ...GRAPH,
      active_view: "rg",
      views: [{
        id: "rg",
        label: "App",
        kind: "resource_group",
        classification: "resource_group_fallback",
        description: "",
        root_resource_id: "rg",
      }],
      resources: [
        ...GRAPH.resources.filter((resource) => !["vnet", "snet"].includes(resource.id)),
        ...Array.from({ length: 3 }, (_, index) => ({
          id: `vnet-${index}`,
          type: "network.vnet",
          name: `Network ${index}`,
          status: "healthy",
          parent_id: "rg",
        })),
        ...Array.from({ length: 3 }, (_, index) => ({
          id: `snet-${index}`,
          type: "network.subnet",
          name: `Subnet ${index}`,
          status: "healthy",
          parent_id: "rg",
        })),
      ],
      links: [
        ...GRAPH.links.filter((link) => !["vnet", "snet"].includes(link.source)
          && !["vnet", "snet"].includes(link.target)),
        ...Array.from({ length: 3 }, (_, index) => ({
          source: `vnet-${index}`,
          target: `snet-${index}`,
          type: "contains" as const,
        })),
      ],
    };

    const laidOut = layoutArchitectureNetworkFloors(focused);
    const networks = laidOut.resources.filter((resource) => resource.type === "network.vnet");
    const overview = layoutArchitectureNetworkFloors({
      ...focused,
      active_view: "fdai",
      views: [{
        ...focused.views![0]!,
        id: "fdai",
        kind: "fdai",
        classification: "ownership_tag",
      }],
    });
    const overviewNetworks = overview.resources.filter(
      (resource) => resource.type === "network.vnet",
    );

    expect(new Set(networks.map((resource) => resource.y)).size).toBe(1);
    expect(new Set(networks.map((resource) => resource.x)).size).toBe(3);
    expect(new Set(overviewNetworks.map((resource) => resource.y)).size).toBeGreaterThan(1);
  });
});
