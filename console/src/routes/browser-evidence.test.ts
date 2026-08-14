import { describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import { decodeBrowserEvidence, loadBrowserEvidenceState } from "./browser-evidence";

const artifact = {
  artifact_id: `sha256:${"a".repeat(64)}`,
  policy_id: "dashboard",
  policy_version: 1,
  source_url: "https://dashboard.example/evidence",
  final_url: "https://dashboard.example/evidence",
  captured_at: "2026-07-21T12:00:00+00:00",
  expires_at: "2026-07-28T12:00:00+00:00",
  selector_count: 1,
  screenshot_hash: null,
  text_hash: "b".repeat(64),
  snapshot_hash: null,
  redaction_count: 2,
  prompt_injection_finding_count: 1,
  browser_version: "chromium-test",
  custody_audit_ref: "audit:browser:1",
  untrusted: true,
  isolation_verified: true,
  legal_hold: false,
  legal_hold_ref: null,
  legal_hold_at: null,
};

const response = (item: Record<string, unknown> = artifact) => ({
  surface: "browser-evidence",
  count: 1,
  items: [item],
});

function panelClient(
  handler: () => Promise<unknown>,
): Pick<OperatorApiClient, "panel"> {
  return {
    async panel<T>(): Promise<T> {
      return await handler() as T;
    },
  };
}

describe("browser evidence decoder", () => {
  it("accepts metadata-only read and shadow evidence", () => {
    const result = decodeBrowserEvidence(response());
    expect(result.items[0]?.source_host).toBe("dashboard.example");
    expect(result.items[0]?.redaction_count).toBe(2);
    expect(result.items[0]?.hash_count).toBe(1);
  });

  it("rejects controls and captured or structured payloads", () => {
    expect(() => decodeBrowserEvidence({ ...response(), capture_controls: false })).toThrow(/not allowed/);
    for (const key of ["screenshot", "visible_text", "aria_snapshot", "selectors", "redaction_manifest", "prompt_injection_findings", "isolation"]) {
      expect(() => decodeBrowserEvidence(response({ ...artifact, [key]: "private" }))).toThrow(/not allowed/);
    }
  });

  it("rejects malformed identity, time, trust, isolation, and hold metadata", () => {
    const payload = (overrides: Record<string, unknown>) => ({
      surface: "browser-evidence",
      count: 1,
      items: [{ ...artifact, ...overrides }],
    });
    expect(() => decodeBrowserEvidence({ ...payload({}), surface: "other" })).toThrow(/surface is invalid/);
    expect(() => decodeBrowserEvidence({ ...payload({}), count: 0 })).toThrow(/count MUST match/);
    expect(() => decodeBrowserEvidence(payload({ source_url: "file:\/\/etc\/passwd" }))).toThrow(/canonical HTTPS/);
    expect(() => decodeBrowserEvidence(payload({ text_hash: "not-a-hash" }))).toThrow(/text_hash is invalid/);
    expect(() => decodeBrowserEvidence(payload({ captured_at: "yesterday" }))).toThrow(/RFC 3339/);
    expect(() => decodeBrowserEvidence(payload({ untrusted: false }))).toThrow(/MUST be untrusted/);
    expect(() => decodeBrowserEvidence(payload({ isolation_verified: false }))).toThrow(/MUST be verified/);
    expect(() => decodeBrowserEvidence(payload({ legal_hold: true }))).toThrow(/legal hold is inconsistent/);
    expect(() => decodeBrowserEvidence(payload({ legal_hold_ref: "case-1" }))).toThrow(/legal hold is inconsistent/);
    expect(() => decodeBrowserEvidence({ surface: "browser-evidence", count: 501, items: Array.from({ length: 501 }, () => artifact) })).toThrow(/exceed 500/);
  });

  it("classifies ready, unavailable, and invalid responses", async () => {
    const readyHandler = vi.fn(async () => response());
    const unavailableHandler = vi.fn(async () => {
      throw new OperatorApiError(503, "unavailable");
    });
    const invalidHandler = vi.fn(async () => ({ surface: "wrong", count: 0, items: [] }));

    await expect(loadBrowserEvidenceState(panelClient(readyHandler))).resolves.toMatchObject({ status: "ready" });
    await expect(loadBrowserEvidenceState(panelClient(unavailableHandler))).resolves.toMatchObject({ status: "unavailable" });
    await expect(loadBrowserEvidenceState(panelClient(invalidHandler))).resolves.toMatchObject({ status: "error" });
  });
});
