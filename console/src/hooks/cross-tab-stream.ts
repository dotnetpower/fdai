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
