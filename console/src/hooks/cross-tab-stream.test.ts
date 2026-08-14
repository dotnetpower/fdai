import { describe, expect, test, vi } from "vitest";
import {
  crossTabStreamName,
  openCrossTabSnapshotChannel,
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
});
