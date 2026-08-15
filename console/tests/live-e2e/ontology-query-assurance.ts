import type {
  AnswerVerification,
  SemanticProjectionReceipt,
} from "../../src/deck/backend-types";
import {
  parseAnswerVerification,
  parseSemanticProjectionReceipt,
} from "../../src/deck/backend-normalizers";
import { buildBrowserEvidenceProvenance } from "./browser-evidence-provenance";

export type AssuranceLocale = "en" | "ko";

export type AssuranceOperation =
  | "inventory_listing"
  | "relationship_traversal"
  | "property_filter"
  | "aggregation"
  | "temporal_comparison"
  | "causal_analysis"
  | "evidence_validation"
  | "action_draft_boundary"
  | "ambiguous_clarification"
  | "unsupported_domain";

export interface AssuranceQuestion {
  readonly question_id: string;
  readonly locale: AssuranceLocale;
  readonly operation: AssuranceOperation;
  readonly prompt: string;
}

export interface AssuranceJudgment {
  readonly passed: boolean;
  readonly failure_reason?: string;
  readonly receipt?: SemanticProjectionReceipt;
}

export interface AssuranceTurnJudgment extends AssuranceJudgment {
  readonly verification?: AnswerVerification;
}

export interface AssuranceRunConfiguration {
  readonly schema_version: "1.3.0";
  readonly run_id: string;
  readonly seed: number;
  readonly minimum_request_interval_ms: number;
  readonly per_question_deadline_ms: number;
  readonly no_progress_deadline_ms: number;
  readonly run_budget_ms: number;
  readonly authentication: "browser_entra";
  readonly transport_retry_policy: {
    readonly max_attempts: number;
    readonly base_retry_delay_ms: number;
    readonly max_retry_delay_ms: number;
    readonly retryable_sources: readonly string[];
  };
  readonly question_ids: readonly string[];
}

export interface AssuranceRunProvenance {
  readonly source_revision: string;
  readonly configuration_digest: string;
  readonly workspace_patch_digest: string;
}

export type AssuranceRunMode = "live" | "interrupted";

/**
 * Names how the published cohort was produced.
 *
 * `liveProven` is not a turn count: a turn that never produced a governed answer proves nothing
 * about the current stack, so only a verified live answer names the run live.
 */
export function assuranceRunMode(input: {
  readonly liveProven: boolean;
  readonly stopReason: string | null;
}): AssuranceRunMode {
  return input.stopReason === null && input.liveProven ? "live" : "interrupted";
}

/**
 * Returns whether a run may carry live release authority.
 *
 * Only a run that answered against the current stack may mint a production receipt.
 */
export function assuranceCarriesLiveAuthority(runMode: AssuranceRunMode): boolean {
  return runMode === "live";
}

/** Names the receipt a run may claim, so an interrupted live run is never called a replay. */
export function assuranceReceiptSource(input: {
  readonly runMode: AssuranceRunMode;
  readonly liveQuestionCount: number;
  readonly resumedCount: number;
}): "live_assurance" | "resumed_replay" | "interrupted_partial" {
  if (assuranceCarriesLiveAuthority(input.runMode)) return "live_assurance";
  return input.liveQuestionCount === 0 && input.resumedCount > 0
    ? "resumed_replay"
    : "interrupted_partial";
}

/**
 * Names the question a resumed run must always re-answer against the live stack.
 *
 * The checkpoint decides, not the operation taxonomy: an answer-required operation may legitimately
 * end in a governed refusal, so releasing it could leave the run unable to prove a generation. The
 * released question is the last one an earlier run actually answered with a generation digest, and
 * only a cohort with no such evidence falls back to the last answer-required question.
 */
