import { Fragment, type RefObject } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import {
  PREFERENCES_CHANGED_EVENT,
  readConsolePreferences,
} from "../preferences";
import type { BackendHealth, VerificationProgress } from "./backend";
import {
  conversationCountLabel,
  ConversationSidebar,
  IntroPanel,
  TurnBubble,
  type Turn,
} from "./command-deck-presenters";
import { DigestList } from "./command-deck-digest";
import { CommandDeckLauncher } from "./command-deck-launcher";
import { CommandDeckHeader } from "./command-deck-header";
import { ComposerAttachments } from "./composer-attachments.view";
import { ContextFreshnessIndicator } from "./context-freshness";
import { resumedConversationAt } from "./conversation-resume";
import { clampDockWidth, type DeckLayoutMode } from "./command-deck-session";
import { investigationFlowPosition } from "./investigation-turn-state";
import type { DeckSlashCommand } from "./command-deck-slash";
import type { ConversationSummary } from "./conversation-sessions";
import { conversationTrajectoriesByAnswer } from "./conversation-trajectory";
import type { useViewContext } from "./context";
import { RetrievalTrace } from "./retrieval-trace";

interface CommandDeckViewProps {
  readonly open: boolean;
  readonly layoutMode: DeckLayoutMode;
  readonly dragging: boolean;
  readonly routeLabel: string;
  readonly health: BackendHealth | null;
  readonly sessionLabel: string | null;
  readonly deckStyle: Record<string, string> | undefined;
  readonly dockWidth: number;
  readonly srStatus: string;
  readonly conversations: readonly ConversationSummary[];
  readonly conversationHasMore: boolean;
  readonly conversationPageLoading: boolean;
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
  readonly onLoadMoreConversations: () => void;
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
  health,
  sessionLabel,
  deckStyle,
  dockWidth,
  srStatus,
  conversations,
  conversationHasMore,
  conversationPageLoading,
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
  onLoadMoreConversations,
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
  const trajectories = conversationTrajectoriesByAnswer(turns);
  const [showModelTrace, setShowModelTrace] = useState(
    () => readConsolePreferences().showModelTrace,
  );
  useEffect(() => {
    const sync = () => setShowModelTrace(readConsolePreferences().showModelTrace);
    window.addEventListener(PREFERENCES_CHANGED_EVENT, sync);
    return () => window.removeEventListener(PREFERENCES_CHANGED_EVENT, sync);
  }, []);
  const [showConversations, setShowConversations] = useState(false);
  const [showDigest, setShowDigest] = useState(false);
  const openedAtRef = useRef(Date.now());
  const processedResumeKeysRef = useRef(new Set<string>());
  const [resumedAtBySession, setResumedAtBySession] = useState<Readonly<Record<string, string>>>({});
  useEffect(() => {
    if (turns.length === 0 || processedResumeKeysRef.current.has(sessionKey)) return;
    const resumedAt = resumedConversationAt(turns, openedAtRef.current);
    processedResumeKeysRef.current.add(sessionKey);
    if (resumedAt) {
      setResumedAtBySession((current) => ({ ...current, [sessionKey]: resumedAt }));
    }
  }, [sessionKey, turns]);
  const resumedAt = resumedAtBySession[sessionKey];
  const recordCount = snapshot?.records
    ? Object.values(snapshot.records).reduce((count, records) => count + records.length, 0)
    : 0;
  const lastTurn = turns[turns.length - 1];
  const finalAnswerPresent = lastTurn?.role === "deck" &&
    lastTurn.kind !== "activity" && lastTurn.source !== "investigation" &&
    (lastTurn.streaming === true || lastTurn.terminal === true);
  const showPreparingAnswer = inFlight && !finalAnswerPresent;
  const activeOperatorIndex = turns.reduce(
    (latest, turn, index) => turn.role === "operator" ? index : latest,
    -1,
  );
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

