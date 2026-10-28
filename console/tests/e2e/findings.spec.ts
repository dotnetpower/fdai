import { expect, test, type Page } from "@playwright/test";

const findingId = "a".repeat(64);
function fixtureFinding(version = 1) {
  return {
    finding_id: findingId, notification_version: version,
    notification_reason: version > 1 ? "escalated" : "opened",
    notification_changed_at: "2026-09-01T00:00:00Z",
    resource_ref: "resource:fixture-vm", resource_kind: "virtual_machine",
    signal: "host_cpu", severity: version > 1 ? "critical" : "high", status: "active",
    observation: "Fixture-only CPU threshold exceeded.",
    occurred_at: "2026-09-01T00:00:00Z", evidence_complete: true,
    evidence_state: "complete", evidence_gaps: [], evidence_refs: ["metric:fixture"],
    execution_authority: false, cause_claim_supported: false,
  };
}

async function installFindingFeed(page: Page, items: () => readonly unknown[]) {
  await page.route("**/*", async (route) => {
    const request = new URL(route.request().url());
    if (request.pathname === "/system/data-sources") {
      await route.fulfill({ json: { surface: "read-data-sources", sources: [] } });
    } else if (request.pathname === "/findings") {
      const current = items();
      await route.fulfill({ json: {
        source: "runtime-observed", total_count: current.length,
        next_cursor: null, items: current,
      } });
    } else {
      await route.continue();
    }
  });
}

