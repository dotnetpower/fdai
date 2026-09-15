import { describe, expect, it } from "vitest";
import {
  emptyScopedDutyDraft, isScopedDutyCaseId, isScopedDutyCoreId, isScopedDutyFresh,
  scopedDutyBindingIdentity, scopedDutyControls, scopedDutyCreationFor, scopedDutyDraftIssues,
  scopedDutyInstant, scopedDutyRequestIssues, type ScopedDutyBinding, type ScopedDutyCase,
  type ScopedDutyCatalog, type ScopedDutyDraft, type ScopedDutyState,
} from "./scoped-duty-model";

const NOW = Date.parse("2026-09-15T12:00:00Z");
const REQUESTER = "00000000-0000-0000-0000-00000000000a";
const OWNER = "00000000-0000-0000-0000-00000000000b";
const OTHER_OWNER = "00000000-0000-0000-0000-00000000000c";
const PRIMARY = "00000000-0000-0000-0000-00000000001a";
const BACKUP = "00000000-0000-0000-0000-00000000001b";
const DIGEST = "a".repeat(64);
const CASE_ID = `operator-${"a".repeat(32)}`;
const CATALOG: ScopedDutyCatalog = {
  source_revision: `sha256:${DIGEST}`, scopes: ["scope:example", "scope:other"],
  observed_at: "2026-09-15T11:59:30Z", expires_at: "2026-09-15T12:01:00Z",
  artifact_delivery_available: true, execution_authority: false,
};

function binding(changes: Partial<ScopedDutyBinding> = {}): ScopedDutyBinding {
  return { subject: { kind: "user", ref: PRIMARY }, agent_name: "Odin", scope_ref: "scope:example",
    duty: "primary", effective_from: "2026-09-15T11:00:00Z", effective_until: "2026-09-16T12:00:00Z",
    fallback: null, ...changes };
}
function draft(bindings: readonly ScopedDutyBinding[] = [binding(), binding({ subject: { kind: "user", ref: BACKUP }, duty: "backup" })]): ScopedDutyDraft {
  return { request: { schema_version: "1.0.0", source_revision: CATALOG.source_revision, bindings, supersedes_case_id: null },
    justification: "Keep independent ownership for the exact example scope." };
}
function materialized(state: ScopedDutyState = "pending_review"): ScopedDutyCase {
  const request = draft().request;
  const reviewed = ["approved", "ownership_pr_open", "ownership_merged"].includes(state);
  const artifact = ["ownership_pr_open", "ownership_merged"].includes(state);
  return { case_id: CASE_ID, core_case_id: "00000000-0000-0000-0000-000000000002", state,
    revision: reviewed ? 4 : 2, requester_ref: REQUESTER, request,
    plan: { kind: "scoped_duty_review", schema_version: "1.0.0", source_revision: CATALOG.source_revision,
      input_digest: DIGEST, digest: DIGEST, resolution_at: CATALOG.observed_at, checked_at: CATALOG.observed_at,
      coverage_basis: "current_observation_only", current_coverage: true, review_required: true, execution_authority: false,
      policy: { max_resolution_age_microseconds: 300_000_000, read_timeout_seconds: 5, total_timeout_seconds: 120 },
      bindings: request.bindings.map((row) => ({ binding: row, scope: { scope_ref: row.scope_ref, source_revision: request.source_revision },
        resolution: { subject: row.subject, people: [row.subject], at: CATALOG.observed_at, observed_at: CATALOG.observed_at,
          valid_until: CATALOG.expires_at, provenance_ref: "directory:example", provenance_digest: DIGEST, complete: true },
        held_reason: null, schedule_failure: null, used_fallback: false, digest: DIGEST })),
      coverage: [{ agent_name: "Odin", scope_ref: "scope:example", primary_refs: [PRIMARY], backup_refs: [BACKUP], escalation_refs: [], held_reasons: [] }] },
    reviews: reviewed ? [OWNER, OTHER_OWNER].map((reviewer_ref) => ({ reviewer_ref, decision: "approve", plan_digest: DIGEST, reviewed_at: "2026-09-15T11:59:45Z" }))
      : state === "rejected" ? [{ reviewer_ref: OWNER, decision: "reject", plan_digest: DIGEST, reviewed_at: "2026-09-15T11:59:45Z" }] : [],
    pr_ref: artifact ? "https://example.com/pull/1" : null, candidate_digest: artifact ? DIGEST : null,
    merge_commit_sha: state === "ownership_merged" ? "b".repeat(40) : null, execution_authority: false };
}
function codes(value: ScopedDutyDraft, catalog: ScopedDutyCatalog | null = CATALOG) {
  return scopedDutyDraftIssues(value, catalog, NOW).map((issue) => issue.code);
}

