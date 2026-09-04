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

/** One channel's recorded delivery state from the latest A2 route audit. */
export interface IncidentChannelDelivery {
  readonly channelId: string;
  readonly state: string;
}

/** Recorded A2 delivery evidence, never inferred from provider status alone. */
export interface IncidentNotificationEvidence {
  readonly targetChannelIds: readonly string[];
  readonly excludedChannels: readonly { readonly channelId: string; readonly reason: string }[];
  readonly deliveries: readonly IncidentChannelDelivery[];
  readonly observedDeliveredChannelIds: readonly string[];
}

export interface IncidentOperationalOverview {
  readonly phase: IncidentOperationalPhase;
  readonly notificationDeliveryFailed: boolean;
  readonly notificationEvidence: IncidentNotificationEvidence;
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
  // Incident attention is an A2 operational-alert concern only. An A4 digest
  // route or an A1 approval transport failure has its own surface, so they
  // never turn an incident red here.
  const notificationHistory = [...history]
    .filter((item) => {
      const kind = item.action_kind.toLowerCase();
      if (kind === "notification.escalation") return true;
      if (kind !== "notification.route") return false;
      const tier = stringEntry(item, "trust_tier");
      return tier === "" || tier === "a2_operational_alert";
    })
    .sort((left, right) => right.seq - left.seq);
  const latestNotification = notificationHistory[0];
  const latestNotificationKind = latestNotification?.action_kind.toLowerCase() ?? "";
  const latestNotificationOutcome = stringEntry(latestNotification, "outcome");
  const latestRoute = notificationHistory.find(
    (item) => item.action_kind.toLowerCase() === "notification.route",
  );
  const latestRouteAuditId = exactStringEntry(latestRoute, "audit_id");
  const observedDeliveredChannelIds = observedDeliveredChannels(
    history,
    latestRouteAuditId,
    latestRoute?.seq ?? Number.MAX_SAFE_INTEGER,
  );
  const deliveries = channelDeliveries(latestRoute);
  const failedChannelIds = deliveries
    .filter((item) => !TERMINAL_DELIVERED_STATES.has(item.state))
    .map((item) => item.channelId);
  // A provider 2xx only proves acceptance. Attention clears when the route
  // itself recorded delivered, or when an independent publication observation
  // recorded `published` for every channel that was still open.
  const recoveredByObservation = failedChannelIds.length > 0
    && failedChannelIds.every((channelId) => observedDeliveredChannelIds.includes(channelId));
  const notificationFailed = (
    latestNotificationKind === "notification.escalation"
    || (latestNotificationKind === "notification.route"
      && ["route_unresolved", "unresolved", "failed"].includes(latestNotificationOutcome))
  ) && !recoveredByObservation;
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
    notificationEvidence: {
      targetChannelIds: stringArrayEntry(latestRoute, "target_channel_ids"),
      excludedChannels: excludedChannels(latestRoute),
      deliveries,
      observedDeliveredChannelIds,
    },
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

const TERMINAL_DELIVERED_STATES = new Set(["delivered"]);

/** Channel ids an authenticated publication observation confirmed for the latest route. */
function observedDeliveredChannels(
  history: readonly AuditItem[],
  routeAuditId: string,
  routeSeq: number,
): readonly string[] {
  if (!routeAuditId) return [];
  const observed = new Map<string, boolean>();
  for (const item of [...history].sort((left, right) => left.seq - right.seq)) {
    if (item.action_kind.toLowerCase() !== "notification.delivery.observed") continue;
    if (item.seq <= routeSeq || exactStringEntry(item, "audit_id") !== routeAuditId) continue;
    if (stringEntry(item, "phase") !== "completed") continue;
    const channelId = item.entry["channel_id"];
    if (typeof channelId !== "string" || !channelId.trim()) continue;
    observed.set(
      channelId,
      stringEntry(item, "publication_result") === "published"
        && stringEntry(item, "delivery_state") === "delivered",
    );
  }
  return [...observed.entries()]
    .filter(([, delivered]) => delivered)
    .map(([channelId]) => channelId);
}

function channelDeliveries(item: AuditItem | undefined): readonly IncidentChannelDelivery[] {
  const raw = item?.entry["deliveries"];
  if (!Array.isArray(raw)) return [];
  const deliveries: IncidentChannelDelivery[] = [];
  for (const value of raw) {
    if (typeof value !== "object" || value === null) continue;
    const record = value as Record<string, unknown>;
    const channelId = record["channel_id"];
    const state = record["state"];
    if (typeof channelId !== "string" || !channelId.trim()) continue;
    if (typeof state !== "string" || !state.trim()) continue;
    deliveries.push({ channelId, state: state.toLowerCase() });
  }
  return deliveries;
}

function excludedChannels(
  item: AuditItem | undefined,
): readonly { readonly channelId: string; readonly reason: string }[] {
  const raw = item?.entry["excluded_channels"];
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return [];
  return Object.entries(raw as Record<string, unknown>)
    .filter(([channelId, reason]) => channelId.trim() && typeof reason === "string")
    .map(([channelId, reason]) => ({ channelId, reason: String(reason) }));
}

function stringArrayEntry(item: AuditItem | undefined, key: string): readonly string[] {
  const raw = item?.entry[key];
  if (!Array.isArray(raw)) return [];
  return raw.filter((value): value is string => typeof value === "string" && value.trim() !== "");
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

function exactStringEntry(item: AuditItem | undefined, key: string): string {
  const value = item?.entry[key];
  return typeof value === "string" ? value.trim() : "";
}
