/**
 * Authenticated agent-activity SSE stream.
 *
 * `EventSource` cannot attach the bearer header required by the read API, so
 * this hook uses fetch streaming. It keeps visibility gating and reconnect
 * behavior while decoding only the three supported agent frames.
 */

import { useEffect, useRef, useState } from "preact/hooks";
import { loadConfig } from "../config";
import {
  mergeObservationSource,
  normalizeObservationSource,
  type FrameSource,
  type ObservationSource,
} from "./observation-source";

export interface AgentStreamDescriptor {
  readonly url: string;
}

export function agentStreamDescriptor(): AgentStreamDescriptor {
  const config = loadConfig();
  const base = config.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
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
  | ConversationTurnMessage;

export type AgentStreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "unsupported";

export interface UseAgentStreamOptions {
  readonly url: string;
  readonly onEvent: (event: AgentActivityMessage) => void;
  readonly onStatus?: (status: AgentStreamStatus) => void;
  readonly getAuthorizationHeader?: () => Promise<string | null>;
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
  const headers = new Headers({ accept: "text/event-stream" });
  if (authorization) headers.set("authorization", authorization);
  return headers;
}

export function agentReconnectDelay(attempt: number): number {
  return Math.min(30000, 1000 * (2 ** Math.min(attempt, 5)));
}

export function isPermanentAgentStreamFailure(status: number): boolean {
  return status === 401 || status === 403;
}

export function shouldResumeAgentStream(permanentFailure: boolean, hidden: boolean): boolean {
  return !permanentFailure && !hidden;
}

export async function consumeAgentActivitySse(
  response: Response,
  onEvent: (event: AgentActivityMessage) => void,
): Promise<void> {
  if (!response.ok) throw new Error(`agent stream returned HTTP ${response.status}`);
  const contentType = response.headers.get("content-type")?.toLowerCase() ?? "";
  if (!contentType.includes("text/event-stream")) {
    throw new Error("agent stream returned an invalid content type");
  }
  if (!response.body) throw new Error("agent stream response has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const consumeBlock = (block: string): void => {
    const data = block.split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (!data) return;
    const event = decodeAgentActivityMessage(data);
    if (event) onEvent(event);
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer = (buffer + decoder.decode(value, { stream: !done })).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      consumeBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
    if (done) {
      if (buffer.trim()) consumeBlock(buffer);
      return;
    }
  }
}

export function useAgentStream(options: UseAgentStreamOptions): UseAgentStreamResult {
  const [status, setStatus] = useState<AgentStreamStatus>(
    typeof fetch === "undefined" ? "unsupported" : "idle",
  );
  const [lastError, setLastError] = useState<string | null>(null);
  const [source, setSource] = useState<ObservationSource>("unknown");
  const onEventRef = useRef(options.onEvent);
  const onStatusRef = useRef(options.onStatus);
  onEventRef.current = options.onEvent;
  onStatusRef.current = options.onStatus;
  const { url, getAuthorizationHeader } = options;

  useEffect(() => {
    if (typeof fetch === "undefined") return undefined;
    let cancelled = false;
    let controller: AbortController | null = null;
    let reconnectTimer: number | null = null;
    let reconnectAttempt = 0;
    let permanentFailure = false;
    const publishStatus = (next: AgentStreamStatus): void => {
      setStatus(next);
      onStatusRef.current?.(next);
    };
    const isHidden = (): boolean => typeof document !== "undefined" && document.hidden;
    const scheduleReconnect = (): void => {
      if (cancelled || permanentFailure || isHidden()) return;
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      const delay = agentReconnectDelay(reconnectAttempt);
      reconnectAttempt += 1;
      reconnectTimer = window.setTimeout(() => {
        reconnectTimer = null;
        void connect();
      }, delay);
    };
    const connect = async (): Promise<void> => {
      if (cancelled || controller) return;
      publishStatus("connecting");
      const active = new AbortController();
      controller = active;
      try {
        const authorization = await getAuthorizationHeader?.() ?? null;
        if (cancelled || controller !== active) return;
        const response = await fetch(url, {
          method: "GET",
          headers: agentStreamHeaders(authorization),
          credentials: "omit",
          signal: active.signal,
        });
        if (!response.ok) {
          permanentFailure = isPermanentAgentStreamFailure(response.status);
          throw new Error(`agent stream returned HTTP ${response.status}`);
        }
        publishStatus("open");
        setLastError(null);
        await consumeAgentActivitySse(response, (event) => {
          if (!cancelled && controller === active) {
            reconnectAttempt = 0;
            setSource((current) => mergeObservationSource(
              current,
              normalizeObservationSource(event.source),
            ));
            onEventRef.current(event);
          }
        });
        if (!cancelled && controller === active) {
          setLastError("connection to agent stream closed");
          publishStatus("closed");
        }
      } catch (error) {
        if (!cancelled && !active.signal.aborted) {
          setLastError(error instanceof Error ? error.message : String(error));
          publishStatus("closed");
        }
      } finally {
        if (controller === active) controller = null;
        scheduleReconnect();
      }
    };
    const disconnect = (next: AgentStreamStatus): void => {
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
      controller?.abort();
      controller = null;
      publishStatus(next);
    };
    const handleVisibility = (): void => {
      if (cancelled) return;
      const hidden = isHidden();
      if (hidden) disconnect("idle");
      else if (shouldResumeAgentStream(permanentFailure, hidden)) void connect();
    };
    if (isHidden()) publishStatus("idle");
    else void connect();
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", handleVisibility);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      controller?.abort();
    };
  }, [url, getAuthorizationHeader]);

  return { status, lastError, source };
}
