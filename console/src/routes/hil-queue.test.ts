import { describe, expect, test } from "vitest";
import { OperatorApiError } from "../api";
import type { HilQueueItem } from "../types";
import { approvalSearchText, loadHilQueueState, nextApprovalExpiryDelay } from "./hil-queue";

function item(expiresAt: string | null): HilQueueItem {
  return { ttl_expires_at: expiresAt } as HilQueueItem;
}

describe("approval queue source state", () => {
  test("renders optional projection absence as unavailable", async () => {
    const client = {
      listHilQueue: async () => { throw new OperatorApiError(503, "unavailable"); },
    };

    await expect(loadHilQueueState(client, "")).resolves.toEqual({
      status: "unavailable",
      message: expect.any(String),
    });
  });

  test("preserves unexpected failures as errors", async () => {
    const client = {
      listHilQueue: async () => { throw new OperatorApiError(500, "broken"); },
    };

    await expect(loadHilQueueState(client, "restart")).resolves.toEqual({
      status: "error",
      message: "broken",
    });
  });
});

describe("approval expiry clock", () => {
  test("schedules the nearest future expiry and ignores expired or missing TTLs", () => {
    const now = Date.parse("2026-07-17T09:00:00Z");
    expect(nextApprovalExpiryDelay([
      item(null),
      item("2026-07-17T08:59:00Z"),
      item("2026-07-17T09:00:05Z"),
      item("2026-07-17T09:00:20Z"),
    ], now)).toBe(5_020);
    expect(nextApprovalExpiryDelay([item(null), item("2026-07-17T08:59:00Z")], now))
      .toBeNull();
  });

  test("ignores malformed future timestamps", () => {
    const now = Date.parse("2026-07-17T09:00:00Z");
    expect(nextApprovalExpiryDelay([item("not-a-time")], now)).toBeNull();
  });
});

describe("approval search evidence", () => {
  test("indexes action, resource, event, correlation, reason, and rules case-insensitively", () => {
    const approval = {
      idempotency_key: "idem-1",
      action_kind: "Compute.Restart",
      target_resource_ref: "Resource-A",
      event_id: "EVENT-1",
      correlation_id: "CORR-1",
      reason: "Risk Gate",
      reasons: ["Verifier Review"],
      citing_rule_ids: ["Rule.Example"],
      requested_at: "2026-07-17T09:00:00Z",
      approval_id: "approval-1",
      action_id: "action-1",
      mode: "shadow",
      stop_condition: "health probe fails",
      rollback_kind: "pr_revert",
      rollback_reference: null,
      blast_radius_scope: "single_resource",
      blast_radius_count: 1,
      blast_radius_rate_per_minute: null,
      blast_radius_summary: "1 resource",
      ttl_expires_at: null,
    } satisfies HilQueueItem;
    const text = approvalSearchText(approval);
    for (const expected of ["compute.restart", "resource-a", "event-1", "corr-1", "risk gate", "verifier review", "rule.example"]) {
      expect(text).toContain(expected);
    }
  });
});
