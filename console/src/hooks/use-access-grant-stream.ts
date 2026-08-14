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

const SAFE_ID = /^[A-Za-z0-9._:-]{1,256}$/;
const SAFE_TEXT = /^[\x20-\x7E]{1,512}$/;

export interface AccessGrantRequestProjection {
  readonly request_id: string;
  readonly correlation_id: string;
  readonly capability_id: string;
  readonly scope_ref: string;
  readonly grant_mode: string;
  readonly requested_at: string;
  readonly expires_at: string;
  readonly quorum: number;
  readonly status: "pending";
  readonly revision: number;
}

export interface AccessGrantSnapshot {
  readonly event: "access_grant.snapshot";
  readonly ts: string;
  readonly requests: readonly AccessGrantRequestProjection[];
}

export function decodeAccessGrantSnapshot(data: string): AccessGrantSnapshot | null {
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    return null;
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const snapshot = value as Record<string, unknown>;
  if (
    snapshot.event !== "access_grant.snapshot" ||
    !validTimestamp(snapshot.ts) ||
    !Array.isArray(snapshot.requests) ||
    snapshot.requests.length > 50
  ) return null;
  const requests = snapshot.requests.flatMap((item) => validRequest(item) ? [item] : []);
  if (requests.length !== snapshot.requests.length) return null;
  return { event: "access_grant.snapshot", ts: snapshot.ts, requests };
}

export async function consumeAccessGrantSse(
  response: Response,
  onSnapshot: (snapshot: AccessGrantSnapshot) => void,
): Promise<void> {
  if (!response.ok) throw new Error(`access grant stream returned HTTP ${response.status}`);
  if (!response.headers.get("content-type")?.toLowerCase().includes("text/event-stream")) {
    throw new Error("access grant stream returned an invalid content type");
  }
  if (!response.body) throw new Error("access grant stream response has no body");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const consumeBlock = (block: string): void => {
    const data = block.split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    const snapshot = data ? decodeAccessGrantSnapshot(data) : null;
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

export function useAccessGrantStream(options: {
  readonly url: string;
  readonly enabled: boolean;
  readonly principalId?: string | null;
  readonly getAuthorizationHeader: () => Promise<string | null>;
}): readonly AccessGrantRequestProjection[] {
  const [requests, setRequests] = useState<readonly AccessGrantRequestProjection[]>([]);
  const channelRef = useRef<CrossTabSnapshotChannel<AccessGrantSnapshot> | null>(null);
  const sharingSupported = browserStreamSharingSupported();
  const streamLeader = useExclusiveBrowserStreamLeader(
    options.enabled && sharingSupported,
    "access-grant-attention",
    options.principalId,
  );
  const streamEnabled = options.enabled && (!sharingSupported || streamLeader);

  useEffect(() => {
    if (!options.enabled || !sharingSupported) return undefined;
    const channel = openCrossTabSnapshotChannel(
      crossTabStreamName("access-grant-attention", options.principalId),
      decodeAccessGrantSnapshotValue,
      (snapshot) => setRequests(snapshot.requests),
    );
    channelRef.current = channel;
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, [options.enabled, options.principalId, sharingSupported]);

  useEffect(() => {
    if (!streamEnabled) {
      setRequests([]);
      return undefined;
    }
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
        await consumeAccessGrantSse(response, (snapshot) => {
          if (!cancelled && controller === active) {
            attempt = 0;
            setRequests(snapshot.requests);
            channelRef.current?.publish(snapshot);
          }
        });
      } catch {
        // Durable state is replayed after the bounded reconnect delay.
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
  return requests;
}

function decodeAccessGrantSnapshotValue(value: unknown): AccessGrantSnapshot | null {
  try {
    return decodeAccessGrantSnapshot(JSON.stringify(value));
  } catch {
    return null;
  }
}

function validRequest(value: unknown): value is AccessGrantRequestProjection {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const request = value as Record<string, unknown>;
  return SAFE_ID.test(String(request.request_id ?? ""))
    && SAFE_ID.test(String(request.correlation_id ?? ""))
    && SAFE_ID.test(String(request.capability_id ?? ""))
    && typeof request.scope_ref === "string"
    && request.scope_ref.startsWith("scope://")
    && SAFE_TEXT.test(request.scope_ref)
    && SAFE_ID.test(String(request.grant_mode ?? ""))
    && validTimestamp(request.requested_at)
    && validTimestamp(request.expires_at)
    && request.status === "pending"
    && Number.isInteger(request.quorum)
    && Number(request.quorum) >= 1
    && Number.isInteger(request.revision)
    && Number(request.revision) >= 0;
}

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 64 && Number.isFinite(Date.parse(value));
}
