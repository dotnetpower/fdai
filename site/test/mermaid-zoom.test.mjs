import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  clampZoom,
  createPanGesture,
  scaledSvgWidth,
  shouldCloseBackdrop,
  zoomLabels,
} from "../src/scripts/mermaid-zoom.mjs";

test("zoom clamps to supported bounds and resizes the SVG itself", () => {
  assert.equal(clampZoom(0.01), 0.2);
  assert.equal(clampZoom(20), 8);
  assert.equal(scaledSvgWidth(1000, 1.44), 1440);
});

test("a drag suppresses the generated backdrop click", () => {
  const gesture = createPanGesture();
  gesture.start(100, 100, 10, 20);

  assert.deepEqual(gesture.move(130, 140), {
    tx: 40,
    ty: 60,
    moved: true,
  });
  assert.equal(gesture.end(), true);
  assert.equal(shouldCloseBackdrop(true, true), false);
});

test("a stationary backdrop click still closes the overlay", () => {
  const gesture = createPanGesture();
  gesture.start(100, 100, 10, 20);
  gesture.move(102, 102);

  assert.equal(gesture.end(), false);
  assert.equal(shouldCloseBackdrop(true, false), true);
  assert.equal(shouldCloseBackdrop(false, false), false);
});

test("pan blocks native text selection in script and CSS", async () => {
  const script = await readFile(
    new URL("../src/scripts/mermaid-zoom.mjs", import.meta.url),
    "utf8",
  );
  const css = await readFile(new URL("../src/styles/custom.css", import.meta.url), "utf8");

  assert.match(
    script,
    /stage\.addEventListener\("pointerdown",[\s\S]*?event\.preventDefault\(\)[\s\S]*?removeAllRanges\(\)/,
  );
  assert.match(css, /\.mermaid-zoom-stage\s*\{[\s\S]*?user-select:\s*none/);
});

test("dialog labels follow the page locale", () => {
  assert.equal(zoomLabels("en-US").dialog, "Expanded diagram");
  assert.equal(zoomLabels("ko-KR").dialog, "확대된 다이어그램");
  assert.equal(zoomLabels("ko").close, "닫기");
  assert.equal(zoomLabels("ko").zoomLevel, "확대 비율");
});

test("zoom dialog keeps keyboard focus inside and restores its opener", async () => {
  const script = await readFile(
    new URL("../src/scripts/mermaid-zoom.mjs", import.meta.url),
    "utf8",
  );

  assert.match(script, /pre\.setAttribute\("role", "button"\)/);
  assert.match(script, /event\.key !== "Enter" && event\.key !== " "/);
  assert.match(script, /event\.key !== "Tab"/);
  assert.match(script, /closeButton\.focus/);
  assert.match(script, /opener\?\.focus/);
});

test("keyboard users can zoom, reset, and pan the expanded diagram", async () => {
  const script = await readFile(
    new URL("../src/scripts/mermaid-zoom.mjs", import.meta.url),
    "utf8",
  );

  assert.match(script, /event\.key === "\+" \|\| event\.key === "="/);
  assert.match(script, /event\.key === "0"/);
  assert.match(script, /event\.key === "ArrowLeft"/);
  assert.match(script, /aria-live", "polite"/);
});
