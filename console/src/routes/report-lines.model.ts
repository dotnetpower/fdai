import {
  panelArray,
  panelBoolean,
  panelNonEmptyString,
  panelNonNegativeInteger,
  panelNullableString,
  panelRecord,
} from "./panel-decode";

export type ReportingLineState =
  | "awaiting_core"
  | "pending_confirmation"
  | "pending_owner_review"
  | "active"
  | "conflict"
  | "rejected"
  | "superseded";

export interface ReportingLineCase {
  readonly operatorCaseId: string;
  readonly caseId: string | null;
  readonly candidateId: string;
  readonly uploadId: string;
  readonly requesterRef: string;
  readonly subjectRef: string | null;
  readonly managerRef: string | null;
  readonly state: ReportingLineState;
  readonly revision: number;
  readonly edgeDigest: string | null;
  readonly directoryComparison: string;
  readonly canConfirm: boolean;
  readonly canReview: boolean;
  readonly effectiveFrom: string | null;
  readonly effectiveUntil: string | null;
}

export interface ReportingLineProjection {
  readonly graphRevision: string;
  readonly items: readonly ReportingLineCase[];
  readonly total: number;
  readonly summary: {
    readonly active: number;
    readonly pendingConfirmation: number;
    readonly pendingOwnerReview: number;
    readonly conflict: number;
    readonly awaitingCore: number;
  };
}

export interface ReportLineContactRequest {
  readonly approvalId: string;
  readonly consentId: string;
  readonly consentRevision: number;
  readonly actionType: string;
  readonly targetRef: string;
  readonly routeSubjects: readonly string[];
  readonly expiresAt: string;
}

const STATES: readonly ReportingLineState[] = [
  "awaiting_core",
  "pending_confirmation",
  "pending_owner_review",
  "active",
  "conflict",
  "rejected",
  "superseded",
];

export function decodeReportingLineProjection(value: unknown): ReportingLineProjection {
  const root = panelRecord(value, "reporting lines");
  const summary = panelRecord(root["summary"], "reporting lines.summary");
  return {
    graphRevision: panelNonEmptyString(root, "graph_revision", "reporting lines"),
    items: panelArray(root["items"], "reporting lines.items").map(decodeReportingLineCase),
    total: panelNonNegativeInteger(root, "total", "reporting lines"),
    summary: {
      active: panelNonNegativeInteger(summary, "active", "reporting lines.summary"),
      pendingConfirmation: panelNonNegativeInteger(
        summary,
        "pending_confirmation",
        "reporting lines.summary",
      ),
      pendingOwnerReview: panelNonNegativeInteger(
        summary,
        "pending_owner_review",
        "reporting lines.summary",
      ),
      conflict: panelNonNegativeInteger(summary, "conflict", "reporting lines.summary"),
      awaitingCore: panelNonNegativeInteger(
        summary,
        "awaiting_core",
        "reporting lines.summary",
      ),
    },
  };
}

export function decodeReportingLineCase(value: unknown): ReportingLineCase {
  const item = panelRecord(value, "reporting line");
  const state = panelNonEmptyString(item, "state", "reporting line");
  if (!STATES.includes(state as ReportingLineState)) {
    throw new Error(`reporting line.state has unsupported value ${state}`);
  }
  return {
    operatorCaseId: panelNonEmptyString(item, "operator_case_id", "reporting line"),
    caseId: panelNullableString(item, "case_id", "reporting line"),
    candidateId: panelNonEmptyString(item, "candidate_id", "reporting line"),
    uploadId: panelNonEmptyString(item, "upload_id", "reporting line"),
    requesterRef: panelNonEmptyString(item, "requester_ref", "reporting line"),
    subjectRef: panelNullableString(item, "subject_ref", "reporting line"),
    managerRef: panelNullableString(item, "manager_ref", "reporting line"),
    state: state as ReportingLineState,
    revision: panelNonNegativeInteger(item, "revision", "reporting line"),
    edgeDigest: panelNullableString(item, "edge_digest", "reporting line"),
    directoryComparison: panelNonEmptyString(
      item,
      "directory_comparison",
      "reporting line",
    ),
    canConfirm: panelBoolean(item, "can_confirm", "reporting line"),
    canReview: panelBoolean(item, "can_review", "reporting line"),
    effectiveFrom: panelNullableString(item, "effective_from", "reporting line"),
    effectiveUntil: panelNullableString(item, "effective_until", "reporting line"),
  };
}

export function decodeReportLineContactRequests(
  value: unknown,
): readonly ReportLineContactRequest[] {
  const root = panelRecord(value, "report-line contact requests");
  return panelArray(
    root["items"],
    "report-line contact requests.items",
  ).map((value, index) => {
    const item = panelRecord(value, `report-line contact requests.items[${index}]`);
    return {
      approvalId: panelNonEmptyString(item, "approval_id", "report-line contact request"),
      consentId: panelNonEmptyString(item, "consent_id", "report-line contact request"),
      consentRevision: panelNonNegativeInteger(
        item,
        "consent_revision",
        "report-line contact request",
      ),
      actionType: panelNonEmptyString(item, "action_type", "report-line contact request"),
      targetRef: panelNonEmptyString(item, "target_ref", "report-line contact request"),
      routeSubjects: panelArray(
        item["route_subjects"],
        "report-line contact request.route_subjects",
      ).map((subject, subjectIndex) => {
        if (typeof subject !== "string" || subject.length === 0) {
          throw new Error(
            `report-line contact request.route_subjects[${subjectIndex}] must be text`,
          );
        }
        return subject;
      }),
      expiresAt: panelNonEmptyString(item, "expires_at", "report-line contact request"),
    };
  });
}
