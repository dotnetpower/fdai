import { describe, expect, it } from "vitest";

import { decodeConfigurationBaselines } from "./configuration-baselines.model";

const projection = {
  baseline: {
    version: "v1",
    scope: "example",
    created_at: "2026-08-04T00:00:00Z",
    document_name: "baseline.docx",
    lifecycle: "active-pinned",
    resource_count: 3,
    topology_count: 2,
    unknown_count: 0,
  },
  versions: [{
    version: "v1",
    status: "active",
    created_at: "2026-08-04T00:00:00Z",
    resource_count: 3,
    topology_count: 2,
    unknown_count: 0,
    comparison: {
      baseline_version: "v1",
      verdict: "passed",
      finding_count: 3,
      counts: { unchanged: 3 },
    },
  }],
  drift: {
    verdict: "passed",
    observed_at: "2026-08-04T00:01:00Z",
    finding_count: 3,
    counts: {},
  },
  knowledge: {
    status: "cited",
    citation_count: 1,
    citations: ["knowledge:baseline"],
  },
  safety: {
    mutation_count: 0,
    approval_request_count: 0,
    mitigation_execution_count: 0,
    unsupported_claim_count: 0,
  },
  performance: {
    total_ms: 10,
    observation_ms: 8,
    knowledge_ms: 1,
  },
  review: {
    configured: false,
    state: "not-configured",
    completed_runs: 0,
    required_runs: 3,
    failed_attempts: 0,
  },
};

describe("configuration baselines decoder", () => {
  it("decodes the bounded read-only projection", () => {
    const value = decodeConfigurationBaselines(projection);
    expect(value.baseline.resourceCount).toBe(3);
    expect(value.knowledge.citationCount).toBe(1);
    expect(value.safety.mutation).toBe(0);
    expect(value.performance?.totalMs).toBe(10);
    expect(value.versions).toHaveLength(1);
    expect(value.versions[0]?.status).toBe("active");
  });

  it("rejects an incomplete projection", () => {
    expect(() => decodeConfigurationBaselines({ baseline: {}, drift: {}, knowledge: {}, safety: {}, performance: {}, review: {} })).toThrow();
  });

  it("keeps unpublished baseline timestamps explicitly unavailable", () => {
    const value = decodeConfigurationBaselines({
      ...projection,
      baseline: {
        ...projection.baseline,
        version: "not-published",
        scope: "none",
        created_at: null,
        document_name: "No published configuration baseline",
        lifecycle: "not-published",
        resource_count: 0,
        topology_count: 0,
      },
      versions: [],
      drift: {
        ...projection.drift,
        verdict: "not-evaluated",
        observed_at: null,
        finding_count: 0,
      },
      knowledge: {
        status: "not-indexed",
        citation_count: 0,
        citations: [],
      },
      performance: null,
      review: {
        ...projection.review,
        required_runs: 0,
      },
    });
    expect(value.baseline.createdAt).toBeNull();
    expect(value.drift.observedAt).toBeNull();
    expect(value.performance).toBeNull();
  });
});
