import { describe, expect, it } from "vitest";
import { decodeBrowserEvidence } from "./browser-evidence";

const artifact = {
  artifact_id: `sha256:${"a".repeat(64)}`,
  policy_id: "dashboard",
  policy_version: 1,
  canonical_source_url: "https://dashboard.example/evidence",
  canonical_final_url: "https://dashboard.example/evidence",
  captured_at: "2026-07-21T12:00:00+00:00",
  expires_at: "2026-07-28T12:00:00+00:00",
  selectors: ["main"],
  screenshot_hash: null,
  text_hash: "b".repeat(64),
  snapshot_hash: null,
  redaction_count: 2,
  prompt_injection_findings: ["instruction_override"],
  browser_version: "chromium-test",
  chain_of_custody_audit_ref: "audit:browser:1",
  content_digest: "a".repeat(64),
  untrusted: true,
  can_authorize_action: false,
  isolation_verified: true,
};

describe("browser evidence decoder", () => {
  it("accepts metadata-only read and shadow evidence", () => {
    const result = decodeBrowserEvidence({
      read_only: true,
      shadow_only: true,
      count: 1,
      artifacts: [artifact],
      capture_controls: false,
      promotion_controls: false,
      mutation_controls: false,
    });
    expect(result.artifacts[0]?.source_host).toBe("dashboard.example");
    expect(result.artifacts[0]?.redaction_count).toBe(2);
  });

  it("rejects controls and action-authorizing evidence", () => {
    const payload = (overrides: Record<string, unknown>) => ({
      read_only: true,
      shadow_only: true,
      count: 1,
      artifacts: [{ ...artifact, ...overrides }],
      capture_controls: false,
      promotion_controls: false,
      mutation_controls: false,
    });
    expect(() => decodeBrowserEvidence({ ...payload({}), promotion_controls: true })).toThrow(/read-only and shadow-only/);
    expect(() => decodeBrowserEvidence(payload({ can_authorize_action: true }))).toThrow(/cannot authorize action/);
    expect(() => decodeBrowserEvidence(payload({ canonical_source_url: "file:\/\/etc\/passwd" }))).toThrow(/MUST be HTTPS/);
  });
});
