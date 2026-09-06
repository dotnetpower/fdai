import { Fragment, type RefObject } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { Tooltip } from "../components/tooltip";
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
import { CommandDeckLauncher } from "./command-deck-launcher";
import { CommandDeckHeader } from "./command-deck-header";
import { ComposerAttachments } from "./composer-attachments.view";
import { ConversationHistoryState } from "./conversation-history-state";
import { resumedConversationAt } from "./conversation-resume";
import { clampDockWidth, type DeckLayoutMode } from "./command-deck-session";
import { presentationTimestamp } from "./presentation-value";
import {
  investigationFlowHasTerminalAnswer,
  investigationFlowPosition,
} from "./investigation-turn-state";
import type { DeckSlashCommand } from "./command-deck-slash";
import type { ConversationSummary } from "./conversation-sessions";
import type { ConversationHydrationState } from "./use-command-deck-sessions";
import { conversationTrajectoriesByTurn } from "./conversation-trajectory";
import {
  clampConversationWidth,
  initialConversationWidth,
  saveConversationWidth,
} from "./conversation-sidebar-width";
import type { useViewContext } from "./context";
import type { DeckContextMode } from "./open-deck";
import { fetchHandoverGoal, updateHandoverGoal } from "../handover-api";
import { handoverText } from "./handover-i18n";
import { PendingReplyIndicator, RetrievalTrace } from "./retrieval-trace";
import { SourceReadinessStrip } from "./source-readiness-view";
import "./conversation-sidebar.css";
import { GeneralConversationIntro } from "./general-conversation-intro";

