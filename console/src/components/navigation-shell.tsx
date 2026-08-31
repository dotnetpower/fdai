import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  DECK_STATE_EVENT,
  isDeckOpen,
  requestDeckToggle,
} from "../deck/open-deck";
import { t } from "../i18n";
import {
  DEFAULT_NAVIGATION_PREFERENCES,
  navigationPreferenceKey,
  readNavigationPreferences,
  resetNavigationPreferences,
  writeNavigationPreferences,
  type NavigationPreferences,
} from "../navigation-preferences";
import {
  bottomRailPanels,
  panelForId,
  PANEL_GROUPS,
  panelsInGroup,
  resolvePanels,
  type ConsolePanel,
  type PanelGroup,
} from "../panels";
import { panelPath } from "../router";
import { chatIcon, groupIcon, moreIcon, pinIcon, settingsIcon } from "./rail-icons";
import { Tooltip } from "./tooltip";

interface Props {
  readonly activePanelId: string;
  readonly client: OperatorApiClient;
  readonly principalId?: string | null;
  readonly devMode: boolean;
  readonly explorerOpen: boolean;
  readonly onExplorerOpenChange: (open: boolean) => void;
}

interface GroupSelectionAction {
  readonly explorerOpen: boolean;
}

interface ActivityBarMenuPosition {
  readonly left: number;
  readonly top: number;
}

const MOBILE_QUERY = "(max-width: 720px)";
const FIXED_GROUP_IDS = new Set<PanelGroup>(["overview", "settings"]);
const ACTIVITY_BAR_MENU_WIDTH = 224;
const ACTIVITY_BAR_MENU_MARGIN = 8;
const ACTIVITY_BAR_MENU_ITEM_HEIGHT = 34;

export function visibleNavigationGroups(devMode: boolean): readonly (typeof PANEL_GROUPS)[number][] {
  return PANEL_GROUPS.filter((group) => !group.devOnly || devMode);
}

