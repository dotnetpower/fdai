import { describe, expect, test } from "vitest";
import { livingRulesProvenance, measuredTierMix } from "./dashboard.signals";

describe("Tier evidence", () => {
  test("distinguishes a missing tier from a measured zero", () => {
    expect(measuredTierMix({}, "t0")).toBeNull();
    expect(measuredTierMix({ t0: 0 }, "t0")).toBe(0);
  });
});

describe("Living Rules provenance", () => {
  test("preserves synthetic source and as-of metadata", () => {
    expect(livingRulesProvenance({
      synthetic: true,
      source: {
        name: "synthetic-dev-harness",
        kind: "synthetic",
        as_of: "2026-07-15T00:00:00Z",
      },
    })).toEqual({
      kind: "simulated",
      source: "synthetic-dev-harness",
      asOf: "2026-07-15T00:00:00Z",
    });
  });
});

describe("Measured evidence provenance", () => {
  const source = { name: "postgresql:operational_measurements", kind: "measurement", as_of: null } as const;

  test("labels unknown synthetic markers as observed, not measured", () => {
    expect(livingRulesProvenance({
      synthetic: false,
      source,
      provenance: {
        qualification: "observation",
        synthetic_marker: { declared_non_synthetic: 3, unknown: 1 },
      },
    }).kind).toBe("observed");
  });

  test("keeps fully declared non-synthetic evidence measured", () => {
    expect(livingRulesProvenance({
      synthetic: false,
      source,
      provenance: {
        qualification: "observation",
        synthetic_marker: { declared_non_synthetic: 4, unknown: 0 },
      },
    }).kind).toBe("measured");
    expect(livingRulesProvenance({ synthetic: false, source }).kind).toBe("measured");
  });
});
