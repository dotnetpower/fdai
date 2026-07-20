import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const source = readFileSync(
  fileURLToPath(new URL("./command-deck-header.tsx", import.meta.url)),
  "utf8",
);

describe("Command Deck header layout", () => {
  test("keeps every header action in an explicit single-row grid slot", () => {
    expect(source).toContain('class="deck-header-new-slot"');
    expect(styles).toContain('grid-template-areas: "title center controls close";');
    expect(styles).toContain('grid-template-areas: "title new controls close";');
    expect(styles).toContain(".deck-header-new-slot {\n  grid-area: new;\n  display: none;");
  });
});
