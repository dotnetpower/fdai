import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  navigationLabels,
  navigationModeForPath,
  navigationScrollKey,
} from "../src/scripts/focused-navigation.mjs";

test("SRE routes start in focused navigation", () => {
  for (const path of [
    "/sre",
    "/sre/incident-management/",
    "/ko/sre/scenario-validation-inventory/",
    "/concepts/sre-foundations/",
    "/ko/concepts/sre-foundations/",
  ]) {
    assert.equal(navigationModeForPath(path), "sre", path);
  }
});

test("unrelated routes keep the global documentation tree", () => {
  for (const path of [
    "/",
    "/get-started/",
    "/concepts/risk-tiers/",
    "/capabilities/resilience/",
    "/reference/roadmap/",
  ]) {
    assert.equal(navigationModeForPath(path), "global", path);
  }
});

test("back labels follow the page locale", () => {
  assert.equal(navigationLabels("en").back, "Back to all documentation sections");
  assert.equal(navigationLabels("ko-KR").back, "모든 문서 섹션으로 돌아가기");
});

test("sidebar scroll storage is isolated by locale and mode", () => {
  assert.equal(navigationScrollKey("en", "global"), "fdai-sidebar-scroll:en:global");
  assert.equal(navigationScrollKey("en-US", "sre"), "fdai-sidebar-scroll:en:sre");
  assert.equal(navigationScrollKey("ko-KR", "global"), "fdai-sidebar-scroll:ko:global");
  assert.equal(navigationScrollKey("ko", "sre"), "fdai-sidebar-scroll:ko:sre");
});

test("sidebar keeps shadow and enforce as canonical technical terms", async () => {
  const config = await readFile(new URL("../astro.config.mjs", import.meta.url), "utf8");

  assert.match(config, /translations: \{ ko: "shadow 후 enforce" \}/);
  assert.doesNotMatch(config, /섬도우|쉐도우|섀도우/);
});

test("sidebar is server-rendered as either global or focused SRE navigation", async () => {
  const config = await readFile(new URL("../astro.config.mjs", import.meta.url), "utf8");
  const sidebar = await readFile(
    new URL("../src/components/FocusedSidebar.astro", import.meta.url),
    "utf8",
  );

  assert.match(config, /Sidebar: "\.\/src\/components\/FocusedSidebar\.astro"/);
  assert.match(sidebar, /mode === "sre"/);
  assert.match(sidebar, /SidebarSublist sublist=\{focusedSidebar\}/);
  assert.match(sidebar, /SidebarSublist sublist=\{globalSidebar\}/);
  assert.doesNotMatch(sidebar, /data-fdai-nav-mode|MutationObserver/);
});
