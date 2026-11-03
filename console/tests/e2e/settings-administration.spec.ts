import { readFileSync } from "node:fs";
import { expect, test, type Locator, type Page, type Route } from "@playwright/test";

type IamLabels = Record<"filterRoster" | "clearFilters" | "requestStatusFilter" | "requestSearch" | "requestDetails", string>;
type IntegrationLabels = Record<"bindingRefresh" | "emailRecipientCustomLabel" | "ocrRetry" | "emailPlain" | "emailHtml", string>;
type DiagnosticLabels = Record<"refreshAll" | "copySummary" | "retryLiveness" | "retryReadPath" | "refreshPolicy", string>;

function readCatalog<T>(name: string): T {
  return JSON.parse(readFileSync(
    new URL(`../../src/routes/i18n/${name}`, import.meta.url), "utf8",
  )) as T;
}

const iamEn = readCatalog<IamLabels>("settings-iam.en.json");
const iamKo = readCatalog<IamLabels>("settings-iam.ko.json");
const integrationsEn = readCatalog<IntegrationLabels>("settings-integrations.en.json");
const integrationsKo = readCatalog<IntegrationLabels>("settings-integrations.ko.json");
const diagnosticsEn = readCatalog<DiagnosticLabels>("settings-diagnostics.en.json");
const diagnosticsKo = readCatalog<DiagnosticLabels>("settings-diagnostics.ko.json");

const observedAt = "2026-11-01T08:00:00Z";
const overview = {
  principal: { oid: "owner-1", roles: ["Owner"], capabilities: ["view-console"] },
  roles: [
    { value: "Reader", capabilities: ["view-console"], routine_assignment: true },
    { value: "Owner", capabilities: ["view-console", "manage-group-membership"], routine_assignment: true },
  ],
  assignment_boundary: "identity-provider-group",
  access_authority: { source: "server-verified", is_owner: true, can_manage_group_membership: true },
  directory: { source: "intercepted-directory", availability: "available", observed_at: observedAt, detail: null },
  workflow: { access_request_authority: "proposal_only", assignment_authority: "observation_only", provider_mutation: "promotion_required" },
};
const roster = [
  { provider: "entra", subject_id: "analyst-1", display_name: "Example Analyst", username: "analyst@example.com", principal_type: "person", roles: ["Reader"], active: true },
  { provider: "entra", subject_id: "operator-1", display_name: "Example Operator", username: "operator@example.com", principal_type: "person", roles: ["Contributor"], active: true },
  { provider: "entra", subject_id: "group-1", display_name: "Example Readers", username: null, principal_type: "group", roles: ["Reader"], active: true },
];
const requestBase = {
  idempotency_key: "synthetic-intent", requester_oid: "another-owner", identity_provider: "entra",
  target_subject_id: "analyst-1", target_username: "analyst@example.com", operation: "grant",
  role: "Owner", justification: "Synthetic request for a reviewed operational responsibility.",
  requested_at: observedAt, status: "pending", reviewed_by: null, reviewed_at: null, review_justification: null,
};
const accessRequests = [
  { ...requestBase, request_id: "request-owner" },
  { ...requestBase, request_id: "request-revoke", operation: "revoke", role: "Reader", status: "approved", reviewed_by: "reviewer-1", reviewed_at: observedAt, review_justification: "Reviewed; provider effect remains unverified." },
  { ...requestBase, request_id: "request-rejected", target_subject_id: "operator-1", target_username: "operator@example.com", role: "Approver", status: "rejected", reviewed_by: "reviewer-1", reviewed_at: observedAt },
];
const runtimeSettings = {
  revision: 1, can_manage: true, updated_at: observedAt, updated_by: "owner-1",
  integrations: [
    { key: "teams-a2-operational-alert", source: "core-control-plane", observed: true, configured: false, ready: false, mode: "disabled", reason: "Synthetic setup fixture; delivery remains disabled." },
    { key: "email", source: "operator-service", observed: true, configured: false, ready: false, mode: "disabled", reason: "Synthetic preview only." },
  ],
  runtime: {
    environment: "dev", state_store_durable: true, autonomy_default: "shadow",
    pantheon_enabled: true, workflow_observation_enabled: true,
    primary_transport_configured: false, auxiliary_transport_configured: false, case_history_configured: false,
  },
  settings: [],
};
const kpi = {
  event_count: 2, shadow_share: 1, enforce_share: 0, hil_pending: 0,
  by_action_kind: { evaluate: 2 }, by_outcome: { success: 2 }, by_tier: { T0: 2 },
  last_recorded_at: observedAt, audit_sample: null,
};
const plainText = "Synthetic incident preview. No recovery action has run.";
const template = {
  key: "incident-opened", subject: "Synthetic incident preview", plain_text: plainText,
  html: "<!doctype html><html lang=\"en\"><body><h1>Synthetic incident preview</h1><p>No recovery action has run.</p></body></html>",
};

