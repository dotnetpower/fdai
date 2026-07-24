/**
 * composer-attachment-store - a tiny external store that lifts staged image
 * attachments out of the self-contained composer so the deck submit path can
 * read them at send time and include them in the chat request.
 *
 * The console is read-only: an attachment is evidence for the narrator's vision
 * answer, never an action. This store holds only the send-ready payload
 * (name + media type + base64 data URL) for the NEXT turn; the composer syncs
 * it as images are staged/removed, and the submit hook `take`s (reads + clears)
 * it atomically so a concurrent composer clear cannot drop the payload.
 *
 * Bounds mirror the server parser: at most MAX_ATTACHMENTS images per turn.
 * Pure and DOM-free so it is unit-testable; the base64 read lives in the view.
 */

/** One send-ready inline image attachment (matches the chat request shape). */
export interface ChatAttachment {
  readonly name: string;
  readonly media_type: string;
  readonly data_url: string;
}

/** Per-turn image cap, symmetric to the server-side DEFAULT_MAX_IMAGES. */
export const MAX_ATTACHMENTS = 4;

const staged = new Map<string, ChatAttachment>();
const drainListeners = new Set<() => void>();

/** Subscribe to "the store was drained by a send". The composer uses this to
 *  clear its visual tray on both Enter-send and button-send (a form `submit`
 *  event fires only for the button), keeping the tray and the send payload in
 *  sync. Returns an unsubscribe function. */
export function subscribeComposerAttachmentDrain(listener: () => void): () => void {
  drainListeners.add(listener);
  return () => {
    drainListeners.delete(listener);
  };
}

/** Stage (or replace) one attachment by its composer id. Returns whether it
 *  was accepted; a new id is rejected (false) once the per-turn cap is reached
 *  so the browser cannot exceed the server bound and the composer can mark the
 *  overflow tile as non-sendable. */
export function stageComposerAttachment(id: string, attachment: ChatAttachment): boolean {
  if (!staged.has(id) && staged.size >= MAX_ATTACHMENTS) return false;
  staged.set(id, attachment);
  return true;
}

/** Remove one staged attachment by composer id. */
export function unstageComposerAttachment(id: string): void {
  staged.delete(id);
}

/** Read all staged attachments and clear the store atomically, then notify
 *  drain subscribers. Called by the submit path so exactly one turn owns the
 *  payload and a later composer clear cannot race it away. */
export function takeComposerAttachments(): ChatAttachment[] {
  const list = [...staged.values()];
  staged.clear();
  for (const listener of drainListeners) listener();
  return list;
}

/** Drop everything without returning it (e.g. conversation switch). */
export function clearComposerAttachments(): void {
  staged.clear();
}

/** How many attachments are currently staged (view/tests only). */
export function stagedComposerAttachmentCount(): number {
  return staged.size;
}
