import { describe, expect, test } from "vitest";
import type { AuditItem } from "../types";
import {
  activityFiltersFromSearch,
  activityVerb,
  filterAgentActivity,
  pantheonLayerOf,
  type ActivityFilters,
} from "./agent-activity-groups";

function item(
  seq: number,
  agent: string,
  actionKind: string,
  recordedAt: string,
  entry: Record<string, unknown> = {},
): AuditItem {
  return {
    seq,
    event_id: `event-${seq}`,
    correlation_id: `corr-${seq}`,
    actor: agent,
    action_kind: actionKind,
    mode: "shadow",
    entry,
    entry_hash: `hash-${seq}`,
    previous_hash: `hash-${seq - 1}`,
    recorded_at: recordedAt,
  };
}

const BASE_FILTERS: ActivityFilters = {
  window: "7d",
  layer: "all",
  verb: "all",
  query: "",
};
const agentOf = (value: AuditItem) => value.actor;

describe("agent activity filters", () => {
  test("parses supported route filters and defaults unknown values", () => {
    expect(activityFiltersFromSearch(new URLSearchParams(
      "window=15m&layer=pipeline&verb=execute&q=incident",
    ))).toEqual({ window: "15m", layer: "pipeline", verb: "execute", query: "incident" });
    expect(activityFiltersFromSearch(new URLSearchParams(
      "window=forever&layer=unknown&verb=mutate",
    ))).toEqual({ window: "24h", layer: "all", verb: "all", query: "" });
  });

  test("uses the latest audit row as the relative window anchor", () => {
    const rows = [
      item(1, "Thor", "action.execute", "2026-07-15T10:00:00Z"),
      item(2, "Forseti", "verdict.issue", "2026-07-15T11:00:00Z"),
    ];
    expect(filterAgentActivity(rows, { ...BASE_FILTERS, window: "15m" }, agentOf))
      .toEqual([rows[1]]);
    expect(filterAgentActivity(rows, { ...BASE_FILTERS, window: "1h" }, agentOf))
      .toEqual(rows);
  });

  test("filters canonical pantheon layers without reclassifying unknown producers", () => {
    const rows = [
      item(1, "Saga", "audit.recorded", "2026-07-15T11:00:00Z"),
      item(2, "Thor", "action.execute", "2026-07-15T11:00:01Z"),
      item(3, "Njord", "cost.advise", "2026-07-15T11:00:02Z"),
      item(4, "custom-worker", "custom.run", "2026-07-15T11:00:03Z"),
    ];
    expect(pantheonLayerOf("Saga")).toBe("governance");
    expect(pantheonLayerOf("Thor")).toBe("pipeline");
    expect(pantheonLayerOf("Njord")).toBe("domain");
    expect(pantheonLayerOf("custom-worker")).toBe("system");
    expect(filterAgentActivity(rows, { ...BASE_FILTERS, layer: "pipeline" }, agentOf))
      .toEqual([rows[1]]);
  });

  test("classifies verbs from recorded action and outcome fields", () => {
    expect(activityVerb(item(1, "Thor", "action.execute", "2026-07-15T11:00:00Z")))
      .toBe("execute");
    expect(activityVerb(item(2, "Var", "hil.approved", "2026-07-15T11:00:00Z")))
      .toBe("approve");
    expect(activityVerb(item(3, "Vidar", "rollback.completed", "2026-07-15T11:00:00Z")))
      .toBe("rollback");
    expect(activityVerb(item(4, "Forseti", "verdict.issue", "2026-07-15T11:00:00Z", { outcome: "abstained" })))
      .toBe("abstain");
  });

  test("searches only recorded audit fields and identifiers", () => {
    const rows = [
      item(1, "Thor", "storage.remediate", "2026-07-15T11:00:00Z", {
        summary: "Opened remediation PR",
        resource_ref: "storage-example",
      }),
      item(2, "Saga", "audit.recorded", "2026-07-15T11:00:01Z"),
    ];
    expect(filterAgentActivity(rows, { ...BASE_FILTERS, query: "storage-example" }, agentOf))
      .toEqual([rows[0]]);
    expect(filterAgentActivity(rows, { ...BASE_FILTERS, query: "storage example" }, agentOf))
      .toEqual([rows[0]]);
    expect(filterAgentActivity([
      item(3, "Thor", "restrict-network-access", "2026-07-15T11:00:02Z"),
    ], { ...BASE_FILTERS, query: "restrict network" }, agentOf)).toHaveLength(1);
    expect(filterAgentActivity(rows, { ...BASE_FILTERS, query: "not-recorded" }, agentOf))
      .toEqual([]);
  });
});
