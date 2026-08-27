import { describe, expect, it } from "vitest";
import {
  buildForecastLearningViewSnapshot,
  decodeForecastLearning,
} from "./forecast-learning";

describe("decodeForecastLearning", () => {
  it("preserves pipeline miss and debt evidence", () => {
    const value = decodeForecastLearning({
      source: "postgres",
      durable: true,
      episodes: {
        total: 10,
        closed: 9,
        open: 1,
        overdue: 1,
        abstained: 2,
        closure_completeness: 0.9,
      },
      outcomes: [{ label: "false_negative", miss_origin: "pipeline", count: 1 }],
      publication: {
        pending: 2,
        dead_lettered: 1,
        oldest_pending_at: "2026-07-23T15:00:00Z",
      },
      retention: { pending: 1, overdue: 1 },
    });
    expect(value.outcomes[0]?.miss_origin).toBe("pipeline");
    expect(value.publication.dead_lettered).toBe(1);
    expect(value.retention.overdue).toBe(1);

    const snapshot = buildForecastLearningViewSnapshot(value);
    expect(snapshot).toMatchObject({
      routeId: "forecast-learning",
      routeLabel: "Forecast learning",
      facts: expect.arrayContaining([
        expect.objectContaining({ key: "overdue_episodes", value: 1 }),
        expect.objectContaining({ key: "publication_debt", value: 2 }),
      ]),
      records: {
        outcomes: [
          { label: "false_negative", miss_origin: "pipeline", count: 1 },
        ],
      },
    });
  });

  it("rejects unreconciled episode totals", () => {
    expect(() =>
      decodeForecastLearning({
        source: "postgres",
        durable: true,
        episodes: {
          total: 10,
          closed: 9,
          open: 2,
          overdue: 1,
          abstained: 2,
          closure_completeness: 0.9,
        },
        outcomes: [],
        publication: { pending: 0, dead_lettered: 0, oldest_pending_at: null },
        retention: { pending: 0, overdue: 0 },
      }),
    ).toThrow(/totals do not reconcile/);
  });
});
