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
    expect(source).toContain('class="deck-header-actions"');
    expect(source).toContain('class="deck-header-action deck-header-history"');
    expect(source).toContain('class="deck-window-controls"');
    expect(styles).toContain('grid-template-areas: "title center actions window";');
    expect(styles).toContain('grid-template-areas: "title actions window";');
    expect(styles).toContain(".deck-header-actions {\n  grid-area: actions;");
  });

  test("uses the shared localized tooltip for the close control", () => {
    expect(source).toContain('<Tooltip content={closeLabel}>');
    expect(source).toContain('class="deck-close" onClick={onClose} aria-label={closeLabel}');
    expect(source).toContain('class="deck-window-controls"');
    expect(styles).toContain(".deck-window-controls {\n  grid-area: window;");
    expect(styles).toMatch(/\.deck-overlay-mode-workspace \.deck-header \{[^}]*padding: 6px 12px 6px max\(20px, calc\(\(100% - 1100px\) \/ 2\)\);/s);
  });

  test("separates conversation identity from route context and hides empty search", () => {
    expect(source).toContain('class="deck-header-copy"');
    expect(source).toContain('class="deck-header-conversation-title"');
    expect(source).toContain('{searchAvailable ? <div class="deck-search" role="search">');
    expect(source).toContain('class="deck-header-action"');
    expect(source).toContain('aria-pressed={conversationsOpen}');
    expect(styles).toContain(".deck-backend-header.deck-backend-ready .deck-backend-label { display: none; }");
  });
});
