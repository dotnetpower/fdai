import type { FrameSource } from "../hooks/observation-source";
import type { AuditItem } from "../types";
import { activityVerb, type ActivityVerb } from "./agent-activity-groups";
import {
  agentOf,
  auditProvenanceOf,
  entryConversation,
  entryStr,
} from "./agent-activity-semantics";
import type { LiveAgentActivityEvent } from "./agents.model";
import type { ObservationDomain, OperationalActivityKind } from "../agent-operational-activity";

export const AGENT_LIVE_LOG_LIMIT = 700;
export const AGENT_AUDIT_PARENT_LIMIT = 200;
export const AGENT_AUDIT_CONVERSATION_LIMIT = 200;
export const AGENT_AUDIT_LOG_LIMIT =
  AGENT_AUDIT_PARENT_LIMIT + AGENT_AUDIT_CONVERSATION_LIMIT;
export const AGENT_LOG_LIMIT = AGENT_LIVE_LOG_LIMIT + AGENT_AUDIT_LOG_LIMIT;
export const AGENT_LOG_ROW_HIGHLIGHT_MS = 3_000;
export type AgentLogColumn = "time" | "route" | "type" | "detail" | "correlation";
export const DEFAULT_AGENT_LOG_COLUMNS: readonly AgentLogColumn[] = [
  "time",
  "route",
  "type",
  "detail",
  "correlation",
];

const COLUMN_ORDER: readonly AgentLogColumn[] = [
  "time",
  "route",
  "type",
  "detail",
  "correlation",
];

export type AgentLogSource = FrameSource | "audit-operational" | "audit-sample";

export interface AgentLogRow {
  readonly id: string;
  readonly timestamp: string;
  readonly timestampValid: boolean;
  readonly route: readonly string[];
  readonly kind: "incident" | "handoff" | "state" | Exclude<ActivityVerb, "all"> | "activity";
  readonly detail: string;
  readonly context: string | null;
  readonly correlationId: string | null;
  readonly eventId: string | null;
  readonly activityId: string | null;
  readonly resourceLabel: string | null;
  readonly resourceRef: string | null;
  readonly source: AgentLogSource;
  readonly operationalKind: OperationalActivityKind | null;
  readonly observationDomain: ObservationDomain | null;
  readonly sortOrder: readonly [number, number, number];
}

export function hasAuditTrace(row: Pick<AgentLogRow, "correlationId" | "source">): boolean {
  return row.correlationId !== null
    && (row.source === "audit-operational" || row.source === "audit-sample");
}

export function buildAgentLogRows(
  events: readonly LiveAgentActivityEvent[],
  auditItems: readonly AuditItem[],
): readonly AgentLogRow[] {
  const liveRows: AgentLogRow[] = [];
  const auditRows: AgentLogRow[] = [];
  const conversationRows: AgentLogRow[] = [];
  const latestLiveEventByAgent = new Map<string, LiveAgentActivityEvent>();
  events.forEach((event, index) => {
    const previous = latestLiveEventByAgent.get(event.agent);
    if (isRepeatedPassiveSnapshot(previous, event)) return;
    for (const agent of event.agents.length > 0 ? event.agents : [event.agent]) {
      latestLiveEventByAgent.set(agent, event);
    }
    liveRows.push({
      id: `live:${event.sequence}`,
      timestamp: event.ts,
      timestampValid: timestamp(event.ts) !== null,
      route: event.agents.length > 0 ? event.agents : [event.agent],
      kind: liveKind(event),
      detail: handlerDetail(event),
      context: handlerContext(event),
      correlationId: event.correlationId,
      eventId: event.eventId ?? null,
      activityId: event.activityId,
      resourceLabel: event.resourceName ?? event.resourceRef ?? null,
      resourceRef: event.resourceRef ?? null,
      source: event.source,
      operationalKind: event.operationalKind,
      observationDomain: event.observationDomain,
      sortOrder: [0, 0, events.length - index],
    });
  });
  auditItems.forEach((item) => {
    const actor = agentOf(item);
    const provenance = auditProvenanceOf(item);
    const summary = entryStr(item, "summary") || entryStr(item, "detail") ||
      entryStr(item, "reason") || item.action_kind;
    const target = entryStr(item, "resource_ref") || entryStr(item, "target_resource_ref");
    auditRows.push({
      id: `audit:${item.seq}`,
      timestamp: item.recorded_at,
      timestampValid: timestamp(item.recorded_at) !== null,
      route: [actor],
      kind: activityVerb(item),
      detail: target ? `${item.action_kind} on ${target} - ${summary}` : summary,
      context: `${item.mode} - ${provenance}`,
      correlationId: item.correlation_id,
      eventId: item.event_id,
      activityId: null,
      resourceLabel: null,
      resourceRef: target,
      source: provenance === "sample" ? "audit-sample" : "audit-operational",
      operationalKind: null,
      observationDomain: null,
      sortOrder: [1, item.seq, 0],
    });
    entryConversation(item)?.forEach((turn, index) => {
      conversationRows.push({
        id: `audit:${item.seq}:conversation:${index}`,
        timestamp: item.recorded_at,
        timestampValid: timestamp(item.recorded_at) !== null,
        route: [turn.from, turn.to],
        kind: "handoff",
        detail: turn.text,
        context: item.action_kind,
        correlationId: item.correlation_id,
        eventId: item.event_id,
        activityId: null,
        resourceLabel: null,
        resourceRef: null,
        source: provenance === "sample" ? "audit-sample" : "audit-operational",
        operationalKind: null,
        observationDomain: null,
        sortOrder: [1, item.seq, index + 1],
      });
    });
  });
  return [
    ...newestBoundedRows(liveRows, AGENT_LIVE_LOG_LIMIT),
    ...newestBoundedRows(auditRows, AGENT_AUDIT_PARENT_LIMIT),
    ...newestBoundedRows(conversationRows, AGENT_AUDIT_CONVERSATION_LIMIT),
  ].sort(compareRows);
}

