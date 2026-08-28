import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import {
  canHideNavigationGroup,
  displayedNavigationGroups,
  navigationGroupSelectionAction,
  nextMenuItemIndex,
  visibleNavigationGroups,
} from "./navigation-shell";
import { TOOLTIP_DELAY_MS, TOOLTIP_EXIT_MS } from "./tooltip";

const styles = readFileSync(fileURLToPath(new URL("../styles.css", import.meta.url)), "utf8");
const source = readFileSync(fileURLToPath(new URL("./navigation-shell.tsx", import.meta.url)), "utf8");

describe("navigation shell groups", () => {
  test("shows Labs only in development mode", () => {
    expect(visibleNavigationGroups(false).map((group) => group.id)).toEqual([
      "overview", "operations", "agents", "governance", "evidence", "settings",
    ]);
    expect(visibleNavigationGroups(true).map((group) => group.id)).toEqual([
      "overview", "operations", "agents", "governance", "evidence", "labs", "settings",
    ]);
  });

  test("hides optional groups while keeping Overview and Settings fixed", () => {
    const groups = visibleNavigationGroups(true);
    expect(displayedNavigationGroups(groups, ["operations", "overview", "settings"]).map(
      (group) => group.id,
    )).toEqual(["overview", "agents", "governance", "evidence", "labs", "settings"]);
    expect(canHideNavigationGroup("operations", "operations", [])).toBe(false);
    expect(canHideNavigationGroup("operations", "overview", [])).toBe(true);
    expect(canHideNavigationGroup("operations", "operations", ["operations"])).toBe(true);
    expect(canHideNavigationGroup("overview", "operations", [])).toBe(false);
    expect(canHideNavigationGroup("settings", "operations", [])).toBe(false);
  });

  test("keeps the mobile command deck launcher clear of the activity rail", () => {
    expect(styles).not.toContain(".deck-invoke,\n  .deck-overlay { left: 0; }");
    expect(styles).toContain(".deck-invoke { left: var(--rail-width); }");
    expect(styles).toContain(
      "height: calc(100dvh - var(--header-height) - var(--deck-invoke-height));",
    );
    expect(styles).toContain(".shell-body > main");
  });

  test("uses the shared portal tooltip instead of native activity-bar titles", () => {
    expect(source).toContain('<Tooltip content={group.label} placement="right">');
    expect(source).toContain('<Tooltip content={panel.label} placement="right">');
    expect(source).toContain('content={deckOpen ? t("deck.close") : t("deck.invoke")}');
    expect(source).not.toContain("title=");
    expect(styles).toContain('.app-tooltip[data-state="delayed-open"]');
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
  });

  test("toggles the Command Deck from the bottom utility rail without navigation", () => {
    expect(source).toContain("onClick={requestDeckToggle}");
    expect(source).toContain("aria-pressed={deckOpen}");
    expect(source).toContain('{chatIcon()}');
    expect(source).not.toContain('href={requestDeckToggle}');
  });

  test("keeps pointer entry deliberate and tooltip exit fast", () => {
    expect(TOOLTIP_DELAY_MS).toBe(100);
    expect(TOOLTIP_EXIT_MS).toBe(50);
  });

  test("toggles the selected group and opens a different group without navigation", () => {
    expect(navigationGroupSelectionAction("governance", "governance", true)).toEqual({
      explorerOpen: false,
    });
    expect(navigationGroupSelectionAction("governance", "governance", false)).toEqual({
      explorerOpen: true,
    });
    expect(navigationGroupSelectionAction("governance", "operations", false)).toEqual({
      explorerOpen: true,
    });
    expect(navigationGroupSelectionAction("governance", "governance", true, true)).toEqual({
      explorerOpen: true,
    });
    expect(source).not.toContain("navigate(workspacePath)");
  });

  test("exposes Explorer disclosure state on Activity Bar group buttons", () => {
    expect(source).toContain('aria-expanded={expanded}');
    expect(source).toContain('aria-controls="navigation-explorer"');
    expect(source).toContain('id="navigation-explorer"');
    expect(source).toContain('aria-hidden={!explorerOpen}');
    expect(source).toContain('inert={!explorerOpen}');
    expect(styles).toContain(
      ".navigation-shell-open,\n.navigation-shell-context-open { z-index: 90; }",
    );
    expect(source).not.toContain("aria-pressed={selected && preferences.explorerOpen}");
  });

  test("implements wrapping keyboard navigation for the action menu", () => {
    expect(nextMenuItemIndex(0, "ArrowDown", 3)).toBe(1);
    expect(nextMenuItemIndex(2, "ArrowDown", 3)).toBe(0);
    expect(nextMenuItemIndex(0, "ArrowUp", 3)).toBe(2);
    expect(nextMenuItemIndex(1, "Home", 3)).toBe(0);
    expect(nextMenuItemIndex(1, "End", 3)).toBe(2);
    expect(nextMenuItemIndex(1, "Enter", 3)).toBe(1);
  });

  test("exposes the activity bar menu by pointer and keyboard-accessible controls", () => {
    expect(source).toContain("onContextMenu={(event) =>");
    expect(source).toContain('aria-haspopup="menu"');
    expect(source).toContain('role="menuitemcheckbox"');
    expect(source).toContain('aria-checked={checked}');
    expect(source).toContain('"navigation-shell-context-open"');
    expect(source).toContain("updatePreferences({ ...preferences, hiddenGroupIds });\n    setActivityBarMenu(null);");
    expect(source).toContain("restoreActivityBar");
  });
});
