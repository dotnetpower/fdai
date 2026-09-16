import { describe, expect, test, vi } from "vitest";
import type { OperatorApiClient } from "../api";
import { OperatorApiError } from "../api-transport";
import { decodeRecordedResourceStates } from "../recorded-resource-state";
import { loadDashboardRecordedStates } from "./dashboard-v2.loading";
import { dashboardResourceState } from "./dashboard-v2.model";

const fact = (
  value: string | null,
  source_path: string | null,
  observed_at: string | null = null,
) => ({
  value, source_path, observed_at, recorded_at: observed_at,
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
    ontology_generation: "example-generation",
    ontology_manifest_digest: `sha256:${"c".repeat(64)}`,
    source_kind: "inventory_snapshot_resource",
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
    expect(snapshot?.source).toBe("inventory_snapshot_resource");
    expect(snapshot?.ontologyGeneration).toBe("example-generation");
    expect(snapshot?.ontologyManifestDigest).toBe(`sha256:${"c".repeat(64)}`);
  });

  test.each(["Online", "Active", "Enabled", "Ready", "Custom retained state"])("retains %s without turning it into Running or discarding it", async (value) => {
    const panel = vi.fn<OperatorApiClient["panel"]>().mockResolvedValue({ ...page(["one"]), resources: [resource("one", value)] });
    const snapshot = await loadDashboardRecordedStates({ panel });
    expect(snapshot!.resources[0]!.states!.operational.value).toBe(value);
    expect(dashboardResourceState(snapshot!.resources[0]!, snapshot!, "operation")).not.toBe("unknown");
    expect(dashboardResourceState(snapshot!.resources[0]!, snapshot!, "operation")).not.toBe("running");
    expect(dashboardResourceState(snapshot!.resources[0]!, snapshot!, "availability")).toBe("unknown");
  });

  test("retains serving evidence and uses the latest exact axis observation time", async () => {
    const original = page(["one"]);
    const payload: Record<string, unknown> = {
      ...original,
      resources: [{
        ...original.resources[0],
        states: {
          ...original.resources[0]!.states,
          provisioning: {
            ...fact("Succeeded", "properties.provisioningState", "2026-09-05T11:55:00Z"),
          },
          serving: {
            ...fact("Serving", "servingState", "2026-09-05T11:59:00Z"),
            source_identity: "azure-monitor-model-serving",
            authority: "telemetry",
          },
        },
      }],
    };
    const panel = vi.fn<OperatorApiClient["panel"]>().mockResolvedValue(payload);

    const snapshot = await loadDashboardRecordedStates({ panel });

    expect(snapshot?.resources[0]?.states?.serving?.value).toBe("Serving");
    expect(snapshot?.resources[0]?.observedAt).toBe("2026-09-05T11:59:00Z");
  });

  test.each([
    { source_generation: "different" }, { source_cutoff: "2026-09-05T12:01:00Z" },
    { total_count: 3 }, { ontology_release_digest: `sha256:${"b".repeat(64)}` },
    { ontology_manifest_digest: `sha256:${"d".repeat(64)}` },
    { resources: [resource("one")] },
  ])("rejects mixed, overlapping or inconsistent pages: %j", async (patch) => {
    const panel = vi.fn<OperatorApiClient["panel"]>().mockResolvedValueOnce(page(["one"], "next", 2))
      .mockResolvedValueOnce({ ...page(["two"], null, 2), ...patch });
    await expect(loadDashboardRecordedStates({ panel })).rejects.toThrow(/recorded resource|Recorded resource/i);
  });

  test.each([
    { next_cursor: "loop" }, { resources: [] }, { execution_authority: true },
    { complete: true, next_cursor: "next" }, { total_count: 0 },
    { ontology_generation: "different" }, { source_kind: "ontology_resource" },
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
      await vi.advanceTimersByTimeAsync(45_000);
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

  test.each(["inventory_generation_changed", "ontology_generation_changed"])(
    "restarts the whole snapshot after a typed %s transition",
    async (message) => {
      const panel = vi.fn<OperatorApiClient["panel"]>()
        .mockRejectedValueOnce(new OperatorApiError(409, message))
        .mockResolvedValueOnce(page(["one"]));
      const waitForRetry = vi.fn(async () => undefined);

      const snapshot = await loadDashboardRecordedStates(
        { panel },
        () => false,
        waitForRetry,
      );

      expect(snapshot?.resources.map((item) => item.id)).toEqual(["one"]);
      expect(panel).toHaveBeenCalledTimes(2);
      expect(waitForRetry).toHaveBeenCalledWith(250);
    },
  );

  test("discards partial pages before retrying a generation transition", async () => {
    const panel = vi.fn<OperatorApiClient["panel"]>()
      .mockResolvedValueOnce(page(["old"], "old-next", 2))
      .mockRejectedValueOnce(new OperatorApiError(409, "inventory_generation_changed"))
      .mockResolvedValueOnce(page(["new"]));

    const snapshot = await loadDashboardRecordedStates(
      { panel },
      () => false,
      async () => undefined,
    );

    expect(snapshot?.resources.map((item) => item.id)).toEqual(["new"]);
    expect(panel.mock.calls).toEqual([
      ["/ontology/instances/states", { limit: "500" }],
      ["/ontology/instances/states", { limit: "500", cursor: "old-next" }],
      ["/ontology/instances/states", { limit: "500" }],
    ]);
  });

  test("keeps a persistent generation transition visible after bounded retries", async () => {
    const error = new OperatorApiError(409, "ontology_generation_changed");
    const panel = vi.fn<OperatorApiClient["panel"]>().mockRejectedValue(error);
    const waitForRetry = vi.fn(async () => undefined);

    await expect(loadDashboardRecordedStates(
      { panel },
      () => false,
      waitForRetry,
    )).rejects.toBe(error);

    expect(panel).toHaveBeenCalledTimes(9);
    expect(waitForRetry.mock.calls).toEqual([
      [250],
      [500],
      [1_000],
      [2_000],
      [4_000],
      [8_000],
      [12_000],
      [12_000],
    ]);
  });

  test("rejects invalid state-fact fields instead of synthesizing metadata", () => {
    for (const patch of [{ value: "Running", source_path: null }, { completeness: 2 }, { freshness: "healthy" }, { observed_at: "not-a-time" }]) {
      expect(() => decodeRecordedResourceStates({ ...resource("one").states, operational: { ...fact("Running", "properties.runningStatus"), ...patch } })).toThrow();
    }
  });
});
