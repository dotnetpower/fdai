import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const MOCK_ROOT = fileURLToPath(new URL("../../../mocks/ui/", import.meta.url));

function mockSources(): readonly { readonly file: string; readonly source: string }[] {
  return readdirSync(MOCK_ROOT, { recursive: true, withFileTypes: true })
    .filter((entry) => entry.isFile() && (
      entry.name.endsWith(".html") || entry.name.endsWith(".css") || entry.name.endsWith(".md")
    ))
    .map((entry) => {
      const relative = `${entry.parentPath.slice(MOCK_ROOT.length)}/${entry.name}`.replace(/^\//, "");
      return { file: relative, source: readFileSync(`${entry.parentPath}/${entry.name}`, "utf8") };
    });
}

describe("mock console visual boundary", () => {
  test("prohibits top and left edge accents on content containers", () => {
    const forbidden = [
      /cs-kpi-accent/,
      /cs-hcard-rail/,
      /in-severity-rail/,
      /fc-turn-bar/,
      /vx-card-d/,
      /border-top:\s*[2-9]px\s+solid/,
      /border-left:\s*[2-9]px\s+solid/,
      /box-shadow:\s*inset\s+[1-9][0-9]*px\s+0/,
      /\.cs-tile::before/,
    ];
    const violations = mockSources().flatMap(({ file, source }) =>
      forbidden.flatMap((pattern) => pattern.test(source) ? [`${file}: ${pattern.source}`] : []),
    );
    expect(violations).toEqual([]);
  });

  test("cache-busts iframe previews so removed variants do not persist", () => {
    const landing = readFileSync(`${MOCK_ROOT}/index.html`, "utf8");
    expect(landing).toMatch(/const previewUrl = page \+ '\?shell=left-v5&preview=' \+ Date\.now\(\);/);
    expect(landing).toContain("frame.src = previewUrl");
  });
});
