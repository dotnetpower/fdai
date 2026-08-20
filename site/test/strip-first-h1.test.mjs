import assert from "node:assert/strict";
import test from "node:test";

import { remarkStripFirstH1 } from "../src/plugins/strip-first-h1.mjs";

const h1 = (value) => ({
  type: "heading",
  depth: 1,
  children: [{ type: "text", value }],
});

test("front-matter title owns the rendered H1 even when Markdown wording differs", () => {
  const tree = { type: "root", children: [h1("Markdown wording"), { type: "paragraph", children: [] }] };
  remarkStripFirstH1()(tree, { data: { astro: { frontmatter: { title: "Site wording" } } } });

  assert.equal(tree.children[0].type, "paragraph");
});

test("a page without a front-matter title keeps its Markdown H1", () => {
  const tree = { type: "root", children: [h1("Only heading")] };
  remarkStripFirstH1()(tree, { data: { astro: { frontmatter: {} } } });

  assert.equal(tree.children[0].type, "heading");
});
