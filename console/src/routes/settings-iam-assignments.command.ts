import type { AuthContext } from "../auth";
import { putGovernedJson } from "../governed-command";
import {
  decodeAssignmentCase,
  type AssignmentCase,
  type AssignmentDraft,
} from "./settings-iam-assignments.model";

export async function createAssignmentCase(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  draft: AssignmentDraft,
  idempotencyKey: string,
): Promise<AssignmentCase> {
  if (draft.identity === null) throw new Error("An exact identity is required");
  return decodeAssignmentCase(await putGovernedJson(
    auth,
    operatorApiBaseUrl,
    "/iam/assignment-cases",
    {
      idempotency_key: idempotencyKey,
      subject: { provider: draft.identity.provider, subject_id: draft.identity.subjectId },
      requested_role: draft.role,
      duty_bindings: draft.duties.map((duty) => ({
        agent_name: duty.agentName,
        duty: duty.duty,
        scope_ref: duty.scopeRef.trim(),
      })),
      goal_refs: draft.goalRefs,
      justification: draft.justification.trim(),
    },
    "POST",
  ));
}

export async function submitAssignmentCase(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  assignmentCase: AssignmentCase,
): Promise<AssignmentCase> {
  return decodeAssignmentCase(await putGovernedJson(
    auth,
    operatorApiBaseUrl,
    `/iam/assignment-cases/${encodeURIComponent(assignmentCase.caseId)}/submit`,
    { expected_revision: assignmentCase.revision },
    "POST",
  ));
}

export async function reviewAssignmentCase(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  assignmentCase: AssignmentCase,
  decision: "approve" | "reject",
): Promise<AssignmentCase> {
  return decodeAssignmentCase(await putGovernedJson(
    auth,
    operatorApiBaseUrl,
    `/iam/assignment-cases/${encodeURIComponent(assignmentCase.caseId)}/review`,
    { expected_revision: assignmentCase.revision, decision },
    "POST",
  ));
}
