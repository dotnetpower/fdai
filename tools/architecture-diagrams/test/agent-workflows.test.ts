import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { compileDiagram } from "../src/compiler.js";
import type { Locale } from "../src/model/types.js";
import { parseDiagram } from "../src/model/validate.js";

const workflowDirectory = new URL("../../../docs/diagrams/", import.meta.url);

test("agent workflows render centered messages with complete actor names", async () => {
  for (let index = 1; index <= 12; index += 1) {
    const suffix = String(index).padStart(2, "0");
    const id = `fdai-agent-workflows-${suffix}`;
    const spec = parseDiagram(
      await readFile(new URL(`${id}.diagram.yaml`, workflowDirectory), "utf8"),
    );

    assert.equal(spec.kind, "sequence");
    assert.ok(spec.nodes.every((node) => node.description));
    assert.ok(
      spec.nodes.every(
        (node) => !/\b[A-Za-z][A-Za-z0-9]*- ->/u.test(node.label.en),
      ),
    );

    const artifacts = await compileDiagram(spec);
    for (const locale of ["en", "ko"] satisfies Locale[]) {
      const svg = artifacts.find(
        (artifact) => artifact.path === `${id}.${locale}.svg`,
      );
      assert.ok(svg);
      const source = svg.content.toString("utf8");
      assert.equal(source.match(/class="node-body"/gu)?.length, spec.nodes.length);
      assert.equal(
        source.match(/transform="translate\(330 112\)"/gu)?.length,
        spec.nodes.length,
      );
      assert.doesNotMatch(source, /\b[A-Za-z][A-Za-z0-9]*- -&gt;/u);
    }
  }
});
