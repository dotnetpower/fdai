import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  installBackendHealthRefresh,
  type BackendHealthRefreshHost,
} from "./backend-health-refresh";
import { BACKEND_HEALTH_REFRESH_MS, OFFLINE_HEALTH } from "./backend-health";
import type { BackendHealth } from "./backend-types";

const health: BackendHealth = { available: true, mode: "semantic-core", model: "example-mini", endpoint: null };

function refreshHost() {
  let visible = true;
  let online = true;
  const listeners = new Map<string, () => void>();
  const host: BackendHealthRefreshHost = {
    setTimeout: (callback, delay) => setTimeout(callback, delay),
    clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    addWindowListener: (type, listener) => { listeners.set(type, listener); },
    removeWindowListener: (type) => { listeners.delete(type); },
    addVisibilityListener: (listener) => { listeners.set("visibilitychange", listener); },
    removeVisibilityListener: () => { listeners.delete("visibilitychange"); },
    canRefresh: () => visible && online,
    isOnline: () => online,
  };
  return {
    host, listeners,
    setVisible: (value: boolean) => {
      visible = value;
      listeners.get("visibilitychange")?.();
    },
    setOnline: (value: boolean) => {
      online = value;
      listeners.get(value ? "online" : "offline")?.();
    },
  };
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

describe("open Deck health refresh", () => {
  it("refreshes after each 30-second interval and stops completely on close/unmount", async () => {
    const fixture = refreshHost();
    const probe = vi.fn(async () => health);
    const onHealth = vi.fn();
    const stop = installBackendHealthRefresh(probe, onHealth, fixture.host);
    await vi.advanceTimersByTimeAsync(0);
    expect(onHealth).toHaveBeenCalledWith(health);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS - 1);
    expect(probe).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(probe).toHaveBeenCalledTimes(2);
    stop();
    expect(fixture.listeners.size).toBe(0);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS * 2);
    expect(probe).toHaveBeenCalledTimes(2);
  });

  it("pauses hidden and offline tabs and refreshes when both conditions recover", async () => {
    const fixture = refreshHost();
    fixture.setVisible(false);
    const probe = vi.fn(async () => health);
    const stop = installBackendHealthRefresh(probe, vi.fn(), fixture.host);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS * 3);
    expect(probe).toHaveBeenCalledTimes(1);
    fixture.setVisible(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(probe).toHaveBeenCalledTimes(2);
    fixture.setOnline(false);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS * 3);
    expect(probe).toHaveBeenCalledTimes(2);
    fixture.setVisible(false);
    fixture.setOnline(true);
    expect(probe).toHaveBeenCalledTimes(2);
    fixture.setVisible(true);
    await vi.advanceTimersByTimeAsync(0);
    expect(probe).toHaveBeenCalledTimes(3);
    stop();
  });

  it("reads once on explicit hidden Deck open without repeating in the background", async () => {
    const fixture = refreshHost();
    fixture.setVisible(false);
    const probe = vi.fn(async () => health);
    const onHealth = vi.fn();
    const stop = installBackendHealthRefresh(probe, onHealth, fixture.host);

    await vi.advanceTimersByTimeAsync(0);
    expect(probe).toHaveBeenCalledTimes(1);
    expect(onHealth).toHaveBeenCalledWith(health);
    expect(vi.getTimerCount()).toBe(0);
    fixture.setVisible(false);
    fixture.setOnline(true);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS * 10);
    expect(probe).toHaveBeenCalledTimes(1);
    stop();
    expect(fixture.listeners.size).toBe(0);
  });

  it("does not bypass the offline gate for the initial hidden read", async () => {
    const fixture = refreshHost();
    fixture.setVisible(false);
    fixture.setOnline(false);
    const probe = vi.fn(async () => health);
    const stop = installBackendHealthRefresh(probe, vi.fn(), fixture.host);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS);
    expect(probe).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
    stop();
  });

  it("never overlaps a slow request and ignores its result after disposal", async () => {
    const fixture = refreshHost();
    let complete!: (value: BackendHealth) => void;
    const probe = vi.fn(() => new Promise<BackendHealth>((resolve) => { complete = resolve; }));
    const onHealth = vi.fn();
    const stop = installBackendHealthRefresh(probe, onHealth, fixture.host);
    fixture.setVisible(false);
    fixture.setVisible(true);
    fixture.setOnline(true);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS * 3);
    expect(probe).toHaveBeenCalledTimes(1);
    stop();
    complete(health);
    await vi.advanceTimersByTimeAsync(0);
    expect(onHealth).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("starts the next interval after a slow request completes", async () => {
    const fixture = refreshHost();
    let complete!: (value: BackendHealth) => void;
    const probe = vi.fn()
      .mockImplementationOnce(() => new Promise<BackendHealth>((resolve) => { complete = resolve; }))
      .mockResolvedValue(health);
    const stop = installBackendHealthRefresh(probe, vi.fn(), fixture.host);
    await vi.advanceTimersByTimeAsync(125);
    complete(health);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS - 1);
    expect(probe).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(probe).toHaveBeenCalledTimes(2);
    stop();
  });

  it("reports an unexpected probe rejection as offline and waits for the next interval", async () => {
    const fixture = refreshHost();
    const probe = vi.fn().mockRejectedValueOnce(new Error("read failed")).mockResolvedValue(health);
    const onHealth = vi.fn();
    const stop = installBackendHealthRefresh(probe, onHealth, fixture.host);
    await vi.advanceTimersByTimeAsync(0);
    expect(onHealth).toHaveBeenLastCalledWith(OFFLINE_HEALTH);
    await vi.advanceTimersByTimeAsync(BACKEND_HEALTH_REFRESH_MS);
    expect(onHealth).toHaveBeenLastCalledWith(health);
    stop();
  });
});
