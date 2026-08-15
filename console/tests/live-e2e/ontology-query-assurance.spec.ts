import { rm, writeFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

import {
  attemptEndedByRunBudget,
  classifyExpiredAttempt,
  DeadlineExceededError,
  MAX_TRANSPORT_ATTEMPTS,
  PREAMBLE_ACCESS_TIMEOUT_MS,
  PREAMBLE_NAVIGATION_TIMEOUT_MS,
  PREAMBLE_READY_TIMEOUT_MS,
  resolveAssuranceBudget,
  resolveQuestionBound,
  transportRetryDelayMs,
  pacingDelayMs,
  withDeadline,
  type AssuranceBudget,
} from "./assurance-budget";
import {
  buildAssuranceCheckpoint,
  pendingQuestions,
  readAssuranceCheckpoint,
  resumableResults,
  writeAssuranceCheckpoint,
} from "./assurance-checkpoint";
import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";
import { canonicalJsonDigest } from "./browser-evidence-provenance";
import { isOntologyAssuranceProductionReady } from "./ontology-query-assurance-readiness";
import {
  assuranceCarriesLiveAuthority,
  assuranceOperationMatchesPlan,
  assuranceCheckpointPath,
  assuranceCohortPassed,
  assuranceEvidenceIdentity,
  assuranceOperations,
  assuranceReceiptSource,
  assuranceRunMode,
  checkpointRetirable,
  checkpointDiscardable,
  evidenceGenerationConsistent,
  isRetainedTurnResult,
  liveAnswerProof,
  resumableWithLiveProof,
  releasableForCoverage,
  retainedForLiveGeneration,
  assuranceTransportRetrySources,
  buildAssuranceRunProvenance,
  assuranceSessionId,
  generateOntologyAssuranceCohort,
  hasRequiredAnswerCoverage,
  isRetryableAssuranceTransportFailure,
  judgeSemanticTurn,
  resolveAssuranceRunId,
  selectOntologyAssuranceQuestions,
  type AssuranceRunConfiguration,
  type AssuranceQuestion,
  type AssurancePlanCapability,
  type RetainedTransportAttempt,
  type RetainedTurnResult,
} from "./ontology-query-assurance";

const COHORT_SEED = 0x0fda1;
const DEFAULT_CHECKPOINT_DIRECTORY = "../.fdai/live-validation";
const AUTHENTICATED_EXTERNAL_STACK = Boolean(
  process.env.FDAI_E2E_BASE_URL && process.env.FDAI_E2E_STORAGE_STATE,
);

interface BrowserTurnResult {
  readonly source: string;
  readonly semantic_receipt: unknown;
  readonly verification: unknown;
  readonly plan_capabilities: readonly AssurancePlanCapability[];
}

async function runBrowserTurn(
  page: Page,
  question: AssuranceQuestion,
  runId: string,
): Promise<BrowserTurnResult> {
  return page.evaluate(async ({ prompt, sessionId }) => {
    const { askBackendStream } = await import("/src/deck/backend-stream.ts");
    const reply = await askBackendStream(prompt, null, [], {
      onToken: () => undefined,
      sessionId,
    });
    return {
      source: reply.source,
      semantic_receipt: reply.semanticReceipt ?? null,
      verification: reply.verification ?? null,
      plan_capabilities: Array.from(new Set((reply.intentGraph?.goals ?? []).flatMap((goal) => {
        if (goal.intent === "function" && typeof goal.arguments["function_name"] === "string") {
          return [`function:${goal.arguments["function_name"]}`];
        }
        if (goal.intent === "object_set") {
          const definition = goal.arguments["definition"];
          const predicates = typeof definition === "object" && definition !== null &&
              !Array.isArray(definition)
            ? (definition as Record<string, unknown>)["predicates"]
            : undefined;
          return Array.isArray(predicates) && predicates.length > 0
            ? ["object_set", "object_set:filtered"]
            : ["object_set"];
        }
        return [goal.intent];
      }))).filter((capability): capability is AssurancePlanCapability => [
        "aggregate",
        "evidence_join",
        "function:query.incident_evidence",
        "function:query.manifest",
        "function:query.ontology_relationships",
        "metric_series",
        "object_set",
        "object_set:filtered",
        "topology_at",
        "topology_diff",
      ].includes(capability)),
    };
  }, {
    prompt: question.prompt,
    sessionId: assuranceSessionId(runId, question.question_id),
  });
}

function increment(counts: Record<string, number>, key: string | undefined): void {
  counts[key ?? "none"] = (counts[key ?? "none"] ?? 0) + 1;
}

/**
 * Destroys the execution context that still holds an abandoned turn.
 *
 * Reports failure instead of throwing, so a sick stack still produces a governed artifact.
 */
async function resetTurnContext(page: Page): Promise<boolean> {
  try {
    await page.reload({
      waitUntil: "domcontentloaded",
      timeout: PREAMBLE_NAVIGATION_TIMEOUT_MS,
    });
    return true;
  } catch {
    return false;
  }
}

function claimsExecutionAuthority(raw: unknown): boolean {
  return typeof raw === "object" && raw !== null && !Array.isArray(raw) &&
    (raw as Record<string, unknown>).execution_authority === true;
}

function retainTransportAttempt(
  attempt: number,
  result: BrowserTurnResult,
): RetainedTransportAttempt {
  if (result.semantic_receipt != null) {
    return { attempt, outcome: "semantic_terminal" };
  }
  if (isRetryableAssuranceTransportFailure(result.source, result.semantic_receipt)) {
    return {
      attempt,
      outcome: "retryable_transport_failure",
      source: result.source,
    };
  }
  return { attempt, outcome: "non_retryable_receipt_missing" };
}

/** Rejects a checkpoint whose retained results lost any field the pass criteria read. */
interface QuestionOutcome {
  readonly result: BrowserTurnResult | null;
  readonly transportAttempts: readonly RetainedTransportAttempt[];
  readonly requestCount: number;
  /** `null` when no request started, so the caller does not charge spacing for a turn never made. */
  readonly lastRequestStartedAt: number | null;
  /** True when the run budget, not the stack, ended the question. */
  readonly budgetExhausted: boolean;
  /** True when an abandoned turn could not be cleared from the page. */
  readonly contextResetFailed: boolean;
}

async function resolveQuestion(
  page: Page,
  question: AssuranceQuestion,
  runId: string,
  budget: AssuranceBudget,
  runDeadlineAt: number,
): Promise<QuestionOutcome> {
  const transportAttempts: RetainedTransportAttempt[] = [];
  // Two independent bounds end a question. Only the run budget may stop the cohort; a stalled
  // question is a real failure that must be recorded and must not abort the remaining questions.
  const { questionDeadlineAt, runBudgetIsBinding } = resolveQuestionBound({
    nowMs: Date.now(),
    runDeadlineAt,
    noProgressDeadlineMs: budget.noProgressDeadlineMs,
  });
  let result: BrowserTurnResult | null = null;
  let requestCount = 0;
  let lastRequestStartedAt: number | null = null;
  for (let attempt = 1; attempt <= MAX_TRANSPORT_ATTEMPTS; attempt += 1) {
    if (attempt > 1 && lastRequestStartedAt !== null) {
      const retryDelayMs = transportRetryDelayMs({
        attempt: attempt - 1,
        baseMs: budget.transportRetryBaseMs,
        maxMs: budget.transportRetryMaxMs,
      });
      const spacingMs = pacingDelayMs(
        budget.minimumRequestIntervalMs,
        Date.now() - lastRequestStartedAt,
      );
      await page.waitForTimeout(Math.max(retryDelayMs, spacingMs));
    }
    const remainingMs = questionDeadlineAt - Date.now();
    if (remainingMs <= 0) {
      transportAttempts.push({
        attempt,
        outcome: runBudgetIsBinding ? "question_budget_exhausted" : "stalled_question",
      });
      return {
        result: null,
        transportAttempts,
        requestCount,
        lastRequestStartedAt,
        budgetExhausted: runBudgetIsBinding,
        contextResetFailed: false,
      };
    }
    const attemptDeadlineMs = Math.min(budget.perQuestionDeadlineMs, remainingMs);
    const attemptBoundedByBudget = attemptEndedByRunBudget({
      remainingMs,
      perAttemptDeadlineMs: budget.perQuestionDeadlineMs,
      runBudgetIsBinding,
    });
    lastRequestStartedAt = Date.now();
    requestCount += 1;
    try {
      result = await withDeadline(
        runBrowserTurn(page, question, runId),
        attemptDeadlineMs,
        `assurance turn ${question.question_id}`,
      );
    } catch (error) {
      const deadlineExceeded = error instanceof DeadlineExceededError;
      const outcome = deadlineExceeded
        ? classifyExpiredAttempt({
          attemptDeadlineMs,
          perAttemptDeadlineMs: budget.perQuestionDeadlineMs,
          runBudgetIsBinding,
        })
        : "turn_error";
      // The abandoned turn keeps consuming an authenticated stream, so the execution context is
      // reset before the next question instead of accumulating orphaned work on the same page. A
      // budget-truncated attempt ends the run anyway, so it is not worth a reload.
      const contextResetFailed = deadlineExceeded && !attemptBoundedByBudget &&
        !await resetTurnContext(page);
      transportAttempts.push({
        attempt,
        outcome,
        // A permanent page-side fault must stay distinguishable from a transient blip, and a page
        // that could not be reset must not be mistaken for a clean deadline breach.
        ...(contextResetFailed
          ? { source: "context_reset_failed" }
          : outcome === "turn_error"
          ? { source: error instanceof Error ? error.name : "unknown" }
          : {}),
      });
      // A transient evaluate failure is not terminal evidence, so it may use a remaining attempt
      // instead of being persisted as a permanent failure.
      if (!contextResetFailed && outcome === "turn_error" && attempt < MAX_TRANSPORT_ATTEMPTS) {
        continue;
      }
      return {
        result: null,
        transportAttempts,
        requestCount,
        lastRequestStartedAt,
        budgetExhausted: deadlineExceeded && attemptBoundedByBudget,
        contextResetFailed,
      };
    }
    transportAttempts.push(retainTransportAttempt(attempt, result));
    if (!isRetryableAssuranceTransportFailure(result.source, result.semantic_receipt)) break;
  }
  return {
    result,
    transportAttempts,
    requestCount,
    lastRequestStartedAt,
    budgetExhausted: false,
    contextResetFailed: false,
  };
}

test("authenticated Console completes the seeded bilingual ontology assurance cohort", async ({ page }, testInfo) => {
  test.skip(
    !AUTHENTICATED_EXTERNAL_STACK,
    "requires an external Console and Browser Entra storage state",
  );
  const startedAt = new Date().toISOString();
  const runId = resolveAssuranceRunId(process.env.FDAI_E2E_ASSURANCE_RUN_ID);
  const completeCohort = generateOntologyAssuranceCohort(COHORT_SEED);
  const questions = selectOntologyAssuranceQuestions(
    completeCohort,
    process.env.FDAI_E2E_ASSURANCE_QUESTION_IDS,
  );
  const runScope = questions.length === completeCohort.length
    ? "full_cohort"
    : "focused_probe";
  const budget = resolveAssuranceBudget(process.env, questions.length);
  test.setTimeout(budget.testTimeoutMs);
  const questionIds = questions.map((question) => question.question_id);
  const runConfiguration: AssuranceRunConfiguration = {
    schema_version: "1.4.0",
    run_id: runId,
    seed: COHORT_SEED,
    minimum_request_interval_ms: budget.minimumRequestIntervalMs,
    per_question_deadline_ms: budget.perQuestionDeadlineMs,
    no_progress_deadline_ms: budget.noProgressDeadlineMs,
    run_budget_ms: budget.runBudgetMs,
    authentication: "browser_entra",
    transport_retry_policy: {
      max_attempts: MAX_TRANSPORT_ATTEMPTS,
      base_retry_delay_ms: budget.transportRetryBaseMs,
      max_retry_delay_ms: budget.transportRetryMaxMs,
      retryable_sources: assuranceTransportRetrySources(),
    },
    question_ids: questionIds,
  };
  const provenance = buildAssuranceRunProvenance(
    process.env.FDAI_E2E_SOURCE_REVISION,
    process.env.FDAI_E2E_WORKSPACE_PATCH_SHA256,
    runConfiguration,
  );
  const checkpointBinding = {
    source_revision: provenance.source_revision,
    target_origin: new URL(process.env.FDAI_E2E_BASE_URL!).origin,
    evidence_identity_digest: canonicalJsonDigest(assuranceEvidenceIdentity(runConfiguration)),
    workspace_patch_digest: provenance.workspace_patch_digest,
  };
  const checkpointFile = assuranceCheckpointPath({
    configured: process.env.FDAI_E2E_ASSURANCE_CHECKPOINT,
    directory: DEFAULT_CHECKPOINT_DIRECTORY,
    runScope,
    bindingDigest: canonicalJsonDigest(checkpointBinding),
  });
  const restored = checkpointFile === null ? [] : resumableResults(
    await readAssuranceCheckpoint<RetainedTurnResult>(checkpointFile, isRetainedTurnResult),
    { binding: checkpointBinding, questionIds },
  );
  // Only a verified turn is resumable. Restoring a failed turn would make the failure permanent
  // for this revision, because a resumed question is never re-attempted.
  const resumed = resumableWithLiveProof(restored.filter((result) => result.passed), questions);
  const retained: RetainedTurnResult[] = [...resumed];
  const outstanding = pendingQuestions(questions, retained);
  // A resume that silently restored nothing is otherwise only visible in the final artifact, so
  // the slowest path starts with the one line that distinguishes a resume from a fresh cohort.
  process.stdout.write(
    `assurance-resume checkpoint=${checkpointFile === null ? "disabled" : "enabled"} ` +
      `stored=${restored.length} resumed=${resumed.length} outstanding=${outstanding.length}/` +
      `${questions.length}\n`,
  );

  // The budget is anchored before the preamble so browser restore and navigation are charged to
  // it; otherwise the harness timeout could fire before the run stops itself.
  const runDeadlineAt = Date.now() + budget.runBudgetMs;
  await restoreBrowserEntraSessionStorage(page);
  // Playwright disables navigation and action timeouts by default, so each preamble step declares
  // its own bound; otherwise a hung navigation would reach the opaque harness timeout.
  await page.goto("/architecture", {
    waitUntil: "domcontentloaded",
    timeout: PREAMBLE_NAVIGATION_TIMEOUT_MS,
  });
  await expect(page.locator(".shell")).toBeVisible({ timeout: PREAMBLE_READY_TIMEOUT_MS });
  await expect(page.locator("main [aria-busy='true']"))
    .toHaveCount(0, { timeout: PREAMBLE_READY_TIMEOUT_MS });
  await expect(page.getByText("FDAI could not verify your access."))
    .toHaveCount(0, { timeout: PREAMBLE_ACCESS_TIMEOUT_MS });

  let protectedRequestCount = 0;
  let stopReason: string | null = null;
  let stoppedOn: {
    readonly question_id: string;
    readonly transport_attempts: readonly RetainedTransportAttempt[];
  } | null = null;
  let lastRequestStartedAt = Date.now() - budget.minimumRequestIntervalMs;
  for (const question of outstanding) {
    if (Date.now() >= runDeadlineAt) {
      stopReason = "run_budget_exhausted";
      stoppedOn = { question_id: question.question_id, transport_attempts: [] };
      break;
    }
    const spacingMs = pacingDelayMs(
      budget.minimumRequestIntervalMs,
      Date.now() - lastRequestStartedAt,
    );
    // The guard covers pacing, the intra-question retry wait, and the turn itself, so a page fault
    // anywhere in the question still reaches the artifact instead of escaping the test body. A
    // zero-length wait doubles as a liveness probe when pacing is disabled.
    let outcome: QuestionOutcome;
    try {
      await page.waitForTimeout(spacingMs);
      outcome = await resolveQuestion(page, question, runId, budget, runDeadlineAt);
    } catch {
      stopReason = "page_unavailable";
      stoppedOn = { question_id: question.question_id, transport_attempts: [] };
      break;
    }
    protectedRequestCount += outcome.requestCount;
    if (outcome.lastRequestStartedAt !== null) lastRequestStartedAt = outcome.lastRequestStartedAt;
    if (outcome.contextResetFailed) {
      // The page still holds an abandoned authenticated stream, so no later turn taken on it is
      // trustworthy evidence.
      stopReason = "context_reset_failed";
      stoppedOn = {
        question_id: question.question_id,
        transport_attempts: outcome.transportAttempts,
      };
      break;
    }
    if (outcome.budgetExhausted) {
      // Leave the question outstanding so a resumed run retries it instead of inheriting a
      // permanent failure that only the run budget caused, but keep the diagnosis auditable.
      stopReason = "run_budget_exhausted";
      stoppedOn = {
        question_id: question.question_id,
        transport_attempts: outcome.transportAttempts,
      };
      break;
    }
    {
      const transportAttempts = outcome.transportAttempts;
      const terminalOutcome = transportAttempts.at(-1)?.outcome;
      // A turn that ended in a transport outcome is a transport failure, not a malformed
      // receipt, so the artifact must not mislabel the stack.
      const transportTerminated = terminalOutcome === "retryable_transport_failure" ||
        terminalOutcome === "non_retryable_receipt_missing";
      const judgment = outcome.result === null || transportTerminated
        ? { passed: false, failure_reason: terminalOutcome ?? "turn_error" }
        : judgeSemanticTurn(outcome.result.semantic_receipt, outcome.result.verification);
      const receipt = "receipt" in judgment ? judgment.receipt : undefined;
      const planCapabilities = outcome.result?.plan_capabilities ?? [];
      const planCapabilityMatch = receipt?.disposition !== "answered" ||
        assuranceOperationMatchesPlan(question.operation, planCapabilities);
      retained.push({
        question_id: question.question_id,
        produced_by_run_id: runId,
        locale: question.locale,
        operation: question.operation,
        attempt_count: transportAttempts.length,
        transport_attempts: transportAttempts,
        passed: judgment.passed && planCapabilityMatch,
        unauthorized_execution_claim: claimsExecutionAuthority(outcome.result?.semantic_receipt),
        plan_capabilities: planCapabilities,
        plan_capability_match: planCapabilityMatch,
        ...(judgment.failure_reason
          ? { failure_reason: judgment.failure_reason }
          : !planCapabilityMatch
          ? { failure_reason: "semantic_plan_operation_mismatch" }
          : {}),
        ...(receipt ? {
          projection_id: receipt.projection_id,
          request_id: receipt.request_id,
          disposition: receipt.disposition,
          reason_code: receipt.reason_code,
          ...(receipt.semantic_route ? { semantic_route: receipt.semantic_route } : {}),
          ...(receipt.unavailable_reason ? { unavailable_reason: receipt.unavailable_reason } : {}),
          ...(receipt.ontology_release_digest ? {
            ontology_release_digest: receipt.ontology_release_digest,
          } : {}),
          ...(receipt.principal_manifest_digest ? {
            principal_manifest_digest: receipt.principal_manifest_digest,
          } : {}),
          ...(receipt.plan_digest ? { plan_digest: receipt.plan_digest } : {}),
          ...(receipt.execution_receipt_digest ? {
            execution_receipt_digest: receipt.execution_receipt_digest,
          } : {}),
        } : {}),
        ...("verification" in judgment && judgment.verification ? {
          checks_completed: judgment.verification.checks_completed,
          checks_total: judgment.verification.checks_total,
          evidence_ref_count: judgment.verification.evidence_refs.length,
        } : {}),
      });
    }
    if (checkpointFile !== null) {
      const written = await writeAssuranceCheckpoint(
        checkpointFile,
        buildAssuranceCheckpoint(checkpointBinding, questionIds, retained),
      ).then(() => true, () => false);
      if (!written) {
        // Continuing without a durable checkpoint would silently discard the resume guarantee.
        stopReason = "checkpoint_write_failed";
        stoppedOn = {
          question_id: question.question_id,
          transport_attempts: outcome.transportAttempts,
        };
        break;
      }
    }
    const latest = retained.at(-1)!;
    process.stdout.write(
      `assurance-progress question=${latest.question_id} completed=${retained.length}/` +
        `${questions.length} passed=${latest.passed} disposition=${latest.disposition ?? "none"} ` +
        `remaining_budget_ms=${Math.max(0, runDeadlineAt - Date.now())}\n`,
    );
  }
  const cohortIndex = new Map(questionIds.map((id, index) => [id, index]));
  retained.sort((left, right) =>
    (cohortIndex.get(left.question_id) ?? 0) - (cohortIndex.get(right.question_id) ?? 0)
  );

  const requestIds = retained.flatMap((result) => result.request_id ? [result.request_id] : []);
  const projectionIds = retained.flatMap((result) => result.projection_id ? [result.projection_id] : []);
  const duplicateRequestIds = requestIds.length - new Set(requestIds).size;
  const duplicateProjectionIds = projectionIds.length - new Set(projectionIds).size;
  const failures = retained.filter((result) => !result.passed);
  const retriedQuestionCount = retained.filter((result) => result.attempt_count > 1).length;
  const transportRetryCount = retained.reduce(
    (total, result) =>
      total +
      result.transport_attempts.filter(
        (attempt) => attempt.outcome === "retryable_transport_failure",
      ).length,
    0,
  );
  const exhaustedTransportRetryCount = retained.filter((result) =>
    result.transport_attempts.at(-1)?.outcome === "retryable_transport_failure"
  ).length;
  const localeCounts: Record<string, number> = {};
  const operationCounts: Record<string, number> = {};
  const dispositionCounts: Record<string, number> = {};
  const routeCounts: Record<string, number> = {};
  const unavailableReasonCounts: Record<string, number> = {};
  for (const result of retained) {
    increment(localeCounts, result.locale);
    increment(operationCounts, result.operation);
    increment(dispositionCounts, result.disposition);
    increment(routeCounts, result.semantic_route);
    increment(unavailableReasonCounts, result.unavailable_reason);
  }

  const unsupportedOperationalClaimCount = retained.filter(
    (result) => result.failure_reason === "unsupported_or_failed_claim",
  ).length;
  const unauthorizedExecutionCount = retained.filter(
    (result) => result.unauthorized_execution_claim,
  ).length;
  const planCapabilityMismatchCount = retained.filter(
    (result) => !result.plan_capability_match,
  ).length;
  const deadlineExceededCount = retained.filter((result) =>
    result.transport_attempts.some(
      (attempt) => attempt.outcome === "per_attempt_deadline_exceeded",
    )
  ).length;
  const stalledQuestionCount = retained.filter((result) =>
    result.transport_attempts.some((attempt) => attempt.outcome === "stalled_question")
  ).length;
  const resumedQuestionIds = new Set(resumed.map((result) => result.question_id));
  const liveResults = retained.filter((result) => !resumedQuestionIds.has(result.question_id));
  const liveQuestionCount = liveResults.length;
  const producedByRunIdCounts: Record<string, number> = {};
  for (const result of retained) increment(producedByRunIdCounts, result.produced_by_run_id);
  const answeredResults = retained.filter((result) => result.disposition === "answered");
  const answeredEvidenceCount = answeredResults.filter((result) =>
    result.passed && result.plan_capability_match &&
    result.evidence_ref_count !== undefined && result.evidence_ref_count > 0 &&
    result.checks_total !== undefined && result.checks_total > 0 &&
    result.checks_completed === result.checks_total
  ).length;
  const answeredLocaleCounts: Record<string, number> = {};
  for (const result of answeredResults) increment(answeredLocaleCounts, result.locale);
  const answeredLocaleCoverageComplete = answeredLocaleCounts.en !== undefined &&
    answeredLocaleCounts.en > 0 && answeredLocaleCounts.ko !== undefined &&
    answeredLocaleCounts.ko > 0;
  const authoritativeOutcomeCount = retained.filter((result) =>
    result.passed && result.disposition !== undefined &&
    (result.disposition !== "answered" || result.evidence_ref_count !== undefined)
  ).length;
  const localeCoverageComplete = runScope === "full_cohort" &&
    localeCounts.en === 50 && localeCounts.ko === 50;
  const operationCoverageComplete = runScope === "full_cohort" && assuranceOperations().every(
    (operation) => operationCounts[operation] === 10,
  );
  const requiredAnswerCoverageComplete = runScope === "full_cohort" &&
    hasRequiredAnswerCoverage(retained.map((result) => ({
      operation: result.operation,
      locale: result.locale,
      ...(result.disposition === undefined ? {} : { disposition: result.disposition }),
      complete_verified_evidence:
        result.passed && result.plan_capability_match &&
        result.evidence_ref_count !== undefined && result.evidence_ref_count > 0 &&
        result.checks_total !== undefined && result.checks_total > 0 &&
        result.checks_completed === result.checks_total,
    })));
  // A resumed run republishes earlier turns only when this run proved the current stack with a
  // governed live answer that names the same ontology release and principal manifest.
  const runMode = assuranceRunMode({ liveProven: liveAnswerProof(liveResults), stopReason });
  const generationConsistent = evidenceGenerationConsistent({ resumed, live: liveResults });
  const passed = assuranceCohortPassed({
    stopReason,
    retainedCount: retained.length,
    cohortSize: questions.length,
    liveAuthority: assuranceCarriesLiveAuthority(runMode),
    generationConsistent,
    failureCount: failures.length,
    exhaustedTransportRetryCount,
    duplicateRequestIdCount: duplicateRequestIds,
    duplicateProjectionIdCount: duplicateProjectionIds,
    unsupportedOperationalClaimCount,
    unauthorizedExecutionCount,
    answeredCount: answeredResults.length,
    answeredWithCompleteEvidenceCount: answeredEvidenceCount,
    authoritativeOutcomeCount,
  });
  const productionReady = assuranceCarriesLiveAuthority(runMode) &&
    isOntologyAssuranceProductionReady({
      passed,
      runScope,
      localeCoverageComplete,
      operationCoverageComplete,
      answeredCount: answeredResults.length,
      answeredWithCompleteEvidenceCount: answeredEvidenceCount,
      answeredLocaleCoverageComplete,
      requiredAnswerCoverageComplete,
    });
  const artifact = {
    schema_version: "1.3.0",
    evidence_type: "authenticated_bilingual_ontology_query_assurance",
    receipt_source: assuranceReceiptSource({
      runMode,
      liveQuestionCount,
      resumedCount: resumed.length,
    }),
    run_scope: runScope,
    run_mode: runMode,
    ...provenance,
    evidence_identity_digest: checkpointBinding.evidence_identity_digest,
    target_origin: checkpointBinding.target_origin,
    run_configuration: runConfiguration,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    authentication: "browser_entra",
    authentication_attestation: {
      storage_state_restored: true,
      live_protected_request_count: protectedRequestCount,
    },
    run_budget: {
      run_budget_ms: budget.runBudgetMs,
      per_question_deadline_ms: budget.perQuestionDeadlineMs,
      no_progress_deadline_ms: budget.noProgressDeadlineMs,
      // The configuration keys mirror the operator environment variables; these state what each
      // value actually bounds. Attempt outcomes use the accurate names.
      deadline_semantics: {
        per_question_deadline_ms:
          "one attempt; a breach reports per_attempt_deadline_exceeded and ends the question",
        no_progress_deadline_ms:
          "one whole question including retries; a breach reports stalled_question",
        retry_policy:
          "only a retryable transport source or a transient turn error uses a remaining attempt",
      },
      minimum_request_interval_ms: budget.minimumRequestIntervalMs,
      stop_reason: stopReason,
      ...(stoppedOn ? { stopped_on: stoppedOn } : {}),
    },
    passed,
    production_ready: productionReady,
    summary: {
      question_count: retained.length,
      resumed_question_count: resumed.length,
      produced_by_run_id_counts: producedByRunIdCounts,
      live_question_count: liveQuestionCount,
      per_attempt_deadline_exceeded_count: deadlineExceededCount,
      stalled_question_count: stalledQuestionCount,
      evidence_generation_consistent: generationConsistent,
      passed_count: retained.length - failures.length,
      failed_count: failures.length,
      retried_question_count: retriedQuestionCount,
      transport_retry_count: transportRetryCount,
      exhausted_transport_retry_count: exhaustedTransportRetryCount,
      duplicate_request_id_count: duplicateRequestIds,
      duplicate_projection_id_count: duplicateProjectionIds,
      unsupported_operational_claim_count: unsupportedOperationalClaimCount,
      unauthorized_execution_count: unauthorizedExecutionCount,
      plan_capability_mismatch_count: planCapabilityMismatchCount,
      answered_count: answeredResults.length,
      answered_with_complete_evidence_count: answeredEvidenceCount,
      answered_locale_coverage_complete: answeredLocaleCoverageComplete,
      answered_locale_counts: answeredLocaleCounts,
      authoritative_outcome_count: authoritativeOutcomeCount,
      locale_coverage_complete: localeCoverageComplete,
      operation_coverage_complete: operationCoverageComplete,
      required_answer_coverage_complete: requiredAnswerCoverageComplete,
      locale_counts: localeCounts,
      operation_counts: operationCounts,
      disposition_counts: dispositionCounts,
      semantic_route_counts: routeCounts,
      unavailable_reason_counts: unavailableReasonCounts,
    },
    results: retained,
  };
  const artifactPath = testInfo.outputPath("ontology-query-randomized-assurance.json");
  await writeFile(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`, "utf8");
  await testInfo.attach("ontology-query-randomized-assurance", {
    path: artifactPath,
    contentType: "application/json",
  });

  // Retire a complete cohort only after it published a passing result, so one flaky turn cannot
  // discard every verified turn, and never leave the checkpoint in a state that republishes the
  // same blocking outcome forever.
  const releaseSatisfied = runScope !== "full_cohort" || productionReady;
  const retirable = checkpointRetirable({
    passed,
    releaseSatisfied,
    stopReason,
    retainedCount: retained.length,
    cohortSize: questions.length,
  });
  if (checkpointFile !== null && checkpointDiscardable({ retirable, generationConsistent, stopReason })) {
    // A release that rotated mid-run does not invalidate the turns taken under the newest
    // generation, so those are kept and the next run resumes them. When the live turns disclosed
    // no generation at all there is nothing to prune, so the survivors equal the retained set.
    const survivors = generationConsistent ? [] : retainedForLiveGeneration(retained, liveResults);
    if (survivors.length > 0 && survivors.length < retained.length) {
      await writeAssuranceCheckpoint(
        checkpointFile,
        buildAssuranceCheckpoint(checkpointBinding, questionIds, survivors),
      );
    } else if (survivors.length === 0) {
      await rm(checkpointFile, { force: true });
    }
  } else if (
    checkpointFile !== null && passed && !releaseSatisfied && stopReason === null
  ) {
    // Every turn passed but an answer-required operation only refused, so releasing those turns is
    // the only way a later run can satisfy the release criteria instead of replaying the block.
    await writeAssuranceCheckpoint(
      checkpointFile,
      buildAssuranceCheckpoint(checkpointBinding, questionIds, releasableForCoverage(retained)),
    );
  }

  expect(stopReason, `assurance run stopped early: ${stopReason}`).toBeNull();
  expect(runMode, "a governed run MUST prove the live stack with an answered turn")
    .toBe("live");
  expect(generationConsistent, "retained answers MUST describe one governed generation")
    .toBe(true);
  expect(retained).toHaveLength(questions.length);
  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
  expect(duplicateRequestIds).toBe(0);
  expect(duplicateProjectionIds).toBe(0);
  if (runScope === "full_cohort") {
    expect(localeCounts).toEqual({ en: 50, ko: 50 });
    expect(productionReady, JSON.stringify(artifact.summary, null, 2)).toBe(true);
  } else {
    expect(productionReady).toBe(false);
  }
});