export function NavigationShell({
  activePanelId,
  client,
  principalId,
  devMode,
  explorerOpen,
  onExplorerOpenChange,
}: Props) {
  const panelIds = useMemo(() => resolvePanels().map((panel) => panel.id), []);
  const activePanel = panelForId(activePanelId);
  const activeGroup = activePanel.placement === "bottom" ? null : activePanel.group;
  const [selectedGroup, setSelectedGroup] = useState<PanelGroup>(activeGroup ?? "overview");
  const [preferences, setPreferences] = useState<NavigationPreferences>(
    () => readNavigationPreferences(panelIds, principalId),
  );
  const [mobile, setMobile] = useState(isMobile);
  const [editing, setEditing] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activityBarMenu, setActivityBarMenu] = useState<ActivityBarMenuPosition | null>(null);
  const [deckOpen, setDeckOpen] = useState(isDeckOpen);
  const shellRef = useRef<HTMLDivElement | null>(null);
  const activityBarMenuRef = useRef<HTMLDivElement | null>(null);
  const activityBarMenuButtonRef = useRef<HTMLButtonElement | null>(null);
  const activityBarMenuItemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const groupRefs = useRef(new Map<PanelGroup, HTMLButtonElement | null>());
  const menuRef = useRef<HTMLDivElement | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const menuItemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const visibleGroups = useMemo(
    () => visibleNavigationGroups(devMode),
    [devMode],
  );
  const displayedGroups = useMemo(
    () => displayedNavigationGroups(visibleGroups, preferences.hiddenGroupIds),
    [preferences.hiddenGroupIds, visibleGroups],
  );
  const explorerPinned = preferences.explorerPinned && !mobile;

  useEffect(() => {
    if (activeGroup !== null) setSelectedGroup(activeGroup);
  }, [activeGroup]);

  useEffect(() => {
    const stored = readNavigationPreferences(panelIds, principalId);
    setPreferences(stored);
    onExplorerOpenChange(stored.explorerPinned && !isMobile());
    setEditing(false);
    setMenuOpen(false);
    setActivityBarMenu(null);
  }, [onExplorerOpenChange, panelIds, principalId]);

  useEffect(() => {
    const media = window.matchMedia(MOBILE_QUERY);
    const onChange = (event: MediaQueryListEvent) => {
      setMobile(event.matches);
      if (event.matches) {
        onExplorerOpenChange(false);
        setEditing(false);
        setMenuOpen(false);
        setActivityBarMenu(null);
      }
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [onExplorerOpenChange]);

  useEffect(() => {
    const onDeckState = (event: Event) => {
      setDeckOpen((event as CustomEvent<{ readonly open: boolean }>).detail.open);
    };
    window.addEventListener(DECK_STATE_EVENT, onDeckState);
    return () => window.removeEventListener(DECK_STATE_EVENT, onDeckState);
  }, []);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== navigationPreferenceKey(principalId)) return;
      const stored = readNavigationPreferences(panelIds, principalId);
      setPreferences(stored);
      if (stored.explorerPinned && !mobile) onExplorerOpenChange(true);
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [mobile, onExplorerOpenChange, panelIds, principalId]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node;
      if (
        menuRef.current?.contains(target) ||
        activityBarMenuRef.current?.contains(target) ||
        activityBarMenuButtonRef.current?.contains(target)
      ) return;
      setMenuOpen(false);
      setActivityBarMenu(null);
      if (!explorerPinned && explorerOpen && !shellRef.current?.contains(target)) {
        onExplorerOpenChange(false);
        setEditing(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (activityBarMenu !== null) {
          window.requestAnimationFrame(() => activityBarMenuButtonRef.current?.focus());
          setActivityBarMenu(null);
        } else if (menuOpen) {
          window.requestAnimationFrame(() => menuButtonRef.current?.focus());
        } else if (!explorerPinned && explorerOpen) {
          window.requestAnimationFrame(() => groupRefs.current.get(selectedGroup)?.focus());
          onExplorerOpenChange(false);
        }
        setMenuOpen(false);
        setEditing(false);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [
    activityBarMenu,
    explorerOpen,
    explorerPinned,
    menuOpen,
    onExplorerOpenChange,
    selectedGroup,
  ]);

  useEffect(() => {
    if (menuOpen) window.requestAnimationFrame(() => menuItemRefs.current[0]?.focus());
  }, [menuOpen]);

  useLayoutEffect(() => {
    if (activityBarMenu === null) return;
    activityBarMenuRef.current
      ?.querySelector<HTMLButtonElement>("button:not(:disabled)")
      ?.focus();
  }, [activityBarMenu]);

  const selectedMeta = PANEL_GROUPS.find((group) => group.id === selectedGroup)!;
  const eligiblePanels = panelsInGroup(selectedGroup);
  const orderedPanels = orderPanels(eligiblePanels, preferences.groupOrder[selectedGroup]);
  const visiblePanels = orderedPanels.filter(
    (panel) => panel.id === activePanelId || !preferences.hiddenPanelIds.includes(panel.id),
  );
  const hiddenPanels = orderedPanels.filter(
    (panel) => panel.id !== activePanelId && preferences.hiddenPanelIds.includes(panel.id),
  );
  const firstActivityBarMenuIndex = visibleGroups.findIndex((group) =>
    canHideNavigationGroup(group.id, activeGroup, preferences.hiddenGroupIds));

  function updatePreferences(next: NavigationPreferences): void {
    setPreferences(next);
    writeNavigationPreferences(next, principalId);
  }

  function setExplorerOpen(open: boolean): void {
    onExplorerOpenChange(open);
    if (!open) {
      setEditing(false);
      setMenuOpen(false);
    }
  }

  function selectGroup(group: PanelGroup): void {
    const action = navigationGroupSelectionAction(
      selectedGroup,
      group,
      explorerOpen,
      explorerPinned,
    );
    if (!action.explorerOpen) {
      setExplorerOpen(false);
      return;
    }
    setSelectedGroup(group);
    setExplorerOpen(true);
  }

  function focusGroup(from: PanelGroup, delta: number): void {
    const index = displayedGroups.findIndex((group) => group.id === from);
    const next = displayedGroups[(index + delta + displayedGroups.length) % displayedGroups.length];
    if (next === undefined) return;
    groupRefs.current.get(next.id)?.focus();
  }

  function hidePanel(panelId: string): void {
    if (panelId === activePanelId) return;
    updatePreferences({
      ...preferences,
      hiddenPanelIds: [...new Set([...preferences.hiddenPanelIds, panelId])],
    });
  }

  function toggleExplorerPinned(): void {
    updatePreferences({ ...preferences, explorerPinned: !preferences.explorerPinned });
    setExplorerOpen(true);
  }

  function openActivityBarMenu(left: number, top: number): void {
    const estimatedHeight = visibleGroups.length * ACTIVITY_BAR_MENU_ITEM_HEIGHT + 48;
    const boundedHeight = Math.min(estimatedHeight, window.innerHeight - 2 * ACTIVITY_BAR_MENU_MARGIN);
    setActivityBarMenu({
      left: Math.max(
        ACTIVITY_BAR_MENU_MARGIN,
        Math.min(left, window.innerWidth - ACTIVITY_BAR_MENU_WIDTH - ACTIVITY_BAR_MENU_MARGIN),
      ),
      top: Math.max(
        ACTIVITY_BAR_MENU_MARGIN,
        Math.min(top, window.innerHeight - boundedHeight - ACTIVITY_BAR_MENU_MARGIN),
      ),
    });
    setMenuOpen(false);
  }

  function openActivityBarMenuFromButton(): void {
    if (activityBarMenu !== null) {
      setActivityBarMenu(null);
      return;
    }
    const bounds = activityBarMenuButtonRef.current?.getBoundingClientRect();
    if (bounds === undefined) return;
    openActivityBarMenu(bounds.right + 6, bounds.bottom);
  }

  function toggleGroupVisibility(group: PanelGroup): void {
    if (!canHideNavigationGroup(group, activeGroup, preferences.hiddenGroupIds)) return;
    const hidden = preferences.hiddenGroupIds.includes(group);
    const hiddenGroupIds = hidden
      ? preferences.hiddenGroupIds.filter((id) => id !== group)
      : [...preferences.hiddenGroupIds, group];
    updatePreferences({ ...preferences, hiddenGroupIds });
    setActivityBarMenu(null);
    if (!hidden && selectedGroup === group) {
      setSelectedGroup(activeGroup ?? "overview");
      setExplorerOpen(false);
    }
  }

  function restoreActivityBar(): void {
    updatePreferences({ ...preferences, hiddenGroupIds: [] });
    setActivityBarMenu(null);
  }

  function showPanel(panelId: string): void {
    updatePreferences({
      ...preferences,
      hiddenPanelIds: preferences.hiddenPanelIds.filter((id) => id !== panelId),
    });
  }

  function saveVisibleOrder(panelIdsInOrder: readonly string[]): void {
    const hiddenIds = orderedPanels
      .map((panel) => panel.id)
      .filter((id) => preferences.hiddenPanelIds.includes(id));
    updatePreferences({
      ...preferences,
      groupOrder: {
        ...preferences.groupOrder,
        [selectedGroup]: [...panelIdsInOrder, ...hiddenIds],
      },
    });
  }

  function reorderPanel(sourceId: string, targetId: string, after: boolean): void {
    if (sourceId === targetId) return;
    const ids = visiblePanels.map((panel) => panel.id);
    const sourceIndex = ids.indexOf(sourceId);
    if (sourceIndex < 0) return;
    ids.splice(sourceIndex, 1);
    let targetIndex = ids.indexOf(targetId);
    if (targetIndex < 0) return;
    if (after) targetIndex += 1;
    ids.splice(targetIndex, 0, sourceId);
    saveVisibleOrder(ids);
  }

  function movePanel(panelId: string, delta: number): void {
    const ids = visiblePanels.map((panel) => panel.id);
    const sourceIndex = ids.indexOf(panelId);
    const targetIndex = Math.max(0, Math.min(ids.length - 1, sourceIndex + delta));
    if (sourceIndex < 0 || sourceIndex === targetIndex) return;
    ids.splice(sourceIndex, 1);
    ids.splice(targetIndex, 0, panelId);
    saveVisibleOrder(ids);
  }

  function startDrag(event: PointerEvent, panelId: string): void {
    if (event.button !== 0) return;
    event.preventDefault();
    const handle = event.currentTarget as HTMLButtonElement;
    const sourceRow = handle.closest<HTMLElement>("[data-nav-panel-id]");
    let currentTarget: { panelId: string; after: boolean } | null = null;
    sourceRow?.classList.add("dragging");

    const onMove = (moveEvent: PointerEvent) => {
      clearDragClasses("drop-before", "drop-after");
      const row = (document.elementFromPoint(moveEvent.clientX, moveEvent.clientY) as Element | null)
        ?.closest<HTMLElement>("[data-nav-panel-id]");
      if (row == null || row.dataset.navPanelId === panelId) {
        currentTarget = null;
        return;
      }
      const bounds = row.getBoundingClientRect();
      currentTarget = {
        panelId: row.dataset.navPanelId!,
        after: moveEvent.clientY > bounds.top + bounds.height / 2,
      };
      row.classList.add(currentTarget.after ? "drop-after" : "drop-before");
    };
    const onEnd = () => {
      if (currentTarget !== null) reorderPanel(panelId, currentTarget.panelId, currentTarget.after);
      clearDragClasses("dragging", "drop-before", "drop-after");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onEnd);
      window.removeEventListener("pointercancel", onEnd);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onEnd);
    window.addEventListener("pointercancel", onEnd);
  }

  function resetMenu(): void {
    resetNavigationPreferences(principalId);
    setPreferences(DEFAULT_NAVIGATION_PREFERENCES);
    setExplorerOpen(false);
    setEditing(false);
    setMenuOpen(false);
  }

  const renderGroupButton = (group: (typeof PANEL_GROUPS)[number]) => {
    const expanded = group.id === selectedGroup && explorerOpen;
    return (
      <li key={group.id}>
        <Tooltip content={group.label} placement="right">
          <button
            ref={(element) => { groupRefs.current.set(group.id, element); }}
            type="button"
            class={`activity-bar-button ${expanded ? "active" : ""}`}
            aria-label={group.label}
            aria-expanded={expanded}
            aria-controls="navigation-explorer"
            onClick={() => selectGroup(group.id)}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                focusGroup(group.id, 1);
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                focusGroup(group.id, -1);
              }
            }}
          >
            <span aria-hidden="true">{groupIcon(group.id)}</span>
          </button>
        </Tooltip>
      </li>
    );
  };

  return (
    <div
      ref={shellRef}
      class={[
        "navigation-shell",
        explorerOpen ? "navigation-shell-open" : "",
        explorerPinned ? "navigation-shell-pinned" : "",
        activityBarMenu !== null ? "navigation-shell-context-open" : "",
      ].filter(Boolean).join(" ")}
    >
      <nav
        class="activity-bar"
        aria-label={t("nav.primaryLabel")}
        onContextMenu={(event) => {
          event.preventDefault();
          openActivityBarMenu(event.clientX, event.clientY);
        }}
      >
        <ul class="activity-bar-list">
          {displayedGroups.filter((group) => group.placement !== "bottom").map(renderGroupButton)}
        </ul>
        <ul class="activity-bar-list activity-bar-bottom">
          <li>
            <Tooltip content={t("nav.customizeActivityBar")} placement="right">
              <button
                ref={activityBarMenuButtonRef}
                type="button"
                class="activity-bar-button"
                aria-label={t("nav.customizeActivityBar")}
                aria-haspopup="menu"
                aria-expanded={activityBarMenu !== null}
                onClick={openActivityBarMenuFromButton}
              >
                <span aria-hidden="true">{moreIcon()}</span>
              </button>
            </Tooltip>
          </li>
          <li>
            <Tooltip content={deckOpen ? t("deck.close") : t("deck.invoke")} placement="right">
              <button
                type="button"
                class={`activity-bar-button ${deckOpen ? "active" : ""}`}
                aria-label={deckOpen ? t("deck.close") : t("deck.invoke")}
                aria-pressed={deckOpen}
                onClick={requestDeckToggle}
              >
                <span aria-hidden="true">{chatIcon()}</span>
              </button>
            </Tooltip>
          </li>
          {displayedGroups.filter((group) => group.placement === "bottom").map(renderGroupButton)}
          {bottomRailPanels().map((panel) => (
            <li key={panel.id}>
              <Tooltip content={panel.label} placement="right">
                <a
                  href={panelPath(panel.id)}
                  class={`activity-bar-button ${activePanelId === panel.id ? "active" : ""}`}
                  aria-label={panel.label}
                  aria-current={activePanelId === panel.id ? "page" : undefined}
                  onClick={() => setExplorerOpen(false)}
                >
                  <span aria-hidden="true">{panel.id === "settings" ? settingsIcon() : null}</span>
                </a>
              </Tooltip>
            </li>
          ))}
        </ul>
      </nav>
      {activityBarMenu !== null ? (
        <div
          ref={activityBarMenuRef}
          class="activity-bar-context-menu"
          role="menu"
          aria-label={t("nav.activityBarMenu")}
          style={{ left: activityBarMenu.left, top: activityBarMenu.top }}
        >
          {visibleGroups.map((group, index) => {
            const checked = !preferences.hiddenGroupIds.includes(group.id);
            const fixed = FIXED_GROUP_IDS.has(group.id);
            const current = activeGroup === group.id && checked;
            return (
              <button
                key={group.id}
                ref={(element) => { activityBarMenuItemRefs.current[index] = element; }}
                type="button"
                role="menuitemcheckbox"
                aria-checked={checked}
                disabled={fixed || current}
                autoFocus={index === firstActivityBarMenuIndex}
                onKeyDown={(event) =>
                  focusMenuItem(event, index, activityBarMenuItemRefs.current)}
                onClick={() => toggleGroupVisibility(group.id)}
              >
                <span class="activity-bar-menu-check" aria-hidden="true">
                  {checked ? "✓" : ""}
                </span>
                <span>{group.label}</span>
                {fixed
                  ? <small>{t("nav.alwaysShown")}</small>
                  : current
                    ? <small>{t("nav.currentGroup")}</small>
                    : null}
              </button>
            );
          })}
          <div class="activity-bar-menu-separator" role="separator" />
          <button
            ref={(element) => {
              activityBarMenuItemRefs.current[visibleGroups.length] = element;
            }}
            type="button"
            role="menuitem"
            onKeyDown={(event) =>
              focusMenuItem(event, visibleGroups.length, activityBarMenuItemRefs.current)}
            onClick={restoreActivityBar}
          >
            <span class="activity-bar-menu-check" aria-hidden="true" />
            <span>{t("nav.restoreActivityBar")}</span>
          </button>
        </div>
      ) : null}

      <aside
        id="navigation-explorer"
        class={`navigation-explorer ${editing ? "editing" : ""}`}
        aria-label={t("nav.explorerLabel")}
        aria-hidden={!explorerOpen}
        inert={!explorerOpen}
      >
        <header class="navigation-explorer-head">
          <div>
            <strong>{selectedMeta.label}</strong>
            <small>{selectedMeta.hint}</small>
          </div>
          <Tooltip
            content={explorerPinned ? t("nav.unpinNavigation") : t("nav.pinNavigation")}
            placement="bottom"
          >
            <button
              type="button"
              class="navigation-icon-button navigation-pin-button"
              aria-label={explorerPinned ? t("nav.unpinNavigation") : t("nav.pinNavigation")}
              aria-pressed={explorerPinned}
              onClick={toggleExplorerPinned}
            >
              <span aria-hidden="true">{pinIcon(explorerPinned)}</span>
            </button>
          </Tooltip>
          <div ref={menuRef} class="navigation-more-wrap">
            <Tooltip content={t("nav.moreActions")} placement="bottom">
              <button
                ref={menuButtonRef}
                type="button"
                class="navigation-icon-button"
                aria-label={t("nav.moreActions")}
                aria-expanded={menuOpen}
                aria-haspopup="menu"
                onClick={(event) => {
                  event.stopPropagation();
                  setMenuOpen((open) => !open);
                }}
              >
                ...
              </button>
            </Tooltip>
            {menuOpen ? (
              <div class="navigation-more-menu" role="menu" aria-label={t("nav.moreActions")}>
                <button
                  ref={(element) => { menuItemRefs.current[0] = element; }}
                  type="button"
                  role="menuitem"
                  onKeyDown={(event) => focusMenuItem(event, 0, menuItemRefs.current)}
                  onClick={() => { setEditing(true); setMenuOpen(false); }}
                >
                  {t("nav.customize")}
                </button>
                <button
                  ref={(element) => { menuItemRefs.current[1] = element; }}
                  type="button"
                  role="menuitem"
                  onKeyDown={(event) => focusMenuItem(event, 1, menuItemRefs.current)}
                  onClick={() => setExplorerOpen(false)}
                >
                  <span>{t("nav.hideNavigation")}</span>
                </button>
                <button
                  ref={(element) => { menuItemRefs.current[2] = element; }}
                  type="button"
                  role="menuitem"
                  onKeyDown={(event) => focusMenuItem(event, 2, menuItemRefs.current)}
                  onClick={resetMenu}
                >
                  {t("nav.reset")}
                </button>
              </div>
            ) : null}
          </div>
        </header>

        <div class="navigation-explorer-scroll">
          <section class="navigation-section">
            <header><span>{selectedMeta.label}</span><small>{editing ? t("nav.visible") : t("nav.menu")}</small></header>
            <ul>
              {visiblePanels.map((panel) => {
                return (
                  <li
                    key={panel.id}
                    data-nav-panel-id={panel.id}
                    class={`navigation-row ${panel.id === activePanelId ? "active" : ""}`}
                  >
                    {editing ? (
                      <Tooltip content={t("nav.reorderHint")} placement="right">
                        <button
                          type="button"
                          class="navigation-drag-handle"
                          aria-label={t("nav.reorder", { panel: panel.label })}
                          onPointerDown={(event) => startDrag(event, panel.id)}
                          onKeyDown={(event) => {
                            if (!event.altKey) return;
                            if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                              event.preventDefault();
                              movePanel(panel.id, event.key === "ArrowUp" ? -1 : 1);
                            }
                          }}
                        >
                          <span aria-hidden="true">::</span>
                        </button>
                      </Tooltip>
                    ) : null}
                    <a
                      href={panelPath(panel.id)}
                      aria-current={panel.id === activePanelId ? "page" : undefined}
                      onClick={() => {
                        if (mobile || !explorerPinned) setExplorerOpen(false);
                      }}
                    >
                      {panel.label}
                    </a>
                    {editing ? (
                      <Tooltip
                        content={panel.id === activePanelId
                          ? t("nav.hideActiveDisabled")
                          : t("nav.hidePanel", { panel: panel.label })}
                        placement="left"
                      >
                        <button
                          type="button"
                          class="navigation-row-action"
                          disabled={panel.id === activePanelId}
                          aria-label={t("nav.hidePanel", { panel: panel.label })}
                          onClick={() => hidePanel(panel.id)}
                        >
                          <span aria-hidden="true">⊘</span>
                        </button>
                      </Tooltip>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </section>

          {editing ? (
            <section class="navigation-section navigation-hidden-section">
              <header><span>{t("nav.hidden")}</span><small>{hiddenPanels.length}</small></header>
              {hiddenPanels.length === 0 ? <p>{t("nav.noHidden")}</p> : (
                <ul>
                  {hiddenPanels.map((panel) => (
                    <li key={panel.id} class="navigation-row hidden">
                      <span>{panel.label}</span>
                      <Tooltip content={t("nav.showPanel", { panel: panel.label })} placement="left">
                        <button
                          type="button"
                          class="navigation-row-action"
                          aria-label={t("nav.showPanel", { panel: panel.label })}
                          onClick={() => showPanel(panel.id)}
                        >
                          <span aria-hidden="true">↶</span>
                        </button>
                      </Tooltip>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          ) : null}
        </div>

        {editing ? (
          <footer class="navigation-editor-footer">
            <button type="button" onClick={resetMenu}>{t("nav.reset")}</button>
            <button type="button" class="primary" onClick={() => setEditing(false)}>{t("nav.done")}</button>
          </footer>
        ) : null}
      </aside>
    </div>
  );
}

function orderPanels(
  panels: readonly ConsolePanel[],
  order: readonly string[] | undefined,
): readonly ConsolePanel[] {
  if (order === undefined) return panels;
  const positions = new Map(order.map((id, index) => [id, index]));
  return [...panels].sort((left, right) =>
    (positions.get(left.id) ?? Number.MAX_SAFE_INTEGER) -
    (positions.get(right.id) ?? Number.MAX_SAFE_INTEGER),
  );
}

export function navigationGroupSelectionAction(
  selectedGroup: PanelGroup,
  requestedGroup: PanelGroup,
  explorerOpen: boolean,
  explorerPinned = false,
): GroupSelectionAction {
  if (selectedGroup === requestedGroup) {
    return { explorerOpen: explorerPinned || !explorerOpen };
  }
  return { explorerOpen: true };
}

export function displayedNavigationGroups(
  groups: readonly (typeof PANEL_GROUPS)[number][],
  hiddenGroupIds: readonly PanelGroup[],
): readonly (typeof PANEL_GROUPS)[number][] {
  const hidden = new Set(hiddenGroupIds);
  return groups.filter((group) => FIXED_GROUP_IDS.has(group.id) || !hidden.has(group.id));
}

export function canHideNavigationGroup(
  group: PanelGroup,
  activeGroup: PanelGroup | null,
  hiddenGroupIds: readonly PanelGroup[],
): boolean {
  return !FIXED_GROUP_IDS.has(group) &&
    (activeGroup !== group || hiddenGroupIds.includes(group));
}

function isMobile(): boolean {
  return typeof window !== "undefined" && window.matchMedia(MOBILE_QUERY).matches;
}

function clearDragClasses(...classNames: readonly string[]): void {
  for (const className of classNames) {
    document.querySelectorAll(`.${className}`).forEach((element) => element.classList.remove(className));
  }
}

export function nextMenuItemIndex(index: number, key: string, count: number): number {
  if (count <= 0) return index;
  if (key === "ArrowDown") return (index + 1) % count;
  if (key === "ArrowUp") return (index - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return index;
}

function focusMenuItem(
  event: KeyboardEvent,
  index: number,
  items: readonly (HTMLButtonElement | null)[],
): void {
  if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
  event.preventDefault();
  const direction = event.key === "ArrowUp" || event.key === "End" ? -1 : 1;
  let next = nextMenuItemIndex(index, event.key, items.length);
  for (let attempt = 0; attempt < items.length; attempt += 1) {
    const item = items[next];
    if (item !== null && item !== undefined && !item.disabled) {
      item.focus();
      return;
    }
    next = (next + direction + items.length) % items.length;
  }
}
