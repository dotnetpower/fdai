/** Round 12: real Console route with test-only identity and intercepted API evidence.
 * This is not Browser Entra, provider, notification, or deployed runtime validation.
 */
import { expect, test, type Page } from "@playwright/test";
import reportFixture from "../../src/routes/alert-quality.backend.fixture.json" with { type: "json" };
import settingsFixture from "../../src/routes/alert-quality.settings.fixture.json" with { type: "json" };
import en from "../../src/routes/i18n/alert-quality.en.json" with { type: "json" };
import ko from "../../src/routes/i18n/alert-quality.ko.json" with { type: "json" };

const scope = settingsFixture.scope_ref;
const subject = "example-operator";
const now = "2026-09-14T10:05:00Z";
type Write = { path: string; body: Record<string, unknown>; key?: string | undefined };

async function fixture(page: Page, options: {
  locale?: "en" | "ko"; anonymous?: boolean; missing?: boolean;
  expired?: boolean; ambiguous?: boolean; settingsConflict?: boolean;
  scopeGate?: Promise<void>;
} = {}) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.clock.setFixedTime(new Date(now));
  const writes: Write[] = [];
  const reads: string[] = [];
  const report = structuredClone(reportFixture);
  const settings = structuredClone(settingsFixture);
  report.assessment.findings.push({ ...report.assessment.findings[0]!, reason: "flapping", guidance: "review-evaluation" });
  if (options.expired) report.assessment.valid_until = "2026-09-14T10:04:00Z";
  // Replace only the test browser's module response. Production authentication is unchanged.
  if (!options.anonymous) await page.route("**/src/auth.ts*", (route) => route.fulfill({
    contentType: "application/javascript",
    body: `export async function initAuth() { return {
      devMode: false, interactiveSignIn: false,
      account: { homeAccountId: "${subject}", localAccountId: "${subject}",
        username: "operator@example.com", idTokenClaims: { roles: ["Owner"] } },
      getAuthorizationHeader: async () => "Bearer test-only",
      signIn: async () => {}, signOut: async () => {}
    }; }`,
  }));
  await page.route(/\/(?:api\/|alert-quality(?:[/?]|$)|iam(?:[/?]|$)|system\/)/, async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") return route.continue();
    const path = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (request.method() === "GET") reads.push(path);
    if (path === "/system/data-sources") return route.fulfill({ json: {
      surface: "read-data-sources", sources: [{ key: "operational-state", source: "postgresql",
        routes: ["/alert-quality"], availability: "available", configured: true, reachable: true,
        authoritative: true, durable: true, synthetic: false, reason: null, last_observed_at: now }],
    } });
    if (path === "/iam") return route.fulfill({ json: {
      principal: { oid: subject, roles: ["Owner"], capabilities: ["view-console"] }, roles: [],
      assignment_boundary: "identity-provider-group",
      access_authority: { source: "server-verified", is_owner: true, can_manage_group_membership: false },
    } });
    if (path === "/iam/self") return route.fulfill({ json: {
      principal: { subject_id: subject, username: "operator@example.com", roles: ["Owner"] },
      request: null, can_access_console: true,
    } });
    if (path === "/alert-quality/scopes") {
      await options.scopeGate;
      return route.fulfill({ json: {
        source: "alert-noise-governance", scope_refs: [scope], execution_authority: false,
      } });
    }
    if (path === "/alert-quality/settings") {
      if (request.method() === "PUT") {
        const body = request.postDataJSON() as Record<string, unknown>;
        writes.push({ path, body });
        if (options.settingsConflict) return route.fulfill({ status: 409, json: { detail: "conflict" } });
        Object.assign(settings, { enabled: body.enabled, revision: 1, preference_state: "recorded", recorded_at: now });
      }
      return route.fulfill({ json: settings });
    }
    if (path === "/alert-quality/assess" || path === "/alert-quality/proposals") {
      writes.push({ path, body: request.postDataJSON(), key: request.headers()["idempotency-key"] });
      if (options.ambiguous) return route.abort();
      return route.fulfill({ status: 202, json: { ...report, unavailable_reason: "proposal_pending" } });
    }
    if (path === "/alert-quality") return route.fulfill({ json: options.missing
      ? { ...report, assessment: null, plans: [], unavailable_reason: "assessment_missing" } : report });
    return route.fulfill({ status: 503, json: { detail: "test-only unavailable source" } });
  });
  await page.goto(`/alert-quality?scope_ref=${encodeURIComponent(scope)}&locale=${options.locale ?? "en"}`);
  return { writes, reads };
}

