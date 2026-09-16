/** Synthetic no-network fixtures for the two actual handover UI routes, not live evidence. */
import type { Page } from "@playwright/test";

export const HANDOVER_AT = Date.parse("2026-09-15T12:00:00Z");
export const HANDOVER_GOAL = "a".repeat(64);
export const SCOPED_CASE = `operator-${"a".repeat(32)}`;
export const SCOPED_SOURCE = `sha256:${"b".repeat(64)}`;
export const SLOTS = ["scope_exclusions", "decision_triggers", "runbook_rollback",
  "dependencies_escalation", "failure_risks", "source_governance"];

/** Produce a decoder-valid six-slot goal without implying operational acceptance. */
export function goalFixture(state = "not_started", operations = ["evidence", "not-applicable", "reuse"]): Record<string, unknown> {
  const complete = state === "ready_for_review" || state === "accepted";
  const review = { reviewer_ref: "human:owner", goal_revision: 7,
    evidence_digest: "c".repeat(64), reviewed_at: "2026-09-15T11:59:45Z" };
  return {
    goal_id: HANDOVER_GOAL, subject_ref: "human:synthetic-subject", agent_name: "Muninn", state,
    revision: 9, execution_authority: false, checklist_version: "1.0.0", required_slots: SLOTS,
    evidence: complete ? SLOTS.map((slot) => ({ slot, evidence_ref: `doc:synthetic-${slot}:v1`,
      digest: "d".repeat(64), kind: "document" })) : [], slot_exemptions: {}, high_impact: true,
    owner_review: state === "accepted" ? review : null,
    backup_review: state === "accepted" ? { ...review, reviewer_ref: "human:backup", goal_revision: 8 } : null,
    source_revision: SCOPED_SOURCE, scope_ref: "scope:example", allowed_operations: operations,
  };
}

/** Preserve the exact scoped-duty decoder shape while exposing only synthetic retained evidence. */
export function scopedCaseFixture(): Record<string, unknown> {
  const bindings = ["primary", "backup"].map((duty) => ({ agent_name: "Odin", scope_ref: "scope:example", duty,
    subject: { kind: "user", ref: `person:example-${duty}` }, fallback: null,
    effective_from: "2026-09-15T11:00:00Z", effective_until: "2026-09-16T12:00:00Z" }));
  return {
    case_id: SCOPED_CASE, core_case_id: "00000000-0000-0000-0000-000000000011", state: "pending_review",
    revision: 2, requester_ref: "requester-1", request: { schema_version: "1.0.0", source_revision: SCOPED_SOURCE,
      bindings, supersedes_case_id: null }, reviews: [], pr_ref: null, candidate_digest: null,
    merge_commit_sha: null, execution_authority: false,
    plan: { kind: "scoped_duty_review", schema_version: "1.0.0", source_revision: SCOPED_SOURCE,
      input_digest: "c".repeat(64), digest: "d".repeat(64), resolution_at: "2026-09-15T11:59:45Z",
      checked_at: "2026-09-15T11:59:45Z", coverage_basis: "current_observation_only", current_coverage: true,
      review_required: true, execution_authority: false,
      policy: { max_resolution_age_microseconds: 300_000_000, read_timeout_seconds: 5, total_timeout_seconds: 120 },
      bindings: bindings.map((binding) => ({ binding, scope: { scope_ref: binding.scope_ref, source_revision: SCOPED_SOURCE },
        resolution: { subject: binding.subject, people: [binding.subject], at: "2026-09-15T11:59:45Z",
          observed_at: "2026-09-15T11:59:45Z", valid_until: "2026-09-15T12:01:45Z", provenance_ref: "directory:synthetic",
          provenance_digest: "e".repeat(64), complete: true }, held_reason: null, schedule_failure: null,
        used_fallback: false, digest: "f".repeat(64) })),
      coverage: [{ agent_name: "Odin", scope_ref: "scope:example", primary_refs: ["person:example-primary"],
        backup_refs: ["person:example-backup"], escalation_refs: [], held_reasons: [] }],
    },
  };
}

