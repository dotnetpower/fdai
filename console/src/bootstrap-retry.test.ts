import { describe, expect, it, vi } from "vitest";
import { ReadApiError } from "./api";
import { withStartupTransportRetry } from "./bootstrap-retry";

describe("withStartupTransportRetry", () => {
  it("retries transient network failures using the bounded delay schedule", async () => {
    const operation = vi
      .fn<() => Promise<string>>()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue("ready");
    const wait = vi.fn(async () => undefined);

    await expect(withStartupTransportRetry(operation, {
      delaysMs: [250, 500],
      wait,
    })).resolves.toBe("ready");

    expect(operation).toHaveBeenCalledTimes(3);
    expect(wait.mock.calls).toEqual([[250], [500]]);
  });

  it("does not retry an HTTP or authentication response", async () => {
    const error = new ReadApiError(401, "Authentication token unavailable");
    const operation = vi.fn<() => Promise<never>>().mockRejectedValue(error);
    const wait = vi.fn(async () => undefined);

    await expect(withStartupTransportRetry(operation, {
      delaysMs: [250, 500],
      wait,
    })).rejects.toBe(error);

    expect(operation).toHaveBeenCalledOnce();
    expect(wait).not.toHaveBeenCalled();
  });
});
