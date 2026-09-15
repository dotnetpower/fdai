import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ScopedDutyApi, decodeScopedDutyCase, decodeScopedDutyCatalog,
  decodeScopedDutyProjection, decodeScopedDutyProposal,
} from "./scoped-duty-api";
import { isScopedDutyFresh, scopedDutyCreationFor, type ScopedDutyCaseRead, type ScopedDutyDraft, type ScopedDutyState } from "./scoped-duty-model";

const CASE_ID = `operator-${"a".repeat(32)}`;
const OTHER_CASE = `operator-${"b".repeat(32)}`;
const CORE_ID = "00000000-0000-0000-0000-000000000001";
const PRIMARY = "00000000-0000-0000-0000-000000000002";
const BACKUP = "00000000-0000-0000-0000-000000000003";
const REQUESTER = "00000000-0000-0000-0000-000000000004";
const OWNERS = ["00000000-0000-0000-0000-000000000005", "00000000-0000-0000-0000-000000000006"];
const DIGEST = "a".repeat(64);
const WINDOW = { source_revision: `sha256:${DIGEST}`, observed_at: "2026-09-15T11:59:30Z",
  expires_at: "2026-09-15T12:01:00Z", execution_authority: false as const };

function draft(): ScopedDutyDraft {
  return { request: { schema_version: "1.0.0", source_revision: WINDOW.source_revision, supersedes_case_id: null,
    bindings: [PRIMARY, BACKUP].map((ref, index) => ({ subject: { kind: "user", ref }, agent_name: "Odin", scope_ref: "scope:example",
      duty: index === 0 ? "primary" : "backup", effective_from: "2026-09-15T11:00:00Z", effective_until: "2026-09-16T12:00:00Z", fallback: null })) },
    justification: "Review independent ownership of this exact example scope." };
}
function proposal(caseId = CASE_ID) {
  return { case_id: caseId, proposal_id: caseId, accepted_at: "2026-09-15T12:00:00Z", state: "awaiting_core", execution_authority: false };
}
function coverage() {
  return { agent_name: "Odin", scope_ref: "scope:example", primary_refs: [PRIMARY], backup_refs: [BACKUP], escalation_refs: [], held_reasons: [] as string[] };
}
function rawCase(state: ScopedDutyState = "pending_review") {
  const input = draft().request;
  const approved = ["approved", "ownership_pr_open", "ownership_merged"].includes(state);
  const opened = ["ownership_pr_open", "ownership_merged"].includes(state);
  return { case_id: CASE_ID, core_case_id: CORE_ID, requester_ref: REQUESTER, state, revision: approved ? 4 : 2,
    request: input, plan: { kind: "scoped_duty_review", schema_version: "1.0.0", source_revision: input.source_revision,
      input_digest: DIGEST, digest: DIGEST, resolution_at: WINDOW.observed_at, checked_at: WINDOW.observed_at,
      coverage_basis: "current_observation_only", current_coverage: true, review_required: true, execution_authority: false,
      policy: { max_resolution_age_microseconds: 300_000_000, read_timeout_seconds: 5.0, total_timeout_seconds: 120.0 },
      bindings: input.bindings.map((binding) => ({ binding, scope: { scope_ref: binding.scope_ref, source_revision: input.source_revision },
        resolution: { subject: binding.subject, people: [binding.subject], at: WINDOW.observed_at,
          observed_at: WINDOW.observed_at, valid_until: WINDOW.expires_at, provenance_ref: "directory:example", provenance_digest: DIGEST, complete: true },
        held_reason: null, schedule_failure: null, used_fallback: false, digest: DIGEST })), coverage: [coverage()] },
    reviews: approved ? OWNERS.map((reviewer_ref) => ({ reviewer_ref, decision: "approve", plan_digest: DIGEST, reviewed_at: "2026-09-15T11:59:45Z" })) : [],
    pr_ref: opened ? "https://example.com/pull/1" : null, candidate_digest: opened ? DIGEST : null,
    merge_commit_sha: state === "ownership_merged" ? "b".repeat(40) : null, execution_authority: false };
}
function observed() {
  return { ...WINDOW, ...coverage(), state: "observed", partial: false, invalid_cases: 0,
    case_id: CORE_ID, case_revision: 5, candidate_digest: DIGEST, merge_commit_sha: "b".repeat(40), pr_ref: "https://example.com/pull/1" };
}
function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
function harness(timeout = 10_000) {
  const client = { operatorApiBaseUrl: "https://example.com", authorizationHeader: vi.fn(async (): Promise<string | null> => null) };
  const fetcher = vi.fn<typeof fetch>();
  return { client, fetcher, api: new ScopedDutyApi(client, fetcher, timeout) };
}
afterEach(() => { vi.useRealTimers(); });

