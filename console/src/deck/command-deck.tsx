/**
 * CommandDeck - a screen-aware conversational surface.
 *
 * Design goals (deliberately NOT a corner bubble):
 * - Always visible as a slim bar pinned to the bottom of the viewport,
 *   inviting a question. Cmd+K / Ctrl+K / `/` focuses it.
 * - On focus it expands into a full-viewport overlay split into two
 *   columns: the transcript on the left, the "what I see" digest on
 *   the right. This is the "overwhelming" gesture - the deck is not a
 *   pop-up, it is the operator workspace momentarily.
 * - The right column shows the current ViewSnapshot, so the operator
 *   literally sees what the assistant grounds its answers on. Nothing
 *   hidden.
 * - Read-only for questions; for an explicit operator command it submits a
 *   PROPOSAL to the typed pipeline (POST /chat/action) - it never executes.
 *   Nothing changes until Forseti judges the proposal and an approver signs
 *   off a high-risk one (execution is shadow-first, RBAC server-enforced).
 */

import { useCallback, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import { navigate } from "../router";
import { type VerificationProgress } from "./backend";
export {
  clampDockWidth,
  clearScheduledTimeouts,
  matchingTurnIndexes,
  parseDeckLayoutMode,
  replyAgent,
  restoredTurn,
  sessionIdFor,
  type DeckLayoutMode,
} from "./command-deck-session";
import {
  conversationPath,
  conversationUserScope,
} from "./conversation-sessions";
import { useViewContext } from "./context";
import { getDeckUser } from "./deck-user";
import { DEFAULT_NARRATOR, type Turn } from "./command-deck-presenters";
import { CommandDeckView } from "./command-deck-view";
import { serializeTurns, transcriptKeyFor } from "./transcript-store";
import {
  useCommandDeckSubmit,
  type ActiveRequest,
} from "./use-command-deck-submit";
import { useCommandDeckComposer } from "./use-command-deck-composer";
import { useCommandDeckLayout } from "./use-command-deck-layout";
import { useCommandDeckTranscript } from "./use-command-deck-transcript";
import { useContextTurnStream } from "./use-context-turn-stream";
import { useDeckBackendHealth } from "./use-deck-backend-health";
import { useCommandDeckEvents } from "./use-command-deck-events";
import { useCommandDeckLifecycle } from "./use-command-deck-lifecycle";
import {
  currentPathname,
  sessionStore,
  useCommandDeckSessionController,
  useCommandDeckSessionState,
} from "./use-command-deck-sessions";

export function CommandDeck() {
  const snapshot = useViewContext();
  const deckUser = getDeckUser();
  const userScope = conversationUserScope(
    deckUser?.accountId ?? deckUser?.username ?? deckUser?.name ?? null,
    deckUser?.devMode ?? false,
  );
  const [open, setOpen] = useState(false);
  const {
    deckStyle,
    dockWidth,
    dragging,
    layoutMode,
    onDockResizeKeyDown,
    onOverlayKeyDown,
    overlayRef,
    selectLayoutMode,
    startDockResize,
    startFloatingDrag,
  } = useCommandDeckLayout(open);
  const [draft, setDraft] = useState("");
  // Highlighted row in the "/" slash-command palette (keyboard navigable).
  const [slashActiveIndex, setSlashActiveIndex] = useState(0);
  // Active conversation session. The general screen deck is "screen"; a chat
  // scoped to one agent uses e.g. "agent:Forseti" and keeps a separate
  // transcript so threads never bleed into each other.
  const {
    conversations,
    historyRef,
    indexKey,
    openingBriefingLoadedRef,
    sessionIdsRef,
    sessionKey,
    sessionKeyRef,
    sessionLabel,
    sessionMetadataRef,
    setConversations,
    setSessionKey,
    setSessionLabel,
    setTurns,
    turns,
    turnsRef,
    updateConversationIndex,
  } = useCommandDeckSessionState(userScope, snapshot?.routeLabel ?? currentPathname());
  const [pending, setPending] = useState(false);
  const [retrievalProgress, setRetrievalProgress] =
    useState<VerificationProgress | null>(null);
  const health = useDeckBackendHealth(open);
  const [srStatus, setSrStatus] = useState("");
  const [inFlight, setInFlight] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const activeRequestRef = useRef<ActiveRequest | null>(null);
  const inFlightRef = useRef(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const contextTimersRef = useRef(new Set<number>());
  const streamContextTurn = useContextTurnStream({
    turnsRef,
    contextTimersRef,
    setTurns,
  });

  const {
    activeSearchMatch,
    jumpToLatest,
    moveSearch,
    onTranscriptScroll,
    pinTranscriptToLatest,
    scrollerRef,
    searchMatches,
    searchQuery,
    setActiveSearchMatch,
    setSearchQuery,
    stuck,
  } = useCommandDeckTranscript({
    turns,
    conversations,
    sessionKey,
    turnsRef,
    sessionMetadataRef,
  });

  const { cancelActiveRequest, closeDeck, focusInput, openDeck } =
    useCommandDeckLifecycle({
      setOpen,
      setTurns,
      setPending,
      setRetrievalProgress,
      setInFlight,
      turnsRef,
      activeRequestRef,
      abortRef,
      inFlightRef,
      contextTimersRef,
      inputRef,
    });

  const {
    hydrateDurableTurns,
    removeCachedConversation,
    startNewConversation,
    switchSession,
  } = useCommandDeckSessionController({
    userScope,
    routeLabel: snapshot?.routeLabel,
    indexKey,
    conversations,
    sessionIdsRef,
    sessionKeyRef,
    sessionMetadataRef,
    turnsRef,
    historyRef,
    setConversations,
    setDraft,
    setSessionKey,
    setSessionLabel,
    setTurns,
    setSearchQuery,
    setActiveSearchMatch,
    cancelActiveRequest,
    focusInput,
    streamContextTurn,
    updateConversationIndex,
  });

  const { openGeneralDeck } = useCommandDeckEvents({
    open,
    layoutMode,
    routeLabel: snapshot?.routeLabel,
    userScope,
    inFlight,
    draft,
    conversations,
    inputRef,
    searchRef,
    overlayRef,
    inFlightRef,
    sessionKeyRef,
    turnsRef,
    openingBriefingLoadedRef,
    historyRef,
    setDraft,
    setSearchQuery,
    setSrStatus,
    updateConversationIndex,
    cancelActiveRequest,
    closeDeck,
    focusInput,
    hydrateDurableTurns,
    openDeck,
    streamContextTurn,
    switchSession,
  });

  const submit = useCommandDeckSubmit({
    snapshot,
    pending,
    turns,
    conversations,
    sessionKeyRef,
    turnsRef,
    activeRequestRef,
    abortRef,
    inFlightRef,
    sessionIdsRef,
    sessionMetadataRef,
    historyRef,
    setTurns,
    setDraft,
    setPending,
    setRetrievalProgress,
    setSrStatus,
    setInFlight,
    updateConversationIndex,
    focusInput,
    pinTranscriptToLatest,
  });

  const clearTurns = useCallback(() => {
    cancelActiveRequest();
    setTurns([]);
    turnsRef.current = [];
    const store = sessionStore();
    try {
      store?.removeItem(transcriptKeyFor(sessionKeyRef.current));
    } catch {
      /* best-effort */
    }
  }, [cancelActiveRequest]);

  const {
    onInputKeyDown,
    regenerateAt,
    runSlashCommand,
    slashSuggestions,
    stopStream,
  } = useCommandDeckComposer({
    draft,
    turns,
    slashActiveIndex,
    historyRef,
    turnsRef,
    setDraft,
    setTurns,
    setSlashActiveIndex,
    setSrStatus,
    submit,
    startNewConversation,
    clearTurns,
    closeDeck,
    cancelActiveRequest,
  });

  const headline = snapshot?.headline ?? "Idle. Open any route to publish a view snapshot.";
  const routeLabel = snapshot?.routeLabel ?? t("deck.label");

  return (
    <CommandDeckView
      open={open}
      layoutMode={layoutMode}
      dragging={dragging}
      routeLabel={routeLabel}
      headline={headline}
      health={health}
      sessionLabel={sessionLabel}
      deckStyle={deckStyle}
      dockWidth={dockWidth}
      srStatus={srStatus}
      conversations={conversations}
      sessionKey={sessionKey}
      currentPath={currentPathname()}
      turns={turns}
      snapshot={snapshot}
      pending={pending}
      retrievalProgress={retrievalProgress}
      stuck={stuck}
      inFlight={inFlight}
      searchQuery={searchQuery}
      searchMatches={searchMatches}
      activeSearchMatch={activeSearchMatch}
      draft={draft}
      slashSuggestions={slashSuggestions}
      slashActiveIndex={slashActiveIndex}
      overlayRef={overlayRef}
      searchRef={searchRef}
      scrollerRef={scrollerRef}
      inputRef={inputRef}
      onInvoke={open ? closeDeck : openGeneralDeck}
      onClose={closeDeck}
      onOpenGeneral={openGeneralDeck}
      onOverlayKeyDown={onOverlayKeyDown}
      onDockResizeStart={startDockResize}
      onDockResizeKeyDown={onDockResizeKeyDown}
      onFloatingDragStart={startFloatingDrag}
      onSearchInput={(value) => {
        setSearchQuery(value);
        setActiveSearchMatch(0);
      }}
      onMoveSearch={moveSearch}
      onNewConversation={startNewConversation}
      onSelectLayout={selectLayoutMode}
      onRemoveConversation={removeCachedConversation}
      onSelectConversation={(conversation) => {
        if (
          conversation.kind !== "agent" &&
          conversation.originPath !== conversationPath(currentPathname())
        ) {
          navigate(conversation.originPath);
        }
        switchSession(
          conversation.key,
          conversation.agent ?? null,
          undefined,
          conversation.label,
          conversation.kind,
        );
        focusInput();
      }}
      onTranscriptScroll={onTranscriptScroll}
      onSubmit={submit}
      onRegenerate={regenerateAt}
      onJumpToLatest={jumpToLatest}
      onRunSlashCommand={runSlashCommand}
      onSlashActiveIndex={setSlashActiveIndex}
      onDraftInput={setDraft}
      onInputKeyDown={onInputKeyDown}
      onStopStream={stopStream}
    />
  );
}
