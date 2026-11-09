import { expect, test, type Page, type Route } from "@playwright/test";
import { decodeProvisionEvent } from "../../src/hooks/use-provision-stream";
import type { UserContextPayload, UserPreferencePayload } from "../../src/user-context-client";

const NOW = Date.parse("2026-10-01T10:00:00Z");
const preference: UserPreferencePayload = {
  principal_id: "operator-example", locale: "en", verbosity: "concise", answer_detail: "standard",
  answer_format: "prose", answer_preferences_enabled: true, answer_intent_detail: {},
  answer_intent_format: {}, timezone: "UTC", share_with_learner: false, revision: 1,
};
function context(saved = preference): UserContextPayload {
  return {
    preference: saved, memories: [], policies: [], subscriptions: [], briefing_runs: [], scheduled_continuations: [],
    conversations: [{
      conversation_id: "conversation-example", channel_id: "console", started_at: new Date(NOW).toISOString(),
      last_active: new Date(NOW).toISOString(), status: "active", latest_operator_turn_id: "turn-example",
      first_operator_question: "Review the example maintenance window.",
    }],
    conversation_page: { has_more: false, next_cursor: null },
  };
}
function runtime(revision = 1, budget = 30) {
  return {
    revision, can_manage: true, updated_at: null, updated_by: null, integrations: [],
    runtime: {
      environment: "dev", state_store_durable: true, autonomy_default: "shadow", pantheon_enabled: true,
      workflow_observation_enabled: true, primary_transport_configured: true,
      auxiliary_transport_configured: false, case_history_configured: false,
    },
    settings: [
      { key: "analyzer.budget_seconds", effective_value: budget, override_value: budget === 30 ? null : budget, environment_value: 30 },
      { key: "analyzer.window_seconds", effective_value: 300, override_value: null, environment_value: 300 },
    ].map((setting) => ({
      ...setting, group: "analysis", value_type: "integer", minimum: 10, maximum: 3600,
      options: [], restart_required: false, available: true, unavailable_reason: null,
    })),
  };
}
const memoryItems = [
  { id: "memory-old", scope_ref: "resource:example-a", body: "Earlier approved maintenance guidance.", active: false, superseded_by: "memory-latest" },
  { id: "memory-latest", scope_ref: "resource:example-a", body: "Use the approved maintenance window and retain the complete source references.", active: true, superseded_by: null },
  { id: "memory-other", scope_ref: "resource:example-b", body: "Separate guidance for the second logical resource.", active: true, superseded_by: null },
].map((item) => ({
  ...item, scope_kind: "resource", category: "maintenance", source_event: "hil.reject",
  source_ref: "event:example-a", author: "operator-a", approved_by: "operator-b", approval_state: "approved",
  created_at: new Date(NOW).toISOString(), expires_at: null, expired: false,
}));
const compaction = {
  candidate_id: "compaction-example", scope_kind: "resource", scope_ref: "resource:example-a",
  category: "maintenance", body: "Compacted approved maintenance guidance.",
  source_refs: ["event:example-a", "event:example-b"], proposed_by_agent: "Norns",
  state: "approved", reviewed_by: "operator-b", review_reason: "Evidence references reviewed.",
};
const provisionSnapshot = {
  schema_version: "fdai.provision-status.v1", type: "provision.snapshot", run_id: "run-example", sequence: 1,
  attempt: 1, state: "applying", current_stage: "initial-inventory", stages_completed: 1, stages_total: 2,
  checkpoints_completed: 1, checkpoints_total: 2, last_progress_at: new Date(NOW).toISOString(), reason_code: null, ready: false,
  readiness: { database: true, semantic: false, models: false, runtime: false, inventory: false, system: false },
  stages: [{ id: "database", status: "completed" }, { id: "initial-inventory", status: "active" }],
  inventory: { resources_observed: 3, resources_expected: 4, pages_completed: 1, pages_expected: 2,
    provider_types_completed: 1, provider_types_total: 2, links_observed: 2, unmapped_objects: 0, coverage_gaps: 1 },
};

