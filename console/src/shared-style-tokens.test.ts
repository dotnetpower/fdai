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
const adaptiveMock = readFileSync(
  fileURLToPath(new URL("../../mocks/ui/deck-sources-v2.html", import.meta.url)),
  "utf8",
);
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
    expect(adaptiveMock).toContain("ex-answer-preparing cs-grounding-panel");
    expect(adaptiveMock).toContain("ex-preparation-stage cs-grounding-stage");
    expect(adaptiveMock).toContain("ex-observed cs-run-record");
    expect(adaptiveMock).toContain("ex-observed-rail cs-run-phase-strip");
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

  test("shares at least forty Command Deck visual roles across production and mock", () => {
    expect(adaptiveMock).toContain("../../ui/calm-slate-primitives.css?v=deck-shared-v2");
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
    expect(sharedDeckRoles.length).toBeGreaterThanOrEqual(40);
    for (const role of sharedDeckRoles) {
      expect(sharedPrimitives, `${role} missing from shared primitives`).toContain(`.${role}`);
      expect(productionDeck, `${role} missing from production Command Deck`).toContain(role);
      expect(adaptiveMock, `${role} missing from adaptive mock`).toContain(role);
    }
  });

  test("bounds mock source exposure and keeps the mobile composer on one row", () => {
    expect(adaptiveMock).toContain("while (preparationSourceStrip.children.length > 3)");
    expect(adaptiveMock).toContain("preparationSourceStrip.firstElementChild.remove()");
    expect(adaptiveMock).toMatch(
      /@media \(max-width: 720px\)[\s\S]*\.ex-composer \{ grid-template-columns: auto minmax\(0, 1fr\) auto;/,
    );
    expect(adaptiveMock).not.toContain("ex-composer-scope");
  });

  test("provides a same-state unverified specimen for production comparison", () => {
    expect(adaptiveMock).toContain('id="ex-unverified"');
    expect(adaptiveMock).toContain('workbench.dataset.outcome = "unverified"');
    expect(adaptiveMock).toContain("This request cannot be answered with verified capabilities.");
    expect(adaptiveMock).toContain("Unsupported claim");
    expect(adaptiveMock).toContain("Review answer quality");
    expect(adaptiveMock).toContain("Model trace off / evidence 2/2 /");
    expect(adaptiveMock).toContain("verification Not verified");
    expect(adaptiveMock).toContain('{ name: "Plan", state: "not-observed"');
    expect(adaptiveMock).toContain('{ name: "Collaboration", state: "not-observed"');
    expect(adaptiveMock).toContain('{ name: "Verification", state: "unverified"');
    expect(adaptiveMock).toContain("observed.open = true");
  });

  test("provides a production-shaped workspace shell around the same answer DOM", () => {
    expect(adaptiveMock).toContain('id="ex-workspace"');
    expect(adaptiveMock).toContain('data-shell="specimen"');
    expect(adaptiveMock).toContain('data-conversations="closed" data-digest="closed"');
    expect(adaptiveMock).toContain('class="ex-workspace-body cs-deck-workspace-body"');
    expect(adaptiveMock).toContain('class="ex-conversations cs-deck-conversation-panel"');
    expect(adaptiveMock).toContain('class="ex-workspace-tools cs-deck-workspace-toolbar"');
    expect(adaptiveMock).toContain('class="ex-digest cs-deck-digest-panel"');
    expect(adaptiveMock).toContain('class="ex-source-readiness-slot cs-deck-source-readiness-slot"');
    expect(adaptiveMock).toContain('aria-label="Search this conversation"');
    expect(adaptiveMock).toContain('class="ex-window-search-count" aria-live="polite"');
    expect(adaptiveMock).toContain('class="ex-search-previous" aria-label="Previous match"');
    expect(adaptiveMock).toContain('class="ex-search-next" aria-label="Next match"');
    expect(adaptiveMock).toContain('aria-label="Command deck layout"');
    expect(adaptiveMock).toContain('class="ex-backend-status">deterministic</span>');
    expect(adaptiveMock).toContain('../../console/public/agent-icons/bragi.svg');
    expect(adaptiveMock).toContain('aria-label="Filter conversations" placeholder="Filter conversations"');
    expect(adaptiveMock).toContain('data-filter="all" aria-pressed="true">Mine</button>');
    expect(adaptiveMock).toContain('aria-label="Conversation workspace tools"');
    expect(sharedPrimitives).toContain("--cs-deck-conversation-width: 240px");
    expect(sharedPrimitives).toContain("--cs-deck-digest-width: 280px");
    expect(adaptiveMock).not.toContain("grid-template-columns: 220px minmax(0, 1fr)");
    expect(adaptiveMock).toContain("grid-template-rows: 50px auto minmax(0, 1fr) auto");
    expect(adaptiveMock).toContain("@media (max-width: 1100px)");
    expect(adaptiveMock).toContain("width: min(300px, 82%)");
    expect(adaptiveMock).toContain('workbench.dataset.shell = enabled ? "workspace" : "specimen"');
    expect(adaptiveMock).toContain("setConversations(false);");
    expect(adaptiveMock).toContain("setDigest(false);");
    expect(adaptiveMock).toContain('class="ex-conversations-scrim cs-deck-conversation-scrim"');
    expect(adaptiveMock).toContain('workbench.querySelector(".ex-digest-toggle").addEventListener');
    expect(adaptiveMock).toContain('workbench.querySelector(".ex-conversation-search").addEventListener');
    expect(adaptiveMock).toContain('class="ex-conversations-count">20+</span>');
    expect(adaptiveMock).toContain('class="ex-conversation-new" aria-label="New conversation"');
    expect(adaptiveMock).toContain('class="ex-conversation-resize" role="separator"');
    expect(adaptiveMock).toContain('class="ex-conversation-favorite"');
    expect(adaptiveMock).toContain('class="ex-conversation-remove"');
    expect(adaptiveMock).toContain('aria-label="Current screen"');
    expect(adaptiveMock).toContain('aria-label="Other screens"');
    expect(adaptiveMock).toContain('aria-label="Agent conversations"');
    expect(adaptiveMock).toContain('workbench.querySelector(".ex-new-conversation").addEventListener');
    expect(adaptiveMock).toContain('workbench.querySelector(".ex-jump-latest").addEventListener');
    expect(adaptiveMock).toContain('workbench.querySelector(".ex-close-deck").addEventListener');
    expect(adaptiveMock).toContain('transcriptSearch.addEventListener("input", applyTranscriptSearch)');
    expect(adaptiveMock).toContain('transcriptSearchPrevious.addEventListener("click"');
    expect(adaptiveMock).toContain('transcriptSearchNext.addEventListener("click"');
    expect(adaptiveMock).toContain('conversationResize.addEventListener("keydown"');
    expect(adaptiveMock).toContain('conversationResize.addEventListener("mousedown"');
    expect(adaptiveMock).toContain('workbench.querySelector(".ex-digest-refresh").addEventListener');
    expect(adaptiveMock).toContain('class="ex-digest-freshness" data-state="stale"');
    expect(adaptiveMock).toContain('var states = ["hidden", "loading", "error", "ready"]');
    expect(adaptiveMock).toContain('sourceReadiness.setAttribute("aria-busy", "true")');
    expect(adaptiveMock).toContain('sourceReadiness.classList.add("is-error")');
    expect(adaptiveMock).toContain('sourceReadiness.setAttribute("role", "navigation")');
    expect(adaptiveMock).toContain('workbench.addEventListener("keydown", function (event)');
    expect(adaptiveMock).toContain('event.key !== "Tab"');
    expect(adaptiveMock).toContain('event.key === "Escape"');
    expect(adaptiveMock).toContain('transcriptSearch.select()');
    expect(adaptiveMock).toContain('.ex-workbench[data-shell="workspace"] .ex-window-layout { display: none; }');
    expect(adaptiveMock).toContain('.ex-window-search button, .ex-close-deck { width: 44px; height: 44px; }');
    expect(adaptiveMock).toContain('.ex-conversation-search, .ex-conversation-filters button, .ex-conversation-select { min-height: 44px;');
    expect(adaptiveMock).toContain('workbench.querySelector(".ex-attach").addEventListener');
    expect(adaptiveMock).toContain('workbench.querySelector(".ex-send").addEventListener');
  });
});
