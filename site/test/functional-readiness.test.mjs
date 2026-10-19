import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkGfm from "remark-gfm";

const documents = new URL("../../docs/user-guide/concepts/", import.meta.url);
const parser = unified().use(remarkParse).use(remarkGfm);
const allowedStates = new Set(["ready", "partial", "blocked", "planned", "not-assessed"]);
const expectedBacklogIds = Object.entries({ F10: 4, F11: 3, F12: 4, F13: 3, F14: 4, F15: 3 })
  .flatMap(([group, count]) => Array.from({ length: count }, (_, index) => `${group}.${index + 1}`));

function stateLabel(state, suffix) {
  return {
    ready: "Ready",
    partial: "Partial",
    blocked: "Blocked",
    planned: "Planned",
    "not-assessed": suffix ? "미평가" : "Not assessed",
  }[state];
}

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

function singleReadinessBadge(node, suffix, id) {
  const badges = readinessBadges(node);
  assert.equal(badges.length, 1, `${id}: exactly one readiness badge is required`);
  const [badge] = badges;
  assert.ok(allowedStates.has(badge.state), `${id}: unknown state ${badge.state}`);
  assert.equal(badge.label, stateLabel(badge.state, suffix), `${id}: readiness label contradicts state`);
  return badge;
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
  const [specification, assessment, backlog] = await Promise.all([
    readFile(new URL(`functional-specification${suffix}.md`, documents), "utf8"),
    readFile(new URL(`functional-readiness${suffix}.md`, documents), "utf8"),
    readFile(new URL(`functional-readiness-backlog${suffix}.md`, documents), "utf8"),
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
    const badge = singleReadinessBadge(row.children[1], suffix, id);
    evidence.set(id, { state: badge.state, label: badge.label, anchor: id.toLowerCase().replace(".", "-") });
  }
  return { specification, specificationTree, assessment, functions, evidence, backlog };
}

function backlogRecords(backlog) {
  const tree = parser.parse(backlog);
  const work = new Map();
  const visit = (node) => {
    if (node.type === "listItem" && typeof node.checked === "boolean") {
      const id = text(node.children[0]).match(/^([A-Z]\d{2}), /u)?.[1];
      assert.ok(id, "every work package must start with a canonical ID");
      assert.ok(!work.has(id), `duplicate work package: ${id}`);
      work.set(id, node.checked);
    }
    for (const child of node.children ?? []) visit(child);
  };
  visit(tree);
  assert.ok(work.size, "missing work packages");
  const inventory = new Map();
  for (const row of rows(tree)) {
    const id = text(row.children[0]);
    if (!/^F\d{2}\.\d+$/u.test(id)) continue;
    assert.ok(!inventory.has(id), `duplicate inventory: ${id}`);
    assert.equal(row.children.length, 5, `${id}: missing required-package column`);
    const transition = text(row.children[1]).match(/^([A-Za-z -]+) -> ([A-Za-z -]+)$/u);
    assert.ok(transition, `${id}: malformed readiness transition`);
    const previous = transition[1].toLowerCase().replaceAll(" ", "-");
    const state = transition[2].toLowerCase().replaceAll(" ", "-");
    assert.ok(allowedStates.has(previous) && allowedStates.has(state), `${id}: unknown state`);
    const raw = text(row.children[4]);
    assert.ok(raw === "-" || /^[A-Z]\d{2}(?:, [A-Z]\d{2})*$/u.test(raw),
      `${id}: required packages must be exact comma-separated IDs or -`);
    const required = raw === "-" ? [] : raw.split(", ");
    assert.equal(new Set(required).size, required.length, `${id}: duplicate required package`);
    for (const workId of required) assert.ok(work.has(workId), `${id}: unknown work package ${workId}`);
    inventory.set(id, { previous, state, required });
  }
  return { work, inventory };
}

function validateBacklog(records, evidence) {
  const expected = [...evidence.keys()].filter((id) => Number(id.slice(1).split(".")[0]) >= 10);
  assert.deepEqual(expected.sort(), expectedBacklogIds.toSorted(), "F10-F15 function IDs changed");
  assert.deepEqual([...records.inventory.keys()].sort(), expected.sort(), "incomplete F10-F15 inventory");
  for (const [id, entry] of records.inventory) {
    assert.equal(entry.state, evidence.get(id)?.state, `${id}: backlog/assessment state mismatch`);
    if (entry.state === "partial") assert.ok(entry.required.length, `${id}: Partial needs required packages`);
    if (entry.state === "ready") {
      for (const workId of entry.required) {
        assert.equal(records.work.get(workId), true, `${id}: Ready retains unfinished ${workId}`);
      }
    }
  }
}

for (const suffix of ["", "-ko"]) {
  test(`readiness${suffix}: required backlog packages cannot be hidden behind Ready`, async () => {
    const { backlog, evidence } = await load(suffix);
    validateBacklog(backlogRecords(backlog), evidence);
  });

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
      const status = singleReadinessBadge(row.children[3], suffix, id);
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
    const { specification, assessment, functions, evidence } = await load(suffix);
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
      for (const state of allowedStates) {
        const count = entry.states.filter((value) => value === state).length;
        if (state === "partial" && count === 0) {
          assert.ok(!summary.includes(`${stateLabel(state, suffix)} 0/${entry.rows.length}`),
            `${group}: zero Partial count must not be displayed`);
        } else if (count || state === "ready") {
          assert.ok(summary.includes(`${stateLabel(state, suffix)} ${count}/${entry.rows.length}`),
            `${group}: wrong ${state} count`);
        }
      }
    }
    for (const state of allowedStates) {
      const count = [...evidence.values()].filter((entry) => entry.state === state).length;
      const expected = `${stateLabel(state, suffix)} ${count}/52`;
      if (count || state === "ready" || state === "partial") {
        assert.ok(specification.includes(expected), `wrong specification overall ${state} count`);
      }
      assert.ok(assessment.includes(expected), `wrong assessment overall ${state} count`);
    }
  });

  test(`readiness${suffix}: zero Partial summary badges are omitted`, async () => {
    const { specification, assessment } = await load(suffix);
    const zeroPartialBadge =
      /<span\b[^>]*data-readiness="partial"[^>]*>\s*Partial\s+0\/\d+\s*<\/span>/u;
    assert.doesNotMatch(specification, zeroPartialBadge);
    assert.doesNotMatch(assessment, zeroPartialBadge);
  });
}

