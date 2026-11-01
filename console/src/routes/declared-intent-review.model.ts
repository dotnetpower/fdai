import {
  panelArray,
  panelBoolean,
  panelContractError,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
  panelString,
} from "./panel-decode";

export type DeclaredIntentLocale = "en" | "ko";
export type DeclaredIntentOperation = "add" | "update";

export interface DeclaredIntentPropertyChangePayload {
  readonly field_name: string;
  readonly before_value: string | null;
  readonly after_value: string | null;
  readonly changed: boolean;
}

export interface DeclaredIntentPropertiesPayload {
  readonly id: string;
  readonly name: string;
  readonly criticality: string;
  readonly effective_from: string;
  readonly effective_to: string | null;
  readonly source_ref: string;
}

export interface DeclaredIntentReviewProjectionPayload {
  readonly type: "declared-intent.review-projection";
  readonly schema_version: "1.0.0";
  readonly read_only: true;
  readonly authority: "none";
  readonly execution_authority: false;
  readonly protected_surface: true;
  readonly general_topic_safe: false;
  readonly action_type: "document.review-intent-diff";
  readonly intent_digest: string;
  readonly resource_id: string;
  readonly object_type: "BusinessService";
  readonly operation: DeclaredIntentOperation;
  readonly expected_revision: number;
  readonly scope_ref: string;
  readonly requester_ref: string;
  readonly reviewer_id: string;
  readonly independent_reviewer: true;
  readonly source_revision: number;
  readonly source_digest: string;
  readonly envelope_digest: string;
  readonly acl_digest: string;
  readonly ontology_release: string;
  readonly before_properties: DeclaredIntentPropertiesPayload | null;
  readonly after_properties: DeclaredIntentPropertiesPayload;
  readonly property_changes: readonly DeclaredIntentPropertyChangePayload[];
}

export interface DeclaredIntentGeneralTopicSummaryPayload {
  readonly type: "declared-intent.general-topic-summary";
  readonly schema_version: "1.0.0";
  readonly read_only: true;
  readonly authority: "none";
  readonly execution_authority: false;
  readonly protected_surface: false;
  readonly general_topic_safe: true;
  readonly discloses_source_properties: false;
  readonly intent_digest: string;
  readonly resource_id: string;
  readonly correlation_id: string;
  readonly phase: string;
  readonly producer_principal: string;
  readonly outcome: string;
  readonly applied_revision: number;
}

export interface DeclaredIntentDiffRowViewModel {
  readonly fieldName: string;
  readonly fieldLabel: string;
  readonly beforeDisplay: string;
  readonly afterDisplay: string;
  readonly changed: boolean;
  readonly changeBadge: string;
}

export interface DeclaredIntentReviewViewModel {
  readonly locale: DeclaredIntentLocale;
  readonly readOnly: true;
  readonly authority: "none";
  readonly executionAuthority: false;
  readonly protectedSurface: true;
  readonly title: string;
  readonly subtitle: string;
  readonly operationLabel: string;
  readonly authorityNotice: string;
  readonly privacyNotice: string;
  readonly intentDigest: string;
  readonly resourceId: string;
  readonly scopeRef: string;
  readonly requesterRef: string;
  readonly reviewerId: string;
  readonly expectedRevision: number;
  readonly sourceRevision: number;
  readonly changedFieldCount: number;
  readonly rows: readonly DeclaredIntentDiffRowViewModel[];
}

const OPERATIONS = new Set<DeclaredIntentOperation>(["add", "update"]);
const SHA256_RE = /^sha256:[a-f0-9]{64}$/;
const FORBIDDEN_GENERAL_KEYS = new Set([
  "properties", "before_properties", "after_properties", "property_changes",
  "name", "criticality", "effective_from", "effective_to", "source_ref",
  "document_id", "version_id", "document_bytes",
]);

const FIELD_LABELS: Record<DeclaredIntentLocale, Record<string, string>> = {
  en: {
    id: "Service ID",
    name: "Service Name",
    criticality: "Criticality",
    effective_from: "Effective From",
    effective_to: "Effective To",
    source_ref: "Source Version Reference",
  },
  ko: {
    id: "서비스 ID",
    name: "서비스 이름",
    criticality: "중요도",
    effective_from: "유효 시작 시각",
    effective_to: "유효 종료 시각",
    source_ref: "원본 버전 참조",
  },
};

const COPY: Record<
  DeclaredIntentLocale,
  {
    readonly title: string;
    readonly subtitle: string;
    readonly addOp: string;
    readonly updateOp: string;
    readonly changedBadge: string;
    readonly unchangedBadge: string;
    readonly unsetValue: string;
    readonly authorityNotice: string;
    readonly privacyNotice: string;
  }
