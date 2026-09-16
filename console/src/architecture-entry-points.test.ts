import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, test } from "vitest";

const SOURCE_ROOT = join(process.cwd(), "src");
const FORBIDDEN_ACTIONS: ReadonlyArray<readonly [string, RegExp]> = [
  ["Live Architecture action", /\bt\(\s*["']live\.detail\.architecture["']\s*\)/],
  ["Onboarding Architecture action", /\bt\(\s*["']onboardingView\.inspectArchitecture["']\s*\)/],
  ["Rule Architecture action", /\bt\(\s*["']governance\.rules\.detail\.viewArchitecture["']\s*\)/],
  ["Impact Architecture action", /\bt\(\s*["']ontology\.blast\.openArchitecture["']\s*\)/],
  ["Architecture action class", /\b(?:blast-map-open|finding-architecture-link)\b/],
];

function productionTsxFiles(directory: string): readonly string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return productionTsxFiles(path);
    if (!entry.isFile() || !entry.name.endsWith(".tsx") || entry.name.endsWith(".test.tsx")) {
      return [];
    }
    return [path];
  });
}

describe("Architecture action visibility", () => {
  test("keeps dedicated cross-screen Architecture actions out of production UI", () => {
    const violations = productionTsxFiles(SOURCE_ROOT)
      .flatMap((path) => {
        const source = readFileSync(path, "utf8");
        return FORBIDDEN_ACTIONS
          .filter(([, pattern]) => pattern.test(source))
          .map(([name]) => `${relative(SOURCE_ROOT, path)}: ${name}`);
      });

    expect(violations).toEqual([]);
  });
});
