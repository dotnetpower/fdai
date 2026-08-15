import { describe, expect, it } from "vitest";

import {
  DEFAULT_MINIMUM_REQUEST_INTERVAL_MS,
  DEFAULT_NO_PROGRESS_DEADLINE_MS,
  DEFAULT_PER_QUESTION_DEADLINE_MS,
  DeadlineExceededError,
  MAXIMUM_RUN_BUDGET_MS,
  MINIMUM_RUN_BUDGET_MS,
  RUN_BUDGET_PER_QUESTION_MS,
  TEST_TIMEOUT_SLACK_MS,
  pacingDelayMs,
  resolveAssuranceBudget,
  transportRetryDelayMs,
  withDeadline,
} from "./assurance-budget";

describe("pacingDelayMs", () => {
  it("waits only for the remainder of the minimum spacing", () => {
    expect(pacingDelayMs(15_000, 0)).toBe(15_000);
    expect(pacingDelayMs(15_000, 4_000)).toBe(11_000);
  });

  it("does not add a delay once a turn already exceeded the spacing", () => {
    expect(pacingDelayMs(15_000, 15_000)).toBe(0);
    expect(pacingDelayMs(15_000, 47_600)).toBe(0);
  });

  it("rejects invalid inputs", () => {
    expect(() => pacingDelayMs(-1, 0)).toThrow(/non-negative/);
    expect(() => pacingDelayMs(15_000, Number.NaN)).toThrow(/non-negative/);
  });
});

describe("transportRetryDelayMs", () => {
  it("grows exponentially from the base and stops at the maximum", () => {
    const bounds = { baseMs: 2_000, maxMs: 15_000 };
    expect(transportRetryDelayMs({ attempt: 1, ...bounds })).toBe(2_000);
    expect(transportRetryDelayMs({ attempt: 2, ...bounds })).toBe(4_000);
    expect(transportRetryDelayMs({ attempt: 4, ...bounds })).toBe(15_000);
    expect(transportRetryDelayMs({ attempt: 40, ...bounds })).toBe(15_000);
  });

  it("honors a server hint but clamps it to the bounded maximum", () => {
    const bounds = { baseMs: 2_000, maxMs: 15_000 };
    expect(transportRetryDelayMs({ attempt: 1, ...bounds, retryAfterSeconds: 5 })).toBe(5_000);
    expect(transportRetryDelayMs({ attempt: 1, ...bounds, retryAfterSeconds: 600 })).toBe(15_000);
  });

  it("ignores an unusable server hint instead of failing the run", () => {
    const bounds = { baseMs: 2_000, maxMs: 15_000 };
    expect(transportRetryDelayMs({ attempt: 1, ...bounds, retryAfterSeconds: -5 })).toBe(2_000);
    expect(
      transportRetryDelayMs({ attempt: 1, ...bounds, retryAfterSeconds: Number.NaN }),
    ).toBe(2_000);
  });

  it("rejects invalid attempts and bounds", () => {
    expect(() => transportRetryDelayMs({ attempt: 0, baseMs: 1, maxMs: 2 })).toThrow(/positive/);
    expect(() => transportRetryDelayMs({ attempt: 1, baseMs: 5, maxMs: 1 })).toThrow(/base <= max/);
  });
});