type CapturedRequest = { method: string; path: string; body: Record<string, unknown> | null; query: URLSearchParams };
type Handler = (route: Route, request: CapturedRequest, attempt: number) => Promise<void>;
const releases: (() => void)[] = [];

function gate() {
  let release!: () => void;
  const wait = new Promise<void>((resolve) => { release = resolve; });
  releases.push(release);
  return { wait, release };
}
async function json(route: Route, payload: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
}
async function installApi(page: Page, handlers: Readonly<Record<string, Handler>> = {}) {
  const requests: CapturedRequest[] = [];
  const blockedExternal: string[] = [];
  const defaults: Readonly<Record<string, unknown>> = {
    "/iam": overview,
    "/iam/self": { principal: { subject_id: "owner-1", username: null, roles: ["Owner"] }, request: null, can_access_console: true },
    "/iam/access-requests": { items: accessRequests, total: accessRequests.length, next_cursor: null },
    "/iam/directory/roster": { items: roster },
    "/runtime/settings": runtimeSettings,
    "/notification-templates/incident-opened": template,
    "/healthz": { status: "ok" },
    "/kpi": kpi,
  };
  // Only local documents/assets pass through. Every API request is intercepted, including writes.
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (!["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)) {
      blockedExternal.push(url.origin);
      await route.abort("blockedbyclient");
      return;
    }
    const method = request.method();
    const path = url.pathname.replace(/^\/api(?=\/)/, "");
    const read = method === "GET" || method === "HEAD";
    if (read && !url.pathname.startsWith("/api/") && !["fetch", "xhr"].includes(request.resourceType())) {
      await route.continue();
      return;
    }
    const captured: CapturedRequest = {
      method, path, body: read ? null : request.postDataJSON() as Record<string, unknown>,
      query: url.searchParams,
    };
    requests.push(captured);
    const attempt = requests.filter((item) => item.path === path && item.method === method).length;
    if (handlers[path]) return handlers[path]!(route, captured, attempt);
    if (read && path in defaults) return json(route, defaults[path]);
    return json(route, { detail: "Optional intercepted source unavailable; no live fallback." }, read ? 404 : 409);
  });
  return {
    requests, blockedExternal,
    count: (path: string, method = "GET") => requests.filter((item) => item.path === path && item.method === method).length,
    writes: () => requests.filter((item) => !["GET", "HEAD"].includes(item.method)),
  };
}
async function interceptClipboard(page: Page) {
  const copied: string[] = [];
  await page.exposeFunction("captureAdministrationSummary", (text: string) => { copied.push(text); });
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: (text: string) => (window as unknown as {
          captureAdministrationSummary: (value: string) => Promise<void>;
        }).captureAdministrationSummary(text),
      },
    });
  });
  return copied;
}

async function expectContainedControl(page: Page, control: Locator) {
  await control.scrollIntoViewIfNeeded();
  await expect(control).toBeVisible();
  await expect(control).toBeInViewport();
  const box = await control.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
}

