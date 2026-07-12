/**
 * Agent-activity SSE stream hook (Track B).
 *
 * Subscribes to the read-API's `GET /agents/stream` SSE endpoint via
 * `EventSource` and hands each decoded {@link AgentActivityMessage} to a
 * consumer. Where {@link useLiveStream} is action-centric (pipeline stage
 * frames), this hook is agent-centric: per-agent status, incident tickets,
 * and agent-to-agent conversation turns.
 *
 * The emitter publishes with the default (`message`) SSE event name and a
 * JSON payload whose `type` field discriminates the three kinds, so the
 * hook reads `es.onmessage` and demultiplexes on `payload.type`.
 *
 * Pure read consumer - it issues no privileged calls. Reconnection is
 * delegated to the browser; the hook closes the connection while the tab is
 * hidden so a backgrounded tab cannot flood the backend with reconnects.
 */

import { useEffect, useRef, useState } from "preact/hooks";

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
}

export interface ConversationTurnMessage {
  readonly type: "conversation.turn";
  readonly correlation_id: string;
  readonly from_agent: string;
  readonly to_agent: string;
  readonly kind: TurnKind;
  readonly text: string;
  readonly ts: string;
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
  readonly withCredentials?: boolean;
}

export interface UseAgentStreamResult {
  readonly status: AgentStreamStatus;
  readonly lastError: string | null;
}

export function useAgentStream(options: UseAgentStreamOptions): UseAgentStreamResult {
  const [status, setStatus] = useState<AgentStreamStatus>(
    typeof EventSource === "undefined" ? "unsupported" : "idle",
  );
  const [lastError, setLastError] = useState<string | null>(null);

  const onEventRef = useRef(options.onEvent);
  const onStatusRef = useRef(options.onStatus);
  onEventRef.current = options.onEvent;
  onStatusRef.current = options.onStatus;

  const url = options.url;
  const withCredentials = options.withCredentials ?? false;

  useEffect(() => {
    if (typeof EventSource === "undefined") return undefined;

    let cancelled = false;
    let source: EventSource | null = null;

    const connect = () => {
      if (cancelled || source) return;
      setStatus("connecting");
      onStatusRef.current?.("connecting");

      const es = new EventSource(url, { withCredentials });
      source = es;

      // The emitter publishes semantic frames with the default (`message`)
      // event name; the `hello` boot frame is named and ignored here.
      es.onmessage = (raw) => {
        if (cancelled || source !== es) return;
        try {
          const parsed = JSON.parse(raw.data) as AgentActivityMessage;
          onEventRef.current(parsed);
        } catch (err) {
          setLastError(err instanceof Error ? err.message : String(err));
        }
      };

      es.onopen = () => {
        if (cancelled || source !== es) return;
        setStatus("open");
        setLastError(null);
        onStatusRef.current?.("open");
      };

      es.onerror = () => {
        if (cancelled || source !== es) return;
        const nextStatus: AgentStreamStatus =
          es.readyState === EventSource.CLOSED ? "closed" : "connecting";
        setStatus(nextStatus);
        if (es.readyState === EventSource.CLOSED) {
          setLastError("connection to agent stream closed");
        }
        onStatusRef.current?.(nextStatus);
      };
    };

    const disconnect = (nextStatus: AgentStreamStatus) => {
      if (source) {
        source.close();
        source = null;
      }
      setStatus(nextStatus);
      onStatusRef.current?.(nextStatus);
    };

    const isHidden = () => typeof document !== "undefined" && document.hidden;

    const handleVisibility = () => {
      if (cancelled) return;
      if (isHidden()) {
        disconnect("idle");
      } else {
        connect();
      }
    };

    if (isHidden()) {
      setStatus("idle");
      onStatusRef.current?.("idle");
    } else {
      connect();
    }

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", handleVisibility);
    }

    return () => {
      cancelled = true;
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibility);
      }
      if (source) {
        source.close();
        source = null;
      }
    };
  }, [url, withCredentials]);

  return { status, lastError };
}