          <div class={`deck-body${showConversations ? " has-conversations" : ""}${showDigest ? " has-digest" : ""}`}>
            {showConversations ? (
              <ConversationSidebar
                conversations={conversations}
                activeKey={sessionKey}
                currentPath={currentPath}
                hasMore={conversationHasMore}
                loading={conversationPageLoading}
                onNew={onNewConversation}
                onLoadMore={onLoadMoreConversations}
                onRemove={onRemoveConversation}
                onSelect={onSelectConversation}
              />
            ) : null}
            <div class="deck-transcript-column">
              <div class="deck-transcript-tools" role="toolbar" aria-label={t("deck.workspaceTools")}>
                <button type="button" onClick={onNewConversation}>+ {t("deck.newConversation")}</button>
                <button
                  type="button"
                  aria-pressed={showConversations}
                  onClick={() => setShowConversations((visible) => !visible)}
                >
                  {t("deck.conversations")} <span>
                    {conversationCountLabel(conversations.length, conversationHasMore)}
                  </span>
                </button>
                <button
                  type="button"
                  class="deck-panel-toggle-context"
                  aria-pressed={showDigest}
                  onClick={() => setShowDigest((visible) => !visible)}
                >
                  {t("deck.digest.title")} <span>{recordCount}</span>
                </button>
              </div>
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
              <div class="deck-transcript-inner">
              {resumedAt ? (
                <div class="deck-resume-banner" role="status">
                  <span>{t("deck.resumedConversation", {
                    time: new Date(resumedAt).toLocaleString(),
                  })}</span>
                  <button type="button" onClick={onNewConversation}>{t("deck.newConversation")}</button>
                </div>
              ) : null}
              {turns.length === 0 ? (
                <IntroPanel snapshot={snapshot} onPick={onSubmit} />
              ) : null}
              {turns.map((turn, index) => {
                const trajectory = trajectories.get(turn.id);
                const investigationFlow = investigationFlowPosition(turns, index);
                const progressIndex = turn.kind === "message" && turn.source === "investigation"
                  ? turns.slice(0, index).filter((candidate) =>
                      candidate.kind === "message" && candidate.source === "investigation").length
                  : undefined;
                return (
                  <Fragment key={turn.id}>
                    <TurnBubble
                      turn={turn}
                    {...(trajectory ? { trajectory } : {})}
                    showModelTrace={showModelTrace}
                    searchMatch={searchMatches.includes(index)}
                    activeSearchMatch={searchMatches[activeSearchMatch] === index}
                    onPickFollowUp={onSubmit}
                    {...(progressIndex !== undefined ? { progressIndex } : {})}
                    investigationFlowContinuation={investigationFlow.continuation}
                    investigationFlowStart={investigationFlow.start}
                    investigationFlowEnd={investigationFlow.end}
                    {...(turn.role === "deck" &&
                      !turn.streaming &&
                      !inFlight &&
                      turns.slice(0, index).some((previous) => previous.role === "operator")
                      ? { onRegenerate: () => onRegenerate(index) }
                      : {})}
                    />
                    {showPreparingAnswer && index === activeOperatorIndex ? (
                      <RetrievalTrace
                        snapshot={snapshot}
                        health={health}
                        progress={retrievalProgress}
                      />
                    ) : null}
                  </Fragment>
                );
              })}
              {pending && activeOperatorIndex < 0 ? (
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
              </div>
              </section>
            </div>

            {showDigest ? <aside class="deck-digest" aria-label={t("deck.digest.label")}>
              <div class="deck-digest-header">
                <span class="deck-digest-title">{t("deck.digest.title")}</span>
                {snapshot ? <ContextFreshnessIndicator capturedAt={snapshot.capturedAt} /> : null}
              </div>
              <DigestList snapshot={snapshot} />
            </aside> : null}
          </div>

          <form
            class="deck-input-row"
            onSubmit={(event) => {
              event.preventDefault();
              if (onRunSlashCommand(draft)) return;
              onSubmit(draft);
            }}
          >
            <div class="deck-composer-inner">
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
                placeholder={t("deck.inputPlaceholderContext", { route: routeLabel })}
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
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}
