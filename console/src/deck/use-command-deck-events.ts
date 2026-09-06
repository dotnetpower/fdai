import { useCallback, useEffect, useRef } from "preact/hooks";
import { t } from "../i18n";
import type { Turn } from "./command-deck-presenters";
import { DEFAULT_NARRATOR } from "./command-deck-presenters";
import { record as recordHistory, type DraftHistory } from "./draft-history";
import {
  acknowledgeDeckOpenEvent,
  DECK_OPEN_EVENT,
  DECK_TOGGLE_EVENT,
  publishDeckOpenState,
  setDeckOpenListenerReady,
  installWorkspaceDeckNavigationHandler,
  type DeckContextMode,
  type DeckOpenDetail,
  type IncidentConversationBinding,
} from "./open-deck";
import {
  newConversationKey,
  newGeneralConversationKey,
  normalizeAgentTarget,
  normalizeIncidentBinding,
  screenConversationKey,
  userConversationKey,
  type ConversationSummary,
} from "./conversation-sessions";
import type { DeckLayoutMode } from "./command-deck-session";
import { currentPathname } from "./use-command-deck-sessions";

interface EventsOptions {
  readonly open: boolean;
  readonly contextMode: DeckContextMode;
  readonly layoutMode: DeckLayoutMode;
  readonly routeLabel: string | undefined;
  readonly userScope: string;
  readonly inFlight: boolean;
  readonly draft: string;
  readonly conversations: readonly ConversationSummary[];
  readonly inputRef: { current: HTMLTextAreaElement | null };
  readonly searchRef: { current: HTMLInputElement | null };
  readonly overlayRef: { current: HTMLDivElement | null };
  readonly inFlightRef: { current: boolean };
  readonly sessionKeyRef: { current: string };
  readonly turnsRef: { current: readonly Turn[] };
  readonly conversationRouteNavigationRef: { current: boolean };
  readonly historyRef: { current: DraftHistory };
  readonly setDraft: (value: string) => void;
  readonly setSearchQuery: (value: string) => void;
  readonly setSrStatus: (value: string) => void;
  readonly setContextMode: (value: DeckContextMode) => void;
  readonly submitPrompt: (
    text: string,
    options?: { readonly snapshot?: null },
  ) => void;
  readonly updateConversationIndex: (summary: ConversationSummary) => void;
  readonly cancelActiveRequest: () => "stream" | "action" | null;
  readonly closeDeck: () => void;
  readonly focusInput: () => void;
  readonly openDeck: () => void;
  readonly startNewConversation: () => void;
  readonly streamContextTurn: (
    agent: string | null,
    text: string,
    source?: string,
    groundingText?: string,
  ) => void;
  readonly switchSession: (
    key: string,
    agent: string | null,
    contextNote?: string,
    conversationLabel?: string,
    kind?: ConversationSummary["kind"],
    register?: boolean,
    metadata?: ConversationSummary,
    binding?: IncidentConversationBinding,
    hydrate?: boolean,
    openingBriefing?: string,
  ) => void;
}

export function resolveDeckOpenSession(
  detail: DeckOpenDetail | undefined,
  userScope: string,
  pathname: string,
  nonce?: string,
) {
  const requestedKey = typeof detail?.sessionKey === "string" && detail.sessionKey
    ? detail.sessionKey
    : null;
  const targetAgent = normalizeAgentTarget(detail?.targetAgent);
  const invalidFreshTarget = detail?.newConversation === true &&
    detail.targetAgent !== undefined && targetAgent === null;
  const key = detail?.newConversation === true && targetAgent
    ? newConversationKey(userScope, targetAgent, nonce)
    : detail?.newConversation === true && detail.binding?.kind === "incident"
      ? newConversationKey(userScope, null, nonce)
    : requestedKey
      ? userConversationKey(userScope, requestedKey)
      : detail?.contextMode === "general"
        ? newGeneralConversationKey(userScope, nonce)
      : screenConversationKey(userScope, pathname);
  const label = !invalidFreshTarget && typeof detail?.sessionLabel === "string"
    ? detail.sessionLabel
    : null;
  return {
    key,
    label,
    contextAgent: detail?.binding
      ? DEFAULT_NARRATOR
      : invalidFreshTarget ? null : (targetAgent ?? label),
    kind: targetAgent || requestedKey?.startsWith("agent:")
      ? "agent" as const
      : "screen-thread" as const,
    hydrateDurable: detail?.newConversation !== true,
  };
}

