import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test, vi } from "vitest";
import { DEFAULT_NAVIGATION_PREFERENCES } from "../navigation-preferences";
import {
  firstVisiblePanelInGroup,
  navigationGroupSelectionAction,
  nextMenuItemIndex,
  visibleNavigationGroups,
  workspaceGroupNavigationPath,
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
    expect(source).not.toContain("title=");
    expect(styles).toContain('.app-tooltip[data-state="delayed-open"]');
    expect(styles).toContain("@media (prefers-reduced-motion: reduce)");
  });

  test("keeps pointer entry deliberate and tooltip exit fast", () => {
    expect(TOOLTIP_DELAY_MS).toBe(100);
    expect(TOOLTIP_EXIT_MS).toBe(50);
  });

  test("resolves the first visible child page using the operator's group order", () => {
    expect(firstVisiblePanelInGroup("operations", DEFAULT_NAVIGATION_PREFERENCES)?.id)
      .toBe("live");
    expect(firstVisiblePanelInGroup("operations", {
      ...DEFAULT_NAVIGATION_PREFERENCES,
      groupOrder: {
        ...DEFAULT_NAVIGATION_PREFERENCES.groupOrder,
        operations: ["incidents", "live"],
      },
      hiddenPanelIds: ["incidents"],
    })?.id).toBe("live");
  });

  test("navigates to the first child whether or not a workspace Deck closes", () => {
    const accepted = vi.fn(() => true);
    const ignored = vi.fn(() => false);

    expect(workspaceGroupNavigationPath(
      "operations",
      DEFAULT_NAVIGATION_PREFERENCES,
      accepted,
    )).toBe("/live");
    expect(workspaceGroupNavigationPath(
      "operations",
      DEFAULT_NAVIGATION_PREFERENCES,
      ignored,
    )).toBe("/live");
    expect(accepted).toHaveBeenCalledOnce();
    expect(ignored).toHaveBeenCalledOnce();
  });

  test("toggles the selected group without navigating and opens a different group", () => {
    expect(navigationGroupSelectionAction("governance", "governance", true)).toEqual({
      explorerOpen: false,
      navigate: false,
    });
    expect(navigationGroupSelectionAction("governance", "governance", false)).toEqual({
      explorerOpen: true,
      navigate: false,
    });
    expect(navigationGroupSelectionAction("governance", "operations", false)).toEqual({
      explorerOpen: true,
      navigate: true,
    });
  });

  test("exposes Explorer disclosure state on Activity Bar group buttons", () => {
    expect(source).toContain('aria-expanded={expanded}');
    expect(source).toContain('aria-controls="navigation-explorer"');
    expect(source).toContain('id="navigation-explorer"');
    expect(source).toContain('aria-hidden={!preferences.explorerOpen}');
    expect(source).toContain('inert={!preferences.explorerOpen}');
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
});