test("English and Korean readiness decisions agree", async () => {
  const english = await load("");
  const korean = await load("-ko");
  const decisions = (evidence) => [...evidence].map(([id, { state, anchor }]) => [id, state, anchor]);
  assert.deepEqual(decisions(english.evidence), decisions(korean.evidence));
  const en = backlogRecords(english.backlog);
  const ko = backlogRecords(korean.backlog);
  assert.deepEqual([...en.work].sort(), [...ko.work].sort(), "work package IDs/completion diverge");
  assert.deepEqual([...en.inventory].sort(), [...ko.inventory].sort(), "required packages/states diverge");
});

const minimalBacklog = `
| Function | Transition | Existing | Remaining | Required packages |
|----------|------------|----------|-----------|-------------------|
| F10.1 | Ready -> Partial | Local | Receipt | K01 |

- [ ] **K01, lifecycle receipt:** Retain the exact receipt.
`;

for (const [name, mutate, error] of [
  ["duplicate work ID", (s) => `${s}\n- [ ] **K01, repeated:** More work.`, /duplicate work package/u],
  ["missing work ID", (s) => s.replace("K01, lifecycle", "Lifecycle"), /canonical ID/u],
  ["unknown work ID", (s) => s.replace("| K01 |", "| K99 |"), /unknown work package/u],
  ["duplicate required ID", (s) => s.replace("| K01 |", "| K01, K01 |"), /duplicate required package/u],
  ["range hides IDs", (s) => s.replace("| K01 |", "| K01-K03 |"), /exact comma-separated IDs/u],
  ["malformed transition", (s) => s.replace("Ready -> Partial", "Ready"), /malformed readiness transition/u],
  ["unknown state", (s) => s.replace("Ready -> Partial", "Ready -> Done"), /unknown state/u],
  ["duplicate function", (s) => s.replace("\n\n- [ ]", "\n| F10.1 | Ready -> Partial | Local | Receipt | K01 |\n\n- [ ]"), /duplicate inventory/u],
  ["missing required column", (s) => s.replace("| Receipt | K01 |", "| Receipt |"), /missing required-package/u],
]) {
  test(`backlog parser rejects ${name}`, () => {
    assert.throws(() => backlogRecords(mutate(minimalBacklog)), error);
  });
}

