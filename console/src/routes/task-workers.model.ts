import {
  panelArray,
  panelBoolean,
  panelContractError,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNonNegativeNumber,
  panelNullableString,
  panelRecord,
  panelString,
  panelStringArray,
} from "./panel-decode";

export type TaskWorkerLocale = "en" | "ko";
export type TaskWorkerStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "abstained"
  | "cancelled"
  | "timed_out"
  | "budget_exhausted"
  | "denied"
  | "failed";

export interface TaskWorkerBudgetProjection {
  readonly max_wall_seconds: number;
  readonly max_tool_calls: number;
  readonly max_tokens: number;
  readonly max_cost_microusd: number;
  readonly heartbeat_seconds: number;
}

export interface TaskWorkerUsageProjection {
  readonly tokens: number;
  readonly cost_microusd: number;
  readonly tool_calls: number;
  readonly reserved_tokens: number;
  readonly reserved_cost_microusd: number;
  readonly complete: boolean;
}

export interface TaskWorkerListRowProjection {
  readonly worker_id: string;
  readonly parent_trace_ref: string;
  readonly status: TaskWorkerStatus;
  readonly budget: TaskWorkerBudgetProjection;
  readonly created_at: string;
  readonly updated_at: string;
  readonly heartbeat_at: string | null;
  readonly allowed_tools: readonly string[];
  readonly denied_tools: readonly string[];
  readonly evidence_count: number;
  readonly usage: TaskWorkerUsageProjection;
  readonly terminal_reason: string | null;
  readonly trusted: false;
  readonly read_only: true;
  readonly execution_authority: "none";
}

export interface TaskWorkerResultProjection {
  readonly worker_id: string;
  readonly parent_trace_ref: string;
  readonly status: TaskWorkerStatus;
  readonly summary: string | null;
  readonly summary_truncated: boolean;
  readonly evidence_refs: readonly string[];
  readonly caveats: readonly string[];
  readonly usage: TaskWorkerUsageProjection;
  readonly terminal_reason: string;
  readonly started_at: string;
  readonly finished_at: string;
  readonly trusted: false;
}

export interface TaskWorkerDetailProjection {
  readonly read_only: true;
  readonly execution_authority: "none";
  readonly worker: TaskWorkerListRowProjection & {
    readonly evidence_refs: readonly string[];
    readonly result: TaskWorkerResultProjection | null;
  };
}

export interface TaskWorkerEventProjection {
  readonly worker_id: string;
  readonly sequence: number;
  readonly kind: string;
  readonly at: string;
  readonly details: readonly (readonly [string, string])[];
}

export interface TaskWorkerListProjection {
  readonly read_only: true;
  readonly execution_authority: "none";
  readonly workers: readonly TaskWorkerListRowProjection[];
}

export interface TaskWorkerEventsProjection {
  readonly read_only: true;
  readonly execution_authority: "none";
  readonly worker_id: string;
  readonly events: readonly TaskWorkerEventProjection[];
}

export interface TaskWorkerCardViewModel {
  readonly workerId: string;
  readonly parentTraceRef: string;
  readonly status: TaskWorkerStatus;
  readonly statusLabel: string;
  readonly untrustedBadgeLabel: string;
  readonly usageStatusLabel: string;
  readonly allowedToolCount: number;
  readonly deniedToolCount: number;
  readonly evidenceCount: number;
  readonly terminalReason: string | null;
}

export interface TaskWorkersViewModel {
  readonly locale: TaskWorkerLocale;
  readonly readOnly: true;
  readonly executionAuthority: "none";
  readonly canCreateWorker: false;
  readonly canCancelWorker: false;
  readonly canApproveOrExecute: false;
  readonly title: string;
  readonly subtitle: string;
  readonly untrustedNotice: string;
  readonly activeWorkerCount: number;
  readonly terminalWorkerCount: number;
  readonly workers: readonly TaskWorkerCardViewModel[];
  readonly selectedSummary: string | null;
  readonly deliveryFailedEventCount: number;
}

