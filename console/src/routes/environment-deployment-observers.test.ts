import { describe, expect, it } from "vitest";
import { decodeObserverProposals } from "./observer-proposals";
import { effectiveObserverStatus, filterObserverProposals, nextObserverExpiryDelay } from "./environment-deployment-observers";

const expires = Date.parse("2026-10-01T10:00:00Z");
const items = decodeObserverProposals({
  synthetic: false, execution_authority: false,
  items: [{
    target_ref: "cluster-example", expires_at: new Date(expires).toISOString(),
    state: "current", execution_authority: false,
    proposal: { target_ref: "cluster-example", status: "needs_evidence", execution_authority: false,
      approval_required: true, recommended: null,
      candidates: [{ method: "gitops", egress: "private", state: "unknown", blockers: [], missing: ["kubernetes_read"] }] },
  }, {
    target_ref: "cluster-unavailable", expires_at: new Date(expires).toISOString(),
    state: "unavailable", execution_authority: false, proposal: null,
  }],
});

describe("environment observer evidence freshness", () => {
  it("uses the same effective status for the screen and published records", () => {
    expect(effectiveObserverStatus(items[0]!, expires - 1)).toBe("needs_evidence");
    expect(effectiveObserverStatus(items[0]!, expires)).toBe("expired");
    expect(effectiveObserverStatus(items[1]!, expires)).toBe("unavailable");
  });
  it("only schedules the next live expiry, with a bounded timer delay", () => {
    expect(nextObserverExpiryDelay([], expires - 1000)).toBeNull();
    expect(nextObserverExpiryDelay([items[1]!], expires - 1000)).toBeNull();
    expect(nextObserverExpiryDelay(items, expires - 1000)).toBe(1020);
    expect(nextObserverExpiryDelay(items, expires)).toBeNull();
    expect(nextObserverExpiryDelay([{ ...items[0]!, expiresAt: expires + 9_000_000_000 }], expires)).toBe(2_147_483_647);
  });
  it("filters by target and effective status while keeping expired evidence separate", () => {
    expect(filterObserverProposals(items, "EXAMPLE", "", expires - 1)).toEqual([items[0]]);
    expect(filterObserverProposals(items, "", "expired", expires)).toEqual([items[0]]);
    expect(filterObserverProposals(items, "", "unavailable", expires)).toEqual([items[1]]);
    expect(filterObserverProposals(items, "missing", "", expires)).toEqual([]);
  });
});