export function liveProofQuestionIds(
  cohort: readonly { readonly question_id: string; readonly operation: AssuranceOperation }[],
  proven: readonly {
    readonly question_id: string;
    readonly disposition?: string;
    readonly ontology_release_digest?: string;
  }[] = [],
): readonly string[] {
  const answered = new Set(
    proven
      .filter((result) =>
        result.disposition === "answered" &&
        typeof result.ontology_release_digest === "string" &&
        result.ontology_release_digest.length > 0
      )
      .map((result) => result.question_id),
  );
  for (let index = cohort.length - 1; index >= 0; index -= 1) {
    const question = cohort[index]!;
    if (answered.has(question.question_id)) return [question.question_id];
  }
  for (let index = cohort.length - 1; index >= 0; index -= 1) {
    const question = cohort[index]!;
    if (ANSWER_REQUIRED_OPERATIONS.includes(question.operation)) return [question.question_id];
  }
  return [];
}

/**
 * Trims a checkpoint so the live-proof question is always re-answered.
 *
 * Resuming keeps earlier work instead of discarding it, but a cohort that answers nothing against
 * the current stack proves nothing about it. Selection is by cohort identity, not array position,
 * so a checkpoint stored out of order cannot release the wrong question.
 */
export function resumableWithLiveProof<
  TResult extends {
    readonly question_id: string;
    readonly disposition?: string;
    readonly ontology_release_digest?: string;
  },
>(
  resumed: readonly TResult[],
  cohort: readonly { readonly question_id: string; readonly operation: AssuranceOperation }[],
): readonly TResult[] {
  const proof = new Set(liveProofQuestionIds(cohort, resumed));
  return resumed.filter((result) => !proof.has(result.question_id));
}

interface AssuranceGenerationDigests {
  readonly ontology_release_digest?: string;
  readonly principal_manifest_digest?: string;
}

/**
 * Returns whether the resumed and live answers describe the same governed generation.
 *
 * Resumed evidence that no live answer confirms is not comparable evidence for the current stack,
 * so a cohort whose live turns disclose no generation may not republish generation-bearing
 * answers from an earlier stack.
 */
export function evidenceGenerationConsistent(input: {
  readonly resumed: readonly AssuranceGenerationDigests[];
  readonly live: readonly AssuranceGenerationDigests[];
}): boolean {
  const observed = (
    results: readonly AssuranceGenerationDigests[],
    key: keyof AssuranceGenerationDigests,
  ): ReadonlySet<string> =>
    new Set(
      results.map((result) => result[key]).filter((value): value is string => value !== undefined),
    );
  for (const key of ["ontology_release_digest", "principal_manifest_digest"] as const) {
    const resumedDigests = observed(input.resumed, key);
    const liveDigests = observed(input.live, key);
    if (resumedDigests.size > 1 || liveDigests.size > 1) return false;
    if (resumedDigests.size === 1 && liveDigests.size === 0) return false;
    for (const digest of resumedDigests) if (!liveDigests.has(digest)) return false;
  }
  return true;
}

/** Returns whether any live turn produced a governed answer bound to an ontology release. */
export function liveAnswerProof(
  live: readonly {
    readonly disposition?: string;
    readonly ontology_release_digest?: string;
  }[],
): boolean {
  return live.some((result) =>
    result.disposition === "answered" &&
    typeof result.ontology_release_digest === "string" &&
    result.ontology_release_digest.length > 0
  );
}

/**
 * Returns whether a checkpoint may be retired.
 *
 * Retirement requires the outcome the runner actually asserts, not only the pass conjunction, so a
 * complete cohort that fails its release criteria keeps its checkpoint instead of restarting from
 * nothing on the next run.
 */
export function checkpointRetirable(input: {
  readonly passed: boolean;
  readonly releaseSatisfied: boolean;
  readonly stopReason: string | null;
  readonly retainedCount: number;
  readonly cohortSize: number;
}): boolean {
  return input.passed && input.releaseSatisfied && input.stopReason === null &&
    input.cohortSize > 0 && input.retainedCount === input.cohortSize;
}

/**
 * Returns whether the checkpoint file must be removed.
 *
 * A truncated run may simply have proved nothing yet, so only a run that completed can prove that
 * its retained set actually mixes generations. Removing a checkpoint on an unproven run would
 * destroy verified turns that a later run could still resume.
 */
