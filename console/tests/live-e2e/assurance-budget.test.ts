import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  DEFAULT_MINIMUM_REQUEST_INTERVAL_MS,
  DEFAULT_NO_PROGRESS_DEADLINE_MS,
  DEFAULT_PER_QUESTION_DEADLINE_MS,
  DeadlineExceededError,
  MAXIMUM_RUN_BUDGET_MS,
  MINIMUM_RUN_BUDGET_MS,
  PREAMBLE_ACCESS_TIMEOUT_MS,
  PREAMBLE_BOUND_MS,
  PREAMBLE_NAVIGATION_TIMEOUT_MS,
  PREAMBLE_READY_TIMEOUT_MS,
  RUN_BUDGET_PER_QUESTION_MS,
  TEST_TIMEOUT_SLACK_MS,
  attemptEndedByRunBudget,
  classifyExpiredAttempt,
  pacingDelayMs,
  resolveAssuranceBudget,
  resolveQuestionBound,
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

  it("rejects invalid attempts and bounds", () => {
    expect(() => transportRetryDelayMs({ attempt: 0, baseMs: 1, maxMs: 2 })).toThrow(/positive/);
    expect(() => transportRetryDelayMs({ attempt: 1, baseMs: 5, maxMs: 1 })).toThrow(/base <= max/);
  });
});

describe("resolveQuestionBound", () => {
  it("reports the stalled-question guard as binding while the run budget has room", () => {
    const bound = resolveQuestionBound({
      nowMs: 1_000,
      runDeadlineAt: 1_000 + 1_680_000,
      noProgressDeadlineMs: 300_000,
    });

    expect(bound.questionDeadlineAt).toBe(1_000 + 300_000);
    expect(bound.runBudgetIsBinding).toBe(false);
  });

  it("reports the run budget as binding once it expires first", () => {
    const bound = resolveQuestionBound({
      nowMs: 1_000,
      runDeadlineAt: 1_000 + 10_000,
      noProgressDeadlineMs: 300_000,
    });

    expect(bound.questionDeadlineAt).toBe(1_000 + 10_000);
    expect(bound.runBudgetIsBinding).toBe(true);
  });

  it("rejects unusable inputs instead of guessing a bound", () => {
    expect(() =>
      resolveQuestionBound({ nowMs: Number.NaN, runDeadlineAt: 1, noProgressDeadlineMs: 1 })
    ).toThrow(/finite/);
    expect(() =>
      resolveQuestionBound({ nowMs: 0, runDeadlineAt: 1, noProgressDeadlineMs: 0 })
    ).toThrow(/positive/);
  });
});

describe("attemptEndedByRunBudget", () => {
  it("never blames the run budget while the stalled-question guard is binding", () => {
    expect(attemptEndedByRunBudget({
      remainingMs: 128_000,
      perAttemptDeadlineMs: 180_000,
      runBudgetIsBinding: false,
    })).toBe(false);
  });

  it("blames the run budget only when it truncated the attempt", () => {
    expect(attemptEndedByRunBudget({
      remainingMs: 128_000,
      perAttemptDeadlineMs: 180_000,
      runBudgetIsBinding: true,
    })).toBe(true);
    expect(attemptEndedByRunBudget({
      remainingMs: 180_000,
      perAttemptDeadlineMs: 180_000,
      runBudgetIsBinding: true,
    })).toBe(false);
  });
});

