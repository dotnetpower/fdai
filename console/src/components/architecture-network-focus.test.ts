import { describe, expect, it } from "vitest";
import {
  DEFAULT_ARCHITECTURE_NETWORK_FILTERS,
  architectureNetworkFocusGraph,
  defaultArchitectureNetworkFocusId,
  exportArchitectureNetworkSvg,
  filterArchitectureNetworkGraph,
  layoutArchitectureNetworkFocusGraph,
  traceArchitectureNetworkPath,
} from "./architecture-network-focus";
import type { InventoryGraphResponse } from "./architecture-map.model";

const GRAPH: InventoryGraphResponse = {
  snapshot_at: "2026-08-22T00:00:00Z",
  freshness: "fresh",
  scope: null,
  depth: 4,
  included_link_types: ["contains", "attached_to", "depends_on", "peered_with"],
  truncated: false,
  resources: [
    { id: "sub", type: "subscription", name: "Subscription", status: "unknown", x: 0, y: 0, w: 18, h: 12 },
    { id: "rg-a", type: "resource-group", name: "Workload", status: "unknown", parent_id: "sub", x: 1, y: 1, w: 10, h: 8 },
    { id: "rg-b", type: "resource-group", name: "Unrelated", status: "unknown", parent_id: "sub", x: 12, y: 1, w: 5, h: 5 },
    { id: "vnet", type: "network.vnet", name: "Network", status: "healthy", parent_id: "rg-a", x: 2, y: 2, w: 7, h: 5 },
    { id: "subnet", type: "network.subnet", name: "Subnet", status: "healthy", parent_id: "rg-a", x: 2.5, y: 2.5, w: 6, h: 4 },
    { id: "public", type: "network.public-ip", name: "Public address", status: "healthy", parent_id: "rg-a", network_plane_id: "subnet", x: 3, y: 3 },
    { id: "nic", type: "network.interface", name: "Interface", status: "healthy", parent_id: "rg-a", network_plane_id: "subnet", x: 4, y: 3 },
    { id: "vm", type: "compute.vm", name: "Sensitive workload name", status: "healthy", parent_id: "rg-a", network_plane_id: "subnet", x: 5, y: 3 },
    { id: "db", type: "postgresql-server", name: "Sensitive data name", status: "healthy", parent_id: "rg-a", network_plane_id: "subnet", x: 6, y: 3 },
    { id: "other", type: "compute.vm", name: "Other", status: "healthy", parent_id: "rg-b", x: 13, y: 2 },
  ],
  links: [
    { source: "sub", target: "rg-a", type: "contains" },
    { source: "sub", target: "rg-b", type: "contains" },
    { source: "rg-a", target: "vnet", type: "contains" },
    { source: "vnet", target: "subnet", type: "contains" },
    { source: "public", target: "nic", type: "attached_to" },
    { source: "nic", target: "subnet", type: "attached_to" },
    { source: "vm", target: "nic", type: "attached_to" },
    { source: "vm", target: "db", type: "depends_on" },
  ],
};

