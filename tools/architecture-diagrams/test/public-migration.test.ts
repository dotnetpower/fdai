import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import {
  PUBLIC_MIGRATION,
  validatePublicMigration,
} from "../src/migrate/public.js";

const repositoryRoot = path.resolve(import.meta.dirname, "../../..");

test("public migration inventory validates all bilingual diagrams in memory", async () => {
  const plan = await validatePublicMigration(repositoryRoot);

  assert.equal(PUBLIC_MIGRATION.length, 16);
  assert.equal(plan.totalBlocks, 32);
  assert.equal(plan.reusedBlocks, 5);
  assert.equal(plan.specs.length, 27);
  assert.equal(new Set(plan.specs.map((spec) => spec.id)).size, 27);
});
