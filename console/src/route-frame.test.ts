import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import { describeLoadFailure } from "./components/ui-shell";
import { resolvePanels } from "./panels";
import { routeFrameFor, wideFramePanelIds } from "./route-frame";

const workspaceStyles = readFileSync(
  fileURLToPath(new URL("./routes/calm-slate-workspaces.css", import.meta.url)),
  "utf8",
);
const sharedTokens = readFileSync(
  fileURLToPath(new URL("../../ui/calm-slate-tokens.css", import.meta.url)),
  "utf8",
);

describe("route frame", () => {
  test("defaults every registered panel to the standard frame unless it is declared wide", () => {
    const wide = new Set(wideFramePanelIds());
    for (const panel of resolvePanels()) {
      expect(routeFrameFor(panel.id)).toBe(wide.has(panel.id) ? "wide" : "standard");
    }
    expect(routeFrameFor("fork-added-panel")).toBe("standard");
  });

  test("only names panels that exist in the registry", () => {
    const registered = new Set(resolvePanels().map((panel) => panel.id));
    for (const id of wideFramePanelIds()) expect(registered.has(id)).toBe(true);
  });

  test("owns both frame widths through shared tokens and shell-level selectors", () => {
    expect(sharedTokens).toMatch(/--cs-route-width:\s*1240px/);
    expect(sharedTokens).toMatch(/--cs-route-width-wide:\s*1600px/);
    expect(workspaceStyles).toMatch(
      /main\[data-route-frame="standard"\] > \*\s*\{[^}]*var\(--cs-route-width\)/,
    );
    expect(workspaceStyles).toMatch(
      /main\[data-route-frame="wide"\] > \*\s*\{[^}]*var\(--cs-route-width-wide\)/,
    );
  });
});

describe("describeLoadFailure", () => {
  test("separates a browser transport failure from the failed resource", () => {
    const described = describeLoadFailure("Failed to load Reports: Failed to fetch");
    expect(described.title).toBe("Failed to load Reports");
    expect(described.detail).toContain("could not be reached");
  });

  test("keeps authoritative server messages untouched", () => {
    expect(describeLoadFailure("Failed to load Reports: 403 Forbidden")).toEqual({
      title: "Failed to load Reports: 403 Forbidden",
    });
  });
});
