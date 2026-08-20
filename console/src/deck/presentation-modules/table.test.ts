import { describe, expect, test } from "vitest";
import { presentationFieldRole } from "./table";

describe("verified table field roles", () => {
  test.each([
    ["name", "name"],
    ["Name", "name"],
    ["resource.name", "name"],
    ["type", "type"],
    ["properties.location", "location"],
    ["object_type", undefined],
    ["id", undefined],
  ])("maps %s to %s", (label, expected) => {
    expect(presentationFieldRole(label)).toBe(expected);
  });
});
