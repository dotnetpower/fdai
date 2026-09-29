import { afterEach, describe, expect, it, vi } from "vitest";
import { decodeTestContextChoices, decodeTestContextStatus, readTestContextStatus, submitTestContextCommand, targetMatchesChoice, validProposalId } from "./test-context-status";

const id = "example-command";

const contextDraft = {
  target_ref: "resource-example", signal_code: "cpu_percent", source_ref: "turn:example",
  semantic_receipt: `sha256:${"a".repeat(64)}`, authority: "candidate_only" as const, execution_authority: false as const,
  window: { expected_min: 60, expected_max: 90,
    effective_from: "2026-09-15T10:00:00+00:00", effective_to: "2026-09-15T11:00:00+00:00" },
};

const statusRequest = {
  operation: "propose", context_id: "case-one:cpu_percent:aaaaaaaaaaaaaaaa",
  access_scope_digest: "a".repeat(64), target_ref: "resource-example",
  signal_code: "cpu_percent", expected_revision: 0, policy_revision: "policy:example",
  source_ref: "turn:example", semantic_receipt: `sha256:${"a".repeat(64)}`,
  expected_min: 60, expected_max: 90,
  effective_from: "2026-09-15T10:00:00+00:00", effective_to: "2026-09-15T11:00:00+00:00",
};
const pending = {
  proposal_id: id,
  operation: "test-context.propose",
  dispatch_status: "pending",
  accepted_at: "2026-09-15T00:00:00Z",
  policy_application: "unknown",
  current_authorization: "not_evaluated",
  execution_authority: false,
  request: statusRequest,
  reviewer_transition_allowed: false,
  requester_is_current_principal: true,
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
      ...applied, operation: "test-context.revoke", current_authorization: "not_evaluated",
      context_application: { state: "revoked", revision: 3, execution_authority: false },
    }, id)).toMatchObject({ application: { state: "revoked" }, currentAuthorization: "not_evaluated" });
    const reviewed = {
      ...applied, operation: "test-context.review",
      context_application: { state: "reviewed", revision: 2, execution_authority: false },
    };
    expect(decodeTestContextStatus({ ...reviewed, current_authorization: "expired" }, id)
      ?.currentAuthorization).toBe("expired");
    expect(decodeTestContextStatus({ ...reviewed, current_authorization: "active" }, id)
      ?.currentAuthorization).toBe("active");
  });
  it.each([
    { ...pending, proposal_id: "other" },
    { ...pending, execution_authority: true },
    { ...pending, reviewer_transition_allowed: "yes" },
    { ...pending, requester_is_current_principal: "yes" },
    { ...pending, dispatch_status: "completed" },
    { ...pending, policy_application: "recorded" },
    { ...pending, context_application: applied.context_application },
    { ...applied, dispatch_status: "rejected" },
    { ...applied, context_application: { ...applied.context_application, state: "reviewed" } },
    { ...applied, context_application: { ...applied.context_application, execution_authority: true } },
    { ...applied, context_application: { ...applied.context_application, revision: 0 } },
    { ...applied, current_authorization: "active" },
    { ...applied, current_authorization: "expired" },
    { ...applied, operation: "test-context.revoke", current_authorization: "active",
      context_application: { state: "revoked", revision: 3, execution_authority: false } },
    { ...pending, current_authorization: "revoked" },
    { ...pending, accepted_at: "yesterday" },
    { ...pending, request: { ...statusRequest, target_ref: "" } },
  ])("withholds invalid or contradictory evidence", (value) => {
    expect(decodeTestContextStatus(value, id)).toBeNull();
  });

  it("accepts real review and revoke status requests without null proposal fields", () => {
    const reviewRequest = {
      operation: "review", context_id: "proposal-context", access_scope_digest: "a".repeat(64),
      target_ref: "vm-b", signal_code: "cpu_percent", expected_revision: 1,
      policy_revision: "policy:example", source_ref: "turn:proposal",
      semantic_receipt: `sha256:${"c".repeat(64)}`,
    };
    const reviewed = {
      ...pending, proposal_id: "review-command", operation: "test-context.review",
      policy_application: "recorded", dispatch_status: "published", current_authorization: "not_evaluated",
      reviewer_transition_allowed: true, requester_is_current_principal: false, request: reviewRequest,
      context_application: { state: "reviewed", revision: 2, execution_authority: false },
    };
    const revoked = {
      ...reviewed, proposal_id: "revoke-command", operation: "test-context.revoke",
      current_authorization: "not_evaluated",
      context_application: { state: "revoked", revision: 3, execution_authority: false },
    };
    expect(decodeTestContextStatus(reviewed, "review-command")?.request.targetRef).toBe("vm-b");
    expect(decodeTestContextStatus(revoked, "revoke-command")?.application?.state).toBe("revoked");
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


describe("test context reviewed choices and submission", () => {
  const choicePayload = {
    schema_version: "1.0.0",
    source_revision: "sha256:" + "b".repeat(64) + "#7",
    choices: [{
      case_scope_id: "case-one",
      access_scope_digest: "a".repeat(64),
      target_selectors: ["resource-example"],
      policy_revision: "policy:example",
      source_revision: "sha256:" + "b".repeat(64) + "#7",
      allowed_operations: ["propose", "review", "revoke"],
      execution_authority: false,
    }],
    unavailable_reasons: [],
    execution_authority: false,
  };

  it("renders only no-authority server choices that match the source draft", () => {
    const decoded = decodeTestContextChoices(choicePayload);
    expect(decoded?.choices).toHaveLength(1);
    expect(targetMatchesChoice(contextDraft, decoded!.choices[0]!)).toBe(true);
    expect(targetMatchesChoice({ ...contextDraft, target_ref: "other" }, decoded!.choices[0]!)).toBe(false);
    expect(decodeTestContextChoices({ ...choicePayload, execution_authority: true })).toBeNull();
    expect(decodeTestContextChoices({ ...choicePayload, schema_version: "0.9.0" })).toBeNull();
  });

  it("submits through authenticated lifecycle APIs and binds status to the returned id", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ accepted: true, proposal_id: "proposal-one", duplicate: false }),
    });
    vi.stubGlobal("fetch", fetch);
    const choice = decodeTestContextChoices(choicePayload)!.choices[0]!;
    await expect(submitTestContextCommand("propose", contextDraft, choice, 0, undefined, undefined)).resolves.toEqual({
      kind: "accepted", proposalId: "proposal-one", duplicate: false,
    });
    expect(fetch.mock.calls[0]?.[0]).toContain("/test-context/proposals");
    expect(JSON.parse(fetch.mock.calls[0]?.[1].body)).toMatchObject({
      operation: "propose",
      access_scope_digest: "a".repeat(64),
      target_ref: "resource-example",
      policy_revision: "policy:example",
      expected_revision: 0,
    });
    await submitTestContextCommand("review", contextDraft, choice, 1, {
      contextId: "proposal-context", accessScopeDigest: "a".repeat(64), targetRef: "resource-example",
      signalCode: "cpu_percent", policyRevision: "policy:example", sourceRef: "turn:proposal",
      semanticReceipt: `sha256:${"c".repeat(64)}`,
    }, undefined);
    expect(fetch.mock.calls[1]?.[0]).toContain("/test-context/reviews");
    expect(JSON.parse(fetch.mock.calls[1]?.[1].body)).toMatchObject({
      operation: "review", context_id: "proposal-context", expected_revision: 1,
      source_ref: "turn:proposal", semantic_receipt: `sha256:${"c".repeat(64)}`,
    });
  });
});
