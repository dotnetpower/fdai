import { describe, expect, it, vi } from "vitest";

import {
  runConversationRouteNavigation,
  selectConversationWithRoute,
} from "./conversation-navigation";
import type { ConversationSummary } from "./conversation-sessions";

const PREVIOUS: ConversationSummary = {
  key: "screen:scope:/overview",
  label: "Dashboard",
  kind: "screen-default",
  originPath: "/overview",
  originLabel: "Dashboard",
  createdAt: "2026-07-23T08:00:00Z",
  updatedAt: "2026-07-23T09:00:00Z",
};

describe("conversation route selection", () => {
  it("activates after navigating without a reopen workaround", () => {
    const events: string[] = [];

    selectConversationWithRoute(PREVIOUS, "/agents", "current-key", {
      navigate: (path) => events.push(`navigate:${path}`),
      activate: () => events.push("activate"),
      focus: () => events.push("focus"),
    });

    expect(events).toEqual([
      "navigate:/overview",
      "activate",
      "focus",
    ]);
  });

  it("activates an inactive same-route conversation without navigation", () => {
    const navigate = vi.fn();
    const activate = vi.fn();
    const focus = vi.fn();

    selectConversationWithRoute(PREVIOUS, "/overview", "another-key", {
      navigate,
      activate,
      focus,
    });

    expect(navigate).not.toHaveBeenCalled();
    expect(activate).toHaveBeenCalledOnce();
    expect(focus).toHaveBeenCalledOnce();
  });

  it("does not reload the active same-route conversation from cache", () => {
    const navigate = vi.fn();
    const activate = vi.fn();
    const focus = vi.fn();

    selectConversationWithRoute(PREVIOUS, "/overview", PREVIOUS.key, {
      navigate,
      activate,
      focus,
    });

    expect(navigate).not.toHaveBeenCalled();
    expect(activate).not.toHaveBeenCalled();
    expect(focus).toHaveBeenCalledOnce();
  });

  it("keeps agent conversations on the current screen", () => {
    const navigate = vi.fn();

    selectConversationWithRoute(
      { ...PREVIOUS, kind: "agent", agent: "Forseti" },
      "/agents",
      "another-key",
      { navigate, activate: vi.fn(), focus: vi.fn() },
    );

    expect(navigate).not.toHaveBeenCalled();
  });

  it("restores general conversations without navigating to their creation screen", () => {
    const navigate = vi.fn();
    const activate = vi.fn();
    selectConversationWithRoute(
      { ...PREVIOUS, kind: "screen-thread", contextMode: "general" },
      "/agents",
      "another-key",
      { navigate, activate, focus: vi.fn() },
    );
    expect(navigate).not.toHaveBeenCalled();
    expect(activate).toHaveBeenCalledOnce();
  });

  it("marks only the synchronous conversation route event as suppressed", () => {
    const navigating = { current: false };
    const observed: boolean[] = [];

    runConversationRouteNavigation("/overview", navigating, () => {
      observed.push(navigating.current);
    });

    expect(observed).toEqual([true]);
    expect(navigating.current).toBe(false);
  });

  it("clears route suppression when navigation throws", () => {
    const navigating = { current: false };

    expect(() => runConversationRouteNavigation("/overview", navigating, () => {
      throw new Error("navigation failed");
    })).toThrow("navigation failed");
    expect(navigating.current).toBe(false);
  });
});