async function expectAdministrationContainment(page: Page) {
  await page.evaluate(() => document.fonts.ready.then(() => undefined));
  const geometry = await page.locator("html, .settings-overlay, .settings-overlay .settings-route")
    .evaluateAll((elements) => elements.map((element) => ({
      name: element.className || element.tagName,
      width: element.clientWidth,
      scrollWidth: element.scrollWidth,
    })));
  expect(geometry.length).toBeGreaterThanOrEqual(3);
  for (const item of geometry) {
    expect(item.width, item.name).toBeGreaterThan(0);
    expect(item.scrollWidth, item.name).toBeLessThanOrEqual(item.width);
  }
}

test.describe("Production Settings administration desktop", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "This file declares desktop coverage only.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
  });

  test("responsive administration read-only controls remain contained in EN/KO after desktop acceptance", async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Explicit viewports are exercised sequentially in one isolated context.");
    await page.emulateMedia({ reducedMotion: "reduce" });
    const api = await installApi(page, {
      "/runtime/integrations/teams-workflow/binding": async (route, request) => {
        expect(request.method).toBe("GET");
        expect(request.query.has("reveal")).toBe(false);
        return json(route, {
          visible: true, configured: true, binding_version: "binding-responsive-1",
          endpoint_identifier: "synthetic-responsive-binding", observed_at: observedAt, saved_at: observedAt,
          delivery_targets: ["email"], email_recipient_mode: "custom", custom_email: "recipient@example.com",
          channels: [{
            channel_id: "responsive-channel", label: "Example notification channel", enabled: true,
            binding_version: "binding-responsive-1", endpoint_identifier: "synthetic-responsive-channel", saved_at: observedAt,
          }],
        });
      },
      "/models/settings": async (route, request) => {
        expect(request.method).toBe("GET");
        expect(request.query.get("view")).toBe("summary");
        expect(request.query.has("refresh_catalog")).toBe(false);
        return json(route, { detail: "Synthetic OCR metadata unavailable; no catalog discovery." }, 404);
      },
    });
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      for (const locale of ["en", "ko"] as const) {
        const iam = locale === "ko" ? iamKo : iamEn;
        const integrations = locale === "ko" ? integrationsKo : integrationsEn;
        const diagnostics = locale === "ko" ? diagnosticsKo : diagnosticsEn;
        await test.step(`${viewport.width}x${viewport.height} ${locale}: IAM local filters and request details`, async () => {
          await page.goto(`/settings/iam/users?locale=${locale}`);
          const users = page.locator(".settings-users-panel");
          const search = users.getByRole("searchbox", { name: iam.filterRoster, exact: true });
          await expectContainedControl(page, search);
          const reads = api.count("/iam/directory/roster");
          await search.fill("ANALYST");
          await expect(users.locator("tbody tr")).toHaveCount(1);
          const clear = users.getByRole("button", { name: iam.clearFilters, exact: true });
          await expectContainedControl(page, clear);
          await clear.click();
          await expect(search).toHaveValue("");
          await expect(search).toBeFocused();
          expect(api.count("/iam/directory/roster")).toBe(reads);
          await expectAdministrationContainment(page);

          await page.goto(`/settings/iam/requests?locale=${locale}`);
          const requests = page.locator(".settings-requests-panel");
          await expectContainedControl(page, requests.getByRole("combobox", { name: new RegExp(iam.requestStatusFilter) }));
          await expectContainedControl(page, requests.getByRole("searchbox", { name: iam.requestSearch, exact: true }));
          const details = requests.getByText(iam.requestDetails, { exact: true }).first();
          await expectContainedControl(page, details);
          await details.press("Enter");
          await expect(requests.locator("details[open]").getByText(requestBase.justification, { exact: true })).toBeVisible();
          await expectAdministrationContainment(page);
        });
        await test.step(`${viewport.width}x${viewport.height} ${locale}: integration metadata and safe preview`, async () => {
          await page.goto(`/settings/integrations?locale=${locale}`);
          const teams = page.locator(".settings-teams-workflow-setup");
          await expectContainedControl(page, teams.getByRole("button", { name: integrations.bindingRefresh, exact: true }));
          const recipient = teams.getByRole("textbox", { name: integrations.emailRecipientCustomLabel, exact: true });
          await expect(recipient).toHaveValue("recipient@example.com");
          await expectContainedControl(page, recipient);
          const ocr = page.locator(".document-ocr-settings");
          await expectContainedControl(page, ocr.getByRole("button", { name: integrations.ocrRetry, exact: true }));
          const preview = page.locator(".settings-email-template");
          const plain = preview.getByRole("button", { name: integrations.emailPlain, exact: true });
          await expectContainedControl(page, plain);
          await plain.click();
          await expect(preview.locator("pre")).toHaveText(plainText);
          await expect(preview.locator("iframe")).toHaveCount(0);
          await expectAdministrationContainment(page);
          const html = preview.getByRole("button", { name: integrations.emailHtml, exact: true });
          await expectContainedControl(page, html);
          await html.click();
          await expect(preview.locator("iframe")).toHaveAttribute("sandbox", "");
          await expect(preview.locator("iframe")).toHaveAttribute("referrerpolicy", "no-referrer");
          await expectAdministrationContainment(page);
        });
        await test.step(`${viewport.width}x${viewport.height} ${locale}: diagnostic read-only controls`, async () => {
          await page.goto(`/settings/diagnostics?locale=${locale}`);
          const route = page.locator(".settings-route");
          for (const label of [
            diagnostics.refreshAll, diagnostics.copySummary, diagnostics.retryLiveness,
            diagnostics.retryReadPath, diagnostics.refreshPolicy,
          ]) {
            await expectContainedControl(page, route.getByRole("button", { name: label, exact: true }));
          }
          await expect(route.locator(".settings-diagnostic-result")).toHaveCount(2);
          await expect(route.locator(".settings-diagnostic-result[aria-busy='true']")).toHaveCount(0);
          await expectAdministrationContainment(page);
        });
        expect(api.writes()).toEqual([]);
      }
    }
    const modelReads = api.requests.filter((request) => request.path === "/models/settings");
    expect(modelReads.length).toBeGreaterThan(0);
    expect(modelReads.every((request) => request.query.get("view") === "summary" && !request.query.has("refresh_catalog"))).toBe(true);
    expect(api.writes()).toEqual([]);
    expect(api.blockedExternal).toEqual([]);
  });
  test.afterEach(() => { releases.splice(0).forEach((release) => release()); });

  test("IAM keeps the roster usable during a failed request read and filters only local records", async ({ page }) => {
    const pending = gate();
    let requestsAvailable = false;
    const api = await installApi(page, {
      "/iam/access-requests": async (route) => {
        if (!requestsAvailable) {
          await pending.wait;
          return json(route, { detail: "Synthetic request projection unavailable." }, 503);
        }
        return json(route, { items: accessRequests, total: accessRequests.length, next_cursor: null });
      },
    });
    await page.goto("/settings/iam/users?locale=en");
    const users = page.locator(".settings-users-panel");
    const analyst = users.getByRole("row").filter({ hasText: "Example Analyst" });
    await expect(analyst).toBeVisible();
    await expect(analyst.getByRole("cell").nth(2)).toHaveText("Reader");
    expect(api.count("/iam/access-requests")).toBe(1);

    const search = users.getByRole("searchbox", { name: "Filter the displayed roster by name, email or subject ID" });
    await search.fill("ANALYST");
    await expect(users.locator("tbody tr")).toHaveCount(1);
    await users.locator(".settings-roster-toolbar").getByRole("button", { name: "Groups", exact: true }).click();
    await expect(users.getByText("Example Analyst", { exact: true })).toHaveCount(0);
    await users.getByRole("button", { name: "Clear filters", exact: true }).click();
    await expect(search).toHaveValue("");
    await expect(search).toBeFocused();
    await expect(users.getByText("Example Operator", { exact: true })).toBeVisible();
    expect(api.count("/iam")).toBe(1);
    expect(api.count("/iam/directory/roster")).toBe(1);
    expect(api.requests.filter((item) => item.path.startsWith("/iam/") &&
      !["/iam/self", "/iam/access-requests", "/iam/directory/roster"].includes(item.path))).toEqual([]);

    pending.release();
    await page.getByRole("tab", { name: "Access requests", exact: true }).click();
    const panel = page.getByRole("tabpanel");
    await expect(panel.getByText("Access requests are unavailable. This is not an empty request list.")).toBeVisible();
    await expect(panel.locator(".settings-requests-panel")).toHaveCount(0);
    // Tab URLs remount the route; recovery is explicit rather than tied to an HTTP attempt number.
    const readsBeforeRetry = {
      requests: api.count("/iam/access-requests"),
      overview: api.count("/iam"),
      roster: api.count("/iam/directory/roster"),
    };
    requestsAvailable = true;
    await panel.getByRole("button", { name: "Retry", exact: true }).click();
    const requests = panel.locator(".settings-requests-panel");
    await expect(requests.locator("tbody tr")).toHaveCount(3);
    await requests.getByRole("combobox", { name: /Request status/ }).selectOption("pending");
    await requests.getByRole("searchbox", { name: "Search loaded requests by person or request ID" }).fill("analyst");
    await expect(requests.locator("tbody tr")).toHaveCount(1);
    await expect(requests.getByText("Owner", { exact: true })).toBeVisible();
    await expect(requests.getByText(/Filters cover loaded records only\./)).toBeVisible();
    await requests.getByRole("button", { name: "Clear filters", exact: true }).click();
    const approved = requests.getByRole("row").filter({ hasText: "Approved - effect not verified" });
    await expect(approved).toHaveCount(1);
    await approved.getByText("Inspect request details", { exact: true }).click();
    await expect(approved.getByText("Reviewed; provider effect remains unverified.", { exact: true })).toBeVisible();
    await expect(approved.getByText(requestBase.justification, { exact: true })).toBeVisible();
    expect(api.count("/iam/access-requests")).toBe(readsBeforeRetry.requests + 1);
    expect(api.count("/iam")).toBe(readsBeforeRetry.overview);
    expect(api.count("/iam/directory/roster")).toBe(readsBeforeRetry.roster);
    expect(api.writes()).toEqual([]);
    expect(api.blockedExternal).toEqual([]);
  });

  test("IAM request records do not become observed roles when the directory read fails", async ({ page }) => {
    const pending = gate();
    let rosterAvailable = false;
    const api = await installApi(page, {
      "/iam/directory/roster": async (route) => {
        if (!rosterAvailable) {
          await pending.wait;
          return json(route, { detail: "Synthetic directory unavailable." }, 503);
        }
        return json(route, { items: roster });
      },
    });
    await page.goto("/settings/iam/requests?locale=en");
    await expect(page.locator(".settings-requests-panel tbody tr")).toHaveCount(3);
    pending.release();
    await page.getByRole("tab", { name: "Users", exact: true }).click();
    const users = page.locator(".settings-users-panel");
    await expect(users.getByText(/Requests do not prove current roles or identity activity\./)).toBeVisible();
    await expect(users.getByText("Example Analyst", { exact: true })).toHaveCount(0);
    await expect(users.locator("tbody tr")).toHaveCount(1);
    const readsBeforeRetry = {
      requests: api.count("/iam/access-requests"),
      overview: api.count("/iam"),
      roster: api.count("/iam/directory/roster"),
    };
    rosterAvailable = true;
    await users.getByRole("button", { name: "Retry", exact: true }).click();
    const analyst = users.getByRole("row").filter({ hasText: "Example Analyst" });
    await expect(analyst.getByRole("cell").nth(2)).toHaveText("Reader");
    expect(api.count("/iam")).toBe(readsBeforeRetry.overview);
    expect(api.count("/iam/access-requests")).toBe(readsBeforeRetry.requests);
    expect(api.count("/iam/directory/roster")).toBe(readsBeforeRetry.roster + 1);
    expect(api.writes()).toEqual([]);
  });

  test("Integrations confirms the first custom recipient, serializes pending preferences and keeps previews bounded", async ({ page }) => {
    const pending = gate();
    let binding: Record<string, unknown> | null = null;
    const api = await installApi(page, {
      "/runtime/integrations/teams-workflow/binding": async (route, request) => {
        expect(request.query.has("reveal")).toBe(false);
        return json(route, binding ?? { visible: true, configured: false });
      },
      "/runtime/integrations/teams-workflow/test": async (route, request) => {
        expect(request.method).toBe("POST");
        const body = request.body!;
        if (body.selection_only === true) {
          await pending.wait;
          return json(route, { detail: "Synthetic preference save rejected; no configuration changed." }, 503);
        }
        expect(binding).toBeNull();
        binding = {
          visible: true, configured: true, binding_version: "binding-1",
          endpoint_identifier: "synthetic-binding", observed_at: observedAt, saved_at: observedAt,
          delivery_targets: body.delivery_targets, email_recipient_mode: body.email_recipient_mode,
          custom_email: body.custom_email,
          channels: [{
            channel_id: "channel-1", label: "Example notification channel", enabled: true,
            binding_version: "binding-1", endpoint_identifier: "synthetic-channel", saved_at: observedAt,
          }],
        };
        return json(route, {
          request_id: body.request_id, saved: true, binding_version: "binding-1", saved_at: observedAt,
          accepted: true, provider_status: 202, workflow_run_id: null, tested_at: observedAt,
        });
      },
    });
    await page.goto("/settings/integrations?locale=en");
    const teams = page.locator(".settings-teams-workflow-setup");
    await teams.getByRole("radio", { name: "Use separate email address", exact: true }).check();
    await teams.getByRole("textbox", { name: "Separate recipient email", exact: true }).fill("recipient@example.com");
    await expect(teams.getByRole("button", { name: "Save email", exact: true })).toBeDisabled();
    await teams.getByRole("checkbox", { name: /Email delivery channel/ }).check();
    const urlInput = teams.getByLabel("Teams Workflows HTTP URL", { exact: true });
    await urlInput.fill("https://example.com/synthetic-workflow");
    await teams.getByRole("button", { name: "Save and send test", exact: true }).click();
    await expect(teams.getByText("Saved and test accepted", { exact: true })).toBeVisible();
    expect(api.writes()).toHaveLength(1);
    expect(api.writes()[0]!.body).toMatchObject({
      email_recipient_mode: "custom", custom_email: "recipient@example.com",
      delivery_targets: expect.arrayContaining(["email"]),
    });
    await expect(urlInput).not.toHaveValue("https://example.com/synthetic-workflow");
    const digest = teams.getByRole("checkbox", { name: /A4 scheduled digest channel/ });
    await digest.uncheck();
    await expect(teams.getByText("Saving and confirming channel preferences...", { exact: true })).toBeVisible();
    await expect(digest).toBeDisabled();
    await expect(teams.getByRole("checkbox", { name: /Email delivery channel/ })).toBeDisabled();
    await expect(teams.getByRole("button", { name: "Save email", exact: true })).toBeDisabled();
    await expect(teams.getByRole("button", { name: "Test saved binding", exact: true })).toBeDisabled();
    expect(api.writes()).toHaveLength(2);
    expect(api.writes()[1]!.body).toMatchObject({ selection_only: true, webhook_url: "" });
    pending.release();
    await expect(teams.getByText(/The last confirmed selection has been restored/)).toBeVisible();
    await expect(digest).toBeChecked();
    await teams.getByRole("button", { name: "Refresh saved metadata", exact: true }).click();
    await expect(teams.getByRole("textbox", { name: "Separate recipient email", exact: true })).toHaveValue("recipient@example.com");
    expect(api.writes()).toHaveLength(2);

    const preview = page.locator(".settings-email-template");
    await expect(preview.locator("iframe")).toHaveAttribute("sandbox", "");
    await expect(preview.locator("iframe")).toHaveAttribute("referrerpolicy", "no-referrer");
    await expect(page.frameLocator(".settings-email-template-frame").getByRole("heading", { name: "Synthetic incident preview" })).toBeVisible();
    await preview.getByRole("button", { name: "Plain-text preview", exact: true }).click();
    await expect(preview.locator("pre")).toHaveText(plainText);
    await expect(preview.locator("iframe")).toHaveCount(0);
    await preview.getByRole("button", { name: "HTML preview", exact: true }).click();
    await expect(preview.locator("iframe")).toHaveAttribute("sandbox", "");
    expect(api.writes().every((request) => request.path === "/runtime/integrations/teams-workflow/test")).toBe(true);
    expect(api.blockedExternal).toEqual([]);
  });

  test("Diagnostics isolates slow and failed probes, scoped recovery, observation times and allowlisted copying", async ({ page }) => {
    const slowKpi = gate();
    const slowHealth = gate();
    const copied = await interceptClipboard(page);
    const earliest = Date.now();
    const api = await installApi(page, {
      "/kpi": async (route, _request, attempt) => {
        if (attempt === 1) {
          await slowKpi.wait;
          return json(route, { detail: "Synthetic failure: hidden-diagnostic@example.com" }, 503);
        }
        return json(route, kpi);
      },
      "/healthz": async (route, _request, attempt) => {
        if (attempt === 2) {
          await slowHealth.wait;
          return json(route, { status: "degraded" });
        }
        return json(route, { status: "ok" });
      },
      "/runtime/settings": async (route, _request, attempt) => attempt === 1
        ? json(route, { detail: "Synthetic policy read unavailable." }, 503)
        : json(route, runtimeSettings),
    });
    await page.goto("/settings/diagnostics?locale=en");
    const diagnostics = page.locator(".settings-route");
    const health = diagnostics.locator(".settings-diagnostic-result").nth(0);
    const readPath = diagnostics.locator(".settings-diagnostic-result").nth(1);
    const policy = diagnostics.locator("section[aria-labelledby='settings-runtime-policy-status']");
    await expect(health.getByText("Available", { exact: true })).toBeVisible();
    await expect(health).toHaveAttribute("aria-busy", "false");
    await expect(readPath).toHaveAttribute("aria-busy", "true");
    await expect(readPath.locator(".loading-skeleton")).toBeVisible();
    await expect(readPath.getByText(/^Last checked:/)).toHaveCount(0);
    await expect(readPath.getByText(/^Read duration:/)).toHaveCount(0);
    await expect(diagnostics.getByText("1 available / 0 unavailable / 1 checking", { exact: true })).toBeVisible();
    const healthTime = await health.getByText(/^Last checked:/).textContent();
    await expect(health.getByText(/^Read duration: \d+ ms$/)).toBeVisible();
    await expect(policy.getByText(/Policy facts are unavailable/)).toBeVisible();
    await policy.getByRole("button", { name: "Refresh policy facts", exact: true }).click();
    await expect(policy.getByText("Durable", { exact: true })).toBeVisible();
    expect(api.count("/healthz")).toBe(1);
    expect(api.count("/kpi")).toBe(1);
    expect(api.count("/runtime/settings")).toBe(2);
    await diagnostics.getByRole("button", { name: "Copy safe diagnostic summary", exact: true }).click();
    await expect.poll(() => copied.length).toBe(1);
    expect(JSON.parse(copied[0]!).kpi_read_path).toBeNull();

    slowKpi.release();
    await expect(readPath.getByText("Unavailable", { exact: true })).toBeVisible();
    await expect(readPath.locator(".error")).toBeVisible();
    await expect(health.locator(".error")).toHaveCount(0);
    await expect(health.getByText(/^Last checked:/)).toHaveText(healthTime!);
    await expect(readPath.getByText(/^Last checked:/)).toBeVisible();
    await expect(readPath.getByText(/^Read duration: \d+ ms$/)).toBeVisible();
    await expect(diagnostics.getByText("hidden-diagnostic@example.com", { exact: false })).toHaveCount(0);
    await readPath.getByRole("button", { name: "Recheck KPI read access", exact: true }).click();
    await expect(diagnostics.getByText("2 available / 0 unavailable / 0 checking", { exact: true })).toBeVisible();
    expect(api.count("/healthz")).toBe(1);
    expect(api.count("/kpi")).toBe(2);
    expect(api.count("/runtime/settings")).toBe(2);

    await diagnostics.getByRole("button", { name: "Refresh all reads", exact: true }).click();
    await expect(health).toHaveAttribute("aria-busy", "true");
    await expect(readPath).toHaveAttribute("aria-busy", "false");
    await expect(diagnostics.getByText("1 available / 0 unavailable / 1 checking", { exact: true })).toBeVisible();
    expect(api.count("/healthz")).toBe(2);
    expect(api.count("/kpi")).toBe(3);
    expect(api.count("/runtime/settings")).toBe(3);
    await diagnostics.getByRole("button", { name: "Copy safe diagnostic summary", exact: true }).click();
    await expect.poll(() => copied.length).toBe(2);
    expect(JSON.parse(copied[1]!).operator_api_liveness).toBeNull();
    slowHealth.release();
    await expect(health.getByText("Unavailable", { exact: true })).toBeVisible();
    await expect(readPath.getByText("Available", { exact: true })).toBeVisible();
    await health.getByRole("button", { name: "Recheck API liveness", exact: true }).click();
    await expect(diagnostics.getByText("2 available / 0 unavailable / 0 checking", { exact: true })).toBeVisible();
    await diagnostics.getByRole("button", { name: "Copy safe diagnostic summary", exact: true }).click();
    await expect.poll(() => copied.length).toBe(3);
    const summary = JSON.parse(copied[2]!);
    expect(Object.keys(summary).sort()).toEqual([
      "operator_api_liveness", "kpi_read_path", "runtime_observed_at", "runtime_stale", "runtime",
    ].sort());
    expect(Object.keys(summary.runtime).sort()).toEqual([
      "environment", "state_store_durable", "pantheon_enabled", "workflow_observation_enabled",
      "primary_transport_configured", "auxiliary_transport_configured", "case_history_configured",
    ].sort());
    for (const result of [summary.operator_api_liveness, summary.kpi_read_path]) {
      expect(Object.keys(result).sort()).toEqual(["status", "checkedAt", "durationMs"].sort());
      expect(result.status).toBe("available");
      expect(Date.parse(result.checkedAt)).toBeGreaterThanOrEqual(earliest);
      expect(Date.parse(result.checkedAt)).toBeLessThanOrEqual(Date.now() + 1000);
      expect(Number.isInteger(result.durationMs)).toBe(true);
      expect(result.durationMs).toBeGreaterThanOrEqual(0);
    }
    expect(summary.runtime_stale).toBe(false);
    expect(copied.join("\n")).not.toMatch(/hidden-diagnostic|credential|token|webhook|username/);
    expect(api.count("/healthz")).toBe(3);
    expect(api.count("/kpi")).toBe(3);
    expect(api.count("/runtime/settings")).toBe(3);
    expect(api.writes()).toEqual([]);
    expect(api.blockedExternal).toEqual([]);
  });
});
