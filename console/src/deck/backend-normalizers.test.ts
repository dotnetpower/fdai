import { describe, expect, it } from "vitest";
import {
  isSemanticDirectResponseSource,
  newRequestId,
  parseAnswerVerification,
  parseDelegation,
  parseModelUsage,
  parseSemanticProjectionReceipt,
  queueNextRequestId,
  semanticDirectResponseSource,
  tokenSuffix,
} from "./backend-normalizers";

const PROJECTION_ID = `00000000-0000-4000-8000-${"0".repeat(12)}`;
const REQUEST_ID = `00000000-0000-4000-8000-${"0".repeat(11)}1`;
const DIGEST = `sha256:${"a".repeat(64)}`;

describe("request identity replay", () => {
  it("consumes a verified replay UUID exactly once", () => {
    queueNextRequestId(REQUEST_ID);

    expect(newRequestId()).toBe(REQUEST_ID);
    expect(newRequestId()).not.toBe(REQUEST_ID);
  });

  it("rejects a malformed replay identity", () => {
    expect(() => queueNextRequestId("request-1")).toThrow("must be a UUID");
  });
});

function semanticReceipt(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "1.0.0",
    projection_id: PROJECTION_ID,
    request_id: REQUEST_ID,
    disposition: "answered",
    reason_code: "verified_answer",
    semantic_route: "verified_query_plan",
    ontology_release_digest: DIGEST,
    principal_manifest_digest: DIGEST,
    plan_digest: DIGEST,
    execution_receipt_digest: DIGEST,
    execution_authority: false,
    ...overrides,
  };
}

describe("parseSemanticProjectionReceipt", () => {
  it("keeps exact evidence identity without action authority", () => {
    expect(parseSemanticProjectionReceipt(semanticReceipt())).toEqual(semanticReceipt());
  });

  it.each([
    { projection_id: "not-a-uuid" },
    { request_id: "request-1" },
    { ontology_release_digest: "sha256:bad" },
    { execution_receipt_digest: undefined },
    { execution_authority: true },
    { execution_authority: undefined },
    { semantic_route: "semantic_clarification" },
    { semantic_route: undefined },
    { unavailable_reason: "semantic_planner_unavailable" },
  ])("rejects malformed or authority-bearing answered receipts: %o", (override) => {
    expect(parseSemanticProjectionReceipt(semanticReceipt(override))).toBeUndefined();
  });

  it("accepts only typed unavailability for held receipts", () => {
    const held = semanticReceipt({
      disposition: "held",
      semantic_route: undefined,
      unavailable_reason: "authoritative_evidence_unavailable",
      ontology_release_digest: undefined,
      principal_manifest_digest: undefined,
      plan_digest: undefined,
      execution_receipt_digest: undefined,
    });

    expect(parseSemanticProjectionReceipt(held)).toEqual(held);
    expect(parseSemanticProjectionReceipt({ ...held, unavailable_reason: "runtime_failed" }))
      .toBeUndefined();
  });

  it("preserves an evidence-free direct greeting receipt", () => {
    const direct = semanticReceipt({
      disposition: "direct_response",
      reason_code: "semantic_direct_response",
      semantic_route: "semantic_direct_response",
      direct_response_intent: "greeting",
      ontology_release_digest: undefined,
      principal_manifest_digest: undefined,
      plan_digest: undefined,
      execution_receipt_digest: undefined,
    });

    expect(parseSemanticProjectionReceipt(direct)).toEqual(direct);
    expect(parseSemanticProjectionReceipt({ ...direct, direct_response_intent: undefined }))
      .toBeUndefined();
    expect(parseSemanticProjectionReceipt({ ...direct, plan_digest: DIGEST })).toBeUndefined();
  });

  it("preserves an evidence-free self-introduction receipt", () => {
    const direct = semanticReceipt({
      disposition: "direct_response",
      reason_code: "semantic_direct_response",
      semantic_route: "semantic_direct_response",
      direct_response_intent: "self_introduction",
      ontology_release_digest: undefined,
      principal_manifest_digest: undefined,
      plan_digest: undefined,
      execution_receipt_digest: undefined,
    });

    expect(parseSemanticProjectionReceipt(direct)).toEqual(direct);
    expect(parseSemanticProjectionReceipt({ ...direct, direct_response_intent: "identity" }))
      .toBeUndefined();
  });

  it("preserves a strict version 2 semantic assurance observation", () => {
    const observation = {
      schema_version: "1.0.0",
      frame: {
        operation: "select",
        subject_types: ["Resource"],
        measure_concepts: [],
        temporal_scope: "current",
        output_shape: "resource_current_state",
        frame_digest: DIGEST,
      },
      capabilities: ["object_set", "resource_current_state"],
      object_types: ["Resource"],
      link_types: [],
      function_types: ["query.resource_current_state"],
      ontology_paths: [],
      fact_kinds: ["resource.identity"],
      limitation_kinds: [],
      claim_kinds: [],
      evidence_posture: "fresh",
      authority_posture: "read_only",
      read_performed: true,
      observation_digest: DIGEST,
      execution_authority: false,
    };
    const receipt = semanticReceipt({
      schema_version: "2.0.0",
      assurance_observation: observation,
    });

    expect(parseSemanticProjectionReceipt(receipt)).toEqual(receipt);
  });

  it.each([
    { capabilities: ["resource_current_state", "object_set"] },
    { fact_kinds: ["resource.identity", "resource.identity"] },
    { execution_authority: true },
    { unexpected: true },
  ])("rejects malformed semantic assurance observations: %o", (override) => {
    const observation = {
      schema_version: "1.0.0",
      frame: null,
      capabilities: ["object_set"],
      object_types: ["Resource"],
      link_types: [],
      function_types: [],
      ontology_paths: [],
      fact_kinds: [],
      limitation_kinds: [],
      claim_kinds: [],
      evidence_posture: "fresh",
      authority_posture: "read_only",
      read_performed: true,
      observation_digest: DIGEST,
      execution_authority: false,
      ...override,
    };

    expect(parseSemanticProjectionReceipt(semanticReceipt({
      schema_version: "2.0.0",
      assurance_observation: observation,
    }))).toBeUndefined();
  });
});

