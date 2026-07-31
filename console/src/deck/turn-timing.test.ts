import { describe, expect, it } from "vitest";

import { parseTurnTiming } from "./backend";

function timing() {
  return {
    schema_version: 1,
    started_at: "2026-07-31T07:00:00Z",
    completed_at: "2026-07-31T07:00:04Z",
    duration_ms: 4000,
    phases: [
      {
        phase: "evidence",
        status: "degraded",
        started_at: "2026-07-31T07:00:00.500Z",
        completed_at: "2026-07-31T07:00:02.500Z",
        duration_ms: 2000,
      },
      {
        phase: "verification",
        status: "unverified",
        started_at: "2026-07-31T07:00:03Z",
        completed_at: "2026-07-31T07:00:03.500Z",
        duration_ms: 500,
      },
    ],
  };
}

describe("parseTurnTiming", () => {
  it("accepts one bounded terminal timing envelope", () => {
    expect(parseTurnTiming(timing())).toEqual(timing());
  });

  it.each([
    { schema_version: 2 },
    { duration_ms: 3990 },
    { phases: [{ ...timing().phases[0], phase: "unknown" }] },
    { phases: [timing().phases[0], timing().phases[0]] },
    { phases: [{ ...timing().phases[0], completed_at: "2026-07-31T06:59:59Z" }] },
    { phases: [{ ...timing().phases[0], status: "unverified" }] },
    { phases: [{ ...timing().phases[0], started_at: "2026-07-31T06:59:59Z" }] },
    { phases: [timing().phases[1], timing().phases[0]] },
  ])("rejects inconsistent or unbounded timing", (override) => {
    expect(parseTurnTiming({ ...timing(), ...override })).toBeUndefined();
  });
});
