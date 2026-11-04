import { getLocale } from "../i18n";

export type PolicyAdminKind = "approval" | "admission";
export type ApprovalProfileKind = "multi-operator" | "single-operator-production";
export type PolicyModeKind = "shadow" | "enforce";

export interface PolicyRevisionDraft {
  readonly policyKind: PolicyAdminKind;
  readonly revisionId: string;
  readonly parentRevisionId: string;
  readonly approvalProfile: ApprovalProfileKind;
  readonly operatorPrincipal: string;
  readonly executorPrincipal: string;
  readonly effectiveFrom: string;
  readonly rego: string;
  readonly actionTypeName: string;
  readonly actionTypeMode: PolicyModeKind;
  readonly reason: string;
}

export interface PolicyRevisionSubmissionReceipt {
  readonly requestId: string;
  readonly requestDigest: string;
  readonly published: boolean;
}

const REVISION_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;
const ACTION_TYPE_RE = /^[a-z0-9]+(?:[._-][a-z0-9]+)*$/;

export function initialPolicyRevisionDraft(): PolicyRevisionDraft {
  return {
    policyKind: "approval",
    revisionId: "rev-13",
    parentRevisionId: "rev-12",
    approvalProfile: "single-operator-production",
    operatorPrincipal: "owner@example.com",
    executorPrincipal: "thor-executor-uami",
    effectiveFrom: "2026-11-01T00:00:00Z",
    rego: 'package fdai.admission\n\ndefault allow = false\nallow { input.mode == "shadow" }',
    actionTypeName: "aks.nodepool.scale",
    actionTypeMode: "shadow",
    reason: "Adopt reviewed single-operator production approval profile within Release maximums.",
  };
}

export function validatePolicyRevisionDraft(draft: PolicyRevisionDraft): string | null {
  const trimmedReason = draft.reason.trim();
  if (trimmedReason.length < 20 || trimmedReason.length > 1000) {
    return policyAdminText("errorReasonLength");
  }
  if (!REVISION_ID_RE.test(draft.revisionId.trim())) {
    return policyAdminText("errorRevisionId");
  }
  if (
    draft.parentRevisionId.trim() !== ""
    && !REVISION_ID_RE.test(draft.parentRevisionId.trim())
  ) {
    return policyAdminText("errorParentRevisionId");
  }
  if (
    draft.actionTypeName.trim() !== ""
    && !ACTION_TYPE_RE.test(draft.actionTypeName.trim())
  ) {
    return policyAdminText("errorActionType");
  }
  if (draft.policyKind === "approval") {
    const operator = draft.operatorPrincipal.trim();
    const executor = draft.executorPrincipal.trim();
    if (!operator || !executor) {
      return policyAdminText("errorPrincipalsRequired");
    }
    if (operator.toLowerCase() === executor.toLowerCase()) {
      return policyAdminText("errorApproverExecutorDistinct");
    }
  } else if (draft.rego.trim().length === 0) {
    return policyAdminText("errorRegoRequired");
  }
  return null;
}

export function buildPolicyRevisionRequestBody(
  draft: PolicyRevisionDraft,
): Record<string, unknown> {
  const actionTypeModes: Record<string, PolicyModeKind> = {};
  const actionName = draft.actionTypeName.trim();
  if (actionName) {
    actionTypeModes[actionName] = draft.actionTypeMode;
  }
  const parentRevisionId = draft.parentRevisionId.trim() || null;
  if (draft.policyKind === "approval") {
    return {
      policy_kind: "approval",
      parent_revision_id: parentRevisionId,
      reason: draft.reason.trim(),
      content: {
        document: {
          revision_id: draft.revisionId.trim(),
          approval_profile: draft.approvalProfile,
          operator_principal:
            draft.approvalProfile === "single-operator-production"
              ? draft.operatorPrincipal.trim()
              : null,
          executor_principal: draft.executorPrincipal.trim(),
          effective_from: draft.effectiveFrom.trim(),
          original_quorum: 2,
          effective_quorum:
            draft.approvalProfile === "single-operator-production" ? 1 : 2,
        },
        action_type_modes: actionTypeModes,
      },
    };
  }
  return {
    policy_kind: "admission",
    parent_revision_id: parentRevisionId,
    reason: draft.reason.trim(),
    content: {
      rego: draft.rego.trim(),
      action_type_modes: actionTypeModes,
      policy_tests: [],
    },
  };
}

export function decodePolicyRevisionReceipt(raw: unknown): PolicyRevisionSubmissionReceipt {
  if (typeof raw !== "object" || raw === null) {
    throw new Error("Policy revision response must be an object");
  }
  const record = raw as Record<string, unknown>;
  if (
    typeof record.request_id !== "string"
    || typeof record.request_digest !== "string"
    || typeof record.published !== "boolean"
  ) {
    throw new Error("Policy revision response is missing required receipt fields");
  }
  return {
    requestId: record.request_id,
    requestDigest: record.request_digest,
    published: record.published,
  };
}

