import { expect, test } from "@playwright/test";

for (const locale of ["en", "ko"] as const) {
  test(`verifies and restores a clearly labeled session receiver (${locale})`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name === "mobile-chromium", "Checks desktop before narrow layouts.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.route("**/api/**", (route) => route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Optional test source unavailable." }),
    }));
    await page.addInitScript(() => {
      class TestNotification {
        static permission = "granted";
        onshow: (() => void) | null = null;
        constructor(_title: string, options?: NotificationOptions) {
          if (options?.tag === "fdai-console-connection-test") {
            const count = Number(sessionStorage.getItem("fdai:test:notification-probes") ?? 0);
            sessionStorage.setItem("fdai:test:notification-probes", String(count + 1));
          } else {
            sessionStorage.setItem("fdai:test:display-tag-length", String(options?.tag?.length));
            sessionStorage.setItem("fdai:test:event-tag-length", String(options?.data?.tag?.length));
          }
          setTimeout(() => this.onshow?.(), 0);
        }
        close() {}
      }
      Object.defineProperty(window, "Notification", { value: TestNotification, configurable: true });
      Object.defineProperty(navigator, "serviceWorker", {
        configurable: true,
        value: { register: () => {
          const count = Number(sessionStorage.getItem("fdai:test:worker-registers") ?? 0);
          sessionStorage.setItem("fdai:test:worker-registers", String(count + 1));
          return Promise.reject(new Error("Fixture worker unavailable"));
        } },
      });
    });
    await page.goto(`/labs?locale=${locale}`);
    const control = page.locator("button.browser-notification-control");
    await expect(control).toHaveAttribute("aria-pressed", "false");
    await control.click();
    await expect(control).toHaveAttribute("aria-pressed", "true");
    await expect(control).toContainText(locale === "ko" ? "세션 대기" : "Ready (session)");
    await control.focus();
    await expect(page.getByRole("tooltip")).toContainText(locale === "ko" ? "세션 알림 표시를 확인했습니다" : "Session notifications are verified");
    expect(await page.evaluate(() => sessionStorage.getItem("fdai:test:notification-probes"))).toBe("1");
    await page.reload();
    await expect(control).toHaveAttribute("aria-pressed", "true");
    await expect(control).toContainText(locale === "ko" ? "세션 대기" : "Ready (session)");
    expect(await page.evaluate(() => sessionStorage.getItem("fdai:test:notification-probes"))).toBe("1");

    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 993, height: 641 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      const bounds = await control.evaluate((element) => {
        const box = element.getBoundingClientRect();
        return {
          overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          left: box.left,
          right: box.right,
        };
      });
      expect(bounds.overflow).toBe(0);
      expect(bounds.left).toBeGreaterThanOrEqual(0);
      expect(bounds.right).toBeLessThanOrEqual(viewport.width);
      await control.focus();
      await expect(control).toBeFocused();
      await control.screenshot({
        path: testInfo.outputPath(`session-notification-${locale}-${viewport.width}.png`),
        animations: "disabled",
      });
    }
    await page.evaluate(async () => {
      const { prepareBrowserNotificationTransport } = await import("/src/browser-notification-transport.ts");
      const receiver = await prepareBrowserNotificationTransport("/");
      const tag = `fdai:${"a".repeat(128)}`;
      await receiver.show("Fixture-only connection check", {
        tag,
        data: {
          channel_id: "console-web",
          tag,
          acknowledgement_token: "0".repeat(32),
          path: "/audit?correlation=fixture-connection-check&data=live",
        },
      });
    });
    expect(await page.evaluate(() => sessionStorage.getItem("fdai:test:display-tag-length"))).toBe("32");
    expect(await page.evaluate(() => sessionStorage.getItem("fdai:test:event-tag-length"))).toBe("133");
    await page.evaluate(() => sessionStorage.removeItem("fdai:console:notification-session-receiver:v1"));
    await page.reload();
    await expect(control).toContainText(locale === "ko" ? "다시 시도" : "Retry");
    await expect(control).toHaveAttribute("aria-pressed", "true");
    const registrations = await page.evaluate(() => sessionStorage.getItem("fdai:test:worker-registers"));
    await page.evaluate(() => {
      window.dispatchEvent(new Event("focus"));
      return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });
    await expect(control).toBeEnabled();
    expect(await page.evaluate(() => sessionStorage.getItem("fdai:test:worker-registers"))).toBe(registrations);
    await control.click();
    await expect(control).toContainText(locale === "ko" ? "세션 대기" : "Ready (session)");
    expect(await page.evaluate(() => sessionStorage.getItem("fdai:test:notification-probes"))).toBe("2");
    await control.click();
    await expect(control).toHaveAttribute("aria-pressed", "false");
    await expect(control).not.toHaveAttribute("title", /Session|세션/);
  });
}
