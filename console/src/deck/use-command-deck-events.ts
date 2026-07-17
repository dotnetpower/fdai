import { useCallback, useEffect, useRef } from "preact/hooks";
import { fetchOpeningBriefing } from "../user-context-client";
import type { Turn } from "./command-deck-presenters";
import { record as recordHistory, type DraftHistory } from "./draft-history";
import { DECK_OPEN_EVENT, type DeckOpenDetail } from "./open-deck";
import {
  screenConversationKey,
  userConversationKey,
  type ConversationSummary,
} from "./conversation-sessions";
import type { DeckLayoutMode } from "./command-deck-session";
import { currentPathname } from "./use-command-deck-sessions";

interface EventsOptions {
  readonly open: boolean;
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
  readonly openingBriefingLoadedRef: { current: Set<string> };
  readonly historyRef: { current: DraftHistory };
  readonly setDraft: (value: string) => void;
  readonly setSearchQuery: (value: string) => void;
  readonly setSrStatus: (value: string) => void;
  readonly updateConversationIndex: (summary: ConversationSummary) => void;
  readonly cancelActiveRequest: () => "stream" | "action" | null;
  readonly closeDeck: () => void;
  readonly focusInput: () => void;
  readonly hydrateDurableTurns: (key: string) => Promise<void>;
  readonly openDeck: () => void;
  readonly streamContextTurn: (agent: string | null, text: string, source?: string) => void;
  readonly switchSession: (
    key: string,
    agent: string | null,
    contextNote?: string,
    conversationLabel?: string,
    kind?: ConversationSummary["kind"],
  ) => void;
}

export function useCommandDeckEvents(options: EventsOptions) {
  const {
    open,
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
  } = options;

  useEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    const maxHeight = 180;
    element.style.height = "auto";
    const next = Math.min(element.scrollHeight, maxHeight);
    element.style.height = `${next}px`;
    element.style.overflowY = element.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [draft, inputRef, open]);

  useEffect(() => {
    if (!routeLabel) return;
    const key = screenConversationKey(userScope, currentPathname());
    const existing = conversations.find((item) => item.key === key);
    if (
      existing?.kind !== "screen-default" ||
      (existing.label === routeLabel && existing.originLabel === routeLabel)
    ) return;
    updateConversationIndex({ ...existing, label: routeLabel, originLabel: routeLabel });
  }, [conversations, routeLabel, updateConversationIndex, userScope]);

  useEffect(() => {
    inFlightRef.current = inFlight;
  }, [inFlight, inFlightRef]);

  const openGeneralDeck = useCallback(() => {
    const key = screenConversationKey(userScope, currentPathname());
    if (sessionKeyRef.current !== key) {
      switchSession(key, null, undefined, routeLabel ?? currentPathname(), "screen-default");
    }
    openDeck();
    if (
      !openingBriefingLoadedRef.current.has(key) &&
      !turnsRef.current.some((turn) => turn.source === "briefing")
    ) {
      openingBriefingLoadedRef.current.add(key);
      void hydrateDurableTurns(key)
        .then(() => fetchOpeningBriefing(key))
        .then((briefing) => {
          if (briefing && sessionKeyRef.current === key) {
            streamContextTurn(
              "Bragi",
              `**${briefing.title}**\n\n${briefing.body_markdown}`,
              "briefing",
            );
          }
        })
        .catch(() => {
          openingBriefingLoadedRef.current.delete(key);
        });
    }
  }, [
    hydrateDurableTurns,
    openDeck,
    openingBriefingLoadedRef,
    routeLabel,
    sessionKeyRef,
    streamContextTurn,
    switchSession,
    turnsRef,
    userScope,
  ]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const inField = target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable === true;
      if ((event.key === "k" || event.key === "K") && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        if (open) {
          searchRef.current?.focus();
          searchRef.current?.select();
        } else openGeneralDeck();
        return;
      }
      if (!inField && event.key === "/" && !open) {
        event.preventDefault();
        openGeneralDeck();
        return;
      }
      if (event.key === "Escape" && open) {
        event.preventDefault();
        if (document.activeElement === searchRef.current) {
          setSearchQuery("");
          focusInput();
          return;
        }
        if (inFlightRef.current) {
          const kind = cancelActiveRequest();
          setSrStatus(kind === "action"
            ? "Response dismissed; submission outcome may be unknown."
            : "Stopped.");
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
    open,
    openGeneralDeck,
    searchRef,
    setSearchQuery,
    setSrStatus,
  ]);

  useEffect(() => {
    const onOpenDeck = (event: Event) => {
      const detail = (event as CustomEvent<DeckOpenDetail>).detail;
      const note = typeof detail?.contextNote === "string" ? detail.contextNote.trim() : "";
      const requestedKey = typeof detail?.sessionKey === "string" && detail.sessionKey
        ? detail.sessionKey
        : null;
      const key = requestedKey
        ? userConversationKey(userScope, requestedKey)
        : screenConversationKey(userScope, currentPathname());
      const label = typeof detail?.sessionLabel === "string" ? detail.sessionLabel : null;
      if (key !== sessionKeyRef.current) {
        switchSession(
          key,
          label,
          note,
          label ?? undefined,
          requestedKey?.startsWith("agent:") ? "agent" : "screen-thread",
        );
      } else if (note && turnsRef.current.length === 0) {
        streamContextTurn(label, note);
      }
      const seed = typeof detail?.prompt === "string" ? detail.prompt : "";
      if (seed) {
        setDraft(seed);
        historyRef.current = recordHistory(historyRef.current, seed);
      }
      openDeck();
    };
    window.addEventListener(DECK_OPEN_EVENT, onOpenDeck);
    return () => window.removeEventListener(DECK_OPEN_EVENT, onOpenDeck);
  }, [
    historyRef,
    openDeck,
    sessionKeyRef,
    setDraft,
    streamContextTurn,
    switchSession,
    turnsRef,
    userScope,
  ]);

  const layoutModeRef = useRef(layoutMode);
  const openRef = useRef(open);
  const routeLabelRef = useRef<string | undefined>(routeLabel);
  useEffect(() => { layoutModeRef.current = layoutMode; }, [layoutMode]);
  useEffect(() => { openRef.current = open; }, [open]);
  useEffect(() => { routeLabelRef.current = routeLabel; }, [routeLabel]);
  useEffect(() => {
    const switchToCurrentRoute = () => {
      if (layoutModeRef.current === "workspace" || layoutModeRef.current === "dock") {
        closeDeck();
        return;
      }
      if (!openRef.current) return;
      const key = screenConversationKey(userScope, currentPathname());
      if (sessionKeyRef.current !== key) {
        switchSession(
          key,
          null,
          undefined,
          routeLabelRef.current ?? currentPathname(),
          "screen-default",
        );
      }
    };
    window.addEventListener("popstate", switchToCurrentRoute);
    window.addEventListener("fdai:route-changed", switchToCurrentRoute);
    return () => {
      window.removeEventListener("popstate", switchToCurrentRoute);
      window.removeEventListener("fdai:route-changed", switchToCurrentRoute);
    };
  }, [closeDeck, sessionKeyRef, switchSession, userScope]);

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

  useEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [draft, inputRef, open]);

  return { openGeneralDeck };
}
