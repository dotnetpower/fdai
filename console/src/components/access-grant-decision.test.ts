import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthContext } from "../auth";
import type { AccessGrantRequestProjection } from "../hooks/use-access-grant-stream";
import {
  decodeAccessGrantDecisionReceipt,
  reviewAccessGrant,
} from "./access-grant-decision";

const request: AccessGrantRequestProjection = {
  request_id: "request-1",
  correlation_id: "incident-1",
  capability_id: "kubernetes.metrics.read",
  scope_ref: "scope://example/cluster/namespace/example-app",
  grant_mode: "time_bound",
  requested_at: "2026-08-04T00:00:00Z",
  expires_at: "2026-08-04T01:00:00Z",
  quorum: 1,
  status: "pending",
  revision: 3,
};

const receipt = {
  request_id: "request-1",
  status: "approved",
  revision: 4,
  approved_count: 1,
  quorum: 1,
  reviewed_at: "2026-08-04T00:10:00Z",
  permission_applied: false,
  fresh_probe_required: true,
};

afterEach(() => vi.unstubAllGlobals());

describe("access grant decision", () => {
  it("accepts only receipts that preserve the apply and fresh-probe boundary", () => {
    expect(decodeAccessGrantDecisionReceipt(receipt)).toEqual(receipt);
    expect(() => decodeAccessGrantDecisionReceipt({ ...receipt, permission_applied: true }))
      .toThrow("malformed");
    expect(() => decodeAccessGrantDecisionReceipt({ ...receipt, fresh_probe_required: false }))
      .toThrow("malformed");
  });

  it("posts the exact request revision and requires a review reason", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(receipt), {
      status: 200,
      headers: { "content-type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const auth = { getAuthorizationHeader: async () => "Bearer test" } as AuthContext;

    await expect(reviewAccessGrant(auth, "https://example.com", request, "approve", "  reviewed  "))
      .resolves.toEqual(receipt);
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      decision: "approve",
      reason: "reviewed",
      expected_revision: 3,
    });
    await expect(reviewAccessGrant(auth, "https://example.com", request, "reject", " "))
      .rejects.toThrow("reason is required");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
