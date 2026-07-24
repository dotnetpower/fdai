import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const styles = readFileSync(
  fileURLToPath(new URL("../styles.css", import.meta.url)),
  "utf8",
);

function ruleBody(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return styles.match(new RegExp(`${escaped}\\s*\\{(?<body>[\\s\\S]*?)\\}`))
    ?.groups?.body ?? "";
}

describe("Live responsive header", () => {
  it("wraps controls against the available content width", () => {
    expect(ruleBody(".live .page-header")).toContain("flex-wrap: wrap");
    expect(ruleBody(".live .page-header-text")).toContain("flex: 1 1 280px");
    expect(ruleBody(".live .page-header-actions")).toContain("max-width: 100%");
    expect(styles).toMatch(
      /@media \(max-width: 760px\)[\s\S]*?\.live \.page-header-text\s*\{[^}]*flex: 0 1 auto;[^}]*width: 100%;[^}]*\}/,
    );
  });
});
