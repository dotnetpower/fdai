import type { RefObject } from "preact";
import { t } from "../i18n";
import type { BackendHealth, VerificationProgress } from "./backend";
import {
  ConversationSidebar,
  IntroPanel,
  TurnBubble,
  type Turn,
} from "./command-deck-presenters";
import { DigestList } from "./command-deck-digest";
import { CommandDeckLauncher } from "./command-deck-launcher";
import { CommandDeckHeader } from "./command-deck-header";
import { ComposerAttachments } from "./composer-attachments.view";
import { clampDockWidth, type DeckLayoutMode } from "./command-deck-session";
import type { DeckSlashCommand } from "./command-deck-slash";
import type { ConversationSummary } from "./conversation-sessions";
import type { useViewContext } from "./context";
import { RetrievalTrace } from "./retrieval-trace";

interface CommandDeckViewProps {
  readonly open: boolean;
  readonly layoutMode: DeckLayoutMode;
  readonly dragging: boolean;
  readonly routeLabel: string;
  readonly headline: string;
  readonly health: BackendHealth | null;
  readonly sessionLabel: string | null;
  readonly deckStyle: Record<string, string> | undefined;
  readonly dockWidth: number;
  readonly srStatus: string;
  readonly conversations: readonly ConversationSummary[];
  readonly sessionKey: string;
  readonly currentPath: string;
  readonly turns: readonly Turn[];
  readonly snapshot: ReturnType<typeof useViewContext>;
  readonly pending: boolean;
  readonly retrievalProgress: VerificationProgress | null;
  readonly stuck: boolean;
  readonly inFlight: boolean;
  readonly searchQuery: string;
  readonly searchMatches: readonly number[];
  readonly activeSearchMatch: number;
  readonly draft: string;
  readonly slashSuggestions: readonly DeckSlashCommand[];
  readonly slashActiveIndex: number;
  readonly overlayRef: RefObject<HTMLDivElement>;
  readonly searchRef: RefObject<HTMLInputElement>;
  readonly scrollerRef: RefObject<HTMLDivElement>;
  readonly inputRef: RefObject<HTMLTextAreaElement>;
  readonly onInvoke: () => void;
  readonly onClose: () => void;
  readonly onOpenGeneral: () => void;
  readonly onOverlayKeyDown: (event: KeyboardEvent) => void;
  readonly onDockResizeStart: (event: MouseEvent) => void;
  readonly onDockResizeKeyDown: (event: KeyboardEvent) => void;
  readonly onFloatingDragStart: (event: MouseEvent) => void;
  readonly onSearchInput: (value: string) => void;
  readonly onMoveSearch: (direction: -1 | 1) => void;
  readonly onNewConversation: () => void;
  readonly onSelectLayout: (mode: DeckLayoutMode) => void;
  readonly onRemoveConversation: (conversation: ConversationSummary) => void;
  readonly onSelectConversation: (conversation: ConversationSummary) => void;
  readonly onTranscriptScroll: () => void;
  readonly onSubmit: (text: string) => void;
  readonly onRegenerate: (turnIndex: number) => void;
  readonly onJumpToLatest: () => void;
  readonly onRunSlashCommand: (input: string) => boolean;
  readonly onSlashActiveIndex: (index: number) => void;
  readonly onDraftInput: (value: string) => void;
  readonly onInputKeyDown: (event: KeyboardEvent) => void;
  readonly onStopStream: () => void;
}

