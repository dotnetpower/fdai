import assert from "node:assert/strict";
import test from "node:test";

import {
  NODE_BODY_LINE_HEIGHT,
  NODE_ICON_SIZE,
  NODE_LABEL_GAP,
  REFERENCE_NODE_ICON_SIZE,
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

test("node geometry reserves icon space only for visual node kinds", () => {
  const label = {
    en: "Verification and architecture safety check",
    ko: "근거 및 아키텍처 안전성 검토",
  };
  const agentGeometry = nodeGeometry({
    id: "agent",
    kind: "agent",
    label,
  });
  const processGeometry = nodeGeometry({
    id: "process",
    kind: "process",
    label,
  });
  assert.equal(agentGeometry.hasIcon, true);
  assert.ok(
    agentGeometry.labelTop >=
      agentGeometry.iconTop + NODE_ICON_SIZE + NODE_LABEL_GAP,
  );
  assert.equal(processGeometry.hasIcon, false);
  assert.equal(processGeometry.iconSize, 0);
  assert.equal(processGeometry.height, agentGeometry.height);
  assert.ok(processGeometry.labelTop < agentGeometry.labelTop);
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

test("icon presentation uses compact icon-forward geometry", () => {
  const geometry = nodeGeometry({
    id: "service",
    kind: "azure-service",
    icon: "key-vault",
    presentation: "icon",
    label: { en: "Key Vault", ko: "Key Vault" },
  });

  assert.equal(geometry.iconSize, REFERENCE_NODE_ICON_SIZE);
  assert.equal(geometry.width, 116);
  assert.ok(geometry.height < 100);
});

test("explicit node width overrides the presentation default", () => {
  const geometry = nodeGeometry({
    id: "endpoint",
    kind: "service",
    icon: "private-endpoint",
    presentation: "icon",
    label: { en: "PostgreSQL", ko: "PostgreSQL" },
    width: 100,
  });

  assert.equal(geometry.width, 100);
});

test("simple cards widen before wrapping a short bilingual label", () => {
  const geometry = nodeGeometry({
    id: "remediation",
    kind: "service",
    label: { en: "Remediation pull request", ko: "수정 pull request" },
  });

  assert.ok(geometry.width > 148);
  assert.equal(wrapText("수정 pull request", geometry.maxLabelUnits).length, 1);
});

test("node geometry expands for localized body content", () => {
  const geometry = nodeGeometry({
    id: "process",
    kind: "process",
    label: { en: "Interpret", ko: "해석" },
    content: [
      { en: "Extract intent and entities", ko: "의도와 엔터티 추출" },
      { en: "Capture context", ko: "컨텍스트 파악" },
    ],
  });

  assert.equal(geometry.width, 220);
  assert.ok(geometry.bodyTop > geometry.labelTop);
  assert.ok(geometry.height > 75);
});

test("database geometry keeps text below the cylinder cap", () => {
  const geometry = nodeGeometry({
    id: "evidence-store",
    kind: "store",
    shape: "database",
    label: { en: "Evidence store", ko: "근거 저장소" },
    content: [{ en: "Searchable evidence", ko: "검색 가능한 근거" }],
  });

  assert.ok(geometry.labelTop >= 28);
  assert.ok(geometry.height >= 88);
  assert.ok(geometry.bodyTop + NODE_BODY_LINE_HEIGHT < geometry.height);
});
