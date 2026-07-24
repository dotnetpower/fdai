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

export const AGENT_LOG_LIMIT = 200;
export type AgentLogColumn = "time" | "route" | "type" | "detail" | "correlation";
export const DEFAULT_AGENT_LOG_COLUMNS: readonly AgentLogColumn[] = [
  "time",
  "route",
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
  readonly source: AgentLogSource;
  readonly sortOrder: readonly [number, number, number];
}

export function buildAgentLogRows(
  events: readonly LiveAgentActivityEvent[],
  auditItems: readonly AuditItem[],
): readonly AgentLogRow[] {
  const rows: AgentLogRow[] = [];
  const latestLiveEventByAgent = new Map<string, LiveAgentActivityEvent>();
  events.forEach((event, index) => {
    const previous = latestLiveEventByAgent.get(event.agent);
    if (isRepeatedPassiveSnapshot(previous, event)) return;
    for (const agent of event.agents.length > 0 ? event.agents : [event.agent]) {
      latestLiveEventByAgent.set(agent, event);
    }
    addBoundedRow(rows, {
      id: `live:${event.sequence}`,
      timestamp: event.ts,
      timestampValid: timestamp(event.ts) !== null,
      route: event.agents.length > 0 ? event.agents : [event.agent],
      kind: liveKind(event),
      detail: event.detail || event.summary,
      context: event.detail && event.detail !== event.summary ? event.summary : null,
      correlationId: event.correlationId,
      eventId: null,
      source: event.source,
      sortOrder: [0, 0, events.length - index],
    });
  });
  auditItems.forEach((item) => {
    const actor = agentOf(item);
    const provenance = auditProvenanceOf(item);
    const summary = entryStr(item, "summary") || entryStr(item, "detail") ||
      entryStr(item, "reason") || item.action_kind;
    const target = entryStr(item, "resource_ref") || entryStr(item, "target_resource_ref");
    addBoundedRow(rows, {
      id: `audit:${item.seq}`,
      timestamp: item.recorded_at,
      timestampValid: timestamp(item.recorded_at) !== null,
      route: [actor],
      kind: activityVerb(item),
      detail: target ? `${item.action_kind} on ${target} - ${summary}` : summary,
      context: `${item.mode} - ${provenance}`,
      correlationId: item.correlation_id,
      eventId: item.event_id,
      source: provenance === "sample" ? "audit-sample" : "audit-operational",
      sortOrder: [1, item.seq, 0],
    });
    entryConversation(item)?.forEach((turn, index) => {
      addBoundedRow(rows, {
        id: `audit:${item.seq}:conversation:${index}`,
        timestamp: item.recorded_at,
        timestampValid: timestamp(item.recorded_at) !== null,
        route: [turn.from, turn.to],
        kind: "handoff",
        detail: turn.text,
        context: item.action_kind,
        correlationId: item.correlation_id,
        eventId: item.event_id,
        source: provenance === "sample" ? "audit-sample" : "audit-operational",
        sortOrder: [1, item.seq, index + 1],
      });
    });
  });
  return rows;
}

export function filterAgentLogRows(
  rows: readonly AgentLogRow[],
  selectedAgent: string | null,
  query: string,
): readonly AgentLogRow[] {
  const needle = normalize(query);
  return rows.filter((row) => {
    if (selectedAgent !== null && !row.route.includes(selectedAgent)) return false;
    if (!needle) return true;
    return normalize([
      ...row.route,
      row.kind,
      row.detail,
      row.context,
      row.correlationId,
      row.eventId,
      row.source,
    ].filter(Boolean).join(" ")).includes(needle);
  });
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
  if (event.kind === "incident.ticket") return "incident";
  if (event.kind === "conversation.turn") return "handoff";
  return "state";
}

function isRepeatedPassiveSnapshot(
  previous: LiveAgentActivityEvent | undefined,
  candidate: LiveAgentActivityEvent,
): boolean {
  if (
    previous === undefined ||
    candidate.kind !== "agent.state" ||
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

function addBoundedRow(rows: AgentLogRow[], row: AgentLogRow): void {
  rows.push(row);
  rows.sort(compareRows);
  if (rows.length > AGENT_LOG_LIMIT) rows.shift();
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
