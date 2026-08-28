import { describe, expect, it } from "vitest";
import { decodeCostGovernanceAvailability } from "./api-cost-governance";

describe("Cost Governance availability decoder", () => {
  it("preserves available and enabled as independent fields", () => {
    const decoded = decodeCostGovernanceAvailability({
      available: true,
      enabled: false,
      access_allowed: true,
      availability_reasons: [],
      reason: null,
      activation_revision: 7,
      package_version: "0.1.0",
      image_digest: `sha256:${"a".repeat(64)}`,
      asset_manifest_digest: `sha256:${"b".repeat(64)}`,
      semantic_profile_digest: `sha256:${"c".repeat(64)}`,
      ontology_release_digest: `sha256:${"d".repeat(64)}`,
    });

    expect(decoded.available).toBe(true);
    expect(decoded.enabled).toBe(false);
    expect(decoded.availability_reasons).toEqual([]);
    expect(decoded.activation_revision).toBe(7);
  });

  it("preserves bounded unavailability evidence", () => {
    const decoded = decodeCostGovernanceAvailability({
      available: false,
      enabled: false,
      access_allowed: true,
      availability_reasons: ["missing_provider:cost-estimator"],
      reason: "missing_provider",
      activation_revision: 8,
      package_version: "0.1.0",
      image_digest: `sha256:${"a".repeat(64)}`,
      asset_manifest_digest: `sha256:${"b".repeat(64)}`,
      semantic_profile_digest: `sha256:${"c".repeat(64)}`,
      ontology_release_digest: `sha256:${"d".repeat(64)}`,
    });

    expect(decoded.available).toBe(false);
    expect(decoded.enabled).toBe(false);
    expect(decoded.availability_reasons).toEqual(["missing_provider:cost-estimator"]);
  });
});