interface CommandDeckViewProps {
  readonly open: boolean;
  readonly contextMode: DeckContextMode;
  readonly layoutMode: DeckLayoutMode;
  readonly dragging: boolean;
  readonly routeLabel: string;
  readonly health: BackendHealth | null;
  readonly client: OperatorApiClient;
  readonly sessionLabel: string | null;
  readonly deckStyle: Record<string, string>;
  readonly dockWidth: number;
  readonly srStatus: string;
  readonly conversations: readonly ConversationSummary[];
  readonly conversationHasMore: boolean;
  readonly conversationHydration: ConversationHydrationState;
  readonly conversationPageLoading: boolean;
  readonly sessionKey: string;
  readonly currentPath: string;
  readonly turns: readonly Turn[];
  readonly snapshot: ReturnType<typeof useViewContext>;
  readonly canAttachScreen: boolean;
  readonly onAttachScreen: () => void;
  readonly onRemoveScreen: () => void;
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
  readonly onRetryConversation: () => void;
  readonly onSelectLayout: (mode: DeckLayoutMode) => void;
  readonly onRemoveConversation: (conversation: ConversationSummary) => void;
  readonly onToggleFavorite: (conversation: ConversationSummary) => void;
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
  contextMode,
  layoutMode,
  dragging,
  routeLabel,
  health,
  client,
  sessionLabel,
  deckStyle,
  dockWidth,
  srStatus,
  conversations,
  conversationHasMore,
  conversationHydration,
  conversationPageLoading,
  sessionKey,
  currentPath,
  turns,
  snapshot,
  canAttachScreen,
  onAttachScreen,
  onRemoveScreen,
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
  onRetryConversation,
  onSelectLayout,
  onRemoveConversation,
  onToggleFavorite,
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
  const trajectories = conversationTrajectoriesByTurn(turns);
  const [showModelTrace, setShowModelTrace] = useState(
    () => readConsolePreferences().showModelTrace,
  );
  useEffect(() => {
    const sync = () => setShowModelTrace(readConsolePreferences().showModelTrace);
    window.addEventListener(PREFERENCES_CHANGED_EVENT, sync);
    return () => window.removeEventListener(PREFERENCES_CHANGED_EVENT, sync);
  }, []);
  const [showConversations, setShowConversations] = useState(false);
  const beginNewConversation = () => {
    setShowConversations(false);
    onNewConversation();
  };
  const [conversationWidth, setConversationWidth] = useState(initialConversationWidth);
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
  const lastTurn = turns[turns.length - 1];
  const finalAnswerPresent = lastTurn?.role === "deck" &&
    lastTurn.kind !== "activity" && lastTurn.source !== "investigation" &&
    (lastTurn.streaming === true || lastTurn.terminal === true);
  const showPendingReply = pending && retrievalProgress === null && !finalAnswerPresent;
  const showPreparingAnswer = inFlight && retrievalProgress !== null && !finalAnswerPresent;
  const hydrationStatus = conversationHydration.key === sessionKey
    ? conversationHydration.status
    : "idle";
  const emptyConversation = turns.length === 0 && hydrationStatus === "idle";
  const centeredEmptyState = emptyConversation && layoutMode === "workspace";
  const activeConversation = conversations.find((conversation) => conversation.key === sessionKey);
  const handoverGoalId = /(?:^|:)handover:([a-f0-9]{64})$/.exec(sessionKey)?.[1];
  const [handoverStatus, setHandoverStatus] = useState("");
  const [handoverPending, setHandoverPending] = useState(false);
  const runHandoverCommand = async (operation: "snooze" | "decline") => {
    if (!handoverGoalId || handoverPending) return;
    setHandoverPending(true);
    try {
      const goal = await fetchHandoverGoal(client, handoverGoalId);
      await updateHandoverGoal(client, handoverGoalId, operation, goal.revision);
      setHandoverStatus(handoverText(operation === "snooze" ? "snoozeDone" : "declineDone"));
    } catch {
      setHandoverStatus(handoverText("commandFailed"));
    } finally {
      setHandoverPending(false);
    }
  };
  const conversationTitle = emptyConversation
    ? t(contextMode === "general" && !sessionLabel ? "deck.generalTitle" : "deck.newConversation")
    : activeConversation?.label ?? sessionLabel ?? t("deck.label");
  const contextLabel = contextMode === "general" ? t("deck.general") :
    snapshot?.routeLabel ?? t("deck.noScreenContext");
  const closeLabel = t(sessionLabel || activeConversation?.binding
    ? "deck.close"
    : contextMode === "general" ? "deck.generalClose" : "deck.screenClose");
  const activeOperatorIndex = turns.reduce(
    (latest, turn, index) => turn.role === "operator" ? index : latest,
    -1,
  );
  const conversationCount = conversationCountLabel(conversations.length, conversationHasMore);
  const showJumpToLatest = !stuck && turns.length > 0;
  const startConversationResize = (event: MouseEvent) => {
    if (layoutMode !== "workspace" || event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = conversationWidth;
    let latest = conversationWidth;
    const onMove = (moveEvent: MouseEvent) => {
      latest = clampConversationWidth(startWidth + moveEvent.clientX - startX);
      setConversationWidth(latest);
    };
    const onEnd = () => {
      saveConversationWidth(latest);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onEnd);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onEnd);
  };
  const resizeConversationWithKeyboard = (event: KeyboardEvent) => {
    if (layoutMode !== "workspace" ||
        (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    const next = clampConversationWidth(
      conversationWidth + (event.key === "ArrowLeft" ? -20 : 20),
    );
    setConversationWidth(next);
    saveConversationWidth(next);
  };
  const composer = (
    <DeckComposer
      centered={centeredEmptyState}
      routeLabel={contextLabel}
      contextMode={contextMode}
      snapshot={snapshot}
      canAttachScreen={canAttachScreen && !sessionLabel && !activeConversation?.binding}
      onAttachScreen={onAttachScreen}
      onRemoveScreen={onRemoveScreen}
      sessionKey={sessionKey}
      {...(handoverGoalId ? { handoverGoalId } : {})}
      {...(activeConversation?.agent ? { handoverAgent: activeConversation.agent } : {})}
      handoverStatus={handoverStatus}
      handoverPending={handoverPending}
      onHandoverSnooze={() => void runHandoverCommand("snooze")}
      onHandoverDecline={() => void runHandoverCommand("decline")}
      draft={draft}
      inFlight={inFlight}
      slashSuggestions={slashSuggestions}
      slashActiveIndex={slashActiveIndex}
      inputRef={inputRef}
      onSubmit={onSubmit}
      onRunSlashCommand={onRunSlashCommand}
      onSlashActiveIndex={onSlashActiveIndex}
      onDraftInput={onDraftInput}
      onInputKeyDown={onInputKeyDown}
      onStopStream={onStopStream}
    />
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
          class={`deck-overlay cs-deck-surface cs-deck-workspace-shell deck-overlay-mode-${layoutMode}${dragging ? " is-dragging" : ""}${centeredEmptyState ? " is-empty-conversation" : ""}`}
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
            conversationTitle={conversationTitle}
            routeLabel={contextLabel}
            closeLabel={closeLabel}
            sessionLabel={sessionLabel}
            health={health}
            searchAvailable={!emptyConversation}
            canStartNewConversation={!emptyConversation}
            conversationCount={conversationCount}
            conversationsOpen={showConversations}
            searchRef={searchRef}
            searchQuery={searchQuery}
            searchMatches={searchMatches}
            activeSearchMatch={activeSearchMatch}
            layoutMode={layoutMode}
            onFloatingDragStart={onFloatingDragStart}
            onOpenGeneral={onOpenGeneral}
            onSearchInput={onSearchInput}
            onMoveSearch={onMoveSearch}
            onNewConversation={beginNewConversation}
            onToggleConversations={() => setShowConversations((visible) => !visible)}
            onSelectLayout={onSelectLayout}
            onClose={onClose}
          />

          <div class="sr-only" role="status" aria-live="polite">
            {srStatus}
          </div>

          <div class="deck-source-readiness-slot cs-deck-source-readiness-slot">
            {contextMode === "screen" || !emptyConversation ? <SourceReadinessStrip client={client} /> : null}
          </div>

          <div
            class={`deck-body cs-deck-workspace-body${showConversations ? " has-conversations" : ""}`}
            style={`--deck-conversation-width: ${conversationWidth}px`}
          >
            {showConversations ? (
              <>
                <button
                  type="button"
                  class="deck-conversations-scrim cs-deck-conversation-scrim"
                  aria-label={t("deck.closeConversations")}
                  onClick={() => setShowConversations(false)}
                />
                <ConversationSidebar
                  conversations={conversations}
                  activeKey={sessionKey}
                  currentPath={currentPath}
                  hasMore={conversationHasMore}
                  loading={conversationPageLoading}
                  resizable={layoutMode === "workspace"}
                  width={conversationWidth}
                  onNew={beginNewConversation}
                  onDismiss={() => setShowConversations(false)}
                  onLoadMore={onLoadMoreConversations}
                  onRemove={onRemoveConversation}
                  onToggleFavorite={onToggleFavorite}
                  onSelect={onSelectConversation}
                  onResizeKeyDown={resizeConversationWithKeyboard}
                  onResizeStart={startConversationResize}
                />
              </>
            ) : null}
            <div class="deck-transcript-column cs-deck-transcript-column">
              {showJumpToLatest ? (
                <div class="deck-jump-slot">
                  <button
                    type="button"
                    class="deck-jump"
                    onClick={onJumpToLatest}
                    aria-label={t("deck.jumpLatestMessage")}
                  >
                    <span aria-hidden="true">↓</span> {t("deck.jumpLatest")}
                  </button>
                </div>
              ) : null}
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
              <div class={`deck-transcript-inner${centeredEmptyState ? " is-empty-conversation" : ""}`}>
              {resumedAt ? (
                <div class="deck-resume-banner" role="status">
                  <span>{t("deck.resumedConversation", {
                    time: resumedConversationTime(resumedAt),
                  })}</span>
                  <button type="button" onClick={beginNewConversation}>{t("deck.newConversation")}</button>
                </div>
              ) : null}
              {turns.length === 0 && hydrationStatus !== "idle" ? (
                <ConversationHistoryState
                  status={hydrationStatus}
                  onRetry={onRetryConversation}
                />
              ) : null}
              {emptyConversation && contextMode === "general" && !sessionLabel ? (
                <GeneralConversationIntro onPick={(prompt) => {
                  onDraftInput(prompt);
                  onSubmit(prompt);
                }}>
                  {centeredEmptyState ? composer : null}
                </GeneralConversationIntro>
              ) : emptyConversation ? (
                <IntroPanel
                  snapshot={snapshot}
                  routeLabel={contextLabel}
                  contextMode={contextMode}
                  onPick={onSubmit}
                >
                  {centeredEmptyState ? composer : null}
                </IntroPanel>
              ) : null}
              {turns.map((turn, index) => {
                const trajectory = trajectories.get(turn.id);
                const investigationFlow = investigationFlowPosition(turns, index);
                const investigationAnswerSettled = investigationFlowHasTerminalAnswer(
                  turns,
                  index,
                );
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
                    investigationAnswerSettled={investigationAnswerSettled}
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
                    ) : showPendingReply && index === activeOperatorIndex ? (
                      <PendingReplyIndicator />
                    ) : null}
                  </Fragment>
                );
              })}
              {pending && activeOperatorIndex < 0 ? (
                retrievalProgress ? (
                  <RetrievalTrace
                    snapshot={snapshot}
                    health={health}
                    progress={retrievalProgress}
                  />
                ) : (
                  <PendingReplyIndicator />
                )
              ) : null}
              </div>
              </section>
            </div>
          </div>

