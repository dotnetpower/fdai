import { describe, expect, it } from "vitest";
import {
  architectureNetworkActiveIds,
  architectureNetworkLinkPath,
  architectureNetworkMapBounds,
} from "./architecture-network-map";
import {
  architectureNetworkIconForResourceType,
  architectureNetworkIconSourceIsSafe,
} from "./architecture-network-icons";

describe("2D network map bounds", () => {
  it("contains regions and centered resource nodes with stable padding", () => {
    const bounds = architectureNetworkMapBounds([
      { id: "vnet", type: "network.vnet", name: "Network", status: "healthy", x: 2, y: 3, w: 8, h: 5 },
      { id: "vm", type: "compute.vm", name: "VM", status: "healthy", x: 9.5, y: 7.5 },
    ]);
    expect(bounds.x).toBeLessThanOrEqual(1.5);
    expect(bounds.y).toBeLessThanOrEqual(2.5);
    expect(bounds.x + bounds.width).toBeGreaterThanOrEqual(10.5);
    expect(bounds.y + bounds.height).toBeGreaterThanOrEqual(8.5);
  });

  it("maps reviewed resource types to official SVG icons and leaves unknown types unmapped", () => {
    expect(architectureNetworkIconForResourceType("network.interface")).toMatch(
      /^(?:data:image\/svg\+xml|.*\.svg$)/,
    );
    expect(architectureNetworkIconForResourceType("compute.vm")).toMatch(
      /^(?:data:image\/svg\+xml|.*\.svg$)/,
    );
    expect(architectureNetworkIconForResourceType("future.network/type")).toBeUndefined();
  });

  it("allows internal SVG references and rejects active or external icon content", () => {
    expect(architectureNetworkIconSourceIsSafe('<svg xmlns="http://www.w3.org/2000/svg"><linearGradient id="a"/><path href="#a"/></svg>')).toBe(true);
    expect(architectureNetworkIconSourceIsSafe('<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/icon.svg"/></svg>')).toBe(false);
    expect(architectureNetworkIconSourceIsSafe('<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>')).toBe(false);
  });

  it("terminates relationships on node and region boundaries instead of their centers", () => {
    const path = architectureNetworkLinkPath(
      { id: "nic", type: "network.interface", name: "Interface", status: "healthy", x: 2, y: 2 },
      { id: "subnet", type: "network.subnet", name: "Subnet", status: "healthy", x: 0, y: 0, w: 6, h: 6 },
    );
    expect(path).not.toContain("M2 2");
    expect(path).toMatch(/L0 3$/);
  });

  it("keeps highlighted nodes' subnet, VNet, and parent boundaries active", () => {
    const graph = {
      resources: [
        { id: "group", type: "resource-group", name: "Group", status: "healthy" as const },
        { id: "vnet", type: "network.vnet", name: "VNet", status: "healthy" as const, parent_id: "group" },
        { id: "subnet", type: "network.subnet", name: "Subnet", status: "healthy" as const, parent_id: "group" },
        { id: "vm", type: "compute.vm", name: "VM", status: "healthy" as const, parent_id: "group", network_plane_id: "subnet" },
        { id: "other", type: "compute.vm", name: "Other", status: "healthy" as const, parent_id: "group" },
      ],
      links: [{ source: "vnet", target: "subnet", type: "contains" as const }],
    };
    const active = architectureNetworkActiveIds(graph, new Set(["vm"]));
    expect(active).toEqual(new Set(["vm", "subnet", "group", "vnet"]));
    expect(active?.has("other")).toBe(false);
  });
});