export type TaskWorkerListViewModel = TaskWorkersViewModel;

const VALID_STATUSES = new Set<TaskWorkerStatus>([
  "pending", "running", "succeeded", "abstained", "cancelled",
  "timed_out", "budget_exhausted", "denied", "failed",
]);

const COPY: Record<
  TaskWorkerLocale,
  {
    readonly title: string;
    readonly subtitle: string;
    readonly untrustedNotice: string;
    readonly untrustedBadge: string;
    readonly usageComplete: string;
    readonly usageIncomplete: string;
    readonly statuses: Record<TaskWorkerStatus, string>;
  }
> = {
  en: {
    title: "Bounded Task Workers",
    subtitle: "Owner-scoped, read-only investigation worker snapshots and branch events.",
    untrustedNotice:
      "Worker outputs remain untrusted contributions with no approval or execution authority.",
    untrustedBadge: "Untrusted contribution",
    usageComplete: "Measured usage complete",
    usageIncomplete: "Unresolved usage reservation",
    statuses: {
      pending: "Pending", running: "Running", succeeded: "Succeeded",
      abstained: "Abstained", cancelled: "Cancelled", timed_out: "Timed out",
      budget_exhausted: "Budget exhausted", denied: "Denied", failed: "Failed",
    },
  },
  ko: {
    title: "제한형 작업 워커",
    subtitle: "소유자 범위로 제한된 읽기 전용 조사 워커 스냅샷 및 브랜치 이벤트입니다.",
    untrustedNotice:
      "워커 출력은 승인 또는 실행 권한이 없는 신뢰되지 않은 보조 자료로 유지됩니다.",
    untrustedBadge: "신뢰되지 않은 워커 결과",
    usageComplete: "측정된 사용량 확정",
    usageIncomplete: "미확정 예약 사용량 포함",
    statuses: {
      pending: "대기 중", running: "실행 중", succeeded: "성공",
      abstained: "보류", cancelled: "취소됨", timed_out: "시간 초과",
      budget_exhausted: "예산 소진", denied: "거부됨", failed: "실패",
    },
  },
};

function requireReadOnlyRoot(
  root: Readonly<Record<string, unknown>>,
  label: string,
): void {
  if (panelBoolean(root, "read_only", label) !== true) {
    throw panelContractError(`${label}.read_only MUST be true`);
  }
  if (panelString(root, "execution_authority", label) !== "none") {
    throw panelContractError(`${label}.execution_authority MUST be none`);
  }
}

function decodeStatus(value: string, label: string): TaskWorkerStatus {
  if (!VALID_STATUSES.has(value as TaskWorkerStatus)) {
    throw panelContractError(`${label} status ${value} is invalid`);
  }
  return value as TaskWorkerStatus;
}

function decodeUsage(value: unknown, label: string): TaskWorkerUsageProjection {
  const rec = panelRecord(value, label);
  return {
    tokens: panelNonNegativeInteger(rec, "tokens", label),
    cost_microusd: panelNonNegativeInteger(rec, "cost_microusd", label),
    tool_calls: panelNonNegativeInteger(rec, "tool_calls", label),
    reserved_tokens:
      rec.reserved_tokens === undefined ? 0 : panelNonNegativeInteger(rec, "reserved_tokens", label),
    reserved_cost_microusd:
      rec.reserved_cost_microusd === undefined
        ? 0
        : panelNonNegativeInteger(rec, "reserved_cost_microusd", label),
    complete: rec.complete === undefined ? true : panelBoolean(rec, "complete", label),
  };
}

function decodeBudget(value: unknown, label: string): TaskWorkerBudgetProjection {
  const rec = panelRecord(value, label);
  return {
    max_wall_seconds: panelNonNegativeNumber(rec, "max_wall_seconds", label),
    max_tool_calls: panelNonNegativeInteger(rec, "max_tool_calls", label),
    max_tokens: panelNonNegativeInteger(rec, "max_tokens", label),
    max_cost_microusd: panelNonNegativeInteger(rec, "max_cost_microusd", label),
    heartbeat_seconds: panelNonNegativeNumber(rec, "heartbeat_seconds", label),
  };
}

