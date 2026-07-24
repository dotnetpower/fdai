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
  readonly route: readonly string[];
  readonly kind: "incident" | "handoff" | "state" | Exclude<ActivityVerb, "all"> | "activity";
  readonly detail: string;
  readonly context: string | null;
  readonly correlationId: string | null;
  readonly eventId: string | null;
  readonly source: AgentLogSource;
}

export function buildAgentLogRows(
  events: readonly LiveAgentActivityEvent[],
  auditItems: readonly AuditItem[],
): readonly AgentLogRow[] {
  const rows: AgentLogRow[] = [];
  const seenLiveEvents = new Set<string>();
  events.forEach((event) => {
    const identity = liveEventIdentity(event);
    if (seenLiveEvents.has(identity)) return;
    seenLiveEvents.add(identity);
    rows.push({
      id: `live:${event.kind}:${event.ts}:${event.agent}:${event.correlationId ?? "none"}:${stableHash(identity)}`,
      timestamp: event.ts,
      route: event.agents.length > 0 ? event.agents : [event.agent],
      kind: liveKind(event),
      detail: event.detail || event.summary,
      context: event.detail && event.detail !== event.summary ? event.summary : null,
      correlationId: event.correlationId,
      eventId: null,
      source: event.source,
    });
  });
  auditItems.forEach((item) => {
    const actor = agentOf(item);
    const provenance = auditProvenanceOf(item);
    const summary = entryStr(item, "summary") || entryStr(item, "detail") ||
      entryStr(item, "reason") || item.action_kind;
    const target = entryStr(item, "resource_ref") || entryStr(item, "target_resource_ref");
    rows.push({
      id: `audit:${item.seq}`,
      timestamp: item.recorded_at,
      route: [actor],
      kind: activityVerb(item),
      detail: target ? `${item.action_kind} on ${target} - ${summary}` : summary,
      context: `${item.mode} - ${provenance}`,
      correlationId: item.correlation_id,
      eventId: item.event_id,
      source: provenance === "sample" ? "audit-sample" : "audit-operational",
    });
    entryConversation(item)?.forEach((turn, index) => {
      rows.push({
        id: `audit:${item.seq}:conversation:${index}`,
        timestamp: item.recorded_at,
        route: [turn.from, turn.to],
        kind: "handoff",
        detail: turn.text,
        context: item.action_kind,
        correlationId: item.correlation_id,
        eventId: item.event_id,
        source: provenance === "sample" ? "audit-sample" : "audit-operational",
      });
    });
  });
  rows.sort((left, right) => timestamp(left.timestamp) - timestamp(right.timestamp) ||
    left.id.localeCompare(right.id));
  return rows.slice(-AGENT_LOG_LIMIT);
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

function liveKind(event: LiveAgentActivityEvent): AgentLogRow["kind"] {
  if (event.kind === "incident.ticket") return "incident";
  if (event.kind === "conversation.turn") return "handoff";
  return "state";
}

function liveEventIdentity(event: LiveAgentActivityEvent): string {
  return [
    event.kind,
    event.ts,
    event.agent,
    event.agents.join("\u001f"),
    event.state ?? "",
    event.summary,
    event.detail ?? "",
    event.correlationId ?? "",
    event.source,
  ].join("\u001e");
}

function stableHash(value: string): string {
  let hash = 0xcbf29ce484222325n;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= BigInt(value.charCodeAt(index));
    hash = BigInt.asUintN(64, hash * 0x100000001b3n);
  }
  return hash.toString(36);
}

function timestamp(value: string): number {
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? 0 : parsed;
}

function normalize(value: string): string {
  return value.toLocaleLowerCase().replace(/[-_.:/]+/g, " ").replace(/\s+/g, " ").trim();
}