export function CommandDeckView({
  open,
  layoutMode,
  dragging,
  routeLabel,
  headline,
  health,
  sessionLabel,
  deckStyle,
  dockWidth,
  srStatus,
  conversations,
  sessionKey,
  currentPath,
  turns,
  snapshot,
  pending,
  retrievalProgress,
  stuck,
  inFlight,
  searchQuery,
  searchMatches,
  activeSearchMatch,
  draft,
  slashSuggestions,
  slashActiveIndex,
  overlayRef,
  searchRef,
  scrollerRef,
  inputRef,
  onInvoke,
  onClose,
  onOpenGeneral,
  onOverlayKeyDown,
  onDockResizeStart,
  onDockResizeKeyDown,
  onFloatingDragStart,
  onSearchInput,
  onMoveSearch,
  onNewConversation,
  onSelectLayout,
  onRemoveConversation,
  onSelectConversation,
  onTranscriptScroll,
  onSubmit,
  onRegenerate,
  onJumpToLatest,
  onRunSlashCommand,
  onSlashActiveIndex,
  onDraftInput,
  onInputKeyDown,
  onStopStream,
}: CommandDeckViewProps) {
  return (
    <>
      <CommandDeckLauncher
        open={open}
        routeLabel={routeLabel}
        health={health}
        onInvoke={onInvoke}
      />

      {open ? (
        <div
          class={`deck-overlay deck-overlay-mode-${layoutMode}${dragging ? " is-dragging" : ""}`}
          role={layoutMode === "workspace" ? "dialog" : "complementary"}
          aria-modal={layoutMode === "workspace" ? "true" : undefined}
          aria-label={t("deck.label")}
          ref={overlayRef}
          style={deckStyle}
          onKeyDown={onOverlayKeyDown}
        >
          <button
            type="button"
            class="deck-dock-resize-handle"
            role="separator"
            aria-label={t("deck.resizeRightSidebar")}
            aria-orientation="vertical"
            aria-valuemin={340}
            aria-valuemax={clampDockWidth(720, typeof window === "undefined" ? 1440 : window.innerWidth)}
            aria-valuenow={dockWidth}
            onMouseDown={onDockResizeStart}
            onKeyDown={onDockResizeKeyDown}
          >
            <span /><span /><span />
          </button>
          <CommandDeckHeader
            routeLabel={routeLabel}
            sessionLabel={sessionLabel}
            health={health}
            headline={headline}
            searchRef={searchRef}
            searchQuery={searchQuery}
            searchMatches={searchMatches}
            activeSearchMatch={activeSearchMatch}
            layoutMode={layoutMode}
            onFloatingDragStart={onFloatingDragStart}
            onOpenGeneral={onOpenGeneral}
            onSearchInput={onSearchInput}
            onMoveSearch={onMoveSearch}
            onNewConversation={onNewConversation}
            onSelectLayout={onSelectLayout}
            onClose={onClose}
          />

          <div class="sr-only" role="status" aria-live="polite">
            {srStatus}
          </div>

          <div class="deck-body">
            <ConversationSidebar
              conversations={conversations}
              activeKey={sessionKey}
              currentPath={currentPath}
              onNew={onNewConversation}
              onRemove={onRemoveConversation}
              onSelect={onSelectConversation}
            />
            <section
              class="deck-transcript"
              ref={scrollerRef}
              aria-label={t("deck.conversation")}
              role="log"
              aria-live="polite"
              aria-relevant="additions"
              aria-busy={pending}
              onScroll={onTranscriptScroll}
            >
              {turns.length === 0 ? (
                <IntroPanel snapshot={snapshot} onPick={onSubmit} />
              ) : null}
              {turns.map((turn, index) => (
                <TurnBubble
                  key={turn.id}
                  turn={turn}
                  searchMatch={searchMatches.includes(index)}
                  activeSearchMatch={searchMatches[activeSearchMatch] === index}
                  onPickFollowUp={onSubmit}
                  {...(turn.role === "deck" &&
                    !turn.streaming &&
                    !inFlight &&
                    turns.slice(0, index).some((previous) => previous.role === "operator")
                    ? { onRegenerate: () => onRegenerate(index) }
                    : {})}
                />
              ))}
              {pending ? (
                <RetrievalTrace
                  snapshot={snapshot}
                  health={health}
                  progress={retrievalProgress}
                />
              ) : null}
              {!stuck && turns.length > 0 ? (
                <button
                  type="button"
                  class="deck-jump"
                  onClick={onJumpToLatest}
                  aria-label={t("deck.jumpLatest")}
                >
                  {t("deck.jumpLatest")} ↓
                </button>
              ) : null}
            </section>

            <aside class="deck-digest" aria-label={t("deck.digest.label")}>
              <div class="deck-digest-header">
                <span class="deck-digest-title">{t("deck.digest.title")}</span>
                <span class="deck-digest-meta muted">
                  {snapshot ? new Date(snapshot.capturedAt).toLocaleTimeString() : "-"}
                </span>
              </div>
              <DigestList snapshot={snapshot} />
            </aside>
          </div>

          <form
            class="deck-input-row"
            onSubmit={(event) => {
              event.preventDefault();
              if (onRunSlashCommand(draft)) return;
              onSubmit(draft);
            }}
          >
            {slashSuggestions.length > 0 ? (
              <ul class="deck-slash-palette" aria-label={t("deck.slashCommands")}>
                {slashSuggestions.map((command, index) => (
                  <li key={command.name}>
                    <button
                      type="button"
                      class={`deck-slash-item${index === slashActiveIndex ? " is-active" : ""}`}
                      onMouseEnter={() => onSlashActiveIndex(index)}
                      onMouseDown={(event) => {
                        event.preventDefault();
                        onRunSlashCommand(`/${command.name}`);
                      }}
                    >
                      <span class="deck-slash-name">/{command.name}</span>
                      <span class="deck-slash-summary muted">{command.summary}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            <ComposerAttachments />
            <textarea
              ref={inputRef}
              class="deck-input"
              placeholder={t("deck.inputPlaceholder")}
              value={draft}
              rows={1}
              onInput={(event) => onDraftInput((event.target as HTMLTextAreaElement).value)}
              onKeyDown={onInputKeyDown}
            />
            <div class="deck-input-actions">
              {inFlight ? (
                <button
                  type="button"
                  class="deck-btn deck-btn-stop"
                  onClick={onStopStream}
                >
                  {t("deck.stop")}
                </button>
              ) : (
                <button
                  type="submit"
                  class="deck-btn deck-btn-primary"
                  disabled={draft.trim().length === 0}
                >
                  {t("deck.send")}
                </button>
              )}
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}
