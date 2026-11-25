import { describe, expect, test } from "vitest";
import {
  bottomRailPanels,
  DEFAULT_PANEL_ID,
  hubPanelsFor,
  hubRootIdForPanel,
  navLabelForPanel,
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
      "code-security",
      "hil-queue",
      "workflow-apps",
    ]);
    expect(panelForId("incidents").id).toBe("incidents");
    expect(hubPanelsFor("live").map((panel) => panel.id)).toEqual(["live", "gpu"]);
    expect(hubPanelsFor("code-security").map((panel) => panel.id)).toEqual([
      "code-security",
      "configuration-baselines",
    ]);
    expect(hubPanelsFor("hil-queue").map((panel) => panel.id)).toEqual([
      "hil-queue",
      "alert-quality",
      "detection-readiness",
      "conversation-delivery",
    ]);
    expect(hubPanelsFor("workflow-apps").map((panel) => panel.id)).toEqual([
      "workflow-apps",
      "automation-blueprints",
      "processes",
      "scheduler-runs",
      "background-tasks",
      "scheduled-continuations",
    ]);
  });

  test("uses five primary domain groups with Knowledge consolidated under Governance", () => {
    expect(panelsInGroup("overview").map((panel) => panel.id)).toEqual([
      "dashboard",
      "operating-outcomes",
      "cost-governance",
    ]);
    expect(panelsInGroup("agents").map((panel) => panel.id)).toEqual([
      "agents",
      "pantheon",
      "agent-activity",
      "skills",
    ]);
    expect(panelsInGroup("governance").map((panel) => panel.id)).toEqual([
      "rules",
      "architecture",
      "ontology",
      "blast-radius",
      "workflow-builder",
      "knowledge",
    ]);
    expect(panelsInGroup("evidence").map((panel) => panel.id)).toEqual([
      "audit",
      "trace",
      "reports",
      "conversation-search",
    ]);
    expect(panelsInGroup("labs").map((panel) => panel.id)).toEqual([
      "labs",
      "assurance-twin",
    ]);
    expect(panelsInGroup("settings").map((panel) => panel.id)).toEqual([
      "settings-general",
      "settings-models",
      "settings-iam",
      "settings-integrations",
      "settings-diagnostics",
    ]);
  });

  test("preserves permanent route ids as hub tabs with parent active mapping", () => {
    expect(hubPanelsFor("knowledge").map((panel) => panel.id)).toEqual([
      "knowledge",
      "documents",
      "github",
      "gitlab",
      "azure-devops",
    ]);
    expect(hubRootIdForPanel("github")).toBe("knowledge");
    expect(hubRootIdForPanel("llm-cost")).toBe("cost-governance");
    expect(hubRootIdForPanel("settings-runtime")).toBe("settings-models");
    expect(hubRootIdForPanel("dashboard")).toBe("dashboard");
    expect(hubPanelsFor("dashboard")).toEqual([]);
    expect(navLabelForPanel(panelForId("knowledge"))).toBe("Knowledge & documents");
    expect(panelForId("knowledge").label).toBe("Knowledge overview");
  });

  test("promotes an enabled hub child when a Stencil excludes the hub root", () => {
    const g = globalThis as Record<string, unknown>;
    const prev = g.__FDAI_STENCIL_FEATURE_FLAGS__;
    g.__FDAI_STENCIL_FEATURE_FLAGS__ = {
      schema_version: "fdai.stencil-feature-flags.v1",
      stencil_id: "lite-hub-child-test",
      enforcement_mode: "fail-closed",
      enabled_panel_ids: ["dashboard", "audit", "settings-general", "detection-readiness", "alert-quality", "github"],
    };
    try {
      expect(panelsInGroup("operations").map((panel) => panel.id)).toEqual(["alert-quality"]);
      expect(hubRootIdForPanel("detection-readiness")).toBe("alert-quality");
      expect(hubPanelsFor("detection-readiness").map((panel) => panel.id)).toEqual([
        "alert-quality",
        "detection-readiness",
      ]);
      expect(panelsInGroup("governance").map((panel) => panel.id)).toEqual(["github"]);
    } finally {
      if (prev === undefined) delete g.__FDAI_STENCIL_FEATURE_FLAGS__;
      else g.__FDAI_STENCIL_FEATURE_FLAGS__ = prev;
    }
  });

  test("preserves legacy environment routes without showing duplicate menu items", () => {
    expect(panelForId("provision").hiddenFromNavigation).toBe(true);
    expect(panelForId("onboarding").hiddenFromNavigation).toBe(true);
    expect(panelForId("dashboard-v2").hiddenFromNavigation).toBe(true);
    expect(resolvePanels().map((panel) => panel.id)).toContain("settings-environment");
  });

  test("reuses the stable pantheon route as the roles view", () => {
    expect(panelForId("agents").label).toBe("Agent fleet");
    expect(panelForId("pantheon").label).toBe("Roles and ownership");
    expect(navLabelForPanel(panelForId("pantheon"))).toBe("Roles & handover");
    expect(panelForId("pantheon").component).toBe(panelForId("agents").component);
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
