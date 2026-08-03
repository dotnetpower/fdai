import { describe, expect, it } from "vitest";
import { decodeAccessGrantSnapshot } from "./use-access-grant-stream";

const request = {
  request_id: "request-1",
  correlation_id: "incident-1",
  capability_id: "kubernetes.metrics.read",
  scope_ref: "scope://example/cluster/namespace/example-app",
  grant_mode: "time_bound",
  requested_at: "2026-08-04T00:00:00Z",
  expires_at: "2026-08-04T01:00:00Z",
  quorum: 1,
  status: "pending",
  revision: 0,
};

describe("decodeAccessGrantSnapshot", () => {
  it("accepts the bounded browser projection", () => {
    expect(decodeAccessGrantSnapshot(JSON.stringify({
      event: "access_grant.snapshot",
      ts: "2026-08-04T00:01:00Z",
      requests: [request],
    }))?.requests).toEqual([request]);
  });

  it("rejects malformed request values", () => {
    expect(decodeAccessGrantSnapshot(JSON.stringify({
      event: "access_grant.snapshot",
      ts: "2026-08-04T00:01:00Z",
      requests: [{ ...request, status: "applied" }],
    }))).toBeNull();
  });
});
