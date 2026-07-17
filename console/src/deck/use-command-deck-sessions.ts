import { useCallback, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import { fetchConversationTurns } from "../user-context-client";
import { restoredTurn } from "./command-deck-session";
import type { Turn } from "./command-deck-presenters";
import {
  conversationIndexKeyFor,
  conversationPath,
  manualConversationSummary,
  parseConversationIndex,
  screenConversationKey,
  screenConversationSummary,
  serializeConversationIndex,
  upsertConversation,
  userConversationKey,
  type ConversationSummary,
} from "./conversation-sessions";
import { EMPTY_HISTORY } from "./draft-history";
import { parseTurns, serializeTurns, transcriptKeyFor } from "./transcript-store";

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function sessionStore(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
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
    const restored = store ? parseConversationIndex(store.getItem(indexKey)) : [];
    const previous = restored.find((item) => item.key === initialScreenSession);
    return upsertConversation(
      restored,
      screenConversationSummary(
        initialScreenSession,
        currentPathname(),
        initialRouteLabel,
        new Date().toISOString(),
        previous,
      ),
    );
  });
  const turnsRef = useRef<readonly Turn[]>(turns);
  const sessionIdsRef = useRef(new Map<string, string>());
  const sessionMetadataRef = useRef(new Map<string, ConversationSummary>());
  const openingBriefingLoadedRef = useRef(new Set<string>());
  const historyRef = useRef(EMPTY_HISTORY);

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
  readonly streamContextTurn: (agent: string | null, text: string, source?: string) => void;
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
      const durable = await fetchConversationTurns(key);
      if (sessionKeyRef.current !== key || turnsRef.current.length > 0 || durable.length === 0) {
        return;
      }
      const restored = durable.map(restoredTurn);
      turnsRef.current = restored;
      setTurns(restored);
      try {
        sessionStore()?.setItem(transcriptKeyFor(key), serializeTurns(restored));
      } catch {
        /* browser cache is best-effort; durable history remains authoritative */
      }
    } catch {
      /* A missing server conversation is a normal first-open cache miss. */
    }
  }, [sessionKeyRef, setTurns, turnsRef]);

  const switchSession = useCallback((
    key: string,
    agent: string | null,
    contextNote?: string,
    conversationLabel?: string,
    kind: ConversationSummary["kind"] = agent ? "agent" : "screen-default",
    register = true,
    metadata?: ConversationSummary,
  ) => {
    if (key !== sessionKeyRef.current) cancelActiveRequest();
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
    if (next.length === 0) void hydrateDurableTurns(key);
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
    const summary = existing?.kind === "screen-default" && conversationLabel
      ? { ...baseSummary, label: conversationLabel, originLabel: conversationLabel }
      : baseSummary;
    sessionMetadataRef.current.set(key, summary);
    if (register) updateConversationIndex({ ...summary, updatedAt: now });
    const note = contextNote?.trim();
    if (next.length === 0 && note) streamContextTurn(agent, note);
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
    const key = userConversationKey(userScope, `conversation:${newId()}`);
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
      const fallback = remaining.find((item) => item.key === routeKey) ?? remaining[0];
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
