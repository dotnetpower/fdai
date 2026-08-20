import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const siteRoot = new URL("../", import.meta.url);

test("landing pages and shared components publish all seven safeguards", async () => {
  const sources = await Promise.all(
    [
      "src/content/docs/index.mdx",
      "src/content/docs/ko/index.mdx",
      "src/components/ControlLoopSteps.astro",
      "src/components/ActionOntologyExplorer.astro",
    ].map((path) => readFile(new URL(path, siteRoot), "utf8")),
  );
  const combined = sources.join("\n");

  for (const safeguard of [
    "stop condition",
    "rollback",
    "impact-scope limit",
    "dry-run",
    "logical-target lock",
    "idempotency key",
    "two-phase audit",
  ]) {
    assert.match(combined, new RegExp(safeguard));
  }
  assert.doesNotMatch(combined, /four invariants|all four|네 가지|네 개/);
  assert.match(combined, /Missing any one blocks execution/);
  assert.match(combined, /하나라도 빠지면 실행이 차단/);
});
