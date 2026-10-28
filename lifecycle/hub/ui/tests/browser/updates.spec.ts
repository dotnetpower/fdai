import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const SHA = "a".repeat(64);
const change = {
  added_releases: [{ release_id: "2.0.0", channels: ["DEV"], schema_target: 16 }],
  removed_releases: [], changed_releases: [], channel_additions: [], channel_removals: [],
  new_channels: [], new_recalls: [{ scope: "release", target: "1.0.0", sequence: 4 }],
  lifted_recalls: [], schema_widened: false,
};
const candidate = (verified: boolean) => ({
  revision: 7, sha256: SHA, expires_at: "2099-01-01T00:00:00Z", signature_verified: verified,
  key_id: verified ? "vendor-1" : null, accepted_revision: 6,
  decision: { allow: false, reasons: [verified ? "adoption_mode_review" : "signature_not_verified"] },
  change,
});
const reviewRecord = (verified: boolean) => ({
  checked_at: "2026-10-25T00:00:00Z", outcome: "review_required",
  detail: verified ? "adoption_mode_review" : "signature_not_verified",
  candidate: candidate(verified), plans: [],
});
const baseStatus = {
  mode: "review", allowed_channels: ["DEV"], max_new_releases: 3, check_interval_seconds: 900,
  access: "managed-identity", authorization: null, accepted: null, last_check: null, events: [],
};

async function stub(page: Page, options: {
  status: () => unknown; apply?: () => { status: number; json: unknown };
}) {
  const writes: { method: string; path: string; body: string | null }[] = [];
  let statusReads = 0;
  await page.route("https://hub.test/**", async route => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (!["GET", "HEAD"].includes(request.method())) {
      writes.push({ method: request.method(), path: pathname, body: request.postData() });
    }
    if (pathname === "/auth/config") return route.fulfill({ json: { profile: "local-development" } });
    if (pathname === "/v1/catalog/updates") {
      statusReads += 1;
      return route.fulfill({ json: options.status() });
    }
    if (pathname === "/v1/catalog/updates/check") {
      return route.fulfill({ json: { checked_at: "2026-10-25T01:00:00Z", outcome: "unchanged",
        detail: "source_reports_current", candidate: null, plans: [] } });
    }
    if (pathname === "/v1/catalog/updates/apply" && options.apply) {
      return route.fulfill(options.apply());
    }
    if (pathname.startsWith("/v1/")) return route.fulfill({ status: 404, json: { error: "not_found" } });
    const file = pathname.startsWith("/assets/") ? pathname : "/index.html";
    return route.fulfill({
      body: await readFile(resolve("dist", `.${file}`)),
      contentType: file.endsWith(".js") ? "text/javascript" :
        file.endsWith(".css") ? "text/css" : "text/html",
    });
  });
  return { writes, statusReads: () => statusReads };
}

async function expectNoOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(await page.locator("main").evaluate(main => main.scrollWidth <= main.clientWidth)).toBe(true);
}

