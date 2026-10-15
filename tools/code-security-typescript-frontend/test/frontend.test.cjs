"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const test = require("node:test");

const frontend = path.resolve(__dirname, "..", "frontend.cjs");
const digest = `sha256:${"b".repeat(64)}`;
const revision = "a".repeat(40);
const rule = {
  schema_version: "1.0.0",
  rule_id: "fdai.typescript.sql-injection",
  version: "1.0.0",
  analysis_kind: "graph_flow",
  languages: ["typescript"],
  cwe_ids: [89],
  selectors: [
    { role: "sink", symbol: "query", argument_index: 0 },
    { role: "propagator", symbol: "trim" },
    { role: "sanitizer", symbol: "bind", security_context: "sql-parameter-binding" },
  ],
  vulnerable_cases: ["typescript-sqli-cross-file"],
  safe_cases: ["typescript-sqli-parameterized"],
};

function run(root, files, limits = undefined) {
  const request = {
    root,
    files,
    revision,
    build_context_digest: digest,
    framework_model_digest: digest,
    rule,
    limits,
  };
  return spawnSync(process.execPath, [frontend], {
    input: JSON.stringify(request),
    encoding: "utf8",
    env: { PATH: process.env.PATH || "/usr/bin:/bin" },
  });
}

function fixture() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "fdai-ts-analysis-"));
}

test("cross-file route input reaches SQL sink deterministically", () => {
  const root = fixture();
  fs.writeFileSync(path.join(root, "api.ts"), `
    import { execute } from './db';
    export function search(req: Request) {
      return execute(req.query.q.trim());
    }
    app.get('/search', search);
  `);
  fs.writeFileSync(path.join(root, "db.ts"), `
    export function execute(value: string) {
      return pool.query('SELECT ' + value);
    }
  `);
  const first = run(root, ["api.ts", "db.ts"]);
  const second = run(root, ["api.ts", "db.ts"]);

  assert.equal(first.status, 0, first.stderr);
  assert.equal(second.status, 0, second.stderr);
  assert.deepEqual(JSON.parse(first.stdout), JSON.parse(second.stdout));
  const result = JSON.parse(first.stdout);
  assert.equal(result.paths.length, 1);
  assert.deepEqual(new Set(result.paths[0].steps.map((step) => step.span.path)), new Set([
    "api.ts",
    "db.ts",
  ]));
  assert.deepEqual(result.graph.coverage_limits, []);
});

test("parameterized constant query stays safe", () => {
  const root = fixture();
  fs.writeFileSync(path.join(root, "app.ts"), `
    export function search(req: Request) {
      return pool.query('SELECT WHERE id = ?', [req.query.id]);
    }
    app.get('/search', search);
  `);
  const result = run(root, ["app.ts"]);

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout).paths, []);
});

test("requested source cannot escape the analysis root", () => {
  const parent = fixture();
  const root = path.join(parent, "root");
  fs.mkdirSync(root);
  fs.writeFileSync(path.join(parent, "outside.ts"), "export const secret = 1;");
  const result = run(root, ["../outside.ts"]);

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /escapes the analysis root/);
});

test("graph budget stops oversized analysis before output", () => {
  const root = fixture();
  fs.writeFileSync(path.join(root, "app.ts"), "export function one(value: string) { return value; }");
  const result = run(root, ["app.ts"], { max_graph_nodes: 1 });

  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /graph node limit exceeded/);
});