describe("scoped duty declaration guards", () => {
  it("accepts explicit current declarations without adding an IAM or role field", () => {
    const value = draft();
    expect(codes(value)).toEqual([]);
    expect(Object.keys(value.request).sort()).toEqual(["bindings", "schema_version", "source_revision", "supersedes_case_id"]);
  });

  it("starts with no invented platform scope, subject or effective timestamp", () => {
    const value = emptyScopedDutyDraft();
    expect(value.request.source_revision).toBe("");
    expect(value.request.bindings[0]).toMatchObject({ scope_ref: "", subject: { ref: "" }, effective_from: "", effective_until: "" });
    expect(codes(value, null)).toContain("catalog");
  });

  it.each(["odin", "Unknown", "Odin "])("requires the exact Pantheon spelling, not %s", (agent_name) => {
    expect(codes(draft([binding({ agent_name })]))).toContain("agent");
  });

  it.each(["scope:platform", "scope:example/child", "scope:*"])("does not infer catalog membership for %s", (scope_ref) => {
    expect(codes(draft([binding({ scope_ref })]))).toContain("scope");
  });

  it("compares the entire source revision rather than its display prefix", () => {
    const value = draft();
    expect(codes({ ...value, request: { ...value.request, source_revision: CATALOG.source_revision.slice(0, 18) } })).toContain("source_revision");
  });

  it.each(["USER", " user", "user ", "사용자", "x".repeat(257)])("rejects a noncanonical subject reference %s", (ref) => {
    expect(codes(draft([binding({ subject: { kind: "user", ref } })]))).toContain("subject");
  });

  it("requires 1-30 declarations instead of truncating them", () => {
    expect(codes(draft([]))).toContain("bindings");
    const rows = Array.from({ length: 30 }, (_, index) => binding({ subject: { kind: "user", ref: `person:${index}` } }));
    expect(codes(draft(rows))).toEqual([]);
    expect(codes(draft([...rows, binding()]))).toContain("bindings");
  });

  it.each(["2026-02-30T12:00:00Z", "2026-09-15T25:00:00Z", "2026-09-15T12:00:00", "1757937600"])("rejects invalid or implicit time %s", (effective_from) => {
    expect(codes(draft([binding({ effective_from })]))).toContain("utc_time");
  });

  it("requires UTC entry even though the instant parser understands an explicit offset", () => {
    expect(scopedDutyInstant("2026-09-15T21:00:00+09:00")).toBe(NOW);
    expect(codes(draft([binding({ effective_from: "2026-09-15T21:00:00+09:00" })]))).toContain("utc_time");
  });

  it("preserves fractional instants and equivalent UTC encodings", () => {
    expect(scopedDutyInstant("2026-09-15T12:00:00.123456Z") - NOW).toBeCloseTo(123.456, 2);
    expect(scopedDutyBindingIdentity(binding())).toBe(scopedDutyBindingIdentity(binding({ effective_from: "2026-09-15T11:00:00+00:00" })));
  });

  it("rejects an empty half-open interval", () => {
    expect(codes(draft([binding({ effective_until: "2026-09-15T11:00:00Z" })]))).toContain("interval");
  });

  it("rejects same-subject overlap across primary and backup duties", () => {
    const value = draft([binding(), binding({ duty: "backup" })]);
    expect(scopedDutyRequestIssues(value.request)).toContainEqual({ code: "overlap", field: "effective_from", binding: 1 });
  });

  it("permits adjacent intervals without claiming continuous observed coverage", () => {
    expect(codes(draft([binding({ effective_until: "2026-09-15T13:00:00Z" }),
      binding({ effective_from: "2026-09-15T13:00:00Z", duty: "backup" })]))).toEqual([]);
  });

  it("keeps different agent/scope declarations distinct", () => {
    expect(codes(draft([binding(), binding({ agent_name: "Thor" }), binding({ scope_ref: "scope:other" })]))).toEqual([]);
  });

  it("requires an explicit static user fallback for a schedule", () => {
    const schedule = binding({ subject: { kind: "schedule", ref: "rotation:example" } });
    expect(codes(draft([schedule]))).toContain("fallback");
    expect(codes(draft([{ ...schedule, fallback: { kind: "group", ref: "group:example" } }]))).toContain("fallback");
    expect(codes(draft([{ ...schedule, fallback: { kind: "user", ref: "rotation:example" } }]))).toContain("fallback");
    expect(codes(draft([{ ...schedule, fallback: { kind: "user", ref: BACKUP } }]))).toEqual([]);
  });

  it("does not allow fallback fields on user or group declarations", () => {
    for (const kind of ["user", "group"] as const) {
      expect(codes(draft([binding({ subject: { kind, ref: PRIMARY }, fallback: { kind: "user", ref: BACKUP } })]))).toContain("fallback");
    }
  });

  it("keeps future requests inert and rejects already expired declarations", () => {
    expect(codes(draft([binding({ effective_from: "2026-09-15T13:00:00Z" })]))).toEqual([]);
    expect(codes(draft([binding({ effective_until: "2026-09-15T12:00:00Z" })]))).toContain("expired_binding");
  });

  it("distinguishes an exact Core UUID from an Operator request ID", () => {
    const value = draft();
    expect(isScopedDutyCaseId(CASE_ID)).toBe(true);
    expect(isScopedDutyCaseId(`${CASE_ID}/review`)).toBe(false);
    expect(isScopedDutyCoreId(materialized().core_case_id)).toBe(true);
    expect(isScopedDutyCoreId(CASE_ID)).toBe(false);
    expect(codes({ ...value, request: { ...value.request, supersedes_case_id: CASE_ID } })).toContain("supersedes");
  });

  it("bounds justification by content rather than whitespace", () => {
    expect(codes({ ...draft(), justification: " ".repeat(20) })).toContain("justification");
    expect(codes({ ...draft(), justification: "a".repeat(2001) })).toContain("justification");
    expect(codes({ ...draft(), justification: "a".repeat(20) })).toEqual([]);
  });

  it("rejects a large UTF-8 request without dropping declarations", () => {
    const scope = "s".repeat(256);
    const rows = Array.from({ length: 30 }, (_, index) => binding({ scope_ref: scope,
      subject: { kind: "schedule", ref: `rotation-${index}`.padEnd(256, "x") }, fallback: { kind: "user", ref: "p".repeat(256) } }));
    expect(codes({ ...draft(rows), justification: "변경".repeat(1000) }, { ...CATALOG, scopes: [scope] })).toContain("size");
    expect(rows).toHaveLength(30);
  });
});

