import { beforeEach, describe, expect, it, vi } from "vitest";
import type { UserContextPayload, UserPreferencePayload } from "../user-context-client";

const harness = vi.hoisted(() => {
  let slots: unknown[] = [];
  let index = 0;
  return {
    reset() { slots = []; index = 0; },
    render() { index = 0; },
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const position = index++;
      if (!(position in slots)) slots[position] = typeof initial === "function" ? (initial as () => T)() : initial;
      return [slots[position] as T, (next) => {
        slots[position] = typeof next === "function" ? (next as (current: T) => T)(slots[position] as T) : next;
      }];
    },
    useRef<T>(initial: T): { current: T } {
      const position = index++;
      if (!(position in slots)) slots[position] = { current: initial };
      return slots[position] as { current: T };
    },
  };
});

vi.mock("preact/hooks", () => ({ useState: harness.useState, useRef: harness.useRef, useEffect: () => undefined }));
vi.mock("../deck/context", () => ({ usePublishViewContext: () => undefined }));
vi.mock("../i18n", () => ({ getLocale: () => "en", t: (key: string) => key }));
vi.mock("../preferences", () => ({
  PREFERENCES_CHANGED_EVENT: "preferences",
  readConsolePreferences: () => ({ locale: "en", theme: "light", motion: "system", showTokenUsage: false, showModelTrace: false }),
  resetConsolePreferences: vi.fn(() => true), setConsolePreference: vi.fn(() => true),
}));
vi.mock("../mutation-intent", () => ({
  identityForMutationIntent: () => ({ idempotencyKey: "test-key", intentId: "test-intent" }),
}));
vi.mock("../user-context-client", () => ({
  fetchUserContext: vi.fn(), putUserPreference: vi.fn(), putConversationPolicy: vi.fn(),
  createBriefingSubscription: vi.fn(), deleteConversationPolicy: vi.fn(),
  deleteBriefingSubscription: vi.fn(), deleteUserPreference: vi.fn(), deleteUserMemory: vi.fn(),
}));

import * as requests from "../user-context-client";
import { useSettingsController } from "./settings.controller";
import type { OperatorApiClient } from "../api";

const preference: UserPreferencePayload = {
  principal_id: "operator-example", locale: "en", verbosity: "concise", answer_detail: "standard",
  answer_format: "prose", answer_preferences_enabled: true, answer_intent_detail: {},
  answer_intent_format: {}, timezone: "UTC", share_with_learner: false, revision: 1,
};
const context = (saved = preference): UserContextPayload => ({
  preference: saved, memories: [], policies: [], subscriptions: [], briefing_runs: [],
  conversations: [{ latest_operator_turn_id: "turn-example" } as never],
  scheduled_continuations: [],
  conversation_page: { has_more: false, next_cursor: null },
});
const render = () => { harness.render(); return useSettingsController({} as OperatorApiClient); };

