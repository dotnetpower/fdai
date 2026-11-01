import { describe, expect, test } from "vitest";
import { planDispatchEligibility, planDisplayStatus } from "./plan-status";

describe("planDisplayStatus", () => {
  const expires_at = "2026-10-15T00:00:00Z";

  test("an unsuperseded Plan is open only before its expiry", () => {
    expect(planDisplayStatus({ status: "open", expires_at }, Date.parse(expires_at) - 1))
      .toEqual({ label: "Open", variant: "info" });
  });

  test("expiry is inclusive and must not imply execution success", () => {
    expect(planDisplayStatus({ status: "open", expires_at }, Date.parse(expires_at)))
      .toEqual({ label: "Expired", variant: "warn" });
  });

  test("supersession remains visible after expiry", () => {
    expect(planDisplayStatus({ status: "superseded", expires_at }, Date.parse(expires_at) + 1))
      .toEqual({ label: "Superseded", variant: "mute" });
  });

  test("distinguishes terminal, in-progress, expired, superseded, and dispatchable Plans (UXH-11)", () => {
    const beforeExpiry = Date.parse(expires_at) - 1000;
    expect(
      planDispatchEligibility({ status: "open", expires_at, reports: [] }, beforeExpiry),
    ).toEqual({
      dispatchable: true,
      label: "Eligible for Agent dispatch within window",
      variant: "info",
    });
    expect(
      planDispatchEligibility(
        {
          status: "open",
          expires_at,
          reports: [
            {
              plan_id: "p1",
              attempt: 1,
              outcome: "applied",
              reason_code: "applied",
              exact_plan_digest: "sha256:" + "a".repeat(64),
              summary: "ok",
              reported_at: expires_at,
              received_at: expires_at,
            },
          ],
        },
        beforeExpiry,
      ).dispatchable,
    ).toBe(false);
    expect(
      planDispatchEligibility(
        {
          status: "open",
          expires_at,
          reports: [
            {
              plan_id: "p1",
              attempt: 1,
              outcome: "rolled-back",
              reason_code: "health_check_failed",
              exact_plan_digest: "sha256:" + "a".repeat(64),
              summary: "rolled back",
              reported_at: expires_at,
              received_at: expires_at,
            },
          ],
        },
        beforeExpiry,
      ),
    ).toEqual({
      dispatchable: false,
      label: "Terminal (rolled-back) · Not dispatchable",
      variant: "fail",
    });
  });
});