describe("source freshness and review identity", () => {
  it("uses the original non-sliding, half-open catalog deadline", () => {
    expect(isScopedDutyFresh(CATALOG, scopedDutyInstant(CATALOG.observed_at))).toBe(true);
    expect(isScopedDutyFresh(CATALOG, scopedDutyInstant(CATALOG.expires_at))).toBe(false);
    expect(isScopedDutyFresh({ ...CATALOG }, NOW + 90_000)).toBe(false);
    expect(isScopedDutyFresh(CATALOG, NOW - 31_000)).toBe(false);
  });

  it("refuses a freshness window beyond the server ceiling", () => {
    expect(isScopedDutyFresh({ ...CATALOG, expires_at: "2026-09-15T13:00:00Z" }, NOW)).toBe(false);
    expect(codes(draft(), null)).toContain("catalog");
  });

  it("cannot promote an awaiting Core envelope into a usable revision", () => {
    const waiting = { case_id: CASE_ID, state: "awaiting_core" as const, revision: null, request: draft().request, execution_authority: false as const };
    expect(scopedDutyControls(waiting, CATALOG, OWNER, true, NOW)).toEqual({ submit: false, review: false, reason: "awaiting_core" });
  });

  it("requires the server capability even for a requester or otherwise independent reviewer", () => {
    expect(scopedDutyControls(materialized("draft"), CATALOG, REQUESTER, false, NOW).submit).toBe(false);
    expect(scopedDutyControls(materialized(), CATALOG, OWNER, false, NOW).reason).toBe("owner");
  });

  it("permits only the original requester to submit an exact current draft", () => {
    expect(scopedDutyControls(materialized("draft"), CATALOG, REQUESTER, true, NOW).submit).toBe(true);
    expect(scopedDutyControls(materialized("draft"), CATALOG, OWNER, true, NOW).reason).toBe("requester");
  });

  it("does not submit future-only declarations as current coverage", () => {
    const value = materialized("draft");
    const future = { ...value, request: { ...value.request, bindings: value.request.bindings.map((row) => ({ ...row, effective_from: "2026-09-15T13:00:00Z" })) } };
    expect(scopedDutyControls(future, CATALOG, REQUESTER, true, NOW).reason).toBe("future");
  });

  it("blocks self-review with case-varied principal identity", () => {
    expect(scopedDutyControls(materialized(), CATALOG, REQUESTER.toUpperCase(), true, NOW).reason).toBe("separation");
    expect(scopedDutyControls(materialized(), CATALOG, "", true, NOW).reason).toBe("identity");
  });

  it("requires a different reviewer after the first recorded Owner approval", () => {
    const value = { ...materialized(), revision: 3, reviews: [materialized("approved").reviews[0]!] };
    expect(scopedDutyControls(value, CATALOG, OWNER, true, NOW).reason).toBe("already_reviewed");
    expect(scopedDutyControls(value, CATALOG, OTHER_OWNER, true, NOW).review).toBe(true);
  });

  it("excludes declared and resolved people without inferring group authority", () => {
    expect(scopedDutyControls(materialized(), CATALOG, PRIMARY, true, NOW).reason).toBe("target");
    const value = materialized();
    const grouped = { ...value, plan: { ...value.plan, bindings: value.plan.bindings.map((row) => ({ ...row,
      resolution: row.resolution ? { ...row.resolution, people: [{ kind: "user" as const, ref: OWNER }] } : null })) } };
    expect(scopedDutyControls(grouped, CATALOG, OWNER, true, NOW).reason).toBe("target");
  });

  it("excludes a static fallback independently of current resolution", () => {
    const value = materialized();
    const schedule = { ...value, request: { ...value.request, bindings: [binding({ subject: { kind: "schedule", ref: "rotation:example" }, fallback: { kind: "user", ref: OWNER } })] } };
    expect(scopedDutyControls(schedule, CATALOG, OWNER, true, NOW).reason).toBe("target");
  });

  it("stops transitions on catalog drift or expiry without rewriting the case", () => {
    const value = materialized();
    expect(scopedDutyControls(value, { ...CATALOG, source_revision: "different" }, OWNER, true, NOW).reason).toBe("source_revision");
    expect(scopedDutyControls(value, CATALOG, OWNER, true, NOW + 60_000).reason).toBe("catalog");
    expect(value.request.source_revision).toBe(CATALOG.source_revision);
  });

  it.each(["approved", "ownership_pr_open", "ownership_merged", "rejected"] as const)("offers no new Console transition for %s", (state) => {
    expect(scopedDutyControls(materialized(state), CATALOG, OWNER, true, NOW)).toEqual({ submit: false, review: false, reason: "terminal" });
    expect(materialized(state).execution_authority).toBe(false);
  });
});

