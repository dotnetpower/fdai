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

test("release hub stencil builder composes lite custom menu build and prepares release draft", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const releaseDir = resolve("../../release-hub/ui/dist");
  const digest = "d".repeat(64);
  const composeRequests: unknown[] = [];

  await page.route("https://release-hub.test/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/auth/config") {
      return route.fulfill({ json: { profile: "local-development" } });
    }
    if (path === "/v1/catalog") {
      return route.fulfill({
        json: {
          revision: 1,
          updated_at: "2026-11-02T00:00:00Z",
          expires_at: "2099-11-03T00:00:00Z",
          expired: false,
          key_id: "dev-key-1",
          mode: "local-development",
          export_sha256: digest,
          releases: [],
          channels: { DEV: [], RELEASE_CANDIDATE: [], RELEASE: [] },
          events: [],
        },
      });
    }
    if (path === "/v1/stencils") {
      return route.fulfill({
        json: {
          presets: [
            {
              stencil: {
                schema_version: "fdai.stencil-definition.v1",
                stencil_id: "lite-observe-alert",
                title: "Lite: Agent-Driven Observe, Drift & Alert",
                title_ko: "경량 에디션: 에이전트 주도 변경·장애 감지 및 알림",
                description: "Minimal Azure resource footprint.",
                description_ko: "최소한의 Azure 리소스만 생성하는 경량 버전입니다.",
                topology_profile: "lite-observe-alert",
                enabled_workloads: ["core-control-plane", "operator-service"],
                enabled_scheduled_jobs: ["analyzer", "inventory"],
                enabled_loops: [
                  "anomaly-analyzer",
                  "inventory-reconciliation",
                  "notification-dispatch",
                  "saga-audit",
                ],
                enabled_addons: ["notifications", "read-only-console"],
                enabled_panel_ids: ["audit", "dashboard", "incidents", "live", "settings-general"],
                authority_granted: false,
              },
              footprint: {
                stencil_id: "lite-observe-alert",
                stencil_digest: `sha256:${digest}`,
                topology_profile: "lite-observe-alert",
                workload_count: 2,
                total_workloads: 5,
                omitted_workloads: [
                  "document-ingestion-api",
                  "document-processing-worker",
                  "isolated-executor",
                ],
                scheduled_job_count: 2,
                omitted_scheduled_jobs: ["canary", "cost-collector"],
                includes_clamav_sidecar: false,
                includes_privileged_executor: false,
                enabled_panel_count: 5,
                total_panel_count: 60,
                omitted_panel_count: 55,
                active_navigation_groups: ["evidence", "operations", "overview", "settings"],
                enabled_feature_ids: ["F01.1", "F02.1", "F03.1", "F04.1", "F08.1", "F10.1"],
                azure_rbac_posture: "read-only-observation",
                required_azure_roles: ["Reader", "Monitoring Reader", "Log Analytics Reader"],
                terraform_flags: {
                  enable_document_ingestion_workloads: false,
                  enable_isolated_executor: false,
                  product_profile_mode: "observation-first",
                },
                console_build_command:
                  "FDAI_STENCIL_ENABLED_PANELS='audit,dashboard,incidents,live,settings-general' npm --prefix console run build",
              },
            },
          ],
          panels: [
            {
              id: "dashboard",
              group: "overview",
              label: "Overview dashboard",
              label_ko: "종합 대시보드",
              locked: true,
              required_workloads: [],
              required_loops: [],
              required_addons: [],
              feature_ids: ["F01.1"],
            },
            {
              id: "live",
              group: "operations",
              label: "Live operations & resource changes",
              label_ko: "실시간 리소스 및 변경 감지",
              locked: false,
              required_workloads: [],
              required_loops: ["inventory-reconciliation"],
              required_addons: [],
              feature_ids: ["F02.1"],
            },
            {
              id: "incidents",
              group: "operations",
              label: "Incidents & anomaly alerts",
              label_ko: "장애 및 이상 징후 인시던트",
              locked: false,
              required_workloads: [],
              required_loops: ["anomaly-analyzer", "notification-dispatch"],
              required_addons: [],
              feature_ids: ["F04.1"],
            },
            {
              id: "audit",
              group: "evidence",
              label: "Hash-chained audit trail",
              label_ko: "해시 체인 감사 추적",
              locked: true,
              required_workloads: [],
              required_loops: ["saga-audit"],
              required_addons: [],
              feature_ids: ["F10.1"],
            },
            {
              id: "settings-general",
              group: "settings",
              label: "Settings: General",
              label_ko: "설정: 일반",
              locked: true,
              required_workloads: [],
              required_loops: [],
              required_addons: [],
              feature_ids: ["F01.1"],
            },
          ],
          workloads: ["core-control-plane", "operator-service", "isolated-executor"],
          locked_workloads: ["core-control-plane", "operator-service"],
          scheduled_jobs: ["analyzer", "inventory", "canary"],
          locked_scheduled_jobs: ["analyzer", "inventory"],
          loops: [
            "anomaly-analyzer",
            "inventory-reconciliation",
            "notification-dispatch",
            "saga-audit",
          ],
          locked_loops: [
            "anomaly-analyzer",
            "inventory-reconciliation",
            "notification-dispatch",
            "saga-audit",
          ],
          addons: ["notifications", "read-only-console"],
          locked_addons: ["notifications", "read-only-console"],
          locked_panels: ["audit", "dashboard", "settings-general"],
        },
      });
    }
    if (path === "/v1/stencils/compose" && request.method() === "POST") {
      const body = request.postDataJSON();
      composeRequests.push(body);
      return route.fulfill({
        json: {
          stencil: {
            schema_version: "fdai.stencil-definition.v1",
            stencil_id: body.stencil_id,
            title: body.title,
            title_ko: body.title_ko,
            description: body.description,
            description_ko: body.description_ko,
            topology_profile: body.topology_profile,
            enabled_workloads: ["core-control-plane", "operator-service"],
            enabled_scheduled_jobs: ["analyzer", "inventory"],
            enabled_loops: [
              "anomaly-analyzer",
              "inventory-reconciliation",
              "notification-dispatch",
              "saga-audit",
            ],
            enabled_addons: ["notifications", "read-only-console"],
            enabled_panel_ids: body.requested_panel_ids,
            authority_granted: false,
          },
          footprint: {
            stencil_id: body.stencil_id,
            stencil_digest: `sha256:${digest}`,
            topology_profile: "lite-observe-alert",
            workload_count: 2,
            total_workloads: 5,
            omitted_workloads: [
              "document-ingestion-api",
              "document-processing-worker",
              "isolated-executor",
            ],
            scheduled_job_count: 2,
            omitted_scheduled_jobs: ["canary", "cost-collector"],
            includes_clamav_sidecar: false,
            includes_privileged_executor: false,
            enabled_panel_count: body.requested_panel_ids.length,
            total_panel_count: 60,
            omitted_panel_count: 60 - body.requested_panel_ids.length,
            active_navigation_groups: ["evidence", "operations", "overview", "settings"],
            enabled_feature_ids: ["F01.1", "F02.1", "F04.1", "F10.1"],
            azure_rbac_posture: "read-only-observation",
            required_azure_roles: ["Reader", "Monitoring Reader", "Log Analytics Reader"],
            terraform_flags: {
              enable_document_ingestion_workloads: false,
              enable_isolated_executor: false,
              product_profile_mode: "observation-first",
            },
            console_build_command:
              "FDAI_STENCIL_ENABLED_PANELS='audit,dashboard,incidents,live,settings-general' npm --prefix console run build",
          },
          release_manifest: {
            schema_version: "fdai.application-release.v2",
            product: "fdai",
            release_version: "1.7.0",
            source_commit: "a".repeat(40),
            platform_tag: "linux-x86_64",
            components: {
              "core-control-plane": { image_digest: `sha256:${digest}` },
              "operator-service": { image_digest: `sha256:${digest}` },
              pgvector: { image_digest: `sha256:${digest}` },
            },
          },
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

  await page.goto("https://release-hub.test/#/stencils");
  await expect(page.getByRole("heading", { name: "Stencils & Custom Build" })).toBeVisible();

  // Switch to Korean and verify heading localization.
  await page.getByLabel("Builder language").selectOption("ko");
  await expect(page.getByRole("heading", { name: "Stencil 및 커스텀 메뉴 빌드" })).toBeVisible();
  await page.getByLabel("빌더 언어").selectOption("en");

  await page.getByRole("button", { name: "Validate & compose custom build" }).click();
  await expect(
    page.getByRole("heading", { name: "Composed Stencil & Resource Footprint" }),
  ).toBeVisible();
  await expect(page.getByText("Omitted (Lightweight)")).toBeVisible();
  expect(composeRequests).toHaveLength(1);

  for (const width of [1440, 993, 390]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page
    .getByRole("button", { name: "Prepare Release 1.7.0 registration with this Stencil" })
    .click();
  await expect(page.getByRole("heading", { name: "Register release" })).toBeVisible();
  await expect(page.getByLabel("Release id (SemVer)")).toHaveValue("1.7.0");
});