test("Ready with unfinished mandatory work is rejected even when all three documents agree", async () => {
  const { backlog, evidence } = await load("");
  const records = backlogRecords(backlog);
  const id = "F10.1";
  records.inventory.set(id, { ...records.inventory.get(id), state: "ready" });
  evidence.set(id, { ...evidence.get(id), state: "ready" });
  assert.throws(() => validateBacklog(records, evidence), /Ready retains unfinished K01/u);
});

test("completed required packages allow Ready without discarding the inventory", async () => {
  const { backlog, evidence } = await load("");
  const records = backlogRecords(backlog);
  const id = "F10.1";
  const entry = records.inventory.get(id);
  entry.state = "ready";
  evidence.set(id, { ...evidence.get(id), state: "ready" });
  for (const workId of entry.required) records.work.set(workId, true);
  validateBacklog(records, evidence);
});

test("missing, extra, or mismatched inventory rows cannot pass with valid counts elsewhere", async () => {
  const { backlog, evidence } = await load("");
  for (const [mutation, error] of [
    ["missing", /incomplete F10-F15 inventory/u],
    ["extra", /incomplete F10-F15 inventory/u],
    ["mismatch", /backlog\/assessment state mismatch/u],
    ["untracked", /Partial needs required packages/u],
  ]) {
    const records = backlogRecords(backlog);
    if (mutation === "missing") records.inventory.delete("F10.1");
    if (mutation === "extra") records.inventory.set("F16.1", { state: "partial", required: ["K01"] });
    if (mutation === "mismatch") records.inventory.get("F10.1").state = "planned";
    if (mutation === "untracked") records.inventory.get("F10.1").required = [];
    assert.throws(() => validateBacklog(records, evidence), error, mutation);
  }
});

test("renaming a function in both assessment and backlog cannot preserve a false complete inventory", async () => {
  const { backlog, evidence } = await load("");
  const records = backlogRecords(backlog);
  records.inventory.set("F10.5", records.inventory.get("F10.1"));
  records.inventory.delete("F10.1");
  evidence.set("F10.5", evidence.get("F10.1"));
  evidence.delete("F10.1");
  assert.throws(() => validateBacklog(records, evidence), /function IDs changed/u);
});

function badgeCell(html) {
  return rows(parser.parse(`| State |\n|-------|\n| ${html} |`))[0].children[0];
}

test("missing or duplicate badges cannot hide contradictory visual states", () => {
  const ready = '<span class="fdai-readiness-badge" data-readiness="ready">Ready</span>';
  const partial = '<span class="fdai-readiness-badge" data-readiness="partial">Partial</span>';
  for (const html of ["Ready", `${ready}${partial}`]) {
    assert.throws(() => singleReadinessBadge(badgeCell(html), "", "F10.1"), /exactly one/u);
  }
});

test("badge display labels must match machine states", () => {
  const html = '<span class="fdai-readiness-badge" data-readiness="partial">Ready</span>';
  assert.throws(() => singleReadinessBadge(badgeCell(html), "", "F10.1"), /label contradicts state/u);
});

test("unknown states are refused and valid localized Not assessed labels remain accepted", () => {
  const html = '<span class="fdai-readiness-badge" data-readiness="done">Done</span>';
  assert.throws(() => singleReadinessBadge(badgeCell(html), "", "F10.1"), /unknown state/u);
  for (const suffix of ["", "-ko"]) {
    const label = stateLabel("not-assessed", suffix);
    const cell = badgeCell(`<span class="fdai-readiness-badge" data-readiness="not-assessed">${label}</span>`);
    assert.equal(singleReadinessBadge(cell, suffix, "F10.1").state, "not-assessed");
  }
});
