import { expect, test, type Page, type Route } from "@playwright/test";

const runtimeSettings = {
  revision: 2,
  can_manage: true,
  updated_at: null,
  updated_by: null,
  integrations: [
    {
      key: "notification-bindings",
      configured: false,
      ready: false,
      mode: "disabled",
      reason: "not configured",
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
    if (path === "/runtime/integrations/teams-workflow/test") {
      teamsBody = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          request_id: "teams-workflow-test-00000000-0000-0000-0000-000000000000",
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

test("sends transient Teams and Slack tests without retaining either URL", async ({ page }) => {
  if (process.env["FDAI_SETTINGS_VIEWPORT"] === "constrained") {
    await page.setViewportSize({ width: 993, height: 641 });
  }
  const fixture = await installFixture(page);
  await page.goto("/settings/integrations");

  const teamsInput = page.getByLabel("One-time webhook URL");
  await expect(teamsInput).toHaveAttribute("type", "password");
  await expect(teamsInput).toHaveAttribute("autocomplete", "off");
  await teamsInput.fill(webhookUrl);
  await page.getByRole("button", { name: "Send test card" }).click();

  await expect(teamsInput).toHaveValue("");
  expect(fixture.teamsBody()).toMatchObject({ webhook_url: webhookUrl });

  const slackInput = page.getByLabel("One-time Slack webhook URL");
  await expect(slackInput).toHaveAttribute("type", "password");
  await expect(slackInput).toHaveAttribute("autocomplete", "off");
  await slackInput.fill(slackWebhookUrl);
  await page.getByRole("button", { name: "Send Slack test" }).click();

  await expect(page.getByText("Accepted", { exact: true })).toHaveCount(2);
  await expect(slackInput).toHaveValue("");
  expect(fixture.slackBody()).toMatchObject({ webhook_url: slackWebhookUrl });

  for (const selector of ["html", ".settings-route", ".settings-webhook-diagnostic"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }
  if (process.env["FDAI_CAPTURE_SETTINGS_SCREENSHOT"] === "1") {
    await page.screenshot({
      path: test.info().outputPath("settings-teams-workflow.png"),
      fullPage: true,
    });
  }
});
