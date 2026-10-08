import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const sharedStyles = readFileSync(
  fileURLToPath(new URL("../../../ui/calm-slate-primitives.css", import.meta.url)),
  "utf8",
);
const sidebarStyles = readFileSync(
  fileURLToPath(new URL("./conversation-sidebar.css", import.meta.url)),
  "utf8",
);
const conversationLayer = readFileSync(
  fileURLToPath(new URL("../../../ui/calm-slate-deck-conversation.css", import.meta.url)),
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
const header = readFileSync(
  fileURLToPath(new URL("./command-deck-header.tsx", import.meta.url)),
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
  test("activates the shared mock conversation layer on the real Console root", () => {
    expect(styles).toContain('@import url("../../ui/calm-slate-deck-conversation.css");');
    expect(source).toContain("cs-deck-workspace-shell cs-deck-conversation");
    expect(source).toContain('class="deck-transcript cs-deck-transcript"');
    expect(source).toContain("deck-transcript-inner cs-deck-transcript-inner");
  });

  test("opens transcript-first and adds columns only for requested panels", () => {
    expect(source).toContain("const [showConversations, setShowConversations] = useState(false);");
    expect(source).toContain('class="deck-source-readiness-slot cs-deck-source-readiness-slot"');
    expect(sidebarStyles).toContain("grid-template-columns: var(--deck-conversation-width, 240px) minmax(0, 1fr);");
    expect(source).not.toContain("showDigest");
    expect(source).not.toContain("DigestList");
    expect(styles).toMatch(/\.deck-overlay \{[^}]*grid-template-columns: minmax\(0, 1fr\);/s);
    for (const role of [
      "cs-deck-workspace-shell",
      "cs-deck-workspace-header",
      "cs-deck-source-readiness-slot",
      "cs-deck-workspace-body",
      "cs-deck-conversation-panel",
      "cs-deck-conversation-scrim",
      "cs-deck-transcript-column",
    ]) {
      expect(sharedStyles).toContain(`.${role}`);
      expect(`${source}\n${header}\n${presenters}`).toContain(role);
    }
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

  test("keeps conversation actions in the header and omits screen information", () => {
    expect(header).toContain('class="deck-header-actions"');
    expect(header).toContain('class="deck-header-action deck-header-history"');
    expect(header).toContain('class="deck-header-action-count"');
    expect(source).not.toContain("deck-panel-toggle-context");
    expect(source).not.toContain("deck-digest");
    expect(styles).toContain(".deck-header-action {");
  });

  test("closes auxiliary panels when starting a new conversation", () => {
    expect(source).toContain("const beginNewConversation = () => {");
    expect(source).toContain("setShowConversations(false);");
    expect(source).toContain("onNewConversation={beginNewConversation}");
    expect(source).toContain("onNew={beginNewConversation}");
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

  test("centers the composer only for a new workspace conversation", () => {
    expect(source).toContain('const centeredEmptyState = emptyConversation && layoutMode === "workspace";');
    expect(source).toContain('centered={centeredEmptyState}');
    expect(source).toContain('{centeredEmptyState ? composer : null}');
    expect(source).toContain('{centeredEmptyState ? null : composer}');
    expect(source).toContain('centeredEmptyState ? " is-empty-conversation" : ""');
    expect(presenters).toContain('class="deck-intro-title"');
    expect(presenters).toContain('class="deck-intro deck-intro-cards"');
    expect(presenters).toContain('class="deck-intro-card-grid"');
    expect(presenters).toContain('class="deck-intro-card is-feature"');
    expect(presenters).toContain('<IntroCardIcon kind="checklist" />');
    expect(presenters).toContain('onClick={() => onPick(card.prompt)}');
    expect(presenters).toContain('onClick={() => onPick(screenPrompt)}');
    expect(styles).toMatch(/\.deck-overlay-mode-workspace \.deck-transcript-inner\.is-empty-conversation \{[^}]*justify-content: center;/s);
    expect(styles).toMatch(/\.deck-overlay-mode-workspace \.deck-intro-card-grid \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\) minmax\(230px, 1\.35fr\);[^}]*grid-template-rows: repeat\(2, minmax\(132px, auto\)\);/s);
    expect(styles).toMatch(/\.deck-overlay-mode-workspace \.deck-intro-card\.is-feature \{[^}]*grid-column: 3;[^}]*grid-row: 1 \/ 3;[^}]*min-height: 278px;/s);
    expect(styles).toMatch(/\.deck-input-row\.is-centered \{[^}]*border-top: 0;[^}]*background: transparent;/s);
    expect(styles).toMatch(/\.deck-overlay-mode-workspace \.deck-input-row\.is-centered \.deck-composer-inner \{[^}]*width: min\(100%, 820px\);[^}]*border-radius: 14px;/s);
    expect(styles).toMatch(/\.deck-input-row\.is-centered \.deck-input \{[^}]*height: 48px;[^}]*padding-block: 13px;[^}]*line-height: 22px;/s);
    expect(source).toContain('class="deck-send-icon"');
    expect(styles).toContain(".deck-input-row.is-centered .deck-send-label { display: none; }");
    // Jump to latest follows the measured transcript, never a bare turn count.
    expect(source).toContain("{jumpVisible ? (");
    expect(source).not.toContain("showJumpToLatest");
  });

  test("shows compact pending feedback before observed progress", () => {
    expect(source).toContain(
      "const showPendingReply = pending && retrievalProgress === null && !finalAnswerPresent;",
    );
    expect(source).toContain(
      "const showPreparingAnswer = inFlight && retrievalProgress !== null && !finalAnswerPresent;",
    );
    expect(source).toContain("<PendingReplyIndicator />");
    expect(source).toContain("<RetrievalTrace");
    expect(styles).toContain(".deck-pending-reply {");
    expect(styles).toContain("@keyframes deck-pending-dot");
    expect(styles).toContain(':root[data-motion="reduced"] .deck-pending-reply,');
    expect(styles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.deck-pending-reply,[\s\S]*\.deck-pending-reply-dots > span,/,
    );
    // The preparing trace enters with the conversation layer's motion, which honors reduced motion.
    expect(conversationLayer).toContain(".cs-deck-enter { animation: cs-deck-enter .26s");
    expect(conversationLayer).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.cs-deck-enter,/);
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

  test("keeps the conversation overlay from reserving another side panel", () => {
    expect(source).not.toContain("has-digest");
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
    expect(source).toContain('class="deck-conversations-scrim cs-deck-conversation-scrim"');
    expect(sidebarStyles).toMatch(/@media \(max-width: 1100px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-conversations-scrim \{[^}]*position: absolute;[^}]*inset: 0;[^}]*display: block;/);
  });

  test("opens conversation history as an overlay outside workspace mode", () => {
    expect(styles).toContain(".deck-overlay-mode-floating .deck-body.has-conversations,");
    expect(styles).toContain(".deck-overlay-mode-dock .deck-body.has-conversations,");
    expect(sidebarStyles).toMatch(/\.deck-overlay-mode-floating \.deck-conversations,[\s\S]*\.deck-overlay-mode-dock \.deck-conversations \{[^}]*position: absolute;[^}]*inset: 0 auto 0 0;[^}]*width: min\(300px, 82%\);/);
    expect(sidebarStyles).toMatch(/\.deck-overlay-mode-floating \.deck-conversations-scrim,[\s\S]*\.deck-overlay-mode-dock \.deck-conversations-scrim \{[^}]*position: absolute;[^}]*inset: 0;[^}]*display: block;/);
    expect(styles).not.toContain(".deck-overlay-mode-dock .deck-transcript-tools { display: none; }");
  });

  test("shows only explicitly selected screen context in the composer", () => {
    expect(source).not.toContain('class="deck-composer-scope"');
    expect(styles).not.toContain(".deck-composer-scope");
    expect(source).toContain("<CommandDeckHeader");
    expect(source).toContain("routeLabel={routeLabel}");
    expect(source).not.toContain('class="deck-digest-header"');
    expect(source).toContain('placeholder={t("deck.inputPlaceholder")}');
    expect(source).toContain('t("deck.inputPlaceholderContext", { route: routeLabel })');
    expect(source).toContain('class="deck-composer-context cs-deck-composer-context"');
    expect(source).toContain('class={`deck-context-control cs-deck-context-chip${snapshot ? "" : " is-empty"}`}');
    expect(source).toContain("onClick={snapshot ? onRemoveScreen : onAttachScreen}");
  });

  test("anchors the latest-message action in the composer context row", () => {
    const transcriptColumn = source.slice(
      source.indexOf('class="deck-transcript-column cs-deck-transcript-column"'),
      source.indexOf('class="deck-transcript cs-deck-transcript"'),
    );
    const contextRow = source.slice(
      source.indexOf('<div class="deck-composer-context cs-deck-composer-context">'),
      source.indexOf('<div class="deck-composer-inner cs-deck-composer-grid">'),
    );
    // The action never floats over the transcript, so it can't cover an answer being read.
    expect(transcriptColumn).not.toContain("deck-jump");
    expect(contextRow).toContain('class="deck-jump cs-deck-jump"');
    expect(contextRow).toContain('<span class="cs-deck-jump-label">{t("deck.jumpLatest")}</span>');
    expect(source).toContain("{snapshot || canAttachScreen || jumpVisible ? (");
    expect(conversationLayer).toMatch(/\.cs-deck-jump \{[^}]*margin-left: auto;[^}]*border-radius: var\(--cs-radius-pill\);/s);
    expect(source).not.toContain("deck-jump-slot");
    expect(styles).not.toContain(".deck-jump");
  });

  test("keeps readable metadata at 12px and keyboard focus visible", () => {
    expect(styles).toContain(".deck-turn-time,\n.deck-citation,");
    expect(styles).toContain("font-size: 12px;\n}");
    expect(styles).toContain(".deck-btn:focus-visible,");
    expect(styles).toContain("outline: 2px solid var(--accent);");
    expect(styles).toContain(".deck-conversation-select:focus-visible {");
    expect(styles).toContain(".deck-input:focus-visible {");
    expect(conversationLayer).toMatch(
      /\.cs-deck-readiness \{[^}]*font: var\(--cs-type-label-size\)\/var\(--cs-type-label-line-height\) var\(--cs-font\);/s,
    );
    expect(presenters).toContain('class="deck-turn-time muted"');
    expect(presenters).toContain('class="cs-deck-user-time"');
    expect(presenters).toContain('class="cs-deck-user-line"');
    expect(presenters).toContain("isDeck && (!isInvestigationFlow || isInvestigationFinalAnswer)");
    expect(presenters).toContain("dateTime={turn.recordedAt}");
    expect(presenters).toContain("presentationTimestamp(");
    expect(conversationLayer).toMatch(
      /\.cs-deck-verification \{[^}]*font: 600 var\(--cs-type-label-size\)\/var\(--cs-type-label-line-height\) var\(--cs-font\);/s,
    );
    expect(conversationLayer).toMatch(/\.cs-deck-verification:focus-visible \{[^}]*outline: 2px solid var\(--cs-steel\);/s);
    expect(styles).not.toMatch(/\.deck-verification[\s.{:,-]/);
  });

  test("keeps syntax-highlighted code on the shared code surface", () => {
    expect(conversationLayer).toMatch(/\.cs-deck-code \{[^}]*background: var\(--cs-code-bg\);/s);
    expect(conversationLayer).toMatch(/\.cs-deck-code-scroll \{[^}]*color-scheme: dark;/s);
    expect(conversationLayer).toMatch(
      /\.cs-deck-code-block > \.cs-deck-code-text \{[^}]*overflow-wrap: anywhere;[^}]*white-space: pre-wrap;/s,
    );
    expect(styles).toContain(".cs-deck-code :is(.hljs-attr, .hljs-attribute, .hljs-name, .hljs-tag) { color: var(--cs-code-key); }");
    expect(styles).toContain(".cs-deck-code :is(.hljs-string, .hljs-regexp, .hljs-addition) { color: var(--cs-code-string); }");
    expect(styles).not.toMatch(/^\.hljs-/m);
    expect(styles).not.toMatch(/\.deck-code(-pre|-head|-lang|-copy)?[\s.{:,]/);
  });

  test("reflows execution details from the deck container width", () => {
    expect(styles).toContain("container-name: deck-transcript;");
    expect(styles).toContain("@container deck-transcript (max-width: 620px)");
    expect(conversationLayer).toMatch(
      /@container deck-transcript \(max-width: 620px\)[\s\S]*\.cs-run-timeline \{ --cs-run-columns: minmax\(0, 1fr\) auto auto 10px; \}/,
    );
  });

  test("keeps reply sources readable and reflows structured evidence on mobile", () => {
    expect(styles).toContain(".deck-turn-head > .tooltip-anchor {");
    expect(styles).toContain("max-width: min(75%, 420px);");
    expect(styles).toContain(".deck-turn-head > .tooltip-anchor .deck-turn-source { max-width: 100%; }");
    expect(structuredStyles).toContain("@media (max-width: 560px)");
    expect(structuredStyles).toMatch(/@media \(max-width: 560px\)[\s\S]*\.deck-presentation-table,[\s\S]*display: block;/);
    // A narrow deck keeps the source links on one scrollable row with unavailable sources first.
    expect(conversationLayer).toMatch(
      /@container deck-readiness \(max-width: 560px\) \{[\s\S]*?\.cs-deck-readiness-items \{[^}]*flex: 1 1 100%;[^}]*overflow-x: auto;/,
    );
    expect(styles).toMatch(
      /@media \(max-width: 640px\)[\s\S]*\.deck-overlay-mode-dock \.deck-dock-resize-handle \{ display: none; \}/,
    );
  });

  test("matches the conversation layer's quiet table headers", () => {
    expect(styles).toMatch(/\.deck-table \{[^}]*border: 0;[^}]*border-top: 1px solid var\(--border\);/s);
    // Column headers read as quiet labels on a faint band, never uppercase or accent-ruled.
    const quietHeader =
      /background: color-mix\(in srgb, var\(--cs-text\) 2%, var\(--cs-card\)\);[^}]*color: var\(--cs-deck-meta-text\);[^}]*font-size: 12px;[^}]*text-transform: none;[^}]*border-bottom: 1px solid var\(--cs-hairline\);/s;
    expect(styles).toMatch(new RegExp(`\\.deck-table thead th \\{[^}]*${quietHeader.source}`, "s"));
    expect(structuredStyles).toMatch(new RegExp(`\\.deck-presentation-table th \\{[^}]*${quietHeader.source}`, "s"));
    expect(conversationLayer).toMatch(/\.cs-deck-table th \{[^}]*color: var\(--cs-deck-meta-text\);/s);
    // Only the first letter of a data key is raised, so headers read as sentence case.
    const firstLetter = ".deck-presentation-table th::first-letter { text-transform: uppercase; }";
    expect(structuredStyles).toContain(firstLetter);
    expect(structuredStyles.replace(firstLetter, "")).not.toContain("text-transform: uppercase");
    expect(structuredStyles).toMatch(/\.deck-presentation-table \{[^}]*border: 0;[^}]*border-top: 1px solid var\(--border\);/s);
    expect(structuredStyles).toMatch(/\.deck-presentation-table tbody tr:nth-child\(even\) \{\s*background: transparent;/s);
  });

  test("aligns answers, structured evidence, and the composer to one calm reading measure", () => {
    expect(sharedStyles).toContain("--cs-deck-reading-width: 840px;");
    expect(styles).toContain("--deck-reading-width: var(--cs-deck-reading-width);");
    expect(styles).toMatch(/\.deck-overlay-mode-workspace \{[^}]*inset: var\(--header-height\) 0 0 var\(--rail-width, 88px\);[^}]*width: auto;[^}]*height: auto;[^}]*min-width: 0;[^}]*min-height: 0;/s);
    expect(styles).toMatch(
      /\.deck-overlay-mode-workspace \.deck-transcript-inner \{[^}]*padding-inline: clamp\(24px, 6vw, 60px\);/s,
    );
    expect(styles).toMatch(
      /\.deck-overlay-mode-workspace \.deck-turn-deck,[\s\S]*?width: min\(100%, var\(--deck-reading-width\)\);/,
    );
    expect(styles).toMatch(
      /\.deck-turn-operator \{[^}]*align-self: center;[^}]*width: min\(100%, var\(--deck-reading-width, var\(--cs-deck-reading-width\)\)\);/s,
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
    expect(tableModule).toContain('class="deck-presentation-table-wrap"');
  });

  test("keeps unscaled font metrics and aligned operational controls", () => {
    expect(styles).toMatch(
      /\.deck-overlay \{[^}]*font-family: var\(--font-sans\);[^}]*font-synthesis: none;[^}]*font-optical-sizing: auto;[^}]*text-rendering: auto;/s,
    );
    expect(styles).toMatch(/\.deck-transcript-inner \{[^}]*gap: 20px;/s);
    expect(styles).toMatch(
      /\.deck-overlay button,[\s\S]*?\.deck-overlay textarea \{[^}]*font-family: inherit;/s,
    );
    expect(styles).toMatch(
      /\.deck-header-action \{[^}]*width: 32px;[^}]*height: 32px;/s,
    );
    expect(styles).toMatch(/\.deck-close \{[^}]*width: 32px;[^}]*height: 32px;/s);
    expect(styles).toMatch(/\.deck-model-selector select \{[^}]*min-height: 32px;/s);
    expect(sharedStyles).toMatch(/\.cs-grounding-head \{[^}]*min-height: 44px;/s);
    expect(sharedStyles).toMatch(/\.cs-grounding-stage \{[^}]*min-height: 36px;/s);
    expect(conversationLayer).toMatch(/\.cs-grounding-phase \{[^}]*white-space: nowrap;/s);
    expect(tableModule).toContain("data-layout={layout}");
    expect(structuredStyles).toMatch(
      /\.deck-presentation-table\[data-layout="wide"\] \{[^}]*min-width: 960px;[^}]*table-layout: auto;/s,
    );
    expect(structuredStyles).toMatch(
      /\.deck-presentation-table th \{[^}]*position: sticky;[^}]*top: 0;[^}]*z-index: 1;/s,
    );
    expect(tableModule).toContain("data-field={presentationFieldRole(column.label)}");
    expect(tableModule).toContain("presentationColumnLabel(column.label)");
    expect(structuredStyles).toContain('.deck-presentation-table[data-layout="compact"] th[data-field="name"],');
    expect(structuredStyles).toContain('.deck-presentation-table[data-layout="compact"] td[data-field="name"] { width: 58%; }');
    expect(structuredStyles).toContain('.deck-presentation-table[data-layout="wide"] td[data-field="timestamp"] { min-width: 156px; }');
    expect(structuredStyles).toMatch(
      /@container deck-transcript \(max-width: 1000px\)[\s\S]*\.deck-presentation-table\[data-layout="wide"\][\s\S]*display: block;/,
    );
    // Only the wide table breaks out; the turn keeps the reading column so its prose stays aligned.
    expect(styles).not.toContain('.deck-turn-deck:has(.deck-presentation-table[data-layout="wide"])');
    expect(styles).toMatch(
      /\.deck-overlay-mode-workspace \.deck-turn-deck \.deck-presentation-table-wrap\[data-layout="wide"\] \{[^}]*--deck-wide-table-width: min\(1080px, calc\(100cqi - 48px\)\);[^}]*margin-inline: calc\(\(100% - var\(--deck-wide-table-width\)\) \/ 2\);/s,
    );
    expect(structuredStyles).toMatch(
      /@media \(max-width: 560px\)[\s\S]*\.deck-presentation-table th \{ position: static; \}/,
    );
  });

  test("keeps pending stages visible in a stable compact source slot", () => {
    expect(sharedStyles).toMatch(/\.cs-grounding-source-window \{[^}]*height: 88px;[^}]*overflow: hidden;/s);
    expect(sharedStyles).toMatch(/\.cs-grounding-source \{[^}]*min-height: 28px;/s);
    expect(conversationLayer).toMatch(
      /\.cs-grounding-source-list \{[^}]*height: calc\(var\(--cs-grounding-source-row\) \* var\(--cs-grounding-source-rows, 3\)/s,
    );
    expect(conversationLayer).toMatch(/\.cs-deck-kind \{[^}]*overflow: hidden;[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/s);
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
    expect(conversationLayer).toMatch(/\.cs-deck-disclosure-summary \{[^}]*min-height: 28px;/s);
    expect(conversationLayer).toMatch(/\.cs-deck-disclosure-summary:focus-visible \{[^}]*outline: 2px solid var\(--cs-steel\);/s);
    expect(conversationLayer).toMatch(
      /@media \(max-width: 640px\) \{\s*:is\([^)]*\.cs-deck-disclosure-summary\) \{\s*min-height: 44px;/,
    );
    expect(styles).toMatch(/\.deck-search button \{[^}]*width: 32px;[^}]*height: 32px;/s);
    expect(sharedStyles).toContain("--cs-deck-control-height: 32px;");
    expect(sharedStyles).toMatch(
      /\.cs-deck-tool-icon \{[^}]*width: var\(--cs-deck-control-height\);[^}]*height: var\(--cs-deck-control-height\);/s,
    );
    expect(sharedStyles).toMatch(/\.cs-deck-tool:focus-visible,\s*\.cs-deck-pill:focus-visible \{/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-search button \{ width: 44px; height: 44px; \}/);
    expect(sharedStyles).toMatch(/@media \(max-width: 720px\)[\s\S]*\.cs-deck-tool-icon \{ width: 44px; height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-transcript-tools \{ overflow-x: hidden; padding-inline: 12px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-transcript-tools button \{[^}]*min-height: 44px;[^}]*padding-inline: 6px;/s);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-layout-controls \{ display: none; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-input-row button \{ min-width: 44px; min-height: 44px; \}/);
    expect(conversationLayer).toMatch(
      /@media \(max-width: 640px\) \{\s*:is\([^)]*\.cs-deck-readiness-item[^)]*\) \{\s*min-height: 44px;/,
    );
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-search input \{ min-height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-input \{ min-height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-intro-card-grid \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/s);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-intro-card,[\s\S]*\.deck-overlay-mode-workspace \.deck-intro-card \{ min-height: 116px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-intro-card\.is-feature \{[^}]*grid-column: 1 \/ -1;[^}]*min-height: 132px;/s);
    expect(sidebarStyles).toMatch(/@media \(max-width: 780px\)[\s\S]*\.deck-overlay-mode-workspace \.deck-conversation-filter \{ min-height: 44px; \}/);
    expect(sidebarStyles).toMatch(/\.deck-overlay-mode-workspace \.deck-conversation-remove \{[^}]*width: 44px;[^}]*height: 44px;/s);
    expect(sidebarStyles).toMatch(/\.deck-overlay-mode-workspace \.deck-conversation-favorite \{[^}]*width: 44px;[^}]*height: 44px;/s);
  });

  test("keeps mobile header and composer compact", () => {
    expect(styles).toMatch(
      /@media \(max-width: 640px\)[\s\S]*grid-template-areas:\s*"title title actions window"\s*"model headline headline headline";/,
    );
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-header-action \{ width: 44px; height: 44px; \}/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*grid-template-columns: 120px minmax\(0, 1fr\) auto 44px;/);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-header-actions > \*, \.deck-header-action \{ flex: none; \}/);
    expect(styles).toMatch(
      /@media \(max-width: 640px\)[\s\S]*\.deck-composer-inner \{ grid-template-columns: auto minmax\(0, 1fr\) auto;/,
    );
    expect(styles).toContain("calc((100% - 1100px) / 2)");
    expect(styles).toContain("flex: 0 1 420px;");
    expect(styles).toContain(".deck-overlay.deck-overlay-mode-workspace { left: 0; }");
    expect(styles).toMatch(/\.deck-input \{[^}]*width: 100%;[^}]*min-width: 0;[^}]*box-sizing: border-box;/s);
    expect(styles).toMatch(/@media \(max-width: 640px\)[\s\S]*\.deck-investigation\.is-answer-settled \.deck-investigation-head \{[^}]*grid-template-columns: 16px minmax\(0, 1fr\) auto;/s);
    expect(conversationLayer).toMatch(
      /@container deck-transcript \(max-width: 620px\)[\s\S]*\.cs-deck-action-row > :is\(\.cs-deck-verification, :has\(> \.cs-deck-verification\)\) \{\s*flex: 1 0 100%;/,
    );
    expect(styles).toMatch(/@container deck-transcript \(max-width: 620px\)[\s\S]*\.deck-trajectory-phase-details > li \{ grid-template-columns: 20px minmax\(0, 1fr\); \}/);
    expect(styles).toMatch(/@media \(max-width: 1100px\)[\s\S]*\.deck-search kbd \{ display: none; \}/);
  });
});
