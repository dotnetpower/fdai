import { describe, expect, it } from "vitest";
import {
  DEFAULT_ARCHITECTURE_NETWORK_FILTERS,
  ARCHITECTURE_NETWORK_OVERVIEW_LIMIT,
  ARCHITECTURE_NETWORK_OVERVIEW_SUBNET_LIMIT,
  ARCHITECTURE_NETWORK_OVERVIEW_VNET_LIMIT,
  architectureNetworkFocusGraph,
  architectureNetworkOverviewGraph,
  architectureNetworkPathPresentationGraph,
  exportArchitectureNetworkSvg,
  filterArchitectureNetworkGraph,
  layoutArchitectureNetworkFocusGraph,
  traceArchitectureNetworkPath,
} from "./architecture-network-focus";
import type { InventoryGraphResponse } from "./architecture-map.model";
import { layoutArchitectureNetworkOverviewPresentation } from "./architecture-map-layout";
import {
  architectureTopologyBounds,
  architectureTopologyCanvasSize,
  architectureTopologyFitScale,
} from "./architecture-topology-graph.model";

const VNET_TYPES_FOR_TEST = new Set(["virtual-network", "network.vnet"]);
const SUBNET_TYPES_FOR_TEST = new Set(["subnet", "network.subnet"]);

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
  it("keeps every returned VNet visible for the scope overview", () => {
    const secondary = {
      id: "vnet-secondary",
      type: "network.vnet",
      name: "Secondary",
      status: "healthy",
      parent_id: "rg-b",
    };
    const graph = { ...GRAPH, resources: [...GRAPH.resources, secondary] };

    expect(architectureNetworkFocusGraph(graph, null)).toBe(graph);
    expect(layoutArchitectureNetworkFocusGraph(graph).resources.map((resource) => resource.id))
      .toContain("vnet-secondary");
  });

  it("bounds the Network overview to network roles and required ancestors", () => {
    const unrelated = Array.from({ length: 80 }, (_, index) => ({
      id: `app-${index}`,
      type: "app-service",
      name: `Application ${index}`,
      status: "healthy",
      parent_id: "rg-a",
    }));
    const networkRoles = Array.from({ length: 60 }, (_, index) => ({
      id: `gateway-${index}`,
      type: "network.application-gateway",
      name: `Gateway ${index}`,
      status: "healthy",
      parent_id: "rg-a",
      network_plane_id: "subnet",
    }));
    const overview = architectureNetworkOverviewGraph({
      ...GRAPH,
      resources: [...GRAPH.resources, ...unrelated, ...networkRoles],
    });

    expect(overview.resources.some((resource) => resource.id === "sub")).toBe(true);
    expect(overview.resources.some((resource) => resource.id === "rg-a")).toBe(true);
    expect(overview.resources.some((resource) => resource.id === "app-0")).toBe(false);
    expect(overview.resources.filter((resource) =>
      resource.id.startsWith("gateway-"))).toHaveLength(ARCHITECTURE_NETWORK_OVERVIEW_LIMIT);
  });

  it("limits default VNet and Subnet boundaries before fitting the overview", () => {
    const vnets = Array.from({ length: 8 }, (_, index) => ({
      id: `vnet-${index}`,
      type: "network.vnet",
      name: `Network ${index}`,
      status: "healthy",
      parent_id: "rg-a",
    }));
    const subnets = vnets.flatMap((vnet, vnetIndex) =>
      Array.from({ length: 4 }, (_, index) => ({
        id: `subnet-${vnetIndex}-${index}`,
        type: "network.subnet",
        name: `Subnet ${vnetIndex}-${index}`,
        status: "healthy",
        parent_id: "rg-a",
      })));
    const overview = architectureNetworkOverviewGraph({
      ...GRAPH,
      resources: [
        ...GRAPH.resources.filter((resource) =>
          !VNET_TYPES_FOR_TEST.has(resource.type)
          && !SUBNET_TYPES_FOR_TEST.has(resource.type)),
        ...vnets,
        ...subnets,
      ],
      links: vnets.flatMap((vnet, vnetIndex) =>
        subnets
          .filter((subnet) => subnet.id.startsWith(`subnet-${vnetIndex}-`))
          .map((subnet) => ({
            source: vnet.id,
            target: subnet.id,
            type: "contains" as const,
          }))),
    });

    expect(overview.resources.filter((resource) =>
      resource.type === "network.vnet")).toHaveLength(
        ARCHITECTURE_NETWORK_OVERVIEW_VNET_LIMIT,
      );
    expect(overview.resources.filter((resource) =>
      resource.type === "network.subnet")).toHaveLength(
        ARCHITECTURE_NETWORK_OVERVIEW_SUBNET_LIMIT,
      );
    const laidOut = layoutArchitectureNetworkOverviewPresentation(overview);
    const canvas = architectureTopologyCanvasSize(
      architectureTopologyBounds(laidOut.resources),
    );
    expect(architectureTopologyFitScale(canvas, 1047, 600)).toBeGreaterThanOrEqual(.5);
  });

  it("applies the VNet limit to parent-only containment", () => {
    const vnets = Array.from({ length: 4 }, (_, index) => ({
      id: `parent-vnet-${index}`,
      type: "network.vnet",
      name: `Parent network ${index}`,
      status: "healthy",
      parent_id: "rg-a",
    }));
    const subnets = vnets.flatMap((vnet, vnetIndex) =>
      Array.from({ length: 2 }, (_, index) => ({
        id: `parent-subnet-${vnetIndex}-${index}`,
        type: "network.subnet",
        name: `Parent subnet ${vnetIndex}-${index}`,
        status: "healthy",
        parent_id: vnet.id,
      })));
    const overview = architectureNetworkOverviewGraph({
      ...GRAPH,
      resources: [
        ...GRAPH.resources.filter((resource) =>
          !VNET_TYPES_FOR_TEST.has(resource.type)
          && !SUBNET_TYPES_FOR_TEST.has(resource.type)),
        ...vnets,
        ...subnets,
      ],
      links: [],
    });
    const visibleVnetIds = new Set(overview.resources
      .filter((resource) => resource.type === "network.vnet")
      .map((resource) => resource.id));
    const visibleSubnets = overview.resources.filter((resource) =>
      resource.type === "network.subnet");

    expect(visibleVnetIds.size).toBe(ARCHITECTURE_NETWORK_OVERVIEW_VNET_LIMIT);
    expect(visibleSubnets).toHaveLength(4);
    expect(visibleSubnets.every((resource) =>
      visibleVnetIds.has(resource.parent_id ?? ""))).toBe(true);
  });

  it("preserves inferred Subnet membership after connector nodes are omitted", () => {
    const publicIps = Array.from({ length: 14 }, (_, index) => ({
      id: `public-${index}`,
      type: "network.public-ip",
      name: `Public ${index}`,
      status: "healthy",
      parent_id: "rg-a",
    }));
    const nics = publicIps.map((resource, index) => ({
      id: `nic-${index}`,
      type: "network.interface",
      name: `Interface ${index}`,
      status: "healthy",
      parent_id: "rg-a",
    }));
    const evidenceGraph: InventoryGraphResponse = {
      ...GRAPH,
      resources: [...GRAPH.resources, ...publicIps, ...nics],
      links: [
        ...GRAPH.links,
        ...publicIps.flatMap((resource, index) => [
          { source: resource.id, target: nics[index]!.id, type: "attached_to" as const },
          { source: nics[index]!.id, target: "subnet", type: "attached_to" as const },
        ]),
      ],
    };
    const overview = architectureNetworkOverviewGraph(evidenceGraph);
    const visiblePublicIps = overview.resources.filter((resource) =>
      resource.id.startsWith("public-"));

    expect(visiblePublicIps).toHaveLength(ARCHITECTURE_NETWORK_OVERVIEW_LIMIT);
    expect(visiblePublicIps.every((resource) =>
      resource.network_plane_id === "subnet")).toBe(true);
    expect(overview.resources.some((resource) => resource.id.startsWith("nic-"))).toBe(false);
    const withPath = architectureNetworkPathPresentationGraph(
      overview,
      evidenceGraph,
      ["vm", "nic"],
    );
    expect(withPath.resources.filter((resource) => resource.id.startsWith("public-"))
      .every((resource) => resource.network_plane_id === "subnet")).toBe(true);
  });

  it("allocates Subnets across ranked VNets before taking another from one VNet", () => {
    const vnets = [
      { id: "vnet-primary", type: "network.vnet", name: "Primary", status: "healthy", parent_id: "rg-a" },
      { id: "vnet-secondary", type: "network.vnet", name: "Secondary", status: "healthy", parent_id: "rg-a" },
    ];
    const primarySubnets = Array.from({ length: 10 }, (_, index) => ({
      id: `z-primary-${index}`,
      type: "network.subnet",
      name: `Z primary ${index}`,
      status: "healthy",
      parent_id: "vnet-primary",
    }));
    const secondarySubnets = Array.from({ length: 9 }, (_, index) => ({
      id: `a-secondary-${index}`,
      type: "network.subnet",
      name: `A secondary ${index}`,
      status: "healthy",
      parent_id: "vnet-secondary",
    }));
    const overview = architectureNetworkOverviewGraph({
      ...GRAPH,
      resources: [
        ...GRAPH.resources.filter((resource) =>
          !VNET_TYPES_FOR_TEST.has(resource.type)
          && !SUBNET_TYPES_FOR_TEST.has(resource.type)),
        ...vnets,
        ...primarySubnets,
        ...secondarySubnets,
      ],
      links: [],
    });
    const subnetIds = overview.resources
      .filter((resource) => resource.type === "network.subnet")
      .map((resource) => resource.id);

    expect(subnetIds.filter((id) => id.startsWith("z-primary-"))).toHaveLength(2);
    expect(subnetIds.filter((id) => id.startsWith("a-secondary-"))).toHaveLength(2);
  });

  it("adds exact path hops back to the bounded presentation", () => {
    const overview = architectureNetworkOverviewGraph(GRAPH);
    const presented = architectureNetworkPathPresentationGraph(
      overview,
      GRAPH,
      ["public", "nic", "vm", "db"],
    );
    const ids = new Set(presented.resources.map((resource) => resource.id));

    expect(ids.has("vm")).toBe(true);
    expect(ids.has("db")).toBe(true);
    expect(presented.links).toContainEqual({
      source: "vm",
      target: "db",
      type: "depends_on",
    });
  });

  it("adds an omitted path Resource's inferred Subnet and VNet ancestors", () => {
    const evidenceGraph: InventoryGraphResponse = {
      ...GRAPH,
      resources: [
        ...GRAPH.resources,
        { id: "vnet-omitted", type: "network.vnet", name: "Omitted network", status: "healthy", parent_id: "rg-b" },
        { id: "subnet-omitted", type: "network.subnet", name: "Omitted subnet", status: "healthy", parent_id: "vnet-omitted" },
        { id: "nic-omitted", type: "network.interface", name: "Omitted interface", status: "healthy", parent_id: "rg-b" },
        { id: "role-omitted", type: "network.public-ip", name: "Omitted role", status: "healthy", parent_id: "rg-b" },
      ],
      links: [
        ...GRAPH.links,
        { source: "role-omitted", target: "nic-omitted", type: "attached_to" },
        { source: "nic-omitted", target: "subnet-omitted", type: "attached_to" },
      ],
    };
    const presented = architectureNetworkPathPresentationGraph(
      architectureNetworkOverviewGraph(GRAPH),
      evidenceGraph,
      ["role-omitted"],
    );
    const ids = new Set(presented.resources.map((resource) => resource.id));

    expect(presented.resources.find((resource) =>
      resource.id === "role-omitted")?.network_plane_id).toBe("subnet-omitted");
    expect(ids.has("subnet-omitted")).toBe(true);
    expect(ids.has("vnet-omitted")).toBe(true);
    expect(ids.has("rg-b")).toBe(true);
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
