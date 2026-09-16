import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { layoutDiagram } from "../src/layout/elk.js";
import { assertLayoutIntegrity, layoutIntegrityErrors } from "../src/layout/integrity.js";
import { parseDiagram } from "../src/model/validate.js";
import { renderSvg } from "../src/render/svg.js";

const overviewUrl = new URL(
  "../../../docs/diagrams/fdai-system-overview.diagram.yaml",
  import.meta.url,
);

test("AKS topology uses resource icons and attaches every route to its current endpoints", async () => {
  const spec = parseDiagram(await readFile(new URL(
    "../../../docs/diagrams/fdai-azure-aks-deployment.diagram.yaml",
    import.meta.url,
  ), "utf8"));
  const icons = new Map(spec.nodes.map(node => [node.id, node.icon]));
  for (const node of ["operator", "ingestion", "core", "worker", "executor"]) {
    assert.equal(icons.get(node), "deploy");
  }
  assert.equal(icons.get("jobs"), "cronjob");
  assert.equal(icons.get("system-pool"), "node");
  assert.equal(icons.get("user-pool"), "node");
  assert.equal(icons.get("entra"), "entra-id");
  assert.equal(icons.get("load-balancer"), "load-balancer");
  assert.equal(icons.get("apim"), "api-management-services");
  const layout = await layoutDiagram(spec);
  assertLayoutIntegrity(spec, layout);
  assert.deepEqual(layoutIntegrityErrors({ ...spec, kind: "network" }, layout), []);
  const shapes = new Map([...layout.groups, ...layout.nodes]);
  const access = layout.groups.get("browser-access")!;
  const cluster = layout.groups.get("aks")!;
  const services = layout.groups.get("azure-services")!;
  assert.ok(access.x + access.width < cluster.x);
  assert.ok(cluster.x + cluster.width < services.x);
  assert.ok(layout.width > layout.height);
  for (const id of ["sign-in", "browser-api", "gateway-backends"]) {
    const edge = layout.edges.find(candidate => candidate.id === id);
    assert.ok(edge);
    const source = shapes.get(edge.sources[0]!);
    const target = shapes.get(edge.targets[0]!);
    const section = edge.sections?.[0];
    assert.ok(source && target && section);
    assert.equal(section.startPoint.y, source.y + source.height);
    assert.equal(section.endPoint.y, target.y);
    for (const point of [section.startPoint, ...(section.bendPoints ?? []), section.endPoint]) {
      assert.equal(point.x, section.startPoint.x, `${id} must remain vertical within the access column`);
      assert.ok(point.y >= section.startPoint.y && point.y <= section.endPoint.y, id);
    }
  }
  const segments = layout.edges.flatMap(edge => (edge.sections ?? []).flatMap(section => {
    const points = [section.startPoint, ...(section.bendPoints ?? []), section.endPoint];
    return points.slice(1).map((end, index) => ({ id: edge.id, start: points[index]!, end }));
  })).filter(segment => segment.start.x !== segment.end.x || segment.start.y !== segment.end.y);
  for (const [index, first] of segments.entries()) {
    for (const second of segments.slice(index + 1)) {
      if (first.id === second.id) continue;
      const vertical = first.start.x === first.end.x && second.start.x === second.end.x && first.start.x === second.start.x;
      const horizontal = first.start.y === first.end.y && second.start.y === second.end.y && first.start.y === second.start.y;
      if (!vertical && !horizontal) continue;
      const axis = vertical ? "y" : "x";
      const overlap = Math.min(Math.max(first.start[axis], first.end[axis]), Math.max(second.start[axis], second.end[axis]))
        - Math.max(Math.min(first.start[axis], first.end[axis]), Math.min(second.start[axis], second.end[axis]));
      assert.ok(overlap <= 0, `${first.id} overlaps ${second.id}`);
    }
  }
  for (const edge of layout.edges) {
    const source = shapes.get(edge.sources[0]!);
    const target = shapes.get(edge.targets[0]!);
    assert.ok(source && target);
    for (const [point, shape] of [
      [edge.sections?.[0]?.startPoint, source],
      [edge.sections?.at(-1)?.endPoint, target],
    ] as const) {
      assert.ok(point, edge.id);
      assert.ok(point.x >= shape.x - 1 && point.x <= shape.x + shape.width + 1, edge.id);
      assert.ok(point.y >= shape.y - 1 && point.y <= shape.y + shape.height + 1, edge.id);
      assert.ok(Math.min(
        Math.abs(point.x - shape.x), Math.abs(point.x - shape.x - shape.width),
        Math.abs(point.y - shape.y), Math.abs(point.y - shape.y - shape.height),
      ) <= 1, edge.id);
    }
  }
  for (const locale of ["en", "ko"] as const) {
    const svg = await renderSvg(spec, layout, locale);
    assert.equal((svg.match(/<image /g) ?? []).length, spec.nodes.length);
    assert.doesNotMatch(svg, /href="https?:/);
  }
});

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

test("canonical overview avoids collisions while preserving direct hops", async () => {
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

  for (const [edgeId, route] of [
    ["bus-to-ingest", "orthogonal-outer"],
    ["executor-to-remediation", "orthogonal-outer"],
    ["audit-to-console", "orthogonal-outer"],
  ] as const) {
    const match = svg.match(
      new RegExp(`data-edge-id="${edgeId}"[\\s\\S]*?<path class="edge-path" d="([^"]+)"`),
    );
    assert.ok(match);
    assert.match(match[1] ?? "", /Q/);
    assert.match(svg, new RegExp(`data-edge-id="${edgeId}"[^>]+data-edge-route="${route}"`));
  }

  for (const edgeId of ["catalog-to-decision"]) {
    const match = svg.match(
      new RegExp(`data-edge-id="${edgeId}"[\\s\\S]*?<path class="edge-path" d="([^"]+)"`),
    );
    assert.ok(match);
    assert.equal(match[1]?.match(/[MLQ]/g)?.length, 2);
    assert.doesNotMatch(match[1] ?? "", /[QC]/);
  }

  for (const edgeId of ["risk-to-approval"]) {
    const match = svg.match(
      new RegExp(`data-edge-id="${edgeId}"[\\s\\S]*?<path class="edge-path" d="([^"]+)"`),
    );
    assert.ok(match);
    assert.match(match[1] ?? "", /C/);
  }
});
