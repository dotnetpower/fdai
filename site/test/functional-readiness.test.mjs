import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";

const documents = new URL("../../docs/user-guide/concepts/", import.meta.url);
const parser = unified().use(remarkParse).use(remarkGfm);
const allowedStates = new Set(["ready", "partial", "blocked", "planned", "not-assessed"]);

function text(node) {
  return node.value ?? (node.children ?? []).map(text).join("");
}

function rows(tree) {
  return tree.children.filter((node) => node.type === "table")
    .flatMap((table) => table.children.slice(1));
}

function readinessBadges(node) {
  const html = (node.children ?? []).map((child) => child.value ?? "").join("");
  return [...html.matchAll(
    /<span class="fdai-readiness-badge" data-readiness="([^"]+)">([^<]+)<\/span>/gu,
  )].map((match) => ({ state: match[1], label: match[2] }));
}

function links(node) {
  const found = [];
  const visit = (current) => {
    if (current.type === "link") found.push(current);
    for (const child of current.children ?? []) visit(child);
  };
  visit(node);
  return found;
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
    const [badge] = readinessBadges(row.children[1]);
    assert.ok(badge, `missing assessment badge: ${id}`);
    assert.ok(allowedStates.has(badge.state), `unknown state: ${badge.state}`);
    evidence.set(id, { state: badge.state, label: badge.label, anchor: id.toLowerCase().replace(".", "-") });
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
      const [status] = readinessBadges(row.children[3]);
      assert.ok(status, `missing status badge: ${id}`);
      assert.equal(status.state, evidence.get(id)?.state, `state mismatch: ${id}`);
      assert.equal(status.label, evidence.get(id)?.label, `label mismatch: ${id}`);
      assert.equal(links(row.children[3]).length, 0, `${id}: badge must not be a link`);
    }
  });

  test(`readiness${suffix}: status legend explains badges and function links open evidence`, async () => {
    const { functions, evidence, specificationTree, assessment } = await load(suffix);
    const heading = suffix ? "준비 상태 정의" : "Readiness states";
    const definitions = suffix ? "#준비-상태-정의" : "#readiness-states";
    assert.ok(specificationTree.children.some((node) => node.type === "heading" && text(node) === heading));
    assert.ok(links(specificationTree).some((link) => link.url === definitions));
    for (const row of functions) {
      const functionLink = row.children[1].children.find((node) => node.type === "link");
      assert.ok(functionLink, "every function needs an evidence link");
      const id = text(functionLink).match(/^F\d{2}\.\d+/u)[0];
      assert.equal(links(row.children[3]).length, 0, `${id}: status badge should be static`);
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
      entry.states.push(evidence.get(id).label);
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
      const count = [...evidence.values()].filter((entry) => entry.label === state).length;
      assert.ok(specification.includes(`${state} ${count}/52`), `wrong overall ${state} count`);
    }
  });
}

test("English and Korean readiness decisions agree", async () => {
  const english = await load("");
  const korean = await load("-ko");
  assert.deepEqual([...english.evidence], [...korean.evidence]);
});
