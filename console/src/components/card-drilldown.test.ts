import { readdirSync, readFileSync } from "node:fs";
import { extname, join, relative } from "node:path";
import ts from "typescript";
import { describe, expect, test } from "vitest";

const SOURCE_ROOT = join(import.meta.dirname, "..");
const STYLES_PATH = join(SOURCE_ROOT, "styles.css");
const STRUCTURAL_CARD_NAMES = new Set([
  "deck-rt-card",
  "login-card",
  "scope-axis-card",
  "scope-builder-card",
  "scope-executor-card",
  "step-card",
]);

interface Finding {
  readonly file: string;
  readonly line: number;
  readonly tag: string;
}

function sourceFiles(directory: string): readonly string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return extname(path) === ".tsx" && !path.endsWith(".test.tsx") ? [path] : [];
  });
}

function classTokens(attribute: ts.JsxAttribute, source: ts.SourceFile): readonly string[] {
  const initializer = attribute.initializer;
  if (initializer === undefined) return [];
  const text = ts.isStringLiteral(initializer)
    ? initializer.text
    : initializer.getText(source);
  return text.match(/[A-Za-z0-9_-]+/g) ?? [];
}

function isCardToken(token: string): boolean {
  if (token.includes("skeleton")) return false;
  return token === "card" || token === "kpi" || token.endsWith("-card") || token.endsWith("-kpi");
}

function jsxTag(node: ts.JsxOpeningLikeElement, source: ts.SourceFile): string {
  return node.tagName.getText(source);
}

function hasAttribute(
  node: ts.JsxOpeningLikeElement,
  source: ts.SourceFile,
  name: string,
  value?: string,
): boolean {
  return node.attributes.properties.some((property) => {
    if (!ts.isJsxAttribute(property) || property.name.getText(source) !== name) return false;
    if (value === undefined) return true;
    const initializer = property.initializer;
    return initializer !== undefined
      && ts.isStringLiteral(initializer)
      && initializer.text === value;
  });
}

function hasDetailDescendant(node: ts.Node, source: ts.SourceFile): boolean {
  let found = false;
  const visit = (child: ts.Node): void => {
    if (found) return;
    if (ts.isJsxOpeningElement(child) || ts.isJsxSelfClosingElement(child)) {
      const tag = jsxTag(child, source);
      if (tag === "a" || (tag === "button" && hasAttribute(child, source, "aria-controls"))) {
        found = true;
        return;
      }
    }
    ts.forEachChild(child, visit);
  };
  ts.forEachChild(node, visit);
  return found;
}

