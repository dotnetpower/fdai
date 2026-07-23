import { describe, expect, it, vi } from "vitest";

import { selectConversationWithRoute } from "./conversation-navigation";
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
  it("reopens the deck after navigating to a previous screen conversation", () => {
    const events: string[] = [];

    selectConversationWithRoute(PREVIOUS, "/agents", "current-key", {
      navigate: (path) => events.push(`navigate:${path}`),
      activate: () => events.push("activate"),
      reopen: () => events.push("reopen"),
      focus: () => events.push("focus"),
    });

    expect(events).toEqual([
      "navigate:/overview",
      "activate",
      "reopen",
      "focus",
    ]);
  });

  it("activates an inactive same-route conversation without navigation", () => {
    const navigate = vi.fn();
    const reopen = vi.fn();
    const activate = vi.fn();
    const focus = vi.fn();

    selectConversationWithRoute(PREVIOUS, "/overview", "another-key", {
      navigate,
      activate,
      reopen,
      focus,
    });

    expect(navigate).not.toHaveBeenCalled();
    expect(reopen).not.toHaveBeenCalled();
    expect(activate).toHaveBeenCalledOnce();
    expect(focus).toHaveBeenCalledOnce();
  });

  it("does not reload the active same-route conversation from cache", () => {
    const navigate = vi.fn();
    const reopen = vi.fn();
    const activate = vi.fn();
    const focus = vi.fn();

    selectConversationWithRoute(PREVIOUS, "/overview", PREVIOUS.key, {
      navigate,
      activate,
      reopen,
      focus,
    });

    expect(navigate).not.toHaveBeenCalled();
    expect(activate).not.toHaveBeenCalled();
    expect(reopen).not.toHaveBeenCalled();
    expect(focus).toHaveBeenCalledOnce();
  });

  it("keeps agent conversations on the current screen", () => {
    const navigate = vi.fn();
    const reopen = vi.fn();

    selectConversationWithRoute(
      { ...PREVIOUS, kind: "agent", agent: "Forseti" },
      "/agents",
      "another-key",
      { navigate, reopen, activate: vi.fn(), focus: vi.fn() },
    );

    expect(navigate).not.toHaveBeenCalled();
    expect(reopen).not.toHaveBeenCalled();
  });
});
