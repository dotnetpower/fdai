import { describe, expect, it } from "vitest";
import type { CostGovernanceProjection } from "../api-cost-governance";
import { summarizeCostGovernance } from "./cost-governance.view-model";

describe("Cost Governance view model", () => {
  it("summarizes disclosed service groups without inventing unavailable values", () => {
    const projection: CostGovernanceProjection = {
      surface: "overview",
      complete: false,
      source_authority: "cost-observation",
      items: [
        {
          kind: "summary",
          group_id: "Compute",
          amount_rounded: "1,200",
          currency: "USD",
          record_count: 3,
          suppressed: false,
        },
        {
          kind: "summary",
          group_id: "Storage",
          amount_band: "100-500",
          currency: "USD",
          record_count: 2,
          suppressed: false,
        },
      ],
      suppressed_count: 0,
    };

    const summary = summarizeCostGovernance(projection);

    expect(summary.knownTotal).toBeNull();
    expect(summary.currency).toBe("USD");
    expect(summary.totalsByCurrency).toEqual({});
    expect(summary.sourceRecordCount).toBe(5);
    expect(summary.rows[0]?.label).toBe("Compute");
    expect(summary.rows[1]?.amount).toBeNull();
    expect(summary.rows[1]?.amountLabel).toBe("100-500");
    expect(summary.largestShare).toBeNull();
  });

  it("does not combine totals across currencies", () => {
    const projection: CostGovernanceProjection = {
      surface: "overview",
      complete: true,
      source_authority: "cost-observation",
      items: [
        { kind: "summary", group_id: "Compute", amount_exact: "10", currency: "USD", record_count: 1 },
        { kind: "summary", group_id: "Compute", amount_exact: "20", currency: "EUR", record_count: 1 },
      ],
      suppressed_count: 0,
    };

    const summary = summarizeCostGovernance(projection);

    expect(summary.knownTotal).toBeNull();
    expect(summary.currency).toBe("");
    expect(summary.totalsByCurrency).toEqual({ USD: 10, EUR: 20 });
  });
});