describe("creation replay identity", () => {
  it("keeps the exact key and serialized payload after an uncertain POST", () => {
    const value = draft(), first = scopedDutyCreationFor(null, value, () => "intent-one");
    expect(scopedDutyCreationFor(first, value, () => "must-not-be-used")).toBe(first);
    expect(JSON.parse(first.body)).toMatchObject({ idempotency_key: "intent-one", request: value.request });
  });

  it("rotates on an edit and again when returning to an earlier draft", () => {
    const value = draft(), first = scopedDutyCreationFor(null, value, () => "intent-one");
    const changed = scopedDutyCreationFor(first, { ...value, justification: `${value.justification} Revised.` }, () => "intent-two");
    const reverted = scopedDutyCreationFor(changed, value, () => "intent-three");
    expect([first.idempotencyKey, changed.idempotencyKey, reverted.idempotencyKey]).toEqual(["intent-one", "intent-two", "intent-three"]);
  });

  it("retains immutable retry bytes when the caller's original object changes", () => {
    const mutable = { ...draft(), justification: draft().justification };
    const first = scopedDutyCreationFor(null, mutable, () => "intent-one");
    mutable.justification = "This is a different independent request justification.";
    expect(JSON.parse(first.body).justification).toBe(draft().justification);
  });

  it("binds adopted catalog revisions into a different creation identity", () => {
    const value = draft(), first = scopedDutyCreationFor(null, value, () => "intent-one");
    const next = scopedDutyCreationFor(first, { ...value, request: { ...value.request, source_revision: "new-revision" } }, () => "intent-two");
    expect(next.idempotencyKey).not.toBe(first.idempotencyKey);
    expect(JSON.parse(next.body).request.source_revision).toBe("new-revision");
  });
});
