import path from "node:path";
import process from "node:process";

import {
  checkPublicMigration,
  writePublicMigration,
} from "./migrate/public.js";

const command = process.argv[2] ?? "check";
const repositoryRoot = path.resolve(import.meta.dirname, "../../..");

async function run(): Promise<void> {
  const plan = command === "write"
    ? await writePublicMigration(repositoryRoot)
    : command === "check"
      ? await checkPublicMigration(repositoryRoot)
      : null;
  if (plan == null) throw new Error(`Unknown command '${command}'. Use check or write.`);
  console.log(
    `${command === "write" ? "Migrated" : "Validated"} ${plan.totalBlocks} public Mermaid diagram pair(s): ${plan.reusedBlocks} reused and ${plan.specs.length} generated.`,
  );
}

run().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exitCode = 1;
});
