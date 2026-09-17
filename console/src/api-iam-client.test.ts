import { afterEach, describe, expect, test, vi } from "vitest";
import { IamApiClient } from "./api-iam-client";
import type { OperatorApiTransport } from "./api-transport";

const rosterPayload = {
  items: [
    {
      provider: "entra",
      subject_id: "user-1",
      display_name: "Example Operator",
      principal_type: "person",
      roles: ["Reader"],
      username: "operator@example.com",
      active: true,
    },
  ],
};

function clientWith(getJson: (path: string) => Promise<unknown>): IamApiClient {
  return new IamApiClient({ getJson } as unknown as OperatorApiTransport);
}

afterEach(() => {
  vi.useRealTimers();
});

describe("IAM API client cache", () => {
  test("coalesces and briefly reuses roster reads", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-17T00:00:00Z"));
    const getJson = vi.fn(async () => rosterPayload);
    const client = clientWith(getJson);

    const first = client.roster();
    const overlapping = client.roster();

    expect(overlapping).toBe(first);
    await expect(first).resolves.toHaveLength(1);
    await expect(client.roster()).resolves.toHaveLength(1);
    expect(getJson).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(30_001);
    await expect(client.roster()).resolves.toHaveLength(1);
    expect(getJson).toHaveBeenCalledTimes(2);
  });

  test("does not cache a failed roster read", async () => {
    const getJson = vi.fn()
      .mockRejectedValueOnce(new Error("directory unavailable"))
      .mockResolvedValueOnce(rosterPayload);
    const client = clientWith(getJson);

    await expect(client.roster()).rejects.toThrow("directory unavailable");
    await expect(client.roster()).resolves.toHaveLength(1);
    expect(getJson).toHaveBeenCalledTimes(2);
  });
});
