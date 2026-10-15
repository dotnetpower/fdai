import { describe, expect, test } from "vitest";
import { planDisplayStatus } from "./plan-status";

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
});
