import { describe, expect, it } from "vitest";

import { decodeConfigurationBaselines } from "./configuration-baselines";

describe("configuration baselines decoder", () => {
  it("decodes the bounded read-only projection", () => {
    const value = decodeConfigurationBaselines({ baseline: { version: "v1", scope: "example", created_at: "2026-08-04T00:00:00Z", document_name: "baseline.docx", lifecycle: "active-pinned", resource_count: 3, topology_count: 2, unknown_count: 0 }, drift: { verdict: "passed", observed_at: "2026-08-04T00:01:00Z", finding_count: 3, counts: {} }, knowledge: { status: "cited", citation_count: 1, citations: ["knowledge:baseline"] }, safety: { mutation_count: 0, approval_request_count: 0, mitigation_execution_count: 0, unsupported_claim_count: 0 }, performance: { total_ms: 10, observation_ms: 8, knowledge_ms: 1 }, review: { configured: false, state: "not-configured", completed_runs: 0, required_runs: 3 } });
    expect(value.baseline.resourceCount).toBe(3);
    expect(value.knowledge.citationCount).toBe(1);
    expect(value.safety.mutation).toBe(0);
    expect(value.performance.totalMs).toBe(10);
  });

  it("rejects an incomplete projection", () => {
    expect(() => decodeConfigurationBaselines({ baseline: {}, drift: {}, knowledge: {}, safety: {}, performance: {}, review: {} })).toThrow();
  });
});
