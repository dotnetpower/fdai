import { describe, expect, it } from "vitest";
import { parseAnswerVerification, tokenSuffix } from "./backend-normalizers";

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
});

describe("parseAnswerVerification", () => {
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
});
