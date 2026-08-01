import type { HumanIdentityResult, IamRole } from "./settings-iam.model";

export type AssignmentDuty = "primary" | "backup" | "escalation";
export type AssignmentState =
  | "draft"
  | "pending_review"
  | "approved"
  | "ownership_pr_open"
  | "ownership_merged"
  | "iam_applying"
  | "active"
  | "rejected"
  | "degraded"
  | "superseded";

export interface AssignmentDutyBinding {
  readonly agentName: string;
  readonly duty: AssignmentDuty;
  readonly scopeRef: string;
}

export interface AssignmentCase {
  readonly caseId: string;
  readonly state: AssignmentState;
  readonly revision: number;
  readonly requesterRef: string;
  readonly subjectProvider: string;
  readonly subjectId: string;
  readonly requestedRole: Exclude<IamRole, "BreakGlass">;
  readonly dutyBindings: readonly AssignmentDutyBinding[];
  readonly goalRefs: readonly string[];
  readonly justification: string;
  readonly reviews: readonly {
    readonly reviewerRef: string;
    readonly decision: "approve" | "reject";
    readonly reviewedAt: string;
  }[];
  readonly effectReceipts: readonly {
    readonly kind: "ownership" | "iam";
    readonly receiptRef: string;
    readonly digest: string;
    readonly receivedAt: string;
  }[];
  readonly degradedReason: string | null;
}

export interface AssignmentProjectionItem {
  readonly subject: {
    readonly provider: string;
    readonly subjectId: string;
    readonly displayName: string | null;
    readonly username: string | null;
    readonly active: boolean | null;
  };
  readonly roles: readonly IamRole[] | null;
  readonly duties: readonly {
    readonly agentName: string;
    readonly duty: AssignmentDuty | null;
    readonly responsibility: "accountable" | "informed";
    readonly source: "stewardship";
  }[];
  readonly coverage: readonly {
    readonly agentName: string;
    readonly primaryCount: number;
    readonly backupOrEscalationCount: number;
    readonly findingCodes: readonly string[];
  }[] | null;
  readonly assignmentCase: AssignmentCase | null;
  readonly handover: {
    readonly goalRefs: readonly string[];
    readonly state: string | null;
    readonly evidenceRefs: readonly string[] | null;
    readonly availability: "not_connected";
  };
}

export interface AssignmentProjectionPage {
  readonly items: readonly AssignmentProjectionItem[];
  readonly total: number;
  readonly nextCursor: number | null;
  readonly authority: "observation_only";
  readonly directoryAvailability: "available" | "not_configured";
  readonly caseProjectionTruncated: boolean;
}

export interface AssignmentDraft {
  readonly identity: HumanIdentityResult | null;
  readonly role: Exclude<IamRole, "BreakGlass">;
  readonly duties: readonly AssignmentDutyBinding[];
  readonly goalRefs: readonly string[];
  readonly justification: string;
}

export interface AssignmentFilters {
  readonly query: string;
  readonly role: "all" | Exclude<IamRole, "BreakGlass">;
  readonly agent: string;
  readonly coverage: "all" | "covered" | "gap" | "unavailable";
}

export function assignmentValidation(draft: AssignmentDraft): readonly string[] {
  const issues: string[] = [];
  if (draft.identity === null) issues.push("identity");
  else if (!draft.identity.active) issues.push("inactive_identity");
  if (draft.duties.length === 0) issues.push("duties");
  if (draft.duties.some((duty) => !duty.scopeRef.trim())) issues.push("scope");
  const dutyKeys = draft.duties.map((duty) => `${duty.agentName}:${duty.scopeRef.trim().toLowerCase()}`);
  if (new Set(dutyKeys).size !== dutyKeys.length) issues.push("duplicate_duty");
  if (draft.justification.trim().length < 20) issues.push("justification");
  return issues;
}

export function filterAssignments(
  items: readonly AssignmentProjectionItem[],
  filters: AssignmentFilters,
): readonly AssignmentProjectionItem[] {
  const query = filters.query.trim().toLowerCase();
  return items.filter((item) => {
    const search = [item.subject.displayName, item.subject.username, item.subject.subjectId]
      .filter((value): value is string => value !== null)
      .join(" ")
      .toLowerCase();
    const coverage = item.coverage === null
      ? "unavailable"
      : item.coverage.some((entry) => entry.primaryCount < 1 || entry.backupOrEscalationCount < 1)
      ? "gap"
      : "covered";
    return (!query || search.includes(query))
      && (filters.role === "all" || item.roles?.includes(filters.role) === true)
      && (!filters.agent || item.duties.some((duty) => duty.agentName === filters.agent))
      && (filters.coverage === "all" || filters.coverage === coverage);
  });
}