async function geometry(page: Page) {
  for (const selector of ["html", "main"]) {
    const measured = await page.locator(selector).evaluate((element) => ({
      width: element.clientWidth, scroll: element.scrollWidth,
    }));
    expect(measured.scroll).toBeLessThanOrEqual(measured.width);
  }
  // The pre-existing inline title breadcrumb is not a standalone form target.
  const undersized = await page.locator("main button:not(.page-header-domain-trigger), main select, main input[type=text]").evaluateAll((elements) =>
    elements.filter((element) => element.getClientRects().length > 0)
      .filter((element) => element.getBoundingClientRect().height < 44)
      .map((element) => ({ tag: element.tagName, text: element.textContent, height: element.getBoundingClientRect().height })));
  expect(undersized).toEqual([]);
}

test.describe.configure({ mode: "serial" });

test("desktop completes routing and revision-bound preference", async ({ page }, info) => {
  const { writes } = await fixture(page);
  const main = page.locator("main");
  await expect(main.getByRole("heading", { name: en.title, exact: true })).toBeVisible();
  await expect(main.getByRole("button", { name: en.assess, exact: true })).toBeEnabled();
  await expect(main.getByText(en.notMeasured, { exact: true }).first()).toBeVisible();
  const form = main.getByRole("form", { name: en.proposal, exact: true });
  await form.locator("select[name=target_ref]").selectOption("rule:example_1");
  await form.getByLabel(en.removeGroup, { exact: true }).fill("group:source");
  await form.getByLabel(en.replacementGroup, { exact: true }).fill("group:replacement");
  const submit = form.getByRole("button", { name: en.submitProposal });
  await submit.focus();
  await expect(submit).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(main.getByText(en["command.submitted"], { exact: true })).toBeVisible();
  expect(writes).toHaveLength(1);
  expect(writes[0]!.key).toBeTruthy();
  expect(writes[0]!.body.treatment).toEqual({ kind: "routing", target_ref: "rule:example_1",
    remove_group_ref: "group:source", replacement_group_ref: "group:replacement" });
  await geometry(page);
  await page.screenshot({ path: info.outputPath("alert-quality-en-desktop.png"), fullPage: true });
  await main.locator("#alert-quality-enabled").selectOption("false");
  await main.getByRole("button", { name: en["settings.save"], exact: true }).click();
  await expect(main.getByText(en["settings.command.saved"], { exact: true })).toBeVisible();
  await expect(main.getByRole("button", { name: en.assess, exact: true })).toBeDisabled();
  expect(writes[1]!.body).toEqual({ scope_ref: scope, enabled: false, expected_revision: 0 });
});

test("desktop completes only the finite suppression axis", async ({ page }) => {
  const { writes } = await fixture(page);
  const main = page.locator("main");
  await expect(main.getByRole("button", { name: en.assess, exact: true })).toBeEnabled();
  const form = main.getByRole("form", { name: en.proposal, exact: true });
  await form.locator("select[name=treatment_kind]").selectOption("suppression");
  await form.locator("select[name=target_ref]").selectOption("rule:example_1");
  await form.getByLabel(en.processingRule, { exact: true }).fill("processing:example");
  await form.locator("input[name=preprovisioned]").check();
  await form.getByLabel(en.starts, { exact: true }).fill("2026-09-14T11:00:00Z");
  await form.getByLabel(en.ends, { exact: true }).fill("2026-09-14T11:30:00Z");
  await form.getByRole("button", { name: en.submitProposal }).click();
  await expect.poll(() => writes.length).toBe(1);
  await expect(main.getByText(en["command.submitted"], { exact: true })).toBeVisible();
  expect(writes[0]!.body.treatment).toEqual({ kind: "suppression", target_ref: "rule:example_1",
    processing_rule_ref: "processing:example", starts_at: "2026-09-14T11:00:00Z", ends_at: "2026-09-14T11:30:00Z" });
  await geometry(page);
});

