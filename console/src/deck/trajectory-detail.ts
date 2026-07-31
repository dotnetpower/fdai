import type {
  EvidenceBranch,
  InvestigationActivity,
  InvestigationMilestone,
  TrajectoryDetail,
} from "./backend-types";
import {
  parseEvidenceBranch,
  parseInvestigationActivity,
  parseInvestigationMilestone,
} from "./backend-normalizers";

const MAX_DETAIL_CHARS = 64 * 1024;
const MAX_ACTIVITIES = 8;
const MAX_BRANCHES = 4;
const MAX_MILESTONES = 16;

export function parseTrajectoryDetail(raw: unknown): TrajectoryDetail | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  if (!withinDetailBound(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  if (record.schema_version !== 1 ||
      !Array.isArray(record.activities) || record.activities.length > MAX_ACTIVITIES ||
      !Array.isArray(record.branches) || record.branches.length > MAX_BRANCHES ||
      !Array.isArray(record.milestones) || record.milestones.length > MAX_MILESTONES) {
    return undefined;
  }
  const activities = record.activities.map(parseActivityShape);
  const branches = record.branches.map(parseBranchShape);
  const milestones = record.milestones.map(parseMilestoneShape);
  if (activities.some((item) => item === null) || branches.some((item) => item === null) ||
      milestones.some((item) => item === null)) return undefined;
  if (hasDuplicate(activities as InvestigationActivity[], (item) => item.activityId) ||
      hasDuplicate(branches as EvidenceBranch[], (item) => item.branchId) ||
      hasDuplicate(milestones as InvestigationMilestone[], (item) => item.messageId)) {
    return undefined;
  }
  const omitted = parseOmitted(record.omitted);
  if (!omitted || !boundedInteger(record.truncated_outputs, 0, 10_000)) return undefined;
  return {
    schema_version: 1,
    activities: activities as InvestigationActivity[],
    branches: branches as EvidenceBranch[],
    milestones: milestones as InvestigationMilestone[],
    omitted,
    truncated_outputs: record.truncated_outputs,
  };
}

function parseActivityShape(raw: unknown): InvestigationActivity | null {
  const parsed = parseInvestigationActivity(raw);
  if (parsed) {
    const record = raw as Record<string, unknown>;
    return record.execution !== undefined && parsed.execution === undefined ? null : parsed;
  }
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const normalized = parseInvestigationActivity({
    activity_id: record.activityId,
    kind: record.kind,
    status: record.status,
    label: record.label,
    agent: record.agent,
    detail: record.detail,
    completed: record.completed,
    total: record.total,
    authority: record.authority,
    observed_at: record.observedAt,
    branch_id: record.branchId,
    execution: normalizedExecutionToWire(record.execution),
  });
  return record.execution !== undefined && normalized?.execution === undefined ? null : normalized;
}

function normalizedExecutionToWire(raw: unknown): unknown {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return raw;
  const record = raw as Record<string, unknown>;
  return {
    tool: record.tool,
    command: record.command,
    input_kind: record.inputKind,
    redacted: record.redacted,
    output: record.output,
    output_truncated: record.outputTruncated,
    exit_code: record.exitCode,
    started_at: record.startedAt,
    completed_at: record.completedAt,
    duration_ms: record.durationMs,
  };
}

function parseBranchShape(raw: unknown): EvidenceBranch | null {
  const parsed = parseEvidenceBranch(raw);
  if (parsed) return parsed;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  return parseEvidenceBranch({
    branch_id: record.branchId,
    branch_kind: record.kind,
    parent_branch_id: record.parentBranchId,
    status: record.status,
    summary: record.summary,
    started_at: record.startedAt,
    completed_at: record.completedAt,
    duration_ms: record.durationMs,
    evidence_refs: record.evidenceRefs,
  });
}

function parseMilestoneShape(raw: unknown): InvestigationMilestone | null {
  const parsed = parseInvestigationMilestone(raw);
  if (parsed?.recordedAt) return parsed;
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const record = raw as Record<string, unknown>;
  const normalized = parseInvestigationMilestone({
    message_id: record.messageId,
    text: record.text,
    agent: record.agent,
    recorded_at: record.recordedAt,
  });
  return normalized?.recordedAt ? normalized : null;
}

function parseOmitted(raw: unknown): TrajectoryDetail["omitted"] | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return undefined;
  const record = raw as Record<string, unknown>;
  if (!boundedInteger(record.activities, 0, 10_000) ||
      !boundedInteger(record.branches, 0, 10_000) ||
      !boundedInteger(record.milestones, 0, 10_000)) return undefined;
  return {
    activities: record.activities,
    branches: record.branches,
    milestones: record.milestones,
  };
}

function hasDuplicate<T>(items: readonly T[], keyFor: (item: T) => string): boolean {
  return new Set(items.map(keyFor)).size !== items.length;
}

function boundedInteger(value: unknown, minimum: number, maximum: number): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) &&
    value >= minimum && value <= maximum;
}

function withinDetailBound(raw: unknown): boolean {
  try {
    return new TextEncoder().encode(JSON.stringify(raw)).length <= MAX_DETAIL_CHARS;
  } catch {
    return false;
  }
}
