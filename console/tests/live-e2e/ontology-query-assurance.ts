import type {
  AnswerVerification,
  SemanticProjectionReceipt,
} from "../../src/deck/backend-types";
import {
  parseAnswerVerification,
  parseSemanticProjectionReceipt,
} from "../../src/deck/backend-normalizers";

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
