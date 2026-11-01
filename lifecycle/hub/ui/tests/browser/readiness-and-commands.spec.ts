import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const installationId = "prod-korea";
const digest = "a".repeat(64);

test("installation readiness, recovery timeline, configuration tab, commands, audit, and EN/KO switch", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const writes: { path: string; body: unknown }[] = [];

  await page.route("https://hub.test/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/auth/config") {
      return route.fulfill({ json: { profile: "local-development" } });
    }
    if (path === `/v1/installations/${installationId}`) {
      return route.fulfill({
        json: {
          installation_id: installationId,
          enrollment: "enrolled",
          settings: {
            channel: "RELEASE",
            version_range: ">=1.4.0 <2.0.0",
            region: "koreacentral",
            allowed_regions: ["koreacentral"],
            windows: [
              {
                start: "02:00:00",
                duration_minutes: 60,
                timezone: "Asia/Seoul",
                allows_downtime: false,
              },
            ],
          },
          configuration_digest: digest,
          reported_at: "2026-10-25T01:00:00Z",
          schema_revision: 15,
          current_release: "1.5.0",
          health: "healthy",
          entities: [
            {
              entity_id: "core",
              kind: "workload",
              managed: true,
              ownership_gap: null,
              release_id: "1.5.0",
              health: "healthy",
            },
          ],
          suppressions: [
            {
              scope: "entity:core",
              starts_at: "2026-10-25T01:10:00Z",
              ends_at: "2099-10-26T01:10:00Z",
              origin: "failure",
              failed_plan_id: "plan-0001",
            },
          ],
          open_plan: null,
          last_evaluation: {
            outcome: "waiting",
            target_release_id: "1.6.0",
            plan_id: null,
            checks: [
              {
                release_id: "1.6.0",
                blocks: [{ reason_code: "suppression_window_active", details: [] }],
              },
            ],
            evaluated_at: "2026-10-25T01:12:00Z",
          },
          reports: [
            {
              plan_id: "plan-0001",
              attempt: 1,
              outcome: "rolled-back",
              reason_code: "health_check_failed",
              exact_plan_digest: `sha256:${digest}`,
              summary: "Canary failed readiness check",
              reported_at: "2026-10-25T01:10:00Z",
              received_at: "2026-10-25T01:10:01Z",
            },
          ],
        },
      });
    }
    if (path === "/v1/configurations") {
      return route.fulfill({
        json: {
          configurations: [
            {
              digest,
              imported_at: "2026-10-24T00:00:00Z",
              schema_key_count: 4,
              override_count: 1,
              installation_ids: [installationId],
              signature_status: "not-recorded",
            },
          ],
        },
      });
    }
    if (path === "/v1/installations") {
      return route.fulfill({
        json: {
          installations: [
            {
              installation_id: installationId,
              channel: "RELEASE",
              version_range: ">=1.4.0 <2.0.0",
              current_release: "1.5.0",
              target_release_id: "1.6.0",
              outcome: "waiting",
              health: "healthy",
              next_window_starts_at: "2026-10-26T02:00:00Z",
              next_window_ends_at: "2026-10-26T03:00:00Z",
              next_window_open: false,
              last_evaluated_at: "2026-10-25T01:12:00Z",
            },
          ],
        },
      });
    }
    if (path === `/v1/installations/${installationId}/suppressions/lift`) {
      writes.push({ path, body: request.postDataJSON() });
      return route.fulfill({ json: { lifted: installationId, scope: "entity:core" } });
    }
    if (path === "/v1/audit") {
      return route.fulfill({
        json: {
          chain_intact: true,
          records: [
            {
              sequence: 2,
              recorded_at: "2026-10-25T01:15:00Z",
              action: "suppression.lifted",
              installation_id: installationId,
              subject: "entity:core",
              previous_hash: "0".repeat(64),
              record_hash: "f".repeat(64),
            },
          ],
        },
      });
    }
    if (path.startsWith("/v1/")) {
      return route.fulfill({ status: 404, json: { error: "not_found" } });
    }
    const file = path.startsWith("/assets/") || path.startsWith("/brand/") ? path : "/index.html";
    return route.fulfill({
      body: await readFile(resolve("dist", `.${file}`)),
      contentType: file.endsWith(".js")
        ? "text/javascript"
        : file.endsWith(".css")
        ? "text/css"
        : file.endsWith(".png")
        ? "image/png"
        : "text/html",
    });
  });

  await page.goto(`https://hub.test/installations/${installationId}`);
  await expect(page.getByRole("heading", { name: "Update readiness and next step" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Failure, hold, and recovery timeline" }),
  ).toBeVisible();

  // Switch to Korean and verify localized headings without overflow.
  await page.getByRole("button", { name: "Switch workspace language" }).click();
  await expect(page.getByRole("heading", { name: "업데이트 준비 상태 및 다음 단계" })).toBeVisible();
  await page.getByRole("button", { name: "Switch workspace language" }).click();

  // Open Configuration tab and verify lazy load of stored revision metadata.
  await page.getByRole("button", { name: "Configuration", exact: true }).click();
  await expect(
    page.getByText("Stored revision metadata (signature provenance: not recorded)"),
  ).toBeVisible();

  // Navigate to Commands and lift the suppression using the one-click confirmation helper.
  await page.getByRole("link", { name: "Commands", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Lifecycle commands" })).toBeVisible();
  await page.getByLabel("Command action", { exact: true }).selectOption("lift");
  await page.getByLabel("Command installation", { exact: true }).selectOption(installationId);
  await page.getByLabel("Suppression scope", { exact: true }).fill("entity:core");
  await page.getByLabel("Reason code", { exact: true }).fill("verified_recovery");
  await page.getByRole("button", { name: "Fill reviewed confirmation" }).click();
  await page.getByRole("button", { name: "Lift suppression" }).click();
  await expect(page.getByRole("status")).toContainText("Active suppression lifted");
  expect(writes).toEqual([
    {
      path: `/v1/installations/${installationId}/suppressions/lift`,
      body: {
        scope: "entity:core",
        reason: "verified_recovery",
        confirmation: `lift suppression ${installationId} entity:core`,
      },
    },
  ]);

  // Navigate to Audit and verify hash-chain status.
  await page.getByRole("link", { name: "Audit", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Hash-chained audit" })).toBeVisible();
  await expect(page.getByText("Verified intact")).toBeVisible();
  await expect(page.getByRole("cell", { name: "suppression.lifted" })).toBeVisible();

  for (const width of [1440, 993, 390]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(
      await page.locator("main").evaluate((main) => main.scrollWidth <= main.clientWidth),
    ).toBe(true);
  }
});

test("release hub workspace promotes stage with one-click confirmation and checks EN/KO geometry", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const releaseDir = resolve("../../release-hub/ui/dist");
  const digest = "b".repeat(64);
  const manifest = JSON.stringify({
    product: "fdai",
    release_version: "1.6.0",
    source_commit: "c".repeat(40),
    platform_tag: "linux-x86_64",
    capability_maximums: { "action:scale-service": "auto" },
    services: { core: { image_digest: `sha256:${digest}`, sbom_sha256: digest } },
  });
  let channels = ["DEV"];
  let revision = 1;
  const promotions: unknown[] = [];

  await page.route("https://release-hub.test/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/auth/config") {
      return route.fulfill({ json: { profile: "local-development" } });
    }
    if (path === "/v1/catalog") {
      return route.fulfill({
        json: {
          revision,
          updated_at: "2026-10-26T00:00:00Z",
          expires_at: "2099-10-27T00:00:00Z",
          expired: false,
          key_id: "dev-key-1",
          mode: "local-development",
          export_sha256: digest,
          releases: [
            {
              id: "1.6.0",
              label: "Autumn candidate",
              manifest,
              digest,
              signed_payload_sha256: digest,
              signature: "c2ln",
              signature_status: "development-key-verified",
              state: "published",
              channels,
              published_at: "2026-10-26T00:00:00Z",
              recalled_at: null,
            },
          ],
          channels: {
            DEV: ["1.6.0"],
            RELEASE_CANDIDATE: channels.includes("RELEASE_CANDIDATE") ? ["1.6.0"] : [],
            RELEASE: [],
          },
          events:
            revision > 1
              ? [
                  {
                    revision: 2,
                    release_id: "1.6.0",
                    action: "contribute",
                    reason: "QA and canary soak verified",
                    channel: "RELEASE_CANDIDATE",
                    occurred_at: "2026-10-26T01:00:00Z",
                    actor: "local-operator",
                  },
                ]
              : [],
        },
      });
    }
    if (path === "/v1/releases/1.6.0/promote" && request.method() === "POST") {
      promotions.push(request.postDataJSON());
      revision = 2;
      channels = ["DEV", "RELEASE_CANDIDATE"];
      return route.fulfill({
        json: {
          revision,
          updated_at: "2026-10-26T01:00:00Z",
          expires_at: "2099-10-27T01:00:00Z",
          expired: false,
          key_id: "dev-key-1",
          mode: "local-development",
          releases: [],
          channels: { DEV: ["1.6.0"], RELEASE_CANDIDATE: ["1.6.0"], RELEASE: [] },
          events: [],
        },
      });
    }
    const file = path.startsWith("/assets/") || path.startsWith("/brand/") ? path : "/index.html";
    return route.fulfill({
      body: await readFile(resolve(releaseDir, `.${file}`)),
      contentType: file.endsWith(".js")
        ? "text/javascript"
        : file.endsWith(".css")
        ? "text/css"
        : file.endsWith(".png")
        ? "image/png"
        : "text/html",
    });
  });

  await page.goto("https://release-hub.test/#/releases/1.6.0");
  await expect(page.getByRole("heading", { name: "fdai 1.6.0" })).toBeVisible();
  await page.getByRole("button", { name: "Review promotion evidence" }).click();
  await expect(page.getByText("DEV -> RELEASE_CANDIDATE", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Promote DEV -> RELEASE_CANDIDATE" }).click();
  await expect(page.getByRole("heading", { name: "Promote stage" })).toBeVisible();
  await page.getByLabel("Reason").fill("QA and canary soak verified");
  await page.getByRole("button", { name: "Fill reviewed confirmation (1.6.0)" }).click();
  await page.getByRole("button", { name: "Confirm promote stage" }).click();

  await expect(page.getByRole("status")).toContainText("Catalog change recorded and read back");
  expect(promotions).toHaveLength(1);
  expect(promotions[0]).toMatchObject({
    revision: 1,
    confirmation: "1.6.0",
    reason: "QA and canary soak verified",
    source_channel: "DEV",
    target_channel: "RELEASE_CANDIDATE",
  });

  for (const width of [1440, 993, 390]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