describe("observed network focus", () => {
  it("selects the VNet with the most observed subnet containment", () => {
    expect(defaultArchitectureNetworkFocusId(GRAPH)).toBe("vnet");
  });

  it("focuses one VNet while retaining only required ancestors and linked resources", () => {
    const focused = architectureNetworkFocusGraph(GRAPH, "vnet");
    expect(focused.resources.map((resource) => resource.id)).toContain("sub");
    expect(focused.resources.map((resource) => resource.id)).toContain("db");
    expect(focused.resources.map((resource) => resource.id)).not.toContain("rg-b");
    expect(focused.resources.map((resource) => resource.id)).not.toContain("other");
    expect(focused.active_view).toBe("network-focus");
    expect(focused.resources.find((resource) => resource.id === "vnet")?.w).toBeUndefined();
  });

  it("includes direct peer subnets and attachments without widening to unrelated resources", () => {
    const graph: InventoryGraphResponse = {
      ...GRAPH,
      resources: [
        ...GRAPH.resources,
        { id: "peer-vnet", type: "network.vnet", name: "Peer", status: "healthy", parent_id: "rg-a" },
        { id: "peer-subnet", type: "network.subnet", name: "Peer subnet", status: "healthy", parent_id: "rg-a" },
        { id: "firewall", type: "network.firewall", name: "Firewall", status: "healthy", parent_id: "rg-a" },
        { id: "peer-unrelated", type: "compute.vm", name: "Unrelated peer resource", status: "healthy", parent_id: "rg-a" },
      ],
      links: [
        ...GRAPH.links,
        { source: "vnet", target: "peer-vnet", type: "peered_with", direction: "bidirectional" },
        { source: "peer-vnet", target: "peer-subnet", type: "contains" },
        { source: "firewall", target: "peer-subnet", type: "attached_to" },
      ],
    };
    const focused = architectureNetworkFocusGraph(graph, "vnet");
    const ids = new Set(focused.resources.map((resource) => resource.id));
    expect(ids.has("peer-vnet")).toBe(true);
    expect(ids.has("peer-subnet")).toBe(true);
    expect(ids.has("firewall")).toBe(true);
    expect(ids.has("peer-unrelated")).toBe(false);
  });

  it("filters public exposure without mutating the source graph", () => {
    const filtered = filterArchitectureNetworkGraph(GRAPH, {
      ...DEFAULT_ARCHITECTURE_NETWORK_FILTERS,
      publicExposure: false,
    });
    expect(filtered.resources.some((resource) => resource.id === "public")).toBe(false);
    expect(GRAPH.resources.some((resource) => resource.id === "public")).toBe(true);
  });

  it("rebuilds VNet and subnet regions from observed containment", () => {
    const focused = architectureNetworkFocusGraph(GRAPH, "vnet");
    const laidOut = layoutArchitectureNetworkFocusGraph(focused);
    const vnet = laidOut.resources.find((resource) => resource.id === "vnet")!;
    const subnet = laidOut.resources.find((resource) => resource.id === "subnet")!;
    const vm = laidOut.resources.find((resource) => resource.id === "vm")!;
    expect(vnet.w).toBeGreaterThan(4);
    expect(subnet.w).toBeGreaterThan(4);
    expect(vm.network_plane_id).toBe("subnet");
    expect(vm.x).toBeGreaterThan(subnet.x ?? 0);
  });
});

describe("observed network paths", () => {
  it("returns the shortest typed path with observed evidence", () => {
    const result = traceArchitectureNetworkPath(GRAPH, "public", "db");
    expect(result?.status).toBe("found");
    expect(result?.resourceIds).toEqual(["public", "nic", "vm", "db"]);
    expect(result?.hops.map((hop) => hop.link.type)).toEqual([
      "attached_to", "attached_to", "depends_on",
    ]);
    expect(result?.evidencePosture).toBe("observed");
  });

  it("reports no observed path only from complete fresh relationship coverage", () => {
    expect(traceArchitectureNetworkPath(GRAPH, "public", "other")?.status)
      .toBe("no_observed_path");
    expect(traceArchitectureNetworkPath({ ...GRAPH, truncated: true }, "public", "other")?.status)
      .toBe("unknown");
    expect(traceArchitectureNetworkPath({ ...GRAPH, included_link_types: ["attached_to"] }, "public", "other")?.status)
      .toBe("unknown");
  });
});

describe("sanitized network export", () => {
  it("omits resource ids and observed names while retaining evidence posture and visual parity", async () => {
    const path = traceArchitectureNetworkPath(GRAPH, "public", "db");
    const svg = await exportArchitectureNetworkSvg(GRAPH, path);
    expect(svg).toContain("Read-only observed topology");
    expect(svg).toContain("fresh");
    expect(svg).toContain("data:image/svg+xml");
    expect(svg).toContain('data-edge-index="');
    expect(svg).toContain('data-relationship-type="depends_on"');
    expect(svg).toContain('marker-end="url(#network-arrow)"');
    expect(svg).toContain('marker-start="url(#network-arrow-start)"');
    expect(svg).toContain("Peered with");
    expect(svg).toContain("Attached to");
    expect(svg).toContain("<path");
    expect(svg).not.toContain("<line");
    expect(svg).not.toContain("Sensitive workload name");
    expect(svg).not.toContain("Sensitive data name");
    expect(svg).not.toContain('data-node-id="vm"');
  });
});
