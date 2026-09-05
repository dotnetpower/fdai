import { afterEach, describe, expect, it, vi } from "vitest";
import {
  decodeHandoverInvitation,
  handoverLoginSessionId,
  offerProactiveHandover,
} from "./handover-invitation";
import { PANTHEON } from "./routes/agents.model";
import { PANTHEON_NAMES } from "./pantheon-names";
import {
  clearPendingDeckOpenRequests,
  setDeckOpenListenerReady,
} from "./deck/open-deck";

class MemoryStorage implements Storage {
  readonly #values = new Map<string, string>();
  get length() { return this.#values.size; }
  clear() { this.#values.clear(); }
  getItem(key: string) { return this.#values.get(key) ?? null; }
  key(index: number) { return [...this.#values.keys()][index] ?? null; }
  removeItem(key: string) { this.#values.delete(key); }
  setItem(key: string, value: string) { this.#values.set(key, value); }
}

class FakeCustomEvent<T> {
  readonly type: string;
  readonly detail: T;
  constructor(type: string, init?: { detail?: T }) {
    this.type = type;
    this.detail = init?.detail as T;
  }
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setDeckOpenListenerReady(false);
  clearPendingDeckOpenRequests();
});

describe("handover invitation", () => {
  it("keeps the lightweight Pantheon name contract aligned with the roster", () => {
    expect(PANTHEON_NAMES).toEqual(PANTHEON.map((agent) => agent.name));
  });

  it("decodes an authority-free invitation", () => {
    expect(decodeHandoverInvitation({
      invitation: {
        invitation_id: "invite-1",
        goal_id: "goal-1",
        goal_revision: 1,
        agent_name: "Muninn",
        session_id: "session-1",
        max_questions: 3,
        max_minutes: 5,
        source_revision: "revision-7",
        execution_authority: false,
      },
    })).toEqual({
      invitationId: "invite-1",
      goalId: "goal-1",
      goalRevision: 1,
      agentName: "Muninn",
      sessionId: "session-1",
      maxQuestions: 3,
      maxMinutes: 5,
      sourceRevision: "revision-7",
    });
  });

  it("rejects an unknown agent or authority-bearing response", () => {
    expect(() => decodeHandoverInvitation({
      invitation: {
        invitation_id: "invite-1",
        goal_id: "goal-1",
        goal_revision: 1,
        agent_name: "Unknown",
        session_id: "session-1",
        max_questions: 3,
        max_minutes: 5,
        source_revision: "revision-7",
        execution_authority: true,
      },
    })).toThrow("malformed");
  });

  it("reuses one login session id", () => {
    const storage = new MemoryStorage();
    const first = handoverLoginSessionId(storage);
    expect(handoverLoginSessionId(storage)).toBe(first);
  });

  it("opens a mapped agent conversation from the server invitation", async () => {
    const storage = new MemoryStorage();
    const invitation = {
      invitationId: "invite-1",
      goalId: "goal-1",
      goalRevision: 1,
      agentName: "Muninn",
      sessionId: "session-1",
      maxQuestions: 3,
      maxMinutes: 5,
      sourceRevision: "revision-7",
    } as const;
    const load = vi.fn().mockResolvedValue(invitation);
    const dispatched: FakeCustomEvent<Record<string, unknown>>[] = [];
    vi.stubGlobal("CustomEvent", FakeCustomEvent);
    vi.stubGlobal("window", {
      dispatchEvent: (event: FakeCustomEvent<Record<string, unknown>>) => {
        dispatched.push(event);
        return true;
      },
    });
    setDeckOpenListenerReady(true);

    await offerProactiveHandover({} as never, storage, load);

    expect(load).toHaveBeenCalledOnce();
    expect(dispatched.at(-1)?.detail).toMatchObject({
      sessionKey: "handover:goal-1",
      targetAgent: "Muninn",
      onlyWhenIdle: true,
    });
  });
});