          {centeredEmptyState ? null : composer}
        </div>
      ) : null}
    </>
  );
}

type DeckComposerProps = Pick<CommandDeckViewProps,
  | "draft"
  | "inFlight"
  | "slashSuggestions"
  | "slashActiveIndex"
  | "inputRef"
  | "onSubmit"
  | "onRunSlashCommand"
  | "onSlashActiveIndex"
  | "onDraftInput"
  | "onInputKeyDown"
  | "onStopStream"
  | "sessionKey"
  | "contextMode"
  | "snapshot"
  | "canAttachScreen"
  | "onAttachScreen"
  | "onRemoveScreen"
> & {
  readonly centered: boolean;
  readonly routeLabel: string;
  readonly handoverGoalId?: string;
  readonly handoverAgent?: string;
  readonly handoverStatus: string;
  readonly handoverPending: boolean;
  readonly onHandoverSnooze: () => void;
  readonly onHandoverDecline: () => void;
};

function DeckComposer({
  centered,
  routeLabel,
  contextMode,
  snapshot,
  canAttachScreen,
  onAttachScreen,
  onRemoveScreen,
  sessionKey,
  handoverGoalId,
  handoverAgent,
  handoverStatus,
  handoverPending,
  onHandoverSnooze,
  onHandoverDecline,
  draft,
  inFlight,
  slashSuggestions,
  slashActiveIndex,
  inputRef,
  onSubmit,
  onRunSlashCommand,
  onSlashActiveIndex,
  onDraftInput,
  onInputKeyDown,
  onStopStream,
}: DeckComposerProps) {
  return (
    <form
      class={`deck-input-row cs-deck-composer-shell${centered ? " is-centered" : ""}`}
      onSubmit={(event) => {
        event.preventDefault();
        if (onRunSlashCommand(draft)) return;
        onSubmit(draft);
      }}
    >
      {snapshot || canAttachScreen ? (
        <div class="deck-composer-context">
          <Tooltip content={snapshot ? t("deck.removeScreenHint") : t("deck.attachScreenHint")} placement="top">
            <button
              type="button"
              class="deck-context-control"
              disabled={inFlight}
              onClick={snapshot ? onRemoveScreen : onAttachScreen}
              aria-label={snapshot
                ? t("deck.removeScreen", { route: snapshot.routeLabel })
                : t("deck.attachScreen")}
            >
              <span>{snapshot
                ? t("deck.attachedScreen", { route: snapshot.routeLabel })
                : t("deck.attachScreen")}</span>
              <span aria-hidden="true">{snapshot ? "×" : "+"}</span>
            </button>
          </Tooltip>
        </div>
      ) : null}
      <div class="deck-composer-inner cs-deck-composer-grid">
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
        {handoverGoalId && handoverAgent ? (
          <div class="deck-handover-actions">
            <a
              class="deck-handover-upload"
              href={`/documents?handover_goal=${encodeURIComponent(handoverGoalId)}`}
            >
              {handoverText("uploadDocument")}
            </a>
            <button type="button" disabled={handoverPending} onClick={onHandoverSnooze}>
              {handoverText("remindLater")}
            </button>
            <button type="button" disabled={handoverPending} onClick={onHandoverDecline}>
              {handoverText("decline")}
            </button>
            {handoverStatus ? <span role="status">{handoverStatus}</span> : null}
          </div>
        ) : null}
        <ComposerAttachments />
        <textarea
          ref={inputRef}
          class="deck-input cs-deck-composer-input"
          placeholder={t("deck.inputPlaceholder")}
          aria-label={contextMode === "general"
            ? t("deck.inputPlaceholder")
            : t("deck.inputPlaceholderContext", { route: routeLabel })}
          value={draft}
          rows={1}
          onInput={(event) => onDraftInput((event.target as HTMLTextAreaElement).value)}
          onKeyDown={onInputKeyDown}
        />
        <div class="deck-input-actions">
          {inFlight ? (
            <button
              type="button"
              class="deck-btn deck-btn-stop cs-deck-composer-send"
              onClick={onStopStream}
            >
              {t("deck.stop")}
            </button>
          ) : (
            <button
              type="submit"
              class="deck-btn deck-btn-primary cs-deck-composer-send"
              aria-label={t("deck.send")}
              disabled={draft.trim().length === 0}
            >
              <span class="deck-send-label">{t("deck.send")}</span>
              <svg class="deck-send-icon" aria-hidden="true" viewBox="0 0 24 24">
                <path d="M12 19 V5 M6 11 L12 5 L18 11" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </form>
  );
}

function resumedConversationTime(value: string): string {
  const timestamp = presentationTimestamp(value);
  return timestamp ? `${timestamp.date} ${timestamp.time}` : value;
}
