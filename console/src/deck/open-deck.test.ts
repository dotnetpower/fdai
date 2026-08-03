import { afterEach, describe, expect, it, vi } from "vitest";
import {
  DECK_OPEN_EVENT,
  isDeckOpenListenerReady,
  DECK_WORKSPACE_NAVIGATION_EVENT,
  installWorkspaceDeckNavigationHandler,
  openDeckWithContext,
  openDeckWithPrompt,
  requestWorkspaceDeckCloseForNavigation,
  setDeckOpenListenerReady,
} from "./open-deck";

class FakeCustomEvent<T> {
  readonly type: string;
  readonly detail: T;
  constructor(type: string, init?: { detail?: T }) {
    this.type = type;
    this.detail = (init?.detail ?? {}) as T;
  }
}

afterEach(() => {
  setDeckOpenListenerReady(false);
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

describe("openDeckWithContext", () => {
  it("defers until the lazy Command Deck listener is ready", () => {
    const dispatch = vi.fn();
    vi.stubGlobal("CustomEvent", FakeCustomEvent);
    vi.stubGlobal("window", { dispatchEvent: dispatch });

    expect(isDeckOpenListenerReady()).toBe(false);
    expect(openDeckWithContext({ onlyWhenIdle: true })).toBe(false);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("reports when an idle-only open request is deferred", () => {
    vi.stubGlobal("CustomEvent", FakeCustomEvent);
    vi.stubGlobal("window", { dispatchEvent: () => false });
    setDeckOpenListenerReady(true);

    expect(openDeckWithContext({ onlyWhenIdle: true })).toBe(false);
  });

  it("dispatches a fresh agent-conversation request", () => {
    const dispatched: FakeCustomEvent<Record<string, unknown>>[] = [];
    setDeckOpenListenerReady(true);
    vi.stubGlobal("CustomEvent", FakeCustomEvent);
    vi.stubGlobal("window", {
      dispatchEvent: (event: FakeCustomEvent<Record<string, unknown>>) =>
        dispatched.push(event),
    });

    openDeckWithContext({
      sessionLabel: "Heimdall",
      newConversation: true,
      targetAgent: "Heimdall",
      prompt: "What has Heimdall been working on?",
    });

    expect(dispatched[0]?.detail).toMatchObject({
      sessionLabel: "Heimdall",
      newConversation: true,
      targetAgent: "Heimdall",
    });
    expect(dispatched[0]?.detail.sessionKey).toBeUndefined();
  });

  it("dispatches a structured incident binding", () => {
    const dispatched: FakeCustomEvent<Record<string, unknown>>[] = [];
    setDeckOpenListenerReady(true);
    vi.stubGlobal("CustomEvent", FakeCustomEvent);
    vi.stubGlobal("window", {
      dispatchEvent: (event: FakeCustomEvent<Record<string, unknown>>) =>
        dispatched.push(event),
    });

    openDeckWithContext({
      sessionKey: "agent:Var:incident:corr-selected",
      sessionLabel: "Var / INC-selected",
      prompt: "What is the root cause status?",
      binding: {
        kind: "incident",
        incidentId: "INC-selected",
        correlationId: "corr-selected",
        selectedAgent: "Var",
      },
    });

    expect(dispatched).toHaveLength(1);
    expect(dispatched[0]?.detail.binding).toEqual({
      kind: "incident",
      incidentId: "INC-selected",
      correlationId: "corr-selected",
      selectedAgent: "Var",
    });
  });
});

describe("requestWorkspaceDeckCloseForNavigation", () => {
  it("closes once and returns true when the workspace Deck accepts", () => {
    const target = new EventTarget();
    const closeDeck = vi.fn();
    vi.stubGlobal("window", target);
    const uninstall = installWorkspaceDeckNavigationHandler(() => true, closeDeck);

    expect(requestWorkspaceDeckCloseForNavigation()).toBe(true);
    expect(closeDeck).toHaveBeenCalledOnce();

    uninstall();
    expect(requestWorkspaceDeckCloseForNavigation()).toBe(false);
    expect(closeDeck).toHaveBeenCalledOnce();
  });

  it("returns false when the Deck is closed or not in workspace mode", () => {
    const target = new EventTarget();
    const closeDeck = vi.fn();
    vi.stubGlobal("window", target);
    installWorkspaceDeckNavigationHandler(() => false, closeDeck);

    expect(requestWorkspaceDeckCloseForNavigation()).toBe(false);
    expect(closeDeck).not.toHaveBeenCalled();
  });
});
