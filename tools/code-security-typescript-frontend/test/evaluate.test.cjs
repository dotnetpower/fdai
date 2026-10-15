"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { evaluate } = require("../evaluate.cjs");

test("dev and holdout receipts meet the initial split targets", () => {
  const receipt = evaluate(path.join(__dirname, "..", "evaluation-corpus.json"));

  assert.equal(receipt.dev.precision, 1);
  assert.equal(receipt.dev.recall, 1);
  assert.equal(receipt.dev.unsupported, 0);
  assert.equal(receipt.holdout.precision, 1);
  assert.equal(receipt.holdout.recall, 1);
  assert.equal(receipt.holdout.unsupported, 0);
  assert.match(receipt.corpus_digest, /^sha256:[a-f0-9]{64}$/);
  assert.ok(receipt.resources.duration_ms >= 0);
  assert.ok(receipt.resources.peak_rss_bytes > 0);

  const recorded = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "..",
    "rule-catalog", "code-security", "evaluation", "typescript-analysis-1.0.0.json")));
  const { resources: _observedResources, ...stableReceipt } = receipt;
  const { resources: _recordedResources, ...stableRecorded } = recorded;
  assert.deepEqual(stableRecorded, stableReceipt);
});
