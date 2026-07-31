import type { EvidenceBranchStatus, InvestigationActivityStatus } from "./backend";
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

export interface TrajectoryPresentation {
  readonly phaseStates: Readonly<Record<TrajectoryPhase, TrajectoryPhaseState>>;
  readonly modelCallCount: number;
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

  return {
    phaseStates: {
      input: "completed",
      plan: trajectory.answer.answerPlan ? "completed" : "not_observed",
      collaboration: collaborationState(trajectory),
      evidence: aggregateEvidenceState(evidenceStatuses),
      verification: verificationState(trajectory),
      answer: "completed",
    },
    modelCallCount: trajectory.answer.modelTrace?.calls.length ?? 0,
    evidenceAttemptCount: evidenceStatuses.length,
    evidenceCompletedCount: evidenceStatuses.filter((status) => status === "completed").length,
    evidenceReferenceCount: evidenceReferences.size,
  };
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
