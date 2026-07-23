import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { parseDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

const overviewUrl = new URL(
  "../../../docs/diagrams/fdai-system-overview.diagram.yaml",
  import.meta.url,
);

test("canonical overview exposes the five architecture layers", async () => {
  const spec = parseDiagram(await readFile(overviewUrl, "utf8"));
  const labels = new Map(spec.groups.map((group) => [group.id, group.label.en]));

  assert.equal(labels.get("fdai-control-plane"), "1. Headless FDAI control plane");
  assert.equal(labels.get("action-delivery"), "2. Action delivery");
  assert.equal(labels.get("operator-console-layer"), "3. Operator console");
  assert.equal(labels.get("human-channel"), "4. Human channel");
  assert.equal(labels.get("rule-catalog-layer"), "5. Rule catalog");
  assert.equal(
    spec.groups.find((group) => group.id === "rule-catalog-layer")?.placement,
    "below",
  );

  const parentByNode = new Map(spec.nodes.map((node) => [node.id, node.parent]));
  assert.equal(parentByNode.get("remediation-pr"), "action-delivery");
  assert.equal(parentByNode.get("read-only-console"), "operator-console-layer");
  assert.equal(parentByNode.get("chatops"), "human-channel");
  assert.equal(parentByNode.get("rule-catalog"), "rule-catalog-layer");
});

test("canonical overview rounds routed corners while preserving direct hops", async () => {
  const spec = parseDiagram(await readFile(overviewUrl, "utf8"));
  const layout = await layoutDiagram(spec);
  const svg = await renderSvg(spec, layout, "en");
  const paths = [...svg.matchAll(/<path class="edge-path" d="([^"]+)"[^>]*marker-end/g)].map(
    (match) => match[1] ?? "",
  );

  assert.ok(paths.filter((path) => path.includes("Q")).length >= 6);
  assert.ok(paths.some((path) => !path.includes("Q")));
  assert.match(svg, /class="group-header"/);

  const controlFlow = layout.groups.get("control-flow");
  const ruleCatalog = layout.groups.get("rule-catalog-layer");
  assert.ok(controlFlow && ruleCatalog);
  assert.ok(ruleCatalog.y > controlFlow.y + controlFlow.height);

  for (const edgeId of ["bus-to-ingest", "catalog-to-decision"]) {
    const match = svg.match(
      new RegExp(`data-edge-id="${edgeId}"[\\s\\S]*?<path class="edge-path" d="([^"]+)"`),
    );
    assert.ok(match);
    assert.equal(match[1]?.match(/[MLQ]/g)?.length, 2);
    assert.doesNotMatch(match[1] ?? "", /Q/);
  }

  for (const edgeId of [
    "risk-to-approval",
    "executor-to-remediation",
    "audit-to-console",
  ]) {
    const match = svg.match(
      new RegExp(`data-edge-id="${edgeId}"[\\s\\S]*?<path class="edge-path" d="([^"]+)"`),
    );
    assert.ok(match);
    assert.match(match[1] ?? "", /C/);
  }
});
