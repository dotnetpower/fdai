import type {
  EvidenceBranch,
  EvidenceBranchStatus,
  InvestigationActivity,
  InvestigationActivityStatus,
  WorkProgressShape,
} from "./backend-types";
import type { ConversationTrajectory } from "./conversation-trajectory";

export const TRAJECTORY_PHASES = [
  "input",
  "plan",
  "collaboration",
  "evidence",
  "verification",
  "answer",
] as const;

export type TrajectoryPhase = typeof TRAJECTORY_PHASES[number];
export type TrajectoryPhaseState =
  | "completed"
  | "corrected"
  | "degraded"
  | "failed"
  | "running"
  | "unverified"
  | "not_observed";

export type WorkProgressPresentation = "none" | "compact" | "timeline";

export interface TrajectoryPresentation {
  readonly workProgress: WorkProgressPresentation;
  readonly phaseStates: Readonly<Record<TrajectoryPhase, TrajectoryPhaseState>>;
  readonly modelCallCount: number;
  readonly modelCallCountIsLowerBound: boolean;
  readonly modelCallCountRecorded: boolean;
  readonly modelLatencyMs?: number;
  readonly totalTokens?: number;
  readonly inputTokens?: number;
  readonly outputTokens?: number;
  readonly evidenceAttemptCount: number;
  readonly evidenceCompletedCount: number;
  readonly evidenceReferenceCount: number;
}

export function buildTrajectoryPresentation(
  trajectory: ConversationTrajectory,
): TrajectoryPresentation {
  const evidenceStatuses = uniqueEvidenceStatuses(trajectory);
  const evidenceReferences = new Set([
    ...trajectory.branches.flatMap((branch) => branch.evidenceRefs),
    ...(trajectory.answer.verification?.evidence_refs ?? []),
  ]);

  const recordedModelCalls = trajectory.answer.modelTrace
    ? trajectory.answer.modelTrace.calls.length + trajectory.answer.modelTrace.omitted_calls
    : 0;
  const budgetCalls = trajectory.turnBudget?.complete ? trajectory.turnBudget.model_calls.used : 0;
  const accountedCalls = trajectory.answer.modelUsage?.model_calls;
  const modelCallCountRecorded = trajectory.answer.modelTrace !== undefined ||
    trajectory.turnBudget?.complete === true || accountedCalls !== undefined;
  const modelBacked = trajectory.answer.source?.startsWith("llm:") === true;
  return {
    workProgress: workProgressPresentation(trajectory),
    phaseStates: {
      input: "completed",
      plan: trajectory.answer.answerPlan ? "completed" : "not_observed",
      collaboration: collaborationState(trajectory),
      evidence: aggregateEvidenceState(evidenceStatuses),
      verification: verificationState(trajectory),
      answer: "completed",
    },
    modelCallCount: modelCallCountRecorded
      ? Math.max(recordedModelCalls, budgetCalls, accountedCalls ?? 0) : modelBacked ? 1 : 0,
    modelCallCountIsLowerBound: modelBacked && !modelCallCountRecorded,
    modelCallCountRecorded,
    ...(
      trajectory.answer.modelLatencyMs !== undefined
        ? { modelLatencyMs: trajectory.answer.modelLatencyMs }
        : {}
    ),
    ...(trajectory.answer.modelUsage
      ? {
        totalTokens: trajectory.answer.modelUsage.total_tokens,
        ...(trajectory.answer.modelUsage.prompt_tokens !== undefined
          ? { inputTokens: trajectory.answer.modelUsage.prompt_tokens } : {}),
        ...(trajectory.answer.modelUsage.completion_tokens !== undefined
          ? { outputTokens: trajectory.answer.modelUsage.completion_tokens } : {}),
      }
      : {}),
    evidenceAttemptCount: evidenceStatuses.length,
    evidenceCompletedCount: evidenceStatuses.filter((status) => status === "completed").length,
    evidenceReferenceCount: evidenceReferences.size,
  };
}

export function workProgressPresentation(
  trajectory: ConversationTrajectory,
): WorkProgressPresentation {
  const activities = trajectory.activities.filter((activity) => !isModelCallStep(activity));
  const observedCount = activities.length + unrepresentedBranchCount(
    activities,
    trajectory.branches,
  );
  if (observedCount === 0 && trajectory.milestones.length === 0) return "none";
  return compactQueryRead({
    activities,
    branches: trajectory.branches,
    milestoneCount: trajectory.milestones.length,
    ...(trajectory.workProgressShape ? { shape: trajectory.workProgressShape } : {}),
  }) ? "compact" : "timeline";
}

