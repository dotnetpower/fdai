import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, test } from "vitest";
import { PANEL_GROUPS, resolvePanels } from "./panels";
import {
  filterNavigationGroupsByStencil,
  filterPanelsByStencil,
  LOCKED_STENCIL_PANEL_IDS,
  parseStencilEnabledPanelIds,
  transformPanelsSourceForStencil,
} from "./stencil-panels";

describe("stencil-panels", () => {
  test("returns null when no Stencil filter is provided and enforces locked safety-core panels", () => {
    expect(parseStencilEnabledPanelIds(undefined)).toBeNull();
    expect(parseStencilEnabledPanelIds("")).toBeNull();
    expect(parseStencilEnabledPanelIds("   ")).toBeNull();

    const parsed = parseStencilEnabledPanelIds("live, incidents");
    expect(parsed).not.toBeNull();
    for (const locked of LOCKED_STENCIL_PANEL_IDS) {
      expect(parsed?.has(locked)).toBe(true);
    }
    expect(parsed?.has("live")).toBe(true);
    expect(parsed?.has("incidents")).toBe(true);
    expect(parsed?.has("aks-commerce")).toBe(false);
  });

  test("rejects malformed panel IDs", () => {
    expect(() => parseStencilEnabledPanelIds("live,Bad_Panel")).toThrow(/Invalid Stencil panel id/);
  });

  test("filters panels and hides domain groups with zero enabled visible panels", () => {
    const enabled = parseStencilEnabledPanelIds(
      "live,incidents,detection-readiness,alert-quality,pantheon,agent-activity,rules,settings-integrations",
    );
    const allPanels = resolvePanels();
    const filtered = filterPanelsByStencil(allPanels, enabled);
    const filteredIds = filtered.map((panel) => panel.id);
    expect(filteredIds).toContain("dashboard");
    expect(filteredIds).toContain("audit");
    expect(filteredIds).toContain("settings-general");
    expect(filteredIds).toContain("live");
    expect(filteredIds).not.toContain("documents");
    expect(filteredIds).not.toContain("aks-commerce");

    const groups = filterNavigationGroupsByStencil(PANEL_GROUPS, allPanels, enabled);
    const groupIds = groups.map((g) => g.id);
    expect(groupIds).toContain("overview");
    expect(groupIds).toContain("operations");
    expect(groupIds).toContain("agents");
    expect(groupIds).toContain("governance");
    expect(groupIds).toContain("evidence");
    expect(groupIds).toContain("settings");
    // Knowledge and Labs have zero enabled panels in the Lite Stencil, so their groups disappear.
    expect(groupIds).not.toContain("knowledge");
    expect(groupIds).not.toContain("labs");
  });

  test("physically prunes disabled route imports from panels.tsx at build time (#2526)", () => {
    const rawPanelsTsx = readFileSync(resolve(__dirname, "panels.tsx"), "utf-8");
    const liteEnabled = parseStencilEnabledPanelIds(
      "dashboard,live,incidents,detection-readiness,alert-quality,configuration-baselines,conversation-delivery,pantheon,agent-activity,rules,trace,audit,settings-general,settings-integrations",
    );
    const transformed = transformPanelsSourceForStencil(rawPanelsTsx, liteEnabled);

    // Included Lite Observe & Alert routes remain in the transformed source.
    expect(transformed).toContain("export const CORE_PANELS: readonly ConsolePanel[] = [");
    expect(transformed).toContain('import("./routes/live")');
    expect(transformed).toContain('import("./routes/incidents")');
    expect(transformed).toContain('import("./routes/detection-readiness")');
    expect(transformed).toContain('import("./routes/alert-quality")');
    expect(transformed).toContain('import("./routes/audit")');

    // Excluded heavy routes are physically absent from the transformed source.
    expect(transformed).not.toContain('import("./routes/aks-commerce")');
    expect(transformed).not.toContain('import("./routes/cost-governance")');
    expect(transformed).not.toContain('import("./routes/gpu-monitoring")');
    expect(transformed).not.toContain('import("./routes/knowledge-domain")');
    expect(transformed).not.toContain('import("./routes/code-security")');
    expect(transformed).not.toContain('import("./routes/workflow-builder")');
    expect(transformed).not.toContain('import("./routes/analytics-hubs")');
  });
});
