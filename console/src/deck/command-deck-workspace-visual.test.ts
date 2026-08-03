import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const source = readFileSync(
  fileURLToPath(new URL("./command-deck-view.tsx", import.meta.url)),
  "utf8",
);

describe("Command Deck workspace hierarchy", () => {
  test("opens transcript-first and adds columns only for requested panels", () => {
    expect(source).toContain("const [showConversations, setShowConversations] = useState(false);");
    expect(source).toContain("const [showDigest, setShowDigest] = useState(false);");
    expect(styles).toContain(".deck-body.has-conversations { grid-template-columns: 210px minmax(0, 1fr); }");
    expect(styles).toContain(".deck-body.has-digest { grid-template-columns: minmax(0, 1fr) 280px; }");
  });

  test("does not reserve a hidden digest column on narrow screens", () => {
    expect(styles).toContain(".deck-body.has-digest { grid-template-columns: minmax(0, 1fr); }");
    expect(styles).toContain(".deck-panel-toggle-context { display: none; }");
    expect(styles).not.toContain(".deck-body { min-width: 0; grid-template-columns: 200px minmax(0, 1fr); }");
  });

  test("does not retain hidden workspace panel columns after a layout change", () => {
    expect(styles).toContain(".deck-overlay-mode-floating .deck-body.has-conversations,");
    expect(styles).toContain(".deck-overlay-mode-floating .deck-body.has-digest,");
    expect(styles).toContain(".deck-overlay-mode-dock .deck-body.has-conversations,");
    expect(styles).toContain(".deck-overlay-mode-dock .deck-body.has-digest { grid-template-columns: minmax(0, 1fr); }");
  });

  test("keeps route and freshness metadata out of the composer", () => {
    expect(source).not.toContain('class="deck-composer-scope"');
    expect(styles).not.toContain(".deck-composer-scope");
    expect(source).toContain("<CommandDeckHeader");
    expect(source).toContain("routeLabel={routeLabel}");
    expect(source).toContain('class="deck-digest-header"');
  });

  test("keeps readable metadata at 12px and keyboard focus visible", () => {
    expect(styles).toContain(".deck-turn-time,\n.deck-code-lang,");
    expect(styles).toContain("font-size: 12px;\n}");
    expect(styles).toContain(".deck-btn:focus-visible,");
    expect(styles).toContain("outline: 2px solid var(--accent);");
    expect(styles).toContain(".deck-conversation-select:focus-visible {");
    expect(styles).toContain(".deck-input:focus-visible {");
  });

  test("reflows execution details from the deck container width", () => {
    expect(styles).toContain("container-name: deck-transcript;");
    expect(styles).toContain("@container deck-transcript (max-width: 620px)");
    expect(styles).toContain("grid-template-columns: 58px minmax(0, 1fr) auto 9px;");
  });
});
