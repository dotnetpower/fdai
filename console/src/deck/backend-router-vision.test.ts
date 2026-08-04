import { describe, expect, it } from "vitest";

import { parseRouter } from "./backend-normalizers";

describe("vision router health parser", () => {
  it("preserves bounded nested vision candidates", () => {
    const parsed = parseRouter({
      chose: "text-fast",
      candidates: [],
      vision: {
        available: true,
        chose: "vision-fast",
        candidates: [{
          deployment: "vision-fast",
          p50_ms: 420,
          p95_ms: 600,
          samples: 2,
          history_ms: [420, 600],
        }],
      },
    });

    expect(parsed?.vision).toEqual({
      available: true,
      chose: "vision-fast",
      candidates: [{
        deployment: "vision-fast",
        p50_ms: 420,
        p95_ms: 600,
        samples: 2,
        history_ms: [420, 600],
      }],
    });
  });
});
