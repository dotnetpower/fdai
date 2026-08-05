const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");

const uiRoot = join(__dirname, "..");
const script = readFileSync(join(uiRoot, "assets", "live.js"), "utf8");
const stylesheet = readFileSync(join(uiRoot, "assets", "calm-slate.css"), "utf8");
const html = readFileSync(join(uiRoot, "live.html"), "utf8");

test("flow preview exposes twelve concurrent work slots", () => {
  assert.match(script, /var FLOW_POOL_SIZE = 12;/);
  assert.match(script, /for \(var slotIndex = 0; slotIndex < FLOW_POOL_SIZE; slotIndex\+\+\) spawn\(t\);\s*renderOperationalState\(t\);/);
  assert.match(stylesheet, /grid-template-columns: repeat\(4, minmax\(0, 1fr\)\); grid-template-rows: repeat\(3, minmax\(0, 1fr\)\)/);
});

test("gated and shadow paths do not observe execution or effect", () => {
  const gatedPath = script.match(
    /if \(ev\.outcome !== "auto" \|\| ev\.mode === "shadow"\) \{\s*(return \[[^;]+\];)\s*\}/,
  );

  assert.ok(gatedPath, "expected an explicit gated and shadow stage path");
  assert.match(gatedPath[1], /"route", "decide", "authorize", "audit"/);
  assert.doesNotMatch(gatedPath[1], /"execute"|"effect"/);
  assert.match(script, /var skipped = pathIndex < 0;/);
  assert.match(script, /var state = skipped \? "Not applicable"/);
});

test("saturated generation records omitted attempts", () => {
  const saturatedBranch = script.match(/if \(!slot\) \{([\s\S]*?)return false;\s*\}/);

  assert.ok(saturatedBranch, "expected an explicit saturated-pool branch");
  assert.match(saturatedBranch[1], /droppedFrames\+\+/);
  assert.match(saturatedBranch[1], /buckets\[buckets\.length - 1\]\.dropped\+\+/);
  assert.match(script, /t\.dropped \+= b\.dropped/);
  assert.doesNotMatch(html, /4\/4 synthetic|no omitted preview frames/);
});

test("live controls use unique element ids", () => {
  const ids = Array.from(html.matchAll(/\sid="([^"]+)"/g), (match) => match[1]);
  const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);

  assert.deepEqual(Array.from(new Set(duplicates)), []);
});
