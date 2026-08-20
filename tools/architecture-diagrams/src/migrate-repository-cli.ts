import path from "node:path";
import process from "node:process";

import {
  checkRepositoryMigration,
  writeRepositoryMigration,
} from "./migrate/repository.js";

const command = process.argv[2] ?? "check";
const repositoryRoot = path.resolve(import.meta.dirname, "../../..");

async function run(): Promise<void> {
  const plan = command === "write"
    ? await writeRepositoryMigration(repositoryRoot)
    : command === "check"
      ? await checkRepositoryMigration(repositoryRoot)
      : null;
  if (plan == null) throw new Error(`Unknown command '${command}'. Use check or write.`);
  console.log(
    `${command === "write" ? "Migrated" : "Validated"} ${plan.totalBlocks} repository Mermaid diagram pair(s); ${plan.deferredBlocks} localized block(s) deferred for concurrent edits.`,
  );
}

run().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
