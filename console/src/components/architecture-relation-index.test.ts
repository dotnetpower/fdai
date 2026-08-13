import { describe, expect, it } from "vitest";
import { architectureRelationshipIndexLabel } from "./architecture-relation-index";

describe("architecture relationship index labels", () => {
  it("labels inventory peering relationships", () => {
    expect(architectureRelationshipIndexLabel("peered_with")).toBe("Peers with <->");
  });
});
