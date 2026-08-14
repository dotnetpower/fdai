export interface CrossTabSnapshotChannel<T> {
  publish(snapshot: T): void;
  close(): void;
}

interface BroadcastPort {
  onmessage: ((event: MessageEvent<unknown>) => void) | null;
  postMessage(message: unknown): void;
  close(): void;
}

type BroadcastPortFactory = (name: string) => BroadcastPort;

const RFC3339_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/;

export function browserStreamSharingSupported(): boolean {
  return typeof BroadcastChannel !== "undefined"
    && typeof navigator !== "undefined"
    && navigator.locks !== undefined;
}

export function crossTabStreamName(
  channel: string,
  principalId: string | null | undefined,
): string {
  return `fdai:${channel}:${principalId?.trim() || "anonymous"}`;
}

export function shouldAcceptCrossTabSnapshot(
  currentTimestamp: string | null,
  candidateTimestamp: string,
): boolean {
  if (!isCanonicalStreamTimestamp(candidateTimestamp)) return false;
  return currentTimestamp === null || (
    isCanonicalStreamTimestamp(currentTimestamp)
    && Date.parse(candidateTimestamp) >= Date.parse(currentTimestamp)
  );
}

export function isCanonicalStreamTimestamp(value: unknown): value is string {
  return typeof value === "string"
    && value.length <= 64
    && RFC3339_TIMESTAMP.test(value)
    && Number.isFinite(Date.parse(value));
}

export function openCrossTabSnapshotChannel<T>(
  name: string,
  decode: (value: unknown) => T | null,
  onSnapshot: (snapshot: T) => void,
  createPort: BroadcastPortFactory = (channelName) => new BroadcastChannel(channelName),
): CrossTabSnapshotChannel<T> {
  const port = createPort(name);
  port.onmessage = (event) => {
    const snapshot = decode(event.data);
    if (snapshot !== null) onSnapshot(snapshot);
  };
  return {
    publish: (snapshot) => port.postMessage(snapshot),
    close: () => port.close(),
  };
}

export function tryOpenCrossTabSnapshotChannel<T>(
  name: string,
  decode: (value: unknown) => T | null,
  onSnapshot: (snapshot: T) => void,
  createPort?: BroadcastPortFactory,
): CrossTabSnapshotChannel<T> | null {
  try {
    return openCrossTabSnapshotChannel(name, decode, onSnapshot, createPort);
  } catch {
    return null;
  }
}
