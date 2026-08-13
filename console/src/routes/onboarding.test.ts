import { describe, expect, it } from "vitest";
import { OperatorApiError } from "../api";
import { decodeOnboarding, loadOnboardingState } from "./onboarding";

const payload = {
  probe_mode: "configured",
  ready: false,
  blocked: true,
  missing_resources: ["event_bus"],
  missing_role_assignments: [["executor", "reader", "event_bus"]],
  present_resource_count: 0,
  present_role_count: 0,
};

describe("onboarding response", () => {
  it("renders optional endpoint absence as unavailable", async () => {
    const client = {
      panel: async () => { throw new OperatorApiError(404, "not found"); },
    };

    await expect(loadOnboardingState(client)).resolves.toEqual({
      status: "unavailable",
      message: expect.any(String),
    });
  });

  it("preserves unexpected endpoint failures", async () => {
    const client = {
      panel: async () => { throw new OperatorApiError(500, "broken"); },
    };

    await expect(loadOnboardingState(client)).resolves.toEqual({
      status: "error",
      message: "broken",
    });
  });

  it("preserves a configured probe failure", () => {
    expect(decodeOnboarding({ ...payload, error: "OnboardingProbeError:denied" }).error)
      .toBe("OnboardingProbeError:denied");
  });

  it("accepts legacy omission but rejects malformed probe errors", () => {
    expect(decodeOnboarding(payload).error).toBeNull();
    expect(() => decodeOnboarding({ ...payload, error: { message: "denied" } }))
      .toThrow(/string or null/);
  });

  it("requires each role gap to contain principal, role, and target", () => {
    expect(() => decodeOnboarding({ ...payload, missing_role_assignments: [["executor", "reader"]] }))
      .toThrow(/principal, role, and target/);
  });

  it("rejects contradictory readiness and invalid counts", () => {
    expect(() => decodeOnboarding({ ...payload, ready: true, blocked: true }))
      .toThrow(/MUST NOT both be true/);
    expect(() => decodeOnboarding({ ...payload, ready: false, blocked: false }))
      .toThrow(/either ready or blocked/);
    expect(() => decodeOnboarding({ ...payload, present_resource_count: -1 }))
      .toThrow(/non-negative integer/);
    expect(() => decodeOnboarding({ ...payload, present_role_count: 1.5 }))
      .toThrow(/non-negative integer/);
  });
});
