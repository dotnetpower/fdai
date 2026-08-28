import { readConsolePreferences } from "../preferences";
import type {
  AnswerEvidenceManifest,
  AnswerVerification,
  AnswerVerificationStatus,
  AtomicAnswerClaim,
  AtomicClaimStatus,
  DelegationMetadata,
  EvidenceFreshnessContext,
  ConfirmedAnswerSegment,
  EvidenceBranch,
  EvidenceBranchKind,
  EvidenceBranchStatus,
  EvidenceManifestEntry,
  InvestigationActivity,
  InvestigationActivityStatus,
  InvestigationExecutionTarget,
  InvestigationMilestone,
  ModelUsage,
  RetrievalSourcePreview,
  RouterCandidate,
  RouterSnapshot,
  ResourceContext,
  SemanticAssuranceFrame,
  SemanticAssuranceObservation,
  SemanticAssurancePath,
  SemanticAssurancePathStep,
  SemanticProjectionReceipt,
} from "./backend-types";
import { PANTHEON } from "../routes/agents.model";

const PANTHEON_AGENT_NAMES = new Set(PANTHEON.map((agent) => agent.name));
const MAX_AGENT_NAME_CHARS = 64;
const MAX_TRACE_REF_CHARS = 256;
const RESOURCE_NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}$/;
const RESOURCE_TYPE_PATTERN = /^[a-z0-9][a-z0-9_.-]{1,127}$/;
const RESOURCE_GROUP_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.()-]{1,127}$/;
const EVENT_STATUS_PATTERN = /^[A-Za-z][A-Za-z0-9 _.-]{1,63}$/;
const RESOURCE_EVIDENCE_PREFIXES = ["inventory:", "subscription-health:"] as const;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;
const SEMANTIC_DIRECT_RESPONSE_INTENTS = new Set(["greeting", "self_introduction"] as const);
const SEMANTIC_REASON_PATTERN = /^[a-z0-9_]{1,128}$/;
const SEMANTIC_ASSURANCE_IDENTIFIER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const SEMANTIC_OPERATIONS = new Set<SemanticAssuranceFrame["operation"]>([
  "select",
  "aggregate",
  "compare",
  "explain_change",
  "validate",
  "action_draft",
]);
const SEMANTIC_EVIDENCE_POSTURES = new Set<SemanticAssuranceObservation["evidence_posture"]>([
  "fresh",
  "stale",
  "incomplete",
  "conflicting",
  "unavailable",
]);
const SEMANTIC_DISPOSITIONS = new Set<SemanticProjectionReceipt["disposition"]>([
  "answered",
  "direct_response",
  "held",
  "clarification",
  "unsupported",
  "action_draft",
  "cancelled",
]);
const SEMANTIC_ROUTES = new Set<NonNullable<SemanticProjectionReceipt["semantic_route"]>>([
  "verified_query_plan",
  "semantic_direct_response",
  "semantic_clarification",
  "semantic_unsupported",
  "semantic_action_draft",
  "semantic_cancellation",
]);
const SEMANTIC_UNAVAILABLE_REASONS = new Set<NonNullable<SemanticProjectionReceipt["unavailable_reason"]>>([
  "authoritative_evidence_unavailable",
  "historical_evidence_unavailable",
  "semantic_planner_unavailable",
]);
const SEMANTIC_ROUTE_BY_DISPOSITION: Partial<Record<SemanticProjectionReceipt["disposition"], NonNullable<SemanticProjectionReceipt["semantic_route"]>>> = {
  answered: "verified_query_plan",
  direct_response: "semantic_direct_response",
  clarification: "semantic_clarification",
  unsupported: "semantic_unsupported",
  action_draft: "semantic_action_draft",
  cancelled: "semantic_cancellation",
};

export function parseSemanticProjectionReceipt(
  raw: unknown,
): SemanticProjectionReceipt | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  const disposition = record.disposition;
  const semanticRoute = record.semantic_route;
  const unavailableReason = record.unavailable_reason;
  const directResponseIntent = record.direct_response_intent;
  const schemaVersion = record.schema_version;
  if (
    (schemaVersion !== "1.0.0" && schemaVersion !== "2.0.0") ||
    typeof record.projection_id !== "string" ||
    !UUID_PATTERN.test(record.projection_id) ||
    typeof record.request_id !== "string" ||
    !UUID_PATTERN.test(record.request_id) ||
    typeof disposition !== "string" ||
    !SEMANTIC_DISPOSITIONS.has(disposition as SemanticProjectionReceipt["disposition"]) ||
    typeof record.reason_code !== "string" ||
    !SEMANTIC_REASON_PATTERN.test(record.reason_code) ||
    record.execution_authority !== false
  ) return undefined;
  const expectedRoute = SEMANTIC_ROUTE_BY_DISPOSITION[
    disposition as SemanticProjectionReceipt["disposition"]
  ];
  if (disposition === "held") {
    if (
      semanticRoute !== undefined ||
      typeof unavailableReason !== "string" ||
      !SEMANTIC_UNAVAILABLE_REASONS.has(
        unavailableReason as NonNullable<SemanticProjectionReceipt["unavailable_reason"]>,
      )
    ) return undefined;
  } else if (
    typeof semanticRoute !== "string" ||
    !SEMANTIC_ROUTES.has(
      semanticRoute as NonNullable<SemanticProjectionReceipt["semantic_route"]>,
    ) ||
    semanticRoute !== expectedRoute ||
    unavailableReason !== undefined
  ) return undefined;
  const digestKeys = [
    "ontology_release_digest",
    "principal_manifest_digest",
    "plan_digest",
    "execution_receipt_digest",
  ] as const;
  const digests: Partial<Record<typeof digestKeys[number], string>> = {};
  for (const key of digestKeys) {
    const value = record[key];
    if (value !== undefined) {
      if (typeof value !== "string" || !DIGEST_PATTERN.test(value)) return undefined;
      digests[key] = value;
    }
  }
  if (disposition === "answered" && Object.keys(digests).length !== digestKeys.length) {
    return undefined;
  }
  if (
    (disposition === "direct_response" &&
      !SEMANTIC_DIRECT_RESPONSE_INTENTS.has(
        directResponseIntent as "greeting" | "self_introduction",
      )) ||
    (disposition !== "direct_response" && directResponseIntent !== undefined) ||
    (disposition === "direct_response" && Object.keys(digests).length > 0)
  ) return undefined;
  const assuranceObservation = schemaVersion === "2.0.0"
    ? parseSemanticAssuranceObservation(record.assurance_observation)
    : undefined;
  if (
    (schemaVersion === "2.0.0" && assuranceObservation === undefined) ||
    (schemaVersion === "1.0.0" && record.assurance_observation !== undefined)
  ) return undefined;
  return {
    schema_version: schemaVersion,
    projection_id: record.projection_id,
    request_id: record.request_id,
    disposition: disposition as SemanticProjectionReceipt["disposition"],
    reason_code: record.reason_code,
    ...(semanticRoute !== undefined ? {
      semantic_route: semanticRoute as NonNullable<SemanticProjectionReceipt["semantic_route"]>,
    } : {}),
    ...(unavailableReason !== undefined ? {
      unavailable_reason: unavailableReason as NonNullable<SemanticProjectionReceipt["unavailable_reason"]>,
    } : {}),
    ...(directResponseIntent !== undefined ? {
      direct_response_intent: directResponseIntent as "greeting" | "self_introduction",
    } : {}),
    ...digests,
    ...(assuranceObservation !== undefined ? {
      assurance_observation: assuranceObservation,
    } : {}),
    execution_authority: false,
  };
}