export function shouldDeferDeckOpen(
  detail: DeckOpenDetail | undefined,
  inFlight: boolean,
  draft: string,
): boolean {
  return detail?.onlyWhenIdle === true && (inFlight || draft.trim().length > 0);
}

export function useCommandDeckEvents(options: EventsOptions) {
  const {
    open,
    contextMode,
    layoutMode,
    routeLabel,
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
    setContextMode,
    submitPrompt,
    updateConversationIndex,
    cancelActiveRequest,
    closeDeck,
    focusInput,
    openDeck,
    startNewConversation,
    streamContextTurn,
    switchSession,
  } = options;

  useEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    const maxHeight = 180;
    element.style.height = "auto";
    const next = Math.min(element.scrollHeight, maxHeight);
    element.style.height = `${next}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [draft, inputRef, layoutMode, open]);

  useEffect(() => {
    if (!routeLabel) return;
    const key = screenConversationKey(userScope, currentPathname());
    const existing = conversations.find((item) => item.key === key);
    if (
      existing?.kind !== "screen-default" ||
      existing.originLabel === routeLabel
    ) return;
    updateConversationIndex({ ...existing, originLabel: routeLabel });
  }, [conversations, routeLabel, updateConversationIndex, userScope]);

  useEffect(() => {
    inFlightRef.current = inFlight;
  }, [inFlight, inFlightRef]);

  const openGeneralDeck = useCallback(() => {
    startNewConversation();
    openDeck();
  }, [openDeck, startNewConversation]);

  const openScreenDeck = useCallback(() => {
    const key = screenConversationKey(userScope, currentPathname());
    if (key !== sessionKeyRef.current) {
      switchSession(
        key,
        null,
        undefined,
        routeLabelRef.current ?? currentPathname(),
        "screen-default",
      );
    }
    setContextMode("screen");
    openDeck();
  }, [openDeck, sessionKeyRef, setContextMode, switchSession, userScope]);

  const layoutModeRef = useRef(layoutMode);
  const openRef = useRef(open);
  const contextModeRef = useRef(contextMode);
  const routeLabelRef = useRef<string | undefined>(routeLabel);
  layoutModeRef.current = layoutMode;
  openRef.current = open;
  contextModeRef.current = contextMode;
  routeLabelRef.current = routeLabel;
  useEffect(() => { publishDeckOpenState(open, contextMode); }, [contextMode, open]);
  useEffect(() => () => publishDeckOpenState(false), []);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const inField = target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable === true;
      if ((event.key === "k" || event.key === "K") && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        if (openRef.current) {
          if (searchRef.current) {
            searchRef.current.focus();
            searchRef.current.select();
          } else {
            focusInput();
          }
        } else openScreenDeck();
        return;
      }
      if (!inField && event.key === "/" && !openRef.current) {
        event.preventDefault();
        openScreenDeck();
        return;
      }
      if (event.key === "Escape" && openRef.current) {
        event.preventDefault();
        if (document.activeElement === searchRef.current) {
          setSearchQuery("");
          focusInput();
          return;
        }
        if (inFlightRef.current) {
          const kind = cancelActiveRequest();
          setSrStatus(kind === "action"
            ? t("deck.announcement.responseDismissed")
            : t("deck.announcement.stopped"));
          return;
        }
        closeDeck();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [
    cancelActiveRequest,
    closeDeck,
    focusInput,
    inFlightRef,
    openScreenDeck,
    searchRef,
    setSearchQuery,
    setSrStatus,
  ]);

  useEffect(() => {
    const onOpenDeck = (event: Event) => {
      acknowledgeDeckOpenEvent(event);
      const detail = (event as CustomEvent<DeckOpenDetail>).detail;
      if (shouldDeferDeckOpen(detail, inFlightRef.current, draft)) {
        event.preventDefault();
        return;
      }
      const note = typeof detail?.contextNote === "string" ? detail.contextNote.trim() : "";
      const briefing = typeof detail?.openingBriefing === "string"
        ? detail.openingBriefing.trim()
        : "";
      const incidentBinding = normalizeIncidentBinding(detail?.binding) ?? undefined;
      const requestedMode = detail?.contextMode === "general" ||
        incidentBinding !== undefined || detail?.targetAgent ? "general" : "screen";
      const { key, label, contextAgent, kind, hydrateDurable } = resolveDeckOpenSession(
        detail,
        userScope,
        currentPathname(),
      );
      if (key !== sessionKeyRef.current) {
        switchSession(
          key,
          contextAgent,
          note,
          label ?? undefined,
          kind,
          true,
          undefined,
          incidentBinding,
          hydrateDurable,
          briefing || undefined,
        );
      } else if ((briefing || note) && turnsRef.current.length === 0) {
        streamContextTurn(
          contextAgent,
          briefing || note,
          "context",
          note || undefined,
        );
      }
      setContextMode(requestedMode);
      const seed = typeof detail?.prompt === "string" ? detail.prompt : "";
      if (seed) {
        if (detail?.submitPrompt === true) {
          submitPrompt(seed, requestedMode === "general" ? { snapshot: null } : undefined);
        } else {
          setDraft(seed);
          historyRef.current = recordHistory(historyRef.current, seed);
        }
      }
      openDeck();
    };
    const onToggleDeck = () => {
      if (openRef.current && contextModeRef.current === "general") closeDeck();
      else openGeneralDeck();
    };
    window.addEventListener(DECK_OPEN_EVENT, onOpenDeck);
    window.addEventListener(DECK_TOGGLE_EVENT, onToggleDeck);
    setDeckOpenListenerReady(true);
    return () => {
      setDeckOpenListenerReady(false);
      window.removeEventListener(DECK_OPEN_EVENT, onOpenDeck);
      window.removeEventListener(DECK_TOGGLE_EVENT, onToggleDeck);
    };
  }, [
    closeDeck,
    draft,
    historyRef,
    inFlightRef,
    openDeck,
    openGeneralDeck,
    sessionKeyRef,
    setDraft,
    setContextMode,
    submitPrompt,
    streamContextTurn,
    switchSession,
    turnsRef,
    userScope,
  ]);

  useEffect(() => installWorkspaceDeckNavigationHandler(
    () => openRef.current && layoutModeRef.current === "workspace",
    closeDeck,
  ), [closeDeck]);
  useEffect(() => {
    const switchToCurrentRoute = () => {
      if (conversationRouteNavigationRef.current) return;
      if (layoutModeRef.current === "workspace" || layoutModeRef.current === "dock") {
        closeDeck();
        return;
      }
      if (!openRef.current) return;
      // A floating conversation keeps its original context until an explicit entry switch.
    };
    window.addEventListener("popstate", switchToCurrentRoute);
    window.addEventListener("fdai:route-changed", switchToCurrentRoute);
    return () => {
      window.removeEventListener("popstate", switchToCurrentRoute);
      window.removeEventListener("fdai:route-changed", switchToCurrentRoute);
    };
  }, [
    closeDeck,
    conversationRouteNavigationRef,
    sessionKeyRef,
    setContextMode,
    switchSession,
    userScope,
  ]);

  useEffect(() => {
    if (!open || layoutMode !== "workspace") return;
    const onFocusIn = (event: FocusEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      const overlay = overlayRef.current;
      if (overlay && overlay.contains(target)) return;
      if (target.closest(".navigation-shell")) return;
      requestAnimationFrame(() => inputRef.current?.focus());
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, [inputRef, layoutMode, open, overlayRef]);

  return { openGeneralDeck, openScreenDeck };
}
