import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import type { PresentationBlock } from "./backend-types";
import { presentationBlockCanCollapse } from "./structured-reply";

const source = readFileSync(
  fileURLToPath(new URL("./structured-reply.tsx", import.meta.url)),
  "utf8",
);
const styles = readFileSync(
  fileURLToPath(new URL("./structured-reply.css", import.meta.url)),
  "utf8",
);
const conversationLayer = readFileSync(
  fileURLToPath(new URL("../../../ui/calm-slate-deck-conversation.css", import.meta.url)),
  "utf8",
);

describe("adaptive structured reply layouts", () => {
  test("keeps limitation blocks visible despite a collapsed presentation hint", () => {
    const block: PresentationBlock = {
      slotId: "limitations", kind: "callout", title: "Evidence limits",
      emphasis: "supporting", collapsed: true, evidenceRefs: ["evidence-1"],
      data: { tone: "warning", lines: ["Current evidence is unavailable."] },
    };
    expect(presentationBlockCanCollapse(block)).toBe(false);
    expect(presentationBlockCanCollapse({ ...block, data: { ...block.data, tone: "neutral" } })).toBe(false);
  });

  test("keeps attention and warning callouts expanded in every slot", () => {
    const block: PresentationBlock = {
      slotId: "risk", kind: "callout", title: "Risk",
      emphasis: "supporting", collapsed: true, evidenceRefs: ["evidence-1"],
      data: { tone: "attention", lines: ["The error rate exceeds its threshold."] },
    };
    expect(presentationBlockCanCollapse(block)).toBe(false);
    expect(presentationBlockCanCollapse({ ...block, data: { ...block.data, tone: "warning" } })).toBe(false);
    expect(presentationBlockCanCollapse({ ...block, data: { ...block.data, tone: "neutral" } })).toBe(true);
  });

  test("preserves explicit collapse hints for ordinary summary blocks", () => {
    const block: PresentationBlock = {
      slotId: "overview", kind: "summary", title: "Summary",
      emphasis: "supporting", collapsed: true, evidenceRefs: ["evidence-1"],
      data: { items: [{ label: "Observed", value: "1", tone: "neutral" }] },
    };
    expect(presentationBlockCanCollapse(block)).toBe(true);
    expect(presentationBlockCanCollapse({ ...block, collapsed: false })).toBe(false);
  });

  test("renders only the server-selected artifact layout", () => {
    expect(source).toContain("data-layout={artifact.layout}");
    expect(source).toContain("<PresentationAssemblyView assembly={artifact.assembly}");
    expect(source).not.toMatch(/includes\(|match\(|test\(/);
  });

  test("shows bounded dynamic assembly metadata on one quiet line", () => {
    expect(source).toContain("{assembly.label}");
    expect(source).toContain("§ {assembly.sectionCount}");
    expect(source).toContain('assembly.digest.slice("sha256:".length');
    expect(source).toContain("assembly.inputKinds.map");
    expect(source).toContain('<p class="deck-presentation-assembly cs-deck-document-assembly">');
    expect(conversationLayer).toMatch(/\.cs-deck-document-assembly code \{[^}]*font: var\(--cs-type-label-size\)/s);
  });

  test("keeps operational briefs inline and Markdown documents as one document card", () => {
    // An operational brief flows with the answer like the mock's incident brief, so it carries no
    // card chrome; a Markdown document is the layer's document card with document sections.
    expect(styles).not.toContain('data-layout="operational_brief"');
    expect(source).toContain('const document = artifact.layout === "markdown_document";');
    expect(source).toContain('class={`deck-presentation${document ? " cs-deck-document" : ""}`}');
    expect(source).toContain('document ? " cs-deck-document-section" : ""');
    expect(source).toContain('document ? "cs-deck-document-heading" : "deck-presentation-block-title"');
    expect(conversationLayer).toMatch(/\.cs-deck-document \{[^}]*border: 1px solid var\(--cs-deck-line-strong\);/s);
    expect(styles).toContain('.deck-presentation[data-layout="markdown_document"] { display: block; }');
  });

  test("reflows structured blocks from the transcript width", () => {
    // The fact grid reflows by its own auto-fill track, and tables stack below 560px.
    expect(conversationLayer).toMatch(
      /\.cs-deck-answer-facts \{[^}]*grid-template-columns: repeat\(auto-fill, minmax\(150px, 1fr\)\);/s,
    );
    expect(styles).toContain("@container deck-transcript (max-width: 560px)");
    expect(styles).toMatch(
      /@container deck-transcript \(max-width: 560px\) \{[\s\S]*\.deck-presentation-table tr \{ display: block; \}|@container deck-transcript \(max-width: 560px\) \{\s*\.deck-presentation-table,/,
    );
  });
});
