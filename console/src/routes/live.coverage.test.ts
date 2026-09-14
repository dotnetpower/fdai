import { describe, expect, test } from "vitest";

import {
  decodeCatalogCoverage,
  decodeResourceTotal,
  decodeRuleEvaluation,
} from "./live.coverage";

describe("Live authoritative coverage boundaries", () => {
  test("keeps catalog inventory distinct from recorded resources", () => {
    expect(decodeCatalogCoverage({
      total: 8_537,
      resource_type_count: 373,
      facets: {
        by_origin: {
          active: 50,
          collected: 8_487,
        },
      },
    })).toEqual({
      total: 8_537,
      active: 50,
      collected: 8_487,
      resourceTypes: 373,
    });
    expect(decodeResourceTotal({ total: 840 })).toBe(840);
  });

  test("does not turn a missing rule projection into zero findings", () => {
    expect(decodeRuleEvaluation({
      evaluated: false,
      counts: {},
    })).toEqual({
      evaluated: false,
      evaluatedRules: 0,
    });
  });

  test("rejects catalog origin totals that imply false coverage", () => {
    expect(() => decodeCatalogCoverage({
      total: 8_537,
      resource_type_count: 373,
      facets: {
        by_origin: {
          active: 50,
          collected: 8_486,
        },
      },
    })).toThrow("do not reconcile");
  });
});
