import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDiagram } from "../src/compiler.js";
import type { Locale } from "../src/model/types.js";
import { parseDiagram } from "../src/model/validate.js";

const riskTiersUrl = new URL(
  "../../../docs/diagrams/fdai-risk-tiers-01.diagram.yaml",
  import.meta.url,
);

test("risk-tier decision text stays within its rendered surfaces", async () => {
  const spec = parseDiagram(await readFile(riskTiersUrl, "utf8"));
  const classifier = spec.nodes.find((node) => node.id === "c");
  const safeguards = spec.nodes.find((node) => node.id === "i");

  assert.ok(classifier);
  assert.equal(classifier.shape, "diamond");
  assert.equal(classifier.width, 320);
  assert.equal(classifier.height, 220);

  assert.ok(safeguards);
  assert.equal(safeguards.kind, "decision");
  assert.equal(safeguards.shape, "card");
  assert.equal(safeguards.content?.length, 2);

  const artifacts = await compileDiagram(spec);
  for (const locale of ["en", "ko"] satisfies Locale[]) {
    const svg = artifacts.find(
      (artifact) => artifact.path === `fdai-risk-tiers-01.${locale}.svg`,
    );
    assert.ok(svg);
    const source = svg.content.toString("utf8");
    assert.match(
      source,
      /data-node-id="c"[^>]*data-shape="diamond"/u,
    );
    assert.match(
      source,
      /data-node-id="i"[^>]*data-shape="card"/u,
    );
  }
});