describe("resolveAssuranceBudget", () => {
  it("derives a bounded budget from the question count", () => {
    expect(resolveAssuranceBudget({}, 1).runBudgetMs).toBe(MINIMUM_RUN_BUDGET_MS);
    expect(resolveAssuranceBudget({}, 14).runBudgetMs).toBe(14 * RUN_BUDGET_PER_QUESTION_MS);
    expect(resolveAssuranceBudget({}, 100).runBudgetMs).toBe(MAXIMUM_RUN_BUDGET_MS);
  });

  it("keeps the full cohort envelope far below the previous four-hour timeout", () => {
    expect(resolveAssuranceBudget({}, 100).testTimeoutMs).toBeLessThan(4 * 60 * 60 * 1_000);
  });

  it("applies defaults and derives the harness timeout from the budget", () => {
    const budget = resolveAssuranceBudget({}, 14);
    expect(budget.minimumRequestIntervalMs).toBe(DEFAULT_MINIMUM_REQUEST_INTERVAL_MS);
    expect(budget.perQuestionDeadlineMs).toBe(DEFAULT_PER_QUESTION_DEADLINE_MS);
    expect(budget.noProgressDeadlineMs).toBe(DEFAULT_NO_PROGRESS_DEADLINE_MS);
    expect(budget.testTimeoutMs).toBe(
      budget.runBudgetMs + budget.minimumRequestIntervalMs + TEST_TIMEOUT_SLACK_MS,
    );
  });

  it("keeps the harness timeout above every wait the loop can still grant", () => {
    for (const override of [{}, { FDAI_E2E_ASSURANCE_RUN_BUDGET_MS: "60000" }]) {
      const budget = resolveAssuranceBudget(
        {
          ...override,
          FDAI_E2E_ASSURANCE_PER_QUESTION_DEADLINE_MS: "600000",
          FDAI_E2E_ASSURANCE_NO_PROGRESS_DEADLINE_MS: "600000",
        },
        100,
      );
      // A turn is clamped to the run deadline, so only one granted spacing wait can outlive it.
      expect(budget.testTimeoutMs).toBeGreaterThan(
        budget.runBudgetMs + budget.minimumRequestIntervalMs,
      );
    }
  });

  it("accepts bounded operator overrides", () => {
    const budget = resolveAssuranceBudget(
      {
        FDAI_E2E_ASSURANCE_RUN_BUDGET_MS: "600000",
        FDAI_E2E_ASSURANCE_MIN_REQUEST_INTERVAL_MS: "0",
      },
      100,
    );
    expect(budget.runBudgetMs).toBe(600_000);
    expect(budget.minimumRequestIntervalMs).toBe(0);
  });

  it("rejects malformed, out-of-range, and incoherent overrides", () => {
    expect(() => resolveAssuranceBudget({ FDAI_E2E_ASSURANCE_RUN_BUDGET_MS: "soon" }, 1))
      .toThrow(/non-negative integer/);
    expect(() => resolveAssuranceBudget({ FDAI_E2E_ASSURANCE_RUN_BUDGET_MS: "1" }, 1))
      .toThrow(/within/);
    expect(() => resolveAssuranceBudget({ FDAI_E2E_ASSURANCE_MIN_REQUEST_INTERVAL_MS: "-1" }, 1))
      .toThrow(/non-negative integer/);
    expect(() =>
      resolveAssuranceBudget({ FDAI_E2E_ASSURANCE_NO_PROGRESS_DEADLINE_MS: "30000" }, 1)
    ).toThrow(/no-progress deadline/);
    expect(() => resolveAssuranceBudget({}, 0)).toThrow(/positive integer/);
  });
});

describe("withDeadline", () => {
  it("returns the operation result when it finishes in time", async () => {
    await expect(withDeadline(Promise.resolve("ready"), 1_000, "turn")).resolves.toBe("ready");
  });

  it("rejects a stalled operation with an identifying deadline error", async () => {
    const stalled = new Promise<never>(() => undefined);
    await expect(withDeadline(stalled, 10, "assurance turn en-aggregation-4"))
      .rejects.toBeInstanceOf(DeadlineExceededError);
  });

  it("propagates an operation failure instead of masking it as a deadline breach", async () => {
    await expect(withDeadline(Promise.reject(new Error("stream error")), 1_000, "turn"))
      .rejects.toThrow(/stream error/);
  });

  it("rejects an unusable deadline", async () => {
    await expect(withDeadline(Promise.resolve(1), 0, "turn")).rejects.toThrow(/positive finite/);
  });
});
