import assert from "node:assert/strict";
import test from "node:test";

import {
  CALM_SLATE_DARK,
  CALM_SLATE_LIGHT,
  calmSlateFoundationCss,
  embeddedThemeCss,
  standaloneThemeCss,
} from "../src/render/theme.js";
import { layoutDiagram } from "../src/layout/elk.js";
import { validateDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

test("light palette maps semantic roles to Calm Slate colors", () => {
  assert.equal(CALM_SLATE_LIGHT["--fdai-diagram-canvas"], "#fbfaf9");
  assert.equal(CALM_SLATE_LIGHT["--fdai-diagram-edge-request"], "#44688e");
  assert.equal(CALM_SLATE_LIGHT["--fdai-diagram-edge-audit"], "#5e8259");
  assert.equal(CALM_SLATE_LIGHT["--fdai-diagram-edge-mutation"], "#bc7449");
  assert.equal(CALM_SLATE_LIGHT["--fdai-diagram-edge-rollback"], "#ac5a5a");
});

test("dark palette stays warm and avoids a black canvas", () => {
  assert.equal(CALM_SLATE_DARK["--fdai-diagram-canvas"], "#171a1d");
  assert.notEqual(CALM_SLATE_DARK["--fdai-diagram-canvas"], "#000000");
  assert.equal(CALM_SLATE_DARK["--fdai-diagram-chart-2"], "#71a097");
});

test("standalone and embedded theme scopes remain separate", () => {
  assert.match(standaloneThemeCss(), /svg\[data-diagram-id\]:not\(\[data-embedded\]\)/);
  assert.match(standaloneThemeCss(), /prefers-color-scheme: dark/);
  assert.match(embeddedThemeCss(), /:host-context\(\[data-theme="dark"\]\)/);
});

test("foundation excludes the Azure reference profile", () => {
  const css = calmSlateFoundationCss();
  assert.match(css, /not\(\[data-profile="azure-reference"\]\)/);
    assert.match(css, /data-profile="azure-reference"[^}]+is-keyboard-focused/);
  assert.match(css, /Segoe UI Variable Text/);
  assert.match(css, /stroke-width: 1/);
  assert.match(css, /prefers-reduced-motion: reduce/);
  assert.match(css, /\.edge-path \{ transition: none; \}/);
});

test("render fallbacks use the Calm Slate semantic palette", async () => {
  const spec = validateDiagram({
    id: "theme-fallback",
    version: 1,
    kind: "flowchart",
    locales: {
      en: { title: "Theme", description: "Theme", alt: "Theme fallback." },
      ko: { title: "테마", description: "테마", alt: "테마 fallback입니다." },
    },
    canvas: { width: 640, height: 360, direction: "RIGHT" },
    groups: [],
    nodes: [
      { id: "source", kind: "process", tone: "input", label: { en: "Source", ko: "원본" } },
      { id: "target", kind: "process", tone: "policy", label: { en: "Target", ko: "대상" } },
    ],
    edges: [{ id: "request", from: "source", to: "target", kind: "request" }],
  });
  const svg = await renderSvg(spec, await layoutDiagram(spec), "en");

  assert.match(svg, /var\(--fdai-diagram-edge-request, #44688e\)/);
  assert.match(svg, /var\(--fdai-diagram-tone-input-fill, #f2f5f8\)/);
});
