import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDiagram } from "../src/compiler.js";
import { layoutDiagram } from "../src/layout/elk.js";
import { validateDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

const canonicalUrl = new URL(
  "../../../docs/diagrams/fdai-delivery-roadmap.diagram.yaml",
  import.meta.url,
);

function ganttSpec() {
  return validateDiagram({
    id: "gantt-sample",
    version: 1,
    kind: "gantt",
    locales: {
      en: { title: "Delivery", description: "Delivery plan", alt: "Two dependent tasks." },
      ko: { title: "전달", description: "전달 계획", alt: "두 개의 의존 작업입니다." },
    },
    canvas: { width: 960, height: 480, direction: "RIGHT" },
    groups: [
      { id: "foundation", kind: "layer", label: { en: "Foundation", ko: "기반" } },
    ],
    nodes: [
      { id: "design", parent: "foundation", kind: "process", shape: "bar", label: { en: "Design", ko: "설계" }, start: 0, duration: 4, status: "done", progress: 100 },
      { id: "build", parent: "foundation", kind: "process", shape: "bar", label: { en: "Build", ko: "구현" }, after: "design", duration: 3, status: "active", progress: 45 },
    ],
    edges: [
      { id: "design-build", from: "design", to: "build", kind: "timeline" },
    ],
  });
}

test("lays dependent Gantt tasks on a shared time axis", async () => {
  const spec = ganttSpec();
  const layout = await layoutDiagram(spec);
  const design = layout.nodes.get("design")!;
  const build = layout.nodes.get("build")!;

  assert.ok(build.x >= design.x + design.width);
  assert.equal(design.height, 34);
  assert.ok(layout.groups.get("foundation")!.height > design.height);
  assert.equal(layout.edges.length, 1);
  const svg = await renderSvg(spec, layout, "en");
  assert.match(svg, /data-node-id="design"[^>]+transform="translate\(48 112\)"/);
});

test("accepts an ISO date axis", async () => {
  const spec = ganttSpec();
  spec.nodes[0]!.start = "2026-08-08";
  delete spec.nodes[1]!.after;
  spec.nodes[1]!.start = "2026-08-12";
  assert.doesNotThrow(() => validateDiagram(spec));
  const layout = await layoutDiagram(spec);
  assert.ok(layout.nodes.get("build")!.x > layout.nodes.get("design")!.x);
});

test("rejects incomplete and mixed Gantt schedules", () => {
  const spec = ganttSpec();
  delete spec.nodes[0]!.duration;
  assert.throws(() => validateDiagram(spec), /requires 'end' or 'duration'/);

  const mixed = ganttSpec();
  mixed.nodes[1]!.start = "2026-08-12";
  delete mixed.nodes[1]!.after;
  assert.throws(() => validateDiagram(mixed), /cannot mix numeric and date axes/);
});

test("compiles the canonical Gantt roadmap with status and progress", async () => {
  const spec = validateDiagram(
    (await import("yaml")).parse(await readFile(canonicalUrl, "utf8")),
  );
  const artifacts = await compileDiagram(spec);
  const koreanSvg = artifacts.find(
    (artifact) => artifact.path === "fdai-delivery-roadmap.ko.svg",
  );

  assert.ok(koreanSvg);
  const svg = koreanSvg.content.toString("utf8");
  assert.match(svg, /data-shape="bar"/);
  assert.match(svg, /data-status="critical"/);
  assert.match(svg, /class="node-progress"/);
  const manifestArtifact = artifacts.find(
    (artifact) => artifact.path === "fdai-delivery-roadmap.manifest.json",
  );
  assert.ok(manifestArtifact);
  const manifest = JSON.parse(manifestArtifact.content.toString("utf8")) as {
    nodes: Array<{ id: string; status?: string; progress?: number; after?: string }>;
  };
  const contextProjection = manifest.nodes.find(
    (node) => node.id === "context-projection",
  );
  assert.equal(contextProjection?.status, "active");
  assert.equal(contextProjection?.progress, 65);
  assert.equal(contextProjection?.after, "ontology-contracts");
});