function cardViolations(): readonly Finding[] {
  return sourceFiles(SOURCE_ROOT).flatMap((file) => {
    const source = ts.createSourceFile(
      file,
      readFileSync(file, "utf8"),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    );
    const findings: Finding[] = [];
    const visit = (node: ts.Node): void => {
      if (ts.isJsxAttribute(node) && ["class", "className"].includes(node.name.getText(source))) {
        const tokens = classTokens(node, source);
        if (tokens.some(isCardToken)) {
          const owner = node.parent.parent;
          if (ts.isJsxOpeningElement(owner) || ts.isJsxSelfClosingElement(owner)) {
            const tag = jsxTag(owner, source);
            const semanticButton = hasAttribute(owner, source, "role", "button")
              && hasAttribute(owner, source, "tabIndex");
            const interactive = tag === "a"
              || tag === "button"
              || semanticButton
              || hasDetailDescendant(owner.parent, source);
            if (!interactive) {
              findings.push({
                file: relative(SOURCE_ROOT, file),
                line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
                tag,
              });
            }
          }
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
    return findings;
  });
}

function kpiCardViolations(): readonly Finding[] {
  return sourceFiles(SOURCE_ROOT).flatMap((file) => {
    const source = ts.createSourceFile(
      file,
      readFileSync(file, "utf8"),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    );
    const findings: Finding[] = [];
    const visit = (node: ts.Node): void => {
      if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && jsxTag(node, source) === "KpiCard") {
        const hasHref = node.attributes.properties.some(
          (property) => ts.isJsxAttribute(property) && property.name.getText(source) === "href",
        );
        let parent: ts.Node | undefined = node.parent;
        let wrappedByLink = false;
        while (parent !== undefined && !ts.isSourceFile(parent)) {
          if (ts.isJsxElement(parent) && jsxTag(parent.openingElement, source) === "a") {
            wrappedByLink = true;
            break;
          }
          parent = parent.parent;
        }
        if (!hasHref || wrappedByLink) {
          findings.push({
            file: relative(SOURCE_ROOT, file),
            line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
            tag: wrappedByLink ? "nested KpiCard" : "KpiCard without href",
          });
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
    return findings;
  });
}

function kpiEvidenceStateViolations(): readonly Finding[] {
  return sourceFiles(SOURCE_ROOT).flatMap((file) => {
    const source = ts.createSourceFile(
      file,
      readFileSync(file, "utf8"),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    );
    const findings: Finding[] = [];
    const visit = (node: ts.Node): void => {
      if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && jsxTag(node, source) === "KpiCard") {
        const evidenceState = node.attributes.properties.find(
          (property) => ts.isJsxAttribute(property) && property.name.getText(source) === "evidenceState",
        );
        const value = node.attributes.properties.find(
          (property) => ts.isJsxAttribute(property) && property.name.getText(source) === "value",
        );
        const valueText = value?.getText(source) ?? "";
        const hasEvidenceGap = /unavailable|===\s*null|!==\s*null|kpiEvidenceLabel\(/i.test(valueText);
        if (hasEvidenceGap && evidenceState === undefined) {
          findings.push({
            file: relative(SOURCE_ROOT, file),
            line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
            tag: "KpiCard without evidenceState",
          });
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
    return findings;
  });
}

function forbiddenStructuralNames(): readonly string[] {
  const sourceNames = sourceFiles(SOURCE_ROOT).flatMap((file) => {
    const source = ts.createSourceFile(
      file,
      readFileSync(file, "utf8"),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    );
    const names: string[] = [];
    const visit = (node: ts.Node): void => {
      if (ts.isJsxAttribute(node) && ["class", "className"].includes(node.name.getText(source))) {
        for (const token of classTokens(node, source)) {
          if (STRUCTURAL_CARD_NAMES.has(token)) names.push(`${relative(SOURCE_ROOT, file)}:${token}`);
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
    return names;
  });
  const styles = readFileSync(STYLES_PATH, "utf8");
  const styleNames = [...STRUCTURAL_CARD_NAMES]
    .filter((name) => styles.includes(`.${name}`))
    .map((name) => `styles.css:${name}`);
  return [...sourceNames, ...styleNames];
}

describe("console card drill-down contract", () => {
  test("requires every KpiCard to own its native drill-down link", () => {
    expect(kpiCardViolations()).toEqual([]);
  });

  test("requires nullable KPI values to declare a shared evidence state", () => {
    expect(kpiEvidenceStateViolations()).toEqual([]);
  });

  test("requires raw data cards to expose a link or detail control", () => {
    expect(cardViolations()).toEqual([]);
  });

  test("keeps structural tool surfaces out of card semantics", () => {
    expect(forbiddenStructuralNames()).toEqual([]);
  });

  test("cost-governance card links target a narrower section or cross-surface route", () => {
    const COST_GOV_FILE = join(SOURCE_ROOT, "routes/cost-governance-workspace.tsx");
    const raw = readFileSync(COST_GOV_FILE, "utf8");
    const source = ts.createSourceFile(COST_GOV_FILE, raw, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

    interface CardLink {
      readonly surface: string;
      readonly href: string;
      readonly line: number;
    }

    const SURFACE_FUNCTIONS = new Map<string, string>([
      ["Overview", "overview"],
      ["ResourceEfficiency", "resource-efficiency"],
      ["OptimizationCases", "optimization-cases"],
      ["Outcomes", "outcomes"],
    ]);

    const links: CardLink[] = [];
    const visit = (node: ts.Node, surface: string): void => {
      if (ts.isFunctionDeclaration(node) && node.name) {
        const name = node.name.getText(source);
        if (SURFACE_FUNCTIONS.has(name)) surface = SURFACE_FUNCTIONS.get(name)!;
      }
      if (ts.isJsxAttribute(node) && node.name.getText(source) === "href" && node.initializer) {
        const parent = node.parent.parent;
        if ((ts.isJsxOpeningElement(parent) || ts.isJsxSelfClosingElement(parent)) && jsxTag(parent, source) === "a") {
          let inCard = false;
          let ancestor: ts.Node | undefined = parent.parent;
          while (ancestor && !ts.isSourceFile(ancestor)) {
            if ((ts.isJsxOpeningElement(ancestor) || ts.isJsxSelfClosingElement(ancestor))) {
              const tokens = ancestor.attributes.properties.flatMap((p) =>
                ts.isJsxAttribute(p) && ["class", "className"].includes(p.name.getText(source))
                  ? classTokens(p, source)
                  : [],
              );
              if (tokens.some(isCardToken)) { inCard = true; break; }
            }
            if (ts.isJsxElement(ancestor)) {
              const tokens = ancestor.openingElement.attributes.properties.flatMap((p) =>
                ts.isJsxAttribute(p) && ["class", "className"].includes(p.name.getText(source))
                  ? classTokens(p, source)
                  : [],
              );
              if (tokens.some(isCardToken)) { inCard = true; break; }
            }
            ancestor = ancestor.parent;
          }
          if (inCard) {
            const hrefText = node.initializer.getText(source);
            links.push({
              surface,
              href: hrefText,
              line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
            });
          }
        }
      }
      ts.forEachChild(node, (child) => visit(child, surface));
    };
    visit(source, "");

    const noOps = links.filter(({ surface, href }) => {
      if (href.startsWith('"#') || href.startsWith("'#")) return false;
      return href.includes(`"${surface}"`) || href.includes(`'${surface}'`);
    });

    expect(noOps).toEqual([]);

    const anchors = links
      .map(({ href, line }) => {
        const match = href.match(/^["']#([^"']+)["']$/);
        return match ? { fragment: match[1], line } : null;
      })
      .filter((item): item is { fragment: string; line: number } => item !== null);

    const idValues = new Set<string>();
    const collectIds = (node: ts.Node): void => {
      if (ts.isJsxAttribute(node) && node.name.getText(source) === "id" && node.initializer && ts.isStringLiteral(node.initializer)) {
        idValues.add(node.initializer.text);
      }
      ts.forEachChild(node, collectIds);
    };
    collectIds(source);

    const danglingAnchors = anchors.filter(({ fragment }) => !idValues.has(fragment));
    expect(danglingAnchors).toEqual([]);
  });
});