const en = {
  title: "Policy administration (Approval & Admission OPA revisions)",
  subtitle:
    "Submit immutable approval-profile and restricted OPA/Rego admission policy revisions for Mimir validation, Key Vault signing, and activation.",
  openComposer: "Open policy revision composer",
  closeComposer: "Hide policy revision composer",
  promotionsLink: "Review capability promotions and recalls",
  quorumNotice:
    "Moving from multi-operator to single-operator production follows the current profile's governance quorum.Audit entries record approval_profile, original_quorum (2), effective_quorum (1), and operator principal.",
  hardBoundsCallout:
    "Core applies constitutional hard constraints (the seven safeguards, A4 denial, Var/Thor separation, and Release maximums) after operator policy, so no revision can relax them. A new revision applies only to decisions that start after activation.",
  validationTitle: "Mimir validation & activation gates",
  checkSchema: "Schema & canonical ActionType key order",
  checkRego: "Restricted Rego compilation and Release policy tests",
  checkReleaseMax: "No Release capability maximum exceeded (recall precedence enforced)",
  kindLabel: "Policy family",
  kindApproval: "Approval policy (profile & quorum)",
  kindAdmission: "Admission (OPA/Rego) policy",
  profileLabel: "Approval profile",
  profileSingle: "Single-operator production",
  profileMulti: "Multi-operator (default)",
  operatorPrincipalLabel: "Named operator principal (Microsoft Entra ID)",
  executorPrincipalLabel: "Executor principal (Thor Managed Identity, distinct)",
  revisionIdLabel: "Revision ID",
  parentRevisionIdLabel: "Parent revision ID",
  actionTypeLabel: "ActionType mode declaration",
  actionModeLabel: "Requested maximum mode",
  regoLabel: "Restricted OPA/Rego admission rules",
  reasonLabel: "Governance justification (20-1000 chars)",
  submitButton: "Submit policy revision request",
  submittingButton: "Submitting to Operator API...",
  submittedNotice: "Queued policy revision {requestId} ({requestDigest}) for Mimir validation and signing.",
  errorReasonLength: "Provide a trimmed governance justification between 20 and 1,000 characters.",
  errorRevisionId: "Enter a valid revision identifier.",
  errorParentRevisionId: "Parent revision identifier is invalid.",
  errorActionType: "ActionType name must use lowercase dot/hyphen tokens.",
  errorPrincipalsRequired: "Both operator and executor principals are required.",
  errorApproverExecutorDistinct: "The Var approval principal and Thor executor principal must remain distinct.",
  errorRegoRequired: "Admission policy revisions require non-empty Rego content.",
} as const;

const ko: Record<keyof typeof en, string> = {
  title: "정책 관리 (승인 프로필 및 OPA 허용 정책 개정)",
  subtitle:
    "Mimir 검증, Key Vault 서명 및 활성화를 위해 불변 승인 프로필과 제한된 OPA/Rego 허용 정책 개정 요청을 제출합니다.",
  openComposer: "정책 개정 작성기 열기",
  closeComposer: "정책 개정 작성기 닫기",
  promotionsLink: "기능 승격 게이트 및 리콜 현황 검토",
  quorumNotice:
    "다중 운영자에서 단일 운영자 프로덕션 프로필로 전환할 때는 현재 프로필의 거버넌스 정족수를 따릅니다. 감사 로그에는 approval_profile, original_quorum(2), effective_quorum(1), 운영자 주체가 기록됩니다.",
  hardBoundsCallout:
    "Core는 운영자 정책 평가 이후에 헌법적 절대 제약(7대 안전장치, A4 거부, Var/Thor 분리, 릴리스 상한)을 적용하므로 어떤 정책 개정도 이를 완화할 수 없습니다. 새 개정은 활성화 이후 시작되는 결정에만 적용됩니다.",
  validationTitle: "Mimir 검증 및 활성화 게이트",
  checkSchema: "스키마 및 정규 ActionType 키 순서 검증",
  checkRego: "제한된 Rego 컴파일 및 릴리스 정책 테스트",
  checkReleaseMax: "릴리스 기능 상한 미초과 (리콜 우선순위 강제)",
  kindLabel: "정책 분류",
  kindApproval: "승인 정책 (프로필 및 정족수)",
  kindAdmission: "허용 (OPA/Rego) 정책",
  profileLabel: "승인 프로필",
  profileSingle: "단일 운영자 프로덕션 (single-operator-production)",
  profileMulti: "다중 운영자 기본값 (multi-operator)",
  operatorPrincipalLabel: "지정 운영자 주체 (Microsoft Entra ID)",
  executorPrincipalLabel: "실행기 주체 (Thor 관리 ID, 분리 필수)",
  revisionIdLabel: "개정 ID",
  parentRevisionIdLabel: "부모 개정 ID",
  actionTypeLabel: "ActionType 모드 선언",
  actionModeLabel: "요청 최대 모드",
  regoLabel: "제한된 OPA/Rego 허용 규칙",
  reasonLabel: "거버넌스 사유 (20~1000자)",
  submitButton: "정책 개정 요청 제출",
  submittingButton: "Operator API로 제출 중...",
  submittedNotice: "Mimir 검증 및 서명을 위해 정책 개정 {requestId} ({requestDigest}) 요청이 큐에 등록되었습니다.",
  errorReasonLength: "공백을 제외한 20자 이상 1,000자 이하의 거버넌스 사유를 입력하세요.",
  errorRevisionId: "유효한 개정 ID를 입력하세요.",
  errorParentRevisionId: "부모 개정 ID 형식이 올바르지 않습니다.",
  errorActionType: "ActionType 이름은 소문자 점/하이픈 토큰이어야 합니다.",
  errorPrincipalsRequired: "운영자 주체와 실행기 주체를 모두 입력해야 합니다.",
  errorApproverExecutorDistinct: "Var 승인 주체와 Thor 실행기 주체는 반드시 서로 달라야 합니다.",
  errorRegoRequired: "허용 정책 개정에는 비어 있지 않은 Rego 본문이 필요합니다.",
};

export function policyAdminText(
  key: keyof typeof en,
  values: Readonly<Record<string, string | number>> = {},
): string {
  return ((getLocale() === "ko" ? ko[key] : undefined) || en[key]).replace(
    /\{(\w+)\}/g,
    (token, name: string) => String(values[name] ?? token),
  );
}
