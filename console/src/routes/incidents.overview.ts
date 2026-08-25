import type { AuditItem, IncidentSummary } from "../types";
import { COMPLIANT_EVALUATION_REASON } from "./incidents.milestones";

export type IncidentOperationalPhase =
  | "resolved"
  | "notification_failed"
  | "approval_delivery_unavailable"
  | "approval_required"
  | "response_failed"
  | "response_in_progress"
  | "monitoring";

export interface IncidentOperationalOverview {
  readonly phase: IncidentOperationalPhase;
  readonly notificationDeliveryFailed: boolean;
  readonly approvalDeliveryUnavailable: boolean;
  readonly userInputRequired: boolean;
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

const APPROVAL_DELIVERY_FAILURES = new Set([
  "hil.request.dispatch_unavailable",
  "hil.request.dispatch_failed",
  "hil.load.initial_failed",
  "hil.load.reminder_failed",
  "hil.escalation.delivery_failed",
]);

const APPROVAL_DELIVERY_RECOVERIES = new Set([
  "hil.load.initial_sent",
  "hil.load.reminder_sent",
  "hil.escalation.delivered",
  "hil.approved.claimed",
  "hil.approved.executed",
  "hil.approved.execute_failed",
  "hil.rejected",
  "hil.timeout",
  "hil.resolve.integrity_failed",
  "hil.escalation.exhausted",
]);

const APPROVAL_TERMINAL_EVENTS = new Set([
  "hil.approved.claimed",
  "hil.approved.executed",
  "hil.approved.execute_failed",
  "hil.rejected",
  "hil.timeout",
  "hil.resolve.integrity_failed",
  "hil.escalation.exhausted",
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
  if (
    phase === "notification_failed"
    || phase === "approval_delivery_unavailable"
    || phase === "response_failed"
  ) return "blocked";
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
        || kind === "notification.route";
    })
    .sort((left, right) => right.seq - left.seq)[0];
  const latestNotificationKind = latestNotification?.action_kind.toLowerCase() ?? "";
  const latestNotificationOutcome = stringEntry(latestNotification, "outcome");
  const notificationFailed = latestNotificationKind === "notification.escalation"
    || (latestNotificationKind === "notification.route"
      && ["route_unresolved", "unresolved", "failed"].includes(latestNotificationOutcome));
  const latestApprovalDelivery = [...history]
    .filter((item) => {
      const kind = item.action_kind.toLowerCase();
      return APPROVAL_DELIVERY_FAILURES.has(kind) || APPROVAL_DELIVERY_RECOVERIES.has(kind);
    })
    .sort((left, right) => right.seq - left.seq)[0];
  const approvalDeliveryUnavailable = APPROVAL_DELIVERY_FAILURES.has(
    latestApprovalDelivery?.action_kind.toLowerCase() ?? "",
  );
  const latestApprovalEvent = [...history]
    .filter((item) => {
      const kind = item.action_kind.toLowerCase();
      return kind === "hil.requested" || APPROVAL_TERMINAL_EVENTS.has(kind);
    })
    .sort((left, right) => right.seq - left.seq)[0];
  const latestApprovalKind = latestApprovalEvent?.action_kind.toLowerCase() ?? "";
  const approvalTerminal = APPROVAL_TERMINAL_EVENTS.has(latestApprovalKind);
  const approvalRequired = !approvalTerminal && (
    incident.disposition === "awaiting_hil"
    || latestApprovalKind === "hil.requested"
  );
  const responseFailed = incident.disposition === "failed"
    || latestApprovalKind === "hil.approved.execute_failed";
  const rcaAvailable = actionKinds.some((kind) => kind.startsWith("rca."));
  const responseInProgress = incident.status === "in_progress"
    || incident.disposition === "action_delivered"
    || latestApprovalKind === "hil.approved.claimed"
    || latestApprovalKind === "hil.approved.executed";

  const phase: IncidentOperationalPhase = incident.status === "resolved"
    ? "resolved"
    : responseFailed
      ? "response_failed"
      : notificationFailed
        ? "notification_failed"
        : approvalDeliveryUnavailable
          ? "approval_delivery_unavailable"
          : approvalRequired
            ? "approval_required"
          : responseInProgress
            ? "response_in_progress"
            : "monitoring";

  return {
    phase,
    notificationDeliveryFailed: notificationFailed,
    approvalDeliveryUnavailable,
    userInputRequired: approvalRequired || approvalDeliveryUnavailable,
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
  if (stringEntry(item, "reason") === COMPLIANT_EVALUATION_REASON) return false;
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