function decodeWorkerRow(
  value: unknown,
  label: string,
  forbidGoalAndConstraints: boolean,
): TaskWorkerListRowProjection {
  const row = panelRecord(value, label);
  if (forbidGoalAndConstraints && ("goal" in row || "constraints" in row)) {
    throw panelContractError(`${label} MUST NOT expose goal or constraints in list rows`);
  }
  if (panelBoolean(row, "trusted", label) !== false) {
    throw panelContractError(`${label}.trusted MUST be false`);
  }
  requireReadOnlyRoot(row, label);
  return {
    worker_id: panelNonEmptyString(row, "worker_id", label),
    parent_trace_ref: panelNonEmptyString(row, "parent_trace_ref", label),
    status: decodeStatus(panelNonEmptyString(row, "status", label), label),
    budget: decodeBudget(row.budget, `${label}.budget`),
    created_at: panelNonEmptyString(row, "created_at", label),
    updated_at: panelNonEmptyString(row, "updated_at", label),
    heartbeat_at: panelNullableString(row, "heartbeat_at", label),
    allowed_tools: panelStringArray(row.allowed_tools, `${label}.allowed_tools`),
    denied_tools: panelStringArray(row.denied_tools, `${label}.denied_tools`),
    evidence_count: panelNonNegativeInteger(row, "evidence_count", label),
    usage: decodeUsage(row.usage, `${label}.usage`),
    terminal_reason: panelNullableString(row, "terminal_reason", label),
    trusted: false,
    read_only: true,
    execution_authority: "none",
  };
}

export function decodeTaskWorkerListProjection(value: unknown): TaskWorkerListProjection {
  const root = panelRecord(value, "TaskWorkerListProjection");
  requireReadOnlyRoot(root, "TaskWorkerListProjection");
  const seenWorkerIds = new Set<string>();
  const workers = panelArray(root.workers, "TaskWorkerListProjection.workers").map(
    (entry, idx) => {
      const row = decodeWorkerRow(entry, `TaskWorkerListProjection.workers[${idx}]`, true);
      if (seenWorkerIds.has(row.worker_id)) {
        throw panelContractError(
          `TaskWorkerListProjection.workers[${idx}] has duplicate worker_id ${row.worker_id}`,
        );
      }
      seenWorkerIds.add(row.worker_id);
      return row;
    },
  );
  return {
    read_only: true,
    execution_authority: "none",
    workers,
  };
}

export const decodeTaskWorkerList = decodeTaskWorkerListProjection;

export function decodeTaskWorkerDetailProjection(value: unknown): TaskWorkerDetailProjection {
  const root = panelRecord(value, "TaskWorkerDetailProjection");
  requireReadOnlyRoot(root, "TaskWorkerDetailProjection");
  const workerRec = panelRecord(root.worker, "TaskWorkerDetailProjection.worker");
  const base = decodeWorkerRow(workerRec, "TaskWorkerDetailProjection.worker", true);
  const evidenceRefs = panelStringArray(
    workerRec.evidence_refs,
    "TaskWorkerDetailProjection.worker.evidence_refs",
  );
  let result: TaskWorkerResultProjection | null = null;
  if (workerRec.result !== null && workerRec.result !== undefined) {
    const resLabel = "TaskWorkerDetailProjection.worker.result";
    const resRec = panelRecord(workerRec.result, resLabel);
    if (panelBoolean(resRec, "trusted", resLabel) !== false) {
      throw panelContractError(`${resLabel}.trusted MUST be false`);
    }
    const summaryTruncated =
      resRec.summary_truncated === undefined
        ? false
        : panelBoolean(resRec, "summary_truncated", resLabel);
    result = {
      worker_id: panelNonEmptyString(resRec, "worker_id", resLabel),
      parent_trace_ref: panelNonEmptyString(resRec, "parent_trace_ref", resLabel),
      status: decodeStatus(panelNonEmptyString(resRec, "status", resLabel), resLabel),
      summary: panelNullableString(resRec, "summary", resLabel),
      summary_truncated: summaryTruncated,
      evidence_refs: panelStringArray(resRec.evidence_refs, `${resLabel}.evidence_refs`),
      caveats: panelStringArray(resRec.caveats, `${resLabel}.caveats`),
      usage: decodeUsage(resRec.usage, `${resLabel}.usage`),
      terminal_reason: panelNonEmptyString(resRec, "terminal_reason", resLabel),
      started_at: panelNonEmptyString(resRec, "started_at", resLabel),
      finished_at: panelNonEmptyString(resRec, "finished_at", resLabel),
      trusted: false,
    };
  }
  return {
    read_only: true,
    execution_authority: "none",
    worker: { ...base, evidence_refs: evidenceRefs, result },
  };
}

