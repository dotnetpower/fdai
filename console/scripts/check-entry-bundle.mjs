import { readFile, stat } from "node:fs/promises";
import { gzipSync } from "node:zlib";

const RAW_LIMIT = 500_000;
const GZIP_LIMIT = 150_000;
const EXPECTED_LAZY_ROUTES = new Set([
  "src/routes/live.tsx",
  "src/routes/agents.tsx",
  "src/routes/hil-queue.tsx",
  "src/routes/provision.tsx",
  "src/routes/processes.tsx",
  "src/routes/agent-activity.tsx",
  "src/routes/audit.tsx",
  "src/routes/rule-trace.tsx",
  "src/routes/architecture.tsx",
  "src/routes/ontology.tsx",
  "src/routes/pantheon.tsx",
  "src/routes/handover.tsx",
  "src/routes/rule-catalog.tsx",
  "src/routes/workflow-builder.tsx",
  "src/routes/blast-radius.tsx",
  "src/routes/promotion-gates.tsx",
  "src/routes/llm-cost.tsx",
  "src/routes/settings.tsx",
]);

const manifest = JSON.parse(await readFile("dist/.vite/manifest.json", "utf8"));
const entries = Object.entries(manifest);
const entryPair = entries.find(([, value]) => value.isEntry && value.src === "index.html");
if (!entryPair) throw new Error("bundle check: Vite entry for index.html is missing");

const [, entry] = entryPair;
const actualLazy = new Set(entry.dynamicImports ?? []);
const missing = [...EXPECTED_LAZY_ROUTES].filter((route) => !actualLazy.has(route));
if (missing.length > 0) {
  throw new Error(`bundle check: routes are no longer lazy: ${missing.join(", ")}`);
}

const initialKeys = new Set();
const visit = (key) => {
  if (initialKeys.has(key)) return;
  const chunk = manifest[key];
  if (!chunk) throw new Error(`bundle check: missing manifest chunk ${key}`);
  initialKeys.add(key);
  for (const imported of chunk.imports ?? []) visit(imported);
};
visit(entryPair[0]);

let rawBytes = 0;
let gzipBytes = 0;
for (const key of initialKeys) {
  const file = manifest[key].file;
  const path = `dist/${file}`;
  const content = await readFile(path);
  rawBytes += (await stat(path)).size;
  gzipBytes += gzipSync(content, { level: 9 }).length;
}

if (rawBytes > RAW_LIMIT || gzipBytes > GZIP_LIMIT) {
  throw new Error(
    `bundle check: initial JS ${rawBytes} raw / ${gzipBytes} gzip exceeds ` +
      `${RAW_LIMIT} raw / ${GZIP_LIMIT} gzip`,
  );
}

console.log(
  `bundle check: OK (${rawBytes} raw, ${gzipBytes} gzip, ${actualLazy.size} lazy imports)`,
);
