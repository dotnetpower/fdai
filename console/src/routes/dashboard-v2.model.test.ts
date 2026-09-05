import { describe, expect, test } from "vitest";
import {
  dashboardCounts, dashboardMapColumns, dashboardResourceState, dashboardScope, dashboardStatusFilter, dashboardTypeLabel, dashboardUnknownReason,
  decodeDashboardSnapshot, EMPTY_DASHBOARD_FILTERS,
} from "./dashboard-v2.model";
import en from "./i18n/dashboard-v2.en.json";
import ko from "./i18n/dashboard-v2.ko.json";

const base = {
  snapshot_id: "snapshot-example", snapshot_at: "2026-09-05T03:00:00Z",
  source: "test-inventory", observation_kind: "OBSERVED", freshness: "fresh",
  active_view: "example-workload", truncated: false, coverage_gaps: [],
  resources: [
    { id: "sub", name: "Example subscription", type: "subscription", status: "unknown" },
    { id: "rg", name: "Example group", type: "resource-group", status: "unknown", parent_id: "sub" },
    { id: "vm", name: "Example VM", type: "compute.vm", status: "PowerState/running", parent_id: "rg" },
    { id: "db", name: "Example database", type: "postgresql", status: "Succeeded", parent_id: "rg" },
    { id: "unmapped", name: "Example unmapped", type: "new.provider", status: "Healthy", parent_id: "missing" },
  ],
};

