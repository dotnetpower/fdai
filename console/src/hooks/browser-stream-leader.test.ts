import { describe, expect, test, vi } from "vitest";
import {
  browserStreamLockName,
  holdBrowserStreamLeadership,
  reportBrowserStreamLeadershipFailure,
} from "./browser-stream-leader";

describe("browser stream leadership", () => {
  test("scopes one notification leader to the signed-in principal", () => {
    expect(browserStreamLockName("notifications", "principal-1"))
      .toBe("fdai:notifications:principal-1");
    expect(browserStreamLockName("notifications", null))
      .toBe("fdai:notifications:anonymous");
  });

  test("holds leadership until the owning tab aborts", async () => {
    const controller = new AbortController();
    const states: boolean[] = [];
    const requestLock = vi.fn(async (
      _name: string,
      _signal: AbortSignal,
      callback: () => Promise<void>,
    ) => {
      await callback();
    });

    const holding = holdBrowserStreamLeadership(
      requestLock,
      "fdai:notifications:principal-1",
      controller.signal,
      (leader) => states.push(leader),
    );
    await vi.waitFor(() => expect(states).toEqual([true]));
    controller.abort();
    await holding;

    expect(states).toEqual([true, false]);
    expect(requestLock).toHaveBeenCalledOnce();
    expect(requestLock.mock.calls[0]?.[1]).toBe(controller.signal);
  });

  test("never publishes leadership when lock acquisition fails", async () => {
    const states: boolean[] = [];
    const requestLock = vi.fn(async () => {
      throw new Error("lock manager unavailable");
    });

    await expect(holdBrowserStreamLeadership(
      requestLock,
      "fdai:notifications:principal-1",
      new AbortController().signal,
      (leader) => states.push(leader),
    )).rejects.toThrow("lock manager unavailable");

    expect(states).toEqual([]);
  });

  test("reports an active lock acquisition failure but ignores cleanup aborts", () => {
    const states: boolean[] = [];
    const failures: string[] = [];
    const active = new AbortController();
    reportBrowserStreamLeadershipFailure(
      active.signal,
      (leader) => states.push(leader),
      () => failures.push("failed"),
    );

    const cancelled = new AbortController();
    cancelled.abort();
    reportBrowserStreamLeadershipFailure(
      cancelled.signal,
      (leader) => states.push(leader),
      () => failures.push("cancelled"),
    );

    expect(states).toEqual([false]);
    expect(failures).toEqual(["failed"]);
  });
});