function parseSemanticAssuranceObservation(raw: unknown): SemanticAssuranceObservation | undefined {
  const record = asExactRecord(raw, [
    "schema_version",
    "frame",
    "capabilities",
    "object_types",
    "link_types",
    "function_types",
    "ontology_paths",
    "fact_kinds",
    "limitation_kinds",
    "claim_kinds",
    "evidence_posture",
    "authority_posture",
    "read_performed",
    "observation_digest",
    "execution_authority",
  ]);
  if (record === undefined) return undefined;
  const frame = record.frame === null ? null : parseSemanticAssuranceFrame(record.frame);
  const capabilities = parseOrderedIdentifiers(record.capabilities, 128);
  const objectTypes = parseOrderedIdentifiers(record.object_types, 128);
  const linkTypes = parseOrderedIdentifiers(record.link_types, 128);
  const functionTypes = parseOrderedIdentifiers(record.function_types, 128);
  const factKinds = parseOrderedIdentifiers(record.fact_kinds, 128);
  const limitationKinds = parseOrderedIdentifiers(record.limitation_kinds, 128);
  const claimKinds = parseOrderedIdentifiers(record.claim_kinds, 128);
  const paths = parseSemanticAssurancePaths(record.ontology_paths);
  if (
    record.schema_version !== "1.0.0" ||
    (record.frame !== null && frame === undefined) ||
    capabilities === undefined ||
    objectTypes === undefined ||
    linkTypes === undefined ||
    functionTypes === undefined ||
    factKinds === undefined ||
    limitationKinds === undefined ||
    claimKinds === undefined ||
    paths === undefined ||
    typeof record.evidence_posture !== "string" ||
    !SEMANTIC_EVIDENCE_POSTURES.has(
      record.evidence_posture as SemanticAssuranceObservation["evidence_posture"],
    ) ||
    (record.authority_posture !== "read_only" && record.authority_posture !== "draft_only") ||
    typeof record.read_performed !== "boolean" ||
    typeof record.observation_digest !== "string" ||
    !DIGEST_PATTERN.test(record.observation_digest) ||
    record.execution_authority !== false
  ) return undefined;
  return {
    schema_version: "1.0.0",
    frame: frame ?? null,
    capabilities,
    object_types: objectTypes,
    link_types: linkTypes,
    function_types: functionTypes,
    ontology_paths: paths,
    fact_kinds: factKinds,
    limitation_kinds: limitationKinds,
    claim_kinds: claimKinds,
    evidence_posture: record.evidence_posture as SemanticAssuranceObservation["evidence_posture"],
    authority_posture: record.authority_posture,
    read_performed: record.read_performed,
    observation_digest: record.observation_digest,
    execution_authority: false,
  };
}

function parseSemanticAssuranceFrame(raw: unknown): SemanticAssuranceFrame | undefined {
  const record = asExactRecord(raw, [
    "operation",
    "subject_types",
    "measure_concepts",
    "temporal_scope",
    "output_shape",
    "frame_digest",
  ]);
  if (record === undefined) return undefined;
  const subjects = parseOrderedIdentifiers(record.subject_types, 16);
  const measures = parseOrderedIdentifiers(record.measure_concepts, 16);
  if (
    typeof record.operation !== "string" ||
    !SEMANTIC_OPERATIONS.has(record.operation as SemanticAssuranceFrame["operation"]) ||
    subjects === undefined ||
    measures === undefined ||
    !["none", "current", "windowed", "historical"].includes(String(record.temporal_scope)) ||
    typeof record.output_shape !== "string" ||
    !SEMANTIC_ASSURANCE_IDENTIFIER_PATTERN.test(record.output_shape) ||
    typeof record.frame_digest !== "string" ||
    !DIGEST_PATTERN.test(record.frame_digest)
  ) return undefined;
  return {
    operation: record.operation as SemanticAssuranceFrame["operation"],
    subject_types: subjects,
    measure_concepts: measures,
    temporal_scope: record.temporal_scope as SemanticAssuranceFrame["temporal_scope"],
    output_shape: record.output_shape,
    frame_digest: record.frame_digest,
  };
}

function parseSemanticAssurancePaths(raw: unknown): readonly SemanticAssurancePath[] | undefined {
  if (!Array.isArray(raw) || raw.length > 16) return undefined;
  const parsed = raw.map(parseSemanticAssurancePath);
  if (parsed.some((item) => item === undefined)) return undefined;
  const paths = parsed as SemanticAssurancePath[];
  const pathIds = paths.map((path) => path.path_id);
  return isOrderedUnique(pathIds) ? paths : undefined;
}

