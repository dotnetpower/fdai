import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const source = readFileSync(
  fileURLToPath(new URL("./structured-reply.tsx", import.meta.url)),
  "utf8",
);
const styles = readFileSync(
  fileURLToPath(new URL("./structured-reply.css", import.meta.url)),
  "utf8",
);

describe("adaptive structured reply layouts", () => {
  test("renders only the server-selected artifact layout", () => {
    expect(source).toContain("data-layout={artifact.layout}");
    expect(source).toContain("<PresentationAssemblyView assembly={artifact.assembly}");
    expect(source).not.toMatch(/includes\(|match\(|test\(/);
  });

  test("shows bounded dynamic assembly metadata", () => {
    expect(source).toContain("{assembly.label}");
    expect(source).toContain("§ {assembly.sectionCount}");
    expect(source).toContain('assembly.digest.slice("sha256:".length');
    expect(source).toContain("assembly.inputKinds.map");
    expect(styles).toContain(".deck-presentation-assembly");
  });

  test("keeps operational briefs and Markdown documents distinct", () => {
    expect(styles).toContain('.deck-presentation[data-layout="operational_brief"]');
    expect(styles).toContain('grid-template-columns: repeat(2, minmax(0, 1fr));');
    expect(styles).toContain('.deck-presentation[data-layout="markdown_document"]');
    expect(styles).toContain("border-bottom: 1px solid var(--border);");
  });

  test("reflows adaptive layouts to one column in narrow transcript containers", () => {
    expect(styles).toContain("@container deck-transcript (max-width: 560px)");
    expect(styles).toMatch(
      /data-layout="operational_brief"[\s\S]*grid-template-columns: minmax\(0, 1fr\)/,
    );
    expect(styles).toMatch(
      /data-layout="markdown_document"\] \{ padding: 14px; \}/,
    );
  });
});
