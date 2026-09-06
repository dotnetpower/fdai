import type { ViewSnapshot } from "./context";
import type { DeckContextMode } from "./open-deck";

export interface ConversationContext {
  readonly mode: DeckContextMode;
  readonly snapshot: ViewSnapshot | null;
}

/** A tab-local, explicit selection. Route changes never rewrite an existing selection. */
export class ConversationContextStore {
  private readonly contexts = new Map<string, ConversationContext>();

  activate(
    key: string,
    mode: DeckContextMode,
    snapshot: ViewSnapshot | null,
  ): ConversationContext {
    const existing = this.contexts.get(key);
    if (existing) return existing;
    const context = {
      mode,
      snapshot: mode === "screen" && snapshot ? structuredClone(snapshot) : null,
    };
    this.contexts.set(key, context);
    return context;
  }

  attach(key: string, snapshot: ViewSnapshot | null): ConversationContext {
    const existing = this.contexts.get(key);
    if (!existing) throw new Error("Activate the conversation before selecting its screen context.");
    const context = { ...existing, snapshot: snapshot ? structuredClone(snapshot) : null };
    this.contexts.set(key, context);
    return context;
  }

  remove(key: string): void {
    this.contexts.delete(key);
  }
}
