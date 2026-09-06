import { describe, expect, it } from "vitest";
import { ConversationContextStore } from "./conversation-context";
import type { ViewSnapshot } from "./context";

const dashboard: ViewSnapshot = {
  routeId: "dashboard",
  routeLabel: "Dashboard",
  headline: "Synthetic dashboard",
  capturedAt: "2026-09-06T00:00:00Z",
  facts: [{ key: "count", value: 2 }],
};

describe("explicit conversation screen context", () => {
  it("starts general conversations without route evidence", () => {
    const contexts = new ConversationContextStore();
    expect(contexts.activate("general", "general", dashboard)).toEqual({
      mode: "general", snapshot: null,
    });
  });

  it("keeps a detached screen snapshot when routes or live data change", () => {
    const contexts = new ConversationContextStore();
    const selected = contexts.activate("screen", "screen", dashboard);
    expect(selected.snapshot).toEqual(dashboard);
    expect(selected.snapshot).not.toBe(dashboard);
    expect(selected.snapshot?.facts).not.toBe(dashboard.facts);
    expect(contexts.activate("screen", "screen", {
      ...dashboard, routeId: "audit", routeLabel: "Audit",
    })).toBe(selected);
  });

  it("preserves optional general context and explicit removal across entry switches", () => {
    const contexts = new ConversationContextStore();
    contexts.activate("general", "general", dashboard);
    const attached = contexts.attach("general", dashboard);
    expect(attached.mode).toBe("general");
    expect(attached.snapshot).toEqual(dashboard);
    contexts.activate("screen", "screen", dashboard);
    expect(contexts.activate("general", "general", null)).toBe(attached);
    contexts.attach("general", null);
    expect(contexts.activate("general", "general", dashboard).snapshot).toBeNull();
    expect(contexts.activate("screen", "screen", null).snapshot).toEqual(dashboard);
  });

  it("keeps unavailable context explicit and forgets removed conversations", () => {
    const contexts = new ConversationContextStore();
    expect(contexts.activate("screen", "screen", null).snapshot).toBeNull();
    contexts.remove("screen");
    expect(contexts.activate("screen", "screen", dashboard).snapshot).toEqual(dashboard);
    expect(() => contexts.attach("missing", dashboard)).toThrow("Activate the conversation");
  });
});
