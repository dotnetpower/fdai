import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const consoleStyles = readFileSync(fileURLToPath(new URL("./styles.css", import.meta.url)), "utf8");
const mockStyles = readFileSync(
  fileURLToPath(new URL("../../mocks/ui/assets/calm-slate.css", import.meta.url)),
  "utf8",
);
const sharedTokens = readFileSync(
  fileURLToPath(new URL("../../ui/calm-slate-tokens.css", import.meta.url)),
  "utf8",
);
const sharedPrimitives = readFileSync(
  fileURLToPath(new URL("../../ui/calm-slate-primitives.css", import.meta.url)),
  "utf8",
);
const componentGallery = readFileSync(
  fileURLToPath(new URL("../../mocks/ui/components.html", import.meta.url)),
  "utf8",
);
// The Command deck mock is one page (deck.html) whose engine and form data render every response
// form; together they are the mock side of the Console parity checks below.
const deckPage = readFileSync(fileURLToPath(new URL("../../mocks/ui/deck.html", import.meta.url)), "utf8");
const deckEngine = readFileSync(
  fileURLToPath(new URL("../../mocks/ui/assets/deck-sources.js", import.meta.url)),
  "utf8",
);
const deckForms = readFileSync(
  fileURLToPath(new URL("../../mocks/ui/assets/deck-forms.js", import.meta.url)),
  "utf8",
);
const deckStudyStyles = readFileSync(
  fileURLToPath(new URL("../../mocks/ui/assets/deck-study.css", import.meta.url)),
  "utf8",
);
const deckMock = [deckPage, deckEngine, deckForms].join("\n");
const conversationLayer = readFileSync(
  fileURLToPath(new URL("../../ui/calm-slate-deck-conversation.css", import.meta.url)),
  "utf8",
);
const sourceStreamingMock = deckPage;
const productionDeck = [
  "./deck/command-deck-view.tsx",
  "./deck/command-deck-presenters.tsx",
  "./deck/grounded-reply.tsx",
  "./deck/retrieval-trace.tsx",
  "./deck/investigation-timeline.tsx",
  "./deck/conversation-trajectory-view.tsx",
].map((path) => readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8")).join("\n");

describe("shared Calm Slate tokens", () => {
  test("keeps foundation tokens in one stylesheet consumed by Console and mocks", () => {
    expect(consoleStyles).toContain('@import url("../../ui/calm-slate-tokens.css")');
    expect(mockStyles).toMatch(/@import url\("\.\.\/\.\.\/\.\.\/ui\/calm-slate-tokens\.css\?v=semantic-type-v\d+"\)/);
    expect(consoleStyles).toContain('@import url("../../ui/calm-slate-primitives.css")');
    expect(mockStyles).toMatch(/@import url\("\.\.\/\.\.\/\.\.\/ui\/calm-slate-primitives\.css\?v=semantic-type-v\d+"\)/);
    expect(sharedTokens).toContain("--cs-radius: 8px");
    expect(sharedTokens).toContain("--cs-type-page-title-size: 24px");
    expect(sharedTokens).toContain("--cs-type-page-subtitle-size: 13px");
    expect(sharedTokens).toContain("--cs-type-lead-size: 16px");
    expect(sharedTokens).toContain("--cs-type-section-title-size: 18px");
    expect(sharedTokens).toContain("--cs-type-panel-title-size: 15px");
    expect(sharedTokens).toContain("--cs-type-body-size: 14px");
    expect(sharedTokens).toContain("--cs-type-compact-size: 13px");
    expect(sharedTokens).toContain("--cs-type-label-size: 12px");
    expect(sharedTokens).toContain("--cs-type-caption-size: 11px");
    expect(sharedTokens).toContain("--cs-font-size: var(--cs-type-body-size)");
    expect(consoleStyles).toContain("--font-sans: var(--cs-font)");
    expect(mockStyles).toContain("font-size: var(--cs-font-size)");
    expect(mockStyles).not.toContain("--cs-radius: 14px");
    expect(mockStyles).not.toContain("--cs-font:");
    expect(sharedPrimitives).toContain(".is-content-updated::after");
    expect(sharedPrimitives).toContain("animation: calm-slate-content-update 1.35s");
    expect(sharedPrimitives).toContain(".cs-type-page-title");
    expect(sharedPrimitives).toContain(".cs-type-body");
    expect(sharedPrimitives).toContain(".cs-type-caption");
    expect(sharedPrimitives).toContain(".cs-grounding-panel");
    expect(sharedPrimitives).toContain(".cs-grounding-stage");
    expect(sharedPrimitives).toContain(".cs-run-record");
    expect(sharedPrimitives).toContain(".cs-run-phase-strip");
    expect(deckEngine).toContain('h("section", { class: "cs-grounding-panel", "aria-label": "Preparing answer" }');
    expect(deckEngine).toContain('h("li", { class: "cs-grounding-stage", "data-step": String(number) }');
    expect(deckEngine).toContain('h("details", { class: "cs-run-record", "data-run-record": record.turnId }');
    expect(deckEngine).toContain('class: "cs-run-phase-strip"');
    expect(consoleStyles).toContain("font-size: var(--cs-type-page-title-size)");
    expect(mockStyles).toContain("font-size: var(--cs-type-page-title-size)");
  });

  test("renders every semantic typography role in the component gallery", () => {
    expect(componentGallery).toContain('id="typography"');
    expect(componentGallery).toContain("Typography &amp; content hierarchy");
    for (const role of [
      "page-title",
      "page-subtitle",
      "lead",
      "section-title",
      "panel-title",
      "body",
      "compact",
      "label",
      "caption",
    ]) {
      expect(componentGallery).toContain(`cs-type-${role}`);
    }
  });

  test("accounts for every production Command Deck visual role in the unified mock", () => {
    expect(deckPage).toMatch(/assets\/calm-slate\.css\?v=[^"]+/);
    const sharedDeckRoles = [
      "cs-deck-surface",
      "cs-deck-turn",
      "cs-deck-user-turn",
      "cs-deck-user-bubble",
      "cs-deck-agent-turn",
      "cs-deck-turn-head",
      "cs-deck-agent-name",
      "cs-deck-agent-icon",
      "cs-deck-agent-source",
      "cs-deck-answer",
      "cs-deck-turn-foot",
      "cs-deck-turn-time",
      "cs-deck-action-row",
      "cs-deck-tool",
      "cs-deck-tool-icon",
      "cs-work-summary",
      "cs-work-summary-mark",
      "cs-work-summary-copy",
      "cs-work-summary-title",
      "cs-work-summary-meta",
      "cs-work-summary-safety",
      "cs-work-summary-badge",
      "cs-grounding-panel",
      "cs-grounding-head",
      "cs-grounding-stage",
      "cs-grounding-source-window",
      "cs-grounding-source",
      "cs-run-record",
      "cs-run-record-summary",
      "cs-run-record-title",
      "cs-run-record-glyph",
      "cs-run-record-title-copy",
      "cs-run-record-kicker",
      "cs-run-record-heading",
      "cs-run-record-stats",
      "cs-run-record-duration",
      "cs-run-record-chevron",
      "cs-run-record-body",
      "cs-run-phase-strip",
      "cs-run-phase",
      "cs-run-phase-mark",
      "cs-deck-composer-shell",
      "cs-deck-composer-grid",
      "cs-deck-composer-input",
      "cs-deck-composer-send",
    ];
    // The conversation layer replaces these legacy production roles; the Console adopts the
    // replacement when it imports the layer, so the mock renders only the replacement.
    const supersededBy: Record<string, string> = {
      "cs-deck-agent-source": "cs-grounding-authority",
      "cs-deck-turn-foot": "cs-deck-action-row",
      "cs-work-summary": "cs-deck-investigation-head",
      "cs-work-summary-mark": "cs-deck-wave-mark",
      "cs-work-summary-copy": "cs-deck-investigation-title",
      "cs-work-summary-title": "cs-deck-investigation-title",
      "cs-work-summary-meta": "cs-deck-investigation-status",
      "cs-work-summary-safety": "cs-grounding-authority",
      "cs-work-summary-badge": "cs-deck-answer-state",
      "cs-grounding-source-window": "cs-grounding-source-list",
      "cs-run-record-title-copy": "cs-run-record-heading",
      "cs-run-record-kicker": "cs-run-record-heading",
    };
    expect(sharedDeckRoles.length).toBeGreaterThanOrEqual(40);
    let direct = 0;
    for (const role of sharedDeckRoles) {
      expect(sharedPrimitives, `${role} missing from shared primitives`).toContain(`.${role}`);
      const replacement = supersededBy[role];
      // Console adoption swaps a superseded role for its replacement, so production renders one.
      expect(
        productionDeck.includes(role) || (replacement !== undefined && productionDeck.includes(replacement)),
        `${role} missing from production Command Deck`,
      ).toBe(true);
      if (replacement) {
        expect(deckMock, `${role} is superseded but still rendered by the mock`).not.toContain(`"${role}`);
        expect(conversationLayer + sharedPrimitives, `${replacement} has no shared style`).toContain(`.${replacement}`);
        expect(deckMock, `${replacement} missing from the Command deck mock`).toContain(replacement);
      } else {
        expect(deckMock, `${role} missing from the Command deck mock`).toContain(role);
        direct += 1;
      }
    }
    expect(direct).toBeGreaterThanOrEqual(30);
  });

  test("bounds mock source exposure and keeps the mobile composer on one row", () => {
    expect(deckEngine).toContain("var slots = Math.max(1, Math.min(3, emitted));");
    expect(deckEngine).toContain("if (list.children.length <= 3) return;");
    expect(sharedPrimitives).toMatch(/\.cs-deck-composer-grid \{[^}]*grid-template-columns: auto minmax\(0, 1fr\) auto;/);
    expect(conversationLayer).not.toMatch(/cs-deck-composer-grid[^{]*\{[^}]*grid-template-columns/);
    expect(deckPage).not.toContain("ex-composer-scope");
  });

  test("provides a same-state unverified specimen for production comparison", () => {
    expect(deckForms).toContain('answerState: "unverified"');
    expect(deckForms).toContain('label: "Not verified", detail: "Causal claim unsupported"');
    expect(deckForms).toContain("verification rejected the causal claim twice, so this answer shows only verified facts.");
    expect(deckEngine).toContain('if (spec.answerState === "unverified") return "unverified";');
    expect(deckEngine).toContain('unverified: "Unverified"');
    expect(deckEngine).toContain('"data-tip": "Review answer quality"');
    expect(deckEngine).toContain('"Model trace off"');
    expect(deckEngine).toContain('"verification " + STATE_LABEL[trajectory.verification].toLowerCase()');
  });

  test("provides a production-shaped workspace shell around the same answer DOM", () => {
    expect(deckPage).toContain('id="ds-workspace"');
    expect(deckPage).toContain('class="ds-workspace cs-deck-surface cs-deck-workspace-shell cs-deck-conversation"');
    expect(deckPage).toContain('class="ds-header cs-deck-workspace-header"');
    expect(deckPage).toContain('class="cs-deck-workspace-body ds-body-grid"');
    expect(deckPage).toContain('class="cs-deck-conversation-panel ds-panel ds-conversations"');
    expect(deckPage).toContain('class="cs-deck-conversation-scrim"');
    expect(deckPage).toContain('class="cs-deck-digest-panel ds-panel ds-digest"');
    expect(deckPage).toContain('class="cs-deck-source-readiness-slot"');
    expect(deckPage).toContain('aria-label="Search this conversation"');
    expect(deckPage).toContain('id="ds-search-count" aria-live="polite"');
    expect(deckPage).toContain('aria-label="Previous match"');
    expect(deckPage).toContain('aria-label="Next match"');
    expect(deckPage).toContain('aria-label="Filter conversations"');
    expect(deckPage).toContain('aria-controls="ds-conversations"');
    expect(deckPage).toContain('aria-controls="ds-digest"');
    expect(deckPage).toContain('aria-label="New conversation"');
    expect(deckPage).toContain('aria-label="Close command deck"');
    expect(deckStudyStyles).toContain("../../../console/public/agent-icons/bragi.svg");
    expect(deckEngine).toContain('bodyGrid.classList.toggle("has-conversations", open);');
    expect(deckEngine).toContain('bodyGrid.classList.toggle("has-digest", open);');
    expect(deckEngine).toContain('window.matchMedia("(max-width: 1100px)")');
    expect(sharedPrimitives).toContain("@media (max-width: 1100px)");
    expect(deckEngine).toContain('event.key !== "Escape"');
    expect(deckEngine).toContain("searchInput.select();");
    expect(deckEngine).toContain('h("nav", { class: "cs-deck-readiness"');
    expect(deckEngine).toContain('h("div", { class: "cs-deck-readiness is-loading", role: "status", "aria-busy": "true" }');
    expect(sharedPrimitives).toContain("--cs-deck-conversation-width: 240px");
    expect(sharedPrimitives).toContain("--cs-deck-digest-width: 280px");
  });

  test("keeps the conversation layer additive outside the deck root", () => {
    const withoutComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, "");
    const topLevelSelectors = (prelude: string) => {
      const selectors: string[] = [];
      let depth = 0;
      let current = "";
      for (const character of prelude) {
        if (character === "(") depth += 1;
        if (character === ")") depth -= 1;
        if (character === "," && depth === 0) {
          selectors.push(current.trim());
          current = "";
        } else {
          current += character;
        }
      }
      return [...selectors, current.trim()].filter(Boolean);
    };
    const primitiveRoles = new Set(
      [...withoutComments(sharedPrimitives).matchAll(/\.(cs-[a-z0-9-]+)/g)].map((match) => match[1] ?? ""),
    );
    const declarations = withoutComments(conversationLayer);
    const selectors = [...declarations.matchAll(/([^{}]+)\{/g)]
      .map((match) => (match[1] ?? "").trim())
      .filter((prelude) => !prelude.startsWith("@") && !/^(?:from|to|\d+%)$/.test(prelude))
      .flatMap(topLevelSelectors);
    expect(selectors.length).toBeGreaterThan(100);
    for (const selector of selectors) {
      const reusesPrimitive = [...selector.matchAll(/\.(cs-[a-z0-9-]+)/g)]
        .some((match) => primitiveRoles.has(match[1] ?? ""));
      if (reusesPrimitive) {
        expect(selector.startsWith(".cs-deck-conversation "), selector).toBe(true);
      }
    }
    expect(declarations).not.toContain("!important");
    expect(declarations).not.toMatch(/#[0-9a-f]{3,8}\b/i);
    expect(declarations).toContain("container-name: deck-transcript;");
    expect(conversationLayer).toContain("Adoption is a replacement migration, not an override");
    expect(conversationLayer).toContain("so importing this file changes no other surface");
    expect(sourceStreamingMock).toContain("../../ui/calm-slate-deck-conversation.css?v=");
    expect(sourceStreamingMock).toContain("cs-deck-surface cs-deck-workspace-shell cs-deck-conversation");
    expect(sourceStreamingMock).not.toMatch(/\bgs-[a-z]/);
  });
});
