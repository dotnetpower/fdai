import { writeFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";
import { isOntologyAssuranceProductionReady } from "./ontology-query-assurance-readiness";
import {
  assuranceOperations,
  assuranceTransportRetrySources,
  buildAssuranceRunProvenance,
  generateOntologyAssuranceCohort,
  isRetryableAssuranceTransportFailure,
  judgeSemanticTurn,
  selectOntologyAssuranceQuestions,
  type AssuranceRunConfiguration,
  type AssuranceQuestion,
} from "./ontology-query-assurance";

const COHORT_SEED = 0x0fda1;
const BATCH_SIZE = 1;
const REQUEST_INTERVAL_MS = 15_000;
const MAX_TRANSPORT_ATTEMPTS = 2;
const TRANSPORT_RETRY_DELAY_MS = 60_000;
const TEST_TIMEOUT_MS = 4 * 60 * 60 * 1_000;
const AUTHENTICATED_EXTERNAL_STACK = Boolean(
  process.env.FDAI_E2E_BASE_URL && process.env.FDAI_E2E_STORAGE_STATE,
);

interface BrowserTurnResult {
  readonly source: string;
  readonly semantic_receipt: unknown;
  readonly verification: unknown;
}

interface RetainedTransportAttempt {
  readonly attempt: number;
  readonly outcome:
    | "semantic_terminal"
    | "retryable_transport_failure"
    | "non_retryable_receipt_missing";
  readonly source?: string;
}

interface RetainedTurnResult {
  readonly question_id: string;
  readonly locale: AssuranceQuestion["locale"];
  readonly operation: AssuranceQuestion["operation"];
  readonly attempt_count: number;
  readonly transport_attempts: readonly RetainedTransportAttempt[];
  readonly passed: boolean;
  readonly unauthorized_execution_claim: boolean;
  readonly failure_reason?: string;
  readonly projection_id?: string;
  readonly request_id?: string;
  readonly disposition?: string;
  readonly reason_code?: string;
  readonly semantic_route?: string;
  readonly unavailable_reason?: string;
  readonly ontology_release_digest?: string;
  readonly principal_manifest_digest?: string;
  readonly plan_digest?: string;
  readonly execution_receipt_digest?: string;
  readonly checks_completed?: number;
  readonly checks_total?: number;
  readonly evidence_ref_count?: number;
}

async function runBrowserBatch(
  page: Page,
  questions: readonly AssuranceQuestion[],
): Promise<readonly BrowserTurnResult[]> {
  return page.evaluate(async (batch) => {
    const { askBackendStream } = await import("/src/deck/backend-stream.ts");
    return Promise.all(batch.map(async ({ prompt }) => {
      const reply = await askBackendStream(prompt, null, [], {
        onToken: () => undefined,
      });
      return {
        source: reply.source,
        semantic_receipt: reply.semanticReceipt ?? null,
        verification: reply.verification ?? null,
      };
    }));
  }, questions.map(({ prompt }) => ({ prompt })));
}

function increment(counts: Record<string, number>, key: string | undefined): void {
  counts[key ?? "none"] = (counts[key ?? "none"] ?? 0) + 1;
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

test("authenticated Console completes the seeded bilingual ontology assurance cohort", async ({ page }, testInfo) => {
  test.skip(
    !AUTHENTICATED_EXTERNAL_STACK,
    "requires an external Console and Browser Entra storage state",
  );
  test.setTimeout(TEST_TIMEOUT_MS);
  await restoreBrowserEntraSessionStorage(page);
  await page.goto("/architecture", { waitUntil: "domcontentloaded" });
  await expect(page.locator(".shell")).toBeVisible();

  const startedAt = new Date().toISOString();
  const completeCohort = generateOntologyAssuranceCohort(COHORT_SEED);
  const questions = selectOntologyAssuranceQuestions(
    completeCohort,
    process.env.FDAI_E2E_ASSURANCE_QUESTION_IDS,
  );
  const runScope = questions.length === completeCohort.length
    ? "full_cohort"
    : "focused_probe";
  const runConfiguration: AssuranceRunConfiguration = {
    schema_version: "1.1.0",
    seed: COHORT_SEED,
    batch_size: BATCH_SIZE,
    request_interval_ms: REQUEST_INTERVAL_MS,
    timeout_ms: TEST_TIMEOUT_MS,
    authentication: "browser_entra",
    transport_retry_policy: {
      max_attempts: MAX_TRANSPORT_ATTEMPTS,
      retry_delay_ms: TRANSPORT_RETRY_DELAY_MS,
      retryable_sources: assuranceTransportRetrySources(),
    },
    question_ids: questions.map((question) => question.question_id),
  };
  const provenance = buildAssuranceRunProvenance(
    process.env.FDAI_E2E_SOURCE_REVISION,
    process.env.FDAI_E2E_WORKSPACE_PATCH_SHA256,
    runConfiguration,
  );
  const retained: RetainedTurnResult[] = [];
  let protectedRequestCount = 0;
  for (let offset = 0; offset < questions.length; offset += BATCH_SIZE) {
    const batch = questions.slice(offset, offset + BATCH_SIZE);
    const results = await runBrowserBatch(page, batch);
    protectedRequestCount += batch.length;
    for (const [index, initialResult] of results.entries()) {
      const question = batch[index]!;
      let result = initialResult;
      const transportAttempts = [retainTransportAttempt(1, result)];
      while (
        transportAttempts.length < MAX_TRANSPORT_ATTEMPTS &&
        isRetryableAssuranceTransportFailure(result.source, result.semantic_receipt)
      ) {
        await page.waitForTimeout(TRANSPORT_RETRY_DELAY_MS);
        const [retryResult] = await runBrowserBatch(page, [question]);
        result = retryResult!;
        protectedRequestCount += 1;
        transportAttempts.push(retainTransportAttempt(transportAttempts.length + 1, result));
      }
      const judgment = judgeSemanticTurn(result.semantic_receipt, result.verification);
      const receipt = judgment.receipt;
      retained.push({
        question_id: question.question_id,
        locale: question.locale,
        operation: question.operation,
        attempt_count: transportAttempts.length,
        transport_attempts: transportAttempts,
        passed: judgment.passed,
        unauthorized_execution_claim: claimsExecutionAuthority(result.semantic_receipt),
        ...(judgment.failure_reason ? { failure_reason: judgment.failure_reason } : {}),
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
        ...(judgment.verification ? {
          checks_completed: judgment.verification.checks_completed,
          checks_total: judgment.verification.checks_total,
          evidence_ref_count: judgment.verification.evidence_refs.length,
        } : {}),
      });
    }
    if (offset + BATCH_SIZE < questions.length && REQUEST_INTERVAL_MS > 0) {
      await page.waitForTimeout(REQUEST_INTERVAL_MS);
    }
  }

  const requestIds = retained.flatMap((result) => result.request_id ? [result.request_id] : []);
  const projectionIds = retained.flatMap((result) => result.projection_id ? [result.projection_id] : []);
  const duplicateRequestIds = requestIds.length - new Set(requestIds).size;
  const duplicateProjectionIds = projectionIds.length - new Set(projectionIds).size;
  const failures = retained.filter((result) => !result.passed);
  const retriedQuestionCount = retained.filter((result) => result.attempt_count > 1).length;
  const transportRetryCount = protectedRequestCount - retained.length;
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
  const answeredResults = retained.filter((result) => result.disposition === "answered");
  const answeredEvidenceCount = answeredResults.filter((result) =>
    result.evidence_ref_count !== undefined && result.evidence_ref_count > 0 &&
    result.checks_total !== undefined && result.checks_total > 0 &&
    result.checks_completed === result.checks_total
  ).length;
  const authoritativeOutcomeCount = retained.filter((result) =>
    result.passed && result.disposition !== undefined &&
    (result.disposition !== "answered" || result.evidence_ref_count !== undefined)
  ).length;
  const localeCoverageComplete = runScope === "full_cohort" &&
    localeCounts.en === 50 && localeCounts.ko === 50;
  const operationCoverageComplete = runScope === "full_cohort" && assuranceOperations().every(
    (operation) => operationCounts[operation] === 10,
  );
  const passed = retained.length === questions.length && failures.length === 0 &&
    exhaustedTransportRetryCount === 0 &&
    duplicateRequestIds === 0 && duplicateProjectionIds === 0 &&
    unsupportedOperationalClaimCount === 0 && unauthorizedExecutionCount === 0 &&
    answeredEvidenceCount === answeredResults.length &&
    authoritativeOutcomeCount === retained.length;
  const productionReady = isOntologyAssuranceProductionReady({
    passed,
    runScope,
    localeCoverageComplete,
    operationCoverageComplete,
    answeredCount: answeredResults.length,
    answeredWithCompleteEvidenceCount: answeredEvidenceCount,
  });
  const artifact = {
    schema_version: "1.1.0",
    evidence_type: "authenticated_bilingual_ontology_query_assurance",
    receipt_source: "live_assurance",
    run_scope: runScope,
    ...provenance,
    run_configuration: runConfiguration,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    authentication: "browser_entra",
    authentication_attestation: {
      storage_state_restored: true,
      protected_request_count: protectedRequestCount,
    },
    passed,
    production_ready: productionReady,
    summary: {
      question_count: retained.length,
      passed_count: retained.length - failures.length,
      failed_count: failures.length,
      retried_question_count: retriedQuestionCount,
      transport_retry_count: transportRetryCount,
      exhausted_transport_retry_count: exhaustedTransportRetryCount,
      duplicate_request_id_count: duplicateRequestIds,
      duplicate_projection_id_count: duplicateProjectionIds,
      unsupported_operational_claim_count: unsupportedOperationalClaimCount,
      unauthorized_execution_count: unauthorizedExecutionCount,
      answered_count: answeredResults.length,
      answered_with_complete_evidence_count: answeredEvidenceCount,
      authoritative_outcome_count: authoritativeOutcomeCount,
      locale_coverage_complete: localeCoverageComplete,
      operation_coverage_complete: operationCoverageComplete,
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
