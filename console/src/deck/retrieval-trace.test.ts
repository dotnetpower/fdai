import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import type { BackendHealth, RetrievalSourcePreview } from "./backend";
import type { ViewSnapshot } from "./context";
import { buildStages, sourceCards } from "./retrieval-trace";

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
  test("exposes content-free phase attributes for browser assurance", () => {
    const source = readFileSync(
      fileURLToPath(new URL("./retrieval-trace.tsx", import.meta.url)),
      "utf8",
    );

    expect(source).toContain('data-phase={stage.id}');
    expect(source).toContain('data-done={stage.done ? "true" : "false"}');
    expect(source).toContain('data-side={stage.side}');
  });

  test("omits unavailable screen facts while preserving non-placeholder gaps", () => {
    expect(sourceCards(snapshot, [])).toEqual([
      { kind: "evidence", label: "source_gap", detail: "-" },
    ]);
  });

  describe("buildStages", () => {
    test("states the route reason in operator words, never the raw reason code", () => {
      const health = {
        mode: "llm",
        router: { chose: "narrator-gpt-5-4-mini", reason: "disabled", candidates: [] },
      } as unknown as BackendHealth;
      const route = buildStages(null, health, null).find((stage) => stage.id === "route");

      expect(route?.label).toBe("Route - chose narrator-gpt-5-4-mini");
      expect(route?.detail).toBe("Latency routing disabled");
    });

    test("keeps stage identity stable when streamed labels change", () => {
      const first = buildStages(null, null, {
        phase: "verifying",
        label: "Checking evidence",
        completed: 1,
        total: 2,
      });
      const second = buildStages(null, null, {
        phase: "generating",
        label: "Writing answer",
        completed: 2,
        total: 2,
      });

      expect(first.map((stage) => stage.id)).toEqual(["backend"]);
      expect(second.map((stage) => stage.id)).toEqual(["backend"]);
      expect(first[0]?.label).not.toBe(second[0]?.label);
    });
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
