import { writeFile } from "node:fs/promises";

import { expect, test, type BrowserContext, type Page, type TestInfo } from "@playwright/test";

import { buildBrowserEvidenceProvenance } from "./browser-evidence-provenance";
import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";

const AUTHENTICATED_EXTERNAL_STACK = Boolean(
  process.env.FDAI_E2E_BASE_URL && process.env.FDAI_E2E_STORAGE_STATE,
);
const EXPECTED_STREAM_PATHS = new Set([
  "/access-grants/stream",
  "/incidents/stream",
  "/live/stream",
]);

interface LockSnapshot {
  readonly held_count: number;
  readonly pending_count: number;
  readonly held_client_ids: readonly string[];
  readonly held_names: readonly string[];
  readonly pending_client_ids: readonly string[];
}

async function waitForReadyShell(page: Page): Promise<void> {
  await expect(page.locator(".shell")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("main [aria-busy='true']")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByText("FDAI could not verify your access.")).toHaveCount(0);
}

async function lockSnapshot(page: Page): Promise<LockSnapshot> {
  return page.evaluate(async () => {
    const snapshot = await navigator.locks.query();
    return {
      held_count: snapshot.held?.length ?? 0,
      pending_count: snapshot.pending?.length ?? 0,
      held_client_ids: [...new Set(snapshot.held?.flatMap((lock) => lock.clientId ?? []) ?? [])],
      held_names: snapshot.held?.flatMap((lock) => lock.name ?? []).toSorted() ?? [],
      pending_client_ids: [
        ...new Set(snapshot.pending?.flatMap((lock) => lock.clientId ?? []) ?? []),
      ],
    };
  });
}

async function waitForLockCounts(page: Page, held: number, pending: number): Promise<void> {
  await expect.poll(async () => {
    const snapshot = await lockSnapshot(page);
    return { held_count: snapshot.held_count, pending_count: snapshot.pending_count };
  }, { timeout: 10_000 }).toEqual({ held_count: held, pending_count: pending });
}

async function openAuthenticatedPage(
  context: BrowserContext,
  sourcePage: Page,
  path: string,
  syntheticNotificationPermission = false,
  onPageCreated?: (page: Page) => void,
): Promise<Page> {
  const sessionEntries = await sourcePage.evaluate(() => Object.entries(sessionStorage));
  const nextPage = await context.newPage();
  onPageCreated?.(nextPage);
  if (syntheticNotificationPermission) {
    await installSyntheticNotificationPermission(nextPage);
  }
  await nextPage.addInitScript((entries) => {
    for (const [key, value] of entries) sessionStorage.setItem(key, value);
  }, sessionEntries);
  await nextPage.goto(path, { waitUntil: "domcontentloaded" });
  await waitForReadyShell(nextPage);
  return nextPage;
}

async function installSyntheticNotificationPermission(page: Page): Promise<void> {
  await page.addInitScript(() => {
    Object.defineProperty(Notification, "permission", {
      configurable: true,
      get: () => "granted",
    });
  });
}

function provenance(configuration: object) {
  return buildBrowserEvidenceProvenance(
    process.env.FDAI_E2E_SOURCE_REVISION,
    process.env.FDAI_E2E_WORKSPACE_PATCH_SHA256,
    configuration,
  );
}

