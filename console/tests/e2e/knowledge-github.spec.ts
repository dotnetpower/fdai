import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

function source() {
  return {
    repository_alias: "example-app", location: "example/app", revision: 1, enabled: false,
    knowledge_source: {
      credential_reference: "public", knowledge_read_enabled: true,
      observed_commit: "a".repeat(40), readme_digest: "b".repeat(64),
      observed_at: "2026-10-09T00:00:00+00:00",
    },
  };
}

async function setup(page: Page, options: { owner?: boolean; empty?: boolean; unavailable?: boolean; writeError?: boolean; locale?: string } = {}) {
  const owner = options.owner ?? true;
  const writes: { path: string; body: Record<string, unknown> }[] = [];
  let sources = options.empty ? [] : [source()];
  let unavailable = options.unavailable ?? false;
  await page.route("**/src/auth.ts*", (route) => route.fulfill({
    contentType: "application/javascript",
    body: `export async function initAuth() { return {
      devMode: false, interactiveSignIn: false,
      account: { homeAccountId: "example-operator", localAccountId: "example-operator",
        username: "operator@example.com", idTokenClaims: { roles: ["${owner ? "Owner" : "Reader"}"] } },
      getAuthorizationHeader: async () => "Bearer test-only-identity",
      signIn: async () => {}, signOut: async () => {}
    }; }`,
  }));
  await page.route(/\/(?:api\/|knowledge\/github\/sources|iam(?:[/?]|$)|system\/)/, async (route) => {
    const request = route.request();
    if (request.resourceType() === "document") return route.continue();
    const path = new URL(request.url()).pathname.replace(/^\/api/, "");
    if (path === "/iam/self") return route.fulfill({ json: {
      principal: { subject_id: "example-operator", username: "operator@example.com", roles: [owner ? "Owner" : "Reader"] },
      request: null, can_access_console: true,
    } });
    if (path === "/system/data-sources") return route.fulfill({ json: { surface: "read-data-sources", sources: [] } });
    if (path === "/knowledge/github/sources") {
      if (request.method() === "POST") {
        const body = request.postDataJSON();
        writes.push({ path, body });
        if (options.writeError) return route.fulfill({ status: 403, json: { detail: "Owner required" } });
        sources = [source()];
        if (body.action === "disconnect") sources[0]!.knowledge_source.knowledge_read_enabled = false;
        return route.fulfill({ status: 202, json: { request_id: `operator-${"c".repeat(32)}`, dispatch_status: "pending" } });
      }
      if (unavailable) return route.fulfill({ status: 503, json: { detail: "source unavailable" } });
      return route.fulfill({ json: { sources, gaps: [], complete: true, indexed: false } });
    }
    if (request.method() !== "GET") writes.push({ path, body: request.postDataJSON() });
    return route.fulfill({ status: 503, json: { detail: "test-only unavailable" } });
  });
  await page.goto(`/github?locale=${options.locale ?? "en"}`);
  return { writes, recover: () => { unavailable = false; } };
}

async function geometry(page: Page) {
  for (const selector of ["html", "main", ".knowledge-github-route"]) {
    const result = await page.locator(selector).evaluate((element) => ({
      width: element.clientWidth, scroll: element.scrollWidth,
    }));
    expect(result.scroll, `${selector}: ${JSON.stringify(result)}`).toBeLessThanOrEqual(result.width);
  }
}

test("desktop verifies provenance and scan separation before responsive checks", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { writes } = await setup(page);
  await expect(page.getByText("Read access verified", { exact: true })).toBeVisible();
  await expect(page.getByText("Scanning not authorized", { exact: true })).toBeVisible();
  await expect(page.getByText("a".repeat(40), { exact: true })).toBeVisible();
  await expect(page.getByText("b".repeat(64), { exact: true })).toBeVisible();
  expect(writes).toEqual([]);
  await page.getByLabel("Repository alias", { exact: true }).focus();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("GitHub owner/repository", { exact: true })).toBeFocused();
  await geometry(page);
  await page.screenshot({ path: info.outputPath("knowledge-github-desktop.png") });
});

test("Owner connects and disconnects with manual applied-state refresh and no scan request", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { writes } = await setup(page, { empty: true });
  await expect(page.getByText("No repository sources are registered.", { exact: true })).toBeVisible();
  await page.getByLabel("Repository alias", { exact: true }).fill("example-app");
  await page.getByLabel("GitHub owner/repository", { exact: true }).fill("example/app");
  await page.getByRole("button", { name: "Connect read-only source", exact: true }).click();
  await expect(page.getByText(/Connection request queued/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect read-only source", exact: true })).toBeDisabled();
  await expect(page.getByText("Read access verified", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Refresh connections", exact: true }).click();
  await expect(page.getByText("Read access verified", { exact: true })).toBeVisible();
  await expect(page.getByText("Scanning not authorized", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Disconnect knowledge access", exact: true }).click();
  await page.getByRole("button", { name: "Refresh connections", exact: true }).click();
  await expect(page.getByText("Knowledge not connected", { exact: true })).toBeVisible();
  expect(writes).toEqual([
    { path: "/knowledge/github/sources", body: { action: "connect", repository_alias: "example-app", location: "example/app", credential_reference: "public", expected_revision: 0 } },
    { path: "/knowledge/github/sources", body: { action: "disconnect", repository_alias: "example-app", expected_revision: 1 } },
  ]);
  await geometry(page);
});

test("Reader has no writes and unavailable source remains recoverable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await setup(page, { owner: false, unavailable: true });
  await expect(page.getByText(/authoritative GitHub connection ledger is unavailable/)).toBeVisible();
  fixture.recover();
  await page.getByRole("button", { name: "Refresh connections", exact: true }).click();
  await expect(page.getByText("Only an authenticated Owner can change knowledge connections.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect read-only source", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Disconnect knowledge access", exact: true })).toHaveCount(0);
  expect(fixture.writes).toEqual([]);
});

test("forbidden submission requires explicit authoritative reload", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const fixture = await setup(page, { empty: true, writeError: true });
  await page.getByLabel("Repository alias", { exact: true }).fill("example-app");
  await page.getByLabel("GitHub owner/repository", { exact: true }).fill("example/app");
  await page.getByRole("button", { name: "Connect read-only source", exact: true }).click();
  await expect(page.getByText(/Owner authority is required/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect read-only source", exact: true })).toBeDisabled();
  expect(fixture.writes).toHaveLength(1);
});

for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
  test(`English and Korean provenance stays inside ${viewport.width}px viewport`, async ({ page }) => {
    for (const locale of ["en", "ko"]) {
      await page.setViewportSize(viewport);
      await setup(page, { locale });
      await expect(page.getByText("a".repeat(40), { exact: true })).toBeVisible();
      await expect(page.getByText("b".repeat(64), { exact: true })).toBeVisible();
      await geometry(page);
    }
  });
}
