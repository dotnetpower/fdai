import type { EvidenceBranch, InvestigationActivity, InvestigationMilestone } from "./backend";
import { isSemanticDirectResponseSource } from "./backend-normalizers";
import type { Turn } from "./command-deck-presenters";

export interface ConversationTrajectory {
  readonly question: Turn;
  readonly answer: Turn;
  readonly observedTurns: readonly Turn[];
  readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[];
  readonly milestones: readonly InvestigationMilestone[];
  readonly startedAt?: string;
  readonly completedAt?: string;
  readonly durationMs?: number;
  readonly timingSource?: "turn_timing" | "transcript";
}

export function conversationTrajectoriesByAnswer(
  turns: readonly Turn[],
): ReadonlyMap<string, ConversationTrajectory> {
  const trajectories = new Map<string, ConversationTrajectory>();
  let question: Turn | undefined;
  let observedTurns: Turn[] = [];

  for (const turn of turns) {
    if (turn.role === "operator") {
      question = turn;
      observedTurns = [];
      continue;
    }
    if (!question) continue;
    if (!isTerminalAnswer(turn)) {
      observedTurns.push(turn);
      continue;
    }

    trajectories.set(
      turn.id,
      buildTrajectory(question, turn, observedTurns),
    );
  }
  return trajectories;
}

export function conversationTrajectoriesByTurn(
  turns: readonly Turn[],
): ReadonlyMap<string, ConversationTrajectory> {
  const trajectories = new Map<string, ConversationTrajectory>();
  for (const trajectory of conversationTrajectoriesByAnswer(turns).values()) {
    trajectories.set(trajectory.answer.id, trajectory);
    for (const observed of trajectory.observedTurns) trajectories.set(observed.id, trajectory);
  }
  return trajectories;
}

function isTerminalAnswer(turn: Turn): boolean {
  return turn.role === "deck" &&
    turn.terminal === true &&
    turn.kind !== "activity" &&
    turn.source !== "investigation" &&
    turn.source !== "context" &&
    !isSemanticDirectResponseSource(turn.source);
}

function buildTrajectory(
  question: Turn,
  answer: Turn,
  observedTurns: readonly Turn[],
): ConversationTrajectory {
  const activities = mergeById(
    [
      ...(answer.trajectoryDetail?.activities ?? []),
      ...observedTurns.flatMap((turn) => turn.activities ?? []),
    ],
    (activity) => activity.activityId,
  );
  const branches = mergeById(
    [
      ...(answer.trajectoryDetail?.branches ?? []),
      ...observedTurns.flatMap((turn) => turn.branches ?? []),
    ],
    (branch) => branch.branchId,
  );
  const milestones = mergeById(
    [
      ...(answer.trajectoryDetail?.milestones ?? []),
      ...observedTurns
        .filter((turn) => turn.kind === "message" && turn.source === "investigation")
        .map((turn) => ({
          messageId: turn.id.startsWith("milestone-")
            ? turn.id.slice("milestone-".length)
            : turn.id,
          text: turn.text,
          ...(turn.agent ? { agent: turn.agent } : {}),
          ...(turn.recordedAt ? { recordedAt: turn.recordedAt } : {}),
        })),
    ],
    (milestone) => milestone.messageId,
  );
  const turnStartedAt = validTimestamp(answer.turnTiming?.started_at)
    ? answer.turnTiming.started_at
    : undefined;
  const turnCompletedAt = validTimestamp(answer.turnTiming?.completed_at)
    ? answer.turnTiming.completed_at
    : undefined;
  const turnDurationMs = answer.turnTiming?.duration_ms;
  const hasTurnTiming = turnStartedAt !== undefined &&
    turnCompletedAt !== undefined &&
    Number.isFinite(turnDurationMs) &&
    turnDurationMs !== undefined &&
    turnDurationMs >= 0 &&
    Date.parse(turnCompletedAt) >= Date.parse(turnStartedAt);
  const transcriptStartedAt = validTimestamp(question.recordedAt)
    ? question.recordedAt
    : undefined;
  const transcriptCompletedAt = validTimestamp(answer.recordedAt)
    ? answer.recordedAt
    : undefined;
  const transcriptElapsedMs = transcriptStartedAt && transcriptCompletedAt
    ? Date.parse(transcriptCompletedAt) - Date.parse(transcriptStartedAt)
    : undefined;
  const hasTranscriptTiming = transcriptElapsedMs !== undefined && transcriptElapsedMs >= 0;
  const startedAt = hasTurnTiming ? turnStartedAt : transcriptStartedAt;
  const completedAt = hasTurnTiming ? turnCompletedAt : transcriptCompletedAt;
  const durationMs = hasTurnTiming
    ? turnDurationMs
    : hasTranscriptTiming
      ? transcriptElapsedMs
      : undefined;
  const timingSource = hasTurnTiming
    ? "turn_timing" as const
    : hasTranscriptTiming
      ? "transcript" as const
      : undefined;
  return {
    question,
    answer,
    observedTurns,
    activities,
    branches,
    milestones,
    ...(startedAt ? { startedAt } : {}),
    ...(completedAt ? { completedAt } : {}),
    ...(durationMs !== undefined ? { durationMs } : {}),
    ...(timingSource ? { timingSource } : {}),
  };
}

function mergeById<T>(items: readonly T[], idFor: (item: T) => string): readonly T[] {
  const order: string[] = [];
  const merged = new Map<string, T>();
  for (const item of items) {
    const id = idFor(item);
    if (!merged.has(id)) order.push(id);
    merged.set(id, item);
  }
  return order.flatMap((id) => {
    const item = merged.get(id);
    return item === undefined ? [] : [item];
  });
}

function validTimestamp(value: string | undefined): value is string {
  return value !== undefined && Number.isFinite(Date.parse(value));
}