describe("scoped duty API contract decoders", () => {
  it("retains the full revision and all 1000 allowed scopes without normalizing their case", () => {
    const scopes = Array.from({ length: 1000 }, (_, index) => `scope:Example-${index}`);
    const value = decodeScopedDutyCatalog({ ...WINDOW, scopes, artifact_delivery_available: false });
    expect(value.scopes).toEqual(scopes);
    expect(value.source_revision).toBe(WINDOW.source_revision);
    expect(value.artifact_delivery_available).toBe(false);
  });

  it.each([0, "false", true, null])("rejects coerced no-authority value %s", (execution_authority) => {
    expect(() => decodeScopedDutyCatalog({ ...WINDOW, scopes: ["scope:example"], artifact_delivery_available: true, execution_authority })).toThrow();
  });

  it("rejects duplicate scopes and missing completeness-relevant catalog fields", () => {
    expect(() => decodeScopedDutyCatalog({ ...WINDOW, scopes: ["scope:example", "scope:example"], artifact_delivery_available: true })).toThrow();
    expect(() => decodeScopedDutyCatalog({ ...WINDOW, scopes: ["scope:example"] })).toThrow();
    expect(() => decodeScopedDutyCatalog({ ...WINDOW, scopes: ["scope:example"], artifact_delivery_available: "true" })).toThrow();
  });

  it("does not renew an expired snapshot while decoding a late response", () => {
    const value = decodeScopedDutyCatalog({ ...WINDOW, scopes: ["scope:example"], artifact_delivery_available: true });
    expect(isScopedDutyFresh(value, Date.parse("2026-09-15T12:01:00Z"))).toBe(false);
    expect(value.expires_at).toBe(WINDOW.expires_at);
  });

  it("reads exact observation evidence without confusing Core and Operator identities", () => {
    const value = decodeScopedDutyProjection(observed(), "Odin", "scope:example");
    expect(value.artifact?.case_id).toBe(CORE_ID);
    expect(value.primary_refs).toEqual([PRIMARY]);
    expect(value.execution_authority).toBe(false);
  });

  it("rejects an observation for another agent or a related but different scope", () => {
    expect(() => decodeScopedDutyProjection(observed(), "Thor", "scope:example")).toThrow();
    expect(() => decodeScopedDutyProjection(observed(), "Odin", "scope:example/child")).toThrow();
  });

  it("does not accept positive observed coverage from a partial or invalid scan", () => {
    expect(() => decodeScopedDutyProjection({ ...observed(), partial: true }, "Odin", "scope:example")).toThrow();
    expect(() => decodeScopedDutyProjection({ ...observed(), invalid_cases: 1 }, "Odin", "scope:example")).toThrow();
    expect(() => decodeScopedDutyProjection({ ...observed(), backup_refs: [PRIMARY] }, "Odin", "scope:example")).toThrow();
  });

  it("preserves held evidence without synthesizing a case or artifact", () => {
    const held = { ...WINDOW, ...coverage(), state: "held", primary_refs: [], backup_refs: [],
      held_reasons: ["incomplete_scoped_case_scan"], partial: true, invalid_cases: 1 };
    const value = decodeScopedDutyProjection(held, "Odin", "scope:example");
    expect(value).toMatchObject({ state: "held", partial: true, invalid_cases: 1, artifact: null });
    expect(() => decodeScopedDutyProjection({ ...held, primary_refs: [PRIMARY] }, "Odin", "scope:example")).toThrow();
  });

  it("distinguishes awaiting GET from a POST receipt and a full Core case", () => {
    const awaiting = { case_id: CASE_ID, state: "awaiting_core", revision: null, request: draft().request, execution_authority: false };
    expect(decodeScopedDutyCase(awaiting, CASE_ID)).toMatchObject({ state: "awaiting_core", revision: null });
    expect(() => decodeScopedDutyCase({ ...awaiting, revision: 1 }, CASE_ID)).toThrow();
    expect(() => decodeScopedDutyCase(proposal(), CASE_ID)).toThrow();
    expect(decodeScopedDutyCase(rawCase(), CASE_ID)).toMatchObject({ state: "pending_review", core_case_id: CORE_ID, revision: 2 });
  });

  it("refuses personal IAM states and noninteger Core revisions", () => {
    expect(() => decodeScopedDutyCase({ ...rawCase(), state: "active" }, CASE_ID)).toThrow();
    expect(() => decodeScopedDutyCase({ ...rawCase(), revision: true }, CASE_ID)).toThrow();
    expect(() => decodeScopedDutyCase({ ...rawCase(), revision: 0 }, CASE_ID)).toThrow();
  });

  it("fences exact case, Core identity and monotonic revision on refresh", () => {
    const first = decodeScopedDutyCase(rawCase(), CASE_ID);
    expect(() => decodeScopedDutyCase({ ...rawCase(), case_id: OTHER_CASE }, CASE_ID)).toThrow();
    expect(() => decodeScopedDutyCase({ ...rawCase(), core_case_id: PRIMARY, revision: 3 }, CASE_ID, first)).toThrow();
    expect(() => decodeScopedDutyCase({ ...rawCase(), revision: 1 }, CASE_ID, first)).toThrow();
    expect(() => decodeScopedDutyCase({ case_id: CASE_ID, state: "awaiting_core", revision: null, request: draft().request, execution_authority: false }, CASE_ID, first)).toThrow();
  });

  it("does not let a higher revision rewrite requester, review history or lifecycle direction", () => {
    const value = rawCase("approved"), previous = decodeScopedDutyCase(value, CASE_ID);
    expect(() => decodeScopedDutyCase({ ...value, requester_ref: "another-requester", revision: 5 }, CASE_ID, previous)).toThrow();
    expect(() => decodeScopedDutyCase({ ...value, reviews: [...value.reviews].reverse(), revision: 5 }, CASE_ID, previous)).toThrow();
    expect(() => decodeScopedDutyCase({ ...rawCase(), revision: 5 }, CASE_ID, previous)).toThrow();
  });

  it("accepts server UTC normalization when recovering the exact creation request", () => {
    const input = draft().request;
    const expected: ScopedDutyCaseRead = { case_id: CASE_ID, state: "awaiting_core", revision: null, execution_authority: false,
      request: { ...input, bindings: input.bindings.map((row) => ({ ...row, effective_from: row.effective_from.replace("Z", "+00:00") })) } };
    expect(decodeScopedDutyCase(rawCase(), CASE_ID, expected).state).toBe("pending_review");
  });

  it("rejects a changed request or plan target behind the same case identifier", () => {
    const first = decodeScopedDutyCase(rawCase(), CASE_ID), value = rawCase();
    expect(() => decodeScopedDutyCase({ ...value, request: { ...value.request, source_revision: "different" } }, CASE_ID, first)).toThrow();
    const altered = { ...value, plan: { ...value.plan, bindings: value.plan.bindings.map((row) => ({ ...row, binding: { ...row.binding, agent_name: "Thor" } })) } };
    expect(() => decodeScopedDutyCase(altered, CASE_ID)).toThrow();
  });

  it("requires two distinct digest-bound reviews before an approved state", () => {
    const value = rawCase("approved");
    expect(decodeScopedDutyCase(value, CASE_ID).state).toBe("approved");
    expect(() => decodeScopedDutyCase({ ...value, reviews: value.reviews.slice(0, 1) }, CASE_ID)).toThrow();
    expect(() => decodeScopedDutyCase({ ...value, reviews: [value.reviews[0], value.reviews[0]] }, CASE_ID)).toThrow();
    expect(() => decodeScopedDutyCase({ ...value, reviews: value.reviews.map((row) => ({ ...row, plan_digest: "b".repeat(64) })) }, CASE_ID)).toThrow();
  });

  it("refuses requester review and reviews dated before the retained plan", () => {
    const value = rawCase("approved");
    expect(() => decodeScopedDutyCase({ ...value, reviews: [{ ...value.reviews[0], reviewer_ref: REQUESTER }, value.reviews[1]] }, CASE_ID)).toThrow();
    expect(() => decodeScopedDutyCase({ ...value, reviews: value.reviews.map((row) => ({ ...row, reviewed_at: "2026-09-15T10:00:00Z" })) }, CASE_ID)).toThrow();
  });

  it("rejects recorded approval by a resolved target rather than presenting it as independent proof", () => {
    const value = rawCase("approved");
    expect(() => decodeScopedDutyCase({ ...value, reviews: [{ ...value.reviews[0], reviewer_ref: PRIMARY }, value.reviews[1]] }, CASE_ID)).toThrow();
  });

  it("does not equate an open review PR with independent merge proof", () => {
    expect(decodeScopedDutyCase(rawCase("ownership_pr_open"), CASE_ID)).toMatchObject({ merge_commit_sha: null });
    expect(() => decodeScopedDutyCase({ ...rawCase("ownership_pr_open"), state: "ownership_merged" }, CASE_ID)).toThrow();
    expect(() => decodeScopedDutyCase({ ...rawCase("draft"), pr_ref: "https://example.com/pull/1" }, CASE_ID)).toThrow();
  });

  it("keeps future-only held plans as drafts with unresolved people", () => {
    const value = rawCase("draft");
    const bindings = value.request.bindings.map((row) => ({ ...row, effective_from: "2026-09-16T11:00:00Z" }));
    const future = { ...value, request: { ...value.request, bindings }, plan: { ...value.plan, current_coverage: false,
      bindings: value.plan.bindings.map((row, index) => ({ ...row, binding: bindings[index]!, resolution: null, held_reason: "not_yet_effective" })),
      coverage: [{ ...coverage(), primary_refs: [], backup_refs: [], held_reasons: ["not_yet_effective", "current_primary_missing"] }] } };
    expect(decodeScopedDutyCase(future, CASE_ID).state).toBe("draft");
  });

  it("rejects fabricated fields or foreign identities in proposal envelopes", () => {
    expect(decodeScopedDutyProposal(proposal())).not.toHaveProperty("revision");
    expect(() => decodeScopedDutyProposal({ ...proposal(), revision: null })).toThrow();
    expect(() => decodeScopedDutyProposal({ ...proposal(), state: "approved" })).toThrow();
    expect(() => decodeScopedDutyProposal({ ...proposal(), proposal_id: OTHER_CASE })).toThrow();
    expect(() => decodeScopedDutyProposal(proposal(OTHER_CASE), CASE_ID)).toThrow();
  });
});