export function checkpointDiscardable(input: {
  readonly retirable: boolean;
  readonly generationConsistent: boolean;
  readonly stopReason: string | null;
}): boolean {
  return input.retirable || (!input.generationConsistent && input.stopReason === null);
}

/**
 * Keeps only the results that describe the generation the live turns observed.
 *
 * A release that rotates mid-run does not invalidate the turns taken under the newest generation,
 * so those survive and the next run resumes them instead of restarting the whole cohort.
 */
export function retainedForLiveGeneration<
  TResult extends {
    readonly ontology_release_digest?: string;
    readonly principal_manifest_digest?: string;
  },
>(
  retained: readonly TResult[],
  live: readonly TResult[],
): readonly TResult[] {
  const newest = (key: "ontology_release_digest" | "principal_manifest_digest"): string | null => {
    for (let index = live.length - 1; index >= 0; index -= 1) {
      const value = live[index]![key];
      if (typeof value === "string" && value.length > 0) return value;
    }
    return null;
  };
  const ontology = newest("ontology_release_digest");
  const principal = newest("principal_manifest_digest");
  return retained.filter((result) =>
    (result.ontology_release_digest === undefined || ontology === null ||
      result.ontology_release_digest === ontology) &&
    (result.principal_manifest_digest === undefined || principal === null ||
      result.principal_manifest_digest === principal)
  );
}

const LOCALES: readonly AssuranceLocale[] = ["en", "ko"];

/** The transport outcomes the runner records for one attempt. */
export type RetainedTransportAttemptOutcome =
  | "semantic_terminal"
  | "retryable_transport_failure"
  | "non_retryable_receipt_missing"
  | "per_attempt_deadline_exceeded"
  | "question_budget_exhausted"
  | "stalled_question"
  | "turn_error";

export interface RetainedTransportAttempt {
  readonly attempt: number;
  readonly outcome: RetainedTransportAttemptOutcome;
  readonly source?: string;
}

