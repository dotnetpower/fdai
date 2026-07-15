import { describe, expect, test } from "vitest";
import {
  bottomRailPanels,
  DEFAULT_PANEL_ID,
  panelForId,
  panelsInGroup,
  resolvePanels,
} from "./panels";

describe("panel navigation placement", () => {
  test("groups live operator work under Operations", () => {
    const operations = panelsInGroup("operations").map((panel) => panel.id);
    expect(operations).toEqual(["live", "incidents", "hil-queue", "provision", "processes"]);
    expect(panelForId("incidents").id).toBe("incidents");
  });

  test("uses stable domain groups for every visible panel", () => {
    expect(panelsInGroup("overview").map((panel) => panel.id)).toEqual([
      "dashboard", "operating-outcomes", "control-assurance", "verticals", "trust-routing", "llm-cost",
    ]);
    expect(panelsInGroup("agents").map((panel) => panel.id)).toEqual([
      "agents", "pantheon", "agent-activity", "handover",
    ]);
    expect(panelsInGroup("governance").map((panel) => panel.id)).toEqual([
      "architecture", "ontology", "rules", "workflow-builder", "blast-radius", "promotion-gates", "scope",
    ]);
    expect(panelsInGroup("evidence").map((panel) => panel.id)).toEqual([
      "audit", "reports", "trace", "rca", "documents",
    ]);
    expect(panelsInGroup("labs").map((panel) => panel.id)).toEqual(["labs"]);
  });

  test("pins Settings to the bottom rail without changing its route", () => {
    expect(bottomRailPanels().map((panel) => panel.id)).toEqual(["settings"]);
    expect(resolvePanels().some((panel) => panel.id === "settings")).toBe(true);
    expect(panelForId("settings").id).toBe("settings");
    expect(DEFAULT_PANEL_ID).toBe("dashboard");
  });
});