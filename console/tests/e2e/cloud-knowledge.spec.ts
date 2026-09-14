import { expect, test, type Page } from "@playwright/test";

const source = {
  source_id: "apim", title: "API Management networking", collection_id: "cloud-reference",
  mode: "offline", enabled: false, check_interval_seconds: 604800,
  max_unverified_seconds: 2592000, collected_at: "2026-08-01T00:00:00Z",
  checked_at: "2026-08-01T00:00:00Z", freshness: "stale",
  next_due_at: "2026-08-08T00:00:00Z", last_attempt: null,
  update_pending: false, consecutive_failures: 0,
};
const release = {
  release_id: "cloud-1", sequence: 1, manifest_digest: "a".repeat(64),
  registry_digest: "b".repeat(64), package_created_at: "2026-09-10T00:00:00Z",
  imported_at: "2026-09-14T00:00:00Z", admission_expires_at: "2026-10-01T00:00:00Z",
  verified_key_id: "fixture", sources: [{
    source_id: "apim", source_url: "https://example.com/apim", source_sha256: "c".repeat(64),
    normalized_sha256: "d".repeat(64), collected_at: source.collected_at,
    check: { checked_at: source.checked_at, outcome: "fetched" },
    applicability: { provider: "azure", resource_type: "Microsoft.ApiManagement/service",
      service_generation: "classic", skus: ["Premium"], api_versions: [], regions: [], deployment_modes: [] },
    policy: { policy_id: "weekly", check_interval_seconds: 604800, max_unverified_seconds: 2592000 },
    license_ref: "fixture",
  }],
};

async function noOverflow(page: Page): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator(".shell-body > main").evaluate(
    (element) => element.scrollWidth <= element.clientWidth,
  )).toBe(true);
}

test("cloud knowledge dates and reviewed intake stay distinct across desktop and narrow layouts", async ({ page }) => {
  let imports = 0;
  let inspections = 0;
  let rollbacks = 0;
  const bytes: string[] = [];
  await page.context().route("http://127.0.0.1:8011/ingestion/cloud-knowledge**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const headers = {
      "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization,content-type",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    let result: object = { available: true, registry_revision: 1,
      registry_valid_until: "2026-10-01T00:00:00Z", can_refresh: true, can_import: true,
      sources: [source], collections: [{ collection_id: source.collection_id, versions: [{
        document_id: "document-1", version_id: "version-1", state: "ready", active: true,
        available: true, updated_at: "2026-09-14T00:00:00Z", release,
      }, {
        document_id: "document-1", version_id: "version-prior", state: "ready", active: false,
        available: true, updated_at: "2026-09-10T00:00:00Z", release: { ...release, release_id: "cloud-prior" },
      }] }], automatic_activation: false, approval_required: true };
    if (path.endsWith("/inspect")) {
      inspections += 1;
      bytes.push(request.postData() ?? "");
      result = { status: "verified_candidate", approval_required: true, release, document_count: 1 };
    } else if (path.endsWith("/import")) {
      imports += 1;
      bytes.push(request.postData() ?? "");
      result = { status: "ingestion_requested", approval_required: true, release,
        session: { upload_id: "upload-1", document_id: "document-1", version_id: "version-new", state: "received" } };
    } else if (path.endsWith("/versions/version-prior/rollback")) {
      rollbacks += 1;
      result = { status: "ingestion_requested", approval_required: true, release,
        session: { upload_id: "rollback-1", document_id: "document-1", version_id: "rollback-candidate", state: "received" } };
    }
    await route.fulfill({ status: 200, headers, contentType: "application/json", body: JSON.stringify(result) });
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/knowledge");
  const panel = page.getByRole("region", { name: "Cloud reference knowledge" });
  await expect(panel.getByRole("heading", { name: "Cloud reference knowledge" })).toBeVisible();
  await expect(panel.getByText("Stale reference", { exact: true }).first()).toBeVisible();
  await expect(panel.getByText(/2026-08-01/).first()).toBeVisible();
  await expect(panel.getByRole("button", { name: "Import inspected package for review" })).toBeDisabled();
  await panel.getByLabel("Signed knowledge package", { exact: true }).setInputFiles({
    name: "knowledge.json", mimeType: "application/json", buffer: Buffer.from('{"fixture":"data"}'),
  });
  await panel.getByRole("button", { name: "Inspect selected package" }).click();
  await expect(panel.getByText(/Verified candidate \(1 documents\)/)).toBeVisible();
  expect(imports).toBe(0);
  await panel.getByLabel(/I confirm submitting this exact inspected package/).check();
  await panel.getByRole("button", { name: "Import inspected package for review" }).click();
  await expect(panel.getByText(/Ingestion requested for version version-new/)).toBeVisible();
  expect(imports).toBe(1);
  expect(inspections).toBe(1);
  expect(bytes[0]).toBe(bytes[1]);
  await expect(panel.getByRole("button", { name: "Import inspected package for review" })).toBeDisabled();
  expect(await panel.locator('a[href^="https://"]').count()).toBe(0);
  await panel.locator("summary").filter({ hasText: /^cloud-reference$/ }).click();
  await panel.locator("summary").filter({ hasText: /^cloud-prior - / }).click();
  const rollback = panel.getByRole("button", { name: "Submit this revision for rollback review" });
  await expect(rollback).toBeDisabled();
  await panel.getByLabel(/Confirm a new reviewed rollback request/).check();
  await rollback.click();
  await expect(panel.getByText(/Ingestion requested for version rollback-candidate/)).toBeVisible();
  expect(rollbacks).toBe(1);
  await expect(panel.locator("summary").filter({ hasText: /^cloud-1 - Active generation/ })).toHaveCount(1);
  expect(await panel.getByText("rollback-candidate - Active generation", { exact: true }).count()).toBe(0);
  await noOverflow(page);
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await expect(panel.getByRole("heading", { name: "Registered sources" })).toBeVisible();
    await noOverflow(page);
  }
});

test("missing cloud policies show unavailable without enabling actions", async ({ page }) => {
  await page.route("http://127.0.0.1:8011/ingestion/cloud-knowledge", async (route) => {
    await route.fulfill({ status: 200, headers: { "Access-Control-Allow-Origin": "*" },
      contentType: "application/json", body: JSON.stringify({ available: false,
        reason: "source_and_trust_policy_required", can_refresh: false, can_import: false,
        sources: [], collections: [] }) });
  });
  await page.goto("/knowledge");
  const panel = page.getByRole("region", { name: "Cloud reference knowledge" });
  await expect(panel.getByText(/Cloud reference knowledge is unavailable/)).toBeVisible();
  await expect(panel.getByRole("button", { name: "Check due sources" })).toBeDisabled();
  await expect(panel.getByRole("button", { name: "Inspect selected package" })).toBeDisabled();
});
