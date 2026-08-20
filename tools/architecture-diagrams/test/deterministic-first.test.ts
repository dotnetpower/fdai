import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDiagram } from "../src/compiler.js";
import type { Locale } from "../src/model/types.js";
import { parseDiagram } from "../src/model/validate.js";

const deterministicFirstUrl = new URL(
  "../../../docs/diagrams/fdai-deterministic-first-01.diagram.yaml",
  import.meta.url,
);

test("deterministic-first keeps tier selection separate from execution authority", async () => {
  const spec = parseDiagram(await readFile(deterministicFirstUrl, "utf8"));

  assert.equal(spec.kind, "flowchart");
  assert.deepEqual(
    spec.groups.map((group) => group.id),
    ["intake", "tier-ladder", "authority", "closure", "audit-closure"],
  );
  assert.equal(spec.nodes.length, 12);
  assert.equal(spec.edges.length, 18);

  for (const tier of ["t0", "t1", "t2"]) {
    assert.ok(
      spec.edges.some(
        (edge) => edge.from === tier && edge.to === "risk-authority",
      ),
      `${tier} must pass through the shared authority gate`,
    );
  }
  assert.ok(
    spec.edges.some(
      (edge) => edge.from === "t2" && edge.to === "human-review",
    ),
  );
  assert.ok(
    spec.edges.some(
      (edge) => edge.from === "context-hold" && edge.to === "audit",
    ),
  );
  assert.deepEqual(
    spec.nodes
      .filter((node) => node.parent === "closure")
      .map((node) => node.id),
    ["automatic", "approval", "no-change"],
  );
  assert.ok(
    spec.edges.every(
      (edge) => edge.label?.ko !== "yes" && edge.label?.ko !== "no",
    ),
  );

  const artifacts = await compileDiagram(spec);
  for (const locale of ["en", "ko"] satisfies Locale[]) {
    const svg = artifacts.find(
      (artifact) => artifact.path === `fdai-deterministic-first-01.${locale}.svg`,
    );
    assert.ok(svg);
    const source = svg.content.toString("utf8");
    assert.equal([...source.matchAll(/data-node-id=/g)].length, spec.nodes.length);
    assert.equal([...source.matchAll(/data-edge-id=/g)].length, spec.edges.length);
    assert.equal(
      [...source.matchAll(/class="diagram-group\b/g)].length,
      spec.groups.length,
    );
    assert.match(source, /data-node-id="risk-authority"/u);
    assert.match(source, /data-node-id="audit"/u);
  }
});