export function decodeAssignmentProjectionPage(value: unknown): AssignmentProjectionPage {
  const root = record(value, "assignment projection");
  const authority = string(root["authority"], "assignment projection.authority");
  if (authority !== "observation_only") throw new Error("assignment projection authority is invalid");
  const directoryAvailability = string(
    root["directory_availability"],
    "assignment projection.directory_availability",
  );
  if (directoryAvailability !== "available" && directoryAvailability !== "not_configured") {
    throw new Error("assignment projection directory availability is invalid");
  }
  return {
    items: array(root["items"], "assignment projection.items").map(decodeProjectionItem),
    total: integer(root["total"], "assignment projection.total"),
    nextCursor: root["next_cursor"] === null
      ? null
      : integer(root["next_cursor"], "assignment projection.next_cursor"),
    authority: "observation_only",
    directoryAvailability,
    caseProjectionTruncated: boolean(
      root["case_projection_truncated"],
      "assignment projection.case_projection_truncated",
    ),
  };
}

export function decodeAssignmentCase(value: unknown): AssignmentCase {
  const root = record(value, "assignment case");
  const intent = record(root["intent"], "assignment case.intent");
  const subject = record(intent["subject"], "assignment case.intent.subject");
  const state = assignmentState(root["state"]);
  return {
    caseId: string(root["case_id"], "assignment case.case_id"),
    state,
    revision: positiveInteger(root["revision"], "assignment case.revision"),
    requesterRef: string(intent["requester_ref"], "assignment case.intent.requester_ref"),
    subjectProvider: string(subject["provider"], "assignment case.intent.subject.provider"),
    subjectId: string(subject["subject_id"], "assignment case.intent.subject.subject_id"),
    requestedRole: routineRole(intent["requested_role"]),
    dutyBindings: array(intent["duty_bindings"], "assignment case.intent.duty_bindings")
      .map((value) => {
        const item = record(value, "assignment duty binding");
        return {
          agentName: string(item["agent_name"], "assignment duty binding.agent_name"),
          duty: assignmentDuty(item["duty"]),
          scopeRef: string(item["scope_ref"], "assignment duty binding.scope_ref"),
        };
      }),
    goalRefs: stringArray(intent["goal_refs"], "assignment case.intent.goal_refs"),
    justification: string(intent["justification"], "assignment case.intent.justification"),
    reviews: array(root["reviews"], "assignment case.reviews").map((value) => {
      const item = record(value, "assignment review");
      const decision = string(item["decision"], "assignment review.decision");
      if (decision !== "approve" && decision !== "reject") throw new Error("assignment review decision is invalid");
      return {
        reviewerRef: string(item["reviewer_ref"], "assignment review.reviewer_ref"),
        decision,
        reviewedAt: dateString(item["reviewed_at"], "assignment review.reviewed_at"),
      };
    }),
    effectReceipts: array(root["effect_receipts"], "assignment case.effect_receipts")
      .map((value) => {
        const item = record(value, "assignment effect receipt");
        const kind = string(item["kind"], "assignment effect receipt.kind");
        if (kind !== "ownership" && kind !== "iam") throw new Error("assignment effect kind is invalid");
        return {
          kind,
          receiptRef: string(item["receipt_ref"], "assignment effect receipt.receipt_ref"),
          digest: string(item["digest"], "assignment effect receipt.digest"),
          receivedAt: dateString(item["received_at"], "assignment effect receipt.received_at"),
        };
      }),
    degradedReason: nullableString(root["degraded_reason"], "assignment case.degraded_reason"),
  };
}

