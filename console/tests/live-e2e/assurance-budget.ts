/** Bounded pacing, deadline, and resume policy for long-running live assurance runs. */

export const DEFAULT_MINIMUM_REQUEST_INTERVAL_MS = 15_000;
export const DEFAULT_PER_QUESTION_DEADLINE_MS = 180_000;
export const DEFAULT_NO_PROGRESS_DEADLINE_MS = 300_000;
export const DEFAULT_TRANSPORT_RETRY_BASE_MS = 2_000;
export const DEFAULT_TRANSPORT_RETRY_MAX_MS = 15_000;
export const RUN_BUDGET_PER_QUESTION_MS = 120_000;
export const MINIMUM_RUN_BUDGET_MS = 300_000;
export const MAXIMUM_RUN_BUDGET_MS = 5_400_000;
export const TEST_TIMEOUT_SLACK_MS = 120_000;
export const MAX_TRANSPORT_ATTEMPTS = 2;

const BUDGET_BOUNDS = {
  FDAI_E2E_ASSURANCE_MIN_REQUEST_INTERVAL_MS: [0, 60_000],
  FDAI_E2E_ASSURANCE_PER_QUESTION_DEADLINE_MS: [10_000, 600_000],
  FDAI_E2E_ASSURANCE_NO_PROGRESS_DEADLINE_MS: [30_000, 1_800_000],
  FDAI_E2E_ASSURANCE_RUN_BUDGET_MS: [60_000, 14_400_000],
} as const satisfies Record<string, readonly [number, number]>;

type BudgetVariable = keyof typeof BUDGET_BOUNDS;

export interface AssuranceBudget {
  readonly minimumRequestIntervalMs: number;
  readonly perQuestionDeadlineMs: number;
  readonly noProgressDeadlineMs: number;
  readonly runBudgetMs: number;
  readonly transportRetryBaseMs: number;
  readonly transportRetryMaxMs: number;
  readonly testTimeoutMs: number;
}

export interface TransportRetryDelayInput {
  /** One-based count of attempts that already failed. */
  readonly attempt: number;
  readonly baseMs: number;
  readonly maxMs: number;
  /** Server-declared hint. Values above `maxMs` are clamped by the run budget contract. */
  readonly retryAfterSeconds?: number;
}

/** Returns the wait needed to honor a minimum spacing between request starts. */
export function pacingDelayMs(minimumIntervalMs: number, elapsedSinceLastStartMs: number): number {
  if (!Number.isFinite(minimumIntervalMs) || minimumIntervalMs < 0) {
    throw new Error("minimum request interval MUST be a non-negative finite number");
  }
  if (!Number.isFinite(elapsedSinceLastStartMs) || elapsedSinceLastStartMs < 0) {
    throw new Error("elapsed time MUST be a non-negative finite number");
  }
  return Math.max(0, Math.ceil(minimumIntervalMs - elapsedSinceLastStartMs));
}

/** Returns a bounded transport retry delay derived from the observed failure. */
export function transportRetryDelayMs(input: TransportRetryDelayInput): number {
  const { attempt, baseMs, maxMs, retryAfterSeconds } = input;
  if (!Number.isInteger(attempt) || attempt < 1) {
    throw new Error("transport retry attempt MUST be a positive integer");
  }
  if (!Number.isFinite(baseMs) || baseMs < 0 || !Number.isFinite(maxMs) || maxMs < baseMs) {
    throw new Error("transport retry bounds MUST satisfy 0 <= base <= max");
  }
  const exponential = baseMs * 2 ** Math.min(attempt - 1, 16);
  const hintMs = retryAfterSeconds !== undefined &&
      Number.isFinite(retryAfterSeconds) && retryAfterSeconds >= 0
    ? retryAfterSeconds * 1_000
    : 0;
  return Math.min(Math.ceil(Math.max(exponential, hintMs)), maxMs);
}

