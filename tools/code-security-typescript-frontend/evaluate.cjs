"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { analyze } = require("./frontend.cjs");

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
    { role: "source", symbol: "Request.query" },
    { role: "source", symbol: "Request.params" },
    { role: "sink", symbol: "query", argument_index: 0 },
    { role: "propagator", symbol: "trim" },
    { role: "sanitizer", symbol: "bind", security_context: "sql-parameter-binding" },
  ],
  vulnerable_cases: ["typescript-sqli-cross-file", "typescript-sqli-alias"],
  safe_cases: ["typescript-sqli-parameterized", "typescript-sqli-constant"],
};

function metrics(outcomes) {
  let tp = 0; let fp = 0; let fn = 0; let tn = 0; let unsupported = 0;
  for (const outcome of outcomes) {
    if (!outcome.supported) unsupported += 1;
    else if (outcome.expected && outcome.detected) tp += 1;
    else if (outcome.detected) fp += 1;
    else if (outcome.expected) fn += 1;
    else tn += 1;
  }
  const precision = tp + fp ? tp / (tp + fp) : 0;
  const recall = tp + fn ? tp / (tp + fn) : 0;
  return { true_positive: tp, false_positive: fp, false_negative: fn, true_negative: tn,
    unsupported, precision, recall, f1: precision + recall ? 2 * precision * recall / (precision + recall) : 0 };
}

function evaluate(corpusPath) {
  const started = process.hrtime.bigint();
  const raw = fs.readFileSync(corpusPath);
  const corpus = JSON.parse(raw);
  const outcomes = { dev: [], holdout: [] };
  for (const item of corpus.cases) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), "fdai-ts-eval-"));
    try {
      for (const [relative, source] of Object.entries(item.files)) {
        const target = path.join(root, relative);
        fs.mkdirSync(path.dirname(target), { recursive: true });
        fs.writeFileSync(target, source);
      }
      const result = analyze({ root, files: Object.keys(item.files), revision,
        build_context_digest: digest, framework_model_digest: digest, rule });
      outcomes[item.split].push({ expected: item.vulnerable, detected: result.paths.length > 0,
        supported: result.graph.coverage_limits.length === 0 });
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  }
  const elapsed = process.hrtime.bigint() - started;
  return {
    schema_version: "1.0.0",
    corpus_id: corpus.corpus_id,
    corpus_version: corpus.version,
    corpus_digest: `sha256:${crypto.createHash("sha256").update(raw).digest("hex")}`,
    rule_id: rule.rule_id,
    rule_version: rule.version,
    dev: metrics(outcomes.dev),
    holdout: metrics(outcomes.holdout),
    resources: {
      duration_ms: Number(elapsed / 1000000n),
      peak_rss_bytes: process.resourceUsage().maxRSS * 1024,
    },
  };
}

module.exports = { evaluate };

if (require.main === module) {
  process.stdout.write(`${JSON.stringify(evaluate(process.argv[2] || path.join(__dirname,
    "evaluation-corpus.json")), null, 2)}\n`);
}
