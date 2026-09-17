import { describe, expect, it } from "vitest";
import { forecastActivityRows } from "./forecast-activity";
import { decodeForecastLearning } from "./forecast-learning";

describe("recorded forecast activity", () => {
  it("does not hide open episodes just because no terminal outcomes exist", () => {
    const data = decodeForecastLearning({
      source: "postgres",
      durable: true,
      episodes: { total: 12, closed: 2, open: 10, overdue: 0, abstained: 3, closure_completeness: null },
      outcomes: [],
      publication: { pending: 0, dead_lettered: 0, oldest_pending_at: null },
      retention: { pending: 4, overdue: 1 },
    });
    expect(forecastActivityRows(data).map(({ key, value }) => ({ key, value }))).toEqual([
      { key: "total", value: 12 },
      { key: "open", value: 10 },
      { key: "closed", value: 2 },
      { key: "abstained", value: 3 },
      { key: "pendingRetention", value: 4 },
      { key: "oldestPending", value: "Not measured" },
    ]);
  });
});