function decodeProjectionItem(value: unknown): AssignmentProjectionItem {
  const root = record(value, "assignment projection item");
  const subject = record(root["subject"], "assignment projection item.subject");
  const handover = record(root["handover"], "assignment projection item.handover");
  if (handover["availability"] !== "not_connected") throw new Error("assignment handover availability is invalid");
  return {
    subject: {
      provider: string(subject["provider"], "assignment subject.provider"),
      subjectId: string(subject["subject_id"], "assignment subject.subject_id"),
      displayName: nullableString(subject["display_name"], "assignment subject.display_name"),
      username: nullableString(subject["username"], "assignment subject.username"),
      active: nullableBoolean(subject["active"], "assignment subject.active"),
    },
    roles: root["roles"] === null
      ? null
      : stringArray(root["roles"], "assignment roles").map(iamRole),
    duties: array(root["duties"], "assignment duties").map((value) => {
      const item = record(value, "assignment duty");
      const responsibility = string(item["responsibility"], "assignment duty.responsibility");
      if (responsibility !== "accountable" && responsibility !== "informed") throw new Error("assignment responsibility is invalid");
      if (item["source"] !== "stewardship") throw new Error("assignment duty source is invalid");
      return {
        agentName: string(item["agent_name"], "assignment duty.agent_name"),
        duty: item["duty"] === null ? null : assignmentDuty(item["duty"]),
        responsibility,
        source: "stewardship" as const,
      };
    }),
    coverage: root["coverage"] === null
      ? null
      : array(root["coverage"], "assignment coverage").map((value) => {
        const item = record(value, "assignment coverage item");
        return {
          agentName: string(item["agent_name"], "assignment coverage.agent_name"),
          primaryCount: integer(item["primary_count"], "assignment coverage.primary_count"),
          backupOrEscalationCount: integer(
            item["backup_or_escalation_count"],
            "assignment coverage.backup_or_escalation_count",
          ),
          findingCodes: stringArray(item["finding_codes"], "assignment coverage.finding_codes"),
        };
      }),
    assignmentCase: root["case"] === null ? null : decodeAssignmentCase(root["case"]),
    handover: {
      goalRefs: stringArray(handover["goal_refs"], "assignment handover.goal_refs"),
      state: nullableString(handover["state"], "assignment handover.state"),
      evidenceRefs: handover["evidence_refs"] === null
        ? null
        : stringArray(handover["evidence_refs"], "assignment handover.evidence_refs"),
      availability: "not_connected",
    },
  };
}

function assignmentState(value: unknown): AssignmentState {
  const state = string(value, "assignment case.state");
  const states: readonly AssignmentState[] = ["draft", "pending_review", "approved", "ownership_pr_open", "ownership_merged", "iam_applying", "active", "rejected", "degraded", "superseded"];
  if (!states.includes(state as AssignmentState)) throw new Error("assignment case state is invalid");
  return state as AssignmentState;
}

function assignmentDuty(value: unknown): AssignmentDuty {
  const duty = string(value, "assignment duty");
  if (duty !== "primary" && duty !== "backup" && duty !== "escalation") throw new Error("assignment duty is invalid");
  return duty;
}

function routineRole(value: unknown): Exclude<IamRole, "BreakGlass"> {
  const role = iamRole(value);
  if (role === "BreakGlass") throw new Error("BreakGlass is not a routine assignment role");
  return role;
}

function iamRole(value: unknown): IamRole {
  const role = string(value, "IAM role");
  if (!["Reader", "Contributor", "Approver", "Owner", "BreakGlass"].includes(role)) throw new Error("IAM role is invalid");
  return role as IamRole;
}

function record(value: unknown, name: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${name} MUST be an object`);
  return value as Record<string, unknown>;
}
function array(value: unknown, name: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error(`${name} MUST be an array`);
  return value;
}
function string(value: unknown, name: string): string {
  if (typeof value !== "string" || !value) throw new Error(`${name} MUST be a non-empty string`);
  return value;
}
function nullableString(value: unknown, name: string): string | null {
  return value === null ? null : string(value, name);
}
function boolean(value: unknown, name: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${name} MUST be a boolean`);
  return value;
}
function nullableBoolean(value: unknown, name: string): boolean | null {
  return value === null ? null : boolean(value, name);
}
function integer(value: unknown, name: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) throw new Error(`${name} MUST be a non-negative integer`);
  return value;
}
function positiveInteger(value: unknown, name: string): number {
  const parsed = integer(value, name);
  if (parsed < 1) throw new Error(`${name} MUST be positive`);
  return parsed;
}
function stringArray(value: unknown, name: string): readonly string[] {
  return array(value, name).map((item) => string(item, `${name}[]`));
}
function dateString(value: unknown, name: string): string {
  const parsed = string(value, name);
  if (!Number.isFinite(Date.parse(parsed))) throw new Error(`${name} MUST be ISO 8601`);
  return parsed;
}