interface FixtureCall {
  readonly method: string;
  readonly path: string;
  readonly url: URL;
  readonly body: Record<string, unknown> | null;
}
type Handler = (route: Route, call: FixtureCall) => Promise<void>;
async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}
async function installFixtures(page: Page, handlers: Readonly<Record<string, Handler>>) {
  const calls: FixtureCall[] = [];
  // Never forward fixture API traffic to a real settings service or provider.
  await page.route("**/*", async (route) => {
    const request = route.request();
    if (!["fetch", "xhr", "eventsource"].includes(request.resourceType())) {
      await route.continue();
      return;
    }
    const url = new URL(request.url());
    const call: FixtureCall = {
      method: request.method(), path: url.pathname.replace(/^\/api(?=\/)/, ""), url,
      body: request.postData() === null ? null : request.postDataJSON() as Record<string, unknown>,
    };
    calls.push(call);
    const handler = handlers[`${call.method} ${call.path}`];
    if (handler) await handler(route, call);
    else if (call.method === "GET" && call.path === "/me/context") await json(route, context());
    else if (call.method === "GET" && call.path === "/healthz") await json(route, { status: "ok" });
    else await json(route, { detail: "Optional browser-test source unavailable." }, 404);
  });
  return {
    calls,
    matching: (method: string, path: string) => calls.filter((call) => call.method === method && call.path === path),
    writes: () => calls.filter((call) => call.method !== "GET"),
  };
}
function deferred() {
  let release!: () => void;
  const ready = new Promise<void>((resolve) => { release = resolve; });
  return { ready, release };
}

test.use({ viewport: { width: 1440, height: 900 } });
test.beforeEach(async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "This file declares desktop acceptance only.");
  await page.emulateMedia({ reducedMotion: "reduce" });
});

test("General waits for account context before reset and cancels without mutation", async ({ page }) => {
  const gate = deferred();
  const fixture = await installFixtures(page, {
    "GET /me/context": async (route) => { await gate.ready; await json(route, context()); },
  });
  try {
    await page.goto("/settings/general?locale=en");
    const root = page.locator(".settings-overlay .settings-route").filter({ has: page.locator("#settings-user-context") });
    const reset = root.getByRole("button", { name: "Reset account and display preferences", exact: true });
    await expect(reset).toBeDisabled();
    await expect(root.locator("#settings-timezone")).toBeDisabled();
    await expect(root.getByText("Account preferences are up to date", { exact: true })).toHaveCount(0);
    expect(fixture.writes()).toEqual([]);
    gate.release();
    await expect(root.locator("#settings-timezone")).toHaveValue("UTC");
    await expect(reset).toBeEnabled();
    const confirmations: string[] = [];
    page.once("dialog", async (dialog) => {
      confirmations.push(dialog.message());
      await dialog.dismiss();
    });
    await reset.click();
    expect(confirmations).toHaveLength(1);
    expect(confirmations[0]).toContain("Briefings and saved memories will not be deleted");
    expect(fixture.writes()).toEqual([]);
    await expect(reset).toBeEnabled();
  } finally { gate.release(); }
});

test("General preserves an unsaved draft through briefing readback and discards locally", async ({ page }) => {
  let subscriptions: UserContextPayload["subscriptions"] = [];
  const fixture = await installFixtures(page, {
    "GET /me/context": async (route) => { await json(route, { ...context(), subscriptions }); },
    "POST /me/briefing-subscriptions": async (route) => {
      subscriptions = [{
        subscription_id: "briefing-example", name: "Daily major issues", cron_expression: "0 7 * * *",
        timezone: "Asia/Seoul", enabled: true, next_run_at: "2026-10-02T07:00:00+09:00", spec: {}, revision: 1,
      }];
      await json(route, {});
    },
  });
  await page.goto("/settings/general?locale=en");
  const root = page.locator(".settings-overlay .settings-route").filter({ has: page.locator("#settings-user-context") });
  const timezone = root.locator("#settings-timezone");
  await expect(timezone).toBeEnabled();
  await timezone.fill(" Asia/Seoul ");
  await root.locator(".settings-briefing-create").getByRole("button").click();
  await expect(root.getByText("Daily major issues", { exact: true })).toBeVisible();
  await expect(timezone).toHaveValue(" Asia/Seoul ");
  expect(fixture.matching("POST", "/me/briefing-subscriptions")).toHaveLength(1);
  expect(fixture.matching("POST", "/me/briefing-subscriptions")[0]!.body?.["timezone"]).toBe("Asia/Seoul");
  const saveBar = root.locator(".settings-save-bar");
  await saveBar.getByRole("button", { name: "Discard changes", exact: true }).click();
  await expect(timezone).toHaveValue("UTC");
  await expect(saveBar.getByRole("button", { name: "Save user context", exact: true })).toBeDisabled();
  expect(fixture.writes().map((call) => `${call.method} ${call.path}`)).toEqual(["POST /me/briefing-subscriptions"]);
});

