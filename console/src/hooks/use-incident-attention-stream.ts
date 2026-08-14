import { useEffect, useRef, useState } from "preact/hooks";
import { useExclusiveBrowserStreamLeader } from "./browser-stream-leader";
import {
  browserStreamSharingSupported,
  crossTabStreamName,
  openCrossTabSnapshotChannel,
  type CrossTabSnapshotChannel,
} from "./cross-tab-stream";
import { liveReconnectDelay, liveStreamHeaders } from "./use-live-stream";
import { readSseChunk } from "./sse-reader";

const SAFE_ID = /^[\x21-\x7E]{1,256}$/;
const CONTROL_CHAR = /[\u0000-\u001F\u007F]/;
const INCIDENT_STATUSES = new Set(["open", "in_progress"]);

export interface IncidentAttentionProjection {
  readonly incident_id: string;
  readonly correlation_id: string;
  readonly title: string;
  readonly severity: string;
  readonly status: "open" | "in_progress";
  readonly opened_at: string;
  readonly last_updated_at: string;
}

export interface IncidentAttentionSnapshot {
  readonly event: "incident_attention.snapshot";
  readonly ts: string;
  readonly incidents: readonly IncidentAttentionProjection[];
}

export function decodeIncidentAttentionSnapshot(data: string): IncidentAttentionSnapshot | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const snapshot = value as Record<string, unknown>;
  if (
    snapshot.event !== "incident_attention.snapshot"
    || !validTimestamp(snapshot.ts)
    || !Array.isArray(snapshot.incidents)
    || snapshot.incidents.length > 50
  ) return null;
  const incidents = snapshot.incidents.flatMap((item) => validIncident(item) ? [item] : []);
  if (incidents.length !== snapshot.incidents.length) return null;
  return { event: "incident_attention.snapshot", ts: snapshot.ts, incidents };
}

export async function consumeIncidentAttentionSse(
  response: Response,
  onSnapshot: (snapshot: IncidentAttentionSnapshot) => void,
): Promise<void> {
  if (!response.ok) throw new Error(`incident attention stream returned HTTP ${response.status}`);
  if (!response.headers.get("content-type")?.toLowerCase().includes("text/event-stream")) {
    throw new Error("incident attention stream returned an invalid content type");
  }
  if (!response.body) throw new Error("incident attention stream response has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const consumeBlock = (block: string): void => {
    const data = block.split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    const snapshot = data ? decodeIncidentAttentionSnapshot(data) : null;
    if (snapshot) onSnapshot(snapshot);
  };
  while (true) {
    const { value: chunk, done } = await readSseChunk(reader);
    buffer = (buffer + decoder.decode(chunk, { stream: !done })).replace(/\r\n/g, "\n");
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

export function useIncidentAttentionStream(options: {
  readonly url: string;
  readonly principalId?: string | null;
  readonly getAuthorizationHeader: () => Promise<string | null>;
}): readonly IncidentAttentionProjection[] {
  const [incidents, setIncidents] = useState<readonly IncidentAttentionProjection[]>([]);
  const channelRef = useRef<CrossTabSnapshotChannel<IncidentAttentionSnapshot> | null>(null);
  const sharingSupported = browserStreamSharingSupported();
  const streamLeader = useExclusiveBrowserStreamLeader(
    sharingSupported,
    "incident-attention",
    options.principalId,
  );
  const streamEnabled = !sharingSupported || streamLeader;

  useEffect(() => {
    if (!sharingSupported) return undefined;
    const channel = openCrossTabSnapshotChannel(
      crossTabStreamName("incident-attention", options.principalId),
      decodeIncidentAttentionSnapshotValue,
      (snapshot) => setIncidents(snapshot.incidents),
    );
    channelRef.current = channel;
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, [options.principalId, sharingSupported]);

  useEffect(() => {
    if (!streamEnabled) return undefined;
    let cancelled = false;
    let controller: AbortController | null = null;
    let timer: number | null = null;
    let attempt = 0;
    const connect = async (): Promise<void> => {
      if (cancelled || controller) return;
      const active = new AbortController();
      controller = active;
      try {
        const authorization = await options.getAuthorizationHeader();
        const response = await fetch(options.url, {
          headers: liveStreamHeaders(authorization),
          credentials: "omit",
          signal: active.signal,
        });
        await consumeIncidentAttentionSse(response, (snapshot) => {
          if (!cancelled && controller === active) {
            attempt = 0;
            setIncidents(snapshot.incidents);
            channelRef.current?.publish(snapshot);
          }
        });
      } catch {
        // Durable active incidents are replayed after reconnect.
      } finally {
        if (controller === active) controller = null;
        if (!cancelled) {
          timer = window.setTimeout(() => {
            timer = null;
            attempt += 1;
            void connect();
          }, liveReconnectDelay(attempt));
        }
      }
    };
    void connect();
    return () => {
      cancelled = true;
      if (timer !== null) window.clearTimeout(timer);
      controller?.abort();
    };
  }, [options.getAuthorizationHeader, options.url, streamEnabled]);
  return incidents;
}

function decodeIncidentAttentionSnapshotValue(value: unknown): IncidentAttentionSnapshot | null {
  try {
    return decodeIncidentAttentionSnapshot(JSON.stringify(value));
  } catch {
    return null;
  }
}

function validIncident(value: unknown): value is IncidentAttentionProjection {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const incident = value as Record<string, unknown>;
  return SAFE_ID.test(String(incident.incident_id ?? ""))
    && SAFE_ID.test(String(incident.correlation_id ?? ""))
    && safeText(incident.title, 512)
    && safeText(incident.severity, 64)
    && INCIDENT_STATUSES.has(String(incident.status ?? ""))
    && validTimestamp(incident.opened_at)
    && validTimestamp(incident.last_updated_at);
}

function safeText(value: unknown, maxLength: number): value is string {
  return typeof value === "string"
    && value.length >= 1
    && value.length <= maxLength
    && !CONTROL_CHAR.test(value);
}

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 64 && Number.isFinite(Date.parse(value));
}
