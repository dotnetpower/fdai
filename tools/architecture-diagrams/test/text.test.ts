import assert from "node:assert/strict";
import test from "node:test";

import {
  NODE_ICON_SIZE,
  NODE_LABEL_GAP,
  edgeLabelGeometry,
  nodeGeometry,
  visualUnits,
  wrapText,
} from "../src/model/text.js";

test("CJK glyphs consume more visual width than Latin glyphs", () => {
  assert.ok(visualUnits("감사기록") > visualUnits("audit"));
});

test("wrapping never truncates long unbroken labels", () => {
  const source = "AnExtremelyLongUnbrokenArchitectureComponentName";
  const lines = wrapText(source, 8);
  assert.equal(lines.join(""), source);
  assert.ok(lines.length > 3);
});

test("node geometry reserves separate icon and text zones for both locales", () => {
  const geometry = nodeGeometry({
    id: "sample",
    kind: "process",
    label: {
      en: "Verification and architecture safety check",
      ko: "근거 및 아키텍처 안전성 검토",
    },
  });
  assert.ok(geometry.labelTop >= geometry.iconTop + NODE_ICON_SIZE + NODE_LABEL_GAP);
  assert.ok(geometry.height > 96);
});

test("edge labels reserve the widest bilingual text", () => {
  const geometry = edgeLabelGeometry({
    id: "edge",
    from: "a",
    to: "b",
    kind: "approval",
    label: { en: "approval", ko: "사람 승인 요청" },
  });
  assert.ok(geometry);
  assert.ok(geometry.width >= 64);
  assert.ok(geometry.height >= 24);
});
