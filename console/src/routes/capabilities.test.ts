import { describe, expect, test } from "vitest";
import {
  capabilityRouteStateFromSearch,
  decodeCapabilities,
  isMutatingCapability,
} from "./capabilities";

describe("capability catalog provenance", () => {
  test("keeps a stable accessible name for the capability search control", () => {
    expect("Filter capabilities").toMatch(/filter capabilities/i);
  });

  test("counts only execute and breakglass declarations as mutating", () => {
    expect(["read", "simulate", "approve", "execute", "breakglass"]
      .filter(isMutatingCapability)).toEqual(["execute", "breakglass"]);
  });

  test("decodes inert catalog metadata without implying execution eligibility", () => {
    const decoded = decodeCapabilities({
      source: "static-catalog",
      execution_eligibility: false,
      count: 1,
      capabilities: [{
        capability_id: "incident.inspect",
        name: "Inspect incident",
        category: "incident",
        summary: "Inspect bounded incident evidence.",
        side_effect_class: "read",
        default_mode: "shadow",
        required_role: "reader",
        slide_ref: null,
        tags: [],
      }],
    });

    expect(decoded.source).toBe("static-catalog");
    expect(decoded.execution_eligibility).toBe(false);
    expect(decoded.capabilities[0]?.slide_ref).toBeNull();
  });

  test("restores filters and selection from a canonical route", () => {
    expect(capabilityRouteStateFromSearch(new URLSearchParams(
      "q=restart&category=incident&effect=execute&role=owner&capability=incident.restart",
    ))).toEqual({
      query: "restart",
      category: "incident",
      effect: "execute",
      role: "owner",
      selectedId: "incident.restart",
    });
  });

  test("rejects contradictory or ambiguous catalog evidence", () => {
    const item = {
      capability_id: "incident.restart",
      name: "Restart",
      category: "incident",
      summary: "Restart an incident target.",
      side_effect_class: "execute",
      default_mode: "shadow",
      required_role: "owner",
      slide_ref: "workflow-builder",
      tags: [],
    };
    const root = {
      source: "static-catalog",
      execution_eligibility: false,
      count: 1,
      capabilities: [item],
    };
    expect(() => decodeCapabilities({ ...root, count: 2 })).toThrow(/count MUST match/);
    expect(() => decodeCapabilities({ ...root, capabilities: [item, item], count: 2 }))
      .toThrow(/ids MUST be unique/);
    expect(() => decodeCapabilities({ ...root, capabilities: [{ ...item, capability_id: " " }] }))
      .toThrow(/MUST NOT be empty/);
    expect(() => decodeCapabilities({ ...root, capabilities: [{ ...item, slide_ref: 8 }] }))
      .toThrow(/slide_ref MUST be a string/);
  });
});