test("no catalog accepted yet shows an empty state and Check now posts without a body", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await stub(page, { status: () => baseStatus });
  await page.goto("https://hub.test/updates");
  await expect(page.getByRole("heading", { name: "Updates", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Updates", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText("Checks the vendor catalog every 15 minutes; automatic adoption is off."))
    .toBeVisible();
  await expect(page.getByText("No catalog accepted yet")).toBeVisible();
  await expect(page.getByText("No update events recorded yet.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Review and apply" })).toHaveCount(0);
  await expect(page.locator("main input, main textarea")).toHaveCount(0);
  expect(api.writes).toEqual([]);

  await page.getByRole("button", { name: "Check now", exact: true }).click();
  await expect.poll(() => api.writes.length).toBe(1);
  expect(api.writes[0]).toMatchObject({ method: "POST", path: "/v1/catalog/updates/check", body: null });
  await expect.poll(api.statusReads).toBe(2);
  await expectNoOverflow(page);
});

test("review_required candidate is applied with its own revision and digest", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let adopted = false;
  const adoptedRecord = {
    checked_at: "2026-10-25T02:00:00Z", outcome: "adopted", detail: "adopted", candidate: candidate(true),
    plans: [{ installation_id: "installation-alpha", outcome: "issued" }],
  };
  const api = await stub(page, {
    status: () => adopted
      ? { ...baseStatus, accepted: { revision: 7, sha256: SHA, expires_at: "2099-01-01T00:00:00Z", release_count: 2 },
        last_check: adoptedRecord,
        events: [{ action: "adopted", actor: "admin@example.test", revision: 7, sha256: SHA,
          reason: "operator", recorded_at: "2026-10-25T02:00:00Z" }] }
      : { ...baseStatus, last_check: reviewRecord(true) },
    apply: () => { adopted = true; return { status: 200, json: adoptedRecord }; },
  });
  await page.goto("https://hub.test/updates");
  await expect(page.getByText("Automatic adoption is off, so every new catalog needs your review."))
    .toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Urgent: this catalog adds recalls" })).toBeVisible();
  await expect(page.getByText("2.0.0 (DEV)")).toBeVisible();
  await expect(page.getByText("Yes (key vendor-1)")).toBeVisible();
  await expectNoOverflow(page);
  expect(api.writes).toEqual([]);

  const apply = page.getByRole("button", { name: "Review and apply" });
  await apply.click();
  await expect.poll(() => api.writes.length).toBe(1);
  expect(api.writes[0]).toMatchObject({ method: "POST", path: "/v1/catalog/updates/apply" });
  expect(JSON.parse(api.writes[0]!.body!)).toEqual({ revision: 7, sha256: SHA });
  await expect(page.getByRole("status").filter({ hasText: "The new catalog was adopted." })).toBeVisible();
  await expect(page.getByRole("cell", { name: "installation-alpha" })).toBeVisible();
  await expect(page.getByText("Plan issued")).toBeVisible();
  await expect(page.getByText("Issuing a Plan never applies it.")).toBeVisible();
  await expect(page.getByRole("cell", { name: "admin@example.test" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review and apply" })).toHaveCount(0);
  expect(api.writes).toHaveLength(1);
  for (const width of [993, 390]) {
    await page.setViewportSize({ width, height: 844 });
    await expectNoOverflow(page);
  }
});

test("409 candidate_changed explains the change and reloads the status", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await stub(page, {
    status: () => ({ ...baseStatus, last_check: reviewRecord(true) }),
    apply: () => ({ status: 409, json: { error: "candidate_changed" } }),
  });
  await page.goto("https://hub.test/updates");
  await page.getByRole("button", { name: "Review and apply" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "The vendor catalog changed after you reviewed it." }))
    .toBeVisible();
  await expect.poll(api.statusReads).toBe(2);
  await expect(page.getByRole("button", { name: "Review and apply" })).toBeVisible();
  expect(api.writes).toHaveLength(1);
});

test("an unsigned candidate offers no apply button and points to Catalog import", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await stub(page, { status: () => ({ ...baseStatus, last_check: reviewRecord(false) }) });
  await page.goto("https://hub.test/updates");
  await expect(page.getByText("Signature not verified")).toBeVisible();
  await expect(page.getByText("The catalog signature could not be verified.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Review and apply" })).toHaveCount(0);
  await expect(page.getByRole("note").getByRole("link", { name: "Catalog import" }))
    .toHaveAttribute("href", "/catalog");
  expect(api.writes).toEqual([]);
});

test("failed check and automatic mode show clear sentences", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await stub(page, {
    status: () => ({ ...baseStatus, mode: "auto", check_interval_seconds: 7200,
      authorization: { authorized_by: "admin@example.test", expires_at: "2099-01-01T00:00:00Z", valid: true },
      last_check: { checked_at: "2026-10-25T00:00:00Z", outcome: "failed", detail: "source_unavailable",
        candidate: null, plans: [] } }),
  });
  await page.goto("https://hub.test/updates");
  await expect(page.getByText("Checks the vendor catalog every 2 hours; automatic adoption is on."))
    .toBeVisible();
  await expect(page.getByText("The vendor catalog source could not be reached. Try again later.")).toBeVisible();
  await expect(page.getByText("admin@example.test, expires")).toBeVisible();
  await expect(page.locator(".badge").filter({ hasText: "Valid" })).toBeVisible();
});

const integrityResult = (overrides: Record<string, unknown> = {}) => ({
  mode: "tuf", verified: true, reason: "allowed",
  root: { version: 2, expires_at: "2099-01-01T00:00:00Z" },
  snapshot: { version: 5, expires_at: "2099-01-01T00:00:00Z" },
  timestamp: { version: 9, expires_at: "2099-01-01T00:00:00Z" },
  expired: false, root_rotation: false, previous_root_version: 2, max_recall_sequence: 3,
  allowed_plan_types: ["install", "upgrade", "recall-rolloff"],
  demote_operator_overrides_to_shadow: false, ...overrides,
});
const integrityState = (overrides: Record<string, unknown> = {}) => ({
  mode: "tuf", root_version: 2, snapshot_version: 5, snapshot_expires_at: "2099-01-01T00:00:00Z",
  timestamp_version: 9, timestamp_expires_at: "2099-01-01T00:00:00Z", max_recall_sequence: 3,
  observed_at: "2026-10-25T00:00:00Z", last: integrityResult(), ...overrides,
});
const tufReview = (integrity: unknown, reasons: string[]) => ({
  ...reviewRecord(true),
  detail: reasons.join(","),
  candidate: { ...candidate(true), decision: { allow: false, reasons }, integrity },
  integrity,
});

