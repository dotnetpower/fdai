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

  it("makes the IQL source independently collapsible from its result", () => {
    expect(source).toContain('class="deck-investigation-disclosure deck-investigation-command-disclosure"');
    expect(source).toContain('<summary>{kindLabel}</summary>');
    expect(source).toContain('open={status === "running"}');
  });
});
