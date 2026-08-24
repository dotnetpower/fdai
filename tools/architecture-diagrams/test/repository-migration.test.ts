import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import { checkRepositoryMigration } from "../src/migrate/repository.js";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");

test("repository migration inventory validates every task-owned Mermaid block", async () => {
  const plan = await checkRepositoryMigration(repositoryRoot);

  assert.equal(plan.totalBlocks, 80);
  assert.equal(plan.deferredBlocks, 0);
  assert.equal(plan.specs.length, 80);
  assert.equal(new Set(plan.specs.map((spec) => spec.id)).size, 80);
});
