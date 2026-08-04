import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const source = readFileSync(
  fileURLToPath(new URL("./conversation-trajectory-view.tsx", import.meta.url)),
  "utf8",
);

describe("observed trajectory typography", () => {
  test("keeps primary detail text readable and subordinate to the transcript", () => {
    expect(styles).toMatch(
      /\.deck-transcript\s*\{[^}]*overflow-y:\s*auto;[^}]*overflow-anchor:\s*none;[^}]*padding:\s*0;[^}]*font-size:\s*16px;/,
    );
    expect(styles).toMatch(
      /\.deck-transcript-inner\s*\{[^}]*width:\s*min\(100%, 900px\);[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*gap:\s*12px;/,
    );
    expect(styles).toContain("--deck-font-heading: 14px;");
    expect(styles).toContain("--deck-font-body: 13px;");
    expect(styles).toContain("--deck-font-small: 12px;");
    expect(styles).toContain("--deck-font-label: 12px;");
    expect(styles).toContain("font-size: 16px;\n  line-height: 1.62;");
  });

  test("keeps the operator prompt visible in the run record summary", () => {
    expect(source).toContain('class="deck-trajectory-question"');
    expect(source).toContain("{trajectory.question.text}");
    expect(styles).toContain(".deck-trajectory-question { grid-column: 1 / -1;");
    expect(styles).toContain("text-overflow: ellipsis; white-space: nowrap;");
  });
});
