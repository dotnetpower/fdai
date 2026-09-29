import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import en from "../../src/i18n/messages.en.json" with { type: "json" };
import ko from "../../src/i18n/messages.ko.json" with { type: "json" };

const draft = {
  target_ref: "resource-example", signal_code: "cpu_percent", source_ref: "turn:example",
  semantic_receipt: `sha256:${"a".repeat(64)}`,
  authority: "candidate_only", execution_authority: false,
  window: {
    expected_min: 60, expected_max: 90,
    effective_from: "2026-09-15T10:00:00+00:00",
    effective_to: "2026-09-15T11:00:00+00:00",
  },
};
const status = {
  proposal_id: "proposal-submitted", operation: "test-context.propose",
  dispatch_status: "published", accepted_at: "2026-09-15T00:00:00Z",
  policy_application: "recorded", current_authorization: "not_evaluated",
  execution_authority: false,
  reviewer_transition_allowed: false,
  requester_is_current_principal: true,
  request: {
    operation: "propose", context_id: "case-one:cpu_percent:aaaaaaaaaaaaaaaa",
    access_scope_digest: "a".repeat(64), target_ref: "resource-example",
    signal_code: "cpu_percent", expected_revision: 0, policy_revision: "policy:example",
    source_ref: "turn:example", semantic_receipt: `sha256:${"a".repeat(64)}`,
    expected_min: 60, expected_max: 90,
    effective_from: "2026-09-15T10:00:00+00:00",
    effective_to: "2026-09-15T11:00:00+00:00",
  },
  context_application: { state: "proposed", revision: 1, execution_authority: false },
};

const reviewedStatus = {
  proposal_id: "reviewed-command", operation: "test-context.review",
  dispatch_status: "published", accepted_at: "2026-09-15T00:05:00Z",
  policy_application: "recorded", current_authorization: "not_evaluated",
  execution_authority: false, reviewer_transition_allowed: true, requester_is_current_principal: false,
  request: {
    operation: "review", context_id: "case-one:cpu_percent:aaaaaaaaaaaaaaaa",
    access_scope_digest: "a".repeat(64), target_ref: "vm-b",
    signal_code: "cpu_percent", expected_revision: 1, policy_revision: "policy:example",
    source_ref: "turn:proposal", semantic_receipt: `sha256:${"c".repeat(64)}`,
  },
  context_application: { state: "reviewed", revision: 2, execution_authority: false },
};
const revokedStatus = {
  ...reviewedStatus, proposal_id: "revoke-submitted", operation: "test-context.revoke",
  current_authorization: "not_evaluated",
  context_application: { state: "revoked", revision: 3, execution_authority: false },
};

const choices = {
  schema_version: "1.0.0", source_revision: "sha256:" + "b".repeat(64) + "#7",
  choices: [{
    case_scope_id: "case-one", access_scope_digest: "a".repeat(64),
    target_selectors: ["resource-example"], policy_revision: "policy:example",
    source_revision: "sha256:" + "b".repeat(64) + "#7",
    allowed_operations: ["propose", "review", "revoke"], execution_authority: false,
  }],
  unavailable_reasons: [], execution_authority: false,
};

async function openCandidate(page: Page, locale: "en" | "ko", options: { delayChoices?: boolean } = {}) {
  const requests: { method: string; path: string }[] = [];
  let releaseChoices: (() => void) | null = null;
  const choicesReady = new Promise<void>((resolve) => { releaseChoices = resolve; });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    requests.push({ method: request.method(), path });
    if (path.endsWith("/iam/self")) return route.fulfill({ json: {
      principal: { subject_id: "example-operator", username: "operator@example.com", roles: ["Owner"] },
      request: null, can_access_console: true,
    } });
    if (path.endsWith("/iam")) return route.fulfill({ json: {
      principal: { oid: "example-operator", roles: ["Owner"], capabilities: ["view-console"] },
      roles: [], assignment_boundary: "identity-provider-group",
      access_authority: { source: "server-verified", is_owner: true, can_manage_group_membership: false },
    } });
    if (path.endsWith("/chat/health")) return route.fulfill({ json: { available: true, mode: "test", model: "test" } });
    if (path.endsWith("/chat/stream")) return route.fulfill({
      contentType: "text/event-stream",
      body: `event: done\ndata: ${JSON.stringify({
        seq: 1, revision: 1, status: "action_draft", answer: "Candidate only.",
        source: "semantic:action-draft", model: "test", test_context_draft: draft,
        semantic_receipt: {
          schema_version: "1.0.0", projection_id: randomUUID(),
          request_id: (request.postDataJSON() as { request_id: string }).request_id,
          disposition: "action_draft", reason_code: "semantic_action_draft",
          semantic_route: "semantic_action_draft", execution_authority: false,
        },
      })}\n\n`,
    });
    if (path.endsWith("/test-context/choices")) {
      if (options.delayChoices) await choicesReady;
      return route.fulfill({ json: choices });
    }
    if (path.endsWith("/test-context/proposals")) return route.fulfill({ json: { accepted: true, proposal_id: "proposal-submitted", duplicate: false } });
    if (path.endsWith("/test-context/commands/proposal-submitted")) return route.fulfill({ json: status });
    if (path.endsWith("/test-context/commands/reviewed-command")) return route.fulfill({ json: reviewedStatus });
    if (path.endsWith("/test-context/revocations")) return route.fulfill({ json: { accepted: true, proposal_id: "revoke-submitted", duplicate: false } });
    if (path.endsWith("/test-context/commands/revoke-submitted")) return route.fulfill({ json: revokedStatus });
    return route.fulfill({ status: 404, json: { detail: "test-only unavailable source" } });
  });
  await page.goto(`/overview?locale=${locale}`);
  await page.locator(".deck-invoke").click();
  await page.locator(".deck-input").fill("Prepare a test context");
  await page.locator(".deck-input").press("Enter");
  await expect(page.getByText("Candidate only.", { exact: true })).toBeVisible();
  return { requests, releaseChoices: releaseChoices ?? (() => undefined) };
}

