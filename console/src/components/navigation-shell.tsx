import { useEffect, useMemo, useRef, useState } from "preact/hooks";
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
import { groupIcon, settingsIcon } from "./rail-icons";

interface Props {
  readonly activePanelId: string;
  readonly principalId?: string | null;
  readonly devMode: boolean;
}

const MOBILE_QUERY = "(max-width: 720px)";

export function visibleNavigationGroups(devMode: boolean): readonly (typeof PANEL_GROUPS)[number][] {
  return PANEL_GROUPS.filter((group) => !group.devOnly || devMode);
}

export function NavigationShell({ activePanelId, principalId, devMode }: Props) {
  const panelIds = useMemo(() => resolvePanels().map((panel) => panel.id), []);
  const activePanel = panelForId(activePanelId);
  const activeGroup = activePanel.placement === "bottom" ? null : activePanel.group;
  const [selectedGroup, setSelectedGroup] = useState<PanelGroup>(activeGroup ?? "overview");
  const [preferences, setPreferences] = useState<NavigationPreferences>(() => {
    const stored = readNavigationPreferences(panelIds, principalId);
    return isMobile() ? { ...stored, explorerOpen: false } : stored;
  });
  const [editing, setEditing] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const groupRefs = useRef(new Map<PanelGroup, HTMLButtonElement | null>());
  const menuRef = useRef<HTMLDivElement | null>(null);
  const visibleGroups = useMemo(
    () => visibleNavigationGroups(devMode),
    [devMode],
  );

  useEffect(() => {
    if (activeGroup !== null) setSelectedGroup(activeGroup);
  }, [activeGroup]);

  useEffect(() => {
    const stored = readNavigationPreferences(panelIds, principalId);
    setPreferences(isMobile() ? { ...stored, explorerOpen: false } : stored);
    setEditing(false);
    setMenuOpen(false);
  }, [panelIds, principalId]);

  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== navigationPreferenceKey(principalId)) return;
      setPreferences(readNavigationPreferences(panelIds, principalId));
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [panelIds, principalId]);

  useEffect(() => {
    const onPointerDown = (event: PointerEvent) => {
      if (menuRef.current?.contains(event.target as Node)) return;
      setMenuOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
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
  }, []);

  const selectedMeta = PANEL_GROUPS.find((group) => group.id === selectedGroup)!;
  const orderedPanels = orderPanels(panelsInGroup(selectedGroup), preferences.groupOrder[selectedGroup]);
  const visiblePanels = orderedPanels.filter(
    (panel) => panel.id === activePanelId || !preferences.hiddenPanelIds.includes(panel.id),
  );
  const hiddenPanels = orderedPanels.filter(
    (panel) => panel.id !== activePanelId && preferences.hiddenPanelIds.includes(panel.id),
  );

  function updatePreferences(next: NavigationPreferences): void {
    setPreferences(next);
    writeNavigationPreferences(next, principalId);
  }

  function setExplorerOpen(explorerOpen: boolean): void {
    updatePreferences({ ...preferences, explorerOpen });
    if (!explorerOpen) {
      setEditing(false);
      setMenuOpen(false);
    }
  }

  function selectGroup(group: PanelGroup): void {
    if (group === selectedGroup && preferences.explorerOpen) {
      setExplorerOpen(false);
      return;
    }
    setSelectedGroup(group);
    setExplorerOpen(true);
  }

  function focusGroup(from: PanelGroup, delta: number): void {
    const index = visibleGroups.findIndex((group) => group.id === from);
    const next = visibleGroups[(index + delta + visibleGroups.length) % visibleGroups.length];
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
    setEditing(false);
    setMenuOpen(false);
  }

  const renderGroupButton = (group: (typeof PANEL_GROUPS)[number]) => {
    const selected = group.id === selectedGroup;
    const label = selected && preferences.explorerOpen
      ? t("nav.hideGroup", { group: group.label })
      : group.label;
    return (
      <li key={group.id}>
        <button
          ref={(element) => { groupRefs.current.set(group.id, element); }}
          type="button"
          class={`activity-bar-button ${selected ? "active" : ""}`}
          aria-label={label}
          aria-pressed={selected && preferences.explorerOpen}
          title={label}
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
      </li>
    );
  };

  return (
    <div class={`navigation-shell ${preferences.explorerOpen ? "" : "navigation-shell-closed"}`}>
      <nav class="activity-bar" aria-label={t("nav.primaryLabel")}>
        <ul class="activity-bar-list">
          {visibleGroups.filter((group) => group.placement !== "bottom").map(renderGroupButton)}
        </ul>
        <ul class="activity-bar-list activity-bar-bottom">
          {visibleGroups.filter((group) => group.placement === "bottom").map(renderGroupButton)}
          {bottomRailPanels().map((panel) => (
            <li key={panel.id}>
              <a
                href={panelPath(panel.id)}
                class={`activity-bar-button ${activePanelId === panel.id ? "active" : ""}`}
                aria-label={panel.label}
                aria-current={activePanelId === panel.id ? "page" : undefined}
                title={panel.label}
                onClick={() => setExplorerOpen(false)}
              >
                <span aria-hidden="true">{panel.id === "settings" ? settingsIcon() : null}</span>
              </a>
            </li>
          ))}
        </ul>
      </nav>

      <aside class={`navigation-explorer ${editing ? "editing" : ""}`} aria-label={t("nav.explorerLabel")}>
        <header class="navigation-explorer-head">
          <div>
            <strong>{selectedMeta.label}</strong>
            <small>{selectedMeta.hint}</small>
          </div>
          <div ref={menuRef} class="navigation-more-wrap">
            <button
              type="button"
              class="navigation-icon-button"
              aria-label={t("nav.moreActions")}
              aria-expanded={menuOpen}
              title={t("nav.moreActions")}
              onClick={(event) => {
                event.stopPropagation();
                setMenuOpen((open) => !open);
              }}
            >
              ...
            </button>
            {menuOpen ? (
              <div class="navigation-more-menu" role="menu">
                <button type="button" role="menuitem" onClick={() => { setEditing(true); setMenuOpen(false); }}>
                  {t("nav.customize")}
                </button>
                <button type="button" role="menuitem" onClick={() => setExplorerOpen(false)}>
                  <span>{t("nav.hideNavigation")}</span>
                </button>
                <button type="button" role="menuitem" onClick={resetMenu}>{t("nav.reset")}</button>
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
                      <button
                        type="button"
                        class="navigation-drag-handle"
                        aria-label={t("nav.reorder", { panel: panel.label })}
                        title={t("nav.reorderHint")}
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
                    ) : null}
                    <a
                      href={panelPath(panel.id)}
                      aria-current={panel.id === activePanelId ? "page" : undefined}
                      onClick={() => { if (isMobile()) setExplorerOpen(false); }}
                    >
                      {panel.label}
                    </a>
                    {editing ? (
                      <button
                        type="button"
                        class="navigation-row-action"
                        disabled={panel.id === activePanelId}
                        aria-label={t("nav.hidePanel", { panel: panel.label })}
                        title={panel.id === activePanelId ? t("nav.hideActiveDisabled") : t("nav.hidePanel", { panel: panel.label })}
                        onClick={() => hidePanel(panel.id)}
                      >
                        <span aria-hidden="true">⊘</span>
                      </button>
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
                      <button
                        type="button"
                        class="navigation-row-action"
                        aria-label={t("nav.showPanel", { panel: panel.label })}
                        title={t("nav.showPanel", { panel: panel.label })}
                        onClick={() => showPanel(panel.id)}
                      >
                        <span aria-hidden="true">↶</span>
                      </button>
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

function isMobile(): boolean {
  return typeof window !== "undefined" && window.matchMedia(MOBILE_QUERY).matches;
}

function clearDragClasses(...classNames: readonly string[]): void {
  for (const className of classNames) {
    document.querySelectorAll(`.${className}`).forEach((element) => element.classList.remove(className));
  }
}
