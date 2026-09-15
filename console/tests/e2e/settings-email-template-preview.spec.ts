import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { expect, test, type Page, type Route } from "@playwright/test";

const templateHtml = readFileSync(
  fileURLToPath(
    new URL("../../../mocks/email-template/incident-opened.html", import.meta.url),
  ),
  "utf8",
);

const runtimeSettings = {
  revision: 1,
  can_manage: false,
  updated_at: null,
  updated_by: null,
  integrations: [
    {
      key: "email",
      source: "operator-service",
      observed: true,
      configured: false,
      ready: false,
      mode: "disabled",
      reason: "Preview only",
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

async function installFixtures(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/runtime/settings") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(runtimeSettings),
      });
      return;
    }
    if (path === "/notification-templates/incident-opened") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          key: "incident-opened",
          subject: "[SEV2] Incident opened - API latency after configuration rollout",
          plain_text: (
            "SEV2 incident opened at 06:03 UTC. Eight signals were correlated. "
            + "No recovery action has run."
          ),
          html: templateHtml,
        }),
      });
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Optional test source unavailable." }),
    });
  };
  await page.route("**/api/**", handle);
  await page.route("**/runtime/**", handle);
  await page.route("**/notification-templates/**", handle);
}

test.describe("Incident email template preview", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await installFixtures(page);
  });

  for (const viewport of [
    { label: "desktop", width: 1440, height: 900 },
    { label: "constrained", width: 993, height: 641 },
    { label: "mobile", width: 390, height: 844 },
  ]) {
    test(`matches the reviewed specimen at ${viewport.label} width`, async ({
      page,
    }, testInfo) => {
      await page.setViewportSize(viewport);
      await page.goto("/settings/integrations");

      const preview = page.locator(".settings-email-template");
      const header = preview.locator(".settings-email-template-head");
      const frame = preview.locator(".settings-email-template-frame");
      await expect(preview).toBeVisible();
      await expect(header.getByText(
        "[SEV2] Incident opened - API latency after configuration rollout",
        { exact: true },
      )).toBeVisible();
      await expect(frame).toHaveAttribute("sandbox", "");
      await expect(
        page.frameLocator(".settings-email-template-frame").getByRole("heading", {
          name: "API latency increased after a configuration rollout.",
        }),
      ).toBeVisible();

      const geometry = await frame.evaluate((element) => {
        const frameBox = element.getBoundingClientRect();
        const headerBox = element.previousElementSibling?.getBoundingClientRect();
        const route = element.closest(".settings-route");
        return {
          frameWidth: frameBox.width,
          frameLeft: frameBox.left,
          headerWidth: headerBox?.width ?? null,
          headerLeft: headerBox?.left ?? null,
          borderRadius: getComputedStyle(element).borderRadius,
          routeContained: route ? route.scrollWidth <= route.clientWidth : false,
          documentContained:
            document.documentElement.scrollWidth <= document.documentElement.clientWidth,
        };
      });
      expect(geometry.frameWidth).toBeLessThanOrEqual(760);
      if (viewport.label === "desktop") expect(geometry.frameWidth).toBe(760);
      expect(geometry.headerWidth).toBe(geometry.frameWidth);
      expect(geometry.headerLeft).toBe(geometry.frameLeft);
      expect(geometry.borderRadius).toBe("2px");
      expect(geometry.routeContained).toBe(true);
      expect(geometry.documentContained).toBe(true);

      const innerGeometry = await page
        .frameLocator(".settings-email-template-frame")
        .locator("html")
        .evaluate((element) => {
          const paper = element.querySelector(".wrap")?.getBoundingClientRect();
          return {
            contained: element.scrollWidth <= element.clientWidth,
            paperWidth: paper?.width ?? null,
          };
        });
      expect(innerGeometry.contained).toBe(true);
      if (viewport.label === "desktop") {
        expect(innerGeometry.paperWidth).toBe(640);
      } else {
        expect(innerGeometry.paperWidth).toBeLessThanOrEqual(geometry.frameWidth);
      }

      await preview.screenshot({
        path: testInfo.outputPath(`incident-email-${viewport.label}.png`),
      });
    });
  }
});
