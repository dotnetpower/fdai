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

const CANONICAL_GRANT_ID = /^[A-Za-z0-9._:-]{1,256}$/;
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
    !isCanonicalStreamTimestamp(snapshot.ts) ||
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
  await consumeSseFrames(response, (frame) => {
    const snapshot = decodeAccessGrantSnapshot(frame.data);
    if (snapshot) onSnapshot(snapshot);
  });
}

export function useAccessGrantStream(options: {
  readonly url: string;
  readonly enabled: boolean;
  readonly principalId?: string | null;
  readonly getAuthorizationHeader: () => Promise<string | null>;
}): readonly AccessGrantRequestProjection[] {
  const [requests, setRequests] = useState<readonly AccessGrantRequestProjection[]>([]);
  const channelRef = useRef<CrossTabSnapshotChannel<AccessGrantSnapshot> | null>(null);
  const latestSnapshotAtRef = useRef<string | null>(null);
  const sharingSupported = browserStreamSharingSupported();
  const streamLeader = useExclusiveBrowserStreamLeader(
    options.enabled && sharingSupported,
    "access-grant-attention",
    options.principalId,
  );
  const streamEnabled = options.enabled && streamLeader;

  useEffect(() => {
    latestSnapshotAtRef.current = null;
    setRequests([]);
  }, [options.enabled, options.principalId]);

  useEffect(() => {
    if (!options.enabled || !sharingSupported) return undefined;
    const channel = tryOpenCrossTabSnapshotChannel(
      crossTabStreamName("access-grant-attention", options.principalId),
      decodeAccessGrantSnapshotValue,
      (snapshot) => {
        if (!shouldAcceptCrossTabSnapshot(latestSnapshotAtRef.current, snapshot.ts)) return;
        latestSnapshotAtRef.current = snapshot.ts;
        setRequests(snapshot.requests);
      },
    );
    if (channel === null) return undefined;
    channelRef.current = channel;
    return () => {
      channelRef.current = null;
      channel.close();
    };
  }, [options.enabled, options.principalId, sharingSupported]);

  useEffect(() => {
    if (!options.enabled) {
      setRequests([]);
    }
  }, [options.enabled]);

  useAuthenticatedSse({
    url: options.url,
    enabled: streamEnabled,
    pauseWhenHidden: false,
    resumeFromLastEventId: false,
    getAuthorizationHeader: options.getAuthorizationHeader,
    shouldRetryStatus: retryAttentionStatus,
    onFrame: (frame) => {
      const snapshot = decodeAccessGrantSnapshot(frame.data);
      if (
        !snapshot ||
        !shouldAcceptCrossTabSnapshot(latestSnapshotAtRef.current, snapshot.ts)
      ) return false;
      latestSnapshotAtRef.current = snapshot.ts;
      setRequests(snapshot.requests);
      channelRef.current?.publish(snapshot);
      return true;
    },
  });
  return requests;
}

function retryAttentionStatus(status: number): boolean {
  return status === 401 || isTransientSseStatus(status);
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
  return CANONICAL_GRANT_ID.test(String(request.request_id ?? ""))
    && CANONICAL_GRANT_ID.test(String(request.correlation_id ?? ""))
    && CANONICAL_GRANT_ID.test(String(request.capability_id ?? ""))
    && typeof request.scope_ref === "string"
    && request.scope_ref.startsWith("scope://")
    && SAFE_TEXT.test(request.scope_ref)
    && CANONICAL_GRANT_ID.test(String(request.grant_mode ?? ""))
    && isCanonicalStreamTimestamp(request.requested_at)
    && isCanonicalStreamTimestamp(request.expires_at)
    && request.status === "pending"
    && Number.isInteger(request.quorum)
    && Number(request.quorum) >= 1
    && Number.isInteger(request.revision)
    && Number(request.revision) >= 0;
}
