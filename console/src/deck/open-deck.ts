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

/** Detail payload carried by a {@link DECK_OPEN_EVENT}. */
export interface DeckOpenDetail {
  /** Optional draft to seed the deck input with (the operator still sends it). */
  readonly prompt?: string;
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
