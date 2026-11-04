// Whether a blocked candidate Release is waiting out something that resolves on its own (a
// closed maintenance window, an active suppression) or was rejected for a reason that won't
// change until someone acts (a recall, a schema or version mismatch, a missing artifact, data
// residency, an override block, a destructive change). These deserve different colors: the first
// is routine and expected, the second usually needs an operator's attention.
//
// This intentionally mirrors `TIMING_REASONS` in `lifecycle/hub/src/fdai_lifecycle_hub/planning.py`.
// Reason codes are a stable, canonical token shared across the Hub and this UI.
import type { CandidateCheck } from "./api";
import type { HubLocale } from "./locale";

const TIMING_REASON_CODES = new Set([
  "maintenance_window_unavailable",
  "maintenance_window_invalid",
  "suppression_window_active",
  "suppression_window_invalid",
  "suppression_scope_invalid",
]);

const CONSTRAINT_REASON_SENTENCES: Readonly<Record<string, string>> = {
  maintenance_window_unavailable: "Waiting for the next open maintenance window that fits the declared duration.",
  maintenance_window_invalid: "The declared maintenance window start/end bounds are invalid.",
  suppression_window_active: "Blocked temporarily while an active suppression window is in effect.",
  suppression_window_invalid: "The declared suppression window bounds or origin are invalid.",
  suppression_scope_invalid: "The suppression window scope selector is malformed.",
  release_version_outside_range: "Candidate release version is outside the installation's subscribed version range.",
  artifact_requirements_missing: "Candidate release manifest declares no required image artifacts.",
  artifact_unavailable: "Required signed release image artifacts are not yet available in the local bundle/registry.",
  data_residency_missing: "Candidate release does not declare supported data-residency regions.",
  data_residency_mismatch: "Candidate release regions do not satisfy the installation's data-residency policy.",
  target_release_digest_mismatch: "Candidate release digest does not match the admitted Plan target digest.",
  plan_type_unsupported: "The requested Plan type is not supported by the lifecycle evaluator.",
  plan_context_mismatch: "Plan context fields do not match the candidate evaluation inputs.",
  schema_downgrade_blocked: "Database schema downgrade is blocked by the forward-only migration contract.",
  schema_step_gap: "Candidate release skips a required intermediate schema revision.",
  recalled_release: "Candidate release has been recalled and cannot be planned.",
  recalled_capability: "Candidate release includes a recalled capability.",
  missing_matching_override_block: "Entity override configuration has no block matching this release version.",
};

const CONSTRAINT_REASON_SENTENCES_KO: Readonly<Record<string, string>> = {
  maintenance_window_unavailable: "선언된 유지 시간을 충족하는 다음 유지보수 구간이 열릴 때까지 대기 중입니다.",
  maintenance_window_invalid: "선언된 유지보수 구간의 시작/종료 범위가 올바르지 않습니다.",
  suppression_window_active: "활성 억제 구간이 적용 중이어서 일시적으로 차단되었습니다.",
  suppression_window_invalid: "선언된 억제 구간의 시간 범위 또는 출처가 올바르지 않습니다.",
  suppression_scope_invalid: "억제 구간의 범위 선택자 형식이 올바르지 않습니다.",
  release_version_outside_range: "후보 릴리스 버전이 설치 환경의 구독 버전 범위를 벗어납니다.",
  artifact_requirements_missing: "후보 릴리스 매니페스트에 필수 이미지 아티팩트가 선언되어 있지 않습니다.",
  artifact_unavailable: "필수 서명 릴리스 이미지 아티팩트가 아직 로컬 번들/레지스트리에 준비되지 않았습니다.",
  data_residency_missing: "후보 릴리스에 지원되는 데이터 상주 리전이 선언되어 있지 않습니다.",
  data_residency_mismatch: "후보 릴리스 리전이 설치 환경의 데이터 상주 정책을 충족하지 않습니다.",
  target_release_digest_mismatch: "후보 릴리스 다이제스트가 허용된 계획 대상 다이제스트와 일치하지 않습니다.",
  plan_type_unsupported: "요청된 계획 유형을 수명 주기 평가기에서 지원하지 않습니다.",
  plan_context_mismatch: "계획 컨텍스트 필드가 후보 평가 입력값과 일치하지 않습니다.",
  schema_downgrade_blocked: "데이터베이스 스키마 다운그레이드가 순방향 전용 마이그레이션 계약에 의해 차단되었습니다.",
  schema_step_gap: "후보 릴리스가 필수 중간 스키마 개정 단계를 건너뜁니다.",
  recalled_release: "후보 릴리스가 회수되어 계획을 수립할 수 없습니다.",
  recalled_capability: "후보 릴리스에 회수된 기능이 포함되어 있습니다.",
  missing_matching_override_block: "엔티티 재정의 구성에 이 릴리스 버전과 일치하는 블록이 없습니다.",
};

export function isTimingReason(reasonCode: string): boolean {
  return TIMING_REASON_CODES.has(reasonCode);
}

export function describeConstraintReason(reasonCode: string, locale: HubLocale = "en"): string {
  if (locale === "ko") {
    return (
      CONSTRAINT_REASON_SENTENCES_KO[reasonCode] ??
      `제약 조건 검사에서 ${reasonCode.replaceAll("_", " ")} 항목이 보고되었습니다.`
    );
  }
  return CONSTRAINT_REASON_SENTENCES[reasonCode] ?? `Constraint check reported ${reasonCode.replaceAll("_", " ")}.`;
}

export function constraintVerdict(check: CandidateCheck): "passed" | "waiting" | "blocked" {
  if (check.blocks.length === 0) return "passed";
  return check.blocks.every((block) => isTimingReason(block.reason_code)) ? "waiting" : "blocked";
}

export function normalizeConstraintOutcome(
  value: unknown,
): "passed" | "waiting" | "blocking" {
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed === "passed" || trimmed === "waiting" || trimmed === "blocking") {
      return trimmed;
    }
    if (trimmed === "blocked") {
      return "blocking";
    }
    if (isTimingReason(trimmed)) {
      return "waiting";
    }
  }
  return "blocking";
}

export function summarizeConstraintOutcomes(
  outcomes: readonly unknown[],
): { blocking: number; warning: number; passed: number; total: number } {
  let blocking = 0;
  let warning = 0;
  let passed = 0;
  for (const outcome of outcomes) {
    const normalized =
      typeof outcome === "string" && outcome.trim() === "warning"
        ? "waiting"
        : normalizeConstraintOutcome(outcome);
    if (normalized === "passed") {
      passed += 1;
    } else if (normalized === "waiting") {
      warning += 1;
    } else {
      blocking += 1;
    }
  }
  return {
    blocking,
    warning,
    passed,
    total: outcomes.length,
  };
}
