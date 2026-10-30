import { describe, expect, test } from "vitest";
import { decodeControlEnablement, decodeSeveritySource } from "./control-enablement.model";

const setting = { severity: "low", default_enabled: false, enabled: true, source: "profile_override", mode: "shadow", execution_authority: false };

describe("server-owned enablement boundary", () => {
  test("preserves explicit profile overrides without recalculating severity defaults or readiness", () => {
    expect(decodeControlEnablement(setting)).toEqual(setting);
    expect(decodeControlEnablement({ ...setting, available: false, unavailable_reason: "missing_evidence", future_metadata: "ignored" }))
      .toEqual({ ...setting, available: false, unavailable_reason: "missing_evidence" });
    expect(decodeControlEnablement({ ...setting, severity: "critical", default_enabled: false, enabled: false }))
      .toMatchObject({ default_enabled: false, enabled: false });
  });

  test("keeps absent settings and missing published severity explicit", () => {
    expect(decodeControlEnablement(undefined)).toBeNull();
    expect(decodeControlEnablement(null)).toBeNull();
    expect(decodeSeveritySource(undefined)).toBeNull();
    expect(decodeSeveritySource("fdai_default")).toBe("fdai_default");
    expect(decodeSeveritySource("source")).toBe("source");
    expect(() => decodeSeveritySource("inferred")).toThrow(/severity source/);
  });

  test.each([
    { enabled: "true" }, { default_enabled: null }, { available: "false" },
    { execution_authority: true }, { execution_authority: undefined }, { mode: "enforce" },
    { severity: "urgent" }, { source: "browser_override" }, { unavailable_reason: 0 },
  ])("rejects malformed or authority-bearing setting %j", (change) => {
    expect(() => decodeControlEnablement({ ...setting, ...change })).toThrow(/invalid Operator API response/);
  });

  test.each(["severity_default", "profile_override", "lifecycle_disabled"])("retains the server setting source %s", (source) => {
    expect(decodeControlEnablement({ ...setting, source })?.source).toBe(source);
  });
});
