import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";

const documents = new URL("../../docs/user-guide/concepts/", import.meta.url);
const parser = unified().use(remarkParse).use(remarkGfm);
const allowedStates = new Set(["Ready", "Partial", "Blocked", "Planned", "Not assessed", "미평가"]);

function text(node) {
  return node.value ?? (node.children ?? []).map(text).join("");
}

function rows(tree) {
  return tree.children.filter((node) => node.type === "table")
    .flatMap((table) => table.children.slice(1));
}

async function load(suffix) {
  const [specification, assessment] = await Promise.all([
    readFile(new URL(`functional-specification${suffix}.md`, documents), "utf8"),
    readFile(new URL(`functional-readiness${suffix}.md`, documents), "utf8"),
  ]);
  const specificationTree = parser.parse(specification);
  const assessmentTree = parser.parse(assessment);
  const functions = rows(specificationTree)
    .filter((row) => /^F\d{2}\.\d+\s/u.test(text(row.children[1])));
  const evidence = new Map();
  for (const row of rows(assessmentTree)) {
    const id = text(row.children[0]).match(/F\d{2}\.\d+/u)?.[0];
    if (!id) continue;
    assert.ok(!evidence.has(id), `duplicate assessment: ${id}`);
    const state = text(row.children[1]);
    assert.ok(allowedStates.has(state), `unknown state: ${state}`);
    evidence.set(id, { state, anchor: id.toLowerCase().replace(".", "-") });
  }
  return { specification, specificationTree, assessment, functions, evidence };
}

for (const suffix of ["", "-ko"]) {
  test(`readiness${suffix}: all 52 functions have matching individual assessments`, async () => {
    const { functions, evidence } = await load(suffix);
    assert.equal(functions.length, 52);
    assert.equal(evidence.size, 52);
    const seen = new Set();
    for (const row of functions) {
      const id = text(row.children[1]).match(/^F\d{2}\.\d+/u)[0];
      assert.ok(!seen.has(id), `duplicate function: ${id}`);
      seen.add(id);
      assert.equal(row.children.length, 4);
      const status = row.children[3].children.find((node) => node.type === "link");
      assert.ok(status, `missing status link: ${id}`);
      assert.equal(text(status), evidence.get(id)?.state, `state mismatch: ${id}`);
    }
  });

  test(`readiness${suffix}: status links explain states and function links open evidence`, async () => {
    const { functions, evidence, specificationTree, assessment } = await load(suffix);
    const heading = suffix ? "준비 상태 정의" : "Readiness states";
    const definitions = suffix ? "#준비-상태-정의" : "#readiness-states";
    assert.ok(specificationTree.children.some((node) => node.type === "heading" && text(node) === heading));
    for (const row of functions) {
      const functionLink = row.children[1].children.find((node) => node.type === "link");
      assert.ok(functionLink, "every function needs an evidence link");
      const id = text(functionLink).match(/^F\d{2}\.\d+/u)[0];
      const status = row.children[3].children.find((node) => node.type === "link");
      assert.equal(status.url, definitions, `${id}: status should explain its meaning`);
      const anchor = evidence.get(id).anchor;
      assert.equal(functionLink.url, `functional-readiness${suffix}.md#${anchor}`);
      assert.ok(assessment.includes(`id="${anchor}"`), `missing evidence anchor: ${id}`);
    }
  });

  test(`readiness${suffix}: group and overall counts agree with the evidence`, async () => {
    const { specification, functions, evidence } = await load(suffix);
    const groups = new Map();
    for (const row of functions) {
      const id = text(row.children[1]).match(/^F\d{2}\.\d+/u)[0];
      const group = id.split(".")[0];
      const entry = groups.get(group) ?? { rows: [], states: [] };
      entry.rows.push(row);
      entry.states.push(evidence.get(id).state);
      groups.set(group, entry);
    }
    assert.equal(groups.size, 15);
    for (const [group, entry] of groups) {
      const summary = text(entry.rows[0].children[0]);
      for (const state of ["Ready", "Partial"]) {
        const count = entry.states.filter((value) => value === state).length;
        assert.ok(summary.includes(`${state} ${count}/${entry.rows.length}`), `${group}: wrong ${state} count`);
      }
    }
    for (const state of ["Ready", "Partial"]) {
      const count = [...evidence.values()].filter((entry) => entry.state === state).length;
      assert.ok(specification.includes(`${state} ${count}/52`), `wrong overall ${state} count`);
    }
  });
}

test("English and Korean readiness decisions agree", async () => {
  const english = await load("");
  const korean = await load("-ko");
  assert.deepEqual([...english.evidence], [...korean.evidence]);
});