/** Intercept every HTTP API request; deferred responses are released explicitly by the test. */
export async function installHandoverUiFixture(page: Page) {
  await page.clock.setFixedTime(HANDOVER_AT);
  const fixture = {
    goal: goalFixture(), scopedCase: scopedCaseFixture(),
    catalog: { source_revision: SCOPED_SOURCE, scopes: ["scope:example"],
      observed_at: "2026-09-15T11:59:45Z", expires_at: "2026-09-15T12:01:45Z",
      artifact_delivery_available: true, execution_authority: false },
    owner: true, readStatus: 200, writeStatus: 200, catalogStatus: 200, caseStatus: 200,
    observation: null as Record<string, unknown> | null,
    reportingLine: {
      operator_case_id: `operator-${"9".repeat(32)}`,
      case_id: "00000000-0000-0000-0000-000000000099",
      candidate_id: `report-line-${"8".repeat(32)}`,
      upload_id: "00000000-0000-0000-0000-000000000098",
      requester_ref: "uploader-1",
      subject_ref: "owner-1",
      manager_ref: "manager-1",
      state: "pending_confirmation",
      revision: 1,
      edge_digest: "7".repeat(64),
      directory_comparison: "matched",
      can_confirm: true,
      can_review: false,
      effective_from: "2026-09-15T11:00:00Z",
      effective_until: "2026-12-15T11:00:00Z",
      execution_authority: false,
      approval_authority: false,
    } as Record<string, unknown>,
    contactPending: true,
    readGate: Promise.resolve(), writeGate: Promise.resolve(),
    nextGoal: null as Record<string, unknown> | null,
    posts: [] as { path: string; body: Record<string, unknown> }[], reads: [] as string[],
  };
  await page.route("**/*", async (route) => {
    if (!["fetch", "xhr", "eventsource"].includes(route.request().resourceType())) {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    const method = route.request().method();
    const headers = { "Access-Control-Allow-Origin": new URL(page.url()).origin };
    if (method === "POST") fixture.posts.push({ path, body: route.request().postDataJSON() });
    else fixture.reads.push(path);
    if (path.startsWith("/handover/goals/")) {
      const goalAtRequest = fixture.goal, statusAtRequest = fixture.readStatus;
      if (method === "POST") {
        const writeStatus = fixture.writeStatus, nextGoal = fixture.nextGoal;
        await fixture.writeGate;
        if (writeStatus !== 200) {
          await route.fulfill({ status: writeStatus, json: { message: "Synthetic review conflict" } });
          return;
        }
        const body = route.request().postDataJSON();
        const goal = nextGoal ?? { ...goalAtRequest, revision: Number(goalAtRequest.revision) + 1, state: "in_progress",
          slot_exemptions: { ...(goalAtRequest.slot_exemptions as object), [String(body.slot)]: body.reason_ref } };
        if (fixture.goal.goal_id === goalAtRequest.goal_id) fixture.goal = goal;
        await route.fulfill({ json: { goal } });
      } else {
        await fixture.readGate;
        await route.fulfill({ status: statusAtRequest, json: { goal: goalAtRequest } });
      }
    } else if (path === "/iam") {
      await route.fulfill({ json: {
        principal: { oid: "owner-1", roles: [fixture.owner ? "Owner" : "Reader"],
          capabilities: fixture.owner ? ["view-console", "manage-group-membership"] : ["view-console"] },
        roles: [{ value: "Reader", capabilities: ["view-console"], routine_assignment: true },
          { value: "Owner", capabilities: ["view-console", "manage-group-membership"], routine_assignment: true }],
        assignment_boundary: "identity-provider-group",
        access_authority: { source: "server-verified", is_owner: fixture.owner, can_manage_group_membership: fixture.owner },
        directory: { source: "microsoft-graph", availability: "unavailable", observed_at: null, detail: null },
        workflow: { access_request_authority: "proposal_only", assignment_authority: "observation_only", provider_mutation: "promotion_required" },
      } });
    } else if (path === "/handover/scoped-duties/catalog") {
      await route.fulfill({ status: fixture.catalogStatus, json: fixture.catalog });
    } else if (path === "/handover/reporting-lines") {
      await route.fulfill({ json: {
        schema_version: "1.0.0", graph_revision: "6".repeat(64),
        items: [fixture.reportingLine], total: 1, next_cursor: null,
        summary: { active: 0, pending_confirmation: fixture.reportingLine.state === "pending_confirmation" ? 1 : 0,
          pending_owner_review: fixture.reportingLine.state === "pending_owner_review" ? 1 : 0,
          conflict: 0, awaiting_core: 0 },
        execution_authority: false, approval_authority: false,
      } });
    } else if (path.endsWith("/confirm") && path.includes("/handover/reporting-line-cases/")) {
      fixture.reportingLine = { ...fixture.reportingLine, state: "pending_owner_review",
        revision: 2, can_confirm: false };
      await route.fulfill({ status: 202, json: fixture.reportingLine });
    } else if (path === "/hil/report-line-contact-requests") {
      await route.fulfill({ json: { items: fixture.contactPending ? [{
        approval_id: "approval-1", consent_id: "consent-1", consent_revision: 0,
        action_type: "ops.restart-service", target_ref: "scope://service/example",
        route_subjects: ["manager-1"], expires_at: "2026-09-15T12:05:00Z",
        approval_authority: false, execution_authority: false,
      }] : [], total: fixture.contactPending ? 1 : 0 } });
    } else if (path === "/hil/approval-1/report-line-contact" && method === "POST") {
      fixture.contactPending = false;
      await route.fulfill({ status: 202, json: { approval_id: "approval-1",
        status: "contact_queued", consent: true, consent_id: "consent-1",
        execution_authority: false, approval_authority: false } });
    } else if (path === "/hil-queue") {
      await route.fulfill({ json: { items: [], total: 0, detail_level: "full" } });
    } else if (path.startsWith("/handover/scoped-duty-cases") && method === "POST") {
      await fixture.writeGate;
      await route.fulfill({ status: 202, json: { case_id: SCOPED_CASE, proposal_id: SCOPED_CASE,
        accepted_at: "2026-09-15T12:00:00Z", state: "awaiting_core", execution_authority: false } });
    } else if (path === `/handover/scoped-duty-cases/${SCOPED_CASE}`) {
      await route.fulfill({ status: fixture.caseStatus, json: fixture.scopedCase });
    } else if (path === "/handover/scoped-duties" && fixture.observation) {
      await route.fulfill({ json: fixture.observation });
    } else {
      await route.fulfill({ status: 503, headers, json: { error: "Synthetic unrelated source unavailable" } });
    }
  });
  return fixture;
}
