import { describe, expect, test, vi } from "vitest";
import {
  crossTabStreamName,
  openCrossTabSnapshotChannel,
  shouldAcceptCrossTabSnapshot,
  tryOpenCrossTabSnapshotChannel,
} from "./cross-tab-stream";

describe("cross-tab stream snapshots", () => {
  test("scopes snapshot delivery to one principal and channel", () => {
    expect(crossTabStreamName("incident-attention", "principal-1"))
      .toBe("fdai:incident-attention:principal-1");
  });

  test("publishes and accepts only decoded snapshots", () => {
    const postMessage = vi.fn();
    const close = vi.fn();
    const port = { onmessage: null as ((event: MessageEvent<unknown>) => void) | null, postMessage, close };
    const received: string[] = [];
    const channel = openCrossTabSnapshotChannel(
      "fdai:incident-attention:principal-1",
      (value) => typeof value === "string" ? value : null,
      (value) => received.push(value),
      () => port,
    );

    channel.publish("snapshot-1");
    port.onmessage?.({ data: "snapshot-2" } as MessageEvent<unknown>);
    port.onmessage?.({ data: 3 } as MessageEvent<unknown>);
    channel.close();

    expect(postMessage).toHaveBeenCalledWith("snapshot-1");
    expect(received).toEqual(["snapshot-2"]);
    expect(close).toHaveBeenCalledOnce();
  });

  test("rejects a stale snapshot after leader turnover", () => {
    expect(shouldAcceptCrossTabSnapshot(null, "2026-08-14T01:00:00Z")).toBe(true);
    expect(shouldAcceptCrossTabSnapshot(null, "2026/08/14 01:00:00")).toBe(false);
    expect(shouldAcceptCrossTabSnapshot("2026/08/14 01:00:00", "2026-08-14T01:00:01Z"))
      .toBe(false);
    expect(shouldAcceptCrossTabSnapshot(
      "2026-08-14T01:00:00Z",
      "2026-08-14T01:00:01Z",
    )).toBe(true);
    expect(shouldAcceptCrossTabSnapshot(
      "2026-08-14T01:00:01Z",
      "2026-08-14T01:00:00Z",
    )).toBe(false);
  });

  test("degrades an unavailable BroadcastChannel without throwing", () => {
    expect(tryOpenCrossTabSnapshotChannel(
      "fdai:incident-attention:principal-1",
      () => null,
      () => undefined,
      () => { throw new Error("channel blocked"); },
    )).toBeNull();
  });
});
