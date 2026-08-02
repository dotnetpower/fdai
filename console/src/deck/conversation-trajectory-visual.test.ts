import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");

describe("observed trajectory typography", () => {
  test("keeps primary detail text readable and subordinate to the transcript", () => {
    expect(styles).toContain(".deck-transcript {\n  overflow-y: auto;\n  padding: 0;\n  font-size: 15px;");
    expect(styles).toMatch(
      /\.deck-transcript-inner\s*\{[^}]*width:\s*min\(100%, 900px\);[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*gap:\s*12px;/,
    );
    expect(styles).toContain("--deck-font-heading: 13px;");
    expect(styles).toContain("--deck-font-body: 12px;");
    expect(styles).toContain("--deck-font-small: 11px;");
    expect(styles).toContain("--deck-font-label: 11px;");
  });
});