function parseSemanticAssurancePath(raw: unknown): SemanticAssurancePath | undefined {
  const record = asExactRecord(raw, ["path_id", "steps"]);
  if (
    record === undefined ||
    typeof record.path_id !== "string" ||
    !SEMANTIC_ASSURANCE_IDENTIFIER_PATTERN.test(record.path_id) ||
    !Array.isArray(record.steps) ||
    record.steps.length < 1 ||
    record.steps.length > 5
  ) return undefined;
  const parsed = record.steps.map(parseSemanticAssurancePathStep);
  if (parsed.some((item) => item === undefined)) return undefined;
  return { path_id: record.path_id, steps: parsed as SemanticAssurancePathStep[] };
}

function parseSemanticAssurancePathStep(raw: unknown): SemanticAssurancePathStep | undefined {
  const record = asExactRecord(raw, ["from_type", "link_type", "direction", "to_type"]);
  if (
    record === undefined ||
    ![record.from_type, record.link_type, record.to_type].every(
      (item) => typeof item === "string" && SEMANTIC_ASSURANCE_IDENTIFIER_PATTERN.test(item),
    ) ||
    (record.direction !== "outgoing" && record.direction !== "incoming")
  ) return undefined;
  return {
    from_type: record.from_type as string,
    link_type: record.link_type as string,
    direction: record.direction,
    to_type: record.to_type as string,
  };
}

function parseOrderedIdentifiers(raw: unknown, maxItems: number): readonly string[] | undefined {
  if (
    !Array.isArray(raw) ||
    raw.length > maxItems ||
    raw.some((item) => typeof item !== "string" || !SEMANTIC_ASSURANCE_IDENTIFIER_PATTERN.test(item))
  ) return undefined;
  return isOrderedUnique(raw as string[]) ? raw as string[] : undefined;
}

function isOrderedUnique(values: readonly string[]): boolean {
  for (let index = 1; index < values.length; index += 1) {
    const previous = values[index - 1];
    const current = values[index];
    if (previous === undefined || current === undefined || previous >= current) return false;
  }
  return true;
}

function asExactRecord(raw: unknown, keys: readonly string[]): Record<string, unknown> | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  const actual = Object.keys(record).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index])
    ? record
    : undefined;
}

export function parseResourceContext(raw: unknown): ResourceContext | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  const evidenceRef = record.evidence_ref;
  if (
    typeof record.name !== "string" ||
    !RESOURCE_NAME_PATTERN.test(record.name) ||
    typeof record.resource_type !== "string" ||
    !RESOURCE_TYPE_PATTERN.test(record.resource_type) ||
    typeof evidenceRef !== "string" ||
    !RESOURCE_EVIDENCE_PREFIXES.some((prefix) => evidenceRef.startsWith(prefix)) ||
    evidenceRef.length > 1024
  ) return undefined;
  const anchorValues = [record.resource_group, record.event_at, record.event_status];
  const hasAnchor = anchorValues.some((value) => value !== undefined);
  if (hasAnchor && (
    typeof record.resource_group !== "string" ||
    !RESOURCE_GROUP_PATTERN.test(record.resource_group) ||
    typeof record.event_at !== "string" ||
    !Number.isFinite(Date.parse(record.event_at)) ||
    typeof record.event_status !== "string" ||
    !EVENT_STATUS_PATTERN.test(record.event_status)
  )) return undefined;
  return {
    name: record.name,
    resource_type: record.resource_type,
    evidence_ref: evidenceRef,
    ...(hasAnchor ? {
      resource_group: record.resource_group as string,
      event_at: record.event_at as string,
      event_status: record.event_status as string,
    } : {}),
  };
}

export function parseEvidenceFreshnessContext(
  raw: unknown,
): EvidenceFreshnessContext | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  if (
    typeof record.source !== "string" ||
    record.source.length === 0 ||
    record.source.length > 512 ||
    typeof record.observed_at !== "string" ||
    !Number.isFinite(Date.parse(record.observed_at)) ||
    typeof record.window_start !== "string" ||
    !Number.isFinite(Date.parse(record.window_start)) ||
    Date.parse(record.window_start) > Date.parse(record.observed_at) ||
    !["matched", "partial", "none", "unavailable"].includes(String(record.status)) ||
    typeof record.truncated !== "boolean"
  ) return undefined;
  return {
    source: record.source,
    observed_at: record.observed_at,
    window_start: record.window_start,
    status: record.status as EvidenceFreshnessContext["status"],
    truncated: record.truncated,
  };
}

const ACTIVITY_STATUSES = new Set<InvestigationActivityStatus>([
  "pending",
  "running",
  "completed",
  "unavailable",
  "failed",
]);

const MAX_EXECUTION_TOOL_CHARS = 64;
const MAX_EXECUTION_COMMAND_CHARS = 16 * 1024;
const MAX_EXECUTION_OUTPUT_CHARS = 64 * 1024;
const MAX_EXECUTION_TARGET_CHARS = 128;
const EXECUTION_INTERFACE_KINDS = new Set<InvestigationExecutionTarget["interfaceKind"]>([
  "internal_query",
  "http",
  "cli",
  "sdk",
]);
const EXECUTION_TRANSPORTS = new Set<NonNullable<InvestigationExecutionTarget["transport"]>>([
  "event_bus",
  "in_process",
]);
const HTTP_METHODS = new Set<NonNullable<InvestigationExecutionTarget["endpoint"]>["method"]>([
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
]);
const MAX_ACTIVITY_ID_CHARS = 128;
const MAX_ACTIVITY_KIND_CHARS = 128;
const MAX_ACTIVITY_LABEL_CHARS = 512;
const MAX_ACTIVITY_DETAIL_CHARS = 16 * 1024;
const MAX_ACTIVITY_AUTHORITY_CHARS = 1024;
const MAX_ACTIVITY_TIMESTAMP_CHARS = 64;
const MAX_MILESTONE_ID_CHARS = 128;
const MAX_MILESTONE_TEXT_CHARS = 16 * 1024;
const MAX_RETRIEVAL_KIND_CHARS = 128;
const MAX_RETRIEVAL_LABEL_CHARS = 512;
const MAX_RETRIEVAL_DETAIL_CHARS = 16 * 1024;
const MAX_VERIFICATION_CLAIMS = 64;
const MAX_EVIDENCE_ENTRIES = 512;
const MAX_VERIFICATION_REFS = MAX_EVIDENCE_ENTRIES + 8;
const MAX_CLAIM_REFS = MAX_EVIDENCE_ENTRIES;
const MAX_ARTIFACT_LIST_ITEMS = 64;
const MAX_ARTIFACT_IDENTIFIER_CHARS = 1024;
const MAX_ARTIFACT_VALUE_CHARS = 16 * 1024;
const MAX_BRANCH_ID_CHARS = 256;
const MAX_BRANCH_SUMMARY_CHARS = 512;
const MAX_BRANCH_REFS = 64;
const MAX_CONFIRMED_TEXT_CHARS = 256 * 1024;
const BRANCH_KINDS = new Set<EvidenceBranchKind>([
  "tool",
  "operational",
  "agent",
  "public_web",
]);
const BRANCH_STATUSES = new Set<EvidenceBranchStatus>([
  "pending",
  "running",
  "completed",
  "unavailable",
  "failed",
  "timed_out",
  "cancelled",
]);
const TERMINAL_BRANCH_STATUSES = new Set<EvidenceBranchStatus>([
  "completed",
  "unavailable",
  "failed",
  "timed_out",
  "cancelled",
]);

