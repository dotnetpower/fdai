import { useCallback, useEffect, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import {
  fetchConversationPage,
  fetchConversationTurns,
  fetchUserContext,
  type ConversationCursorPayload,
} from "../user-context-client";
import { restoredTurn, sessionIdFor } from "./command-deck-session";
import type { Turn } from "./command-deck-presenters";
import { resetComposerAttachments } from "./composer-attachment-store";
import {
  conversationIndexKeyFor,
  CONVERSATION_HISTORY_PAGE_SIZE,
  conversationFallbackForRoute,
  conversationLabelForPrompt,
  conversationPath,
  markConversationRead,
  manualConversationSummary,
  mergeConversationActivity,
  newConversationKey,
  parseConversationIndex,
  screenConversationKey,
  screenConversationSummary,
  serializeConversationIndex,
  serverConversationSummary,
  upsertConversation,
  userConversationKey,
  type ConversationSummary,
} from "./conversation-sessions";
import { EMPTY_HISTORY } from "./draft-history";
import { parseTurns, serializeTurns, transcriptKeyFor } from "./transcript-store";
import type { IncidentConversationBinding } from "./open-deck";

export function sessionStore(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    try {
      return window.sessionStorage;
    } catch {
      return null;
    }
  }
}

export function currentPathname(): string {
  return typeof window === "undefined" ? "/overview" : window.location.pathname;
}

export function useCommandDeckSessionState(
  userScope: string,
  initialRouteLabel: string,
) {
  const indexKey = conversationIndexKeyFor(userScope);
  const initialScreenSession = screenConversationKey(userScope, currentPathname());
  const [sessionKey, setSessionKey] = useState<string>(initialScreenSession);
  const [sessionLabel, setSessionLabel] = useState<string | null>(null);
  const sessionKeyRef = useRef<string>(initialScreenSession);
  const [turns, setTurns] = useState<readonly Turn[]>(() => {
    const store = sessionStore();
    return store ? parseTurns(store.getItem(transcriptKeyFor(initialScreenSession))) : [];
  });
  const [conversations, setConversations] = useState<readonly ConversationSummary[]>(() => {
    const store = sessionStore();
    const restored = store
      ? parseConversationIndex(store.getItem(indexKey)).slice(0, CONVERSATION_HISTORY_PAGE_SIZE)
      : [];
    const previous = restored.find((item) => item.key === initialScreenSession);
    const summary = screenConversationSummary(
      initialScreenSession,
      currentPathname(),
      initialRouteLabel,
      new Date().toISOString(),
      previous,
    );
    const firstOperator = turns.find((turn) => turn.role === "operator");
    return upsertConversation(
      restored,
      firstOperator
        ? { ...summary, label: conversationLabelForPrompt(summary, firstOperator.text, false) }
        : summary,
    );
  });
  const turnsRef = useRef<readonly Turn[]>(turns);
  const sessionIdsRef = useRef(new Map<string, string>());
  const sessionMetadataRef = useRef(new Map<string, ConversationSummary>());
  const openingBriefingLoadedRef = useRef(new Set<string>());
  const historyRef = useRef(EMPTY_HISTORY);
  const [conversationCursor, setConversationCursor] =
    useState<ConversationCursorPayload | null>(null);
  const [conversationHasMore, setConversationHasMore] = useState(false);
  const [conversationPageLoading, setConversationPageLoading] = useState(false);
  const conversationPageLoadingRef = useRef(false);

  const mergeServerPage = useCallback((records: readonly ConversationSummary[]) => {
    setConversations((current) => {
      let next = [...current];
      for (const summary of records) {
        const existing = next.find((item) => item.key === summary.key);
        const merged = existing ? mergeConversationActivity(existing, summary) : summary;
        const reconciled = merged.key === sessionKeyRef.current
          ? markConversationRead(merged, merged.updatedAt)
          : merged;
        next = upsertConversation(next, reconciled);
      }
      try {
        sessionStore()?.setItem(indexKey, serializeConversationIndex(next));
      } catch {
        /* browser cache is best-effort; durable history remains authoritative */
      }
      return next;
    });
  }, [indexKey]);

  useEffect(() => {
    let active = true;
    const pathname = currentPathname();
    void fetchUserContext()
      .then((context) => {
        if (!active) return;
        const serverConversations = context.conversations.map((record) =>
          serverConversationSummary(record, pathname, initialRouteLabel)
        );
        mergeServerPage(serverConversations);
        setConversationHasMore(context.conversation_page.has_more);
        setConversationCursor(context.conversation_page.next_cursor);
      })
      .catch(() => {
        /* The deck remains usable when durable history is unavailable. */
      });
    return () => {
      active = false;
    };
  }, [initialRouteLabel, mergeServerPage]);

  const loadMoreConversations = useCallback(async () => {
    if (!conversationHasMore || conversationCursor === null || conversationPageLoadingRef.current) {
      return;
    }
    conversationPageLoadingRef.current = true;
    setConversationPageLoading(true);
    try {
      const page = await fetchConversationPage(conversationCursor);
      const pathname = currentPathname();
      mergeServerPage(page.conversations.map((record) =>
        serverConversationSummary(record, pathname, initialRouteLabel)
      ));
      setConversationHasMore(page.has_more);
      setConversationCursor(page.next_cursor);
    } catch {
      /* Keep the cursor so a later scroll can retry without losing the current page. */
    } finally {
      conversationPageLoadingRef.current = false;
      setConversationPageLoading(false);
    }
  }, [conversationCursor, conversationHasMore, initialRouteLabel, mergeServerPage]);

  const updateConversationIndex = useCallback(
    (summary: ConversationSummary) => {
      setConversations((current) => {
        const next = upsertConversation(current, summary);
        const retained = new Set(next.map((item) => item.key));
        try {
          const store = sessionStore();
          store?.setItem(indexKey, serializeConversationIndex(next));
          for (const evicted of current) {
            if (!retained.has(evicted.key)) store?.removeItem(transcriptKeyFor(evicted.key));
          }
        } catch {
          /* best-effort */
        }
        return next;
      });
    },
    [indexKey],
  );

  return {
    conversations,
    conversationHasMore,
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
    setSessionKey,
    setSessionLabel,
    setTurns,
    turns,
    turnsRef,
    loadMoreConversations,
    updateConversationIndex,
  };
}

