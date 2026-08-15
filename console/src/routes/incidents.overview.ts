import type { AuditItem, IncidentSummary } from "../types";

export type IncidentOperationalPhase =
  | "resolved"
  | "notification_failed"
  | "approval_required"
  | "response_failed"
  | "response_in_progress"
  | "monitoring";

export interface IncidentOperationalOverview {
  readonly phase: IncidentOperationalPhase;
  readonly decisionRecorded: boolean;
  readonly rcaAvailable: boolean;
  readonly reportAvailable: boolean;
  readonly traceAvailable: boolean;
  readonly auditAvailable: boolean;
  readonly activityCount: number;
  readonly blockingReason: string | null;
}

/** Action kinds and verdicts that record why a governed response stopped. */
const BLOCKING_VERDICTS = new Set([
  "abstain",
  "abstained",
  "deny",
  "denied",
  "failed",
  "failure",
  "error",
]);

export type IncidentAgentStatus =
  | "completed"
  | "blocked"
  | "pending_user_input"
  | "in_progress"
  | "monitoring";

export function incidentAgentStatus(
  phase: IncidentOperationalPhase,
): IncidentAgentStatus {
  if (phase === "resolved") return "completed";
  if (phase === "notification_failed" || phase === "response_failed") return "blocked";
  if (phase === "approval_required") return "pending_user_input";
  if (phase === "response_in_progress") return "in_progress";
  return "monitoring";
}

export function incidentOperationalOverview(
  incident: IncidentSummary,
  history: readonly AuditItem[],
): IncidentOperationalOverview {
  const actionKinds = history.map((item) => item.action_kind.toLowerCase());
  const latestNotification = [...history]
    .filter((item) => {
      const kind = item.action_kind.toLowerCase();
      return kind === "notification.escalation"
        || kind === "notification.route"
        || kind === "hil.request.dispatch_unavailable";
    })
    .sort((left, right) => right.seq - left.seq)[0];
  const latestNotificationKind = latestNotification?.action_kind.toLowerCase() ?? "";
  const latestNotificationOutcome = stringEntry(latestNotification, "outcome");
  const notificationFailed = latestNotificationKind === "notification.escalation"
    || latestNotificationKind === "hil.request.dispatch_unavailable"
    || (latestNotificationKind === "notification.route"
      && ["route_unresolved", "unresolved", "failed"].includes(latestNotificationOutcome));
  const approvalRequired = incident.disposition === "awaiting_hil"
    || incident.verdict === "hil"
    || actionKinds.includes("hil.requested");
  const responseFailed = incident.disposition === "failed";
  const rcaAvailable = actionKinds.some((kind) => kind.startsWith("rca."));
  const responseInProgress = incident.status === "in_progress"
    || incident.disposition === "action_delivered";

  const phase: IncidentOperationalPhase = incident.status === "resolved"
    ? "resolved"
    : notificationFailed
      ? "notification_failed"
      : approvalRequired
        ? "approval_required"
        : responseFailed
          ? "response_failed"
          : responseInProgress
            ? "response_in_progress"
            : "monitoring";

  return {
    phase,
    decisionRecorded: incident.verdict !== "unknown",
    rcaAvailable,
    reportAvailable: rcaAvailable,
    traceAvailable: history.length > 0,
    auditAvailable: history.length > 0,
    activityCount: history.length,
    blockingReason: blockingReason(history),
  };
}

/** The newest recorded reason a governed response abstained, denied, or failed. */
function blockingReason(history: readonly AuditItem[]): string | null {
  for (const item of [...history].sort((left, right) => right.seq - left.seq)) {
    if (!isBlocking(item)) continue;
    const reason = item.entry["reason"];
    if (typeof reason === "string" && reason.trim()) return reason.trim();
  }
  return null;
}

function isBlocking(item: AuditItem): boolean {
  if (BLOCKING_VERDICTS.has(stringEntry(item, "decision"))) return true;
  if (BLOCKING_VERDICTS.has(stringEntry(item, "outcome"))) return true;
  return item.action_kind
    .toLowerCase()
    .split(/[._-]+/)
    .some((token) => BLOCKING_VERDICTS.has(token));
}

function stringEntry(item: AuditItem | undefined, key: string): string {
  const value = item?.entry[key];
  return typeof value === "string" ? value.trim().toLowerCase() : "";
}