test("General recovers only the unfinished response policy after a partial save", async ({ page }) => {
  let saved = preference;
  let policyAttempts = 0;
  let policies: UserContextPayload["policies"] = [];
  const fixture = await installFixtures(page, {
    "GET /me/context": async (route) => { await json(route, { ...context(saved), policies }); },
    "PUT /me/preferences": async (route) => {
      saved = { ...preference, answer_detail: "deep", verbosity: "detailed", revision: 2 };
      await json(route, saved);
    },
    "PUT /me/policies": async (route) => {
      policyAttempts += 1;
      if (policyAttempts === 1) { await json(route, { detail: "Fixture policy synchronization unavailable." }, 503); return; }
      policies = [{
        policy_id: "response-defaults", kind: "response_defaults", enabled: true, revision: 1,
        source_turn_id: "turn-example", briefing_spec: null,
        response_defaults: { verbosity: "detailed", answer_language: "en" },
      }];
      await json(route, policies[0]);
    },
  });
  await page.goto("/settings/general?locale=en");
  const root = page.locator(".settings-overlay .settings-route").filter({ has: page.locator("#settings-user-context") });
  await expect(root.locator("#settings-timezone")).toBeEnabled();
  await root.getByRole("group", { name: "Answer detail", exact: true }).getByRole("button", { name: "Deep", exact: true }).click();
  const save = root.getByRole("button", { name: "Save user context", exact: true });
  await save.click();
  const retry = root.getByRole("button", { name: "Retry response-policy synchronization", exact: true });
  await expect(retry).toBeEnabled();
  await expect(root.getByText(/User preferences were saved, but response defaults failed:/)).toBeVisible();
  await expect(save).toBeDisabled();
  expect(fixture.matching("PUT", "/me/preferences")).toHaveLength(1);
  await retry.click();
  await expect(root.getByText("Account preferences saved and read back.", { exact: true })).toBeVisible();
  await expect(retry).toHaveCount(0);
  expect(fixture.matching("PUT", "/me/preferences")).toHaveLength(1);
  expect(fixture.matching("PUT", "/me/policies")).toHaveLength(2);
  expect(fixture.matching("PUT", "/me/preferences")[0]!.body?.["expected_revision"]).toBe(1);
  expect(fixture.matching("PUT", "/me/policies").map((call) => call.body?.["expected_revision"])).toEqual([0, 0]);
});

test("Runtime blocks invalid numeric input, filters locally, and preserves conflict drafts", async ({ page }) => {
  let current = runtime();
  let saveAttempts = 0;
  const fixture = await installFixtures(page, {
    "GET /runtime/settings": async (route) => { await json(route, current); },
    "PUT /runtime/settings": async (route) => {
      saveAttempts += 1;
      current = runtime(saveAttempts === 1 ? 2 : 3, saveAttempts === 1 ? 60 : 90);
      await json(route, saveAttempts === 1 ? { detail: "Fixture revision conflict." } : current, saveAttempts === 1 ? 409 : 200);
    },
  });
  await page.goto("/settings/runtime-policies?locale=en");
  const root = page.locator(".settings-overlay .settings-runtime-route");
  const policyRows = root.locator(".settings-runtime-section .settings-runtime-row[data-value-type]");
  const budget = root.getByRole("spinbutton", { name: "Analyzer time budget", exact: true });
  const save = root.locator(".settings-runtime-actions .primary");
  await expect(budget).toHaveValue("30");
  await budget.fill("");
  await expect(budget).toHaveAttribute("aria-invalid", "true");
  await expect(save).toBeDisabled();
  expect(fixture.writes()).toEqual([]);
  await budget.fill("90");
  await root.getByRole("checkbox", { name: "Changed policies only", exact: true }).check();
  await expect(policyRows).toHaveCount(1);
  await expect(root.getByRole("spinbutton", { name: "Analyzer observation window", exact: true })).toHaveCount(0);
  await expect(root.getByText("Showing 1 of 2 loaded policies", { exact: true })).toBeVisible();
  await root.getByRole("searchbox", { name: "Find a policy", exact: true }).fill("no-policy-matches-this");
  await expect(root.getByText("No policies match these filters.", { exact: true })).toBeVisible();
  await root.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(policyRows).toHaveCount(2);
  await expect(budget).toHaveValue("90");
  expect(fixture.writes()).toEqual([]);
  await save.click();
  await expect(root.getByText("Your draft is preserved. Review the latest revision 2 before applying it again.", { exact: true })).toBeVisible();
  await expect(budget).toHaveValue("90");
  await expect(save).toBeDisabled();
  await root.getByRole("button", { name: "Use latest revision and keep this draft", exact: true }).click();
  await expect(save).toBeEnabled();
  expect(fixture.matching("PUT", "/runtime/settings")).toHaveLength(1);
  await save.click();
  await expect.poll(() => fixture.matching("PUT", "/runtime/settings").length).toBe(2);
  await expect(budget).toBeEnabled();
  await expect(save).toBeDisabled();
  await expect(budget).toHaveValue("90");
  expect(fixture.matching("PUT", "/runtime/settings").map((call) => call.body)).toEqual([
    { changes: { "analyzer.budget_seconds": 90 }, expected_revision: 1 },
    { changes: { "analyzer.budget_seconds": 90 }, expected_revision: 2 },
  ]);
});