function parseInvestigationExecution(raw: unknown): InvestigationActivity["execution"] {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  if (
    typeof record.tool !== "string" ||
    record.tool.length === 0 ||
    record.tool.length > MAX_EXECUTION_TOOL_CHARS ||
    typeof record.command !== "string" ||
    record.command.length === 0 ||
    record.command.length > MAX_EXECUTION_COMMAND_CHARS ||
    record.redacted !== true
  ) return undefined;
  const inputKind = record.input_kind === undefined ? "command" : record.input_kind;
  if (inputKind !== "command" && inputKind !== "query") return undefined;
  const output = typeof record.output === "string" &&
      record.output.length <= MAX_EXECUTION_OUTPUT_CHARS
    ? record.output
    : undefined;
  const exitCode = typeof record.exit_code === "number" &&
      Number.isSafeInteger(record.exit_code)
    ? record.exit_code
    : undefined;
  if (inputKind === "query" && exitCode !== undefined) return undefined;
  const durationMs = typeof record.duration_ms === "number" &&
      Number.isSafeInteger(record.duration_ms) &&
      record.duration_ms >= 0
    ? record.duration_ms
    : undefined;
  const target = parseInvestigationExecutionTarget(record.target);
  if (record.target !== undefined && target === undefined) return undefined;
  return {
    tool: record.tool,
    command: record.command,
    inputKind,
    ...(target ? { target } : {}),
    redacted: true,
    ...(output !== undefined ? { output } : {}),
    ...(record.output_truncated === true ? { outputTruncated: true } : {}),
    ...(exitCode !== undefined ? { exitCode } : {}),
    ...(typeof record.started_at === "string" && record.started_at.length <= 64
      ? { startedAt: record.started_at }
      : {}),
    ...(typeof record.completed_at === "string" && record.completed_at.length <= 64
      ? { completedAt: record.completed_at }
      : {}),
    ...(durationMs !== undefined ? { durationMs } : {}),
  };
}

function parseInvestigationExecutionTarget(raw: unknown): InvestigationExecutionTarget | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  const interfaceKind = record.interface_kind;
  if (
    typeof interfaceKind !== "string" ||
    !EXECUTION_INTERFACE_KINDS.has(interfaceKind as InvestigationExecutionTarget["interfaceKind"]) ||
    !machineToken(record.service) ||
    !machineToken(record.component) ||
    !machineToken(record.operation)
  ) return undefined;
  const sourceKind = record.source_kind === undefined
    ? undefined
    : machineToken(record.source_kind) ? record.source_kind : null;
  if (sourceKind === null) return undefined;
  const transport = record.transport === undefined
    ? undefined
    : typeof record.transport === "string" &&
      EXECUTION_TRANSPORTS.has(record.transport as NonNullable<InvestigationExecutionTarget["transport"]>)
    ? record.transport as NonNullable<InvestigationExecutionTarget["transport"]>
    : null;
  if (transport === null) return undefined;
  const endpoint = parseExecutionEndpoint(record.endpoint);
  if (record.endpoint !== undefined && endpoint === undefined) return undefined;
  if (interfaceKind === "http" && endpoint === undefined) return undefined;
  if (interfaceKind !== "http" && endpoint !== undefined) return undefined;
  return {
    interfaceKind: interfaceKind as InvestigationExecutionTarget["interfaceKind"],
    service: record.service as string,
    component: record.component as string,
    operation: record.operation as string,
    ...(sourceKind ? { sourceKind } : {}),
    ...(transport ? { transport } : {}),
    ...(endpoint ? { endpoint } : {}),
  };
}

function parseExecutionEndpoint(raw: unknown): InvestigationExecutionTarget["endpoint"] | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  if (
    typeof record.method !== "string" ||
    !HTTP_METHODS.has(record.method as NonNullable<InvestigationExecutionTarget["endpoint"]>["method"]) ||
    typeof record.path !== "string" ||
    !/^\/[A-Za-z0-9._~!$&'()*+,;=:@%/-]{1,255}$/.test(record.path) ||
    record.path.includes("//")
  ) return undefined;
  return {
    method: record.method as NonNullable<InvestigationExecutionTarget["endpoint"]>["method"],
    path: record.path,
  };
}

function machineToken(value: unknown): value is string {
  return typeof value === "string" &&
    value.length > 0 &&
    value.length <= MAX_EXECUTION_TARGET_CHARS &&
    /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(value);
}

export function parseInvestigationActivity(raw: unknown): InvestigationActivity | null {
  if (typeof raw !== "object" || raw === null) return null;
  const record = raw as Record<string, unknown>;
  const status = record.status;
  if (
    !nonemptyBoundedString(record.activity_id, MAX_ACTIVITY_ID_CHARS) ||
    !nonemptyBoundedString(record.kind, MAX_ACTIVITY_KIND_CHARS) ||
    typeof status !== "string" ||
    !ACTIVITY_STATUSES.has(status as InvestigationActivityStatus) ||
    !nonemptyBoundedString(record.label, MAX_ACTIVITY_LABEL_CHARS)
  ) return null;
  const completed = finiteProgress(record.completed);
  const total = finiteProgress(record.total);
  if (completed !== null && total !== null && completed > total) return null;
  const execution = parseInvestigationExecution(record.execution);
  return {
    activityId: record.activity_id,
    kind: record.kind,
    status: status as InvestigationActivityStatus,
    label: record.label,
    ...(typeof record.agent === "string" && record.agent.length > 0 && record.agent.length <= 64
      ? { agent: record.agent }
      : {}),
    ...(nonemptyBoundedString(record.detail, MAX_ACTIVITY_DETAIL_CHARS)
      ? { detail: record.detail }
      : {}),
    completed,
    total,
    ...(nonemptyBoundedString(record.authority, MAX_ACTIVITY_AUTHORITY_CHARS)
      ? { authority: record.authority }
      : {}),
    ...(nonemptyBoundedString(record.observed_at, MAX_ACTIVITY_TIMESTAMP_CHARS)
      ? { observedAt: record.observed_at }
      : {}),
    ...(execution ? { execution } : {}),
    ...(nonemptyBoundedString(record.branch_id, MAX_BRANCH_ID_CHARS)
      ? { branchId: record.branch_id }
      : {}),
  };
}

