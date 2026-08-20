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
const tableModule = readFileSync(
  fileURLToPath(new URL("./presentation-modules/table.tsx", import.meta.url)),
  "utf8",
);
const sessions = readFileSync(
  fileURLToPath(new URL("./use-command-deck-sessions.ts", import.meta.url)),
  "utf8",
);
const historyState = readFileSync(
  fileURLToPath(new URL("./conversation-history-state.tsx", import.meta.url)),
  "utf8",
);

describe("Command Deck workspace hierarchy", () => {
  test("opens transcript-first and adds columns only for requested panels", () => {
    expect(source).toContain("const [showConversations, setShowConversations] = useState(false);");
    expect(source).toContain("const [showDigest, setShowDigest] = useState(false);");
    expect(source).toContain('class="deck-source-readiness-slot"');
    expect(sidebarStyles).toContain("grid-template-columns: var(--deck-conversation-width, 240px) minmax(0, 1fr);");
    expect(styles).toContain(".deck-body.has-digest { grid-template-columns: minmax(0, 1fr) 280px; }");
    expect(styles).toMatch(/\.deck-overlay \{[^}]*grid-template-columns: minmax\(0, 1fr\);/s);
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

  test("separates durable history loading and failures from a new conversation", () => {
    expect(source).toContain('hydrationStatus !== "idle"');
    expect(source).toContain('hydrationStatus === "idle"');
    expect(historyState).toContain('aria-busy="true"');
    expect(historyState).toContain('role={failed ? "alert" : "status"}');
    expect(historyState).toContain('t("deck.history.retry")');
    expect(styles).toContain(".deck-history-state.is-error");
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-history-state button \{ min-height: 44px; \}/);
    expect(styles).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.deck-history-state\.is-loading span,/);
    expect(styles).toContain(".deck-history-state button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }");
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
    expect(sidebarStyles).toMatch(
      /@media \(max-width: 1100px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-body\.has-conversations\.has-digest \{[^}]*grid-template-columns: minmax\(0, 1fr\);/,
    );
    expect(styles).not.toContain(".deck-body { min-width: 0; grid-template-columns: 200px minmax(0, 1fr); }");
  });

  test("opens mobile conversation history over a full-width transcript", () => {
    expect(sidebarStyles).toMatch(
      /@media \(max-width: 1100px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-body\.has-conversations,[\s\S]*grid-template-columns: minmax\(0, 1fr\);/,
    );
    expect(sidebarStyles).toMatch(
      /@media \(max-width: 1100px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-conversations \{[^}]*position: absolute;[^}]*width: var\(--deck-conversation-width, 240px\);/,
    );
    expect(sidebarStyles).toMatch(/@media \(max-width: 780px\)[\s\S]*width: min\(300px, 82%\);/);
    expect(sidebarStyles).toMatch(
      /\.deck-overlay-mode-workspace \.deck-conversations-dismiss \{[^}]*display: grid;[^}]*width: 44px;[^}]*height: 44px;/s,
    );
    expect(source).toContain("onDismiss={() => setShowConversations(false)}");
    expect(presenters).toContain('class="deck-conversations-dismiss"');
    expect(source).toContain('class="deck-conversations-scrim"');
    expect(sidebarStyles).toMatch(/@media \(max-width: 1100px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-conversations-scrim \{[^}]*position: absolute;[^}]*inset: 0;[^}]*display: block;/);
  });

  test("opens conversation history as an overlay outside workspace mode", () => {
    expect(styles).toContain(".deck-overlay-mode-floating .deck-body.has-conversations,");
    expect(styles).toContain(".deck-overlay-mode-floating .deck-body.has-digest,");
    expect(styles).toContain(".deck-overlay-mode-dock .deck-body.has-conversations,");
    expect(styles).toContain(".deck-overlay-mode-dock .deck-body.has-digest { grid-template-columns: minmax(0, 1fr); }");
    expect(sidebarStyles).toMatch(/\.deck-overlay-mode-floating \.deck-conversations,[\s\S]*\.deck-overlay-mode-dock \.deck-conversations \{[^}]*position: absolute;[^}]*inset: 0 auto 0 0;[^}]*width: min\(300px, 82%\);/);
    expect(sidebarStyles).toMatch(/\.deck-overlay-mode-floating \.deck-conversations-scrim,[\s\S]*\.deck-overlay-mode-dock \.deck-conversations-scrim \{[^}]*position: absolute;[^}]*inset: 0;[^}]*display: block;/);
    expect(styles).not.toContain(".deck-overlay-mode-dock .deck-transcript-tools { display: none; }");
  });

  test("keeps route and freshness metadata out of the composer", () => {
    expect(source).not.toContain('class="deck-composer-scope"');
    expect(styles).not.toContain(".deck-composer-scope");
    expect(source).toContain("<CommandDeckHeader");
    expect(source).toContain("routeLabel={routeLabel}");
    expect(source).toContain('class="deck-digest-header"');
    expect(source).toContain('placeholder={t("deck.inputPlaceholder")}');
    expect(source).toContain('aria-label={t("deck.inputPlaceholderContext", { route: routeLabel })}');
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
    expect(styles).toContain(".deck-verification.is-unverified.is-sourceUnavailable");
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
    expect(structuredStyles).toContain("@media (max-width: 560px)");
    expect(structuredStyles).toMatch(/@media \(max-width: 560px\)[\s\S]*\.deck-presentation-table,[\s\S]*display: block;/);
  });

  test("matches the mock's flat report-table hierarchy", () => {
    expect(styles).toMatch(/\.deck-table \{[^}]*border: 0;[^}]*border-top: 1px solid var\(--border\);/s);
    expect(styles).toMatch(/\.deck-table thead th \{[^}]*background: transparent;[^}]*border-bottom: 2px solid var\(--accent-strong, var\(--accent\)\);/s);
    expect(structuredStyles).toMatch(/\.deck-presentation-table \{[^}]*border: 0;[^}]*border-top: 1px solid var\(--border\);/s);
    expect(structuredStyles).toMatch(/\.deck-presentation-table th \{[^}]*text-transform: uppercase;[^}]*border-bottom: 2px solid var\(--accent-strong, var\(--accent\)\);/s);
    expect(structuredStyles).toMatch(/\.deck-presentation-table tbody tr:nth-child\(even\) \{\s*background: transparent;/s);
  });

  test("aligns answers, structured evidence, and the composer to one calm reading measure", () => {
    expect(styles).toContain("--deck-reading-width: 760px;");
    expect(styles).toMatch(/\.deck-overlay-mode-workspace \{[^}]*inset: var\(--header-height\) 0 0 var\(--rail-width, 88px\);[^}]*width: auto;[^}]*height: auto;[^}]*min-width: 0;[^}]*min-height: 0;/s);
    expect(styles).toMatch(
      /\.deck-overlay-mode-workspace \.deck-transcript-inner \{[^}]*padding-inline: clamp\(24px, 6vw, 60px\);/s,
    );
    expect(styles).toMatch(
      /\.deck-overlay-mode-workspace \.deck-turn-deck,[\s\S]*?width: min\(100%, var\(--deck-reading-width\)\);/,
    );
    expect(styles).toMatch(
      /\.deck-overlay-mode-workspace \.deck-composer-inner \{[^}]*width: min\(100%, calc\(var\(--deck-reading-width\) \+ 120px\)\);/s,
    );
    expect(styles).toMatch(/\.deck-header \{[^}]*position: relative;[^}]*z-index: 2;/s);
    expect(styles).toMatch(/\.deck-body \{[^}]*position: relative;[^}]*z-index: 1;/s);
    expect(styles).toMatch(/\.deck-input-row \{[^}]*z-index: 2;/s);
    expect(styles).toMatch(/\.deck-transcript \{[^}]*overflow-x: hidden;[^}]*overflow-y: auto;/s);
    expect(styles).toContain(".deck-table-block,");
    expect(styles).toContain(".deck-table-cell-value {");
    expect(styles).toContain("overflow-wrap: anywhere;");
    expect(structuredStyles).toMatch(
      /\.deck-presentation-table \{[^}]*width: 100%;[^}]*max-width: 100%;/s,
    );
    expect(structuredStyles).toMatch(
      /\.deck-presentation-table th \{[^}]*position: sticky;[^}]*top: 0;[^}]*z-index: 1;/s,
    );
    expect(tableModule).toContain("data-field={presentationFieldRole(column.label)}");
    expect(structuredStyles).toContain('.deck-presentation-table th[data-field="name"],');
    expect(structuredStyles).toContain('.deck-presentation-table td[data-field="name"] { width: 58%; }');
    expect(structuredStyles).toContain('.deck-presentation-table td[data-field="type"] { width: 24%; }');
    expect(structuredStyles).toContain('.deck-presentation-table td[data-field="location"] { width: 18%; }');
    expect(structuredStyles).toMatch(
      /@media \(max-width: 560px\)[\s\S]*\.deck-presentation-table th \{ position: static; \}/,
    );
  });

  test("keeps pending stages visible and sizes the source slot from content", () => {
    expect(styles).toMatch(/\.deck-rt-slot \{[^}]*max-height: 180px;[^}]*overflow: hidden;/s);
    expect(styles).not.toMatch(/\.deck-rt-slot \{[^}]*\n\s*height: 180px;/s);
    expect(styles).toMatch(/@keyframes deck-rt-rise \{\s*from \{ opacity: 0;/s);
    expect(styles).toMatch(/@keyframes deck-rt-pop \{\s*from \{ opacity: 0;/s);
    expect(styles).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.deck-rt-stage,[\s\S]*\.deck-rt-source \{\s*opacity: 1;\s*transform: none;/);
  });

  test("restores workspace geometry without reduced-motion transitions", () => {
    expect(styles).toMatch(
      /:root\[data-motion="reduced"\] \.deck-overlay \{\s*animation: none !important;\s*transition: none !important;/,
    );
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.deck-overlay \{ transition: none !important; \}/,
    );
    expect(styles.match(/transition-duration: 0s !important;/g)).toHaveLength(2);
    expect(styles).not.toContain("transition-duration: 0.01ms !important;");
  });

  test("keeps deck controls operable at desktop and touch sizes", () => {
    expect(styles).toMatch(/\.deck-llm-escalation-head \{[^}]*min-height: 44px;/s);
    expect(styles).toContain(".deck-llm-escalation-head:focus-visible");
    expect(styles).toMatch(/\.deck-search button \{[^}]*width: 32px;[^}]*height: 32px;/s);
    expect(styles).toMatch(/\.deck-gr-icon \{[^}]*width: 32px;[^}]*height: 32px;/s);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-search button \{ width: 44px; height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-gr-icon \{ width: 44px; height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-transcript-tools \{ overflow-x: hidden; padding-inline: 12px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-transcript-tools button \{[^}]*min-height: 44px;[^}]*padding-inline: 6px;/s);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-layout-controls \{ display: none; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-input-row button \{ min-width: 44px; min-height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-source-status \{ min-height: 44px;/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-search input \{ min-height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-input \{ min-height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-vertical-suggest,[\s\S]*\.deck-suggest \{ min-height: 44px; \}/);
    expect(sidebarStyles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-conversation-filter \{ min-height: 44px; \}/);
    expect(sidebarStyles).toMatch(/\.deck-overlay-mode-workspace \.deck-conversation-remove \{[^}]*width: 44px;[^}]*height: 44px;/s);
    expect(sidebarStyles).toMatch(/\.deck-overlay-mode-workspace \.deck-conversation-favorite \{[^}]*width: 44px;[^}]*height: 44px;/s);
  });

  test("keeps mobile header and composer compact", () => {
    expect(styles).toMatch(
      /@media \(max-width: 640px\)[\s\S]*grid-template-areas:\s*"title close"\s*"headline headline";/,
    );
    expect(styles).toMatch(
      /@media \(max-width: 640px\)[\s\S]*\.deck-composer-inner \{ grid-template-columns: auto minmax\(0, 1fr\) auto;/,
    );
    expect(styles).toContain("calc((100% - 1100px) / 2)");
    expect(styles).toContain("flex: 0 1 420px;");
    expect(styles).toContain(".deck-overlay.deck-overlay-mode-workspace { left: 0; }");
    expect(styles).toMatch(/\.deck-input \{[^}]*width: 100%;[^}]*min-width: 0;[^}]*box-sizing: border-box;/s);
    expect(styles).toMatch(/@media \(max-width: 1100px\)[\s\S]*\.deck-search kbd \{ display: none; \}/);
  });
});
