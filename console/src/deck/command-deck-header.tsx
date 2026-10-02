import type { RefObject } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { Tooltip } from "../components/tooltip";
import { t } from "../i18n";
import type { BackendHealth } from "./backend";
import { BackendBadge, DeckLayoutIcon } from "./command-deck-presenters";
import type { DeckLayoutMode } from "./command-deck-session";
import type {
  ConversationModelAvailability,
  ConversationModelTier,
} from "./conversation-model-selection";
import {
  conversationModelText,
  conversationT2Label,
} from "./conversation-model-i18n";

export function CommandDeckHeader({
  conversationTitle,
  routeLabel,
  sessionLabel,
  health,
  conversationModelTier,
  conversationModelAvailability,
  modelSelectionDisabled,
  searchAvailable,
  canStartNewConversation,
  conversationCount,
  conversationsOpen,
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
  onToggleConversations,
  onSelectLayout,
  onClose,
  onConversationModelTier,
  closeLabel = t("deck.close"),
}: {
  readonly conversationTitle: string;
  readonly routeLabel: string;
  readonly sessionLabel: string | null;
  readonly health: BackendHealth | null;
  readonly conversationModelTier: ConversationModelTier;
  readonly conversationModelAvailability: ConversationModelAvailability;
  readonly modelSelectionDisabled: boolean;
  readonly searchAvailable: boolean;
  readonly canStartNewConversation: boolean;
  readonly conversationCount: string;
  readonly conversationsOpen: boolean;
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
  readonly onToggleConversations: () => void;
  readonly onSelectLayout: (mode: DeckLayoutMode) => void;
  readonly onClose: () => void;
  readonly onConversationModelTier: (tier: ConversationModelTier) => boolean;
  readonly closeLabel?: string;
}) {
  const [searchOpen, setSearchOpen] = useState(false);
  const searchToggle = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const input = searchRef.current;
    if (!input || !searchAvailable) return;
    const showSearch = () => {
      setSearchOpen(true);
      requestAnimationFrame(() => {
        input.focus();
        input.select();
      });
    };
    input.addEventListener("fdai-deck-search", showSearch);
    return () => input.removeEventListener("fdai-deck-search", showSearch);
  }, [searchAvailable, searchRef]);

  return (
    <div class="deck-header cs-deck-workspace-header" data-search-open={searchOpen ? "true" : "false"}>
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
        <span class="deck-header-copy">
          <strong class="deck-header-conversation-title">{conversationTitle}</strong>
          <span class="deck-header-route">{routeLabel}</span>
        </span>
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
      <label class="deck-model-selector">
        <span class="sr-only">{conversationModelText("label")}</span>
        <Tooltip content={conversationModelText("hint")}>
          <select
            value={conversationModelTier}
            disabled={modelSelectionDisabled}
            aria-label={conversationModelText("label")}
            style={{ maxWidth: "164px" }}
            onChange={(event) => {
              const accepted = onConversationModelTier(
                event.currentTarget.value as ConversationModelTier,
              );
              if (!accepted) event.currentTarget.value = conversationModelTier;
            }}
          >
            <option value="auto">{conversationModelText("auto")}</option>
            <option value="t1">{conversationModelText("t1")}</option>
            <option value="t2" disabled={!conversationModelAvailability.t2Available}>
              {conversationModelAvailability.t2Available
                ? conversationT2Label(conversationModelAvailability.t2Label ?? "T2")
                : conversationModelText("t2Unavailable")}
            </option>
          </select>
        </Tooltip>
      </label>
      <div class="deck-header-center">
        {searchAvailable ? <div class="deck-search" role="search">
          <span class="deck-search-icon" aria-hidden="true">⌕</span>
          <input
            ref={searchRef}
            type="search"
            value={searchQuery}
            placeholder={t("deck.searchPlaceholder")}
            aria-label={t("deck.searchConversation")}
            onInput={(event) => onSearchInput((event.target as HTMLInputElement).value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                event.stopPropagation();
                onSearchInput("");
                setSearchOpen(false);
                searchToggle.current?.focus();
                return;
              }
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
        </div> : null}
      </div>
      <div class="deck-header-actions">
        {searchAvailable ? (
          <Tooltip content={t("deck.searchConversation")}>
            <button type="button" class="deck-header-action deck-search-toggle" ref={searchToggle} aria-label={t("deck.searchConversation")} aria-expanded={searchOpen} onClick={() => {
              setSearchOpen(!searchOpen);
              if (!searchOpen) requestAnimationFrame(() => searchRef.current?.focus());
            }}>
              <span aria-hidden="true">⌕</span>
            </button>
          </Tooltip>
        ) : null}
        {canStartNewConversation ? (
          <Tooltip content={t("deck.newConversation")}>
            <button
              type="button"
              class="deck-header-action"
              onClick={onNewConversation}
              aria-label={t("deck.newConversation")}
            >
              <HeaderActionIcon kind="new" />
            </button>
          </Tooltip>
        ) : null}
        <Tooltip content={`${t("deck.conversations")} ${conversationCount}`}>
          <button
            type="button"
            class="deck-header-action deck-header-history"
            aria-label={`${t("deck.conversations")} ${conversationCount}`}
            aria-pressed={conversationsOpen}
            onClick={onToggleConversations}
          >
            <HeaderActionIcon kind="history" />
            <span class="deck-header-action-count">{conversationCount}</span>
          </button>
        </Tooltip>
      </div>
      <div class="deck-window-controls">
        <div class="deck-layout-controls" aria-label={t("deck.layoutControls")}>
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
        <Tooltip content={closeLabel}>
          <button type="button" class="deck-close" onClick={onClose} aria-label={closeLabel}>
            <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M6 6 L18 18 M18 6 L6 18" /></svg>
          </button>
        </Tooltip>
      </div>
    </div>
  );
}

function HeaderActionIcon({ kind }: { readonly kind: "new" | "history" }) {
  if (kind === "new") {
    return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M12 5 V19 M5 12 H19" /></svg>;
  }
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M3 12 A9 9 0 1 0 6 5.3 M3 4 V10 H9 M12 7 V12 L15 14" /></svg>;
}
