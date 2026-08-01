import { readFileSync } from "node:fs";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { AuthContext } from "../auth";
import { createAssignmentCase, submitAssignmentCase } from "./settings-iam-assignments.command";
import { assignmentValidation, decodeAssignmentProjectionPage, filterAssignments, type AssignmentDraft } from "./settings-iam-assignments.model";

const wireCase = { case_id: "case-1", state: "draft", revision: 1, intent: { idempotency_key: "assignment-1", subject: { provider: "entra", subject_id: "target-1" }, requested_role: "Reader", duty_bindings: [{ agent_name: "Odin", duty: "primary", scope_ref: "scope:platform" }], goal_refs: ["goal:odin:v1"], requester_ref: "owner-1", justification: "Assign bounded platform ownership." }, reviews: [], effect_receipts: [], degraded_reason: null, superseded_by: null };
const wireProjection = { items: [{ subject: { provider: "entra", subject_id: "target-1", display_name: null, username: null, active: null }, roles: null, duties: [{ agent_name: "Odin", duty: "primary", responsibility: "accountable", source: "stewardship" }], coverage: [{ agent_name: "Odin", primary_count: 1, backup_or_escalation_count: 1, finding_codes: [] }], case: wireCase, handover: { goal_refs: ["goal:odin:v1"], state: null, evidence_refs: null, availability: "not_connected" } }], total: 1, next_cursor: null, authority: "observation_only", directory_availability: "available", case_projection_truncated: false };
const identity = { provider: "entra", subjectId: "target-1", username: "target@example.com", displayName: "Target User", userType: "member", active: true };
const draft: AssignmentDraft = { identity, role: "Reader", duties: [{ agentName: "Odin", duty: "primary", scopeRef: "scope:platform" }], goalRefs: ["goal:odin:v1"], justification: "Assign bounded platform ownership." };
const auth: AuthContext = { devMode: false, account: null, getAuthorizationHeader: async () => "Bearer token", signIn: async () => undefined, signOut: async () => undefined };

afterEach(() => vi.unstubAllGlobals());

describe("IAM assignment contracts", () => {
  test("decodes unavailable provider state without fabricating values", () => {
    const page = decodeAssignmentProjectionPage(wireProjection);
    expect(page.items[0]?.roles).toBeNull();
    expect(page.items[0]?.subject.active).toBeNull();
    expect(page.items[0]?.handover.state).toBeNull();
    expect(page.items[0]?.assignmentCase?.state).toBe("draft");
  });

  test("validates and filters the compact assignment editor", () => {
    expect(assignmentValidation(draft)).toEqual([]);
    expect(assignmentValidation({ ...draft, identity: null, justification: "short" })).toEqual(["identity", "justification"]);
    const items = decodeAssignmentProjectionPage(wireProjection).items;
    expect(filterAssignments(items, { query: "target-1", role: "all", agent: "Odin", coverage: "covered" })).toHaveLength(1);
    expect(filterAssignments(items, { query: "", role: "Owner", agent: "", coverage: "all" })).toHaveLength(0);
  });

  test("creates and submits only observation-case commands", async () => {
    const fetchMock = vi.fn(async (url: URL, init?: RequestInit) => {
      expect((init?.headers as Record<string, string>)["authorization"]).toBe("Bearer token");
      if (url.pathname.endsWith("/submit")) return new Response(JSON.stringify({ ...wireCase, state: "pending_review", revision: 2 }));
      expect(url.pathname).toBe("/iam/assignment-cases");
      expect(JSON.parse(String(init?.body))).toMatchObject({ subject: { subject_id: "target-1" }, requested_role: "Reader" });
      return new Response(JSON.stringify(wireCase), { status: 201 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const created = await createAssignmentCase(auth, "http://127.0.0.1:8010", draft, "assignment-1");
    const submitted = await submitAssignmentCase(auth, "http://127.0.0.1:8010", created);
    expect(submitted.state).toBe("pending_review");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  test("keeps loading, lock, and form accessibility markers in the view", () => {
    const source = readFileSync(new URL("./settings-iam-assignments.tsx", import.meta.url), "utf8");
    expect(source).toContain("<LoadingState");
    expect(source).toContain('role="alert"');
    expect(source).toContain("<fieldset>");
    expect(source).toContain('aria-label={t("settings.iam.assignmentFilters")}');
  });
});