test("desktop completes only the threshold evaluation axis", async ({ page }) => {
  const { writes } = await fixture(page);
  const main = page.locator("main");
  await expect(main.getByRole("button", { name: en.assess, exact: true })).toBeEnabled();
  const form = main.getByRole("form", { name: en.proposal, exact: true });
  await form.locator("select[name=treatment_kind]").selectOption("evaluation");
  await form.locator("select[name=target_ref]").selectOption("rule:example_1");
  await form.getByLabel(en.metric, { exact: true }).fill("metric:cpu");
  await form.getByRole("combobox", { name: en.operator, exact: true }).selectOption("above");
  await form.getByRole("combobox", { name: en.aggregation, exact: true }).selectOption("average");
  await form.getByLabel(en.threshold, { exact: true }).fill("80");
  await form.getByLabel(en.window, { exact: true }).fill("300");
  await form.getByLabel(en.frequency, { exact: true }).fill("60");
  await form.getByLabel(en.proposedValue, { exact: true }).fill("90");
  await form.getByRole("button", { name: en.submitProposal }).click();
  await expect.poll(() => writes.length).toBe(1);
  await expect(main.getByText(en["command.submitted"], { exact: true })).toBeVisible();
  expect(writes[0]!.body.treatment).toEqual({ kind: "evaluation", target_ref: "rule:example_1",
    evaluation: { metric_ref: "metric:cpu", operator: "above", aggregation: "average", threshold: 90,
      window_seconds: 300, frequency_seconds: 60 } });
  await geometry(page);
});

test("Korean expanded evidence fits desktop then constrained and mobile", async ({ page }, info) => {
  await fixture(page, { locale: "ko" });
  await expect(page.locator("main").getByRole("button", { name: ko.assess, exact: true })).toBeEnabled();
  const summaries = page.locator("main details > summary");
  for (const summary of await summaries.all()) await summary.click();
  for (const viewport of [{ width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await geometry(page);
    await page.locator("main").evaluate((element) => { element.scrollTop = 0; });
    await page.screenshot({ path: info.outputPath(`alert-quality-ko-${viewport.width}.png`), fullPage: true });
  }
});

test("scope loading starts with an accessible reduced-motion skeleton", async ({ page }) => {
  let ready!: () => void;
  const scopeGate = new Promise<void>((resolve) => { ready = resolve; });
  await page.emulateMedia({ reducedMotion: "reduce" });
  try {
    await fixture(page, { scopeGate });
    const skeleton = page.locator("main .loading-skeleton");
    await expect(skeleton).toHaveAttribute("aria-busy", "true");
    await expect(skeleton.locator("[aria-hidden=true]")).toBeVisible();
    const animations = await skeleton.locator(".skeleton-shimmer").evaluateAll((elements) =>
      elements.map((element) => getComputedStyle(element).animationName));
    expect(animations.every((name) => name === "none")).toBe(true);
  } finally { ready(); }
  await expect(page.getByRole("button", { name: en.assess, exact: true })).toBeEnabled();
});

for (const state of ["missing", "expired"] as const) {
  test(`${state} reports permit only a new assessment`, async ({ page }) => {
    await fixture(page, { [state]: true });
    await expect(page.getByRole("button", { name: en.assess, exact: true })).toBeEnabled();
    await expect(page.getByRole("button", { name: en.submitProposal })).toBeDisabled();
  });
}

test("ambiguous writes remain held after an explicit refresh", async ({ page }) => {
  const { writes } = await fixture(page, { ambiguous: true });
  await page.getByRole("button", { name: en.assess, exact: true }).click();
  await expect(page.getByText(en["command.unknown"], { exact: true })).toBeVisible();
  await page.getByRole("button", { name: en.refresh, exact: true }).click();
  await expect(page.getByRole("button", { name: en.assess, exact: true })).toBeDisabled();
  expect(writes).toHaveLength(1);
});

test("Settings conflict requires refresh and never retries PUT", async ({ page }) => {
  const { writes } = await fixture(page, { settingsConflict: true });
  await page.locator("#alert-quality-enabled").selectOption("false");
  await page.getByRole("button", { name: en["settings.save"], exact: true }).click();
  await expect(page.getByText(en["settings.command.conflict"], { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: en["settings.save"], exact: true })).toBeDisabled();
  expect(writes).toHaveLength(1);
});

test("anonymous development mode never acquires alert evidence", async ({ page }) => {
  const { reads, writes } = await fixture(page, { anonymous: true });
  await expect(page.getByText(en.signInRequired, { exact: true })).toBeVisible();
  expect(reads.filter((path) => path.startsWith("/alert-quality"))).toEqual([]);
  expect(writes).toEqual([]);
});