export function parseInvestigationMilestone(raw: unknown): InvestigationMilestone | null {
  if (typeof raw !== "object" || raw === null) return null;
  const record = raw as Record<string, unknown>;
  if (
    !nonemptyBoundedString(record.message_id, MAX_MILESTONE_ID_CHARS) ||
    !nonemptyBoundedString(record.text, MAX_MILESTONE_TEXT_CHARS) ||
    record.text.trim().length === 0
  ) return null;
  return {
    messageId: record.message_id,
    text: record.text,
    ...(nonemptyBoundedString(record.agent, MAX_AGENT_NAME_CHARS)
      ? { agent: record.agent }
      : {}),
    ...(validTimestamp(record.recorded_at) ? { recordedAt: record.recorded_at } : {}),
  };
}

export function parseEvidenceBranch(raw: unknown): EvidenceBranch | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const kind = record.branch_kind;
  const status = record.status;
  if (
    !nonemptyBoundedString(record.branch_id, MAX_BRANCH_ID_CHARS) ||
    typeof kind !== "string" ||
    !BRANCH_KINDS.has(kind as EvidenceBranchKind) ||
    typeof status !== "string" ||
    !BRANCH_STATUSES.has(status as EvidenceBranchStatus) ||
    !nonemptyBoundedString(record.summary, MAX_BRANCH_SUMMARY_CHARS) ||
    !validTimestamp(record.started_at)
  ) return null;
  const parentBranchId = record.parent_branch_id === null
    ? null
    : nonemptyBoundedString(record.parent_branch_id, MAX_BRANCH_ID_CHARS)
    ? record.parent_branch_id
    : undefined;
  if (parentBranchId === undefined) return null;
  const completedAt = validTimestamp(record.completed_at) ? record.completed_at : undefined;
  const durationMs = typeof record.duration_ms === "number" &&
      Number.isSafeInteger(record.duration_ms) && record.duration_ms >= 0
    ? record.duration_ms
    : undefined;
  const evidenceRefs = boundedStrings(record.evidence_refs, MAX_BRANCH_REFS, 1024);
  if (evidenceRefs === null) return null;
  const terminal = TERMINAL_BRANCH_STATUSES.has(status as EvidenceBranchStatus);
  if ((!terminal && (completedAt !== undefined || evidenceRefs.length > 0)) ||
      (completedAt !== undefined && Date.parse(completedAt) < Date.parse(record.started_at))) {
    return null;
  }
  return {
    branchId: record.branch_id,
    kind: kind as EvidenceBranchKind,
    parentBranchId,
    status: status as EvidenceBranchStatus,
    summary: record.summary,
    startedAt: record.started_at,
    ...(completedAt !== undefined ? { completedAt } : {}),
    ...(durationMs !== undefined ? { durationMs } : {}),
    evidenceRefs,
  };
}

export function parseConfirmedAnswerSegment(
  raw: unknown,
  revision: number,
): ConfirmedAnswerSegment | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const status = parseVerificationStatus(record.status);
  const refs = boundedStrings(record.evidence_refs, MAX_VERIFICATION_REFS, 1024);
  if (
    !Number.isSafeInteger(revision) || revision < 0 ||
    !Number.isSafeInteger(record.segment_index) ||
    (record.segment_index as number) < 0 ||
    (record.segment_index as number) >= 64 ||
    !nonemptyBoundedString(record.text, MAX_CONFIRMED_TEXT_CHARS) ||
    status === null || status === "unverified" || refs === null
  ) return null;
  const parsedReplaceStart = nonnegativeSafeInteger(record.replace_start);
  const parsedReplaceEnd = nonnegativeSafeInteger(record.replace_end);
  const replaceStart = parsedReplaceStart === null ? undefined : parsedReplaceStart;
  const replaceEnd = parsedReplaceEnd === null ? undefined : parsedReplaceEnd;
  if ((replaceStart === undefined) !== (replaceEnd === undefined) ||
      (replaceStart !== undefined && replaceEnd !== undefined && replaceEnd < replaceStart)) {
    return null;
  }
  return {
    segmentIndex: record.segment_index as number,
    revision,
    text: record.text,
    status,
    evidenceRefs: refs,
    ...(replaceStart !== undefined ? { replaceStart } : {}),
    ...(replaceEnd !== undefined ? { replaceEnd } : {}),
  };
}

function validTimestamp(value: unknown): value is string {
  return nonemptyBoundedString(value, MAX_ACTIVITY_TIMESTAMP_CHARS) &&
    Number.isFinite(Date.parse(value));
}

function boundedStrings(raw: unknown, maximum: number, chars: number): string[] | null {
  if (!Array.isArray(raw) || raw.length > maximum) return null;
  if (!raw.every((item) => nonemptyBoundedString(item, chars))) return null;
  return raw as string[];
}

function finiteProgress(raw: unknown): number | null {
  return typeof raw === "number" && Number.isSafeInteger(raw) && raw >= 0 ? raw : null;
}