for (const locale of ["en", "ko"] as const) {
  test(`shows Findings independently from Incidents (${locale})`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop is validated before narrow layouts.");
    await page.setViewportSize({ width: 1440, height: 900 });
    const id = findingId;
    await installFindingFeed(page, () => [fixtureFinding()]);
    await page.goto(`/detection-coverage?locale=${locale}&data=live`);
    const current = page.locator(".current-findings");
    await expect(current).toContainText("resource:fixture-vm");
    await expect(page.locator(".finding-toast")).toBeVisible();
    await page.locator(".finding-toast a").click();
    await expect(page).toHaveURL(new RegExp(`finding=${id}`));
    await expect(current).toContainText("Fixture-only CPU threshold exceeded.");
    await expect(page.locator(".finding-toast")).toHaveCount(0);
    await current.locator("summary").click();
    await expect(current).toContainText("metric:fixture");
    const spacing = await current.evaluate((element) => {
      const heading = element.querySelector("h2")!.getBoundingClientRect();
      const count = element.querySelector("p")!.getBoundingClientRect();
      const link = element.querySelector("li > a")!.getBoundingClientRect();
      return { headingGap: count.top - heading.bottom, linkHeight: link.height };
    });
    expect(spacing.headingGap).toBeLessThanOrEqual(24);
    expect(spacing.linkHeight).toBeGreaterThanOrEqual(44);
    await current.locator("summary").focus();
    await page.keyboard.press("Shift+Tab");
    await expect(current.locator("li > a")).toBeFocused();
    for (const viewport of [
      { width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      expect(await page.evaluate(() =>
        document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
      await expect(current).toBeVisible();
      expect(await current.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      await page.screenshot({ path: testInfo.outputPath(`findings-${locale}-${viewport.width}.png`) });
    }
    await page.goto(`/detection-coverage?locale=${locale}&data=sample`);
    await expect(current).toHaveCount(0);
    await page.locator(".finding-attention > a").click();
    await expect(page).toHaveURL(/[?&]data=live/);
    await expect(current).toContainText("resource:fixture-vm");
  });
}

for (const locale of ["en", "ko"] as const) {
  test(`edits the structured availability policy without widening authority (${locale})`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop is validated before narrow layouts.");
    await page.setViewportSize({ width: 1440, height: 900 });
    const policy = { enabled: false, resource_types: [], max_age_seconds: 300, resources: {} };
    let canManage = true;
    await installFindingFeed(page, () => []);
    await page.route("**/runtime/settings", (route) => route.fulfill({ json: {
      revision: 1, can_manage: canManage, updated_at: null, updated_by: null, integrations: [],
      runtime: {
        environment: "dev", state_store_durable: true, autonomy_default: "shadow",
        pantheon_enabled: true, workflow_observation_enabled: true,
        primary_transport_configured: true, auxiliary_transport_configured: false,
        case_history_configured: false,
      },
      settings: [{
        key: "detection.resource_availability", group: "investigation", value_type: "object",
        environment_value: policy, effective_value: policy, override_value: null,
        minimum: null, maximum: null, options: [], restart_required: false,
        available: true, unavailable_reason: null,
      }],
    } }));
    await page.goto(`/settings/runtime-policies?locale=${locale}`);
    const dialog = page.getByRole("dialog");
    const editor = dialog.getByRole("textbox", {
      name: locale === "ko" ? "리소스 가용성 정책" : "Resource availability policy",
    });
    await expect(editor).toHaveValue(JSON.stringify(policy, null, 2));
    await expect(editor).toBeEnabled();
    const draft = { ...policy, max_age_seconds: 240 };
    await editor.fill(JSON.stringify(draft, null, 2));
    for (const viewport of [
      { width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      await editor.scrollIntoViewIfNeeded();
      await expect(editor).toBeVisible();
      await expect(editor).toBeInViewport();
      expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      expect(await page.evaluate(() =>
        document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
      const dimensions = await editor.boundingBox();
      expect(dimensions!.width).toBeGreaterThan(150);
      if (viewport.width === 390) {
        expect(dimensions!.width).toBeGreaterThan(300);
      }
      const dialogBounds = await dialog.boundingBox();
      expect(dimensions!.y).toBeGreaterThanOrEqual(dialogBounds!.y);
      expect(dimensions!.y + dimensions!.height).toBeLessThanOrEqual(
        dialogBounds!.y + dialogBounds!.height,
      );
      await page.screenshot({ path: testInfo.outputPath(`availability-policy-${locale}-${viewport.width}.png`) });
    }
    canManage = false;
    await page.reload();
    await expect(editor).toBeDisabled();
  });
}

test("delivers a background Finding without an Incident and deduplicates reloads", async ({ page }, testInfo) => {
      test.skip(testInfo.project.name !== "desktop-chromium", "Tests one isolated notification receiver.");
      let version = 0;
      await installFindingFeed(page, () => version ? [fixtureFinding(version)] : []);
      await page.addInitScript(() => {
        Object.defineProperty(document, "hidden", {
          configurable: true, get: () => sessionStorage.getItem("test:hidden") === "yes",
        });
        class FixtureNotification {
          static permission = "granted";
          onshow: (() => void) | null = null;
          onerror: (() => void) | null = null;
          onclick: (() => void) | null = null;
          onclose: (() => void) | null = null;
          constructor(title: string, options: NotificationOptions = {}) {
            const tag: unknown = options.data?.tag;
            if (typeof tag === "string" && tag.startsWith("fdai:finding:")) {
              sessionStorage.setItem("test:delivered", String(Number(sessionStorage.getItem("test:delivered") ?? "0") + 1));
              sessionStorage.setItem("test:display-title", title);
              sessionStorage.setItem("test:display-body", options.body ?? "");
              sessionStorage.setItem("test:display-path", String(options.data?.path));
            }
            setTimeout(() => this.onshow?.(), 0);
          }
          close() {}
        }
        Object.defineProperty(window, "Notification", { configurable: true, value: FixtureNotification });
        Object.defineProperty(navigator, "serviceWorker", {
          configurable: true,
          value: { register: () => Promise.reject(new Error("Fixture-only worker unavailable")) },
        });
      });
      await page.goto("/labs?locale=en&data=live");
      const control = page.locator("button.browser-notification-control");
      await control.click();
      await expect(control).toContainText("Ready (session)");
      version = 1;
      await page.evaluate(() => sessionStorage.setItem("test:hidden", "yes"));
      await page.reload();
      await expect.poll(() => page.evaluate(() => sessionStorage.getItem("test:delivered"))).toBe("1");
      expect(await page.evaluate(() => sessionStorage.getItem("test:display-body"))).not.toContain("fixture-vm");
      expect(await page.evaluate(() => sessionStorage.getItem("test:display-path"))).toContain(`finding=${findingId}`);
      await expect.poll(() => page.evaluate(() =>
        localStorage.getItem(`fdai:console:finding-seen:v1:local:${"a".repeat(64)}`))).toBe("1");
      await page.reload();
      await expect(control).toContainText("Sent");
      expect(await page.evaluate(() => sessionStorage.getItem("test:delivered"))).toBe("1");
      version = 2;
      await page.reload();
      await expect.poll(() => page.evaluate(() => sessionStorage.getItem("test:delivered"))).toBe("2");
});
