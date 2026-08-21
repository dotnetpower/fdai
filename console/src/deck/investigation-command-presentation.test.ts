import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const source = readFileSync(
  fileURLToPath(new URL("./investigation-timeline.tsx", import.meta.url)),
  "utf8",
);

describe("investigation command presentation", () => {
  it("uses the same terminal icon for Azure CLI and Resource Graph commands", () => {
    expect(source).toContain("function TerminalIcon()");
    expect(source).toContain("function providerUsesTerminal(");
    expect(source).toContain('evidence.tool === "Azure CLI"');
    expect(source).toContain('evidence.tool.includes("Azure Resource Graph")');
    expect(source).toContain("terminalActivity ? <TerminalIcon /> : kindLabel");
    expect(source).toContain('evidence.inputKind === "query" || providerUsesTerminal(evidence)');
  });

  it("reveals query commands and bounded output with the activity disclosure", () => {
    expect(source).toContain('class="deck-investigation-command"');
    expect(source).toContain('class="deck-investigation-output-block"');
    expect(source).toContain('class="deck-investigation-output"');
    expect(source).not.toContain("deck-investigation-command-disclosure");
  });
});