/**
 * Operator reports the semantic turn's own lifecycle (evidence executed, verified, answer prepared)
 * as `semantic_turn` steps without an execution record. They state workflow facts, not reads, so
 * they don't change the density while they settle normally.
 */
function isSemanticLifecycleStep(activity: InvestigationActivity): boolean {
  return activity.kind === "semantic_turn" && activity.execution === undefined;
}

/**
 * Operator streams each planning model call as a live-only `model_call` step. It shows the wait,
 * not a read, so it never selects the density or counts as observed work.
 */
export function isModelCallStep(activity: InvestigationActivity): boolean {
  return activity.kind === "model_call";
}

/**
 * Returns the turn's one query read when the work is compact, otherwise undefined.
 *
 * A server-pinned shape holds only while the observations agree with it. A procedural pin always
 * shows the timeline. A compact pin keeps one query read compact while it is still pending or
 * running, so the density doesn't flip on completion; without a pin only a completed read is
 * compact. A failed, unavailable, or command read, a second read or other step, an unrepresented
 * branch, any milestone, or a lifecycle step that didn't settle normally falls back to the timeline.
 */
function compactQueryRead({
  activities,
  branches,
  milestoneCount,
  shape,
}: {
  readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[];
  readonly milestoneCount: number;
  readonly shape?: WorkProgressShape;
}): InvestigationActivity | undefined {
  if (shape?.density === "procedural" || milestoneCount > 0) return undefined;
  if (unrepresentedBranchCount(activities, branches) > 0) return undefined;
  const lifecycle = activities.filter(isSemanticLifecycleStep);
  if (lifecycle.some((step) => !LIFECYCLE_SETTLED_NORMALLY.has(step.status))) return undefined;
  const work = activities.filter((activity) => !isSemanticLifecycleStep(activity));
  const read = work[0];
  if (work.length !== 1 || read?.execution?.inputKind !== "query") return undefined;
  if (shape) return read.status !== "failed" && read.status !== "unavailable" ? read : undefined;
  return read.status === "completed" ? read : undefined;
}

const LIFECYCLE_SETTLED_NORMALLY: ReadonlySet<InvestigationActivityStatus> = new Set([
  "pending",
  "running",
  "completed",
]);

function unrepresentedBranchCount(
  activities: readonly InvestigationActivity[],
  branches: readonly EvidenceBranch[],
): number {
  const representedBranchIds = new Set(
    activities.flatMap((activity) =>
      activity.execution && activity.branchId ? [activity.branchId] : []),
  );
  return branches.filter((branch) => !representedBranchIds.has(branch.branchId)).length;
}

function collaborationState(trajectory: ConversationTrajectory): TrajectoryPhaseState {
  const planning = trajectory.answer.answerPlanning;
  if (planning?.status === "completed" || trajectory.answer.delegation) return "completed";
  if (planning?.status === "degraded" || planning?.status === "timed_out") return "degraded";
  if (planning?.status === "skipped") return "not_observed";
  return "not_observed";
}

function verificationState(trajectory: ConversationTrajectory): TrajectoryPhaseState {
  const status = trajectory.answer.verification?.status;
  if (status === "verified" || status === "consistent") return "completed";
  if (status === "corrected") return "corrected";
  if (status === "unverified") return "unverified";
  return "not_observed";
}

function uniqueEvidenceStatuses(
  trajectory: ConversationTrajectory,
): readonly (EvidenceBranchStatus | InvestigationActivityStatus)[] {
  const branchIds = new Set(trajectory.branches.map((branch) => branch.branchId));
  const standaloneActivities = trajectory.activities.filter(
    (activity) => activity.branchId === undefined || !branchIds.has(activity.branchId),
  );
  return [
    ...trajectory.branches.map((branch) => branch.status),
    ...standaloneActivities.map((activity) => activity.status),
  ];
}

function aggregateEvidenceState(
  statuses: readonly (EvidenceBranchStatus | InvestigationActivityStatus)[],
): TrajectoryPhaseState {
  if (statuses.length === 0) return "not_observed";
  if (statuses.some((status) => status === "pending" || status === "running")) return "running";
  const completed = statuses.some((status) => status === "completed");
  const failed = statuses.some((status) => status === "failed");
  const degraded = statuses.some(
    (status) => status === "unavailable" || status === "timed_out" || status === "cancelled",
  );
  if (completed && (failed || degraded)) return "degraded";
  if (completed) return "completed";
  if (failed) return "failed";
  if (degraded) return "degraded";
  return "not_observed";
}
