import { afterEach, describe, expect, it, vi } from "vitest";
import { decodeTestContextStatus, readTestContextStatus, validProposalId } from "./test-context-status";

const id = "example-command";
const pending = {
  proposal_id: id,
  operation: "test-context.propose",
  dispatch_status: "pending",
  accepted_at: "2026-09-15T00:00:00Z",
  policy_application: "unknown",
  current_authorization: "not_evaluated",
  execution_authority: false,
  context_application: null,
};
const applied = {
  ...pending, dispatch_status: "published", policy_application: "recorded",
  context_application: { state: "proposed", revision: 1, execution_authority: false },
};

afterEach(() => vi.unstubAllGlobals());

describe("principal-scoped context command status", () => {
  it("keeps broker delivery, audited history and current authorization independent", () => {
    expect(decodeTestContextStatus(pending, id)).toMatchObject({
      delivery: "pending", policyApplication: "unknown", currentAuthorization: "not_evaluated",
    });
    expect(decodeTestContextStatus(applied, id)).toMatchObject({
      delivery: "published", policyApplication: "recorded", currentAuthorization: "not_evaluated",
      application: { state: "proposed", revision: 1 },
    });
    expect(decodeTestContextStatus({
      ...applied, operation: "test-context.revoke", current_authorization: "revoked",
      context_application: { state: "revoked", revision: 3, execution_authority: false },
    }, id)).toMatchObject({ application: { state: "revoked" }, currentAuthorization: "revoked" });
    expect(decodeTestContextStatus({ ...applied, current_authorization: "expired" }, id)
      ?.currentAuthorization).toBe("expired");
  });
  it.each([
    { ...pending, proposal_id: "other" },
    { ...pending, execution_authority: true },
    { ...pending, current_authorization: "active" },
    { ...pending, dispatch_status: "completed" },
    { ...pending, policy_application: "recorded" },
    { ...pending, context_application: applied.context_application },
    { ...applied, dispatch_status: "rejected" },
    { ...applied, context_application: { ...applied.context_application, state: "reviewed" } },
    { ...applied, context_application: { ...applied.context_application, execution_authority: true } },
    { ...applied, context_application: { ...applied.context_application, revision: 0 } },
    { ...pending, accepted_at: "yesterday" },
  ])("withholds invalid or contradictory evidence", (value) => {
    expect(decodeTestContextStatus(value, id)).toBeNull();
  });
  it("rejects unsafe identity before any network request", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(validProposalId(" x")).toBe(false);
    expect(await readTestContextStatus(" x")).toEqual({ kind: "error" });
    expect(fetch).not.toHaveBeenCalled();
  });
  it("reads a no-store projection and separates unavailable from errors", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => pending })
      .mockResolvedValueOnce({ status: 404, ok: false })
      .mockResolvedValueOnce({ status: 401, ok: false })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ ...pending, execution_authority: true }) });
    vi.stubGlobal("fetch", fetch);
    expect((await readTestContextStatus(id)).kind).toBe("ready");
    expect(fetch.mock.calls[0]?.[0]).toContain("/test-context/commands/example-command");
    expect(fetch.mock.calls[0]?.[1]).toMatchObject({ cache: "no-store" });
    expect(await readTestContextStatus(id)).toEqual({ kind: "unavailable" });
    expect(await readTestContextStatus(id)).toEqual({ kind: "error" });
    expect(await readTestContextStatus(id)).toEqual({ kind: "error" });
  });
});
