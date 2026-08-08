import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  centerViewBox,
  contentViewBox,
  fitViewBox,
  interactiveInitialViewBox,
  needsReadableInitialCrop,
  panViewBox,
  zoomPercentage,
  zoomViewBox,
} from "../src/viewer/viewport.js";

const bounds = { x: 0, y: 88, width: 1600, height: 712 };

test("content view removes the duplicated SVG heading band", () => {
  assert.deepEqual(contentViewBox({ x: 0, y: 0, width: 1600, height: 800 }), bounds);
});

test("narrow viewports start with a readable left-side crop", () => {
  assert.deepEqual(fitViewBox(bounds, 400, 500), {
    x: 0,
    y: 88,
    width: 569.6,
    height: 712,
  });
  assert.deepEqual(fitViewBox(bounds, 1600, 712), bounds);
});

test("compact initial view leaves room to pan on both axes", () => {
  const compact = interactiveInitialViewBox(bounds, 400, 500, true);
  assert.equal(compact.x, 0);
  assert.equal(compact.y, 88);
  assert.ok(Math.abs(compact.width - 284.8) < 0.001);
  assert.ok(Math.abs(compact.height - 356) < 0.001);
  assert.ok(compact.width < bounds.width);
  assert.ok(compact.height < bounds.height);
  assert.deepEqual(interactiveInitialViewBox(bounds, 1600, 712, false), bounds);
});

test("dense diagrams start cropped even in a wide browser", () => {
  assert.equal(needsReadableInitialCrop(bounds, 800, false), true);
  assert.equal(needsReadableInitialCrop(bounds, 1200, false), false);
  assert.equal(needsReadableInitialCrop(bounds, 1600, true), true);
});

test("chart view can center the compact crop", () => {
  const compact = interactiveInitialViewBox(bounds, 400, 500, true);
  const centered = centerViewBox(compact, bounds);

  assert.ok(centered.x > compact.x);
  assert.ok(centered.y > compact.y);
  assert.equal(centered.width, compact.width);
  assert.equal(centered.height, compact.height);
});

test("zoom anchors the selected point and cannot zoom beyond fit", () => {
  const zoomed = zoomViewBox(bounds, bounds, 0.5, 0.25, 0.75);
  assert.deepEqual(zoomed, { x: 200, y: 355, width: 800, height: 356 });
  assert.deepEqual(zoomViewBox(bounds, bounds, 2), bounds);
  assert.equal(zoomPercentage(zoomed, bounds), 200);
});

test("pan stays inside diagram content bounds", () => {
  const zoomed = zoomViewBox(bounds, bounds, 0.5);
  assert.equal(panViewBox(zoomed, bounds, -10_000, -10_000).x, bounds.x);
  assert.equal(panViewBox(zoomed, bounds, 10_000, 10_000).x, 800);
});

test("viewer leaves mouse-wheel scrolling to the page", async () => {
  const viewer = await readFile(
    new URL("../src/viewer/architecture-diagram.ts", import.meta.url),
    "utf8",
  );

  assert.doesNotMatch(viewer, /addEventListener\(\s*["']wheel["']/u);
});

test("toolbar floats over the diagram and reveals on hover or focus", async () => {
  const viewer = await readFile(
    new URL("../src/viewer/architecture-diagram.ts", import.meta.url),
    "utf8",
  );

  assert.match(viewer, /\.shell \{[^}]*position: relative/u);
  assert.match(viewer, /\.toolbar \{[^}]*position: absolute/u);
  assert.match(viewer, /\.shell:hover \.toolbar, \.shell:focus-within \.toolbar/u);
  assert.match(viewer, /@media \(hover: none\)[^{]*\{[^}]*\.toolbar/u);
  assert.doesNotMatch(viewer, /border-bottom:/u);
  assert.match(viewer, /\.shell:fullscreen \.stage \{ height: 100vh; \}/u);
  assert.match(viewer, /classList\.add\("is-keyboard-focused"\)/u);
  assert.match(viewer, /classList\.remove\("is-keyboard-focused"\)/u);
});
