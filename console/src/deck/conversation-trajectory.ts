import type { EvidenceBranch, InvestigationActivity } from "./backend";
import type { Turn } from "./command-deck-presenters";

export interface ConversationTrajectory {
  readonly question: Turn;
  readonly answer: Turn;
  readonly observedTurns: readonly Turn[];
  readonly activities: readonly InvestigationActivity[];
  readonly branches: readonly EvidenceBranch[];
  readonly startedAt?: string;
  readonly completedAt?: string;
  readonly durationMs?: number;
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

function isTerminalAnswer(turn: Turn): boolean {
  return turn.role === "deck" &&
    turn.terminal === true &&
    turn.kind !== "activity" &&
    turn.source !== "investigation" &&
    turn.source !== "context";
}

function buildTrajectory(
  question: Turn,
  answer: Turn,
  observedTurns: readonly Turn[],
): ConversationTrajectory {
  const activities = mergeById(
    observedTurns.flatMap((turn) => turn.activities ?? []),
    (activity) => activity.activityId,
  );
  const branches = mergeById(
    observedTurns.flatMap((turn) => turn.branches ?? []),
    (branch) => branch.branchId,
  );
  const startedAt = validTimestamp(question.recordedAt) ? question.recordedAt : undefined;
  const completedAt = validTimestamp(answer.recordedAt) ? answer.recordedAt : undefined;
  const elapsedMs = startedAt && completedAt
    ? Date.parse(completedAt) - Date.parse(startedAt)
    : undefined;
  const durationMs = elapsedMs !== undefined && elapsedMs >= 0 ? elapsedMs : undefined;
  return {
    question,
    answer,
    observedTurns,
    activities,
    branches,
    ...(startedAt ? { startedAt } : {}),
    ...(completedAt ? { completedAt } : {}),
    ...(durationMs !== undefined ? { durationMs } : {}),
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
