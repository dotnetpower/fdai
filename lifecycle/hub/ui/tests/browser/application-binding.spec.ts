import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { ApplicationBindingRequest, InstallationDetail } from "../../src/api";

const identifier = "installation-alpha";
const digest = "a".repeat(64);

async function openBinding(page: Page, options: {
  product?: string | null; unsupported?: boolean; blocked?: boolean;
  failure?: "conflict" | "network";
} = {}) {
  let product = options.product ?? null;
  let reads = 0;
  const writes: ApplicationBindingRequest[] = [];
  const errors: string[] = [];
  const installation: InstallationDetail = {
    installation_id: identifier, enrollment: "enrolled",
    settings: { channel: "DEV", version_range: "*", region: "region-a", allowed_regions: ["region-a"], windows: [] },
    configuration_digest: "b".repeat(64), reported_at: "2026-10-01T00:00:00Z",
    schema_revision: 0, current_release: null, health: "unknown", entities: [], suppressions: [],
    open_plan: options.blocked ? {
      plan_id: "pending-plan", sequence: 1, target_release_id: "1.0.0", expires_at: "2026-10-02T00:00:00Z",
    } : null,
    last_evaluation: null, reports: [],
  };
  page.on("pageerror", error => errors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("https://hub.test/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/auth/config") return route.fulfill({ json: { profile: "local-development" } });
    if (path === `/v1/installations/${identifier}/execution-settings`) {
      expect(request.method()).toBe("GET");
      reads += 1;
      return route.fulfill({ json: {
        settings_digest: digest, windows: [], plan_duration_minutes: 30,
        ...(options.unsupported ? {} : { product }),
      } });
    }
    if (path === `/v1/installations/${identifier}/application-binding`) {
      expect(request.method()).toBe("POST");
      const body: ApplicationBindingRequest = request.postDataJSON();
      writes.push(body);
      if (options.failure === "network") return route.abort("connectionfailed");
      if (options.failure === "conflict") return route.fulfill({
        status: 409, json: { error: "application_binding_revision_conflict" },
      });
      product = body.product;
      return route.fulfill({ json: { changed: true, settings_digest: "c".repeat(64) } });
    }
    if (!["GET", "HEAD"].includes(request.method())) throw new Error(`Unexpected mutation: ${path}`);
    if (path === `/v1/installations/${identifier}`) return route.fulfill({ json: installation });
    if (path.startsWith("/v1/")) return route.fulfill({ status: 404, json: { error: "not_found" } });
    const file = path.startsWith("/assets/") || path.startsWith("/brand/") ? path : "/index.html";
    return route.fulfill({
      body: await readFile(resolve("dist", `.${file}`)),
      contentType: file.endsWith(".js") ? "text/javascript" :
        file.endsWith(".css") ? "text/css" : file.endsWith(".png") ? "image/png" : "text/html",
    });
  });
  await page.goto(`https://hub.test/installations/${identifier}`);
  await expect(page.getByRole("heading", { name: identifier, exact: true })).toBeVisible();
  expect(reads).toBe(0);
  await page.getByRole("button", { name: "Application", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Application binding", exact: true })).toBeVisible();
  await expect.poll(() => reads).toBe(1);
  return { writes, errors };
}

async function review(page: Page, product: string) {
  await page.getByLabel("Application ID", { exact: true }).fill(product);
  const button = page.getByRole("button", { name: "Bind application", exact: true });
  await expect(button).toBeDisabled();
  await page.getByLabel("Type the application ID again to confirm", { exact: true }).fill(product);
  await expect(button).toBeEnabled();
}

async function geometry(page: Page) {
  const size = await page.evaluate(() => {
    const main = document.querySelector("main");
    if (!main) throw new Error("Missing installation surface");
    return {
      viewport: innerWidth, document: document.documentElement.scrollWidth,
      main: main.clientWidth, content: main.scrollWidth,
    };
  });
  expect(size.document).toBeLessThanOrEqual(size.viewport);
  expect(size.content).toBeLessThanOrEqual(size.main);
}

test("binding is lazy, keyboard-accessible, confirmed and does not dispatch a deployment", async ({ page }, info) => {
  const harness = await openBinding(page);
  const product = `example-${"a".repeat(55)}`;
  await review(page, product);
  await geometry(page);
  await page.screenshot({ path: info.outputPath("application-binding-desktop.png"), fullPage: true });
  for (const width of [993, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 641 });
    await geometry(page);
  }
  await page.getByRole("button", { name: "Bind application", exact: true }).click();
  await expect(page.getByText(`Bound application: ${product}.`, { exact: false })).toBeVisible();
  expect(harness.writes).toHaveLength(1);
  expect(harness.writes[0]).toMatchObject({
    product, expected_settings_digest: digest, reason_code: "operator_application_binding",
    confirmation: `bind application ${identifier} ${product} ${digest}`,
  });
  expect(Object.keys(harness.writes[0]!).sort()).toEqual([
    "confirmation", "expected_settings_digest", "product", "reason_code", "request_id",
  ]);
  expect(harness.errors).toEqual([]);
});

for (const failure of ["conflict", "network"] as const) {
  test(`an ${failure} outcome requires refresh without an automatic retry`, async ({ page }) => {
    const harness = await openBinding(page, { failure });
    await review(page, "example-web");
    await page.getByRole("button", { name: "Bind application", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText("Refresh");
    await expect(page.getByRole("button", { name: "Bind application", exact: true })).toBeDisabled();
    expect(harness.writes).toHaveLength(1);
    await page.getByRole("button", { name: "Refresh binding", exact: true }).click();
    await expect(page.getByLabel("Application ID", { exact: true })).toHaveValue("");
    expect(harness.writes).toHaveLength(1);
    expect(harness.errors).toEqual([]);
  });
}

test("a retained binding is read-only and an older Hub is not assumed unbound", async ({ page }) => {
  let harness = await openBinding(page, { product: "example-web" });
  await expect(page.getByText("Bound application:", { exact: false })).toBeVisible();
  await expect(page.getByRole("button", { name: "Bind application", exact: true })).toHaveCount(0);
  expect(harness.writes).toEqual([]);
  await page.unrouteAll();
  harness = await openBinding(page, { unsupported: true });
  await expect(page.getByText("This Hub does not report application bindings.", { exact: false })).toBeVisible();
  await expect(page.getByLabel("Application ID", { exact: true })).toHaveCount(0);
  expect(harness.writes).toEqual([]);
});

test("an open Plan blocks binding before any mutation", async ({ page }) => {
  const harness = await openBinding(page, { blocked: true });
  await expect(page.getByText("An open Plan blocks application binding.", { exact: false })).toBeVisible();
  await expect(page.getByLabel("Application ID", { exact: true })).toBeDisabled();
  expect(harness.writes).toEqual([]);
});
