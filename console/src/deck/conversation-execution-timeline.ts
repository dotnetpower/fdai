import type { ConversationTrajectory } from "./conversation-trajectory";
import type { TrajectoryPhaseState } from "./conversation-trajectory-presentation";

const MIN_BAR_PCT = 1.5;
const SINGLETON_SPAN_MS = 1000;

export type ExecutionTimelineKind = "turn" | "phase" | "evidence" | "model";

export interface ExecutionTimelineItem {
  readonly id: string;
  readonly kind: ExecutionTimelineKind;
  readonly label: string;
  readonly detail: string;
  readonly state: TrajectoryPhaseState;
  readonly startedAt: string;
  readonly completedAt: string;
  readonly durationMs: number;
  readonly leftPct: number;
  readonly widthPct: number;
}

interface RawTimelineItem extends Omit<ExecutionTimelineItem, "leftPct" | "widthPct"> {}

export function buildExecutionTimeline(
  trajectory: ConversationTrajectory,
  options: { readonly includeModelCalls?: boolean } = {},
): readonly ExecutionTimelineItem[] {
  const items = rawItems(trajectory, options.includeModelCalls !== false)
    .filter((item) => validInterval(item.startedAt, item.completedAt))
    .sort((left, right) => Date.parse(left.startedAt) - Date.parse(right.startedAt));
  if (items.length === 0) return [];
  const startMs = Math.min(...items.map((item) => Date.parse(item.startedAt)));
  const endMs = Math.max(...items.map((item) => Date.parse(item.completedAt)));
  const actualSpanMs = Math.max(0, endMs - startMs);
  const tailMs = actualSpanMs > 0 ? actualSpanMs * 0.05 : SINGLETON_SPAN_MS;
  const denominator = actualSpanMs + tailMs;
  return items.map((item) => {
    const itemStart = Date.parse(item.startedAt);
    const leftPct = ((itemStart - startMs) / denominator) * 100;
    const rawWidth = (item.durationMs / denominator) * 100;
    return {
      ...item,
      leftPct,
      widthPct: Math.min(Math.max(rawWidth, MIN_BAR_PCT), Math.max(MIN_BAR_PCT, 100 - leftPct)),
    };
  });
}

function rawItems(
  trajectory: ConversationTrajectory,
  includeModelCalls: boolean,
): RawTimelineItem[] {
  const items: RawTimelineItem[] = [];
  if (trajectory.startedAt) {
    items.push(pointItem("turn-input", "turn", "input", "operator", trajectory.startedAt));
  }
  for (const phase of trajectory.answer.turnTiming?.phases ?? []) {
    items.push({
      id: `phase-${phase.phase}`,
      kind: "phase",
      label: phase.phase,
      detail: phase.status,
      state: phase.status,
      startedAt: phase.started_at,
      completedAt: phase.completed_at,
      durationMs: phase.duration_ms,
    });
  }
  for (const branch of trajectory.branches) {
    if (!branch.completedAt) continue;
    items.push({
      id: `evidence-${branch.branchId}`,
      kind: "evidence",
      label: branch.kind,
      detail: branch.status,
      state: branchState(branch.status),
      startedAt: branch.startedAt,
      completedAt: branch.completedAt,
      durationMs: branch.durationMs ?? Math.max(0, Date.parse(branch.completedAt) - Date.parse(branch.startedAt)),
    });
  }
  if (includeModelCalls) {
    for (const call of trajectory.answer.modelTrace?.calls ?? []) {
      if (!call.completed_at || call.duration_ms === null) continue;
      items.push({
        id: `model-${call.call_id}`,
        kind: "model",
        label: call.kind,
        detail: call.model,
        state: call.status === "completed" ? "completed" : "degraded",
        startedAt: call.started_at,
        completedAt: call.completed_at,
        durationMs: call.duration_ms,
      });
    }
  }
  if (trajectory.completedAt) {
    items.push(pointItem("turn-answer", "turn", "answer", "terminal", trajectory.completedAt));
  }
  return items;
}

function pointItem(
  id: string,
  kind: ExecutionTimelineKind,
  label: string,
  detail: string,
  at: string,
): RawTimelineItem {
  return {
    id,
    kind,
    label,
    detail,
    state: "completed",
    startedAt: at,
    completedAt: at,
    durationMs: 0,
  };
}

function branchState(status: string): TrajectoryPhaseState {
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  if (status === "pending" || status === "running") return "running";
  return "degraded";
}

function validInterval(startedAt: string, completedAt: string): boolean {
  const start = Date.parse(startedAt);
  const end = Date.parse(completedAt);
  return Number.isFinite(start) && Number.isFinite(end) && end >= start;
}