describe("injected scoped duty transport", () => {
  it("uses the catalog endpoint with no cache, cookies or redirects", async () => {
    const { api, fetcher } = harness();
    fetcher.mockResolvedValueOnce(response({ ...WINDOW, scopes: ["scope:example"], artifact_delivery_available: true }));
    await api.catalog();
    const [url, options] = fetcher.mock.calls[0]!;
    expect(String(url)).toBe("https://example.com/handover/scoped-duties/catalog");
    expect(options).toMatchObject({ method: "GET", cache: "no-store", credentials: "omit", redirect: "error", referrerPolicy: "no-referrer" });
    expect(options?.body).toBeUndefined();
  });

  it("encodes exactly two projection selectors without broadening a scope", async () => {
    const { api, fetcher } = harness();
    const scope = "scope:example/a?b=c&d";
    fetcher.mockResolvedValueOnce(response({ ...observed(), scope_ref: scope }));
    await api.projection("Odin", scope);
    const url = new URL(String(fetcher.mock.calls[0]![0]));
    expect([...url.searchParams.entries()]).toEqual([["agent_name", "Odin"], ["scope_ref", scope]]);
    expect(url.pathname).toBe("/handover/scoped-duties");
  });

  it("reads only an exact case and rejects another case response", async () => {
    const { api, fetcher } = harness();
    fetcher.mockResolvedValueOnce(response({ ...rawCase(), case_id: OTHER_CASE }));
    await expect(api.getCase(CASE_ID)).rejects.toMatchObject({ code: "malformed" });
    expect(String(fetcher.mock.calls[0]![0])).toBe(`https://example.com/handover/scoped-duty-cases/${CASE_ID}`);
  });

  it("leaves a 202 creation awaiting Core without an optimistic submit or GET", async () => {
    const { api, fetcher } = harness();
    fetcher.mockResolvedValueOnce(response(proposal(), 202));
    const result = await api.create(scopedDutyCreationFor(null, draft(), () => "intent-one"));
    expect(result.state).toBe("awaiting_core");
    expect(result).not.toHaveProperty("revision");
    expect(result).not.toHaveProperty("core_case_id");
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(fetcher.mock.calls[0]![1]?.body))).toEqual({ idempotency_key: "intent-one", ...draft() });
  });

  it("replays unchanged creation bytes and key after a POST failure", async () => {
    const { api, fetcher } = harness();
    const creation = scopedDutyCreationFor(null, draft(), () => "intent-one");
    fetcher.mockResolvedValueOnce(response({}, 503)).mockResolvedValueOnce(response(proposal(), 202));
    await expect(api.create(creation)).rejects.toMatchObject({ code: "unavailable" });
    expect(fetcher).toHaveBeenCalledTimes(1);
    await api.create(creation);
    expect(fetcher.mock.calls[0]![1]?.body).toBe(fetcher.mock.calls[1]![1]?.body);
  });

  it("sends only the expected revision for submit and does not materialize a state", async () => {
    const { api, fetcher } = harness();
    fetcher.mockResolvedValueOnce(response({ ...proposal(), proposal_id: OTHER_CASE }, 202));
    expect(await api.submit(CASE_ID, 1)).toMatchObject({ state: "awaiting_core", execution_authority: false });
    expect(JSON.parse(String(fetcher.mock.calls[0]![1]?.body))).toEqual({ expected_revision: 1 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("keeps even the second approval as a proposal with the exact digest", async () => {
    const { api, fetcher } = harness();
    fetcher.mockResolvedValueOnce(response({ ...proposal(), proposal_id: OTHER_CASE }, 202));
    const result = await api.review(CASE_ID, 3, "approve", DIGEST);
    expect(result.state).toBe("awaiting_core");
    expect(result).not.toHaveProperty("revision");
    expect(JSON.parse(String(fetcher.mock.calls[0]![1]?.body))).toEqual({ expected_revision: 3, decision: "approve", plan_digest: DIGEST });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("retains the original review decision and revision on an explicit retry", async () => {
    const { api, fetcher } = harness();
    fetcher.mockRejectedValueOnce(new TypeError("synthetic transport failure")).mockResolvedValueOnce(response(proposal(), 202));
    await expect(api.review(CASE_ID, 2, "reject", DIGEST)).rejects.toMatchObject({ code: "network" });
    await api.review(CASE_ID, 2, "reject", DIGEST);
    expect(fetcher.mock.calls[0]![1]?.body).toBe(fetcher.mock.calls[1]![1]?.body);
  });

  it.each([200, 201])("rejects a non-proposal HTTP %s response for a write", async (status) => {
    const { api, fetcher } = harness();
    fetcher.mockResolvedValueOnce(response(proposal(), status));
    await expect(api.submit(CASE_ID, 1)).rejects.toMatchObject({ code: "malformed" });
  });

  it.each([[400, "invalid_input"], [401, "unauthorized"], [403, "denied"], [404, "not_found"], [409, "conflict"], [503, "unavailable"], [500, "network"]] as const)("classifies HTTP %s without exposing source error content", async (status, code) => {
    const { api, fetcher } = harness();
    fetcher.mockResolvedValueOnce(response({ error: { message: "private-source-output" } }, status));
    await expect(api.getCase(CASE_ID)).rejects.toMatchObject({ code });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("rejects malformed input before authentication or fetch", async () => {
    const { api, fetcher, client } = harness();
    await expect(api.getCase(`${CASE_ID}/review`)).rejects.toMatchObject({ code: "invalid_input" });
    await expect(api.submit(CASE_ID, 0)).rejects.toMatchObject({ code: "invalid_input" });
    await expect(api.review(CASE_ID, 2, "approve", "short")).rejects.toMatchObject({ code: "invalid_input" });
    expect(client.authorizationHeader).not.toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("rejects a creation body with authority fields or excessive bytes before I/O", async () => {
    const { api, fetcher, client } = harness();
    const creation = scopedDutyCreationFor(null, draft(), () => "intent-one");
    await expect(api.create({ ...creation, body: JSON.stringify({ ...JSON.parse(creation.body), execution_authority: true }) })).rejects.toMatchObject({ code: "invalid_input" });
    await expect(api.create({ ...creation, body: " ".repeat(32_001) })).rejects.toMatchObject({ code: "invalid_input" });
    expect(client.authorizationHeader).not.toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("holds malformed and oversized responses rather than showing incomplete evidence", async () => {
    const { api, fetcher } = harness();
    fetcher.mockResolvedValueOnce(new Response("not-json", { status: 200 }))
      .mockResolvedValueOnce(response({ oversized: "x".repeat(2_097_152) }));
    await expect(api.getCase(CASE_ID)).rejects.toMatchObject({ code: "malformed" });
    await expect(api.getCase(CASE_ID)).rejects.toMatchObject({ code: "malformed" });
  });

  it("bounds authentication time and never dispatches after that deadline", async () => {
    vi.useFakeTimers();
    const { api, fetcher, client } = harness(50);
    let release!: (value: string | null) => void;
    client.authorizationHeader.mockReturnValueOnce(new Promise((resolve) => { release = resolve; }));
    const pending = expect(api.submit(CASE_ID, 1)).rejects.toMatchObject({ code: "timeout" });
    await vi.advanceTimersByTimeAsync(51);
    await pending;
    release(null); await Promise.resolve();
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("honors a case/user/client cancellation before a delayed authorization resolves", async () => {
    const { api, fetcher, client } = harness();
    let release!: (value: string | null) => void;
    client.authorizationHeader.mockReturnValueOnce(new Promise((resolve) => { release = resolve; }));
    const controller = new AbortController();
    const pending = expect(api.getCase(CASE_ID, controller.signal)).rejects.toMatchObject({ code: "cancelled" });
    controller.abort(); await pending;
    release(null); await Promise.resolve();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
