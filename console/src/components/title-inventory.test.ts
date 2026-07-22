import { readdirSync, readFileSync } from "node:fs";
import { extname, join, relative } from "node:path";
import ts from "typescript";
import { describe, expect, test } from "vitest";

const SOURCE_ROOT = join(import.meta.dirname, "..");
const VISIBLE_TITLE_COMPONENTS = new Set([
  "DetailSection",
  "EmptyState",
  "OverviewSection",
  "PageHeader",
  "PanelLoading",
  "RecordFacts",
  "RecordList",
  "TypeSelector",
]);

interface TitleAttribute {
  readonly file: string;
  readonly line: number;
  readonly tag: string;
}

function sourceFiles(directory: string): readonly string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return [".ts", ".tsx"].includes(extname(path)) ? [path] : [];
  });
}

function titleAttributes(): readonly TitleAttribute[] {
  return sourceFiles(SOURCE_ROOT).flatMap((file) => {
    const source = ts.createSourceFile(
      file,
      readFileSync(file, "utf8"),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX,
    );
    const attributes: TitleAttribute[] = [];
    const visit = (node: ts.Node): void => {
      if (ts.isJsxAttribute(node) && node.name.getText(source) === "title") {
        const owner = node.parent.parent;
        if (ts.isJsxOpeningElement(owner) || ts.isJsxSelfClosingElement(owner)) {
          attributes.push({
            file: relative(SOURCE_ROOT, file),
            line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
            tag: owner.tagName.getText(source),
          });
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(source);
    return attributes;
  });
}

describe("native title inventory", () => {
  test("uses the shared Tooltip instead of browser-native title bubbles", () => {
    const nativeAttributes = titleAttributes().filter(({ tag }) => /^[a-z]/.test(tag));
    expect(nativeAttributes).toEqual([]);
  });

  test("keeps title props limited to visible-heading component APIs", () => {
    const componentProps = titleAttributes().filter(({ tag }) => /^[A-Z]/.test(tag));
    const unexpected = componentProps.filter(({ tag }) => !VISIBLE_TITLE_COMPONENTS.has(tag));
    expect(unexpected).toEqual([]);
    expect(new Set(componentProps.map(({ tag }) => tag))).toEqual(VISIBLE_TITLE_COMPONENTS);
  });
});