/** One retained turn, as both the artifact and the checkpoint carry it. */
export interface RetainedTurnResult {
  readonly question_id: string;
  readonly produced_by_run_id: string;
  readonly locale: AssuranceLocale;
  readonly operation: AssuranceOperation;
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

/** Adding an outcome without listing it here breaks the build instead of the checkpoint. */
const RETAINED_ATTEMPT_OUTCOME_MEMBERS: Record<RetainedTransportAttemptOutcome, true> = {
  semantic_terminal: true,
  retryable_transport_failure: true,
  non_retryable_receipt_missing: true,
  per_attempt_deadline_exceeded: true,
  question_budget_exhausted: true,
  stalled_question: true,
  turn_error: true,
};

const RETAINED_ATTEMPT_OUTCOMES: readonly string[] = Object.keys(
  RETAINED_ATTEMPT_OUTCOME_MEMBERS,
);

/** Rejects a checkpointed result that lost any field the pass criteria read. */
export function isRetainedTurnResult(value: Record<string, unknown>): boolean {
  const optionalNumbers = ["checks_completed", "checks_total", "evidence_ref_count"] as const;
  const optionalStrings = [
    "disposition",
    "reason_code",
    "failure_reason",
    "projection_id",
    "request_id",
    "semantic_route",
    "unavailable_reason",
    "ontology_release_digest",
    "principal_manifest_digest",
    "plan_digest",
    "execution_receipt_digest",
  ] as const;
  return typeof value.produced_by_run_id === "string" && value.produced_by_run_id.length > 0 &&
    typeof value.passed === "boolean" &&
    typeof value.unauthorized_execution_claim === "boolean" &&
    typeof value.attempt_count === "number" &&
    LOCALES.includes(value.locale as AssuranceLocale) &&
    OPERATIONS.includes(value.operation as AssuranceOperation) &&
    Array.isArray(value.transport_attempts) && value.transport_attempts.length > 0 &&
    value.transport_attempts.every((attempt) => {
      if (typeof attempt !== "object" || attempt === null) return false;
      const record = attempt as Record<string, unknown>;
      return typeof record.attempt === "number" &&
        RETAINED_ATTEMPT_OUTCOMES.includes(record.outcome as string) &&
        (record.source === undefined || typeof record.source === "string");
    }) &&
    optionalNumbers.every((key) => value[key] === undefined || typeof value[key] === "number") &&
    optionalStrings.every((key) => value[key] === undefined || typeof value[key] === "string") &&
    // The runner always records identifiers with a disposition, so a result missing them would
    // pass the uniqueness criteria vacuously.
    (value.disposition === undefined ||
      (typeof value.projection_id === "string" && typeof value.request_id === "string"));
}

/** Decides whether a completed cohort satisfies every governed pass criterion. */
export function assuranceCohortPassed(input: {
  readonly stopReason: string | null;
  readonly retainedCount: number;
  readonly cohortSize: number;
  readonly liveAuthority: boolean;
  readonly generationConsistent: boolean;
  readonly failureCount: number;
  readonly exhaustedTransportRetryCount: number;
  readonly duplicateRequestIdCount: number;
  readonly duplicateProjectionIdCount: number;
  readonly unsupportedOperationalClaimCount: number;
  readonly unauthorizedExecutionCount: number;
  readonly answeredCount: number;
  readonly answeredWithCompleteEvidenceCount: number;
  readonly authoritativeOutcomeCount: number;
}): boolean {
  return input.stopReason === null &&
    input.cohortSize > 0 && input.retainedCount === input.cohortSize &&
    input.liveAuthority && input.generationConsistent &&
    input.failureCount === 0 &&
    input.exhaustedTransportRetryCount === 0 &&
    input.duplicateRequestIdCount === 0 && input.duplicateProjectionIdCount === 0 &&
    input.unsupportedOperationalClaimCount === 0 && input.unauthorizedExecutionCount === 0 &&
    input.answeredWithCompleteEvidenceCount === input.answeredCount &&
    input.authoritativeOutcomeCount === input.retainedCount;
}

/**
 * Keeps only the results a later run should still resume when the release criteria were not met.
 *
 * A cohort can pass every turn and still miss its release criteria when an answer-required
 * operation only refused. Those turns are released so the next run re-attempts them; keeping them
 * would republish the same blocking outcome forever.
 */
export function releasableForCoverage<
  TResult extends { readonly operation: AssuranceOperation; readonly disposition?: string },
>(retained: readonly TResult[]): readonly TResult[] {
  return retained.filter((result) =>
    !(ANSWER_REQUIRED_OPERATIONS.includes(result.operation) && result.disposition !== "answered")
  );
}

/**
 * Names the checkpoint that belongs to one cohort against one binding.
 *
 * The key covers every field the binding validates, so a run against another revision, workspace,
 * or target stack keeps its own file instead of overwriting evidence it may not resume.
 */
export function assuranceCheckpointPath(input: {
  readonly configured: string | undefined;
  readonly directory: string;
  readonly runScope: string;
  readonly bindingDigest: string;
}): string | null {
  if (input.configured !== undefined) {
    const configured = input.configured.trim();
    return configured.length === 0 ? null : configured;
  }
  const key = input.bindingDigest.replace(/^sha256:/, "").slice(0, 16);
  return `${input.directory}/ontology-assurance-${input.runScope}-${key}.json`;
}

/** The configuration fields that decide whether an earlier result is still comparable evidence. */
export interface AssuranceEvidenceIdentity {
  readonly schema_version: AssuranceRunConfiguration["schema_version"];
  readonly seed: number;
  readonly authentication: AssuranceRunConfiguration["authentication"];
  readonly question_ids: readonly string[];
}

/**
 * Projects the evidence identity of a run configuration.
 *
 * Per-run session identity and operational pacing, deadline, and retry knobs are excluded on
 * purpose: they change what a run costs, not whether a completed answer remains valid evidence.
 * Including them would make every resume impossible and discard already-verified turns.
 */
export function assuranceEvidenceIdentity(
  configuration: AssuranceRunConfiguration,
): AssuranceEvidenceIdentity {
  return {
    schema_version: configuration.schema_version,
    seed: configuration.seed,
    authentication: configuration.authentication,
    question_ids: configuration.question_ids,
  };
}

const RETRYABLE_TRANSPORT_SOURCES = new Set([
  "deterministic (offline)",
  "deterministic (stream interrupted)",
  "deterministic (stream error)",
  "deterministic (empty stream)",
  "partial (stream interrupted)",
  "partial (stream error)",
  "partial (sequence gap)",
  "partial (missing terminal verification)",
]);

const ASSURANCE_RUN_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

export function resolveAssuranceRunId(raw: string | undefined): string {
  const runId = raw?.trim();
  if (runId === undefined || !ASSURANCE_RUN_ID_PATTERN.test(runId)) {
    throw new Error(
      "FDAI_E2E_ASSURANCE_RUN_ID must be 1-64 ASCII letters, digits, dots, underscores, or hyphens",
    );
  }
  return runId;
}

export function assuranceSessionId(runId: string, questionId: string): string {
  return `ontology-assurance:${runId}:${questionId}`;
}

const OPERATIONS: readonly AssuranceOperation[] = [
  "inventory_listing",
  "relationship_traversal",
  "property_filter",
  "aggregation",
  "temporal_comparison",
  "causal_analysis",
  "evidence_validation",
  "action_draft_boundary",
  "ambiguous_clarification",
  "unsupported_domain",
];

const ANSWER_REQUIRED_OPERATIONS: readonly AssuranceOperation[] = [
  "inventory_listing",
  "relationship_traversal",
  "property_filter",
  "aggregation",
  "temporal_comparison",
  "causal_analysis",
  "evidence_validation",
];

const ENGLISH_TEMPLATES: Readonly<Record<AssuranceOperation, readonly string[]>> = {
  inventory_listing: [
    "Which ontology object types are available to this operator?",
    "List the readable ontology interfaces in the active release.",
    "Show the resource classes visible in my current scope.",
    "Which read-only ontology functions can I use?",
    "List the queryable relationship types for this operator.",
  ],
  relationship_traversal: [
    "Which workloads are connected to the visible virtual networks?",
    "Show the resources attached to visible private endpoints.",
    "Which services depend on the visible storage resources?",
    "Trace the readable containment relationships for the current inventory.",
    "Which visible resources route to another ontology object?",
  ],
  property_filter: [
    "Which visible resources have a critical health status?",
    "Find readable resources whose lifecycle state is active.",
    "Show ontology objects in the current inventory generation.",
    "Which visible objects have independently verified evidence?",
    "Find readable resources with a declared resource type.",
  ],
  aggregation: [
    "Count visible resources by ontology object type.",
    "Group the readable resources by health status.",
    "How many visible relationship types are currently queryable?",
    "Count readable objects by lifecycle state.",
    "Summarize the number of visible resources in each class.",
  ],
  temporal_comparison: [
    "Compare the visible topology now with the previous retained generation.",
    "Which readable relationships changed since the prior inventory snapshot?",
    "Show visible resources added between the last two retained generations.",
    "Which readable topology links disappeared during the latest change window?",
    "Compare the current and previous health observations for visible resources.",
  ],
  causal_analysis: [
    "What evidence supports a network change affecting visible storage writes?",
    "Which competing explanations remain for the latest visible service degradation?",
    "Did a readable topology change precede the observed health regression?",
    "What evidence refutes the visible network path as the cause of the incident?",
    "Explain the latest visible metric change without treating chronology as causation.",
  ],
  evidence_validation: [
    "Validate whether the current visible inventory has complete evidence.",
    "Which readable claims have independent evidence references?",
    "Show evidence gaps for the visible topology projection.",
    "Is the latest readable metric window complete enough to compare?",
    "Which visible relationships lack the evidence needed for verification?",
  ],
  action_draft_boundary: [
    "Draft a governed change request to review the visible stale resources.",
    "Prepare an action draft for investigating the latest visible topology change.",
    "Create a non-executing draft to remediate visible unhealthy resources.",
    "Draft a governed request to validate the visible private endpoint paths.",
    "Prepare an action proposal for the visible evidence gaps without executing it.",
  ],
  ambiguous_clarification: [
    "Compare the increase for the visible services.",
    "Show the recent change in the relevant resources.",
    "Which of them has the highest value?",
    "Explain why the visible thing changed recently.",
    "Validate the important evidence for the current issue.",
  ],
  unsupported_domain: [
    "Which recipe should I cook for dinner tonight?",
    "Summarize the plot of a fictional space opera.",
    "Recommend a training plan for a marathon.",
    "What chord progression should I use for a jazz song?",
    "Plan a sightseeing route through an ancient city.",
  ],
};

const KOREAN_TEMPLATES: Readonly<Record<AssuranceOperation, readonly string[]>> = {
  inventory_listing: [
    "이 운영자가 조회할 수 있는 온톨로지 객체 유형은 무엇인가요?",
    "활성 릴리스에서 읽을 수 있는 온톨로지 인터페이스를 나열해 주세요.",
    "현재 범위에서 볼 수 있는 리소스 클래스를 보여 주세요.",
    "사용 가능한 읽기 전용 온톨로지 함수는 무엇인가요?",
    "이 운영자가 조회할 수 있는 관계 유형을 나열해 주세요.",
  ],
  relationship_traversal: [
    "조회 가능한 가상 네트워크에 연결된 워크로드는 무엇인가요?",
    "조회 가능한 프라이빗 엔드포인트에 연결된 리소스를 보여 주세요.",
    "조회 가능한 스토리지 리소스에 의존하는 서비스는 무엇인가요?",
    "현재 인벤토리에서 읽을 수 있는 포함 관계를 추적해 주세요.",
    "다른 온톨로지 객체로 라우팅되는 조회 가능한 리소스는 무엇인가요?",
  ],
  property_filter: [
    "상태가 위험인 조회 가능한 리소스는 무엇인가요?",
    "수명 주기 상태가 활성인 읽기 가능한 리소스를 찾아 주세요.",
    "현재 인벤토리 세대의 온톨로지 객체를 보여 주세요.",
    "독립적으로 검증된 증거가 있는 조회 가능한 객체는 무엇인가요?",
    "선언된 리소스 유형이 있는 읽기 가능한 리소스를 찾아 주세요.",
  ],
  aggregation: [
    "조회 가능한 리소스를 온톨로지 객체 유형별로 집계해 주세요.",
    "읽기 가능한 리소스를 상태별로 그룹화해 주세요.",
    "현재 조회 가능한 관계 유형은 몇 개인가요?",
    "읽기 가능한 객체를 수명 주기 상태별로 집계해 주세요.",
    "각 클래스의 조회 가능한 리소스 수를 요약해 주세요.",
  ],
  temporal_comparison: [
    "현재 조회 가능한 토폴로지를 이전 보존 세대와 비교해 주세요.",
    "이전 인벤토리 스냅샷 이후 어떤 읽기 가능한 관계가 바뀌었나요?",
    "최근 두 보존 세대 사이에 추가된 조회 가능한 리소스를 보여 주세요.",
    "최근 변경 구간에 사라진 읽기 가능한 토폴로지 링크는 무엇인가요?",
    "조회 가능한 리소스의 현재 상태 관측과 이전 관측을 비교해 주세요.",
  ],
  causal_analysis: [
    "네트워크 변경이 조회 가능한 스토리지 쓰기에 영향을 줬다는 증거는 무엇인가요?",
    "최근 조회 가능한 서비스 저하에 대해 남아 있는 대안 설명은 무엇인가요?",
    "읽기 가능한 토폴로지 변경이 관측된 상태 저하보다 먼저 발생했나요?",
    "조회 가능한 네트워크 경로가 장애 원인이라는 설명을 반박하는 증거는 무엇인가요?",
    "시간적 선후를 인과로 단정하지 말고 최근 조회 가능한 메트릭 변화를 설명해 주세요.",
  ],
  evidence_validation: [
    "현재 조회 가능한 인벤토리에 완전한 증거가 있는지 검증해 주세요.",
    "독립적인 증거 참조가 있는 읽기 가능한 주장은 무엇인가요?",
    "조회 가능한 토폴로지 투영의 증거 공백을 보여 주세요.",
    "최근 읽기 가능한 메트릭 구간은 비교하기에 충분히 완전한가요?",
    "검증에 필요한 증거가 부족한 조회 가능한 관계는 무엇인가요?",
  ],
  action_draft_boundary: [
    "조회 가능한 오래된 리소스를 검토할 통제된 변경 요청 초안을 작성해 주세요.",
    "최근 조회 가능한 토폴로지 변경을 조사할 작업 초안을 준비해 주세요.",
    "조회 가능한 비정상 리소스를 개선하되 실행하지 않는 초안을 작성해 주세요.",
    "조회 가능한 프라이빗 엔드포인트 경로를 검증할 통제된 요청 초안을 작성해 주세요.",
    "실행하지 말고 조회 가능한 증거 공백에 대한 작업 제안을 준비해 주세요.",
  ],
  ambiguous_clarification: [
    "조회 가능한 서비스의 증가분을 비교해 주세요.",
    "관련 리소스의 최근 변화를 보여 주세요.",
    "그중 값이 가장 높은 것은 무엇인가요?",
    "조회 가능한 대상이 최근 바뀐 이유를 설명해 주세요.",
    "현재 문제에서 중요한 증거를 검증해 주세요.",
  ],
  unsupported_domain: [
    "오늘 저녁에 요리할 음식을 추천해 주세요.",
    "가상의 우주 오페라 줄거리를 요약해 주세요.",
    "마라톤 훈련 계획을 추천해 주세요.",
    "재즈 곡에 사용할 코드 진행을 알려 주세요.",
    "고대 도시 관광 경로를 계획해 주세요.",
  ],
};

function seededRandom(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4_294_967_296;
  };
}