describe("classifyExpiredAttempt", () => {
  it("blames the attempt deadline only when the attempt ran its full length", () => {
    expect(classifyExpiredAttempt({
      attemptDeadlineMs: 180_000,
      perAttemptDeadlineMs: 180_000,
      runBudgetIsBinding: false,
    })).toBe("per_attempt_deadline_exceeded");
  });

  it("reports a truncated attempt as a stalled question while the run budget has room", () => {
    expect(classifyExpiredAttempt({
      attemptDeadlineMs: 115_000,
      perAttemptDeadlineMs: 180_000,
      runBudgetIsBinding: false,
    })).toBe("stalled_question");
  });

  it("reports a truncated attempt as budget exhaustion when the run budget is binding", () => {
    expect(classifyExpiredAttempt({
      attemptDeadlineMs: 8,
      perAttemptDeadlineMs: 180_000,
      runBudgetIsBinding: true,
    })).toBe("question_budget_exhausted");
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

  it("cannot restore the four-hour envelope through an override", () => {
    expect(() =>
      resolveAssuranceBudget({ FDAI_E2E_ASSURANCE_RUN_BUDGET_MS: String(14_400_000) }, 100)
    ).toThrow(/MUST be within/);
    expect(
      resolveAssuranceBudget(
        { FDAI_E2E_ASSURANCE_RUN_BUDGET_MS: String(MAXIMUM_RUN_BUDGET_MS) },
        100,
      ).testTimeoutMs,
    ).toBeLessThan(4 * 60 * 60 * 1_000);
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

  it("keeps the harness timeout above the waits the loop can grant at the permitted extremes", () => {
    for (
      const override of [{}, { FDAI_E2E_ASSURANCE_RUN_BUDGET_MS: String(MINIMUM_RUN_BUDGET_MS) }]
    ) {
      const budget = resolveAssuranceBudget(
        {
          ...override,
          FDAI_E2E_ASSURANCE_MIN_REQUEST_INTERVAL_MS: "60000",
          FDAI_E2E_ASSURANCE_PER_QUESTION_DEADLINE_MS: "600000",
          FDAI_E2E_ASSURANCE_NO_PROGRESS_DEADLINE_MS: "600000",
        },
        100,
      );
      // A turn is clamped to the run deadline, so the only work that can outlive the budget is
      // the pre-question spacing plus one granted intra-question wait.
      const tailMs = 2 * budget.minimumRequestIntervalMs + budget.transportRetryMaxMs;
      expect(budget.testTimeoutMs - budget.runBudgetMs).toBeGreaterThan(tailMs);
      // The preamble is charged to the run budget, so the budget must be able to hold it and
      // still leave room for questions.
      expect(budget.runBudgetMs).toBeGreaterThan(PREAMBLE_BOUND_MS);

      // The envelope must stay dominated by the declared budget rather than by harness slack.
      expect(budget.testTimeoutMs - budget.runBudgetMs).toBeLessThan(budget.runBudgetMs);
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

describe("run preamble bound", () => {
  const source = readFileSync(
    new URL("./ontology-query-assurance.spec.ts", import.meta.url),
    "utf8",
  );
  const preamble = source.slice(
    source.indexOf("await restoreBrowserEntraSessionStorage(page);"),
    source.indexOf("let protectedRequestCount = 0;"),
  );

  // Local, non-blocking calls need no wire timeout; every other awaited step must declare one.
  const LOCAL_PREAMBLE_CALLS = ["restoreBrowserEntraSessionStorage"];

  it("bounds every preamble step with a declared timeout", () => {
    expect(preamble).not.toHaveLength(0);
    const awaited = preamble.match(/^\s*(?:(?:const|let|var)\s+[^=]+=\s*)?await [\s\S]*?;$/gm) ??
      [];
    const remote = awaited.filter(
      (statement) => !LOCAL_PREAMBLE_CALLS.some((name) => statement.includes(name)),
    );

    expect(remote.length).toBeGreaterThan(0);
    for (const statement of remote) {
      expect(statement, statement).toMatch(/PREAMBLE_[A-Z_]+_TIMEOUT_MS/);
    }
  });

  it("keeps the declared bound equal to the sum of those steps", () => {
    const declared = {
      PREAMBLE_NAVIGATION_TIMEOUT_MS,
      PREAMBLE_READY_TIMEOUT_MS,
      PREAMBLE_ACCESS_TIMEOUT_MS,
    };
    const used = (preamble.match(/PREAMBLE_[A-Z_]+_TIMEOUT_MS/g) ?? []).reduce(
      (total, name) => total + declared[name as keyof typeof declared],
      0,
    );

    expect(used).toBe(PREAMBLE_BOUND_MS);
  });
});
