import { describe, expect, test } from "vitest";
import { decodeObserverProposals } from "./observer-proposals";

const unavailable = {
  synthetic: false, execution_authority: false,
  items: [{ target_ref: "cluster-example", expires_at: "2026-09-19T00:01:00Z", state: "unavailable", proposal: null, execution_authority: false }],
};

describe("observer proposal boundaries", () => {
  test("preserves unavailable evidence without inventing a recommendation", () => {
    expect(decodeObserverProposals(unavailable)[0]?.status).toBe("unavailable");
    expect(decodeObserverProposals(unavailable)[0]?.recommended).toBeNull();
  });
  test("rejects authority, synthetic input and duplicate targets", () => {
    expect(() => decodeObserverProposals({ ...unavailable, execution_authority: true })).toThrow();
    expect(() => decodeObserverProposals({ ...unavailable, synthetic: true })).toThrow();
    expect(() => decodeObserverProposals({ ...unavailable, items: [...unavailable.items, ...unavailable.items] })).toThrow();
  });
});
