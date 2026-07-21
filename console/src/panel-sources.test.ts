import { describe, expect, test } from "vitest";

import type { ReadDataSourcesPayload } from "./api-data-sources";
import { resolvePanels } from "./panels";
import { panelSourceAvailability, panelSourceClassification } from "./panel-sources";

const sources: ReadDataSourcesPayload = {
  surface: "read-data-sources",
  sources: [
    {
      key: "state", source: "postgres", routes: ["/kpi"], availability: "available",
      configured: true, reachable: true, authoritative: true, durable: true,
      synthetic: false, reason: null, last_observed_at: null,
    },
    {
      key: "measurement", source: "not-configured", routes: ["/kpi/autonomy", "/finops", "/kpi/promotion-gates"],
      availability: "unavailable", configured: false, reachable: null, authoritative: false,
      durable: null, synthetic: false, reason: "not configured", last_observed_at: null,
    },
  ],
};

describe("panel source availability", () => {
  test("marks a composite dashboard unavailable when one required source is absent", () => {
    expect(panelSourceAvailability("dashboard", sources)).toBe("unavailable");
  });

  test("returns null for a source-independent panel", () => {
    expect(panelSourceAvailability("labs", sources)).toBeNull();
  });

  test("keeps a read-API panel unknown when no manifest source owns its route", () => {
    expect(panelSourceAvailability("skills", sources)).toBe("unknown");
  });

  test("keeps a composite panel unknown when only some routes have owners", () => {
    const partial: ReadDataSourcesPayload = {
      surface: "read-data-sources",
      sources: [sources.sources[0]!],
    };

    expect(panelSourceAvailability("dashboard", partial)).toBe("unknown");
  });

  test("classifies every registered console panel by source ownership", () => {
    const panels = resolvePanels();
    expect(panels).toHaveLength(45);
    expect(panels.filter((panel) => panelSourceClassification(panel.id) === null))
      .toEqual([]);
    expect(panelSourceClassification("documents")).toBe("separate-client");
    expect(panelSourceClassification("settings-diagnostics")).toBe("independent");
  });
});
