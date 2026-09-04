import { expect, test, type Page, type Route } from "@playwright/test";

const runtimeSettings = {
  revision: 2,
  can_manage: true,
  updated_at: null,
  updated_by: null,
  integrations: [
    {
      key: "teams-a1-approval-send",
      source: "core-control-plane",
      observed: true,
      configured: false,
      ready: false,
      mode: "disabled",
      reason: "not configured",
    },
    {
      key: "teams-a1-approval-callback",
      source: "operator-service",
      observed: false,
      configured: false,
      ready: false,
      mode: "disabled",
      reason: "prerequisites are owned by another runtime and were not observed",
    },
    {
      key: "teams-a2-operational-alert",
      source: "core-control-plane",
      observed: true,
      configured: true,
      ready: false,
      mode: "disabled",
      reason: "a binding exists but is not activated for delivery",
    },
    {
      key: "teams-a3-conversation",
      source: "operator-service",
      observed: false,
      configured: false,
      ready: false,
      mode: "disabled",
      reason: "prerequisites are owned by another runtime and were not observed",
    },
    {
      key: "notification-bindings",
      source: "core-control-plane",
      observed: true,
      configured: true,
      ready: true,
      mode: "enabled",
      reason: null,
    },
  ],
  runtime: {
    environment: "dev",
    state_store_durable: true,
    autonomy_default: "shadow",
    pantheon_enabled: true,
    workflow_observation_enabled: true,
    primary_transport_configured: true,
    auxiliary_transport_configured: false,
    case_history_configured: false,
  },
  settings: [],
};

const webhookUrl = (
  "https://example.e4.environment.api.powerplatform.com:443/"
  + "powerautomate/automations/direct/workflows/"
  + "d74f3e0ee1314a4191c650cfda483a70/triggers/manual/paths/invoke"
  + "?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0"
  + "&sig=abcdefghijklmnopqrstuvwxyz012345"
);
const slackWebhookUrl = (
  "https://hooks.slack.com/services/T00000000/B00000000/abcdefghijklmnopqrstuvwxyz"
);

async function installFixture(page: Page): Promise<{
  teamsBody: () => unknown;
  slackBody: () => unknown;
}> {
  let teamsBody: unknown = null;
  let slackBody: unknown = null;
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/runtime/settings") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runtimeSettings),
      });
      return;
    }
    if (path === "/runtime/integrations/teams-workflow/binding") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          visible: true,
          configured: true,
          binding_version: "version-1",
          observed_at: "2026-09-04T07:00:00Z",
          saved_at: "2026-09-04T06:00:00Z",
        }),
      });
      return;
    }
    if (path === "/runtime/integrations/teams-workflow/test") {
      teamsBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          request_id: "teams-workflow-test-00000000-0000-0000-0000-000000000000",
          saved: true,
          binding_version: "version-2",
          saved_at: "2026-08-27T11:59:59Z",
          accepted: true,
          provider_status: 202,
          workflow_run_id: "run-1",
          tested_at: "2026-08-27T12:00:00Z",
        }),
      });
      return;
    }
    if (path === "/runtime/integrations/slack-webhook/test") {
      slackBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          request_id: "slack-webhook-test-00000000-0000-0000-0000-000000000000",
          accepted: true,
          provider_status: 200,
          tested_at: "2026-08-27T13:00:00Z",
        }),
      });
      return;
    }
    if (path === "/notification-templates/incident-opened") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          key: "incident-opened",
          subject: "[SEV2] Incident opened",
          plain_text: "Incident details",
          html: "<!doctype html><html><body>Incident details</body></html>",
        }),
      });
      return;
    }
    await route.continue();
  };
  await page.route("**/api/**", handle);
  await page.route("**/runtime/**", handle);
  await page.route("**/notification-templates/**", handle);
  return {
    teamsBody: () => teamsBody,
    slackBody: () => slackBody,
  };
}

test("separates approval, notification, and conversation readiness without leaking the saved URL", async ({ page }) => {
  if (process.env["FDAI_SETTINGS_VIEWPORT"] === "constrained") {
    await page.setViewportSize({ width: 993, height: 641 });
  }
  const fixture = await installFixture(page);
  await page.goto("/settings/integrations");

  await expect(page.getByRole("heading", { name: "A1 human approvals" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "A2 alerts and A4 digests" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "A3 conversations" })).toBeVisible();
  await expect(page.getByText("Teams A1 approval delivery")).toBeVisible();
  await expect(page.getByText("Teams A2 operational alerts")).toBeVisible();
  await expect(page.getByText("Teams A3 conversations")).toBeVisible();
  await expect(page.getByText("Not observed here").first()).toBeVisible();

  await expect(page.getByRole("heading", { name: "Connect and test Teams Workflows" })).toBeVisible();
  await expect(page.getByText("Binding saved")).toBeVisible();

  const teamsInput = page.getByLabel("Teams Workflows HTTP URL");
  await expect(teamsInput).toHaveValue("");
  await expect(teamsInput).toHaveAttribute("autocomplete", "off");
  await expect(page.getByText(/FDAI never returns the saved URL/)).toBeVisible();
  await teamsInput.fill(webhookUrl);
  await page.getByRole("button", { name: "Save and send test" }).click();

  await expect(page.getByText("Saved and test accepted")).toBeVisible();
  expect(fixture.teamsBody()).toMatchObject({ webhook_url: webhookUrl });
  expect(await page.content()).not.toContain("sig=abcdefghijklmnopqrstuvwxyz012345");

  const slackInput = page.getByLabel("One-time Slack webhook URL");
  await expect(slackInput).toHaveAttribute("type", "password");
  await slackInput.fill(slackWebhookUrl);
  await page.getByRole("button", { name: "Send Slack test" }).click();

  await expect(page.getByText("Accepted", { exact: true })).toBeVisible();
  await expect(slackInput).toHaveValue("");
  expect(fixture.slackBody()).toMatchObject({ webhook_url: slackWebhookUrl });

  for (const selector of ["html", ".settings-route", ".settings-webhook-diagnostic"]) {
    const dimensions = await page.locator(selector).evaluateAll((elements) =>
      elements.map((element) => ({
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
      })),
    );
    for (const element of dimensions) {
      expect(element.scrollWidth).toBeLessThanOrEqual(element.clientWidth);
    }
  }
  if (process.env["FDAI_CAPTURE_SETTINGS_SCREENSHOT"] === "1") {
    await page
      .getByRole("heading", { name: "Connect and test Teams Workflows" })
      .scrollIntoViewIfNeeded();
    await page.screenshot({
      path: test.info().outputPath("settings-teams-workflow.png"),
      fullPage: true,
    });
  }
});
