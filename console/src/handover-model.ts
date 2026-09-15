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
  readonly slots: readonly HandoverEvidenceSlot[];
  readonly highImpact: boolean | null;
  readonly ownerReviewed: boolean;
  readonly backupReviewed: boolean;
  readonly allowedOperations: readonly string[];
  readonly legacyState: string | null;
  readonly sourceRevision: string | null;
  readonly scopeRef: string | null;
}

/** Stable checklist vocabulary; labels are localized and never grant authority. */
export const HANDOVER_SLOTS = [
  "scope_exclusions", "decision_triggers", "runbook_rollback",
  "dependencies_escalation", "failure_risks", "source_governance",
] as const;
export type HandoverSlot = typeof HANDOVER_SLOTS[number];
export interface HandoverEvidenceSlot {
  readonly slot: HandoverSlot;
  readonly evidenceRef: string | null;
  readonly reasonRef: string | null;
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
    !Number.isSafeInteger(item.max_questions) || item.max_questions < 1 || item.max_questions > 3 ||
    !Number.isSafeInteger(item.max_minutes) || item.max_minutes < 1 || item.max_minutes > 5 ||
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
  if (!["not_started", "in_progress", "blocked", "ready_for_review", "accepted", "stale", "declined", "superseded"].includes(item.state)) {
    throw new Error("Handover goal state is unsupported.");
  }
  const slots = decodeGoalSlots(item);
  const review = (value: unknown): boolean => {
    if (value === null || value === undefined) return false;
    if (typeof value !== "object" || Array.isArray(value)) throw new Error("Handover review is malformed.");
    const record = value as Record<string, unknown>;
    if (typeof record.reviewer_ref !== "string" || !record.reviewer_ref.trim() ||
      record.reviewer_ref !== record.reviewer_ref.trim() || /\s/.test(record.reviewer_ref) ||
      record.reviewer_ref.toLowerCase() === String(item.subject_ref).trim().toLowerCase() ||
        typeof record.evidence_digest !== "string" || !/^[a-f0-9]{64}$/.test(record.evidence_digest) ||
      typeof record.goal_revision !== "number" || !Number.isSafeInteger(record.goal_revision) || record.goal_revision < 1 ||
      record.goal_revision >= Number(item.revision) || typeof record.reviewed_at !== "string" ||
      !/(Z|[+-]\d{2}:\d{2})$/.test(record.reviewed_at) || !Number.isFinite(Date.parse(record.reviewed_at))) {
      throw new Error("Handover review is malformed.");
    }
    return true;
  };
  const ownerReviewed = review(item.owner_review);
  const backupReviewed = review(item.backup_review);
  if (ownerReviewed && backupReviewed) {
    const owner = item.owner_review as Record<string, unknown>;
    const backup = item.backup_review as Record<string, unknown>;
    if (String(owner.reviewer_ref).trim().toLowerCase() === String(backup.reviewer_ref).trim().toLowerCase() ||
        owner.evidence_digest !== backup.evidence_digest) throw new Error("Handover reviews are not independent or aligned.");
  }
  const highImpact = typeof item.high_impact === "boolean" ? item.high_impact : null;
  if (item.state === "accepted" && (slots.length !== 6 || slots.some((slot) => !slot.evidenceRef && !slot.reasonRef) ||
      highImpact === null || !ownerReviewed || (highImpact && !backupReviewed))) {
    throw new Error("Accepted handover goal has incomplete evidence or reviews.");
  }
  const operations = item.allowed_operations ?? [];
  if (!Array.isArray(operations) || operations.some((op) => !["evidence", "not-applicable", "reuse", "snooze", "decline", "accept", "acknowledge"].includes(op))) {
    throw new Error("Handover goal operations are malformed.");
  }
  return {
    goalId: item.goal_id,
    subjectRef: item.subject_ref,
    agentName,
    state: item.state,
    revision: item.revision,
    slots, highImpact, ownerReviewed, backupReviewed, allowedOperations: operations,
    legacyState: typeof item.legacy_state === "string" ? item.legacy_state : null,
    sourceRevision: typeof item.source_revision === "string" ? item.source_revision : null,
    scopeRef: typeof item.scope_ref === "string" ? item.scope_ref : null,
  };
}

function decodeGoalSlots(item: Record<string, unknown>): readonly HandoverEvidenceSlot[] {
  if (item.checklist_version === undefined) return [];
  if (item.checklist_version !== "1.0.0" || JSON.stringify(item.required_slots) !== JSON.stringify(HANDOVER_SLOTS) ||
      !Array.isArray(item.evidence) || item.evidence.length > 64 || typeof item.slot_exemptions !== "object" || item.slot_exemptions === null || Array.isArray(item.slot_exemptions)) {
    throw new Error("Handover checklist is malformed.");
  }
  const exemptions = item.slot_exemptions as Record<string, unknown>;
  if (Object.keys(exemptions).some((key) => !HANDOVER_SLOTS.includes(key as HandoverSlot))) throw new Error("Unknown handover slot.");
  for (const value of item.evidence) {
    if (value === null || typeof value !== "object" || Array.isArray(value)) throw new Error("Handover evidence is malformed.");
    const slot = (value as Record<string, unknown>).slot;
    if (slot !== undefined && slot !== null && !HANDOVER_SLOTS.includes(slot as HandoverSlot)) throw new Error("Unknown handover slot.");
  }
  return HANDOVER_SLOTS.map((slot) => {
    const evidence = (item.evidence as unknown[]).filter((value) => value !== null && typeof value === "object" && (value as Record<string, unknown>).slot === slot);
    const reason = exemptions[slot];
    if (evidence.length > 1 || (evidence.length && reason !== undefined) ||
        (reason !== undefined && (typeof reason !== "string" || !reason.trim() || reason.length > 256))) throw new Error("Conflicting handover slot evidence.");
    const record = evidence[0] as Record<string, unknown> | undefined;
    if (record && (typeof record.evidence_ref !== "string" || !record.evidence_ref.startsWith("doc:") || record.evidence_ref.length > 256 ||
      !["document", "document_span"].includes(String(record.kind)) ||
        typeof record.digest !== "string" || !/^[a-f0-9]{64}$/.test(record.digest))) throw new Error("Handover evidence is malformed.");
    return { slot, evidenceRef: record ? record.evidence_ref as string : null, reasonRef: typeof reason === "string" ? reason : null };
  });
}