> = {
  en: {
    title: "Protected Declared-Intent Exact-Diff Review",
    subtitle: "Independent Approver/Owner inspection bound to current source ACL and scope",
    addOp: "Add BusinessService (revision 0)",
    updateOp: "Update BusinessService",
    changedBadge: "Changed",
    unchangedBadge: "Unchanged",
    unsetValue: "(none)",
    authorityNotice:
      "Read-only exact-diff projection (authority=none). Viewing never approves or executes changes.",
    privacyNotice:
      "Source properties are restricted to this protected review surface and never appear on general topics.",
  },
  ko: {
    title: "보호된 선언형 의도 정밀 차분 검토",
    subtitle: "현재 원본 ACL 및 범위가 검증된 독립 승인자/소유자 전용 검토 화면",
    addOp: "BusinessService 신규 추가 (리비전 0)",
    updateOp: "BusinessService 업데이트",
    changedBadge: "변경됨",
    unchangedBadge: "변경 없음",
    unsetValue: "(없음)",
    authorityNotice:
      "읽기 전용 정밀 차분 프로젝션입니다 (authority=none). 조회만으로는 승인이나 실행 권한이 부여되지 않습니다.",
    privacyNotice:
      "원본 속성은 이 보호된 검토 화면에서만 제공되며 일반 토픽에는 절대 노출되지 않습니다.",
  },
};

function decodeProperties(value: unknown, label: string): DeclaredIntentPropertiesPayload {
  const rec = panelRecord(value, label);
  return {
    id: panelNonEmptyString(rec, "id", label),
    name: panelNonEmptyString(rec, "name", label),
    criticality: panelNonEmptyString(rec, "criticality", label),
    effective_from: panelNonEmptyString(rec, "effective_from", label),
    effective_to: panelNullableString(rec, "effective_to", label),
    source_ref: panelNonEmptyString(rec, "source_ref", label),
  };
}

function decodePropertyChange(value: unknown, index: number): DeclaredIntentPropertyChangePayload {
  const label = `DeclaredIntentReviewProjection.property_changes[${index}]`;
  const rec = panelRecord(value, label);
  return {
    field_name: panelNonEmptyString(rec, "field_name", label),
    before_value: panelNullableString(rec, "before_value", label),
    after_value: panelNullableString(rec, "after_value", label),
    changed: panelBoolean(rec, "changed", label),
  };
}

function requireDigest(root: Readonly<Record<string, unknown>>, key: string, label: string): string {
  const val = panelNonEmptyString(root, key, label);
  if (!SHA256_RE.test(val)) throw panelContractError(`${label}.${key} must be a sha256 digest`);
  return val;
}

export function decodeDeclaredIntentReviewProjection(
  value: unknown,
): DeclaredIntentReviewProjectionPayload {
  const label = "DeclaredIntentReviewProjection";
  const root = panelRecord(value, label);
  if (panelString(root, "type", label) !== "declared-intent.review-projection") {
    throw panelContractError(`${label}.type is invalid`);
  }
  if (panelString(root, "schema_version", label) !== "1.0.0") {
    throw panelContractError(`${label}.schema_version is invalid`);
  }
  if (!panelBoolean(root, "read_only", label)) {
    throw panelContractError(`${label}.read_only MUST be true`);
  }
  if (panelString(root, "authority", label) !== "none") {
    throw panelContractError(`${label}.authority MUST be none`);
  }
  if (panelBoolean(root, "execution_authority", label)) {
    throw panelContractError(`${label}.execution_authority MUST be false`);
  }
  if (!panelBoolean(root, "protected_surface", label) || panelBoolean(root, "general_topic_safe", label)) {
    throw panelContractError(`${label} surface flags are invalid`);
  }
  if (
    panelString(root, "action_type", label) !== "document.review-intent-diff" ||
    panelString(root, "object_type", label) !== "BusinessService" ||
    !panelBoolean(root, "independent_reviewer", label)
  ) {
    throw panelContractError(`${label} contract fields are invalid`);
  }
  const operation = panelString(root, "operation", label) as DeclaredIntentOperation;
  if (!OPERATIONS.has(operation)) throw panelContractError(`${label}.operation is invalid`);
  const rawChanges = panelArray(root["property_changes"], `${label}.property_changes`);
  if (rawChanges.length === 0) throw panelContractError(`${label}.property_changes MUST NOT be empty`);
  return {
    type: "declared-intent.review-projection",
    schema_version: "1.0.0",
    read_only: true,
    authority: "none",
    execution_authority: false,
    protected_surface: true,
    general_topic_safe: false,
    action_type: "document.review-intent-diff",
    intent_digest: requireDigest(root, "intent_digest", label),
    resource_id: panelNonEmptyString(root, "resource_id", label),
    object_type: "BusinessService",
    operation,
    expected_revision: panelNonNegativeInteger(root, "expected_revision", label),
    scope_ref: panelNonEmptyString(root, "scope_ref", label),
    requester_ref: panelNonEmptyString(root, "requester_ref", label),
    reviewer_id: panelNonEmptyString(root, "reviewer_id", label),
    independent_reviewer: true,
    source_revision: panelNonNegativeInteger(root, "source_revision", label),
    source_digest: requireDigest(root, "source_digest", label),
    envelope_digest: requireDigest(root, "envelope_digest", label),
    acl_digest: requireDigest(root, "acl_digest", label),
    ontology_release: requireDigest(root, "ontology_release", label),
    before_properties:
      root["before_properties"] === null
        ? null
        : decodeProperties(root["before_properties"], `${label}.before_properties`),
    after_properties: decodeProperties(root["after_properties"], `${label}.after_properties`),
    property_changes: rawChanges.map((item, idx) => decodePropertyChange(item, idx)),
  };
}

