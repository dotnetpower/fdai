import { expect, test, type Page, type Route } from "@playwright/test";

function json(route: Route, payload: unknown): Promise<void> {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

function auditItem(seq: number, recordedAt: string) {
  return {
    seq,
    event_id: `event-${seq}`,
    correlation_id: `corr-${seq}`,
    actor: seq === 1 ? "Forseti" : "Huginn",
    action_kind: seq === 1 ? "risk_gate.decision" : "inventory.refresh",
    mode: "shadow",
    entry: {
      summary: seq === 1
        ? "Verified rollback evidence before judgment."
        : "Collected the latest inventory evidence.",
      outcome: "approved",
    },
    entry_hash: `hash-${seq}`,
    previous_hash: `hash-${seq - 1}`,
    recorded_at: recordedAt,
  };
}

async function installActivityLogFixture(page: Page): Promise<void> {
  let auditReads = 0;
  await page.route("**/system/data-sources*", (route) => json(route, {
    surface: "read-data-sources",
    sources: [{
      key: "agent-activity-log-test",
      source: "deterministic browser fixture",
      routes: ["/audit", "/agents/activity", "/agents/stream"],
      availability: "available",
      configured: true,
      reachable: true,
      authoritative: true,
      durable: true,
      synthetic: true,
      reason: null,
      last_observed_at: "2026-09-17T00:00:00Z",
    }],
  }));
  await page.route("**/audit*", (route) => {
    auditReads += 1;
    const items = auditReads === 1
      ? [auditItem(1, "2026-09-17T00:00:00Z")]
      : [
          auditItem(2, "2026-09-17T00:00:01Z"),
          auditItem(1, "2026-09-17T00:00:00Z"),
        ];
    return json(route, { items, next_cursor: null });
  });
  await page.route("**/agents/activity*", (route) => json(route, {
    items: [],
    snapshot_at: "2026-09-17T00:00:00Z",
    source: "durable-operational-projection",
  }));
  await page.route("**/agents/stream*", (route) => route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: "",
  }));
}

test("highlights only newly appended activity and keeps log text readable", async ({ page }) => {
  await installActivityLogFixture(page);
  await page.goto("/agent-activity");

  const rows = page.locator(".aa-log-row");
  await expect(rows).toHaveCount(1);
  await expect(page.locator(".aa-log-row.is-new-activity")).toHaveCount(0);

  const refresh = page.getByRole("button", { name: "Refresh history" });
  await refresh.focus();
  await page.keyboard.press("Enter");
  const highlighted = page.locator(".aa-log-row.is-new-activity");
  await expect(highlighted).toHaveCount(1);
  await expect(refresh).toBeFocused();
  await expect(refresh).toBeFocused();
  await expect(highlighted).toContainText("Collected the latest inventory evidence.");
  const highlightStyle = await highlighted.evaluate((row) => {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const context = canvas.getContext("2d");
    if (context === null) throw new Error("Canvas 2D context is unavailable");
    const sample = (...colors: string[]): readonly [number, number, number] => {
      context.clearRect(0, 0, 1, 1);
      colors.forEach((color) => {
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
      });
      const [red, green, blue] = context.getImageData(0, 0, 1, 1).data;
      return [red!, green!, blue!];
    };
    const luminance = (rgb: readonly number[]): number => {
      const channels = rgb.map((value) => {
        const channel = value / 255;
        return channel <= 0.04045
          ? channel / 12.92
          : ((channel + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
    };
    const panel = row.closest<HTMLElement>(".aa-agent-log");
    const detail = row.querySelector<HTMLElement>(".aa-log-detail small");
    if (panel === null || detail === null) throw new Error("Expected log presentation is missing");
    const overlay = getComputedStyle(row, "::after");
    const backgroundLuminance = luminance(sample(
      getComputedStyle(panel).backgroundColor,
      overlay.backgroundColor,
    ));
    const textLuminance = luminance(sample(getComputedStyle(detail).color));
    return {
      animationDuration: overlay.animationDuration,
      backgroundColor: overlay.backgroundColor,
      contrast:
        (Math.max(backgroundLuminance, textLuminance) + 0.05) /
        (Math.min(backgroundLuminance, textLuminance) + 0.05),
    };
  });
  expect(highlightStyle).toEqual({
    animationDuration: "3s",
    backgroundColor: expect.not.stringMatching(/rgba?\\([^)]*, 0\\)$/),
    contrast: expect.any(Number),
  });
  expect(highlightStyle.contrast).toBeGreaterThanOrEqual(4.5);

  const metrics = await page.locator(".aa-agent-log").evaluate((panel) => {
    const textElements = [...panel.querySelectorAll<HTMLElement>("*")].filter(
      (element) =>
        element.children.length === 0 &&
        Boolean(element.textContent?.trim()) &&
        getComputedStyle(element).display !== "none",
    );
    const sizes = textElements.map((element) =>
      Number.parseFloat(getComputedStyle(element).fontSize)
    );
    return {
      minimumFontSize: Math.min(...sizes),
      documentOverflow:
        document.documentElement.scrollWidth - document.documentElement.clientWidth,
      panelOverflow: panel.scrollWidth - panel.clientWidth,
    };
  });
  expect(metrics.minimumFontSize).toBeGreaterThanOrEqual(11);
  expect(metrics.documentOverflow).toBeLessThanOrEqual(0);
  expect(metrics.panelOverflow).toBeLessThanOrEqual(0);
  await expect(highlighted).toHaveCount(0, { timeout: 4_000 });
});

test("uses a static bounded cue when reduced motion is requested", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await installActivityLogFixture(page);
  await page.goto("/agent-activity");
  await expect(page.locator(".aa-log-row")).toHaveCount(1);

  await page.getByRole("button", { name: "Refresh history" }).click();
  const highlighted = page.locator(".aa-log-row.is-new-activity");
  await expect(highlighted).toHaveCount(1);
  expect(await highlighted.evaluate((row) => ({
    animationName: getComputedStyle(row, "::after").animationName,
    backgroundColor: getComputedStyle(row, "::after").backgroundColor,
  }))).toEqual({
    animationName: "none",
    backgroundColor: expect.not.stringMatching(/rgba?\\([^)]*, 0\\)$/),
  });
  await expect(highlighted).toHaveCount(0, { timeout: 4_000 });
});
