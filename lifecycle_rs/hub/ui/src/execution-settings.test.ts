import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { hubApi, HubApiError, request } from "./api";
import type { ExecutionSettingsRequest } from "./api";
import { authenticatedFetch } from "./auth";

vi.mock("./auth", () => ({
  authenticatedFetch: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(authenticatedFetch).mockReset().mockImplementation((path, init) => fetch(path, init));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const command: ExecutionSettingsRequest = {
  request_id: "00000000-0000-0000-0000-000000000000",
  expected_settings_digest: "a".repeat(64),
  windows: [{
    start: "01:00:00", duration_minutes: 90.5, timezone: "Asia/Seoul", allows_downtime: false,
  }],
  plan_duration_minutes: 20,
  reason_code: "operator_schedule_change",
  confirmation: `update execution settings installation-alpha ${"a".repeat(64)}`,
};

describe("bounded execution-settings client", () => {
  it("posts an application binding only to its authenticated route under the same deadline", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      changed: true, settings_digest: "b".repeat(64),
    })));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    const { windows: _windows, plan_duration_minutes: _duration, ...common } = command;
    const body = { ...common, product: "example-web" };
    await hubApi.bindApplication("installation-alpha", body);
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/v1/installations/installation-alpha/application-binding", {
      method: "POST", body: JSON.stringify(body),
      headers: { "content-type": "application/json" }, signal: expect.any(AbortSignal),
    });
    expect(timeout).toHaveBeenCalledWith(10_000);
  });
  it("reads only the schedule projection with a ten-second deadline", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      settings_digest: "a".repeat(64), windows: [], plan_duration_minutes: 30,
    })));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    await hubApi.getExecutionSettings("installation-alpha");
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/v1/installations/installation-alpha/execution-settings", {
      headers: {}, signal: expect.any(AbortSignal),
    });
    expect(timeout).toHaveBeenCalledWith(10_000);
  });

  it("sends the exact reviewed command without an actor or execution side effects", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      changed: true, settings_digest: "b".repeat(64),
    })));
    vi.stubGlobal("fetch", fetcher);
    const timeout = vi.spyOn(AbortSignal, "timeout");
    await hubApi.updateExecutionSettings("installation-alpha", command);
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith("/v1/installations/installation-alpha/execution-settings", {
      method: "POST", body: JSON.stringify(command),
      headers: { "content-type": "application/json" }, signal: expect.any(AbortSignal),
    });
    expect(timeout).toHaveBeenCalledWith(10_000);
  });

  it("surfaces stale revisions without an automatic retry", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: "execution_settings_revision_conflict",
    }), { status: 409 }));
    vi.stubGlobal("fetch", fetcher);
    await expect(hubApi.updateExecutionSettings("installation-alpha", command))
      .rejects.toBeInstanceOf(HubApiError);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("does not retry an uncertain save", async () => {
    const failure = new TypeError("Network unavailable");
    const fetcher = vi.fn().mockRejectedValue(failure);
    vi.stubGlobal("fetch", fetcher);
    await expect(hubApi.updateExecutionSettings("installation-alpha", command)).rejects.toBe(failure);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("ends a request when authorization never settles", async () => {
    const controller = new AbortController();
    const timeout = vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
    vi.mocked(authenticatedFetch).mockImplementation(() => new Promise<Response>(() => {}));
    const result = hubApi.updateExecutionSettings("installation-alpha", command);
    const rejected = expect(result).rejects.toMatchObject({ name: "TimeoutError" });
    controller.abort(new DOMException("Request deadline exceeded", "TimeoutError"));
    await rejected;
    expect(timeout).toHaveBeenCalledWith(10_000);
    expect(authenticatedFetch).toHaveBeenCalledOnce();
  });

  it("bounds response parsing as well as authentication and fetch", async () => {
    const controller = new AbortController();
    vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
    let finishJson!: (value: unknown) => void;
    const response = new Response("{}");
    const parsing = vi.spyOn(response, "json").mockReturnValue(
      new Promise<unknown>(resolve => { finishJson = resolve; }),
    );
    vi.mocked(authenticatedFetch).mockResolvedValue(response);
    const result = hubApi.getExecutionSettings("installation-alpha");
    await vi.waitFor(() => expect(parsing).toHaveBeenCalledOnce());
    const rejected = expect(result).rejects.toMatchObject({ name: "TimeoutError" });
    controller.abort(new DOMException("Request deadline exceeded", "TimeoutError"));
    await rejected;
    finishJson({});
    expect(authenticatedFetch).toHaveBeenCalledOnce();
  });

  it("handles an abort during synchronous request setup", async () => {
    const controller = new AbortController();
    vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
    vi.mocked(authenticatedFetch).mockImplementation(() => {
      controller.abort(new DOMException("Request deadline exceeded", "TimeoutError"));
      return new Promise<Response>(() => {});
    });
    await expect(hubApi.getExecutionSettings("installation-alpha"))
      .rejects.toMatchObject({ name: "TimeoutError" });
    expect(authenticatedFetch).toHaveBeenCalledOnce();
  });

  it("does not start authorization when the signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort(new DOMException("Request deadline exceeded", "TimeoutError"));
    await expect(request("/unused", { signal: controller.signal }))
      .rejects.toMatchObject({ name: "TimeoutError" });
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });
});
