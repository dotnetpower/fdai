import { afterEach, describe, expect, it, vi } from "vitest";
import type { OperatorApiClient } from "../api";
import {
  approveRuleActivation,
  isRuleEffectiveEnabled,
  isSeverityDefaultEnabled,
  requestRuleActivation,
} from "./rule-catalog-activation";

const client = {
  authorizationHeader: vi.fn(async () => "Bearer test-only"),
  operatorApiBaseUrl: "http://example.com",
} as unknown as OperatorApiClient;

afterEach(() => vi.unstubAllGlobals());

describe("Rule activation governed requests", () => {
  it("sends membership only with generation concurrency", async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => new Response(
      JSON.stringify({
        accepted: true,
        proposal_id: "operator-" + "a".repeat(32),
        operation: "rule.activation-request",
        mode: "shadow",
        idempotency_key: "request-1",
        revision: "b".repeat(64),
        duplicate: false,
      }),
      { status: 202, headers: { "content-type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("crypto", { randomUUID: () => "request-1" });

    await requestRuleActivation(client, {
      ruleId: "rule.alpha",
      enabled: false,
      reason: "Disable this reviewed Rule after a confirmed operational false positive.",
      generationDigest: "c".repeat(64),
    });

    const init = fetch.mock.calls[0]?.[1];
    expect(new Headers(init?.headers).get("if-match")).toBe("c".repeat(64));
    expect(JSON.parse(String(init?.body))).toEqual({
      mode: "shadow",
      reason: "Disable this reviewed Rule after a confirmed operational false positive.",
      changes: [{ rule_id: "rule.alpha", enabled: false }],
    });
  });

  it("sends an approval without actor or authority claims", async () => {
    const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({
      accepted: true,
      proposal_id: "operator-" + "d".repeat(32),
      operation: "rule.activation-approve",
      mode: "shadow",
      idempotency_key: "approval-1",
      revision: "2026-09-22T00:00:00+00:00",
      duplicate: false,
    }), { status: 202 }));
    vi.stubGlobal("fetch", fetch);
    vi.stubGlobal("crypto", { randomUUID: () => "approval-1" });

    await approveRuleActivation(client, {
      requestId: "operator-" + "a".repeat(32),
      proposalDigest: "b".repeat(64),
    });

    const body = JSON.parse(String(fetch.mock.calls[0]?.[1]?.body));
    expect(body).toEqual({ mode: "shadow", decision: "approve" });
  });

  it("enables critical and high severity rules by default while respecting explicit active membership for lower severities", () => {
    expect(isSeverityDefaultEnabled("critical")).toBe(true);
    expect(isSeverityDefaultEnabled("high")).toBe(true);
    expect(isSeverityDefaultEnabled("medium")).toBe(false);
    expect(isSeverityDefaultEnabled("low")).toBe(false);

    const unavailable = { status: "unavailable" as const, message: "unavailable" };
    expect(isRuleEffectiveEnabled({ id: "collected.high", severity: "high" }, unavailable)).toBe(true);
    expect(isRuleEffectiveEnabled({ id: "collected.critical", severity: "critical" }, unavailable)).toBe(true);
    expect(isRuleEffectiveEnabled({ id: "collected.medium", severity: "medium" }, unavailable)).toBe(false);

    const ready = {
      status: "ready" as const,
      data: {
        revision: 1,
        generation_id: "gen-1",
        generation_digest: "a".repeat(64),
        profile_id: "default",
        profile_version: "1.0.0",
        active_rule_count: 1,
        active_rule_ids: ["active.medium"],
        source: "installation",
        source_ref: "ref",
        requested_by: "req",
        approver_ids: ["app"],
        activated_at: "2026-10-01T00:00:00Z",
        pending_requests: [],
        pending_truncated: false,
        execution_authority: false as const,
      },
    };
    expect(isRuleEffectiveEnabled({ id: "collected.high", severity: "high" }, ready)).toBe(true);
    expect(isRuleEffectiveEnabled({ id: "active.medium", severity: "medium" }, ready)).toBe(true);
    expect(isRuleEffectiveEnabled({ id: "collected.medium", severity: "medium" }, ready)).toBe(false);
  });
});