function shuffle<T>(values: readonly T[], seed: number): T[] {
  const result = [...values];
  const random = seededRandom(seed);
  for (let index = result.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(random() * (index + 1));
    [result[index], result[swapIndex]] = [result[swapIndex]!, result[index]!];
  }
  return result;
}

export function generateOntologyAssuranceCohort(seed: number): readonly AssuranceQuestion[] {
  const questions: AssuranceQuestion[] = [];
  for (const locale of ["en", "ko"] as const) {
    const templates = locale === "en" ? ENGLISH_TEMPLATES : KOREAN_TEMPLATES;
    for (const operation of OPERATIONS) {
      templates[operation].forEach((prompt, index) => {
        questions.push({
          question_id: `${locale}-${operation}-${index + 1}`,
          locale,
          operation,
          prompt,
        });
      });
    }
  }
  return shuffle(questions, seed);
}

/** Selects a deterministic, nonempty subset from a generated assurance cohort. */
export function selectOntologyAssuranceQuestions(
  cohort: readonly AssuranceQuestion[],
  rawQuestionIds: string | undefined,
): readonly AssuranceQuestion[] {
  if (rawQuestionIds === undefined) return cohort;
  const questionIds = rawQuestionIds.split(",").map((value) => value.trim());
  if (questionIds.some((questionId) => questionId.length === 0)) {
    throw new Error("FDAI_E2E_ASSURANCE_QUESTION_IDS must contain nonempty comma-separated ids");
  }
  if (new Set(questionIds).size !== questionIds.length) {
    throw new Error("FDAI_E2E_ASSURANCE_QUESTION_IDS must not contain duplicate ids");
  }
  const requestedIds = new Set(questionIds);
  const unknownIds = questionIds.filter(
    (questionId) => !cohort.some((question) => question.question_id === questionId),
  );
  if (unknownIds.length > 0) {
    throw new Error(`FDAI_E2E_ASSURANCE_QUESTION_IDS contains unknown ids: ${unknownIds.join(", ")}`);
  }
  const selected = cohort.filter((question) => requestedIds.has(question.question_id));
  // Only an answered turn discloses the generation that replied, so a selection without one could
  // never prove the live stack and would fail for a reason the operator cannot see.
  if (!selected.some((question) => ANSWER_REQUIRED_OPERATIONS.includes(question.operation))) {
    throw new Error(
      "FDAI_E2E_ASSURANCE_QUESTION_IDS must include at least one answer-required operation: " +
        ANSWER_REQUIRED_OPERATIONS.join(", "),
    );
  }
  return selected;
}