function claim(overrides: Record<string, unknown> = {}) {
  return {
    claim_id: "c001",
    kind: "id",
    text: "corr-1",
    span: { start: 0, end: 6 },
    raw_value: "corr-1",
    normalized_value: "corr-1",
    unit: null,
    anchors: ["correlation"],
    status: "supported",
    evidence_refs: ["e-1"],
    reason_code: null,
    ...overrides,
  };
}

function manifest(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    manifest_id: "sha256:abc",
    authority: "server_read_model",
    route_id: "incidents",
    captured_at: null,
    complete: true,
    source_entry_count: 1,
    entries: [{
      ref: "e-1",
      path: "/incident/id",
      field: "id",
      kind: "id",
      raw_value: "corr-1",
      normalized_value: "corr-1",
      anchors: ["correlation"],
    }],
    ...overrides,
  };
}

function verification(overrides: Record<string, unknown> = {}) {
  return {
    status: "verified",
    authority: "server_read_model",
    checks_completed: 1,
    checks_total: 1,
    evidence_refs: ["e-1"],
    reason_code: null,
    claims: [claim()],
    failed_claim_ids: [],
    evidence_manifest: manifest(),
    ...overrides,
  };
}

describe("tokenSuffix", () => {
  it("retains bounded telemetry for the observed-work summary", () => {
    expect(parseModelUsage({
      prompt_tokens: 1600,
      completion_tokens: 142,
      total_tokens: 1742,
    })).toEqual({
      prompt_tokens: 1600,
      completion_tokens: 142,
      total_tokens: 1742,
    });
    expect(parseModelUsage({ total_tokens: -1 })).toBeUndefined();
  });

  it("formats nonnegative total and component token usage", () => {
    expect(tokenSuffix({ total_tokens: 0 })).toBe(" · 0 tok");
    expect(tokenSuffix({ prompt_tokens: 800, completion_tokens: 250 })).toBe(" · 1.1k tok");
  });

  it.each([
    { total_tokens: -1 },
    { prompt_tokens: 100, completion_tokens: -150 },
    { prompt_tokens: 100, completion_tokens: -50 },
    { prompt_tokens: -1, completion_tokens: 10 },
  ])("hides invalid negative token telemetry: %o", (usage) => {
    expect(tokenSuffix(usage)).toBe("");
  });

  it("decorates a semantic direct response with measured model telemetry", () => {
    const source = semanticDirectResponseSource(
      "semantic-t1",
      25,
      { prompt_tokens: 12, completion_tokens: 3, total_tokens: 15 },
    );

    expect(source).toBe("semantic-direct-response · semantic-t1 · 25ms · 15 tok");
    expect(isSemanticDirectResponseSource(source)).toBe(true);
  });
});

describe("parseDelegation", () => {
  it("keeps a bounded specialist-to-Bragi handoff", () => {
    expect(parseDelegation({
      primary_agent: "Bragi",
      contributors: [],
      trace_ref: "trace-handoff",
      handoff_from: "Heimdall",
      handoff_reason: "insufficient_agent_evidence",
    })).toEqual({
      primary_agent: "Bragi",
      contributors: [],
      trace_ref: "trace-handoff",
      handoff_from: "Heimdall",
      handoff_reason: "insufficient_agent_evidence",
    });
  });

  it("rejects unknown or oversized agent identities", () => {
    expect(parseDelegation({
      primary_agent: "UnknownAgent",
      contributors: [],
    })).toBeUndefined();
    expect(parseDelegation({
      primary_agent: "Bragi".repeat(20),
      contributors: [],
    })).toBeUndefined();
    expect(parseDelegation({
      primary_agent: "Bragi",
      contributors: ["Heimdall", "UnknownAgent", "Forseti".repeat(20)],
    })).toEqual({
      primary_agent: "Bragi",
      contributors: ["Heimdall"],
    });
  });

  it("trims handoff reasons and drops whitespace-only values", () => {
    expect(parseDelegation({
      primary_agent: "Bragi",
      contributors: [],
      handoff_from: "Heimdall",
      handoff_reason: "  insufficient_agent_evidence  ",
    })?.handoff_reason).toBe("insufficient_agent_evidence");
    expect(parseDelegation({
      primary_agent: "Bragi",
      contributors: [],
      handoff_from: "Heimdall",
      handoff_reason: "  \t\n ",
    })?.handoff_reason).toBeUndefined();
  });
});

