import { writeFile } from "node:fs/promises";

import { expect, test, type Page } from "@playwright/test";

import {
  assuranceOperations,
  generateOntologyAssuranceCohort,
  judgeSemanticTurn,
  type AssuranceQuestion,
} from "./ontology-query-assurance";

const COHORT_SEED = 0x0fda1;
const BATCH_SIZE = 5;
const AUTHENTICATED_EXTERNAL_STACK = Boolean(
  process.env.FDAI_E2E_BASE_URL && process.env.FDAI_E2E_STORAGE_STATE,
);

interface BrowserTurnResult {
  readonly semantic_receipt: unknown;
  readonly verification: unknown;
}

interface RetainedTurnResult {
  readonly question_id: string;
  readonly locale: AssuranceQuestion["locale"];
  readonly operation: AssuranceQuestion["operation"];
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

test("authenticated Console completes the seeded bilingual ontology assurance cohort", async ({ page }, testInfo) => {
  test.skip(
    !AUTHENTICATED_EXTERNAL_STACK,
    "requires an external Console and Browser Entra storage state",
  );
  test.setTimeout(4 * 60 * 60 * 1_000);
  await page.goto("/architecture", { waitUntil: "domcontentloaded" });
  await expect(page.locator("main")).toBeVisible();

  const startedAt = new Date().toISOString();
  const questions = generateOntologyAssuranceCohort(COHORT_SEED);
  const retained: RetainedTurnResult[] = [];
  for (let offset = 0; offset < questions.length; offset += BATCH_SIZE) {
    const batch = questions.slice(offset, offset + BATCH_SIZE);
    const results = await runBrowserBatch(page, batch);
    for (const [index, result] of results.entries()) {
      const question = batch[index]!;
      const judgment = judgeSemanticTurn(result.semantic_receipt, result.verification);
      const receipt = judgment.receipt;
      retained.push({
        question_id: question.question_id,
        locale: question.locale,
        operation: question.operation,
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
  }

  const requestIds = retained.flatMap((result) => result.request_id ? [result.request_id] : []);
  const projectionIds = retained.flatMap((result) => result.projection_id ? [result.projection_id] : []);
  const duplicateRequestIds = requestIds.length - new Set(requestIds).size;
  const duplicateProjectionIds = projectionIds.length - new Set(projectionIds).size;
  const failures = retained.filter((result) => !result.passed);
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
  const localeCoverageComplete = localeCounts.en === 50 && localeCounts.ko === 50;
  const operationCoverageComplete = assuranceOperations().every(
    (operation) => operationCounts[operation] === 10,
  );
  const passed = retained.length === 100 && failures.length === 0 &&
    duplicateRequestIds === 0 && duplicateProjectionIds === 0 &&
    unsupportedOperationalClaimCount === 0 && unauthorizedExecutionCount === 0 &&
    answeredEvidenceCount === answeredResults.length &&
    authoritativeOutcomeCount === retained.length && localeCoverageComplete &&
    operationCoverageComplete;
  const artifact = {
    schema_version: "1.0.0",
    evidence_type: "authenticated_bilingual_ontology_query_assurance",
    receipt_source: "live_assurance",
    seed: COHORT_SEED,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    authentication: "browser_entra",
    passed,
    production_ready: passed,
    summary: {
      question_count: retained.length,
      passed_count: retained.length - failures.length,
      failed_count: failures.length,
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

  expect(retained).toHaveLength(100);
  expect(failures, JSON.stringify(failures, null, 2)).toEqual([]);
  expect(duplicateRequestIds).toBe(0);
  expect(duplicateProjectionIds).toBe(0);
  expect(localeCounts).toEqual({ en: 50, ko: 50 });
});