export function judgeSemanticReceipt(raw: unknown): AssuranceJudgment {
  const receipt = parseSemanticProjectionReceipt(raw);
  if (!receipt) return { passed: false, failure_reason: "invalid_semantic_receipt" };
  return { passed: true, receipt };
}

export function judgeSemanticTurn(
  rawReceipt: unknown,
  rawVerification: unknown,
): AssuranceTurnJudgment {
  const receiptJudgment = judgeSemanticReceipt(rawReceipt);
  if (!receiptJudgment.passed || !receiptJudgment.receipt) return receiptJudgment;

  const verification = parseAnswerVerification(rawVerification);
  if (verification && (
    verification.failed_claim_ids?.length !== 0 ||
    verification.claims?.some((claim) => claim.status === "unsupported") === true
  )) {
    return { passed: false, failure_reason: "unsupported_or_failed_claim" };
  }
  if (receiptJudgment.receipt.disposition !== "answered") {
    if (verification?.reason_code === "malformed_verification_artifact") {
      // An incoherent artifact is a defect on a governed refusal too, not only on an answer.
      return { passed: false, failure_reason: "malformed_verification_artifact" };
    }
    return {
      passed: true,
      receipt: receiptJudgment.receipt,
      ...(verification ? { verification } : {}),
    };
  }
  if (!verification) {
    return { passed: false, failure_reason: "missing_answer_verification" };
  }
  if (verification.status !== "verified") {
    return { passed: false, failure_reason: "answer_not_verified" };
  }
  if (
    verification.checks_total < 1 ||
    verification.checks_completed !== verification.checks_total
  ) {
    return { passed: false, failure_reason: "incomplete_evidence_checks" };
  }
  if (
    verification.evidence_refs.length < 1 ||
    new Set(verification.evidence_refs).size !== verification.evidence_refs.length
  ) {
    return { passed: false, failure_reason: "invalid_evidence_refs" };
  }
  return {
    passed: true,
    receipt: receiptJudgment.receipt,
    verification,
  };
}

