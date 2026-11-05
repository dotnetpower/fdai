import { afterEach, describe, expect, it, vi } from "vitest";
import { latestEligibleChannelHead, requestDeploymentRequests, type DeploymentRequestPage, type Release } from "./api";
import { nextRequestOffset } from "./deployment-requests";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
const record = {
  request_id: "a".repeat(64), subscription_id: "00000000-0000-0000-0000-000000000000",
  release_id: "1.6.0", channel: "DEV", region: "eastus", source_commit: "b".repeat(40),
  catalog_digest: "c".repeat(64), recorded_at: "2026-10-25T12:00:00Z",
  status: "requested", trust: "self-reported",
};
const page = { requests: [record], limit: 25, offset: 25, has_more: true };

describe("operator deployment requests", () => {
  it("chooses the highest eligible SemVer independent of membership order", () => {
    const members = Object.freeze(["1.9.0", "1.10.0-rc.2", "1.10.0-rc.10", "1.10.0"]);
    const states = new Map<string, Release["state"]>(members.map((id) => [id, "published"]));
    expect(latestEligibleChannelHead(members, states)).toBe("1.10.0");
    expect(latestEligibleChannelHead(["1.10.0-rc.2", "1.9.0", "1.10.0-rc.10"], states))
      .toBe("1.10.0-rc.10");
    expect(members).toEqual(["1.9.0", "1.10.0-rc.2", "1.10.0-rc.10", "1.10.0"]);
  });
  it("excludes recalled, missing, and draft channel members", () => {
    const states = new Map<string, Release["state"]>([
      ["2.0.0", "recalled"], ["1.10.0", "published"], ["1.9.0", "draft"],
    ]);
    expect(latestEligibleChannelHead(["missing", "2.0.0", "1.9.0", "1.10.0"], states)).toBe("1.10.0");
    expect(latestEligibleChannelHead(["missing", "2.0.0", "1.9.0"], states)).toBeNull();
    expect(latestEligibleChannelHead([], states)).toBeNull();
  });
  it("refetches once on an explicit catalog refresh without resetting the current page", async () => {
    const state: unknown[] = [];
    let cursor = 0;
    let previousDeps: readonly unknown[] | undefined;
    let cleanup: (() => void) | undefined;
    const generation = { current: 0 };
    vi.doMock("preact/hooks", () => ({
      useMemo: (compute: () => unknown) => compute(),
      useRef: () => generation,
      useState: (initial: unknown) => {
        const index = cursor++;
        if (!(index in state)) state[index] = initial;
        return [state[index], (next: unknown) => {
          state[index] = typeof next === "function"
            ? (next as (value: unknown) => unknown)(state[index]) : next;
        }];
      },
      useEffect: (effect: () => void | (() => void), deps: readonly unknown[]) => {
        if (!previousDeps || deps.some((value, index) => value !== previousDeps?.[index])) {
          cleanup?.();
          previousDeps = [...deps];
          cleanup = effect() || undefined;
        }
      },
    }));
    vi.resetModules();
    try {
      const { DeploymentRequests } = await import("./deployment-requests");
      const fetch = vi.fn(async (path: string) => ({
        ok: true,
        json: async () => ({
          ...page,
          offset: Number(new URL(path, "https://hub.example").searchParams.get("offset")),
        }),
      }));
      vi.stubGlobal("fetch", fetch);
      const render = (refreshGeneration?: number) => {
        cursor = 0;
        return DeploymentRequests(refreshGeneration === undefined ? {} : { refreshGeneration });
      };
      const findNext = (node: unknown): (() => void) | null => {
        if (typeof node !== "object" || node === null) return null;
        const props = (node as { props?: { children?: unknown; onClick?: () => void } }).props;
        if (!props) return null;
        if (props.children === "Next" && props.onClick) return props.onClick;
        const children = Array.isArray(props.children) ? props.children : [props.children];
        for (const child of children) {
          const found = findNext(child);
          if (found) return found;
        }
        return null;
      };

      render();
      await vi.waitFor(() => expect(findNext(render())).not.toBeNull());
      expect(fetch).toHaveBeenCalledTimes(1);
      render(0);
      expect(fetch).toHaveBeenCalledTimes(1);

      const next = findNext(render());
      expect(next).not.toBeNull();
      next?.();
      render();
      await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
      expect(fetch.mock.calls[1]?.[0]).toContain("offset=25");

      render(1);
      await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(3));
      expect(fetch.mock.calls[2]?.[0]).toContain("offset=25");
      render(1);
      expect(fetch).toHaveBeenCalledTimes(3);
    } finally {
      cleanup?.();
      vi.doUnmock("preact/hooks");
      vi.resetModules();
    }
  });
  it("follows has_more beyond the old offset ceiling and stops at the retained end", async () => {
    const later = { ...page, offset: 10000 } as DeploymentRequestPage;
    expect(nextRequestOffset(later)).toBe(10025);
    expect(nextRequestOffset({ ...later, offset: 99950 })).toBe(99975);
    expect(nextRequestOffset({ ...later, offset: 99975, has_more: false })).toBeNull();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, json: async () => ({ ...page, offset: 10025 }),
    }));
    await expect(requestDeploymentRequests("", 10025)).resolves.toMatchObject({ offset: 10025 });
  });
  it("requests the exact subscription page without a write or automatic retry", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => page });
    vi.stubGlobal("fetch", fetch);
    await expect(requestDeploymentRequests(record.subscription_id, 25)).resolves.toEqual(page);
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0]?.[0]).toBe(`/v1/deployment-requests?limit=25&offset=25&subscription_id=${record.subscription_id}`);
    expect(fetch.mock.calls[0]?.[1]).not.toHaveProperty("method");
  });
  it("keeps unavailable operator access distinct from an empty list", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ error: "authentication_required" }) });
    vi.stubGlobal("fetch", fetch);
    await expect(requestDeploymentRequests()).rejects.toThrow("operator access");
    expect(fetch).toHaveBeenCalledOnce();
  });
  it.each([
    { ...page, offset: 0 }, { ...page, requests: [{ ...record, trust: "verified" }] },
    { ...page, requests: [{ ...record, status: "deployed" }] },
    { ...page, requests: [{ ...record, recorded_at: "invalid" }] },
    { ...page, requests: [null] }, { ...page, has_more: "yes" },
  ])("rejects misleading or malformed server state", async (body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => body }));
    await expect(requestDeploymentRequests("", 25)).rejects.toThrow("Invalid deployment request page");
  });
  it("accepts an explicitly empty page", async () => {
    const empty = { requests: [], limit: 25, offset: 0, has_more: false };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => empty }));
    await expect(requestDeploymentRequests()).resolves.toEqual(empty);
  });
});
