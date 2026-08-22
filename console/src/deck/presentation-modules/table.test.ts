import { describe, expect, test } from "vitest";
import {
  presentationColumnLabel,
  presentationFieldRole,
  presentationTableLayout,
} from "./table";

describe("verified table field roles", () => {
  test.each([
    ["name", "name"],
    ["Name", "name"],
    ["resource.name", "name"],
    ["type", "type"],
    ["properties.location", "location"],
    ["observed_state", "state"],
    ["state_concept", "concept"],
    ["source_observed_at", "timestamp"],
    ["inventory_read_at", "timestamp"],
    ["object_type", undefined],
    ["id", undefined],
  ])("maps %s to %s", (label, expected) => {
    expect(presentationFieldRole(label)).toBe(expected);
  });

  test("uses a wide layout only when the reading-width table would be crowded", () => {
    expect(presentationTableLayout(3)).toBe("compact");
    expect(presentationTableLayout(4)).toBe("balanced");
    expect(presentationTableLayout(5)).toBe("wide");
    expect(presentationTableLayout(8)).toBe("wide");
  });

  test.each([
    ["observed_state", "observed state"],
    ["resource.state_concept", "resource state concept"],
    ["inventory-read_at", "inventory-read at"],
  ])("renders %s as the readable heading %s", (label, expected) => {
    expect(presentationColumnLabel(label)).toBe(expected);
  });
});