export function parseRetrievalSourcePreviews(
  raw: unknown,
): readonly RetrievalSourcePreview[] {
  if (!Array.isArray(raw)) return [];
  const sources: RetrievalSourcePreview[] = [];
  for (const item of raw.slice(0, 8)) {
    if (typeof item !== "object" || item === null) continue;
    const record = item as Record<string, unknown>;
    const side = record.side_effect_class;
    if (
      !nonemptyBoundedString(record.kind, MAX_RETRIEVAL_KIND_CHARS) ||
      !nonemptyBoundedString(record.label, MAX_RETRIEVAL_LABEL_CHARS) ||
      !nonemptyBoundedString(record.detail, MAX_RETRIEVAL_DETAIL_CHARS) ||
      (side !== "read" && side !== "route" && side !== "simulate" && side !== "ground")
    ) continue;
    sources.push({
      kind: record.kind,
      label: record.label,
      detail: record.detail,
      side_effect_class: side,
    });
  }
  return sources;
}

export function parseDelegation(raw: unknown): DelegationMetadata | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;
  if (
    typeof record.primary_agent !== "string" ||
    record.primary_agent.length === 0 ||
    record.primary_agent.length > MAX_AGENT_NAME_CHARS ||
    !PANTHEON_AGENT_NAMES.has(record.primary_agent)
  ) {
    return undefined;
  }
  const contributors = Array.isArray(record.contributors)
    ? record.contributors.filter(
        (item): item is string =>
          typeof item === "string" &&
          item.length <= MAX_AGENT_NAME_CHARS &&
          PANTHEON_AGENT_NAMES.has(item),
      ).slice(0, 8)
    : [];
  const handoffReason = typeof record.handoff_reason === "string"
    ? record.handoff_reason.trim().slice(0, 128)
    : "";
  return {
    primary_agent: record.primary_agent,
    contributors,
    ...(typeof record.trace_ref === "string" && record.trace_ref.length > 0
      ? { trace_ref: record.trace_ref.slice(0, MAX_TRACE_REF_CHARS) }
      : {}),
    ...(typeof record.handoff_from === "string" && PANTHEON_AGENT_NAMES.has(record.handoff_from)
      ? { handoff_from: record.handoff_from }
      : {}),
    ...(handoffReason.length > 0
      ? { handoff_reason: handoffReason }
      : {}),
  };
}

let queuedRequestId: string | null = null;

/** Queue one verified semantic request UUID for the next single in-flight stream. */
export function queueNextRequestId(requestId: string): void {
  if (!UUID_PATTERN.test(requestId)) throw new Error("queued request ID must be a UUID");
  queuedRequestId = requestId;
}