export const decodeTaskWorkerDetail = decodeTaskWorkerDetailProjection;

export function decodeTaskWorkerEventsProjection(value: unknown): TaskWorkerEventsProjection {
  const root = panelRecord(value, "TaskWorkerEventsProjection");
  requireReadOnlyRoot(root, "TaskWorkerEventsProjection");
  const workerId = panelNonEmptyString(root, "worker_id", "TaskWorkerEventsProjection");
  const events = panelArray(root.events, "TaskWorkerEventsProjection.events").map((entry, idx) => {
    const label = `TaskWorkerEventsProjection.events[${idx}]`;
    const row = panelRecord(entry, label);
    const details = panelArray(row.details, `${label}.details`).map((pair, pairIdx) => {
      const pairArr = panelArray(pair, `${label}.details[${pairIdx}]`);
      if (pairArr.length !== 2 || typeof pairArr[0] !== "string" || typeof pairArr[1] !== "string") {
        throw panelContractError(`${label}.details[${pairIdx}] MUST be a [key, value] string pair`);
      }
      return [pairArr[0], pairArr[1]] as const;
    });
    return {
      worker_id: panelNonEmptyString(row, "worker_id", label),
      sequence: panelNonNegativeInteger(row, "sequence", label),
      kind: panelNonEmptyString(row, "kind", label),
      at: panelNonEmptyString(row, "at", label),
      details,
    };
  });
  return { read_only: true, execution_authority: "none", worker_id: workerId, events };
}

export function buildTaskWorkersViewModel(
  list: TaskWorkerListProjection,
  locale: TaskWorkerLocale = "en",
  detail: TaskWorkerDetailProjection | null = null,
  events: TaskWorkerEventsProjection | null = null,
): TaskWorkersViewModel {
  const copy = COPY[locale];
  const cards: TaskWorkerCardViewModel[] = list.workers.map((row) => ({
    workerId: row.worker_id,
    parentTraceRef: row.parent_trace_ref,
    status: row.status,
    statusLabel: copy.statuses[row.status],
    untrustedBadgeLabel: copy.untrustedBadge,
    usageStatusLabel: row.usage.complete ? copy.usageComplete : copy.usageIncomplete,
    allowedToolCount: row.allowed_tools.length,
    deniedToolCount: row.denied_tools.length,
    evidenceCount: row.evidence_count,
    terminalReason: row.terminal_reason,
  }));

  const activeWorkerCount = cards.filter(
    (card) => card.status === "pending" || card.status === "running",
  ).length;
  const terminalWorkerCount = cards.length - activeWorkerCount;

  const deliveryFailedEventCount =
    events === null
      ? 0
      : events.events.filter((ev) => ev.kind === "worker.completion_delivery_failed").length;

  return {
    locale,
    readOnly: true,
    executionAuthority: "none",
    canCreateWorker: false,
    canCancelWorker: false,
    canApproveOrExecute: false,
    title: copy.title,
    subtitle: copy.subtitle,
    untrustedNotice: copy.untrustedNotice,
    activeWorkerCount,
    terminalWorkerCount,
    workers: cards,
    selectedSummary: detail?.worker.result?.summary ?? null,
    deliveryFailedEventCount,
  };
}
