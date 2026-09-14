import { describe, expect, test } from "vitest";

import {
  decodeCatalogCoverage,
  decodeResourceTotal,
  decodeRuleEvaluation,
  loadLiveResourceTotal,
} from "./live.coverage";
import { OperatorApiError } from "../api-transport";

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
    expect(decodeResourceTotal({
      schema_version: "1.0.0",
      execution_authority: false,
      mutation_authority: false,
      source_kind: "inventory_snapshot_resource",
      total_count: 840,
    })).toBe(840);
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

  test("retries only typed recorded-state generation transitions", async () => {
    const calls: number[] = [];
    const waits: number[] = [];
    const client = {
      async panel(): Promise<unknown> {
        calls.push(calls.length + 1);
        if (calls.length === 1) {
          throw new OperatorApiError(
            409,
            "inventory_generation_changed",
          );
        }
        return {
          schema_version: "1.0.0",
          execution_authority: false,
          mutation_authority: false,
          source_kind: "inventory_snapshot_resource",
          total_count: 840,
        };
      },
    };

    await expect(loadLiveResourceTotal(
      client,
      () => false,
      async (delay) => {
        waits.push(delay);
      },
    )).resolves.toBe(840);
    expect(calls).toHaveLength(2);
    expect(waits).toEqual([250]);

    const boundedWaits: number[] = [];
    await expect(loadLiveResourceTotal(
      {
        panel: async () => {
          throw new OperatorApiError(
            409,
            "ontology_generation_changed",
          );
        },
      },
      () => false,
      async (delay) => {
        boundedWaits.push(delay);
      },
    )).rejects.toMatchObject({ status: 409 });
    expect(boundedWaits).toEqual([
      250,
      500,
      1_000,
      2_000,
      4_000,
      8_000,
      8_000,
    ]);

    await expect(loadLiveResourceTotal({
      panel: async () => {
        throw new OperatorApiError(503, "projection unavailable");
      },
    })).rejects.toMatchObject({ status: 503 });
  });
});
