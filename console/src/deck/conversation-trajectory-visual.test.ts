import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const resultStyles = readFileSync(
  fileURLToPath(new URL("./conversation-trajectory-results.css", import.meta.url)),
  "utf8",
);
const source = readFileSync(
  fileURLToPath(new URL("./conversation-trajectory-view.tsx", import.meta.url)),
  "utf8",
);
const reply = readFileSync(
  fileURLToPath(new URL("./grounded-reply.tsx", import.meta.url)),
  "utf8",
);

describe("observed trajectory typography", () => {
  test("keeps primary detail text readable and subordinate to the transcript", () => {
    expect(styles).toMatch(
      /\.deck-transcript\s*\{[^}]*overflow-y:\s*auto;[^}]*overflow-anchor:\s*none;[^}]*padding:\s*0;[^}]*font-size:\s*15px;/,
    );
    expect(styles).toMatch(
      /\.deck-transcript-inner\s*\{[^}]*width:\s*min\(100%, 900px\);[^}]*display:\s*flex;[^}]*flex-direction:\s*column;[^}]*gap:\s*12px;/,
    );
    expect(styles).toContain("--deck-font-heading: 13px;");
    expect(styles).toContain("--deck-font-body: 12px;");
    expect(styles).toContain("--deck-font-small: 11px;");
    expect(styles).toContain("--deck-font-label: 11px;");
    expect(styles).toContain("font-size: 15px;\n  line-height: 1.62;");
  });

  test("hides the operator prompt until the run record is expanded", () => {
    expect(source).toContain("const [open, setOpen] = useState(false);");
    expect(source).toContain('class="deck-trajectory-question"');
    expect(source).toContain("{open ? (");
    expect(source).toContain("{trajectory.question.text}");
    expect(styles).toContain(".deck-trajectory-question { grid-column: 1 / -1;");
    expect(styles).toContain("text-overflow: ellipsis; white-space: nowrap;");
  });

  test("expands read and evidence status directly beside the source", () => {
    expect(source).toContain('class="deck-trajectory-results"');
    expect(reply).toContain('class="deck-trajectory-status-trigger"');
    expect(reply).not.toContain('class="deck-trajectory-flyout"');
    expect(reply).toContain('class="deck-gr-source-status"');
    expect(reply).toContain('class="deck-gr-review-status"');
    expect(resultStyles).toContain("position: absolute;");
    expect(resultStyles).toContain("width: 10px;");
    expect(resultStyles).toContain("margin-left: -2px;");
    expect(resultStyles).toContain("max-width: 220px;");
    expect(resultStyles).not.toContain("@media (max-width: 640px)");
  });
});