test("Environment expires evidence and preserves deployment subviews with GET-only refresh", async ({ page }) => {
  expect(decodeProvisionEvent(JSON.stringify(provisionSnapshot))).toMatchObject({
    phase: "snapshot", run_id: "run-example", stages_completed: 1,
  });
  await page.clock.install({ time: new Date(NOW) });
  let observerReads = 0;
  const fixture = await installFixtures(page, {
    "GET /system/data-sources": async (route) => { await json(route, {
      surface: "read-data-sources", sources: [{
        key: "provisioning-stream", source: "browser-test-fixture", routes: ["/provision/stream"],
        availability: "available", configured: true, reachable: true, authoritative: true,
        durable: true, synthetic: true, reason: null, last_observed_at: new Date(NOW).toISOString(),
      }],
    }); },
    "GET /observer-deployment-proposals": async (route) => {
      observerReads += 1;
      await json(route, { synthetic: false, execution_authority: false, items: [{
        target_ref: "cluster-example", expires_at: new Date(NOW + observerReads * 60_000).toISOString(),
        state: "current", execution_authority: false,
        proposal: { target_ref: "cluster-example", status: "needs_evidence", execution_authority: false,
          approval_required: true, recommended: null,
          candidates: [{ method: "gitops", egress: "private", state: "unknown", blockers: [], missing: ["kubernetes_read"] }] },
      }] });
    },
    "GET /onboarding": async (route) => { await json(route, {
      probe_mode: "configured", ready: true, blocked: false, missing_resources: [], missing_role_assignments: [],
      present_resource_count: 5, present_role_count: 4, error: null,
    }); },
    "GET /provision/stream": async (route) => {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify(provisionSnapshot)}\n\n` });
    },
  });
  await page.goto("/settings/environment-and-deployment/observers?locale=en");
  const root = page.locator(".settings-overlay .environment-deployment-route");
  const proposal = root.locator(".observer-proposal");
  await expect(proposal.locator("summary")).toContainText("More evidence needed");
  await proposal.locator("summary").click();
  await expect(proposal.getByText("Kubernetes read access", { exact: false })).toBeVisible();
  await page.clock.fastForward(60_100);
  await expect(proposal.locator("summary")).toContainText("Expired evidence");
  await expect(proposal.getByText(/Refresh evidence to request a new observation, not an installation/)).toBeVisible();
  await expect(proposal.locator("time")).toHaveAttribute("datetime", new Date(NOW + 60_000).toISOString());
  expect(observerReads).toBe(1);
  await root.getByRole("button", { name: "Refresh evidence", exact: true }).click();
  await expect(proposal.locator("summary")).toContainText("More evidence needed");
  expect(observerReads).toBe(2);
  const environmentTabs = root.locator(".environment-deployment-tabs");
  await environmentTabs.getByRole("tab", { name: "Deployment run", exact: true }).click();
  await expect(root.locator(".provision-tabs").getByRole("tab", { name: "Stages", exact: true })).toBeVisible();
  const resources = root.locator(".provision-tabs").getByRole("tab", { name: "Resources", exact: true });
  await resources.click();
  await expect(resources).toHaveAttribute("aria-selected", "true");
  await expect(page).toHaveURL((url) => url.pathname.endsWith("/deployment")
    && url.searchParams.get("deployment-view") === "resources" && url.searchParams.get("locale") === "en");
  await environmentTabs.getByRole("tab", { name: "Readiness", exact: true }).click();
  await expect(page).toHaveURL((url) => url.pathname === "/settings/environment-and-deployment"
    && url.searchParams.get("deployment-view") === "resources" && url.searchParams.get("locale") === "en");
  await expect(root.locator(".onboarding-route")).toBeVisible();
  await expect(root.locator(".provision")).toHaveCount(0);
  const hiddenStreamReads = fixture.matching("GET", "/provision/stream").length;
  await page.clock.fastForward(10_000);
  expect(fixture.matching("GET", "/provision/stream")).toHaveLength(hiddenStreamReads);
  await environmentTabs.getByRole("tab", { name: "Deployment run", exact: true }).click();
  await expect(resources).toHaveAttribute("aria-selected", "true");
  await page.reload();
  await expect(resources).toHaveAttribute("aria-selected", "true");
  const beforeReload = fixture.matching("GET", "/provision/stream").length;
  await root.getByRole("button", { name: "Reload deployment evidence", exact: true }).click();
  await expect.poll(() => fixture.matching("GET", "/provision/stream").length).toBeGreaterThan(beforeReload);
  await expect(resources).toHaveAttribute("aria-selected", "true");
  expect(fixture.writes()).toEqual([]);
});

test("Memory distinguishes applied URL filters, clears them, and refreshes/details read-only", async ({ page }) => {
  const fixture = await installFixtures(page, {
    "GET /operator-memory": async (route, call) => {
      const kind = call.url.searchParams.get("scope_kind");
      const ref = call.url.searchParams.get("scope_ref");
      await json(route, {
        items: memoryItems.filter((item) => (!kind || item.scope_kind === kind) && (!ref || item.scope_ref === ref)),
        compactions: (!kind || kind === compaction.scope_kind) && (!ref || ref === compaction.scope_ref) ? [compaction] : [],
      });
    },
  });
  await page.goto("/settings/memory?locale=en&scope_kind=resource&scope_ref=resource%3Aexample-a");
  const root = page.locator(".settings-overlay .operator-memory-route");
  const kind = root.getByRole("combobox", { name: "Scope kind", exact: true });
  const ref = root.getByRole("textbox", { name: "Scope reference", exact: true });
  await expect(root.locator(".data-table").first()).toBeVisible();
  await expect(kind).toHaveValue("resource");
  await expect(ref).toHaveValue("resource:example-a");
  await ref.fill("resource:example-b");
  await expect(root.getByText("Filter changes have not been applied.", { exact: true })).toBeVisible();
  await expect(root.locator(".settings-filter-summary")).toContainText("Displayed scope: Resource: resource:example-a");
  await root.getByRole("button", { name: "Refresh memory evidence", exact: true }).click();
  await expect.poll(() => fixture.matching("GET", "/operator-memory").length).toBe(2);
  await expect(root.getByRole("button", { name: "Refresh memory evidence", exact: true })).toBeEnabled();
  expect(fixture.matching("GET", "/operator-memory")[1]!.url.searchParams.get("scope_ref")).toBe("resource:example-a");
  await expect(ref).toHaveValue("resource:example-b");
  await root.getByRole("button", { name: "Filter", exact: true }).click();
  await expect(root.getByText("Separate guidance for the second logical resource.", { exact: true }).first()).toBeVisible();
  await expect(page).toHaveURL((url) => url.searchParams.get("scope_ref") === "resource:example-b" && url.searchParams.get("locale") === "en");
  await root.getByRole("button", { name: "Clear filters", exact: true }).click();
  await expect(ref).toHaveValue("");
  await expect(kind).toHaveValue("");
  await expect(page).toHaveURL((url) => !url.searchParams.has("scope_ref") && !url.searchParams.has("scope_kind") && url.searchParams.get("locale") === "en");
  const old = root.locator("#memory-memory-old");
  await old.locator("summary").click();
  await expect(old.getByRole("link", { name: "memory-latest", exact: true })).toHaveAttribute("href", "#memory-memory-latest");
  await expect(old.getByText("Earlier approved maintenance guidance.", { exact: true }).last()).toBeVisible();
  const candidate = root.locator(".data-table").first().locator("tbody tr").first();
  await candidate.locator("summary").click();
  await expect(candidate.getByText("Evidence references reviewed.", { exact: true })).toBeVisible();
  await expect(candidate.locator("code").filter({ hasText: "event:example-b" })).toBeVisible();
  await expect(root.getByText(/up to 100 memory entries/)).toBeVisible();
  expect(fixture.matching("GET", "/operator-memory").every((call) => call.url.searchParams.get("limit") === "100")).toBe(true);
  expect(fixture.writes()).toEqual([]);
});

test("Settings preferences reflow read-only at 993x641 then 390x844 in English and Korean", async ({ page }) => {
  const longTarget = `cluster-${"example-".repeat(16)}bound`;
  const longSource = `event:${"example-source-".repeat(12)}bound`;
  const history = Array.from({ length: 12 }, (_, index) => ({
    run_id: `briefing-example-${index + 1}`, title: `Approved operational summary ${index + 1}`,
    body_markdown: "Review the complete evidence references before interpreting this read-only operational summary.",
    status: "completed", item_count: 1, evidence_refs: ["event:example-a"], source_errors: [],
  }));
  const resourcePolicy = { enabled: false, resource_types: [], resources: {}, max_age_seconds: 300 };
  const fixture = await installFixtures(page, {
    "GET /me/context": async (route) => { await json(route, {
      ...context(), briefing_runs: history, subscriptions: [{
        subscription_id: "briefing-example", name: "Approved daily operational summary",
        cron_expression: "0 7 * * *", timezone: "Asia/Seoul", enabled: true,
        next_run_at: "2030-10-02T07:00:00+09:00", spec: {}, revision: 1,
      }],
    }); },
    "GET /runtime/settings": async (route) => { await json(route, {
      ...runtime(), settings: [...runtime().settings, {
        key: "detection.resource_availability", group: "investigation", value_type: "object",
        environment_value: resourcePolicy, effective_value: resourcePolicy, override_value: null,
        minimum: null, maximum: null, options: [], restart_required: false, available: true, unavailable_reason: null,
      }],
    }); },
    "GET /operator-memory": async (route, call) => {
      const kind = call.url.searchParams.get("scope_kind");
      const ref = call.url.searchParams.get("scope_ref");
      await json(route, {
        items: memoryItems.filter((item) => (!kind || item.scope_kind === kind) && (!ref || item.scope_ref === ref))
          .map((item) => ({ ...item, source_ref: longSource })),
        compactions: (!kind || kind === compaction.scope_kind) && (!ref || ref === compaction.scope_ref)
          ? [{ ...compaction, source_refs: [longSource, "event:example-b"] }] : [],
      });
    },
    "GET /observer-deployment-proposals": async (route) => { await json(route, {
      synthetic: false, execution_authority: false,
      items: [longTarget, "cluster-other"].map((target, index) => ({
        target_ref: target, expires_at: "2099-01-01T00:00:00Z", state: "current", execution_authority: false,
        proposal: {
          target_ref: target, status: index === 0 ? "needs_evidence" : "blocked",
          execution_authority: false, approval_required: true, recommended: null,
          candidates: [{ method: "gitops", egress: "private", state: index === 0 ? "unknown" : "blocked",
            blockers: index === 0 ? [] : ["persistent_storage"], missing: index === 0 ? ["kubernetes_read"] : [] }],
        },
      })),
    }); },
    "GET /system/data-sources": async (route) => { await json(route, {
      surface: "read-data-sources", sources: [{
        key: "provisioning-stream", source: "browser-test-fixture", routes: ["/provision/stream"],
        availability: "available", configured: true, reachable: true, authoritative: true,
        durable: true, synthetic: true, reason: null, last_observed_at: new Date(NOW).toISOString(),
      }],
    }); },
    "GET /provision/stream": async (route) => {
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: `data: ${JSON.stringify(provisionSnapshot)}\n\n` });
    },
  });
  const labels = {
    en: {
      current: "Account preferences are up to date", schedule: "Schedule details",
      history: "Showing 10 of 12 loaded briefing results", allHistory: "Showing 12 of 12 loaded briefing results",
      more: "Show more briefing results", policies: "Showing 3 of 3 loaded policies",
      noChanges: "Showing 0 of 3 loaded policies", filteredPolicy: "Showing 1 of 3 loaded policies",
      changed: "Changed policies only", clear: "Clear filters",
      observers: "Showing 2 of 2 loaded observer targets", filteredObserver: "Showing 1 of 2 loaded observer targets",
      proposalMissing: "Kubernetes read access",
      memory: "2 loaded memory entries, 1 loaded compaction candidates",
      filteredMemory: "1 loaded memory entries, 0 loaded compaction candidates",
      allMemory: "3 loaded memory entries, 1 loaded compaction candidates",
      pending: "Filter changes have not been applied.",
    },
    ko: {
      current: "계정 환경 설정이 최신 상태입니다", schedule: "예약 상세 정보",
      history: "불러온 브리핑 결과 12개 중 10개 표시", allHistory: "불러온 브리핑 결과 12개 중 12개 표시",
      more: "브리핑 결과 더 보기", policies: "불러온 정책 3개 중 3개 표시",
      noChanges: "불러온 정책 3개 중 0개 표시", filteredPolicy: "불러온 정책 3개 중 1개 표시",
      changed: "변경한 정책만 표시", clear: "필터 초기화",
      observers: "불러온 관측 대상 2개 중 2개 표시", filteredObserver: "불러온 관측 대상 2개 중 1개 표시",
      proposalMissing: "Kubernetes 읽기 접근 권한",
      memory: "메모리 항목 2개, 압축 검토 후보 1개를 불러왔습니다",
      filteredMemory: "메모리 항목 1개, 압축 검토 후보 0개를 불러왔습니다",
      allMemory: "메모리 항목 3개, 압축 검토 후보 1개를 불러왔습니다",
      pending: "필터 변경 사항을 아직 적용하지 않았습니다.",
    },
  } as const;
  const checkReflow = async (selector: string, state: string, touch: boolean) => {
    const root = page.locator(selector);
    await expect(root).toBeVisible();
    const failures = await root.evaluate((element, checkTouch) => {
      const overlay = element.closest<HTMLElement>(".settings-overlay");
      const content = element.closest<HTMLElement>(".settings-overlay-content");
      const failures: string[] = [];
      const boxes: Array<{ name: string; node: Element | null }> = [
        { name: "document", node: document.documentElement }, { name: "overlay", node: overlay },
        { name: "content", node: content }, { name: "menu", node: element },
      ];
      for (const { name, node } of boxes) {
        if (!node) { failures.push(`${name}: missing containment boundary`); continue; }
        if (node.scrollWidth > node.clientWidth) failures.push(`${name}: scrollWidth ${node.scrollWidth} > clientWidth ${node.clientWidth}`);
      }
      if (overlay && content) {
        const bounds = [
          { name: "overlay", child: overlay, parent: document.documentElement },
          { name: "content", child: content, parent: overlay }, { name: "menu", child: element, parent: content },
        ];
        for (const { name, child, parent } of bounds) {
          const a = child.getBoundingClientRect();
          const b = parent.getBoundingClientRect();
          if (a.left < b.left - 1 || a.right > b.right + 1) failures.push(`${name}: horizontal bounds ${a.left}:${a.right} outside ${b.left}:${b.right}`);
        }
        if (checkTouch) {
          const controls = [
            ...element.querySelectorAll<HTMLElement>(
              "button:not(:disabled), input:not(:disabled):not([type=checkbox]):not([type=radio]), select:not(:disabled), textarea:not(:disabled), summary, label:has(input[type=checkbox]:not(:disabled)), a[href^='#memory-']",
            ),
            ...overlay.querySelectorAll<HTMLElement>(".settings-overlay-header button:not(:disabled)"),
          ];
          for (const control of controls) {
            if (control.getClientRects().length === 0 || getComputedStyle(control).visibility === "hidden") continue;
            const rect = control.getBoundingClientRect();
            if (rect.width < 44 || rect.height < 44) {
              const name = control.getAttribute("aria-label") || control.textContent?.trim().slice(0, 80) || control.tagName;
              failures.push(`touch target ${name}: ${rect.width.toFixed(2)}x${rect.height.toFixed(2)} < 44x44`);
            }
          }
        }
      }
      return failures;
    }, touch);
    expect(failures, state).toEqual([]);
  };
  for (const viewport of [
    { width: 1208, height: 984 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    for (const locale of ["en", "ko"] as const) {
      const text = labels[locale];
      const state = `${viewport.width}x${viewport.height}/${locale}`;
      const touch = viewport.width === 390;
      await test.step(`${state}/General loaded and expanded history`, async () => {
        await page.goto(`/settings/general?locale=${locale}`);
        const selector = ".settings-overlay .settings-route:has(#settings-user-context)";
        const root = page.locator(selector);
        await expect(root.getByText(text.current, { exact: true })).toBeVisible();
        await expect(root.getByText(text.history, { exact: true })).toBeVisible();
        await checkReflow(selector, `${state}/General loaded`, touch);
        await root.getByRole("button", { name: text.more, exact: true }).click();
        await expect(root.getByText(text.allHistory, { exact: true })).toBeVisible();
        await root.locator("summary").filter({ hasText: text.schedule }).click();
        await expect(root.locator("details[open] code").filter({ hasText: "0 7 * * *" })).toBeVisible();
        await checkReflow(selector, `${state}/General expanded`, touch);
      });
      await test.step(`${state}/Runtime loaded and local filters`, async () => {
        await page.goto(`/settings/runtime-policies?locale=${locale}`);
        const selector = ".settings-overlay .settings-runtime-route";
        const root = page.locator(selector);
        await expect(root.getByText(text.policies, { exact: true })).toBeVisible();
        await checkReflow(selector, `${state}/Runtime loaded`, touch);
        await root.getByRole("checkbox", { name: text.changed, exact: true }).check();
        await expect(root.getByText(text.noChanges, { exact: true })).toBeVisible();
        await root.getByRole("button", { name: text.clear, exact: true }).click();
        await root.locator(".settings-filter-bar input[type=search]").fill("detection.resource_availability");
        await expect(root.getByText(text.filteredPolicy, { exact: true })).toBeVisible();
        await expect(root.locator("textarea")).toBeVisible();
        await checkReflow(selector, `${state}/Runtime filtered structured policy`, touch);
      });
      await test.step(`${state}/Environment filtered disclosures and deployment subview`, async () => {
        await page.goto(`/settings/environment-and-deployment/observers?locale=${locale}`);
        const selector = ".settings-overlay .environment-deployment-route";
        const root = page.locator(selector);
        await expect(root.getByText(text.observers, { exact: true })).toBeVisible();
        await checkReflow(selector, `${state}/Environment loaded`, touch);
        await root.locator(".settings-filter-bar input[type=search]").fill("example");
        await root.locator(".settings-filter-bar select").selectOption("needs_evidence");
        await expect(root.getByText(text.filteredObserver, { exact: true })).toBeVisible();
        const proposal = root.locator(".observer-proposal").filter({ hasText: longTarget });
        await proposal.locator("summary").click();
        await expect(proposal.getByText(text.proposalMissing, { exact: false })).toBeVisible();
        await checkReflow(selector, `${state}/Environment filtered details`, touch);
        await root.locator("#environment-deployment-tab-deployment").click();
        await root.locator("#provision-tab-resources").click();
        await expect(root.locator("#provision-tab-resources")).toHaveAttribute("aria-selected", "true");
        await checkReflow(selector, `${state}/Environment deployment resources`, touch);
      });
      await test.step(`${state}/Memory URL filters and complete record details`, async () => {
        await page.goto(`/settings/memory?locale=${locale}&scope_kind=resource&scope_ref=resource%3Aexample-a`);
        const selector = ".settings-overlay .operator-memory-route";
        const root = page.locator(selector);
        await expect(root.getByText(text.memory, { exact: true })).toBeVisible();
        await checkReflow(selector, `${state}/Memory scoped`, touch);
        await root.locator(".settings-filter-bar input").fill("resource:example-b");
        await expect(root.getByText(text.pending, { exact: true })).toBeVisible();
        await root.locator(".settings-filter-bar button[type=submit]").click();
        await expect(root.getByText(text.filteredMemory, { exact: true })).toBeVisible();
        await checkReflow(selector, `${state}/Memory applied filter`, touch);
        await root.getByRole("button", { name: text.clear, exact: true }).click();
        await expect(root.getByText(text.allMemory, { exact: true })).toBeVisible();
        const old = root.locator("#memory-memory-old");
        await old.locator("summary").click();
        await expect(old.getByRole("link", { name: "memory-latest", exact: true })).toBeVisible();
        const candidate = root.locator(".data-table").first().locator("tbody tr").first();
        await candidate.locator("summary").click();
        await expect(candidate.getByText("Evidence references reviewed.", { exact: true })).toBeVisible();
        await expect(old.locator("details[open] code").filter({ hasText: longSource })).toBeVisible();
        await checkReflow(selector, `${state}/Memory complete details`, touch);
      });
      expect(fixture.writes(), `${state}/all four menus remain GET-only`).toEqual([]);
    }
  }
});
