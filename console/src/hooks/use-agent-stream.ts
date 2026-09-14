/**
 * Authenticated agent-activity SSE stream.
 *
 * `EventSource` cannot attach the bearer header required by the Operator API, so
 * this hook uses fetch streaming. It keeps visibility gating and reconnect
 * behavior while decoding only the supported agent frames.
 */

import { useState } from "preact/hooks";
import { loadConfig } from "../config";
import {
  mergeObservationSource,
  normalizeObservationSource,
  type FrameSource,
  type ObservationSource,
} from "./observation-source";
import {
  authenticatedSseHeaders,
  consumeSseFrames,
  isTransientSseStatus,
  sseReconnectDelay,
  useAuthenticatedSse,
} from "./sse-client";
import {
  decodeAgentOperationalActivity,
  type AgentOperationalActivityMessage,
} from "../agent-operational-activity";
export type { AgentOperationalActivityMessage } from "../agent-operational-activity";

export interface AgentStreamDescriptor {
  readonly url: string;
}

export function agentStreamDescriptor(): AgentStreamDescriptor {
  const config = loadConfig();
  const base = config.operatorApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
  return {
    url: `${base.replace(/\/$/, "")}/agents/stream`,
  };
}

/** Agent status ring - mirrors `AgentState` in `agent_activity_stream.py`. */
export type AgentStatus =
  | "idle"
  | "watching"
  | "collecting"
  | "analyzing"
  | "deciding"
  | "executing"
  | "approving"
  | "auditing";

/** Incident ticket lifecycle - mirrors `TicketStatus`. */
export type TicketStatus = "open" | "investigating" | "resolved";

/** Conversation-turn role - mirrors `TurnKind`. */
export type TurnKind = "question" | "answer" | "handoff";

export interface AgentStateMessage {
  readonly type: "agent.state";
  readonly agent: string;
  readonly state: AgentStatus;
  readonly ts: string;
  readonly correlation_id: string | null;
  readonly detail: string | null;
  readonly source?: FrameSource;
}

export interface IncidentTicketMessage {
  readonly type: "incident.ticket";
  readonly ticket_id: string;
  readonly correlation_id: string;
  readonly status: TicketStatus;
  readonly title: string;
  readonly severity: string;
  readonly involved_agents: readonly string[];
  readonly rca: string | null;
  readonly ts: string;
  readonly source?: FrameSource;
}

export interface ConversationTurnMessage {
  readonly type: "conversation.turn";
  readonly correlation_id: string;
  readonly from_agent: string;
  readonly to_agent: string;
  readonly kind: TurnKind;
  readonly text: string;
  readonly ts: string;
  readonly source?: FrameSource;
}

/** One decoded agent-activity frame (discriminated by `type`). */
export type AgentActivityMessage =
  | AgentStateMessage
  | IncidentTicketMessage
  | ConversationTurnMessage
  | AgentOperationalActivityMessage;

export type AgentStreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "unsupported";

export interface UseAgentStreamOptions {
  readonly url: string;
  readonly onEvent: (event: AgentActivityMessage) => void;
  readonly onGap?: (droppedBefore: number) => void;
  readonly onStatus?: (status: AgentStreamStatus) => void;
  readonly getAuthorizationHeader?: () => Promise<string | null>;
  readonly enabled?: boolean;
}

export interface UseAgentStreamResult {
  readonly status: AgentStreamStatus;
  readonly lastError: string | null;
  readonly source: ObservationSource;
}

const AGENT_STATES: ReadonlySet<string> = new Set([
  "idle", "watching", "collecting", "analyzing", "deciding", "executing", "approving", "auditing",
]);
const TICKET_STATES: ReadonlySet<string> = new Set(["open", "investigating", "resolved"]);
const TURN_KINDS: ReadonlySet<string> = new Set(["question", "answer", "handoff"]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export function decodeAgentActivityMessage(data: string): AgentActivityMessage | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (!isRecord(value) || typeof value.type !== "string") return null;
  const operational = decodeAgentOperationalActivity(value);
  if (operational !== null) return operational;
  if (
    value.type === "agent.state" &&
    typeof value.agent === "string" &&
    typeof value.state === "string" && AGENT_STATES.has(value.state) &&
    typeof value.ts === "string" && isNullableString(value.correlation_id) &&
    isNullableString(value.detail)
  ) return { ...value, source: normalizeObservationSource(value.source) } as unknown as AgentStateMessage;
  if (
    value.type === "incident.ticket" &&
    typeof value.ticket_id === "string" && typeof value.correlation_id === "string" &&
    typeof value.status === "string" && TICKET_STATES.has(value.status) &&
    typeof value.title === "string" && typeof value.severity === "string" &&
    Array.isArray(value.involved_agents) &&
    value.involved_agents.every((agent) => typeof agent === "string") &&
    isNullableString(value.rca) && typeof value.ts === "string"
  ) return { ...value, source: normalizeObservationSource(value.source) } as unknown as IncidentTicketMessage;
  if (
    value.type === "conversation.turn" && typeof value.correlation_id === "string" &&
    typeof value.from_agent === "string" && typeof value.to_agent === "string" &&
    typeof value.kind === "string" && TURN_KINDS.has(value.kind) &&
    typeof value.text === "string" && typeof value.ts === "string"
  ) return { ...value, source: normalizeObservationSource(value.source) } as unknown as ConversationTurnMessage;
  return null;
}

export function agentStreamHeaders(authorization: string | null): Headers {
  return authenticatedSseHeaders(authorization);
}

export function agentReconnectDelay(attempt: number): number {
  return sseReconnectDelay(attempt);
}

export function isPermanentAgentStreamFailure(status: number): boolean {
  return status === 401;
}

export function shouldResumeAgentStream(permanentFailure: boolean, hidden: boolean): boolean {
  return !permanentFailure && !hidden;
}

export async function consumeAgentActivitySse(
  response: Response,
  onEvent: (event: AgentActivityMessage) => void,
): Promise<void> {
  await consumeSseFrames(response, (frame) => {
    const event = decodeAgentActivityMessage(frame.data);
    if (event) onEvent(event);
  }, { strictEventId: false });
}

export function useAgentStream(options: UseAgentStreamOptions): UseAgentStreamResult {
  const [source, setSource] = useState<ObservationSource>("unknown");
  const { url, getAuthorizationHeader, enabled = true } = options;
  const connection = useAuthenticatedSse({
    url,
    getAuthorizationHeader: getAuthorizationHeader ?? noAuthorization,
    enabled,
    pauseWhenHidden: true,
    resumeFromLastEventId: false,
    strictEventId: false,
    shouldRetryStatus: isTransientSseStatus,
    onStatus: (next) => options.onStatus?.(next),
    onFrame: (frame) => {
      if (frame.droppedBefore > 0) options.onGap?.(frame.droppedBefore);
      const event = decodeAgentActivityMessage(frame.data);
      if (!event) return false;
      setSource((current) => mergeObservationSource(
        current,
        event.type === "agent.operational-activity"
          ? "runtime-observed"
          : normalizeObservationSource(event.source),
      ));
      options.onEvent(event);
      return true;
    },
  });
  return {
    status: connection.status,
    lastError: connection.lastError,
    source,
  };
}

async function noAuthorization(): Promise<null> {
  return null;
}

export function agentActivityTimestamp(message: AgentActivityMessage): string {
  return message.type === "agent.operational-activity" ? message.observed_at : message.ts;
}