test("signed roles show versions and a fresh timestamp as verified", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await stub(page, { status: () => ({ ...baseStatus, integrity: integrityState() }) });
  await page.goto("https://hub.test/updates");
  const panel = page.getByText("Catalog integrity").locator("..");
  await expect(panel.locator(".badge").filter({ hasText: "Verified" })).toBeVisible();
  await expect(panel.getByText("Root v2, snapshot v5, timestamp v9.")).toBeVisible();
  await expect(panel.getByText("Timestamp expires")).toBeVisible();
  await expect(page.getByText("Only recall roll-off")).toHaveCount(0);
  await expectNoOverflow(page);
  expect(api.writes).toEqual([]);
});

test("an expired timestamp is judged now and limits the Hub to recall roll-off", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const expired = integrityResult({
    expired: true, demote_operator_overrides_to_shadow: true, allowed_plan_types: ["recall-rolloff"],
    timestamp: { version: 9, expires_at: "2020-01-01T00:00:00Z" },
  });
  const record = tufReview(expired, ["timestamp_expired"]);
  const api = await stub(page, {
    status: () => ({ ...baseStatus, last_check: record, integrity: integrityState({
      timestamp_expires_at: "2020-01-01T00:00:00Z", last: expired }) }),
  });
  await page.goto("https://hub.test/updates");
  const panel = page.getByText("Catalog integrity").locator("..");
  await expect(panel.locator(".badge").filter({ hasText: "Timestamp expired" })).toBeVisible();
  await expect(panel.getByText("Only recall roll-off Plans are issued")).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Timestamp expired" })).toBeVisible();
  await expect(page.getByText("The vendor's signed timestamp has expired, so only recall changes")).toBeVisible();
  await expect(page.getByRole("button", { name: "Review and apply" })).toHaveCount(0);
  await expect(page.getByRole("note").filter({ hasText: "timestamp has expired" })).toBeVisible();
  expect(api.writes).toEqual([]);
});

test("a stale persisted timestamp warns even when the last check said verified", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await stub(page, {
    status: () => ({ ...baseStatus, integrity: integrityState({ timestamp_expires_at: "2020-01-01T00:00:00Z" }) }),
  });
  await page.goto("https://hub.test/updates");
  const panel = page.getByText("Catalog integrity").locator("..");
  await expect(panel.locator(".badge").filter({ hasText: "Timestamp expired" })).toBeVisible();
  await expect(panel.getByText("Only recall roll-off Plans are issued")).toBeVisible();
});

test("a root rotation is shown for review with both versions and can be applied by a person", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const rotation = integrityResult({
    root_rotation: true, previous_root_version: 1, root: { version: 2, expires_at: "2099-01-01T00:00:00Z" },
  });
  const api = await stub(page, {
    status: () => ({ ...baseStatus, last_check: tufReview(rotation, ["root_rotation_requires_review"]),
      integrity: integrityState({ root_version: 1, last: rotation }) }),
    apply: () => ({ status: 200, json: { ...reviewRecord(true), outcome: "adopted", detail: "operator_review",
      plans: [] } }),
  });
  await page.goto("https://hub.test/updates");
  await expect(page.getByRole("alert").filter({ hasText: "Root rotation awaiting review" })).toBeVisible();
  await expect(page.getByText("The vendor changed its offline root keys. A root rotation always needs your review."))
    .toBeVisible();
  await expect(page.getByText("v2 (was v1)")).toBeVisible();
  await expect(page.getByLabel("Catalog roles").getByText("v5", { exact: true })).toBeVisible();
  await expectNoOverflow(page);
  await page.getByRole("button", { name: "Review and apply" }).click();
  await expect.poll(() => api.writes.length).toBe(1);
  expect(JSON.parse(api.writes[0]!.body!)).toEqual({ revision: 7, sha256: SHA });
});

test("unverified roles fail the check with the reason in plain words", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const failed = integrityResult({ verified: false, reason: "catalog_version_rollback" });
  await stub(page, {
    status: () => ({ ...baseStatus, integrity: integrityState({ last: failed }),
      last_check: { checked_at: "2026-10-25T00:00:00Z", outcome: "failed", detail: "integrity_not_verified",
        candidate: null, plans: [], integrity: failed } }),
  });
  await page.goto("https://hub.test/updates");
  await expect(page.getByText("The vendor's signed catalog roles could not be verified, so the catalog was not accepted."))
    .toBeVisible();
  await expect(page.getByText("A signed record carries an older version").first()).toBeVisible();
  await expect(page.locator(".badge").filter({ hasText: "Not verified" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Review and apply" })).toHaveCount(0);
});
