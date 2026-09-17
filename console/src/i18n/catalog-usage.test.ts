import { readdirSync, readFileSync } from "node:fs";
import { extname, join, relative } from "node:path";
import ts from "typescript";
import { describe, expect, test } from "vitest";
import mainCatalog from "./messages.en.json";
import analyticsCatalog from "../routes/i18n/analytics.en.json";
import approvalsCatalog from "../routes/i18n/approvals.en.json";
import architectureCatalog from "../routes/i18n/architecture.en.json";
import aksCommerceCatalog from "../routes/i18n/aks-commerce.en.json";
import browserEvidenceCatalog from "../routes/i18n/browser-evidence.en.json";
import conversationAssuranceCatalog from "../routes/i18n/conversation-assurance.en.json";
import costGovernanceCatalog from "../routes/i18n/cost-governance.en.json";
import dashboardV2Catalog from "../routes/i18n/dashboard-v2.en.json";
import detectionReadinessCatalog from "../routes/i18n/detection-readiness.en.json";
import evidenceCatalog from "../routes/i18n/evidence.en.json";
import governanceCatalog from "../routes/i18n/governance.en.json";
import llmCostCatalog from "../routes/i18n/llm-cost.en.json";
import liveCatalog from "../routes/i18n/live.messages.en.json";
import ontologyCatalog from "../routes/i18n/ontology.en.json";
import processesCatalog from "../routes/i18n/processes.en.json";
import provisionCatalog from "../routes/i18n/provision.en.json";
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

function translatorImport(source: string): string {
  const parsed = ts.createSourceFile("source.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  for (const statement of parsed.statements) {
    if (!ts.isImportDeclaration(statement) || !ts.isStringLiteral(statement.moduleSpecifier)) continue;
    const bindings = statement.importClause?.namedBindings;
    if (bindings && ts.isNamedImports(bindings) && bindings.elements.some(binding => binding.name.text === "t")) {
      return `from "${statement.moduleSpecifier.text}"`;
    }
  }
  return "";
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
  test("selects the t binding rather than another catalog's formatting helpers", () => {
    expect(translatorImport(`
      import { statusLabel } from "./i18n/workflow";
      import { t } from "./i18n/processes";
    `)).toBe('from "./i18n/processes"');
    expect(translatorImport(`import { t as mainT } from "../i18n";`)).toBe("");
  });

  test("all literal t() calls resolve in their English source catalog", () => {
    const mainKeys = catalogKeys(mainCatalog);
    const analyticsKeys = catalogKeys({ analytics: analyticsCatalog });
    const approvalsKeys = catalogKeys({ approvals: approvalsCatalog });
    const aksCommerceKeys = catalogKeys({ aksCommerce: aksCommerceCatalog });
    const architectureKeys = new Set([
      ...catalogKeys(architectureCatalog),
      ...catalogKeys({ architecture: architectureCatalog }),
    ]);
    const browserEvidenceKeys = catalogKeys({
      browserEvidence: browserEvidenceCatalog,
    });
    const conversationAssuranceKeys = catalogKeys({ assurance: conversationAssuranceCatalog });
    const costGovernanceKeys = catalogKeys({ costGovernance: costGovernanceCatalog });
    const dashboardV2Keys = catalogKeys(dashboardV2Catalog);
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
    const processesKeys = catalogKeys({ processesView: processesCatalog });
    const provisionKeys = catalogKeys({ provision: provisionCatalog });
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
      const catalogImport = translatorImport(source);
      const relativePath = relative(SOURCE_ROOT, file);
      const routeKeys = catalogImport.includes('from "./i18n/approvals"')
        ? approvalsKeys
        : catalogImport.includes('from "./i18n/aks-commerce"')
        ? aksCommerceKeys
        : catalogImport.includes('from "./i18n/browser-evidence"')
        ? browserEvidenceKeys
        : catalogImport.includes('from "./i18n/cost-governance"')
        ? costGovernanceKeys
        : catalogImport.includes('from "./i18n/dashboard-v2"') ||
            file.endsWith("routes/i18n/dashboard-v2.ts")
          ? dashboardV2Keys
        : catalogImport.includes('from "./i18n/live"')
        ? liveKeys
        : catalogImport.includes('from "./i18n/analytics"')
          ? analyticsKeys
          : relativePath === "routes/i18n/dashboard-v2.ts" || catalogImport.includes('from "./i18n/dashboard-v2"')
            ? dashboardV2Keys
          : catalogImport.includes("i18n/detection-readiness")
            ? detectionReadinessKeys
          : catalogImport.includes("i18n/architecture")
            ? architectureKeys
              : catalogImport.includes("i18n/conversation-assurance")
                ? conversationAssuranceKeys
            : catalogImport.includes("i18n/evidence")
              ? evidenceKeys
              : catalogImport.includes("i18n/governance")
                ? governanceKeys
            : catalogImport.includes("i18n/ontology")
              ? ontologyKeys
              : catalogImport.includes("i18n/workflow")
                ? workflowKeys
          : catalogImport.includes('from "./i18n/llm-cost"')
            ? llmCostKeys
          : catalogImport.includes("i18n/processes")
            ? processesKeys
          : catalogImport.includes("i18n/provision")
            ? provisionKeys
            : new Set<string>();
      const expected = new Set([...mainKeys, ...routeKeys]);
      for (const key of staticKeys(source)) {
        if (!expected.has(key)) missing.push(`${relativePath}: ${key}`);
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
      "routes/agent-organization.tsx",
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