describe("Dashboard v2 inventory projection", () => {
  test("decodes exact returned identities and scope without exposing raw properties", () => {
    const snapshot = decodeDashboardSnapshot({ ...base, resources: base.resources.map((row) => ({ ...row, props: { internal: "not-for-display" } })) });
    expect(snapshot.resources).toHaveLength(3);
    expect(snapshot.excludedContainers).toBe(2);
    expect(snapshot.scope).toBe("example-workload");
    expect(snapshot.resources[0]).toMatchObject({ id: "vm", group: "rg", subscription: "sub", observedAt: null });
    expect(snapshot.resources[2]).toMatchObject({ group: null, subscription: null });
    expect(JSON.stringify(snapshot)).not.toContain("internal");
    expect(dashboardTypeLabel(snapshot.resources[2]!)).toBe("new.provider");
    expect([...dashboardCounts(snapshot.resources, snapshot, "operation")]).toEqual([["running", 1], ["unknown", 2]]);
  });

  test("omits role assignments from every operational collection without changing raw inventory", () => {
    const payload = { ...base, resources: [...base.resources, { id: "assignment", name: "Example grant", type: "authorization.role-assignment", status: "unknown", parent_id: "rg" }] };
    const snapshot = decodeDashboardSnapshot(payload);
    expect(snapshot.resources).toHaveLength(3);
    expect(snapshot.excludedContainers).toBe(2);
    expect(snapshot.excludedAuthorization).toBe(1);
    expect(snapshot.resources.some((resource) => resource.type === "authorization.role-assignment")).toBe(false);
    expect(payload.resources).toHaveLength(6);
    expect([...dashboardCounts(snapshot.resources, snapshot, "operation")]).toEqual([["running", 1], ["unknown", 2]]);
  });

  test("accepts the producer's lowercase observation enum and preserves evidence hold reasons", () => {
    const snapshot = decodeDashboardSnapshot({ ...base, observation_kind: "observed" });
    expect(dashboardResourceState(snapshot.resources[0]!, snapshot, "operation")).toBe("running");
    expect(dashboardUnknownReason(snapshot.resources[1]!, snapshot)).toBe("unclassifiedState");
    const legacy = decodeDashboardSnapshot({ ...base, snapshot_id: undefined, observation_kind: undefined });
    expect(dashboardResourceState(legacy.resources[0]!, legacy, "operation")).toBe("unknown");
    expect(dashboardUnknownReason(legacy.resources[0]!, legacy)).toBe("missingProvenance");
    const stale = decodeDashboardSnapshot({ ...base, observation_kind: "observed", freshness: "stale" });
    expect(dashboardUnknownReason(stale.resources[0]!, stale)).toBe("oldSnapshot");
    const expected = decodeDashboardSnapshot({ ...base, observation_kind: "expected" });
    expect(dashboardResourceState(expected.resources[0]!, expected, "operation")).toBe("unknown");
  });

  test.each(["fresh", "stale", "unknown"])("availability is not inferred from %s source status", (freshness) => {
    const snapshot = decodeDashboardSnapshot({ ...base, freshness });
    expect(snapshot.resources.map((resource) => dashboardResourceState(resource, snapshot, "availability"))).toEqual(["unknown", "unknown", "unknown"]);
    expect(dashboardResourceState(snapshot.resources[0]!, snapshot, "operation")).toBe(freshness === "fresh" ? "running" : "unknown");
  });

  test.each([
    { observation_kind: "EXPECTED" }, { observation_kind: undefined }, { snapshot_id: null },
    { source: null }, { realtime: { pending_changes: 1 } },
  ])("missing or conflicted observation provenance cannot establish current operation: %j", (metadata) => {
    const snapshot = decodeDashboardSnapshot({ ...base, ...metadata });
    expect(dashboardResourceState(snapshot.resources[0]!, snapshot, "operation")).toBe("unknown");
  });

  test.each([
    { truncated: "false" }, { freshness: {} }, { observation_kind: "maybe" },
    { execution_authority: true }, { mutation_authority: "false" },
    { snapshot_at: "2026-99-31T00:00:00Z" }, { coverage_gaps: [""] },
    { resources: [base.resources[2], base.resources[2]] },
    { resources: [{ ...base.resources[2], parent_id: "vm" }] },
    { realtime: { pending_changes: -1 } },
  ])("rejects malformed projection metadata: %j", (metadata) => {
    expect(() => decodeDashboardSnapshot({ ...base, ...metadata })).toThrow(/inventory/i);
  });

  test("keeps partial and missing state independent of container and page counts", () => {
    const snapshot = decodeDashboardSnapshot({ ...base, truncated: true, truncation_reasons: ["source_limit"] });
    expect(snapshot.truncated).toBe(true);
    expect(snapshot.limitations).toContain("source_limit");
    expect(snapshot.resources[0]!.observedAt).toBeNull();
    expect(dashboardScope(snapshot.resources, { ...EMPTY_DASHBOARD_FILTERS, group: null })).toHaveLength(1);
    expect(dashboardScope(snapshot.resources, { ...EMPTY_DASHBOARD_FILTERS, subscription: "sub", type: "compute.vm", query: "EXAMPLE" })).toHaveLength(1);
    expect(dashboardScope(snapshot.resources, { ...EMPTY_DASHBOARD_FILTERS, type: "none" }, false)).toHaveLength(3);
  });

  test("dense geometry fits its actual pitch and remains bounded", () => {
    for (const width of [290, 480, 640, 790, 1400]) {
      const columns = dashboardMapColumns(width, "dense");
      expect(columns * 26 + 19).toBeLessThanOrEqual(width);
      expect(columns * 14).toBeLessThanOrEqual(476);
      expect(dashboardMapColumns(width, "comfortable") * 56 + 32).toBeLessThanOrEqual(width);
    }
  });

  test("accepts only declared summary-state deep-link filters", () => {
    expect(dashboardStatusFilter("known")).toBe("known");
    expect(dashboardStatusFilter("unknown")).toBe("unknown");
    expect(dashboardStatusFilter("__proto__")).toBe("");
    expect(dashboardStatusFilter(null)).toBe("");
  });

  test("native locale catalogs have matching keys and nonempty readable values", () => {
    expect(Object.keys(ko).sort()).toEqual(Object.keys(en).sort());
    expect(Object.values(en).every(Boolean) && Object.values(ko).every(Boolean)).toBe(true);
    expect(ko.title).toContain("대시보드");
  });
});
