import { useEffect, useRef, useState } from "preact/hooks";
import { useExclusiveBrowserStreamLeader } from "./browser-stream-leader";
import {
  browserStreamSharingSupported,
  crossTabStreamName,
  isCanonicalStreamTimestamp,
  shouldAcceptCrossTabSnapshot,
  tryOpenCrossTabSnapshotChannel,
  type CrossTabSnapshotChannel,
} from "./cross-tab-stream";
import {
  consumeSseFrames,
  isTransientSseStatus,
  useAuthenticatedSse,
} from "./sse-client";

const BOUNDED_PRINTABLE_TOKEN = /^[\x21-\x7E]{1,256}$/;
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
    || !isCanonicalStreamTimestamp(snapshot.ts)
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
  await consumeSseFrames(response, (frame) => {
    const snapshot = decodeIncidentAttentionSnapshot(frame.data);
    if (snapshot) onSnapshot(snapshot);
  });
}

export function useIncidentAttentionStream(options: {
  readonly url: string;
  readonly principalId?: string | null;
  readonly getAuthorizationHeader: () => Promise<string | null>;
}): readonly IncidentAttentionProjection[] {
  const [incidents, setIncidents] = useState<readonly IncidentAttentionProjection[]>([]);
  const channelRef = useRef<CrossTabSnapshotChannel<IncidentAttentionSnapshot> | null>(null);
  const latestSnapshotAtRef = useRef<string | null>(null);
  const sharingSupported = browserStreamSharingSupported();
  const streamLeader = useExclusiveBrowserStreamLeader(
    sharingSupported,
    "incident-attention",
    options.principalId,
  );
  const streamEnabled = streamLeader;

  useEffect(() => {
    latestSnapshotAtRef.current = null;
    setIncidents([]);
  }, [options.principalId]);

  useEffect(() => {
    if (!sharingSupported) return undefined;
    const channel = tryOpenCrossTabSnapshotChannel(
      crossTabStreamName("incident-attention", options.principalId),
      decodeIncidentAttentionSnapshotValue,
      (snapshot) => {
        if (!shouldAcceptCrossTabSnapshot(latestSnapshotAtRef.current, snapshot.ts)) return;
        latestSnapshotAtRef.current = snapshot.ts;
        setIncidents(snapshot.incidents);
      },
    );
    if (channel === null) return undefined;
    channelRef.current = channel;
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, [options.principalId, sharingSupported]);

  useAuthenticatedSse({
    url: options.url,
    enabled: streamEnabled,
    pauseWhenHidden: false,
    resumeFromLastEventId: false,
    getAuthorizationHeader: options.getAuthorizationHeader,
    shouldRetryStatus: retryAttentionStatus,
    onFrame: (frame) => {
      const snapshot = decodeIncidentAttentionSnapshot(frame.data);
      if (
        !snapshot ||
        !shouldAcceptCrossTabSnapshot(latestSnapshotAtRef.current, snapshot.ts)
      ) return false;
      latestSnapshotAtRef.current = snapshot.ts;
      setIncidents(snapshot.incidents);
      channelRef.current?.publish(snapshot);
      return true;
    },
  });
  return incidents;
}

function retryAttentionStatus(status: number): boolean {
  return status === 401 || isTransientSseStatus(status);
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
  return typeof incident.incident_id === "string"
    && BOUNDED_PRINTABLE_TOKEN.test(incident.incident_id)
    && typeof incident.correlation_id === "string"
    && BOUNDED_PRINTABLE_TOKEN.test(incident.correlation_id)
    && safeText(incident.title, 512)
    && safeText(incident.severity, 64)
    && typeof incident.status === "string"
    && INCIDENT_STATUSES.has(incident.status)
    && isCanonicalStreamTimestamp(incident.opened_at)
    && isCanonicalStreamTimestamp(incident.last_updated_at);
}

function safeText(value: unknown, maxLength: number): value is string {
  return typeof value === "string"
    && value.length >= 1
    && value.length <= maxLength
    && !CONTROL_CHAR.test(value);
}
