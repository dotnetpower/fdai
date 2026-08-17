import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const sidebarStyles = readFileSync(
  fileURLToPath(new URL("./conversation-sidebar.css", import.meta.url)),
  "utf8",
);
const structuredStyles = readFileSync(
  fileURLToPath(new URL("./structured-reply.css", import.meta.url)),
  "utf8",
);
const source = readFileSync(
  fileURLToPath(new URL("./command-deck-view.tsx", import.meta.url)),
  "utf8",
);
const presenters = readFileSync(
  fileURLToPath(new URL("./command-deck-presenters.tsx", import.meta.url)),
  "utf8",
);
const sessions = readFileSync(
  fileURLToPath(new URL("./use-command-deck-sessions.ts", import.meta.url)),
  "utf8",
);

describe("Command Deck workspace hierarchy", () => {
  test("opens transcript-first and adds columns only for requested panels", () => {
    expect(source).toContain("const [showConversations, setShowConversations] = useState(false);");
    expect(source).toContain("const [showDigest, setShowDigest] = useState(false);");
    expect(sidebarStyles).toContain("grid-template-columns: var(--deck-conversation-width, 240px) minmax(0, 1fr);");
    expect(styles).toContain(".deck-body.has-digest { grid-template-columns: minmax(0, 1fr) 280px; }");
  });

  test("loads conversation history incrementally", () => {
    expect(source).toContain("hasMore={conversationHasMore}");
    expect(source).toContain("onLoadMore={onLoadMoreConversations}");
    expect(source).toContain("conversationCountLabel(conversations.length, conversationHasMore)");
    expect(sessions).toContain(".slice(0, CONVERSATION_HISTORY_PAGE_SIZE)");
    expect(sessions).toContain("setSessionLabel(agent);");
    expect(presenters).toContain("CONVERSATION_VISIBLE_BATCH_SIZE");
    expect(presenters).toContain("visibleLimit");
  });

  test("persists a bounded workspace conversation width", () => {
    expect(source).toContain("initialConversationWidth");
    expect(source).toContain("clampConversationWidth");
    expect(source).toContain("saveConversationWidth");
    expect(source).toContain('style={`--deck-conversation-width: ${conversationWidth}px`}');
    expect(source).toContain("onResizeStart={startConversationResize}");
    expect(sidebarStyles).toContain(".deck-conversation-resize-handle {");
    expect(sidebarStyles).toContain("cursor: col-resize;");
  });

  test("keeps conversation controls compact and the list independently scrollable", () => {
    expect(sidebarStyles).toContain(".deck-conversation-controls {");
    expect(sidebarStyles).toContain("grid-template-columns: minmax(0, 1fr) 30px;");
    expect(sidebarStyles).toContain("border-bottom: 1px solid var(--border);");
    expect(sidebarStyles).toContain("overflow-y: auto;");
  });

  test("does not reserve a hidden digest column on narrow screens", () => {
    expect(styles).toContain(".deck-body.has-digest { grid-template-columns: minmax(0, 1fr); }");
    expect(styles).toContain(".deck-panel-toggle-context { display: none; }");
    expect(styles).not.toContain(".deck-body { min-width: 0; grid-template-columns: 200px minmax(0, 1fr); }");
  });

  test("opens conversation history as an overlay outside workspace mode", () => {
    expect(styles).toContain(".deck-overlay-mode-floating .deck-body.has-conversations,");
    expect(styles).toContain(".deck-overlay-mode-floating .deck-body.has-digest,");
    expect(styles).toContain(".deck-overlay-mode-dock .deck-body.has-conversations,");
    expect(styles).toContain(".deck-overlay-mode-dock .deck-body.has-digest { grid-template-columns: minmax(0, 1fr); }");
    expect(styles).toContain(".deck-overlay-mode-dock .deck-conversations {");
    expect(styles).toContain("position: absolute;");
    expect(styles).toContain("inset: 42px auto 0 0;");
    expect(styles).toContain("width: min(300px, 82%);");
    expect(styles).not.toContain(".deck-overlay-mode-dock .deck-transcript-tools { display: none; }");
  });

  test("keeps route and freshness metadata out of the composer", () => {
    expect(source).not.toContain('class="deck-composer-scope"');
    expect(styles).not.toContain(".deck-composer-scope");
    expect(source).toContain("<CommandDeckHeader");
    expect(source).toContain("routeLabel={routeLabel}");
    expect(source).toContain('class="deck-digest-header"');
  });

  test("keeps the latest-message action in the toolbar instead of over transcript content", () => {
    const toolbar = source.slice(
      source.indexOf('class="deck-transcript-tools"'),
      source.indexOf('class="deck-transcript"'),
    );
    expect(toolbar).toContain('class="deck-jump"');
    expect(styles).toContain(".deck-jump {");
    expect(styles).toContain("margin-left: auto;");
    expect(styles).not.toMatch(/\.deck-jump\s*\{[^}]*position:\s*sticky/s);
  });

  test("keeps readable metadata at 12px and keyboard focus visible", () => {
    expect(styles).toContain(".deck-turn-time,\n.deck-code-lang,");
    expect(styles).toContain("font-size: 12px;\n}");
    expect(styles).toContain(".deck-btn:focus-visible,");
    expect(styles).toContain("outline: 2px solid var(--accent);");
    expect(styles).toContain(".deck-conversation-select:focus-visible {");
    expect(styles).toContain(".deck-input:focus-visible {");
    expect(styles).toMatch(/\.deck-source-readiness \{[^}]*font-size: 12px;/s);
    expect(presenters).toContain('class="deck-turn-time muted"');
    expect(presenters).toContain("dateTime={turn.recordedAt}");
    expect(presenters).toContain("presentationTimestamp(");
  });

  test("keeps syntax-highlighted code on its dark slab", () => {
    expect(styles).toMatch(/\.deck-code-pre \{[^}]*background: transparent;[^}]*color-scheme: dark;/s);
  });

  test("reflows execution details from the deck container width", () => {
    expect(styles).toContain("container-name: deck-transcript;");
    expect(styles).toContain("@container deck-transcript (max-width: 620px)");
    expect(styles).toContain("grid-template-columns: 58px minmax(0, 1fr) auto 9px;");
  });

  test("keeps reply sources readable and reflows structured evidence on mobile", () => {
    expect(styles).toContain(".deck-turn-head > .tooltip-anchor {");
    expect(styles).toContain("max-width: min(75%, 420px);");
    expect(styles).toContain(".deck-turn-head > .tooltip-anchor .deck-turn-source { max-width: 100%; }");
    expect(structuredStyles).toContain("@media (max-width: 700px)");
    expect(structuredStyles).toMatch(/@media \(max-width: 700px\)[\s\S]*\.deck-presentation-table,[\s\S]*display: block;/);
  });

  test("keeps deck controls operable at desktop and touch sizes", () => {
    expect(styles).toMatch(/\.deck-search button \{[^}]*width: 32px;[^}]*height: 32px;/s);
    expect(styles).toMatch(/\.deck-gr-icon \{[^}]*width: 32px;[^}]*height: 32px;/s);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-search button \{ width: 44px; height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-gr-icon \{ width: 44px; height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-layout-button \{ width: 44px; height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-input-row button \{ min-width: 44px; min-height: 44px; \}/);
  });
});
