import { describe, expect, test } from "vitest";
import {
  CONTENT_UPDATE_PULSE_MS,
  didContentUpdate,
  shouldPulseContentUpdate,
} from "./use-content-update-pulse";

describe("content update pulse", () => {
  test("distinguishes semantic key changes from unchanged rerenders", () => {
    expect(didContentUpdate("watching|probe-1", "watching|probe-1")).toBe(false);
    expect(didContentUpdate("watching|probe-1", "engaged|probe-2")).toBe(true);
    expect(didContentUpdate(null, null)).toBe(false);
    expect(didContentUpdate(undefined, "measured")).toBe(true);
  });

  test("uses the shared top-edge shimmer duration", () => {
    expect(CONTENT_UPDATE_PULSE_MS).toBe(1_350);
  });

  test("skips first render and coalesces updates while a shimmer is active", () => {
    expect(shouldPulseContentUpdate({
      initialized: false,
      active: false,
      previousKey: undefined,
      nextKey: "watching",
    })).toBe(false);
    expect(shouldPulseContentUpdate({
      initialized: true,
      active: true,
      previousKey: "watching",
      nextKey: "engaged",
    })).toBe(false);
    expect(shouldPulseContentUpdate({
      initialized: true,
      active: false,
      previousKey: "watching",
      nextKey: "engaged",
    })).toBe(true);
  });
});
