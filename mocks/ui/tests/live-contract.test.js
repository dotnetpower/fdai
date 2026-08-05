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
  assert.match(stylesheet, /\.cs-swarm \{[^}]*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\)/);
});

test("live operational typography remains legible", () => {
  assert.match(stylesheet, /operational text and labels stay at 12px or larger/);
  assert.match(stylesheet, /\.cs-live-health span \{[^}]*font-size: 12px/);
  assert.match(stylesheet, /\.cs-tile-title \{[^}]*font-size: 13px/);
  assert.match(stylesheet, /\.cs-tile-mode \{[^}]*font-size: 11px/);
  assert.match(stylesheet, /\.cs-tier-row \{[^}]*grid-template-columns: 112px minmax\(60px, 1fr\) 36px/);
  assert.match(stylesheet, /\.cs-tier-axis \{[^}]*margin-left: 118px; margin-right: 42px/);
});

test("live badges explain authority and mode in flow and queue", () => {
  ["A0", "A1", "A2", "A3-H", "A4"].forEach((authority) => {
    assert.match(script, new RegExp(`(?:${authority}|"${authority}"):\\s*"`));
  });
  ["pending", "shadow", "enforce", "gated"].forEach((mode) => {
    assert.match(script, new RegExp(`${mode}:\\s*"`));
  });
  assert.match(script, /data-live-term-tip/);
  assert.match(script, /queueBody\.contains\(document\.activeElement\)/);
  assert.match(script, /document\.addEventListener\("focusin"/);
  assert.match(html, /<th>Tier \/ mode<\/th><th>Why<\/th>/);
  assert.doesNotMatch(html, /Priority basis/);
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
