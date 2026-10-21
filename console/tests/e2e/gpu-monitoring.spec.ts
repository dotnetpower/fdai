import { mkdir, writeFile } from "node:fs/promises";

import { expect, test, type Page, type TestInfo } from "@playwright/test";

async function capture(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  const screenshot = await page.screenshot({ fullPage: true });
  await testInfo.attach(name, { body: screenshot, contentType: "image/png" });
  const root = process.env.FDAI_GPU_MONITORING_VISUAL_CAPTURE_ROOT;
  if (!root) return;
  await mkdir(root, { recursive: true });
  await writeFile(`${root}/${name}.png`, screenshot);
}

async function expectNoOverflow(page: Page): Promise<void> {
  const measured = await page.evaluate(() => {
    const route = document.querySelector(".gpu-monitoring-route")!;
    const main = document.querySelector(".gpu-monitoring-detail");
    return {
      document: {
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      },
      route: {
        clientWidth: route.clientWidth,
        scrollWidth: route.scrollWidth,
      },
      main: {
        clientWidth: main?.clientWidth ?? 0,
        scrollWidth: main?.scrollWidth ?? 0,
      },
      offenders: [...route.querySelectorAll<HTMLElement>("*")]
        .filter((element) => element.scrollWidth > element.clientWidth + 1)
        .slice(0, 10)
        .map((element) => ({
          className: element.className,
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
        })),
    };
  });
  expect(measured.document.scrollWidth).toBeLessThanOrEqual(measured.document.clientWidth + 1);
  expect(measured.route.scrollWidth, JSON.stringify(measured.offenders))
    .toBeLessThanOrEqual(measured.route.clientWidth + 1);
  if (measured.main.clientWidth > 0) {
    expect(measured.main.scrollWidth).toBeLessThanOrEqual(measured.main.clientWidth + 1);
  }
}

test("presents bounded H100 evidence without browser action authority", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const startedAt = Date.now();
  await page.goto("/gpu-monitoring?data=sample&locale=en");

  await expect(page.getByRole("heading", { name: "GPU monitoring" })).toBeVisible();
  expect(Date.now() - startedAt).toBeLessThan(3_000);
  await expect(page.locator(".gpu-monitoring-route .kpi-card")).toHaveCount(4);
  await expect(page.locator(".gpu-device-button")).toHaveCount(1);
  await expect(page.locator(".fd-metric-chart")).toHaveCount(3);
  await expect(page.getByText("NVIDIA H100 NVL").first()).toBeVisible();
  await expect(page.getByText("VRAM pressure").first()).toBeVisible();
  await expect(page.getByText("ops.deallocate-vm")).toBeVisible();
  await expect(page.getByText("Deallocated")).toBeVisible();
  await expect(page.getByText("The Console renders receipts only. It cannot execute or approve the action.")).toBeVisible();
  await page.locator(".gpu-device-button").focus();
  await page.keyboard.press("Space");
  await expect(page.locator(".gpu-device-button")).toHaveAttribute("aria-current", "true");
  await page.locator(".gpu-monitoring-route .kpi-card").first().focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#gpu-inventory$/);
  await expectNoOverflow(page);
  await capture(page, testInfo, "gpu-monitoring-desktop");

  await page.setViewportSize({ width: 993, height: 641 });
  await expectNoOverflow(page);

  await page.setViewportSize({ width: 390, height: 844 });
  const device = page.locator(".gpu-device-button");
  await expect(device).toHaveCSS("min-height", "64px");
  await expect(page.getByText("GPU 및 VRAM 부하")).toHaveCount(0);
  await expectNoOverflow(page);
  await capture(page, testInfo, "gpu-monitoring-mobile");
});

test("preserves Korean content at 320px with enlarged text and forced colors", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 844 });
  await page.emulateMedia({ colorScheme: "dark", forcedColors: "active", reducedMotion: "reduce" });
  await page.goto("/gpu-monitoring?data=sample&locale=ko");
  await page.addStyleTag({
    content: `
      html { font-size: 200% !important; }
      .gpu-monitoring-route * {
        line-height: 1.5 !important;
        letter-spacing: .12em !important;
        word-spacing: .16em !important;
      }
      .gpu-monitoring-route p { margin-bottom: 2em !important; }
    `,
  });

  await expect(page.getByRole("heading", { name: "GPU 모니터링" })).toBeVisible();
  await expect(page.getByText("작업 권한을 부여하지 않습니다.")).toBeVisible();
  await expect(page.locator(".gpu-device-button")).toHaveCSS("min-height", "64px");
  await expectNoOverflow(page);
});

test("keeps absent live GPU evidence explicitly unavailable in Korean", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/gpu-monitoring?locale=ko");

  await expect(page.getByRole("heading", { name: "GPU 모니터링" })).toBeVisible();
  await expect(page.getByText(/인증된 GPU 관측이 실시간 스트림에 도착하지 않았습니다/)).toBeVisible();
  await expect(page.locator(".gpu-monitoring-route .kpi-card")).toHaveCount(0);
  await expectNoOverflow(page);
});
