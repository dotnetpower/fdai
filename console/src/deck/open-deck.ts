/**
 * Cross-screen "open the Command Deck" event contract.
 *
 * A single decoupled seam: any read-only surface can raise the deck (optionally
 * seeding a grounded question) without holding a reference to it. The deck
 * listens for {@link DECK_OPEN_EVENT}; senders call {@link openDeckWithPrompt}.
 *
 * This never executes anything - it only opens a question box the operator
 * still has to send, preserving the read-only-console invariant.
 */

/** The window event name the CommandDeck listens for. */
export const DECK_OPEN_EVENT = "fdai:deck:open";
export const DECK_OPEN_READY_EVENT = "fdai:deck:open-ready";

/** Cancelable request used by Activity Bar group navigation. */
export const DECK_WORKSPACE_NAVIGATION_EVENT = "fdai:deck:workspace-navigation";

export interface IncidentConversationBinding {
  readonly kind: "incident";
  readonly incidentId: string;
  readonly correlationId: string;
  readonly selectedAgent?: string;
}

/** Detail payload carried by a {@link DECK_OPEN_EVENT}. */
export interface DeckOpenDetail {
  /** Optional draft to seed the deck input with (the operator still sends it). */
  readonly prompt?: string;
  /**
   * Optional context note injected as the deck's opening message. Unlike
   * `prompt` (a draft the operator edits/sends), this lands as a grounding
   * turn in the transcript so the narrator's answers to follow-up questions
   * are conditioned on it. Used e.g. to prime a chat with one agent's recent
   * work. Plain text, English (L0 pipeline); rendered read-only.
   */
  readonly contextNote?: string;
  /** Optional operator-facing opening report shown instead of the grounding note. */
  readonly openingBriefing?: string;
  /**
   * Optional session id. The deck keeps each session's transcript separate, so
   * a conversation scoped to one agent (e.g. `agent:Forseti`) never appends to
   * the general screen deck. Omit / `undefined` targets the general session.
   */
  readonly sessionKey?: string;
  /** Human label for a non-general session, shown in the deck header (e.g. `Forseti`). */
  readonly sessionLabel?: string;
  /** Create a fresh conversation instead of restoring `sessionKey`. */
  readonly newConversation?: boolean;
  /** Pantheon agent bound to a fresh agent conversation. */
  readonly targetAgent?: string;
  /** Structured, untrusted selection hint that the server must verify against its read model. */
  readonly binding?: IncidentConversationBinding;
  /** Refuse automatic session switching while a turn or unsent draft is active. */
  readonly onlyWhenIdle?: boolean;
}

let deckOpenListenerReady = false;

export function isDeckOpenListenerReady(): boolean {
  return deckOpenListenerReady;
}

export function setDeckOpenListenerReady(ready: boolean): void {
  deckOpenListenerReady = ready;
  if (ready && typeof window !== "undefined" && typeof Event !== "undefined") {
    window.dispatchEvent(new Event(DECK_OPEN_READY_EVENT));
  }
}

/**
 * Raise the Command Deck, optionally seeding its input with `prompt`.
 *
 * No-op outside a browser (SSR / tests without a window). The deck focuses its
 * input on receipt; the seeded text is a draft, never an auto-submitted turn.
 */
export function openDeckWithPrompt(prompt?: string): void {
  if (typeof window === "undefined" || typeof CustomEvent === "undefined") return;
  const detail: DeckOpenDetail = prompt ? { prompt } : {};
  window.dispatchEvent(new CustomEvent<DeckOpenDetail>(DECK_OPEN_EVENT, { detail }));
}

/**
 * Raise the Command Deck and inject `contextNote` as opening grounding while
 * optionally rendering a shorter `openingBriefing`. A draft `prompt` remains
 * operator-controlled and is never submitted automatically.
 *
 * No-op outside a browser. Still read-only: it opens a primed question box,
 * it never auto-submits or executes anything.
 */
export function openDeckWithContext(detail: DeckOpenDetail): boolean {
  if (typeof window === "undefined" || typeof CustomEvent === "undefined") return false;
  if (!deckOpenListenerReady) return false;
  return window.dispatchEvent(new CustomEvent<DeckOpenDetail>(DECK_OPEN_EVENT, {
    detail,
    cancelable: true,
  }));
}

/**
 * Ask an open full-workspace Deck to close before group navigation.
 *
 * Returns true only when the Deck accepts the cancelable request. Other Deck
 * modes and a closed Deck leave Activity Bar behavior unchanged.
 */
export function requestWorkspaceDeckCloseForNavigation(): boolean {
  if (typeof window === "undefined" || typeof Event === "undefined") return false;
  const event = new Event(DECK_WORKSPACE_NAVIGATION_EVENT, { cancelable: true });
  return !window.dispatchEvent(event);
}

/** Register the Deck side of the workspace-navigation handshake. */
export function installWorkspaceDeckNavigationHandler(
  shouldClose: () => boolean,
  closeDeck: () => void,
): () => void {
  if (typeof window === "undefined") return () => undefined;
  const handler = (event: Event) => {
    if (!shouldClose()) return;
    event.preventDefault();
    closeDeck();
  };
  window.addEventListener(DECK_WORKSPACE_NAVIGATION_EVENT, handler);
  return () => window.removeEventListener(DECK_WORKSPACE_NAVIGATION_EVENT, handler);
}
