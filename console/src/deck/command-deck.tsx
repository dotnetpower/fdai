/**
 * CommandDeck - general conversations from the rail, screen conversations from
 * the bottom launcher or keyboard. Each session retains its explicit context.
 * - Read-only for questions; for an explicit operator command it submits a
 *   PROPOSAL to the typed pipeline (POST /chat/action) - it never executes.
 *   Nothing changes until Forseti judges the proposal and an approver signs
 *   off a high-risk one (execution is shadow-first, RBAC server-enforced).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { t } from "../i18n";
import { offerProactiveHandover } from "../handover-invitation";
import { navigate } from "../router";
import { type VerificationProgress } from "./backend";
export {
  clampDockWidth,
  clearScheduledTimeouts,
  matchingTurnIndexes,
  parseDeckLayoutMode,
  provisionalReplyAgent,
  replyAgent,
  replyAgentLabel,
  restoredTurn,
  sessionIdFor,
  type DeckLayoutMode,
} from "./command-deck-session";
import {
  conversationContextMode,
  conversationUserScope,
} from "./conversation-sessions";
import {
  runConversationRouteNavigation,
  selectConversationWithRoute,
} from "./conversation-navigation";
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
import type { DeckContextMode } from "./open-deck";
import type { CommandDeckSubmitOptions } from "./use-command-deck-submit";
import { ConversationContextStore, type ConversationContext } from "./conversation-context";

export function CommandDeck({ client }: { readonly client: OperatorApiClient }) {
  const snapshot = useViewContext();
  const snapshotPath = useMemo(() => currentPathname(), [snapshot]);
  const deckUser = getDeckUser();
  const userScope = conversationUserScope(
    deckUser?.accountId ?? deckUser?.username ?? deckUser?.name ?? null,
    deckUser?.devMode ?? false,
  );
  useEffect(() => {
    const storage = typeof window === "undefined" ? null : window.sessionStorage;
    void offerProactiveHandover(client, storage).catch((error: unknown) => {
      console.warn("proactive_handover_unavailable", {
        error_type: error instanceof Error ? error.name : "UnknownError",
      });
    });
  }, [client]);
  const [open, setOpen] = useState(false);
  const contextStoreRef = useRef(new ConversationContextStore());
  const [context, setContext] = useState<ConversationContext>({ mode: "screen", snapshot: null });
  const contextRef = useRef(context);
  const contextMode = context.mode;
  const generalSessionRef = useRef<string | null>(null);
  const [draft, setDraft] = useState("");
  // Highlighted row in the "/" slash-command palette (keyboard navigable).
  const [slashActiveIndex, setSlashActiveIndex] = useState(0);
  // Active conversation session. The general screen deck is "screen"; a chat
  // scoped to one agent uses e.g. "agent:Forseti" and keeps a separate
  // transcript so threads never bleed into each other.
  const {
    conversations,
    conversationHasMore,
    conversationHydration,
    conversationPageLoading,
    historyRef,
    indexKey,
    openingBriefingLoadedRef,
    sessionIdsRef,
    sessionKey,
    sessionKeyRef,
    sessionLabel,
    sessionMetadataRef,
    setConversations,
    setConversationHydration,
    setSessionKey,
    setSessionLabel,
    setTurns,
    turns,
    turnsRef,
    loadMoreConversations,
    updateConversationIndex,
  } = useCommandDeckSessionState(userScope, snapshot?.routeLabel ?? currentPathname());
  const entryMode = contextMode === "general" && !sessionLabel &&
    !sessionMetadataRef.current.get(sessionKey)?.binding ? "general" : "screen";
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
  } = useCommandDeckLayout(open, entryMode);
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
  const conversationRouteNavigationRef = useRef(false);
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
    revealCompletedWork,
    scrollerRef,
    searchMatches,
    searchQuery,
    setActiveSearchMatch,
    setSearchQuery,
    stuck,
  } = useCommandDeckTranscript({
    open,
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
    draft,
    routeLabel: snapshot?.routeLabel,
    indexKey,
    conversations,
    sessionIdsRef,
    sessionKeyRef,
    sessionMetadataRef,
    turnsRef,
    historyRef,
    setConversations,
    setConversationHydration,
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

  const activateContext = useCallback((mode: DeckContextMode) => {
    const key = sessionKeyRef.current;
    const metadata = sessionMetadataRef.current.get(key);
    const sameRoute = snapshotPath === currentPathname() &&
      (!metadata || metadata.originPath === currentPathname());
    const previousSnapshot = [...turnsRef.current].reverse()
      .find((turn) => turn.role === "operator")?.requestSnapshot;
    const selected = contextStoreRef.current.activate(
      key, mode, sameRoute ? snapshot : previousSnapshot ?? null,
    );
    contextRef.current = selected;
    setContext(selected);
    if (mode === "general" && !metadata?.agent && !metadata?.binding) {
      generalSessionRef.current = key;
    }
  }, [snapshot, snapshotPath]);

  const submit = useCommandDeckSubmit({
    snapshot,
    pending,
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
    revealCompletedWork,
  });

  const submitForContext = useCallback((
    text: string,
    options: CommandDeckSubmitOptions = {},
  ) => {
    return submit(text, {
      ...options,
      snapshot: options.snapshot === undefined ? contextRef.current.snapshot : options.snapshot,
    });
  }, [submit]);

  const startGeneralConversation = useCallback(() => {
    startNewConversation();
    activateContext("general");
  }, [activateContext, startNewConversation]);

  const resumeGeneralConversation = useCallback(() => {
    const key = generalSessionRef.current;
    if (key === null) {
      startGeneralConversation();
      return;
    }
    if (key !== sessionKeyRef.current) {
      const metadata = sessionMetadataRef.current.get(key);
      switchSession(key, null, undefined, metadata?.label, "screen-thread", false, metadata, undefined, false);
    }
    activateContext("general");
  }, [activateContext, startGeneralConversation, switchSession]);

  const { openGeneralDeck, openScreenDeck } = useCommandDeckEvents({
    open,
    contextMode: entryMode,
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
    conversationRouteNavigationRef,
    historyRef,
    setDraft,
    setSearchQuery,
    setSrStatus,
    setContextMode: activateContext,
    submitPrompt: (text, options) => void submitForContext(text, options),
    updateConversationIndex,
    cancelActiveRequest,
    closeDeck,
    focusInput,
    openDeck,
    startNewConversation: resumeGeneralConversation,
    streamContextTurn,
    switchSession,
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
    submit: submitForContext,
    startNewConversation: startGeneralConversation,
    clearTurns,
    closeDeck,
    cancelActiveRequest,
  });

  const routeLabel = snapshot?.routeLabel ?? t("deck.label");

  return (
    <CommandDeckView
      open={open}
      contextMode={contextMode}
      layoutMode={layoutMode}
      dragging={dragging}
      routeLabel={routeLabel}
      onAttachScreen={() => {
        const selected = contextStoreRef.current.attach(sessionKey, snapshot);
        contextRef.current = selected;
        setContext(selected);
      }}
      onRemoveScreen={() => {
        const selected = contextStoreRef.current.attach(sessionKey, null);
        contextRef.current = selected;
        setContext(selected);
      }}
      canAttachScreen={snapshot !== null && snapshotPath === currentPathname()}
      health={health}
      client={client}
      sessionLabel={sessionLabel}
      deckStyle={deckStyle}
      dockWidth={dockWidth}
      srStatus={srStatus}
      conversations={conversations}
      conversationHasMore={conversationHasMore}
      conversationHydration={conversationHydration}
      conversationPageLoading={conversationPageLoading}
      sessionKey={sessionKey}
      currentPath={currentPathname()}
      turns={turns}
      snapshot={context.snapshot}
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
      onInvoke={open ? closeDeck : openScreenDeck}
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
      onNewConversation={startGeneralConversation}
      onLoadMoreConversations={loadMoreConversations}
      onRetryConversation={() => void hydrateDurableTurns(sessionKey)}
      onSelectLayout={selectLayoutMode}
      onRemoveConversation={(conversation) => {
        contextStoreRef.current.remove(conversation.key);
        if (generalSessionRef.current === conversation.key) generalSessionRef.current = null;
        removeCachedConversation(conversation);
        activateContext(conversationContextMode(sessionMetadataRef.current.get(sessionKeyRef.current)));
      }}
      onToggleFavorite={(conversation) => {
        updateConversationIndex({
          ...conversation,
          favorite: conversation.favorite !== true,
        });
      }}
      onSelectConversation={(conversation) => {
        selectConversationWithRoute(conversation, currentPathname(), sessionKey, {
          navigate: (path) => runConversationRouteNavigation(
            path,
            conversationRouteNavigationRef,
            navigate,
          ),
          activate: (selected) => {
            switchSession(
              selected.key, selected.agent ?? null, undefined, selected.label,
              selected.kind, true, selected,
            );
            activateContext(conversationContextMode(selected));
          },
          focus: focusInput,
        });
      }}
      onTranscriptScroll={onTranscriptScroll}
      onSubmit={(text) => void submitForContext(text)}
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
