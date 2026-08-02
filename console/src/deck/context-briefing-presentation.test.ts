import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

describe("context briefing presentation", () => {
  it("compacts context turns without changing ordinary rich-answer spacing", () => {
    const presenter = readFileSync(
      fileURLToPath(new URL("./command-deck-presenters.tsx", import.meta.url)),
      "utf8",
    );
    const styles = readFileSync(
      fileURLToPath(new URL("../styles.css", import.meta.url)),
      "utf8",
    );

    expect(presenter).toContain('turn.source === "context" ? " is-context" : ""');
    expect(styles).toContain(".deck-rich { display: flex; flex-direction: column; gap: 7px; }");
    expect(styles).toContain(".deck-turn.is-context .deck-rich { gap: 3px; }");
    expect(styles).toContain(
      ".deck-turn.is-context .deck-rich .deck-turn-line { margin-bottom: 0; }",
    );
  });
});