export function assuranceOperations(): readonly AssuranceOperation[] {
  return OPERATIONS;
}

export function requiredAnswerOperations(): readonly AssuranceOperation[] {
  return ANSWER_REQUIRED_OPERATIONS;
}

export function hasRequiredAnswerCoverage(
  results: readonly {
    readonly operation: AssuranceOperation;
    readonly locale: AssuranceLocale;
    readonly disposition?: string;
    readonly complete_verified_evidence: boolean;
  }[],
): boolean {
  return ANSWER_REQUIRED_OPERATIONS.every((operation) => (
    (["en", "ko"] as const).every((locale) => results.some((result) => (
      result.operation === operation &&
      result.locale === locale &&
      result.disposition === "answered" &&
      result.complete_verified_evidence
    )))
  ));
}

export function assuranceTransportRetrySources(): readonly string[] {
  return [...RETRYABLE_TRANSPORT_SOURCES];
}

export function isRetryableAssuranceTransportFailure(
  source: string,
  rawReceipt: unknown,
): boolean {
  return rawReceipt == null && RETRYABLE_TRANSPORT_SOURCES.has(source);
}

export function buildAssuranceRunProvenance(
  sourceRevision: string | undefined,
  workspacePatchDigest: string | undefined,
  configuration: AssuranceRunConfiguration,
): AssuranceRunProvenance {
  return buildBrowserEvidenceProvenance(
    sourceRevision,
    workspacePatchDigest,
    configuration,
  );
}
