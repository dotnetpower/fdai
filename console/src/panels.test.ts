import { describe, expect, test } from "vitest";
import {
  bottomRailPanels,
  DEFAULT_PANEL_ID,
  panelForId,
  panelsInGroup,
  resolvePanels,
  validatePanelRegistry,
} from "./panels";

describe("panel navigation placement", () => {
  test("groups live operator work under Operations", () => {
    const operations = panelsInGroup("operations").map((panel) => panel.id);
    expect(operations).toEqual([
      "live",
      "incidents",
      "hil-queue",
      "provision",
      "onboarding",
      "processes",
      "workflow-apps",
      "scheduler-runs",
      "automation-blueprints",
      "scheduled-continuations",
      "conversation-delivery",
    ]);
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
      "architecture", "ontology", "rules", "workflow-builder", "capabilities", "skills", "blast-radius", "promotion-gates", "context-selection-comparisons", "scope",
    ]);
    expect(panelsInGroup("evidence").map((panel) => panel.id)).toEqual([
      "audit", "browser-evidence", "conversation-search", "reports", "trace", "rca", "documents",
    ]);
    expect(panelsInGroup("labs").map((panel) => panel.id)).toEqual(["labs"]);
    expect(panelsInGroup("settings").map((panel) => panel.id)).toEqual([
      "settings-general", "settings-models", "settings-memory", "settings-iam", "settings-integrations", "settings-diagnostics",
    ]);
  });

  test("pins the Settings group to the bottom rail", () => {
    expect(bottomRailPanels()).toEqual([]);
    expect(resolvePanels().some((panel) => panel.id === "settings-general")).toBe(true);
    expect(panelForId("settings-iam").id).toBe("settings-iam");
    expect(DEFAULT_PANEL_ID).toBe("dashboard");
  });

  test("rejects invalid extension panel registrations", () => {
    const panel = resolvePanels()[0]!;
    expect(() => validatePanelRegistry([panel, panel])).toThrow(/Duplicate console panel id/);
    expect(() => validatePanelRegistry([{ ...panel, id: "Bad_Panel" }])).toThrow(/kebab-case/);
    expect(() => validatePanelRegistry([{ ...panel, label: " " }])).toThrow(/MUST NOT be empty/);
  });
});
