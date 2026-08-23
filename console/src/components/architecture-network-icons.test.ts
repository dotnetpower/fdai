import { describe, expect, it } from "vitest";

import {
  architectureNetworkIconDataUriForResourceType,
  architectureNetworkIconForResourceType,
  architectureNetworkIconSourceIsSafe,
} from "./architecture-network-icons";

const REVIEWED_RESOURCE_TYPES = [
  "compute.vm",
  "network.application-gateway",
  "network.firewall",
  "network.interface",
  "network.load-balancer",
  "network.nsg",
  "network.private-endpoint",
  "network.public-ip",
  "network.route-table",
  "network.subnet",
  "network.virtual-network-gateway",
  "network.vnet",
] as const;

describe("reviewed network icons", () => {
  it("resolves and embeds every reviewed resource type without runtime fetch", async () => {
    for (const type of REVIEWED_RESOURCE_TYPES) {
      expect(architectureNetworkIconForResourceType(type)).toMatch(
        /^(?:data:image\/svg\+xml|.*\.svg$|\/@fs\/.*\.svg)/,
      );
      await expect(architectureNetworkIconDataUriForResourceType(type)).resolves.toMatch(
        /^data:image\/svg\+xml;base64,/,
      );
    }
  });

  it("leaves an unknown resource type unmapped", async () => {
    expect(architectureNetworkIconForResourceType("future.network/type")).toBeUndefined();
    await expect(
      architectureNetworkIconDataUriForResourceType("future.network/type"),
    ).resolves.toBeUndefined();
  });

  it("allows internal SVG fragments and rejects executable or external content", () => {
    expect(architectureNetworkIconSourceIsSafe(
      '<svg xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="paint"/></defs><path fill="url(#paint)" href="#paint"/></svg>',
    )).toBe(true);
    expect(architectureNetworkIconSourceIsSafe(
      '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
    )).toBe(false);
    expect(architectureNetworkIconSourceIsSafe(
      '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/icon.svg"/></svg>',
    )).toBe(false);
  });
});