// These action-unit tests exercise async controller logic with mocked hooks, not DOM or effect lifecycle.
describe("General settings action recovery", () => {
  beforeEach(() => {
    harness.reset();
    vi.clearAllMocks();
    vi.stubGlobal("window", { confirm: vi.fn(() => false), location: { reload: vi.fn() } });
    vi.stubGlobal("document", { getElementById: vi.fn(() => ({ focus: vi.fn() })) });
    vi.mocked(requests.fetchUserContext).mockResolvedValue(context());
    vi.mocked(requests.putConversationPolicy).mockResolvedValue({} as never);
  });

  it("does not reset an unloaded account or mutate after cancellation", async () => {
    let controller = render();
    await controller.reset();
    expect(window.confirm).not.toHaveBeenCalled();
    await controller.refreshContext();
    controller = render();
    await controller.reset();
    expect(window.confirm).toHaveBeenCalledOnce();
    expect(requests.deleteUserPreference).not.toHaveBeenCalled();
  });

  it("sends trimmed timezones in preference and briefing requests", async () => {
    let controller = render();
    await controller.refreshContext();
    controller = render();
    controller.setTimezone(" Asia/Seoul ");
    controller = render();
    vi.mocked(requests.putUserPreference).mockResolvedValue({ ...preference, timezone: "Asia/Seoul", revision: 2 });
    await controller.saveContextPreferences();
    expect(requests.putUserPreference).toHaveBeenCalledWith(expect.objectContaining({ timezone: "Asia/Seoul" }));
    controller = render();
    controller.setTimezone(" UTC ");
    controller = render();
    await controller.addDailyBriefing();
    expect(requests.createBriefingSubscription).toHaveBeenCalledWith(expect.objectContaining({ timezone: "UTC" }), "test-key");
  });

  it("keeps edits made while a preference save is pending", async () => {
    let controller = render();
    await controller.refreshContext();
    controller = render();
    controller.setAnswerDetail("deep");
    controller = render();
    let finish!: (value: UserPreferencePayload) => void;
    vi.mocked(requests.putUserPreference).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    const save = controller.saveContextPreferences();
    controller = render();
    controller.setAnswerFormat("bullets");
    const saved = { ...preference, answer_detail: "deep" as const, revision: 2 };
    vi.mocked(requests.fetchUserContext).mockResolvedValue(context(saved));
    finish(saved);
    await save;
    controller = render();
    expect(controller.answerFormat).toBe("bullets");
    expect(controller.contextDirty).toBe(true);
  });

  it("does not hide readback failure after successful briefing creation", async () => {
    let controller = render();
    await controller.refreshContext();
    controller = render();
    vi.mocked(requests.fetchUserContext).mockRejectedValue(new Error("Readback unavailable"));
    await controller.addDailyBriefing();
    expect(render().contextError).toBe("Readback unavailable");
    expect(requests.createBriefingSubscription).toHaveBeenCalledOnce();
  });

  it("recovers only the unfinished policy after a partial save", async () => {
    let controller = render();
    await controller.refreshContext();
    controller = render();
    controller.setAnswerDetail("deep");
    controller = render();
    const saved = { ...preference, answer_detail: "deep" as const, revision: 2 };
    vi.mocked(requests.putUserPreference).mockResolvedValue(saved);
    vi.mocked(requests.putConversationPolicy).mockRejectedValueOnce(new Error("Policy unavailable"));
    await controller.saveContextPreferences();
    controller = render();
    expect(controller.pendingResponsePolicy).not.toBeNull();
    expect(controller.preferenceDirty).toBe(false);
    expect(controller.contextDirty).toBe(true);
    vi.mocked(requests.fetchUserContext).mockResolvedValue(context(saved));
    await controller.retryResponsePolicy();
    expect(requests.putUserPreference).toHaveBeenCalledOnce();
    expect(requests.putConversationPolicy).toHaveBeenCalledTimes(2);
    expect(render().pendingResponsePolicy).toBeNull();
  });

  it("preserves unsaved account edits when refreshing related records", async () => {
    let controller = render();
    await controller.refreshContext();
    controller = render();
    controller.setAnswerFormat("mixed");
    controller = render();
    await controller.refreshContext();
    expect(render().answerFormat).toBe("mixed");
    controller = render();
    controller.discardContextChanges();
    expect(render().answerFormat).toBe("prose");
    expect(requests.putUserPreference).not.toHaveBeenCalled();
  });

  it("retains a failed initial read as unknown and blocks preference writes", async () => {
    vi.mocked(requests.fetchUserContext).mockRejectedValue(new Error("Context unavailable"));
    let controller = render();
    await controller.refreshContext();
    controller = render();
    expect(controller.serverContext).toBeNull();
    expect(controller.contextError).toBe("Context unavailable");
    controller.setAnswerDetail("deep");
    controller = render();
    await controller.saveContextPreferences();
    expect(requests.putUserPreference).not.toHaveBeenCalled();
  });
});
