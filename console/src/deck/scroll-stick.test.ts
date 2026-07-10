import { describe, expect, it } from "vitest";
import { isNearBottom, STICK_THRESHOLD_PX } from "./scroll-stick";

describe("isNearBottom", () => {
  it("is true when fully scrolled to the bottom", () => {
    // scrollTop == scrollHeight - clientHeight
    expect(isNearBottom(900, 1000, 100)).toBe(true);
  });

  it("is true within the threshold of the bottom", () => {
    // distance = 1000 - 100 - 830 = 70 <= 80
    expect(isNearBottom(830, 1000, 100)).toBe(true);
  });

  it("is false when scrolled up beyond the threshold", () => {
    // distance = 1000 - 100 - 500 = 400 > 80
    expect(isNearBottom(500, 1000, 100)).toBe(false);
  });

  it("is true for a container that does not overflow", () => {
    // distance = 100 - 100 - 0 = 0
    expect(isNearBottom(0, 100, 100)).toBe(true);
  });

  it("respects a custom threshold", () => {
    // distance = 1000 - 100 - 700 = 200
    expect(isNearBottom(700, 1000, 100, 150)).toBe(false);
    expect(isNearBottom(700, 1000, 100, 250)).toBe(true);
  });

  it("tolerates sub-pixel rounding at the exact boundary", () => {
    const scrollTop = 1000 - 100 - STICK_THRESHOLD_PX; // distance == threshold
    expect(isNearBottom(scrollTop, 1000, 100)).toBe(true);
  });
});