describe("parseAnswerVerification", () => {
  it("keeps ontology-query claims independent from verified plan-check counts", () => {
    const parsed = parseAnswerVerification(verification({
      authority: "ontology-query",
      claims: [
        claim({ claim_id: "semantic-fact", text: "resource.runtime_state" }),
        claim({
          claim_id: "semantic-limitation",
          text: "missing_resource_state_is_unknown",
        }),
      ],
      evidence_manifest: undefined,
    }));

    expect(parsed?.status).toBe("verified");
    expect(parsed?.claims).toHaveLength(2);
  });

  it.each([
    { checks_completed: -1, checks_total: 1 },
    { checks_completed: 1.5, checks_total: 2 },
    { checks_completed: 2, checks_total: 1 },
  ])("downgrades invalid verification counters: %o", (counters) => {
    const parsed = parseAnswerVerification(verification(counters));

    expect(parsed).toMatchObject({
      status: "unverified",
      checks_completed: 0,
      checks_total: 0,
      reason_code: "malformed_verification_artifact",
    });
  });

  it.each([
    { span: { start: -1, end: 6 } },
    { span: { start: 7, end: 6 } },
    { span: { start: 0.5, end: 6 } },
  ])("downgrades invalid claim spans: %o", (claimOverride) => {
    const parsed = parseAnswerVerification(verification({ claims: [claim(claimOverride)] }));
    expect(parsed?.status).toBe("unverified");
    expect(parsed?.reason_code).toBe("malformed_verification_artifact");
  });

  it.each([
    manifest({ schema_version: 2 }),
    manifest({ source_entry_count: 0 }),
    manifest({ entries: [manifest().entries[0], manifest().entries[0]] }),
  ])("downgrades an inconsistent evidence manifest", (evidenceManifest) => {
    const parsed = parseAnswerVerification(verification({ evidence_manifest: evidenceManifest }));
    expect(parsed?.status).toBe("unverified");
    expect(parsed?.reason_code).toBe("malformed_verification_artifact");
  });

  it.each([
    { claims: [claim({ evidence_refs: ["missing"] })] },
    { failed_claim_ids: ["missing"] },
    { claims: [claim(), claim()] },
  ])("downgrades dangling or duplicate claim references: %o", (artifact) => {
    const parsed = parseAnswerVerification(verification(artifact));
    expect(parsed?.status).toBe("unverified");
    expect(parsed?.reason_code).toBe("malformed_verification_artifact");
  });

  it.each([
    { evidence_refs: Array(521).fill("e-1") },
    { claims: Array(65).fill(claim()) },
    { evidence_manifest: manifest({ source_entry_count: 513 }) },
    { evidence_manifest: manifest({ entries: Array(513).fill(manifest().entries[0]) }) },
    { reason_code: "r".repeat(1025) },
    { claims: [claim({ text: "x".repeat(16 * 1024 + 1) })] },
  ])("bounds verification artifact payloads: %o", (artifact) => {
    const parsed = parseAnswerVerification(verification(artifact));
    expect(parsed?.status).toBe("unverified");
    expect(parsed?.reason_code).toBe("malformed_verification_artifact");
    expect(parsed?.claims?.length ?? 0).toBeLessThanOrEqual(64);
    expect(parsed?.evidence_refs.length).toBeLessThanOrEqual(520);
  });

  it.each([
    { status: "verified", checks_completed: 0, checks_total: 1, claims: [], evidence_manifest: undefined },
    { evidence_refs: ["e-1", "e-1"] },
    { failed_claim_ids: ["c001"] },
    {
      claims: [claim({ status: "unsupported" })],
      failed_claim_ids: [],
      checks_completed: 0,
    },
    {
      claims: [claim({ status: "unsupported", evidence_refs: ["e-1", "e-1"] })],
      failed_claim_ids: ["c001"],
      checks_completed: 0,
    },
    { evidence_manifest: manifest({ authority: "other_authority" }) },
  ])("downgrades semantically contradictory verification metadata: %o", (artifact) => {
    const parsed = parseAnswerVerification(verification(artifact));
    expect(parsed?.status).toBe("unverified");
    expect(parsed?.reason_code).toBe("malformed_verification_artifact");
  });
});