function boundedOverride(
  environment: Readonly<Record<string, string | undefined>>,
  variable: BudgetVariable,
  fallback: number,
): number {
  const raw = environment[variable];
  if (raw === undefined) return fallback;
  const [minimum, maximum] = BUDGET_BOUNDS[variable];
  if (!/^\d+$/.test(raw.trim())) {
    throw new Error(`${variable} MUST be a non-negative integer number of milliseconds`);
  }
  const value = Number.parseInt(raw.trim(), 10);
  if (!Number.isSafeInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${variable} MUST be within [${minimum}, ${maximum}] milliseconds`);
  }
  return value;
}

/**
 * Derives the bounded run budget for one invocation.
 *
 * The envelope is deliberately not the primary stall protection: the per-question and
 * no-progress deadlines fail a stalled run in minutes, and an exhausted budget stops
 * gracefully with a resumable checkpoint instead of hanging until the harness times out.
 */
export function resolveAssuranceBudget(
  environment: Readonly<Record<string, string | undefined>>,
  questionCount: number,
): AssuranceBudget {
  if (!Number.isInteger(questionCount) || questionCount < 1) {
    throw new Error("assurance question count MUST be a positive integer");
  }
  const derivedBudget = Math.min(
    MAXIMUM_RUN_BUDGET_MS,
    Math.max(MINIMUM_RUN_BUDGET_MS, questionCount * RUN_BUDGET_PER_QUESTION_MS),
  );
  const runBudgetMs = boundedOverride(
    environment,
    "FDAI_E2E_ASSURANCE_RUN_BUDGET_MS",
    derivedBudget,
  );
  const minimumRequestIntervalMs = boundedOverride(
    environment,
    "FDAI_E2E_ASSURANCE_MIN_REQUEST_INTERVAL_MS",
    DEFAULT_MINIMUM_REQUEST_INTERVAL_MS,
  );
  const perQuestionDeadlineMs = boundedOverride(
    environment,
    "FDAI_E2E_ASSURANCE_PER_QUESTION_DEADLINE_MS",
    DEFAULT_PER_QUESTION_DEADLINE_MS,
  );
  const noProgressDeadlineMs = boundedOverride(
    environment,
    "FDAI_E2E_ASSURANCE_NO_PROGRESS_DEADLINE_MS",
    DEFAULT_NO_PROGRESS_DEADLINE_MS,
  );
  if (noProgressDeadlineMs < perQuestionDeadlineMs) {
    throw new Error("no-progress deadline MUST NOT be shorter than the per-question deadline");
  }
  return {
    minimumRequestIntervalMs,
    perQuestionDeadlineMs,
    noProgressDeadlineMs,
    runBudgetMs,
    transportRetryBaseMs: DEFAULT_TRANSPORT_RETRY_BASE_MS,
    transportRetryMaxMs: DEFAULT_TRANSPORT_RETRY_MAX_MS,
    // The loop clamps every turn to the run deadline, so the only work that can outlive the
    // budget is one already-granted spacing wait.
    testTimeoutMs: runBudgetMs + minimumRequestIntervalMs + TEST_TIMEOUT_SLACK_MS,
  };
}

export class DeadlineExceededError extends Error {
  constructor(label: string, deadlineMs: number) {
    super(`${label} exceeded its ${deadlineMs} ms deadline`);
    this.name = "DeadlineExceededError";
  }
}

/**
 * Rejects when an operation outlives its deadline.
 *
 * The underlying operation is not cancellable, so the caller MUST treat a breach as an
 * unhealthy turn rather than assuming the operation stopped.
 */
export async function withDeadline<T>(
  operation: Promise<T>,
  deadlineMs: number,
  label: string,
): Promise<T> {
  if (!Number.isFinite(deadlineMs) || deadlineMs <= 0) {
    throw new Error("deadline MUST be a positive finite number of milliseconds");
  }
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      operation,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new DeadlineExceededError(label, deadlineMs)), deadlineMs);
      }),
    ]);
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
