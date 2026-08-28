import { describe, expect, it } from "vitest";
import type {
  CostGovernanceAvailability,
  CostGovernanceProjection,
  CostGovernanceSurface,
} from "../api-cost-governance";
import {
  isCostGovernanceNavigationVisible,
  loadCostGovernance,
} from "./cost-governance.model";

const projection: CostGovernanceProjection = {
  surface: "overview",
  complete: true,
  source_authority: "cost-observation",
  items: [],
  suppressed_count: 0,
};

class RecordingClient {
  readonly calls: string[] = [];
  availability: CostGovernanceAvailability = {
    available: true,
    enabled: true,
    access_allowed: true,
    availability_reasons: [],
    reason: null,
    activation_revision: 3,
    package_version: "0.1.0",
    image_digest: `sha256:${"b".repeat(64)}`,
    asset_manifest_digest: `sha256:${"c".repeat(64)}`,
    semantic_profile_digest: `sha256:${"d".repeat(64)}`,
    ontology_release_digest: `sha256:${"e".repeat(64)}`,
  };

  async costGovernanceAvailability(): Promise<CostGovernanceAvailability> {
    this.calls.push("availability");
    return this.availability;
  }

  async costGovernance(surface: CostGovernanceSurface): Promise<CostGovernanceProjection> {
    this.calls.push(surface);
    return { ...projection, surface };
  }
}

describe("Cost Governance source preflight", () => {
  it("does not request projection data when package availability fails", async () => {
    const client = new RecordingClient();
    client.availability = {
      available: false,
      enabled: false,
      access_allowed: true,
      availability_reasons: ["host_incompatible"],
      reason: "host_incompatible",
      activation_revision: 4,
      package_version: "0.1.0",
      image_digest: `sha256:${"b".repeat(64)}`,
      asset_manifest_digest: `sha256:${"c".repeat(64)}`,
      semantic_profile_digest: `sha256:${"d".repeat(64)}`,
      ontology_release_digest: `sha256:${"e".repeat(64)}`,
    };
    await loadCostGovernance(client, "overview");
    expect(client.calls).toEqual(["availability"]);
  });

  it("does not request projection data when per-user access fails", async () => {
    const client = new RecordingClient();
    client.availability = {
      available: false,
      enabled: false,
      access_allowed: false,
      availability_reasons: ["package_absent"],
      reason: "access_grant_missing",
      activation_revision: null,
      package_version: null,
      image_digest: null,
      asset_manifest_digest: null,
      semantic_profile_digest: null,
      ontology_release_digest: null,
    };
    await loadCostGovernance(client, "outcomes");
    expect(client.calls).toEqual(["availability"]);
    expect(isCostGovernanceNavigationVisible(client.availability)).toBe(false);
  });

  it("does not request projection data when an available package is disabled", async () => {
    const client = new RecordingClient();
    client.availability = { ...client.availability, enabled: false };
    await loadCostGovernance(client, "overview");
    expect(client.calls).toEqual(["availability"]);
    expect(isCostGovernanceNavigationVisible(client.availability)).toBe(false);
  });

  it("loads each of the four production surfaces only after preflight", async () => {
    for (const surface of [
      "overview",
      "resource-efficiency",
      "optimization-cases",
      "outcomes",
    ] as const) {
      const client = new RecordingClient();
      const result = await loadCostGovernance(client, surface);
      expect(client.calls).toEqual(["availability", surface]);
      expect("surface" in result && result.surface).toBe(surface);
    }
  });
});
