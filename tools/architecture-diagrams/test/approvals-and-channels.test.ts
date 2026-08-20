import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDiagram } from "../src/compiler.js";
import type { Locale } from "../src/model/types.js";
import { parseDiagram } from "../src/model/validate.js";

const approvalsUrl = new URL(
  "../../../docs/diagrams/fdai-approvals-and-channels-01.diagram.yaml",
  import.meta.url,
);

test("approval decisions persist and resume without direct execution authority", async () => {
  const spec = parseDiagram(await readFile(approvalsUrl, "utf8"));

  assert.deepEqual(
    spec.groups.map((group) => group.id),
    ["park", "notify", "decide", "record", "resume", "close"],
  );
  assert.equal(spec.nodes.length, 14);
  assert.equal(spec.edges.length, 16);

  assert.ok(
    spec.edges.some(
      (edge) =>
        edge.from === "risk-authority" &&
        edge.to === "pending-action" &&
        edge.kind === "write",
    ),
  );
  assert.ok(
    spec.edges.some(
      (edge) =>
        edge.from === "decision-registry" && edge.to === "decision-outbox",
    ),
  );
  assert.ok(
    spec.edges.some(
      (edge) =>
        edge.from === "decision-outbox" && edge.to === "resume-coordinator",
    ),
  );
  assert.ok(
    spec.edges.some(
      (edge) => edge.from === "resume-coordinator" && edge.to === "executor",
    ),
  );
  assert.ok(
    !spec.edges.some(
      (edge) =>
        ["decision-ingress", "callback-checks", "decision-outbox"].includes(
          edge.from,
        ) && edge.to === "executor",
    ),
  );

  const ingress = spec.nodes.find((node) => node.id === "decision-ingress");
  assert.ok(ingress?.content?.some((item) => item.en.includes("Console approve_hil")));
  assert.ok(ingress?.content?.some((item) => item.en.includes("planned, not current")));
  assert.equal(spec.nodes.find((node) => node.id === "teams")?.label.en, "Teams A1 | Current");
  assert.ok(
    spec.edges.every(
      (edge) => edge.label?.ko !== "yes" && edge.label?.ko !== "no",
    ),
  );

  const artifacts = await compileDiagram(spec);
  for (const locale of ["en", "ko"] satisfies Locale[]) {
    const svg = artifacts.find(
      (artifact) =>
        artifact.path === `fdai-approvals-and-channels-01.${locale}.svg`,
    );
    assert.ok(svg);
    const source = svg.content.toString("utf8");
    assert.equal([...source.matchAll(/data-node-id=/g)].length, spec.nodes.length);
    assert.equal([...source.matchAll(/data-edge-id=/g)].length, spec.edges.length);
    assert.equal(
      [...source.matchAll(/class="diagram-group\b/g)].length,
      spec.groups.length,
    );
    assert.match(source, /data-node-id="decision-outbox"/u);
    assert.match(source, /data-node-id="resume-coordinator"/u);
  }
});
