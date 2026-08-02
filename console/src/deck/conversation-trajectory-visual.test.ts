import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");

describe("observed trajectory typography", () => {
  test("keeps primary detail text readable and subordinate to the transcript", () => {
    expect(styles).toContain(".deck-transcript {\n  overflow-y: auto;\n  padding: 0;\n  font-size: 15px;");
    expect(styles).toContain(".deck-transcript-inner {\n  width: min(100%, 900px);");
    expect(styles).toContain("display: flex;\n  flex-direction: column;\n  gap: 16px;");
    expect(styles).toContain("--deck-font-heading: 14px;");
    expect(styles).toContain("--deck-font-body: 14px;");
    expect(styles).toContain("--deck-font-small: 12px;");
    expect(styles).toContain("--deck-font-label: 12px;");
  });
});
