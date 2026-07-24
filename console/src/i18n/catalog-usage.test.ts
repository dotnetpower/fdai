import { readdirSync, readFileSync } from "node:fs";
import { extname, join, relative } from "node:path";
import ts from "typescript";
import { describe, expect, test } from "vitest";
import mainCatalog from "./messages.en.json";
import analyticsCatalog from "../routes/i18n/analytics.en.json";
import architectureCatalog from "../routes/i18n/architecture.en.json";
import detectionReadinessCatalog from "../routes/i18n/detection-readiness.en.json";
import evidenceCatalog from "../routes/i18n/evidence.en.json";
import governanceCatalog from "../routes/i18n/governance.en.json";
import llmCostCatalog from "../routes/i18n/llm-cost.en.json";
import liveCatalog from "../routes/i18n/live.messages.en.json";
import ontologyCatalog from "../routes/i18n/ontology.en.json";
import workflowCatalog from "../routes/i18n/workflow.en.json";

const SOURCE_ROOT = join(process.cwd(), "src");
const STATIC_TRANSLATION = /\bt\(\s*["']([^"']+)["']/g;
const HARDCODED_JSX_TEXT = />\s*([A-Z][^<{]*?)\s*</g;
const VISIBLE_ATTRIBUTES = new Set(["aria-label", "placeholder", "title"]);

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    if (!entry.isFile() || ![".ts", ".tsx"].includes(extname(entry.name))) return [];
    if (entry.name.endsWith(".test.ts") || entry.name.endsWith(".test.tsx")) return [];
    return [path];
  });
}

function catalogKeys(value: unknown, prefix = ""): Set<string> {
  const keys = new Set<string>();
  if (typeof value === "string") {
    keys.add(prefix);
    return keys;
  }
  if (value === null || typeof value !== "object" || Array.isArray(value)) return keys;
  for (const [key, child] of Object.entries(value)) {
    const childPrefix = prefix ? `${prefix}.${key}` : key;
    for (const nested of catalogKeys(child, childPrefix)) keys.add(nested);
  }
  return keys;
}

function staticKeys(source: string): string[] {
  return [...source.matchAll(STATIC_TRANSLATION)].map((match) => match[1]!);
}

function hardcodedPresentationStrings(file: string, source: string): string[] {
  const parsed = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const hardcoded: string[] = [];
  const record = (kind: string, value: string): void => {
    const text = value.replace(/\s+/g, " ").trim();
    if (/^[A-Z]/.test(text) && !text.startsWith("GET /")) {
      hardcoded.push(`${file}: ${kind}${text}`);
    }
  };
  const visit = (node: ts.Node): void => {
    if (ts.isJsxText(node)) {
      record("", node.text);
    } else if (
      ts.isJsxAttribute(node) &&
      VISIBLE_ATTRIBUTES.has(node.name.getText(parsed)) &&
      node.initializer &&
      ts.isStringLiteral(node.initializer)
    ) {
      record(`${node.name.getText(parsed)}=`, node.initializer.text);
    } else if (
      ts.isStringLiteral(node) &&
      ts.isJsxExpression(node.parent)
    ) {
      record("", node.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(parsed);
  return hardcoded;
}

describe("console static translation keys", () => {
  test("all literal t() calls resolve in their English source catalog", () => {
    const mainKeys = catalogKeys(mainCatalog);
    const analyticsKeys = catalogKeys({ analytics: analyticsCatalog });
    const architectureKeys = new Set([
      ...catalogKeys(architectureCatalog),
      ...catalogKeys({ architecture: architectureCatalog }),
    ]);
    const evidenceKeys = new Set([
      ...catalogKeys(evidenceCatalog),
      ...catalogKeys({ evidence: evidenceCatalog }),
    ]);
    const detectionReadinessKeys = catalogKeys(detectionReadinessCatalog);
    const governanceKeys = new Set([
      ...catalogKeys(governanceCatalog),
      ...catalogKeys({ governance: governanceCatalog }),
    ]);
    const llmCostKeys = catalogKeys({ llmCost: llmCostCatalog });
    const liveKeys = catalogKeys({ live: liveCatalog });
    const ontologyKeys = new Set([
      ...catalogKeys(ontologyCatalog),
      ...catalogKeys({ ontology: ontologyCatalog }),
    ]);
    const workflowKeys = new Set([
      ...catalogKeys(workflowCatalog),
      ...catalogKeys({ workflow: workflowCatalog }),
    ]);
    const missing: string[] = [];

    for (const file of sourceFiles(SOURCE_ROOT)) {
      const source = readFileSync(file, "utf8");
      const routeKeys = source.includes('from "./i18n/live"')
        ? liveKeys
        : source.includes('from "./i18n/analytics"')
          ? analyticsKeys
          : source.includes("i18n/detection-readiness")
            ? detectionReadinessKeys
          : source.includes("i18n/architecture")
            ? architectureKeys
            : source.includes("i18n/evidence")
              ? evidenceKeys
              : source.includes("i18n/governance")
                ? governanceKeys
            : source.includes("i18n/ontology")
              ? ontologyKeys
              : source.includes("i18n/workflow")
                ? workflowKeys
          : source.includes('from "./i18n/llm-cost"')
            ? llmCostKeys
            : new Set<string>();
      const expected = new Set([...mainKeys, ...routeKeys]);
      for (const key of staticKeys(source)) {
        if (!expected.has(key)) missing.push(`${relative(SOURCE_ROOT, file)}: ${key}`);
      }
    }

    expect(missing).toEqual([]);
  });

  test("account-scoped General Settings has no hardcoded English JSX", () => {
    const source = readFileSync(join(SOURCE_ROOT, "routes/settings.tsx"), "utf8");
    const accountSections = source.slice(source.indexOf('aria-labelledby="settings-user-context"'));
    const hardcoded = [...accountSections.matchAll(HARDCODED_JSX_TEXT)]
      .map((match) => match[1]!.trim())
      .filter(Boolean);
    expect(hardcoded).toEqual([]);
  });

  test("agent workspace has no hardcoded English presentation strings", () => {
    const files = [
      "components/agent-workspace-nav.tsx",
      "routes/agents.tsx",
      "routes/agents.constellation.tsx",
      "routes/agents.detail.tsx",
      "routes/agents.roster.tsx",
    ];
    const hardcoded: string[] = [];

    for (const file of files) {
      const source = readFileSync(join(SOURCE_ROOT, file), "utf8");
      hardcoded.push(...hardcodedPresentationStrings(file, source));
    }

    expect(hardcoded).toEqual([]);
  });
});