export function decodeDeclaredIntentGeneralTopicSummary(
  value: unknown,
): DeclaredIntentGeneralTopicSummaryPayload {
  const label = "DeclaredIntentGeneralTopicSummary";
  const root = panelRecord(value, label);
  for (const key of Object.keys(root)) {
    if (FORBIDDEN_GENERAL_KEYS.has(key)) {
      throw panelContractError(`${label} MUST NOT disclose source property field ${key}`);
    }
  }
  if (panelString(root, "type", label) !== "declared-intent.general-topic-summary") {
    throw panelContractError(`${label}.type is invalid`);
  }
  if (panelString(root, "schema_version", label) !== "1.0.0") {
    throw panelContractError(`${label}.schema_version is invalid`);
  }
  if (!panelBoolean(root, "read_only", label)) {
    throw panelContractError(`${label}.read_only MUST be true`);
  }
  if (panelString(root, "authority", label) !== "none") {
    throw panelContractError(`${label}.authority MUST be none`);
  }
  if (panelBoolean(root, "execution_authority", label)) {
    throw panelContractError(`${label}.execution_authority MUST be false`);
  }
  if (panelBoolean(root, "protected_surface", label)) {
    throw panelContractError(`${label}.protected_surface MUST be false`);
  }
  if (!panelBoolean(root, "general_topic_safe", label)) {
    throw panelContractError(`${label}.general_topic_safe MUST be true`);
  }
  if (panelBoolean(root, "discloses_source_properties", label)) {
    throw panelContractError(`${label}.discloses_source_properties MUST be false`);
  }
  const intentDigest = panelNonEmptyString(root, "intent_digest", label);
  if (!SHA256_RE.test(intentDigest)) {
    throw panelContractError(`${label}.intent_digest is invalid`);
  }
  return {
    type: "declared-intent.general-topic-summary",
    schema_version: "1.0.0",
    read_only: true,
    authority: "none",
    execution_authority: false,
    protected_surface: false,
    general_topic_safe: true,
    discloses_source_properties: false,
    intent_digest: intentDigest,
    resource_id: panelNonEmptyString(root, "resource_id", label),
    correlation_id: panelNonEmptyString(root, "correlation_id", label),
    phase: panelNonEmptyString(root, "phase", label),
    producer_principal: panelNonEmptyString(root, "producer_principal", label),
    outcome: panelNonEmptyString(root, "outcome", label),
    applied_revision: panelNonNegativeInteger(root, "applied_revision", label),
  };
}

export function formatDeclaredIntentReviewViewModel(
  payload: DeclaredIntentReviewProjectionPayload,
  locale: DeclaredIntentLocale = "en",
): DeclaredIntentReviewViewModel {
  const copy = COPY[locale];
  const labels = FIELD_LABELS[locale];
  const rows: DeclaredIntentDiffRowViewModel[] = payload.property_changes.map((change) => ({
    fieldName: change.field_name,
    fieldLabel: labels[change.field_name] ?? change.field_name,
    beforeDisplay: change.before_value ?? copy.unsetValue,
    afterDisplay: change.after_value ?? copy.unsetValue,
    changed: change.changed,
    changeBadge: change.changed ? copy.changedBadge : copy.unchangedBadge,
  }));
  const changedFieldCount = rows.filter((row) => row.changed).length;
  const operationLabel =
    payload.operation === "add"
      ? copy.addOp
      : `${copy.updateOp} (rev ${payload.expected_revision})`;

  return {
    locale,
    readOnly: true,
    authority: "none",
    executionAuthority: false,
    protectedSurface: true,
    title: copy.title,
    subtitle: copy.subtitle,
    operationLabel,
    authorityNotice: copy.authorityNotice,
    privacyNotice: copy.privacyNotice,
    intentDigest: payload.intent_digest,
    resourceId: payload.resource_id,
    scopeRef: payload.scope_ref,
    requesterRef: payload.requester_ref,
    reviewerId: payload.reviewer_id,
    expectedRevision: payload.expected_revision,
    sourceRevision: payload.source_revision,
    changedFieldCount,
    rows,
  };
}
