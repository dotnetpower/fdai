import { readFile, stat } from "node:fs/promises";
import { join } from "node:path";
import { gzipSync } from "node:zlib";

const RAW_LIMIT = 500_000;
const GZIP_LIMIT = 150_000;
const EXPECTED_LAZY_ROUTES = new Set([
  "src/routes/dashboard.tsx",
  "src/routes/dashboard-v2.tsx",
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
  "src/routes/handover.tsx",
  "src/routes/rule-catalog.tsx",
  "src/routes/workflow-builder.tsx",
  "src/routes/blast-radius.tsx",
  "src/routes/promotion-gates.tsx",
  "src/routes/llm-cost.tsx",
  "src/routes/settings.tsx",
]);

const LOCKED_STENCIL_LAZY_ROUTES = new Set([
  "src/routes/dashboard.tsx",
  "src/routes/audit.tsx",
  "src/routes/settings.tsx",
]);

const PANEL_TO_ROUTE_MODULE = new Map([
  ["dashboard", "src/routes/dashboard.tsx"],
  ["dashboard-v2", "src/routes/dashboard-v2.tsx"],
  ["live", "src/routes/live.tsx"],
  ["gpu", "src/routes/gpu-monitoring.tsx"],
  ["incidents", "src/routes/incidents.tsx"],
  ["agents", "src/routes/agents.tsx"],
  ["pantheon", "src/routes/agents.tsx"],
  ["hil-queue", "src/routes/hil-queue.tsx"],
  ["provision", "src/routes/provision.tsx"],
  ["onboarding", "src/routes/onboarding.tsx"],
  ["detection-readiness", "src/routes/detection-readiness.tsx"],
  ["alert-quality", "src/routes/alert-quality.tsx"],
  ["configuration-baselines", "src/routes/configuration-baselines.tsx"],
  ["processes", "src/routes/processes.tsx"],
  ["workflow-apps", "src/routes/workflow-apps.tsx"],
  ["scheduler-runs", "src/routes/scheduler-runs.tsx"],
  ["background-tasks", "src/routes/background-tasks.tsx"],
  ["automation-blueprints", "src/routes/automation-blueprints.tsx"],
  ["scheduled-continuations", "src/routes/scheduled-continuations.tsx"],
  ["conversation-delivery", "src/routes/conversation-delivery.tsx"],
  ["conversation-assurance", "src/routes/conversation-assurance.tsx"],
  ["conversation-search", "src/routes/conversation-search.tsx"],
  ["reports", "src/routes/reports.tsx"],
  ["agent-activity", "src/routes/agent-activity.tsx"],
  ["audit", "src/routes/audit.tsx"],
  ["browser-evidence", "src/routes/browser-evidence.tsx"],
  ["forecast-learning", "src/routes/forecast-learning.tsx"],
  ["assurance-twin", "src/routes/assurance-twin.tsx"],
  ["code-security", "src/routes/code-security.tsx"],
  ["trace", "src/routes/rule-trace.tsx"],
  ["rca", "src/routes/rca.tsx"],
  ["architecture", "src/routes/architecture.tsx"],
  ["ontology", "src/routes/ontology.tsx"],
  ["handover", "src/routes/handover.tsx"],
  ["rules", "src/routes/rule-catalog.tsx"],
  ["workflow-builder", "src/routes/workflow-builder.tsx"],
  ["capabilities", "src/routes/capabilities.tsx"],
  ["skills", "src/routes/skills.tsx"],
  ["knowledge", "src/routes/knowledge-domain.tsx"],
  ["documents", "src/routes/knowledge-domain.tsx"],
  ["github", "src/routes/knowledge-domain.tsx"],
  ["gitlab", "src/routes/knowledge-domain.tsx"],
  ["azure-devops", "src/routes/knowledge-domain.tsx"],
  ["blast-radius", "src/routes/blast-radius.tsx"],
  ["promotion-gates", "src/routes/promotion-gates.tsx"],
  ["context-selection-comparisons", "src/routes/context-selection-comparisons.tsx"],
  ["scope", "src/routes/scope.tsx"],
  ["llm-cost", "src/routes/llm-cost.tsx"],
  ["cost-governance", "src/routes/cost-governance.tsx"],
  ["aks-commerce", "src/routes/aks-commerce.tsx"],
  ["operating-outcomes", "src/routes/analytics-hubs.tsx"],
  ["control-assurance", "src/routes/analytics-hubs.tsx"],
  ["verticals", "src/routes/analytics-hubs.tsx"],
  ["trust-routing", "src/routes/analytics-hubs.tsx"],
  ["labs", "src/routes/labs.tsx"],
  ["settings-general", "src/routes/settings.tsx"],
  ["settings-environment", "src/routes/environment-deployment.tsx"],
  ["settings-models", "src/routes/settings-models.tsx"],
  ["settings-runtime", "src/routes/settings-runtime.tsx"],
  ["settings-memory", "src/routes/operator-memory.tsx"],
  ["settings-iam", "src/routes/settings-iam.tsx"],
  ["settings-integrations", "src/routes/settings-system.tsx"],
  ["settings-diagnostics", "src/routes/settings-system.tsx"],
]);

const ALL_STENCIL_ROUTE_MODULES = new Set(PANEL_TO_ROUTE_MODULE.values());

const directory = process.argv[2] ?? "dist";
const manifest = JSON.parse(await readFile(join(directory, ".vite/manifest.json"), "utf8"));
const entries = Object.entries(manifest);
const entryPair = entries.find(([, value]) => value.isEntry && value.src === "index.html");
if (!entryPair) throw new Error("bundle check: Vite entry for index.html is missing");

const [, entry] = entryPair;
const actualLazy = new Set(entry.dynamicImports ?? []);
const rawStencilPanels = (process.env.FDAI_STENCIL_ENABLED_PANELS ?? "").trim();

if (!rawStencilPanels) {
  const missing = [...EXPECTED_LAZY_ROUTES].filter((route) => !actualLazy.has(route));
  if (missing.length > 0) {
    throw new Error(`bundle check: routes are no longer lazy: ${missing.join(", ")}`);
  }
} else {
  const enabledPanelSet = new Set([
    "dashboard",
    "audit",
    "settings-general",
    ...rawStencilPanels.split(",").map((item) => item.trim()).filter(Boolean),
  ]);
  const expectedStencilRoutes = new Set(LOCKED_STENCIL_LAZY_ROUTES);
  for (const panelId of enabledPanelSet) {
    const mod = PANEL_TO_ROUTE_MODULE.get(panelId);
    if (mod) expectedStencilRoutes.add(mod);
  }
  const missing = [...expectedStencilRoutes].filter((route) => !actualLazy.has(route));
  if (missing.length > 0) {
    throw new Error(`bundle check (stencil): enabled routes are not lazy: ${missing.join(", ")}`);
  }
  // Verify that disabled routes from ALL_STENCIL_ROUTE_MODULES are physically absent from dynamicImports.
  const unexpectedIncluded = [...ALL_STENCIL_ROUTE_MODULES].filter(
    (route) => !expectedStencilRoutes.has(route) && actualLazy.has(route),
  );
  if (unexpectedIncluded.length > 0) {
    throw new Error(
      `bundle check (stencil): excluded routes remained in bundle: ${unexpectedIncluded.join(", ")}`,
    );
  }
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
  const path = join(directory, file);
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
