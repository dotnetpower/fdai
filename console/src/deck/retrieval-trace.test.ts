import { describe, expect, test } from "vitest";
import type { RetrievalSourcePreview } from "./backend";
import type { ViewSnapshot } from "./context";
import { sourceCards } from "./retrieval-trace";

const snapshot: ViewSnapshot = {
  routeId: "dashboard",
  routeLabel: "Dashboard",
  headline: "Current operations",
  facts: [
    { key: "cost_actions", value: "n/a", group: "cost" },
    { key: "policy_escapes", value: " N/A ", group: "guards" },
    { key: "measurement_state", value: "unavailable", group: "autonomy" },
    { key: "source_gap", value: null, group: "evidence" },
  ],
  capturedAt: "2026-08-26T03:00:00Z",
};

describe("sourceCards", () => {
  test("omits unavailable screen facts while preserving non-placeholder gaps", () => {
    expect(sourceCards(snapshot, [])).toEqual([
      { kind: "evidence", label: "source_gap", detail: "-" },
    ]);
  });

  test("omits unavailable server previews without changing available evidence", () => {
    const previews: readonly RetrievalSourcePreview[] = [
      {
        kind: "cost",
        label: "cost_actions",
        detail: "n/a",
        side_effect_class: "read",
      },
      {
        kind: "guards",
        label: "policy_escapes",
        detail: " N/A ",
        side_effect_class: "read",
      },
      {
        kind: "inventory",
        label: "inventory_status",
        detail: "Unavailable",
        side_effect_class: "read",
      },
      {
        kind: "inventory",
        label: "resources",
        detail: "12 rows",
        side_effect_class: "read",
      },
    ];

    expect(sourceCards(null, previews)).toEqual([previews[3]]);
  });
});