interface SessionControllerOptions {
  readonly userScope: string;
  readonly routeLabel: string | undefined;
  readonly indexKey: string;
  readonly conversations: readonly ConversationSummary[];
  readonly sessionIdsRef: { current: Map<string, string> };
  readonly sessionKeyRef: { current: string };
  readonly sessionMetadataRef: { current: Map<string, ConversationSummary> };
  readonly turnsRef: { current: readonly Turn[] };
  readonly historyRef: { current: typeof EMPTY_HISTORY };
  readonly setConversations: (value: readonly ConversationSummary[]) => void;
  readonly setDraft: (value: string) => void;
  readonly setSessionKey: (value: string) => void;
  readonly setSessionLabel: (value: string | null) => void;
  readonly setTurns: (value: readonly Turn[]) => void;
  readonly setSearchQuery: (value: string) => void;
  readonly setActiveSearchMatch: (value: number) => void;
  readonly cancelActiveRequest: () => unknown;
  readonly focusInput: () => void;
  readonly streamContextTurn: (
    agent: string | null,
    text: string,
    source?: string,
    groundingText?: string,
  ) => void;
  readonly updateConversationIndex: (summary: ConversationSummary) => void;
}

export function useCommandDeckSessionController({
  userScope,
  routeLabel,
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
}: SessionControllerOptions) {
  const hydrateDurableTurns = useCallback(async (key: string): Promise<void> => {
    if (sessionKeyRef.current !== key || turnsRef.current.length > 0) return;
    try {
      const durable = await fetchConversationTurns(sessionIdFor(sessionIdsRef.current, key));
      if (sessionKeyRef.current !== key || turnsRef.current.length > 0 || durable.length === 0) {
        return;
      }
      const restored = durable.map(restoredTurn);
      turnsRef.current = restored;
      setTurns(restored);
      const summary = conversations.find((item) => item.key === key);
      const firstOperator = durable.find((turn) => turn.role === "operator");
      if (summary?.restoredFromServer && firstOperator) {
        const titled = {
          ...summary,
          label: conversationLabelForPrompt(summary, firstOperator.content, false),
          restoredFromServer: false,
        };
        sessionMetadataRef.current.set(key, titled);
        updateConversationIndex(titled);
      }
      try {
        sessionStore()?.setItem(transcriptKeyFor(key), serializeTurns(restored));
      } catch {
        /* browser cache is best-effort; durable history remains authoritative */
      }
    } catch {
      /* A missing server conversation is a normal first-open cache miss. */
    }
  }, [
    conversations,
    sessionIdsRef,
    sessionKeyRef,
    sessionMetadataRef,
    setTurns,
    turnsRef,
    updateConversationIndex,
  ]);

  const switchSession = useCallback((
    key: string,
    agent: string | null,
    contextNote?: string,
    conversationLabel?: string,
    kind: ConversationSummary["kind"] = agent ? "agent" : "screen-default",
    register = true,
    metadata?: ConversationSummary,
    binding?: IncidentConversationBinding,
    hydrate = register,
    openingBriefing?: string,
  ) => {
    if (key !== sessionKeyRef.current) cancelActiveRequest();
    if (key !== sessionKeyRef.current) resetComposerAttachments();
    const store = sessionStore();
    if (store && key !== sessionKeyRef.current) {
      try {
        const outgoingKey = sessionKeyRef.current;
        const outgoing = sessionMetadataRef.current.get(outgoingKey);
        const ephemeralEmpty = outgoing?.kind === "screen-thread" &&
          turnsRef.current.length === 0 &&
          !conversations.some((item) => item.key === outgoingKey);
        if (ephemeralEmpty) store.removeItem(transcriptKeyFor(outgoingKey));
        else store.setItem(transcriptKeyFor(outgoingKey), serializeTurns(turnsRef.current));
      } catch {
        /* best-effort */
      }
    }
    const next: Turn[] = store
      ? parseTurns(store.getItem(transcriptKeyFor(key))) as Turn[]
      : [];
    sessionKeyRef.current = key;
    turnsRef.current = next;
    setSessionKey(key);
    setSessionLabel(agent);
    setTurns(next);
    if (shouldHydrateServerTurns(hydrate, next.length)) void hydrateDurableTurns(key);
    setSearchQuery("");
    setActiveSearchMatch(0);
    historyRef.current = EMPTY_HISTORY;
    const existing = conversations.find((item) => item.key === key);
    const now = new Date().toISOString();
    const baseSummary = metadata ?? existing ?? {
      key,
      label: conversationLabel ?? agent ?? t("deck.newConversation"),
      kind,
      ...(agent ? { agent } : {}),
      originPath: conversationPath(currentPathname()),
      originLabel: routeLabel ?? currentPathname(),
      createdAt: now,
      updatedAt: now,
    };
    const firstOperator = next.find((turn) => turn.role === "operator");
    const labeledSummary = firstOperator
      ? {
          ...baseSummary,
          label: conversationLabelForPrompt(baseSummary, firstOperator.text, false),
        }
      : baseSummary;
    const summary = binding ? { ...labeledSummary, binding } : labeledSummary;
    sessionMetadataRef.current.set(key, summary);
    if (register) updateConversationIndex(markConversationRead(summary, now));
    const note = contextNote?.trim();
    const briefing = openingBriefing?.trim();
    if (next.length === 0 && (briefing || note)) {
      streamContextTurn(agent, briefing || note || "", "context", note || undefined);
    }
  }, [
    cancelActiveRequest,
    conversations,
    historyRef,
    hydrateDurableTurns,
    routeLabel,
    sessionKeyRef,
    sessionMetadataRef,
    setActiveSearchMatch,
    setSearchQuery,
    setSessionKey,
    setSessionLabel,
    setTurns,
    streamContextTurn,
    turnsRef,
    updateConversationIndex,
  ]);

  const startNewConversation = useCallback(() => {
    const key = newConversationKey(userScope);
    const summary = manualConversationSummary(
      key,
      currentPathname(),
      routeLabel ?? currentPathname(),
      new Date().toISOString(),
      t("deck.newConversation"),
    );
    switchSession(key, null, undefined, summary.label, summary.kind, false, summary);
    setDraft("");
    focusInput();
  }, [focusInput, routeLabel, setDraft, switchSession, userScope]);

  const removeCachedConversation = useCallback((conversation: ConversationSummary) => {
    const removingActive = sessionKeyRef.current === conversation.key;
    if (removingActive) cancelActiveRequest();
    const remaining = conversations.filter((item) => item.key !== conversation.key);
    try {
      const store = sessionStore();
      store?.removeItem(transcriptKeyFor(conversation.key));
      store?.setItem(indexKey, serializeConversationIndex(remaining));
    } catch {
      /* best-effort */
    }
    sessionIdsRef.current.delete(conversation.key);
    setConversations(remaining);
    if (removingActive) {
      const routeKey = screenConversationKey(userScope, currentPathname());
      const fallback = conversationFallbackForRoute(
        remaining,
        userScope,
        currentPathname(),
      );
      if (fallback) {
        switchSession(fallback.key, fallback.agent ?? null, undefined, fallback.label, fallback.kind);
      } else {
        switchSession(routeKey, null, undefined, routeLabel ?? currentPathname(), "screen-default");
      }
    }
    focusInput();
  }, [
    cancelActiveRequest,
    conversations,
    focusInput,
    indexKey,
    routeLabel,
    sessionIdsRef,
    sessionKeyRef,
    setConversations,
    switchSession,
    userScope,
  ]);

  return { hydrateDurableTurns, removeCachedConversation, startNewConversation, switchSession };
}

export function shouldHydrateServerTurns(register: boolean, turnCount: number): boolean {
  return register && turnCount === 0;
}
