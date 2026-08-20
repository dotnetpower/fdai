import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDiagram } from "../src/compiler.js";
import type { Locale } from "../src/model/types.js";
import { parseDiagram } from "../src/model/validate.js";

const getStartedUrl = new URL(
  "../../../docs/diagrams/fdai-get-started-01.diagram.yaml",
  import.meta.url,
);

test("get-started readiness opens only one bounded observation pilot", async () => {
  const spec = parseDiagram(await readFile(getStartedUrl, "utf8"));

  assert.deepEqual(
    spec.groups.map((group) => group.id),
    ["workload", "evidence", "action", "authority", "measurement", "platform"],
  );
  assert.equal(spec.nodes.length, 13);
  assert.equal(spec.edges.length, 12);

  const gates = [
    ["repeatable-check", "prepare-workload", "evidence-check"],
    ["evidence-check", "prepare-evidence", "action-check"],
    ["action-check", "prepare-action", "authority-check"],
    ["authority-check", "prepare-authority", "measurement-check"],
    ["measurement-check", "prepare-measurement", "platform-check"],
    ["platform-check", "prepare-platform", "observation-pilot"],
  ] as const;
  for (const [gate, prepare, next] of gates) {
    assert.ok(spec.edges.some((edge) => edge.from === gate && edge.to === prepare));
    assert.ok(spec.edges.some((edge) => edge.from === gate && edge.to === next));
  }
  assert.ok(
    !spec.edges.some(
      (edge) => edge.to === "observation-pilot" && edge.from !== "platform-check",
    ),
  );

  const action = spec.nodes.find((node) => node.id === "action-check");
  assert.ok(action?.content?.some((item) => item.en.includes("idempotency")));
  assert.ok(action?.content?.some((item) => item.en.includes("effect verification")));
  const evidence = spec.nodes.find((node) => node.id === "prepare-evidence");
  assert.ok(evidence?.content?.some((item) => item.en.includes("not the only")));
  const platform = spec.nodes.find((node) => node.id === "prepare-platform");
  assert.ok(platform?.content?.some((item) => item.en.includes("Slack A1")));

  const artifacts = await compileDiagram(spec);
  for (const locale of ["en", "ko"] satisfies Locale[]) {
    const svg = artifacts.find(
      (artifact) => artifact.path === `fdai-get-started-01.${locale}.svg`,
    );
    assert.ok(svg);
    const source = svg.content.toString("utf8");
    assert.equal([...source.matchAll(/data-node-id=/g)].length, spec.nodes.length);
    assert.equal([...source.matchAll(/data-edge-id=/g)].length, spec.edges.length);
    assert.equal(
      [...source.matchAll(/class="diagram-group\b/g)].length,
      spec.groups.length,
    );
    assert.match(source, /data-node-id="observation-pilot"/u);
  }
});
