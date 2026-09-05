import { describe, expect, test, vi } from "vitest";
import type { OperatorApiClient } from "../api";
import { decodeRecordedResourceStates } from "../recorded-resource-state";
import { loadDashboardRecordedStates } from "./dashboard-v2.loading";
import { dashboardResourceState } from "./dashboard-v2.model";

const fact = (value: string | null, source_path: string | null) => ({
  value, source_path, observed_at: null, recorded_at: null,
  freshness: "unknown", completeness: null, conflicts: [], reason: value === null ? "state_not_recorded" : "metadata_not_recorded",
});
function resource(id: string, value = "Running") {
  return {
    id, object_type: "Resource", resource_type: "compute.container-app", name: id,
    resource_group: "example-group", subscription_id: "example-subscription",
    status: "Succeeded", last_seen: "2026-09-05T12:00:00Z", selected: false,
    states: { schema_version: "1.0.0", operational: fact(value, "properties.runningStatus"), provisioning: fact("Succeeded", "properties.provisioningState"), availability: fact(null, null) },
  };
}
function page(ids: string[], next_cursor: string | null = null, total_count = ids.length) {
  return {
    schema_version: "1.0.0", source_generation: "example-generation",
    source_cutoff: "2026-09-05T12:00:00Z", ontology_release_digest: `sha256:${"a".repeat(64)}`,
    resources: ids.map((id) => resource(id)), total_count, next_cursor,
    complete: next_cursor === null, execution_authority: false, mutation_authority: false,
  };
}

describe("shared recorded state consumption", () => {
  test("loads pages by cursor, preserving state axes without per-resource queries", async () => {
    const panel = vi.fn<OperatorApiClient["panel"]>()
      .mockResolvedValueOnce(page(["one"], "next", 2))
      .mockResolvedValueOnce(page(["two"], null, 2));
    const snapshot = await loadDashboardRecordedStates({ panel });
    expect(panel.mock.calls).toEqual([
      ["/ontology/instances/states", { limit: "500" }],
      ["/ontology/instances/states", { limit: "500", cursor: "next" }],
    ]);
    expect(snapshot?.resources).toHaveLength(2);
    expect(snapshot?.resources[0]?.observedAt).toBeNull();
    expect(snapshot?.resources[0]?.states?.operational.value).toBe("Running");
    expect(snapshot?.resources[0]?.states?.provisioning.value).toBe("Succeeded");
    expect(snapshot?.resources[0]?.states?.operational.freshness).toBe("unknown");
    expect(snapshot?.recordedStates).toBe(true);
  });

  test.each(["Online", "Active", "Enabled", "Ready", "Custom retained state"])("retains %s without turning it into Running or discarding it", async (value) => {
    const panel = vi.fn<OperatorApiClient["panel"]>().mockResolvedValue({ ...page(["one"]), resources: [resource("one", value)] });
    const snapshot = await loadDashboardRecordedStates({ panel });
    expect(snapshot!.resources[0]!.states!.operational.value).toBe(value);
    expect(dashboardResourceState(snapshot!.resources[0]!, snapshot!, "operation")).not.toBe("unknown");
    expect(dashboardResourceState(snapshot!.resources[0]!, snapshot!, "operation")).not.toBe("running");
    expect(dashboardResourceState(snapshot!.resources[0]!, snapshot!, "availability")).toBe("unknown");
  });

  test.each([
    { source_generation: "different" }, { source_cutoff: "2026-09-05T12:01:00Z" },
    { total_count: 3 }, { ontology_release_digest: `sha256:${"b".repeat(64)}` },
    { resources: [resource("one")] },
  ])("rejects mixed, overlapping or inconsistent pages: %j", async (patch) => {
    const panel = vi.fn<OperatorApiClient["panel"]>().mockResolvedValueOnce(page(["one"], "next", 2))
      .mockResolvedValueOnce({ ...page(["two"], null, 2), ...patch });
    await expect(loadDashboardRecordedStates({ panel })).rejects.toThrow(/recorded resource|Recorded resource/i);
  });

  test.each([
    { next_cursor: "loop" }, { resources: [] }, { execution_authority: true },
    { complete: true, next_cursor: "next" }, { total_count: 0 },
    { resources: [{ ...resource("one"), resource_type: "authorization.role-assignment" }] },
  ])("fails closed on malformed or stalled responses: %j", async (patch) => {
    const panel = vi.fn<OperatorApiClient["panel"]>().mockResolvedValue({ ...page(["one"], "loop", 2), ...patch });
    await expect(loadDashboardRecordedStates({ panel })).rejects.toThrow();
    expect(panel.mock.calls.length).toBeLessThanOrEqual(2);
  });

  test("cancels without publishing old data or requesting another page", async () => {
    let cancelled = false;
    const panel = vi.fn<OperatorApiClient["panel"]>().mockImplementation(async () => {
      cancelled = true;
      return page(["one"], "next", 2);
    });
    expect(await loadDashboardRecordedStates({ panel }, () => cancelled)).toBeNull();
    expect(panel).toHaveBeenCalledTimes(1);
  });

  test("ends a stalled batch at the total deadline without requesting another page", async () => {
    vi.useFakeTimers();
    try {
      const panel = vi.fn<OperatorApiClient["panel"]>().mockReturnValue(new Promise(() => {}));
      const outcome = expect(loadDashboardRecordedStates({ panel })).rejects.toThrow("total deadline");
      await vi.advanceTimersByTimeAsync(30000);
      await outcome;
      expect(panel).toHaveBeenCalledTimes(1);
    } finally { vi.useRealTimers(); }
  });

  test("reports bounded client coverage instead of claiming all 20001 records were loaded", async () => {
    const panel = vi.fn<OperatorApiClient["panel"]>();
    for (let index = 0; index < 40; index += 1) {
      panel.mockResolvedValueOnce(page(Array.from({ length: 500 }, (_, at) => `resource-${index * 500 + at}`), `cursor-${index}`, 20001));
    }
    const snapshot = await loadDashboardRecordedStates({ panel });
    expect(snapshot?.resources).toHaveLength(20000);
    expect(snapshot?.totalCount).toBe(20001);
    expect(snapshot?.truncated).toBe(true);
    expect(snapshot?.limitations).toEqual(["client_record_limit"]);
    expect(panel).toHaveBeenCalledTimes(40);
  });

  test("preserves conflicted or stale values as recorded evidence rather than fresh facts", () => {
    const states = decodeRecordedResourceStates({
      ...resource("one").states,
      operational: { ...fact("Running", "properties.runningStatus"), freshness: "stale", conflicts: ["conflicting_source"], reason: "conflict" },
    });
    expect(states.operational).toMatchObject({ value: "Running", freshness: "stale", conflicts: ["conflicting_source"] });
  });

  test("rejects invalid state-fact fields instead of synthesizing metadata", () => {
    for (const patch of [{ value: "Running", source_path: null }, { completeness: 2 }, { freshness: "healthy" }, { observed_at: "not-a-time" }]) {
      expect(() => decodeRecordedResourceStates({ ...resource("one").states, operational: { ...fact("Running", "properties.runningStatus"), ...patch } })).toThrow();
    }
  });
});
