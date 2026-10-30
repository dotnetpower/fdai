import { describe, expect, test } from "vitest";
import { decodeControlRemediation } from "./control-remediation.model";

describe("server-owned remediation reference boundary", () => {
  test.each(["manual_guidance", "governed_candidates", "unavailable"])("preserves %s without inferring candidates", (status) => {
    const value = { status, candidates: [], limitations: ["source_unavailable"], execution_authority: false };
    expect(decodeControlRemediation(value)).toEqual(value);
  });

  test("accepts only explicit Rule and ActionType references, not execution authority", () => {
    const value = {
      status: "governed_candidates",
      candidates: [{ rule_id: "storage.https-only", action_type_ref: "storage.enable-https" }],
      limitations: [], execution_authority: false,
    };
    expect(decodeControlRemediation(value)).toEqual(value);
    for (const change of [{ execution_authority: true }, { status: "execution_ready" }, { candidates: [{ rule_id: "example" }] }]) {
      expect(() => decodeControlRemediation({ ...value, ...change })).toThrow(/invalid Operator API response/);
    }
    expect(decodeControlRemediation(undefined)).toBeNull();
  });
});
