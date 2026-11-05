import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { supportsSampleData } from "./console-data-mode";
import { registeredPanelRoutes } from "./router";
import { ALL_CONSOLE_ROUTES, SAMPLE_ENABLED_ROUTES } from "../tests/e2e/shared-ui-rubric-probe";

const CONSOLE_SRC = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(CONSOLE_SRC, "../..");

async function collectTsxFiles(dir: string): Promise<string[]> {
  const entries = await readdir(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await collectTsxFiles(full)));
    } else if (entry.isFile() && entry.name.endsWith(".tsx") && !entry.name.endsWith(".test.tsx")) {
      files.push(full);
    }
  }
  return files.sort();
}

function extractOpeningTags(
  source: string,
  regex: RegExp,
): { tag: string; line: number; index: number; attrs: string }[] {
  const results: { tag: string; line: number; index: number; attrs: string }[] = [];
  for (const match of source.matchAll(regex)) {
    const tag = match[1] ?? "button";
    const start = (match.index ?? 0) + match[0].length;
    let pos = start;
    let depth = 0;
    let quote: string | null = null;
    while (pos < source.length) {
      const ch = source[pos]!;
      if (quote) {
        if (ch === quote && source[pos - 1] !== "\\") quote = null;
      } else if (ch === '"' || ch === "'" || ch === "`") {
        quote = ch;
      } else if (ch === "{") {
        depth += 1;
      } else if (ch === "}") {
        depth = Math.max(0, depth - 1);
      } else if (ch === ">" && depth === 0) {
        break;
      }
      pos += 1;
    }
    const attrs = source.slice(start, pos);
    const line = source.slice(0, match.index ?? 0).split("\n").length;
    results.push({ tag, line, index: match.index ?? 0, attrs });
  }
  return results;
}

describe("UI/UX and functional consistency static contracts", () => {
  it("keeps the 63-route UI/UX rubric probe synchronized with registeredPanelRoutes and supportsSampleData", () => {
    const registeredPaths = registeredPanelRoutes()
      .map((route) => route.path)
      .sort();
    expect([...ALL_CONSOLE_ROUTES].sort()).toEqual(registeredPaths);

    const samplePaths = registeredPanelRoutes()
      .filter((route) => supportsSampleData(route.panelId))
      .map((route) => route.path)
      .sort();
    expect([...SAMPLE_ENABLED_ROUTES].sort()).toEqual(samplePaths);
  });

  it("requires programmatic accessible labels on form controls across Console and Lifecycle Hub UI", async () => {
    const files = [
      ...(await collectTsxFiles(CONSOLE_SRC)),
      ...(await collectTsxFiles(path.join(REPO_ROOT, "lifecycle/hub/ui/src"))),
    ];
    const unlabeled: string[] = [];
    for (const file of files) {
      const source = await readFile(file, "utf8");
      const lines = source.split("\n");
      for (const { tag, line, index, attrs } of extractOpeningTags(
        source,
        /<(input|select|textarea)\b/g,
      )) {
        if (lines[line - 1]?.trimStart().startsWith("//")) continue;
        if (
          attrs.includes('type="hidden"') ||
          attrs.includes("type='hidden'") ||
          /\bhidden\b/.test(attrs)
        ) {
          continue;
        }
        const before = source.slice(Math.max(0, index - 800), index);
        const wrappedInLabel =
          (before.includes("<label") &&
            !before.slice(before.lastIndexOf("<label")).includes("</label>")) ||
          (file.endsWith("audit.filters.tsx") && source.includes("<label>"));
        const hasLabelAttr =
          attrs.includes("aria-label=") ||
          attrs.includes("aria-labelledby=") ||
          attrs.includes("id=") ||
          attrs.includes("title=");
        if (!wrappedInLabel && !hasLabelAttr) {
          unlabeled.push(`${path.relative(REPO_ROOT, file)}:${line}:${tag}`);
        }
      }
    }
    expect(unlabeled).toEqual([]);
  });

  it("requires explicit type= on every <button> across Console and Lifecycle Hub UI", async () => {
    const files = [
      ...(await collectTsxFiles(CONSOLE_SRC)),
      ...(await collectTsxFiles(path.join(REPO_ROOT, "lifecycle/hub/ui/src"))),
    ];
    const missingType: string[] = [];
    for (const file of files) {
      const source = await readFile(file, "utf8");
      for (const { line, attrs } of extractOpeningTags(source, /<(button)\b/g)) {
        if (
          !attrs.includes("type=") &&
          !attrs.includes("{...props}") &&
          !attrs.includes("{...buttonProps}") &&
          !attrs.includes("{...rest}")
        ) {
          missingType.push(`${path.relative(REPO_ROOT, file)}:${line}`);
        }
      }
    }
    expect(missingType).toEqual([]);
  });

  it("forbids system-locale Date.toLocaleString() or toLocaleTimeString([]) in Console routes", async () => {
    const files = await collectTsxFiles(path.join(CONSOLE_SRC, "routes"));
    const violations: string[] = [];
    for (const file of files) {
      const source = await readFile(file, "utf8");
      const lines = source.split("\n");
      lines.forEach((line, idx) => {
        if (
          /\bdate\.toLocaleString\(\)/.test(line) ||
          /\.toLocaleTimeString\(\s*\[\s*\]/.test(line)
        ) {
          violations.push(`${path.relative(REPO_ROOT, file)}:${idx + 1}`);
        }
      });
    }
    expect(violations).toEqual([]);
  });
});
