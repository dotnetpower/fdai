import { describe, expect, it } from "vitest";

import {
  architectureNetworkOrthogonalRoute,
  architectureNetworkPeeringRoute,
} from "./architecture-network-route";

describe("network relationship routing", () => {
  it("routes around an unrelated node between aligned endpoints", () => {
    const points = architectureNetworkOrthogonalRoute(
      { id: "source", x: 0, y: 0, width: 1, height: 1 },
      { id: "target", x: 4, y: 0, width: 1, height: 1 },
      [{ id: "obstacle", x: 2, y: 0, width: 1, height: 1 }],
    );
    expect(points[0]).toEqual({ x: .5, y: 1 });
    expect(points.at(-1)).toEqual({ x: 4.5, y: 1 });
    expect(points.some((point) => point.y > 1)).toBe(true);
  });

  it("connects side-by-side peer boundaries through their header corridor", () => {
    const points = architectureNetworkPeeringRoute(
      { id: "workload", x: 0, y: 1, width: 8, height: 6 },
      { id: "shared", x: 10, y: 1, width: 5, height: 4 },
    );
    expect(points).toEqual([
      { x: 8, y: 1.48 },
      { x: 10, y: 1.48 },
    ]);
  });
});
