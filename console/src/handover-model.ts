import { PANTHEON_NAME_SET } from "./pantheon-names";

function normalizeAgentTarget(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim();
  return PANTHEON_NAME_SET.has(normalized) ? normalized : null;
}

export interface HandoverInvitation {
  readonly invitationId: string;
  readonly goalId: string;
  readonly goalRevision: number;
  readonly agentName: string;
  readonly sessionId: string;
  readonly maxQuestions: number;
  readonly maxMinutes: number;
  readonly sourceRevision: string;
}

export interface HandoverGoal {
  readonly goalId: string;
  readonly subjectRef: string;
  readonly agentName: string;
  readonly state: string;
  readonly revision: number;
}

export function decodeHandoverInvitation(value: unknown): HandoverInvitation | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Handover invitation response is malformed.");
  }
  const invitation = (value as Record<string, unknown>).invitation;
  if (invitation === null) return null;
  if (invitation === undefined || typeof invitation !== "object" || Array.isArray(invitation)) {
    throw new Error("Handover invitation is malformed.");
  }
  const item = invitation as Record<string, unknown>;
  const agentName = normalizeAgentTarget(item.agent_name);
  if (
    typeof item.invitation_id !== "string" ||
    typeof item.goal_id !== "string" ||
    typeof item.goal_revision !== "number" ||
    !Number.isSafeInteger(item.goal_revision) ||
    item.goal_revision < 1 ||
    agentName === null ||
    typeof item.session_id !== "string" ||
    typeof item.max_questions !== "number" ||
    typeof item.max_minutes !== "number" ||
    typeof item.source_revision !== "string" ||
    item.execution_authority !== false
  ) {
    throw new Error("Handover invitation fields are malformed.");
  }
  return {
    invitationId: item.invitation_id,
    goalId: item.goal_id,
    goalRevision: item.goal_revision,
    agentName,
    sessionId: item.session_id,
    maxQuestions: item.max_questions,
    maxMinutes: item.max_minutes,
    sourceRevision: item.source_revision,
  };
}

export function decodeHandoverGoal(value: unknown): HandoverGoal {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Handover goal response is malformed.");
  }
  const goal = (value as Record<string, unknown>).goal;
  if (goal === null || typeof goal !== "object" || Array.isArray(goal)) {
    throw new Error("Handover goal is malformed.");
  }
  const item = goal as Record<string, unknown>;
  const agentName = normalizeAgentTarget(item.agent_name);
  if (
    typeof item.goal_id !== "string" ||
    typeof item.subject_ref !== "string" ||
    agentName === null ||
    typeof item.state !== "string" ||
    typeof item.revision !== "number" ||
    !Number.isSafeInteger(item.revision) ||
    item.revision < 1 ||
    item.execution_authority !== false
  ) {
    throw new Error("Handover goal fields are malformed.");
  }
  return {
    goalId: item.goal_id,
    subjectRef: item.subject_ref,
    agentName,
    state: item.state,
    revision: item.revision,
  };
}
