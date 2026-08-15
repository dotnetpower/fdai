import { describe, expect, it } from "vitest";
import { outcomeBoundLabel, outcomeDenominatorLabel } from "./incidents.detail-sections";

describe("incident outcome analytics disclosure", () => {
  it("states only the measured count when nothing was excluded", () => {
    expect(outcomeDenominatorLabel({ denominator: 12, matched_total: 12 })).toBe("12");
    expect(outcomeBoundLabel({ denominator: 12, matched_total: 12, truncated: false }))
      .toBe("Complete bounded cohort");
  });

  it("states the measured share and the excluded remainder when the bound applied", () => {
    expect(outcomeDenominatorLabel({ denominator: 500, matched_total: 1557 }))
      .toBe("500 of 1557 matched");
    expect(outcomeBoundLabel({ denominator: 500, matched_total: 1557, truncated: true }))
      .toBe("Bounded at 500 incidents; 1057 matched incidents not measured");
  });

  it("does not invent an excluded count when the server did not observe one", () => {
    expect(outcomeDenominatorLabel({ denominator: 500, matched_total: null })).toBe("500");
    expect(outcomeBoundLabel({ denominator: 500, matched_total: null, truncated: true }))
      .toBe("Bounded at 500 incidents");
  });
});
