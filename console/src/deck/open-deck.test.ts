import { afterEach, describe, expect, it, vi } from "vitest";
import { DECK_OPEN_EVENT, openDeckWithPrompt } from "./open-deck";

class FakeCustomEvent<T> {
  readonly type: string;
  readonly detail: T;
  constructor(type: string, init?: { detail?: T }) {
    this.type = type;
    this.detail = (init?.detail ?? {}) as T;
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("openDeckWithPrompt", () => {
  it("dispatches the deck-open event with a seeded prompt", () => {
    const dispatched: FakeCustomEvent<{ prompt?: string }>[] = [];
    vi.stubGlobal("CustomEvent", FakeCustomEvent);
    vi.stubGlobal("window", {
      dispatchEvent: (e: FakeCustomEvent<{ prompt?: string }>) => dispatched.push(e),
    });

    openDeckWithPrompt("what is the root cause?");

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0]?.type).toBe(DECK_OPEN_EVENT);
    expect(dispatched[0]?.detail.prompt).toBe("what is the root cause?");
  });

  it("dispatches an event with no prompt when none is given", () => {
    const dispatched: FakeCustomEvent<{ prompt?: string }>[] = [];
    vi.stubGlobal("CustomEvent", FakeCustomEvent);
    vi.stubGlobal("window", {
      dispatchEvent: (e: FakeCustomEvent<{ prompt?: string }>) => dispatched.push(e),
    });

    openDeckWithPrompt();

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0]?.detail.prompt).toBeUndefined();
  });

  it("is a no-op when window is unavailable (SSR)", () => {
    vi.stubGlobal("window", undefined);
    expect(() => openDeckWithPrompt("x")).not.toThrow();
  });
});
