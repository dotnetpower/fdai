import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDiagram } from "../src/compiler.js";
import type { Locale } from "../src/model/types.js";
import { parseDiagram } from "../src/model/validate.js";

const handoverUrl = new URL(
  "../../../docs/diagrams/fdai-ownership-and-handover-01.diagram.yaml",
  import.meta.url,
);

test("ownership handover stays review-only until validated activation", async () => {
  const spec = parseDiagram(await readFile(handoverUrl, "utf8"));

  assert.deepEqual(
    spec.groups.map((group) => group.id),
    ["ingest", "interpret", "resolve", "validate", "govern", "activate"],
  );
  assert.equal(spec.nodes.length, 15);
  assert.equal(spec.edges.length, 19);

  const interpreter = spec.nodes.find((node) => node.id === "grounded-interpreter");
  assert.ok(interpreter?.content?.some((item) => item.en.includes("default abstains")));

  const validation = spec.nodes.find((node) => node.id === "draft-validation");
  assert.ok(validation?.content?.some((item) => item.en.includes("15-agent pantheon")));
  assert.ok(validation?.content?.some((item) => item.en.includes("no access-role fields")));

  const draft = spec.nodes.find((node) => node.id === "inert-draft");
  assert.ok(draft?.content?.some((item) => item.en.includes("grants no RBAC")));

  assert.ok(
    spec.edges.some(
      (edge) => edge.from === "draft-pr" && edge.to === "human-review",
    ),
  );
  assert.ok(
    spec.edges.some(
      (edge) => edge.from === "loader-validation" && edge.to === "active-map",
    ),
  );
  assert.ok(
    !spec.edges.some(
      (edge) => edge.to === "active-map" && edge.from !== "loader-validation",
    ),
  );
  for (const source of ["draft-validation", "human-review", "loader-validation"]) {
    assert.ok(
      spec.edges.some(
        (edge) => edge.from === source && edge.to === "unchanged",
      ),
      `${source} must preserve an unchanged outcome`,
    );
  }
  assert.ok(
    spec.edges.some((edge) => edge.from === "unchanged" && edge.to === "audit"),
  );

  const artifacts = await compileDiagram(spec);
  for (const locale of ["en", "ko"] satisfies Locale[]) {
    const svg = artifacts.find(
      (artifact) =>
        artifact.path === `fdai-ownership-and-handover-01.${locale}.svg`,
    );
    assert.ok(svg);
    const source = svg.content.toString("utf8");
    assert.equal([...source.matchAll(/data-node-id=/g)].length, spec.nodes.length);
    assert.equal([...source.matchAll(/data-edge-id=/g)].length, spec.edges.length);
    assert.equal(
      [...source.matchAll(/class="diagram-group\b/g)].length,
      spec.groups.length,
    );
    assert.match(source, /data-node-id="inert-draft"/u);
    assert.match(source, /data-node-id="active-map"/u);
  }
});