async function retainArtifact(testInfo: TestInfo, name: string, artifact: object): Promise<void> {
  const artifactPath = testInfo.outputPath(name);
  await writeFile(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`, "utf8");
  await testInfo.attach(name, { path: artifactPath, contentType: "application/json" });
}

test("Browser Entra tabs share bounded attention and notification streams", async ({ page }, testInfo) => {
  test.skip(!AUTHENTICATED_EXTERNAL_STACK, "requires Browser Entra storage state");
  test.setTimeout(90_000);
  const configuration = {
    schema_version: "1.0.0",
    authentication: "browser_entra",
    routes: ["/overview", "/ontology", "/agent-activity"],
    expected_stream_channels: EXPECTED_STREAM_PATHS.size,
    page_count: 3,
    notification_permission: "synthetic_granted_for_connection_mechanics",
  };
  const pageLabels = new WeakMap<Page, string>();
  pageLabels.set(page, "initial");
  const streamRequests: Array<{ readonly path: string; readonly owner: string }> = [];
  let authenticatedSelfResponseCount = 0;
  page.context().on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (EXPECTED_STREAM_PATHS.has(path)) {
      streamRequests.push({
        path,
        owner: pageLabels.get(request.frame().page()) ?? "unknown",
      });
    }
  });
  page.context().on("response", (response) => {
    if (new URL(response.url()).pathname === "/iam/self" && response.status() === 200) {
      authenticatedSelfResponseCount += 1;
    }
  });

  await installSyntheticNotificationPermission(page);
  await restoreBrowserEntraSessionStorage(page);
  await page.goto("/overview", { waitUntil: "domcontentloaded" });
  await waitForReadyShell(page);
  const notificationControl = page.locator(".browser-notification-control");
  await expect(notificationControl).toBeVisible();
  if (await notificationControl.getAttribute("aria-pressed") !== "true") {
    await notificationControl.click();
  }
  await expect(notificationControl).toHaveAttribute("aria-pressed", "true");
  await waitForLockCounts(page, 3, 0);
  const iamDurationMs = await page.evaluate(() => (
    performance.getEntriesByType("resource")
      .filter((entry) => entry.name.includes("/iam/self"))
      .at(-1)?.duration ?? null
  ));

  const ontology = await openAuthenticatedPage(
    page.context(), page, "/ontology?view=topology", true,
    (created) => pageLabels.set(created, "ontology"),
  );
  const activity = await openAuthenticatedPage(
    page.context(), page, "/agent-activity", true,
    (created) => pageLabels.set(created, "agent-activity"),
  );
  await waitForLockCounts(activity, 3, 6);
  const beforeFailoverLocks = await lockSnapshot(activity);
  expect(beforeFailoverLocks.held_client_ids).toHaveLength(1);
  expect(beforeFailoverLocks.pending_client_ids).toHaveLength(2);
  expect(beforeFailoverLocks.held_names.map((name) => name.split(":")[1])).toEqual([
    "access-grant-attention",
    "browser-notifications",
    "incident-attention",
  ]);
  const afterThreePages = [...streamRequests];
  expect(new Set(afterThreePages.map((request) => request.owner))).toEqual(new Set(["initial"]));
  expect(new Set(afterThreePages.map((request) => request.path))).toEqual(EXPECTED_STREAM_PATHS);

  await page.close();
  await waitForLockCounts(activity, 3, 3);
  const afterFailoverLocks = await lockSnapshot(activity);
  expect(afterFailoverLocks.held_client_ids).toHaveLength(1);
  expect(afterFailoverLocks.pending_client_ids).toHaveLength(1);
  expect(afterFailoverLocks.held_client_ids[0]).not.toBe(beforeFailoverLocks.held_client_ids[0]);
  await expect.poll(
    () => new Set(streamRequests.filter((request) => request.owner !== "initial")
      .map((request) => request.path)),
    { timeout: 10_000 },
  ).toEqual(EXPECTED_STREAM_PATHS);
  const failoverOwners = new Set(
    streamRequests.filter((request) => request.owner !== "initial")
      .map((request) => request.owner),
  );
  expect(failoverOwners.size).toBe(1);
  expect(failoverOwners.has("unknown")).toBe(false);
  expect(authenticatedSelfResponseCount).toBe(3);
  expect(iamDurationMs).not.toBeNull();
  expect(iamDurationMs!).toBeLessThan(30_000);

  await retainArtifact(testInfo, "console-cross-tab-sse-assurance.json", {
    schema_version: "1.0.0",
    evidence_type: "authenticated_console_cross_tab_sse_assurance",
    receipt_source: "live_assurance",
    ...provenance(configuration),
    run_configuration: configuration,
    captured_at: new Date().toISOString(),
    authentication: "browser_entra",
    authentication_attestation: {
      storage_state_restored: true,
      authenticated_self_response_count: authenticatedSelfResponseCount,
      synthetic_notification_permission: true,
      notification_delivery_claimed: false,
    },
    passed: true,
    summary: {
      initial_iam_duration_ms: iamDurationMs,
      held_stream_leader_count_after_one_page: 3,
      held_stream_leader_count_after_three_pages: 3,
      pending_lock_count_after_three_pages: 6,
      held_stream_leader_count_after_leader_close: 3,
      pending_lock_count_after_leader_close: 3,
      follower_pages_healthy: 2,
      initial_leader_client_count: beforeFailoverLocks.held_client_ids.length,
      failover_leader_client_count: afterFailoverLocks.held_client_ids.length,
      leader_client_changed: true,
      initial_leader_request_attempt_count: afterThreePages.length,
      failover_leader_request_attempt_count:
        streamRequests.filter((request) => request.owner !== "initial").length,
    },
  });
  await ontology.close();
  await activity.close();
});

test("Agent Activity refreshes heartbeat state without initialization rows", async ({ page }, testInfo) => {
  test.skip(!AUTHENTICATED_EXTERNAL_STACK, "requires Browser Entra storage state");
  test.setTimeout(150_000);
  const configuration = {
    schema_version: "1.0.0",
    authentication: "browser_entra",
    route: "/agent-activity",
    refresh_count: 2,
  };
  let authenticatedSelfResponseCount = 0;
  page.on("response", (response) => {
    if (new URL(response.url()).pathname === "/iam/self" && response.status() === 200) {
      authenticatedSelfResponseCount += 1;
    }
  });
  await restoreBrowserEntraSessionStorage(page);

  const samples: Array<{
    readonly last_observed_at: string;
    readonly row_count: number;
    readonly initialization_row_count: number;
  }> = [];
  await page.goto(configuration.route, { waitUntil: "domcontentloaded" });
  await waitForReadyShell(page);
  const journal = page.locator(".aa-live-journal");
  await expect(journal).toBeVisible();
  const firstHeartbeatAt = await journal.locator("header time").getAttribute("datetime");
  expect(firstHeartbeatAt).not.toBeNull();
  let previousHeartbeatMs = Date.parse(firstHeartbeatAt!);

  for (let refresh = 0; refresh <= configuration.refresh_count; refresh += 1) {
    if (refresh > 0) await page.reload({ waitUntil: "domcontentloaded" });
    await waitForReadyShell(page);
    await expect(journal).toBeVisible();
    const lastObserved = journal.locator("header time");
    await expect(lastObserved).toHaveCount(1, { timeout: 15_000 });
    await expect.poll(async () => {
      const observedAt = await lastObserved.getAttribute("datetime");
      return observedAt === null ? null : Date.parse(observedAt);
    }, { timeout: 45_000, intervals: [1_000] }).toBeGreaterThan(previousHeartbeatMs);
    const lastObservedAt = await lastObserved.getAttribute("datetime");
    expect(lastObservedAt).not.toBeNull();
    expect(Number.isFinite(Date.parse(lastObservedAt!))).toBe(true);
    previousHeartbeatMs = Date.parse(lastObservedAt!);
    const rows = journal.locator(".aa-log-row");
    samples.push({
      last_observed_at: lastObservedAt!,
      row_count: await rows.count(),
      initialization_row_count: await rows.filter({ hasText: "Runtime agent initialized" }).count(),
    });
  }
  expect(samples.every((sample) => sample.initialization_row_count === 0)).toBe(true);
  expect(samples.every((sample) => sample.last_observed_at !== firstHeartbeatAt)).toBe(true);
  expect(authenticatedSelfResponseCount).toBe(3);

  await retainArtifact(testInfo, "agent-activity-heartbeat-assurance.json", {
    schema_version: "1.0.0",
    evidence_type: "authenticated_agent_activity_heartbeat_assurance",
    receipt_source: "live_assurance",
    ...provenance(configuration),
    run_configuration: configuration,
    captured_at: new Date().toISOString(),
    authentication: "browser_entra",
    authentication_attestation: {
      storage_state_restored: true,
      authenticated_self_response_count: authenticatedSelfResponseCount,
    },
    passed: true,
    summary: {
      samples,
      initialization_row_count: 0,
      heartbeat_timestamp_present_after_each_load: true,
      heartbeat_timestamp_advanced_before_refresh: true,
    },
  });
});