export function newRequestId(): string {
  if (queuedRequestId !== null) {
    const requestId = queuedRequestId;
    queuedRequestId = null;
    return requestId;
  }
  const cryptoLike = globalThis.crypto as { randomUUID?: () => string } | undefined;
  return cryptoLike?.randomUUID?.() ?? `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function parseVerificationStatus(raw: unknown): AnswerVerificationStatus | null {
  return raw === "verified" ||
      raw === "consistent" ||
      raw === "corrected" ||
      raw === "unverified"
    ? raw
    : null;
}

export function parseAnswerVerification(raw: unknown): AnswerVerification | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;
  const status = parseVerificationStatus(record.status);
  if (status === null || !boundedString(record.authority, MAX_ARTIFACT_IDENTIFIER_CHARS)) {
    return undefined;
  }
  const checksCompleted = nonnegativeSafeInteger(record.checks_completed);
  const checksTotal = nonnegativeSafeInteger(record.checks_total);
  const malformedCounters = checksCompleted === null ||
    checksTotal === null || checksCompleted > checksTotal;
  const refs = boundedStringArray(
    record.evidence_refs,
    MAX_VERIFICATION_REFS,
    MAX_ARTIFACT_IDENTIFIER_CHARS,
  );
  const failedClaimIds = boundedStringArray(
    record.failed_claim_ids ?? [],
    MAX_VERIFICATION_CLAIMS,
    MAX_ARTIFACT_IDENTIFIER_CHARS,
  );
  const reasonCode = record.reason_code === null || record.reason_code === undefined
    ? null
    : boundedString(record.reason_code, MAX_ARTIFACT_IDENTIFIER_CHARS)
      ? record.reason_code
      : undefined;
  const claims = parseAtomicClaims(record.claims);
  const manifest = parseEvidenceManifest(record.evidence_manifest);
  const artifactPresent = record.claims !== undefined || record.evidence_manifest !== undefined;
  const malformedArtifact = malformedCounters || refs === null || failedClaimIds === null ||
    reasonCode === undefined ||
    (artifactPresent && (claims === null || manifest === null)) ||
    !verificationArtifactsAgree({
      status,
      authority: record.authority,
      checksCompleted,
      checksTotal,
      refs,
      claims,
      manifest,
      failedClaimIds: failedClaimIds ?? [],
    });
  return {
    status: malformedArtifact ? "unverified" : status,
    authority: record.authority,
    checks_completed: malformedCounters ? 0 : checksCompleted,
    checks_total: malformedCounters ? 0 : checksTotal,
    evidence_refs: refs ?? [],
    reason_code: malformedArtifact
      ? "malformed_verification_artifact"
      : reasonCode,
    claims: claims ?? [],
    ...(manifest ? { evidence_manifest: manifest } : {}),
    failed_claim_ids: failedClaimIds ?? [],
  };
}

function parseAtomicClaims(raw: unknown): AtomicAnswerClaim[] | null {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || raw.length > MAX_VERIFICATION_CLAIMS) return null;
  const claims: AtomicAnswerClaim[] = [];
  for (const item of raw) {
    if (typeof item !== "object" || item === null) return null;
    const claim = item as Record<string, unknown>;
    const kind = claim.kind;
    const status = claim.status;
    const span = claim.span;
    const spanRecord =
      typeof span === "object" && span !== null
        ? (span as Record<string, unknown>)
        : null;
    const start = spanRecord?.start;
    const end = spanRecord?.end;
    const startValue = nonnegativeSafeInteger(start);
    const endValue = nonnegativeSafeInteger(end);
    if (
      !boundedString(claim.claim_id, MAX_ARTIFACT_IDENTIFIER_CHARS) ||
      !["id", "number", "percentage", "timestamp", "causal", "scope"].includes(
        String(kind),
      ) ||
      !boundedString(claim.text, MAX_ARTIFACT_VALUE_CHARS) ||
      startValue === null ||
      endValue === null ||
      startValue > endValue ||
      !boundedString(claim.raw_value, MAX_ARTIFACT_VALUE_CHARS) ||
      !boundedString(claim.normalized_value, MAX_ARTIFACT_VALUE_CHARS) ||
      (claim.unit !== null && !boundedString(claim.unit, MAX_ARTIFACT_IDENTIFIER_CHARS)) ||
      !boundedStringArray(
        claim.anchors,
        MAX_ARTIFACT_LIST_ITEMS,
        MAX_ARTIFACT_IDENTIFIER_CHARS,
      ) ||
      !["supported", "unsupported", "ambiguous"].includes(String(status)) ||
      !boundedStringArray(
        claim.evidence_refs,
        MAX_CLAIM_REFS,
        MAX_ARTIFACT_IDENTIFIER_CHARS,
      ) ||
      (claim.reason_code !== null &&
        !boundedString(claim.reason_code, MAX_ARTIFACT_IDENTIFIER_CHARS))
    ) return null;
    claims.push({
      claim_id: claim.claim_id,
      kind: kind as AtomicAnswerClaim["kind"],
      text: claim.text,
      span: { start: startValue, end: endValue },
      raw_value: claim.raw_value,
      normalized_value: claim.normalized_value,
      unit: claim.unit as string | null,
      anchors: claim.anchors as string[],
      status: status as AtomicClaimStatus,
      evidence_refs: claim.evidence_refs as string[],
      reason_code: claim.reason_code as string | null,
    });
  }
  return claims;
}

function parseEvidenceManifest(raw: unknown): AnswerEvidenceManifest | null | undefined {
  if (raw === undefined) return undefined;
  if (typeof raw !== "object" || raw === null) return null;
  const manifest = raw as Record<string, unknown>;
  if (!Array.isArray(manifest.entries) || manifest.entries.length > MAX_EVIDENCE_ENTRIES) {
    return null;
  }
  const entries: EvidenceManifestEntry[] = [];
  for (const item of manifest.entries) {
    if (typeof item !== "object" || item === null) return null;
    const entry = item as Record<string, unknown>;
    const anchors = boundedStringArray(
      entry.anchors,
      MAX_ARTIFACT_LIST_ITEMS,
      MAX_ARTIFACT_IDENTIFIER_CHARS,
    );
    const aliases = entry.aliases === undefined
      ? undefined
      : boundedStringArray(
          entry.aliases,
          MAX_ARTIFACT_LIST_ITEMS,
          MAX_ARTIFACT_IDENTIFIER_CHARS,
        );
    if (
      !boundedString(entry.ref, MAX_ARTIFACT_IDENTIFIER_CHARS) ||
      !boundedString(entry.path, MAX_ARTIFACT_IDENTIFIER_CHARS) ||
      !boundedString(entry.field, MAX_ARTIFACT_IDENTIFIER_CHARS) ||
      !boundedString(entry.kind, MAX_ARTIFACT_IDENTIFIER_CHARS) ||
      !boundedString(entry.raw_value, MAX_ARTIFACT_VALUE_CHARS) ||
      !boundedString(entry.normalized_value, MAX_ARTIFACT_VALUE_CHARS) ||
      anchors === null ||
      aliases === null
    ) return null;
    entries.push({
      ref: entry.ref,
      path: entry.path,
      field: entry.field,
      kind: entry.kind,
      raw_value: entry.raw_value,
      normalized_value: entry.normalized_value,
      anchors,
      ...(aliases === undefined ? {} : { aliases }),
    });
  }
  const sourceEntryCount = nonnegativeSafeInteger(manifest.source_entry_count);
  if (
    manifest.schema_version !== 1 ||
    !boundedString(manifest.manifest_id, MAX_ARTIFACT_IDENTIFIER_CHARS) ||
    !boundedString(manifest.authority, MAX_ARTIFACT_IDENTIFIER_CHARS) ||
    (manifest.route_id !== null &&
      !boundedString(manifest.route_id, MAX_ARTIFACT_IDENTIFIER_CHARS)) ||
    (manifest.captured_at !== null &&
      !boundedString(manifest.captured_at, MAX_ARTIFACT_IDENTIFIER_CHARS)) ||
    typeof manifest.complete !== "boolean" ||
    sourceEntryCount === null ||
    sourceEntryCount > MAX_EVIDENCE_ENTRIES ||
    sourceEntryCount < entries.length
  ) return null;
  return {
    schema_version: manifest.schema_version,
    manifest_id: manifest.manifest_id,
    authority: manifest.authority,
    route_id: manifest.route_id as string | null,
    captured_at: manifest.captured_at as string | null,
    complete: manifest.complete,
    source_entry_count: sourceEntryCount,
    entries,
  };
}

function verificationArtifactsAgree(input: {
  readonly status: AnswerVerificationStatus;
  readonly authority: string;
  readonly checksCompleted: number | null;
  readonly checksTotal: number | null;
  readonly refs: readonly string[] | null;
  readonly claims: AtomicAnswerClaim[] | null;
  readonly manifest: AnswerEvidenceManifest | null | undefined;
  readonly failedClaimIds: readonly string[];
}): boolean {
  if (
    input.checksCompleted === null ||
    input.checksTotal === null ||
    input.refs === null ||
    input.claims === null ||
    input.manifest === null
  ) return false;
  if (new Set(input.refs).size !== input.refs.length) return false;
  if (input.status !== "unverified" && input.checksCompleted !== input.checksTotal) return false;
  const claimIds = new Set(input.claims.map((claim) => claim.claim_id));
  const actualFailedClaimIds = input.claims
    .filter((claim) => claim.status !== "supported")
    .map((claim) => claim.claim_id);
  if (claimIds.size !== input.claims.length) return false;
  if (new Set(input.failedClaimIds).size !== input.failedClaimIds.length) return false;
  if (!sameStringSet(input.failedClaimIds, actualFailedClaimIds)) return false;
  if (input.claims.some((claim) => new Set(claim.evidence_refs).size !== claim.evidence_refs.length)) {
    return false;
  }
  if (input.claims.length > 0) {
    const supported = input.claims.length - actualFailedClaimIds.length;
    if (
      input.authority !== "ontology-query" &&
      (input.checksTotal !== input.claims.length || input.checksCompleted !== supported)
    ) return false;
  }
  if (input.manifest === undefined) return true;
  if (input.authority !== input.manifest.authority) return false;
  const manifestRefs = new Set(input.manifest.entries.map((entry) => entry.ref));
  if (manifestRefs.size !== input.manifest.entries.length) return false;
  const claimRefs = new Set(input.claims.flatMap((claim) => claim.evidence_refs));
  if ([...claimRefs].some((ref) => !manifestRefs.has(ref))) return false;
  return [...manifestRefs].every((ref) => claimRefs.has(ref));
}

function sameStringSet(left: readonly string[], right: readonly string[]): boolean {
  if (left.length !== right.length) return false;
  const rightSet = new Set(right);
  return left.every((value) => rightSet.has(value));
}

function nonnegativeSafeInteger(raw: unknown): number | null {
  return typeof raw === "number" && Number.isSafeInteger(raw) && raw >= 0 ? raw : null;
}

function boundedString(raw: unknown, maxChars: number): raw is string {
  return typeof raw === "string" && raw.length <= maxChars;
}

function nonemptyBoundedString(raw: unknown, maxChars: number): raw is string {
  return boundedString(raw, maxChars) && raw.length > 0;
}

function boundedStringArray(
  raw: unknown,
  maxItems: number,
  maxChars: number,
): string[] | null {
  if (!Array.isArray(raw) || raw.length > maxItems) return null;
  return raw.every((item) => boundedString(item, maxChars)) ? raw : null;
}

export function extractString(payload: unknown, key: string): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === "string" ? value : null;
}

export function extractNumber(payload: unknown, key: string): number | null {
  if (typeof payload !== "object" || payload === null) return null;
  const value = (payload as Record<string, unknown>)[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function totalTokensOf(raw: unknown): number | null {
  if (typeof raw !== "object" || raw === null) return null;
  const usage = raw as Record<string, unknown>;
  const total = usage.total_tokens;
  if (typeof total === "number" && Number.isFinite(total) && total >= 0) {
    return Math.round(total);
  }
  const prompt = usage.prompt_tokens;
  const completion = usage.completion_tokens;
  if (
    typeof prompt === "number" &&
    Number.isFinite(prompt) &&
    prompt >= 0 &&
    typeof completion === "number" &&
    Number.isFinite(completion) &&
    completion >= 0
  ) {
    return Math.round(prompt + completion);
  }
  return null;
}

export function parseModelUsage(raw: unknown): ModelUsage | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const usage = raw as Record<string, unknown>;
  const total = totalTokensOf(raw);
  if (total === null) return undefined;
  const prompt = usage.prompt_tokens;
  const completion = usage.completion_tokens;
  return {
    total_tokens: total,
    ...(typeof prompt === "number" && Number.isSafeInteger(prompt) && prompt >= 0
      ? { prompt_tokens: prompt }
      : {}),
    ...(typeof completion === "number" && Number.isSafeInteger(completion) && completion >= 0
      ? { completion_tokens: completion }
      : {}),
  };
}

export function tokenSuffix(usage: unknown): string {
  if (!readConsolePreferences().showTokenUsage) return "";
  const total = totalTokensOf(usage);
  if (total === null) return "";
  const label =
    total >= 1000 ? `${(total / 1000).toFixed(total >= 10000 ? 0 : 1)}k` : `${total}`;
  return ` · ${label} tok`;
}
const SEMANTIC_DIRECT_RESPONSE_SOURCE = "semantic-direct-response";

export function isSemanticDirectResponseSource(source: unknown): source is string {
  return typeof source === "string" && (
    source === SEMANTIC_DIRECT_RESPONSE_SOURCE ||
    source.startsWith(`${SEMANTIC_DIRECT_RESPONSE_SOURCE} · `)
  );
}

export function semanticDirectResponseSource(
  model: string,
  latencyMs: number | null,
  usage: unknown,
): string {
  const modelSuffix = model !== "llm" ? ` · ${model}` : "";
  const latencySuffix = latencyMs !== null && latencyMs >= 0 ? ` · ${latencyMs}ms` : "";
  return `${SEMANTIC_DIRECT_RESPONSE_SOURCE}${modelSuffix}${latencySuffix}${tokenSuffix(usage)}`;
}

export function parseRouter(raw: unknown): RouterSnapshot | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const record = raw as Record<string, unknown>;
  const chose = typeof record.chose === "string" ? record.chose : null;
  if (chose === null) return undefined;
  const reason = typeof record.reason === "string" ? record.reason : "";
  const candidates = parseRouterCandidates(record.candidates);
  const visionRecord = typeof record.vision === "object" && record.vision !== null
    ? record.vision as Record<string, unknown>
    : null;
  const visionChose = typeof visionRecord?.chose === "string" ? visionRecord.chose : null;
  const vision = visionRecord
    ? {
        available: visionRecord.available === true,
        chose: visionChose,
        candidates: parseRouterCandidates(visionRecord.candidates),
      }
    : undefined;
  return { chose, reason, candidates, ...(vision ? { vision } : {}) };
}

function parseRouterCandidates(raw: unknown): RouterCandidate[] {
  const rawCandidates = Array.isArray(raw) ? raw : [];
  const candidates: RouterCandidate[] = [];
  for (const candidate of rawCandidates) {
    if (typeof candidate !== "object" || candidate === null) continue;
    const candidateRecord = candidate as Record<string, unknown>;
    const deployment =
      typeof candidateRecord.deployment === "string" ? candidateRecord.deployment : null;
    if (deployment === null) continue;
    const p50 =
      typeof candidateRecord.p50_ms === "number" && Number.isFinite(candidateRecord.p50_ms)
        ? candidateRecord.p50_ms
        : null;
    const p95 =
      typeof candidateRecord.p95_ms === "number" && Number.isFinite(candidateRecord.p95_ms)
        ? candidateRecord.p95_ms
        : null;
    const samples =
      typeof candidateRecord.samples === "number" && Number.isFinite(candidateRecord.samples)
        ? candidateRecord.samples
        : 0;
    const historyRaw = Array.isArray(candidateRecord.history_ms)
      ? candidateRecord.history_ms
      : [];
    const history: number[] = [];
    for (const item of historyRaw) {
      if (typeof item === "number" && Number.isFinite(item) && item >= 0) history.push(item);
    }
    candidates.push({ deployment, p50_ms: p50, p95_ms: p95, samples, history_ms: history });
  }
  return candidates;
}