export function filterAgentLogRows(
  rows: readonly AgentLogRow[],
  selectedAgent: string | null,
  query: string,
  operationalKind: "all" | OperationalActivityKind = "all",
): readonly AgentLogRow[] {
  const needle = normalize(query);
  return rows.filter((row) => {
    if (selectedAgent !== null && !row.route.includes(selectedAgent)) return false;
    if (operationalKind !== "all" && row.operationalKind !== operationalKind) return false;
    if (!needle) return true;
    return normalize([
      ...row.route,
      row.kind,
      row.detail,
      row.context,
      row.correlationId,
      row.eventId,
      row.activityId,
      row.resourceLabel,
      row.resourceRef,
      row.source,
      row.operationalKind,
      row.observationDomain,
    ].filter(Boolean).join(" ")).includes(needle);
  });
}

export function appendedAgentLogRowIds(
  previousIds: ReadonlySet<string> | null,
  rows: readonly Pick<AgentLogRow, "id" | "source">[],
): readonly string[] {
  if (previousIds === null) return [];
  return rows.flatMap((row) =>
    row.source !== "replay" && !previousIds.has(row.id) ? [row.id] : []
  );
}

export function toggleAgentLogColumn(
  visible: readonly AgentLogColumn[],
  column: AgentLogColumn,
): readonly AgentLogColumn[] {
  const next = visible.includes(column)
    ? visible.filter((candidate) => candidate !== column)
    : COLUMN_ORDER.filter((candidate) => candidate === column || visible.includes(candidate));
  return next.length > 0 ? next : ["detail"];
}

export function isNearLogBottom(
  scrollHeight: number,
  scrollTop: number,
  clientHeight: number,
): boolean {
  return scrollHeight - scrollTop - clientHeight < 24;
}

export type AgentLogFullscreenAction = "exit-native" | "enter-native" | "enter-fallback";

export function agentLogFullscreenAction(
  hasFullscreenElement: boolean,
  requestFullscreenAvailable: boolean,
): AgentLogFullscreenAction {
  if (hasFullscreenElement) return "exit-native";
  return requestFullscreenAvailable ? "enter-native" : "enter-fallback";
}

export function fallbackAfterFullscreenFailure(action: AgentLogFullscreenAction): boolean {
  return action === "enter-native";
}

function liveKind(event: LiveAgentActivityEvent): AgentLogRow["kind"] {
  if (event.operationalKind !== null) return "activity";
  if (event.activityId !== null && event.activityPhase !== undefined) return "activity";
  if (event.kind === "incident.ticket") return "incident";
  if (event.kind === "conversation.turn") return "handoff";
  return "state";
}

function handlerDetail(event: LiveAgentActivityEvent): string {
  if (event.activityId === null || event.activityPhase === undefined) {
    return event.detail || event.summary;
  }
  return event.eventType ?? event.topic ?? event.detail ?? event.summary;
}

function handlerContext(event: LiveAgentActivityEvent): string | null {
  if (event.activityId === null || event.activityPhase === undefined) {
    return event.detail && event.detail !== event.summary ? event.summary : null;
  }
  return [
    event.resourceType,
    event.activityPhase,
    event.durationMs === undefined ? null : `${event.durationMs} ms`,
    event.topic,
  ].filter((value): value is string => value !== null && value !== undefined).join(" - ");
}

function shortResourceId(value: string): string {
  return value.split("/").filter(Boolean).at(-1) ?? value;
}

function isRepeatedPassiveSnapshot(
  previous: LiveAgentActivityEvent | undefined,
  candidate: LiveAgentActivityEvent,
): boolean {
  if (
    previous === undefined ||
    candidate.kind !== "agent.state" ||
    candidate.activityId !== null ||
    (candidate.state !== "idle" && candidate.state !== "watching")
  ) return false;
  return previous.kind === candidate.kind &&
    previous.state === candidate.state &&
    previous.detail === candidate.detail &&
    previous.correlationId === candidate.correlationId &&
    previous.source === candidate.source;
}

function compareOrder(
  left: readonly [number, number, number],
  right: readonly [number, number, number],
): number {
  return left[0] - right[0] || left[1] - right[1] || left[2] - right[2];
}

function newestBoundedRows(
  rows: AgentLogRow[],
  limit: number,
): readonly AgentLogRow[] {
  rows.sort(compareRows);
  return rows.length > limit ? rows.slice(-limit) : rows;
}

function compareRows(left: AgentLogRow, right: AgentLogRow): number {
  return compareTimestamp(left.timestamp, right.timestamp) ||
    compareOrder(left.sortOrder, right.sortOrder) || left.id.localeCompare(right.id);
}

function compareTimestamp(left: string, right: string): number {
  const leftValue = timestamp(left);
  const rightValue = timestamp(right);
  if (leftValue === null) return rightValue === null ? 0 : 1;
  if (rightValue === null) return -1;
  return leftValue - rightValue;
}

function timestamp(value: string): number | null {
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}

function normalize(value: string): string {
  return value.toLocaleLowerCase().replace(/[-_.:/]+/g, " ").replace(/\s+/g, " ").trim();
}