test("English desktop candidate and historical command status remain non-authoritative", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { requests } = await openCandidate(page, "en");
  const panel = page.getByRole("region", { name: en.deck.testContext.title });
  await expect(panel).toBeVisible();
  await expect(panel).toContainText(draft.target_ref);
  await expect(panel).toContainText(draft.signal_code);
  await expect(panel).toContainText(draft.source_ref);
  await expect(panel).toContainText(draft.window.effective_from);
  await expect(panel).toContainText(en.deck.testContext.choice);
  await panel.getByRole("button", { name: en.deck.testContext.submitProposal }).click();
  await expect(panel).toContainText("proposal-submitted");
  await expect(panel).toContainText(en.deck.testContext.deliveryStates.published);
  await expect(panel).toContainText(en.deck.testContext.applicationStates.recorded);
  await expect(panel).toContainText(en.deck.testContext.authorizationStates.not_evaluated);
  expect(requests.filter(({ path }) => path.includes("/test-context/"))).toEqual([
    { method: "GET", path: "/api/test-context/choices" },
    { method: "POST", path: "/api/test-context/proposals" },
    { method: "GET", path: "/api/test-context/commands/proposal-submitted" },
  ]);
  const geometry = await page.locator(".deck-test-context").evaluate((element) => ({
    width: element.clientWidth, scroll: element.scrollWidth,
    documentWidth: document.documentElement.clientWidth,
    documentScroll: document.documentElement.scrollWidth,
  }));
  expect(geometry.scroll).toBeLessThanOrEqual(geometry.width);
  expect(geometry.documentScroll).toBeLessThanOrEqual(geometry.documentWidth);
  await page.route("**/api/test-context/commands/missing-command", (route) =>
    route.fulfill({ status: 404, json: { detail: "not found" } }));
  await panel.getByLabel(en.deck.testContext.commandId).fill("missing-command");
  await panel.getByRole("button", { name: en.deck.testContext.lookup }).click();
  await expect(panel).toContainText(en.deck.testContext.unavailable);
  await page.unroute("**/api/test-context/commands/missing-command");
  await page.route("**/api/test-context/commands/error-command", (route) =>
    route.fulfill({ status: 503, json: { detail: "unclassified failure" } }));
  await panel.getByLabel(en.deck.testContext.commandId).fill("error-command");
  await panel.getByRole("button", { name: en.deck.testContext.lookup }).click();
  await expect(panel).toContainText(en.deck.testContext.error);
});

test("Korean candidate reflows without upgrading draft authority", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  const { requests } = await openCandidate(page, "ko");
  const panel = page.getByRole("region", { name: ko.deck.testContext.title });
  await expect(panel).toContainText(ko.deck.testContext.choice);
  await page.setViewportSize({ width: 993, height: 641 });
  await expect(panel).toBeVisible();
  const constrained = await panel.evaluate((element) => ({
    width: element.clientWidth, scroll: element.scrollWidth,
    documentWidth: document.documentElement.clientWidth,
    documentScroll: document.documentElement.scrollWidth,
  }));
  expect(constrained.scroll).toBeLessThanOrEqual(constrained.width);
  expect(constrained.documentScroll).toBeLessThanOrEqual(constrained.documentWidth);
  await page.setViewportSize({ width: 390, height: 844 });
  const geometry = await panel.evaluate((element) => ({
    width: element.clientWidth, scroll: element.scrollWidth,
    documentWidth: document.documentElement.clientWidth,
    documentScroll: document.documentElement.scrollWidth,
  }));
  expect(geometry.scroll).toBeLessThanOrEqual(geometry.width);
  expect(geometry.documentScroll).toBeLessThanOrEqual(geometry.documentWidth);
  expect(requests.filter(({ method, path }) => method !== "GET" && path.includes("/test-context/"))).toEqual([]);
});


test("manual lookup does not discard delayed reviewed choices", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const opened = await openCandidate(page, "en", { delayChoices: true });
  const panel = page.getByRole("region", { name: en.deck.testContext.title });
  await panel.getByLabel(en.deck.testContext.commandId).fill("proposal-submitted");
  await panel.getByRole("button", { name: en.deck.testContext.lookup }).click();
  await expect(panel).toContainText(en.deck.testContext.deliveryStates.published);
  opened.releaseChoices();
  await expect(panel.getByLabel(en.deck.testContext.choice)).toBeVisible();
  await expect(panel.getByRole("button", { name: en.deck.testContext.submitProposal })).toBeEnabled();
});


test("reviewer can revoke an active reviewed request from decoded status", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await openCandidate(page, "en");
  const panel = page.getByRole("region", { name: en.deck.testContext.title });
  await panel.getByLabel(en.deck.testContext.commandId).fill("reviewed-command");
  await panel.getByRole("button", { name: en.deck.testContext.lookup }).click();
  await expect(panel).toContainText("vm-b");
  await expect(panel).toContainText(en.deck.testContext.authorizationStates.not_evaluated);
  await panel.getByRole("button", { name: en.deck.testContext.revoke }).click();
  await expect(panel).toContainText("revoke-submitted");
  await expect(panel).toContainText(en.deck.testContext.authorizationStates.not_evaluated);
});
