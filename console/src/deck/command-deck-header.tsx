import type { RefObject } from "preact";
import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";
import type { BackendHealth } from "./backend";
import { BackendBadge, DeckLayoutIcon } from "./command-deck-presenters";
import type { DeckLayoutMode } from "./command-deck-session";

export function CommandDeckHeader({
  routeLabel,
  sessionLabel,
  health,
  headline,
  searchRef,
  searchQuery,
  searchMatches,
  activeSearchMatch,
  layoutMode,
  onFloatingDragStart,
  onOpenGeneral,
  onSearchInput,
  onMoveSearch,
  onNewConversation,
  onSelectLayout,
  onClose,
}: {
  readonly routeLabel: string;
  readonly sessionLabel: string | null;
  readonly health: BackendHealth | null;
  readonly headline: string;
  readonly searchRef: RefObject<HTMLInputElement>;
  readonly searchQuery: string;
  readonly searchMatches: readonly number[];
  readonly activeSearchMatch: number;
  readonly layoutMode: DeckLayoutMode;
  readonly onFloatingDragStart: (event: MouseEvent) => void;
  readonly onOpenGeneral: () => void;
  readonly onSearchInput: (value: string) => void;
  readonly onMoveSearch: (direction: -1 | 1) => void;
  readonly onNewConversation: () => void;
  readonly onSelectLayout: (mode: DeckLayoutMode) => void;
  readonly onClose: () => void;
}) {
  return (
    <div class="deck-header">
      <div class="deck-header-title" onMouseDown={onFloatingDragStart}>
        <span class="deck-header-glyph" aria-hidden="true">
          <svg viewBox="0 0 16 16" width="14" height="14">
            <path
              d="M3 2.75h10a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5H7L3.5 14v-2.25H3a1.5 1.5 0 0 1-1.5-1.5v-6A1.5 1.5 0 0 1 3 2.75Z"
              fill="none"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </span>
        <span>{t("deck.label")}</span>
        <span class="deck-header-sep muted">·</span>
        <span class="deck-header-route">{routeLabel}</span>
        {sessionLabel && (
          <>
            <Tooltip content={t("deck.tooltip.chattingWith", { session: sessionLabel })}>
              <span class="deck-session-chip">{sessionLabel}</span>
            </Tooltip>
            <Tooltip content={t("deck.tooltip.backToGeneral")}>
              <button type="button" class="deck-session-exit" onClick={onOpenGeneral}>
                {t("deck.general")}
              </button>
            </Tooltip>
          </>
        )}
        <BackendBadge health={health} placement="header" />
      </div>
      <div class="deck-header-center">
        <div class="deck-header-headline muted">{headline}</div>
        <div class="deck-search" role="search">
          <span class="deck-search-icon" aria-hidden="true">⌕</span>
          <input
            ref={searchRef}
            type="search"
            value={searchQuery}
            placeholder={t("deck.searchPlaceholder")}
            aria-label={t("deck.searchConversation")}
            onInput={(event) => onSearchInput((event.target as HTMLInputElement).value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                onMoveSearch(event.shiftKey ? -1 : 1);
              }
            }}
          />
          <span class="deck-search-count" aria-live="polite">
            {searchQuery.trim()
              ? `${searchMatches.length === 0 ? 0 : activeSearchMatch + 1}/${searchMatches.length}`
              : ""}
          </span>
          <button
            type="button"
            onClick={() => onMoveSearch(-1)}
            disabled={searchMatches.length === 0}
            aria-label={t("deck.previousMatch")}
          >
            ↑
          </button>
          <button
            type="button"
            onClick={() => onMoveSearch(1)}
            disabled={searchMatches.length === 0}
            aria-label={t("deck.nextMatch")}
          >
            ↓
          </button>
          <kbd>{navigator.platform.toLowerCase().includes("mac") ? "⌘K" : "Ctrl K"}</kbd>
        </div>
      </div>
      <span class="deck-header-new-slot">
        <Tooltip content={t("deck.newConversation")}>
          <button
            type="button"
            class="deck-header-new"
            onClick={onNewConversation}
            aria-label={t("deck.newConversation")}
          >
            <span class="deck-header-new-glyph" aria-hidden="true">+</span>
            <span class="deck-header-new-label">{t("deck.newConversation")}</span>
          </button>
        </Tooltip>
      </span>
      <div class="deck-layout-controls" aria-label={t("deck.layout")}>
        <Tooltip content={t("deck.tooltip.floatingPanel")}>
          <button
            type="button"
            class="deck-layout-button"
            aria-label={t("deck.tooltip.floatingPanel")}
            aria-pressed={layoutMode === "floating"}
            onClick={() => onSelectLayout("floating")}
          >
            <DeckLayoutIcon mode="floating" />
          </button>
        </Tooltip>
        <Tooltip content={t("deck.tooltip.dockRight")}>
          <button
            type="button"
            class="deck-layout-button"
            aria-label={t("deck.tooltip.dockRight")}
            aria-pressed={layoutMode === "dock"}
            onClick={() => onSelectLayout("dock")}
          >
            <DeckLayoutIcon mode="dock" />
          </button>
        </Tooltip>
        <Tooltip content={t("deck.tooltip.fullWorkspace")}>
          <button
            type="button"
            class="deck-layout-button"
            aria-label={t("deck.tooltip.fullWorkspace")}
            aria-pressed={layoutMode === "workspace"}
            onClick={() => onSelectLayout("workspace")}
          >
            <DeckLayoutIcon mode="workspace" />
          </button>
        </Tooltip>
      </div>
      <button type="button" class="deck-close" onClick={onClose} aria-label={t("deck.close")}>
        ×
      </button>
    </div>
  );
}
