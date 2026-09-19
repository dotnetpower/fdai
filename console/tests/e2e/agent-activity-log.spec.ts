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

function operationalActivity(index: number) {
  const identity = `inventory.scan:load-${index}:completed`;
  return {
    type: "agent.operational-activity",
    schema_version: "1.0.0",
    activity_id: identity,
    idempotency_key: identity,
    kind: "inventory.scan",
    status: "completed",
    owner_agent: "Huginn",
    producer: "inventory-sync-job",
    observation_domain: null,
    observed_at: new Date(Date.UTC(2026, 8, 17, 0, 0, index)).toISOString(),
    source: "inventory",
    freshness: "fresh",
    evidence_count: 1,
    duration_ms: 1,
    correlation_id: `load-${index}`,
    reason_codes: [],
    execution_authority: false,
  };
}

async function installActivityLogFixture(
  page: Page,
  streamBody = "",
): Promise<void> {
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
    body: streamBody,
  }));
}

function handlerActivityStream(): string {
  const base = {
    type: "agent.state",
    agent: "Huginn",
    ts: "2026-09-17T00:01:00Z",
    activity_id: "handler:example",
    activity_correlation_id: "correlation-1",
    topic: "fdai.change.events",
    event_id: "event-1",
    event_type: "inventory.resource_changed",
    resource_ref: "scope:example/resource-group/example/providers/compute/vm-example",
    resource_name: "vm-example",
    resource_type: "compute-vm",
    started_at: "2026-09-17T00:00:59.958Z",
    source: "runtime-observed",
  };
  return [
    { ...base, state: "collecting", correlation_id: "correlation-1", phase: "started", detail: "Processing fdai.change.events" },
    { ...base, state: "watching", correlation_id: null, phase: "completed", detail: "Processed fdai.change.events", completed_at: "2026-09-17T00:01:00Z", duration_ms: 42 },
  ].map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join("");
}

async function installBusyActivityLogFixture(page: Page): Promise<void> {
  const retained = Array.from({ length: 500 }, (_, index) => operationalActivity(index));
  const live = Array.from({ length: 120 }, (_, index) => operationalActivity(index + 500));
  const streamBody = live.map((event) =>
    `id: ${event.activity_id}\nevent: message\ndata: ${JSON.stringify(event)}\n\n`
  ).join("");

  await page.route("**/system/data-sources*", (route) => json(route, {
    surface: "read-data-sources",
    sources: [{
      key: "agent-activity-load-test",
      source: "deterministic browser fixture",
      routes: ["/audit", "/agents/activity", "/agents/stream"],
      availability: "available",
      configured: true,
      reachable: true,
      authoritative: true,
      durable: true,
      synthetic: true,
      reason: null,
      last_observed_at: "2026-09-17T00:10:19Z",
    }],
  }));
  await page.route("**/audit*", (route) => json(route, {
    items: [auditItem(1, "2026-09-17T00:00:00Z")],
    next_cursor: null,
  }));
  await page.route("**/agents/activity*", (route) => json(route, {
    items: retained,
    snapshot_at: "2026-09-17T00:08:19Z",
    source: "durable-operational-projection",
  }));
  await page.route("**/agents/stream*", (route) => route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: streamBody,
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

test("shows one resource-first row for a completed handler activity", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installActivityLogFixture(page, handlerActivityStream());
  await page.goto("/agent-activity");

  const resource = page.locator(".aa-log-detail code", { hasText: "vm-example" });
  await expect(resource).toHaveCount(1);
  const row = resource.locator("xpath=ancestor::*[contains(@class, 'aa-log-row')]");
  await expect(row).toContainText("inventory.resource_changed");
  await expect(row).toContainText("compute-vm - completed - 42 ms - fdai.change.events");
  await resource.hover();
  await expect(page.getByRole("tooltip")).toContainText(
    "scope:example/resource-group/example/providers/compute/vm-example",
  );

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    expect(await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth
    )).toBeLessThanOrEqual(0);
  }
});

test("keeps pointer and search controls responsive during a bounded activity burst", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installBusyActivityLogFixture(page);
  await page.goto("/agent-activity");

  const rows = page.locator(".aa-log-row");
  await expect(page.locator(".aa-log-grid")).toHaveAttribute("aria-rowcount", "602");
  expect(await rows.count()).toBeLessThan(40);
  await expect(rows.first()).toHaveAttribute("data-activity-id", "inventory.scan:load-619:completed");

  const columns = page.getByRole("button", { name: "Columns" });
  const menu = page.getByRole("menu");
  const clickStarted = await page.evaluate(() => performance.now());
  await columns.click();
  await expect(menu).toBeVisible();
  const clickDuration = await page.evaluate((started) => performance.now() - started, clickStarted);
  expect(clickDuration).toBeLessThan(1_000);

  const inventoryLane = page.locator(".aa-log-lanes button").nth(1);
  await inventoryLane.click();
  await expect(inventoryLane).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".aa-log-grid")).toHaveAttribute("aria-rowcount", "601");
  expect(await rows.count()).toBeLessThan(40);

  const search = page.getByRole("searchbox", { name: "Find" });
  const searchStarted = await page.evaluate(() => performance.now());
  await search.fill("load-619");
  await expect(rows).toHaveCount(1);
  const searchDuration = await page.evaluate((started) => performance.now() - started, searchStarted);
  expect(searchDuration).toBeLessThan(1_000);
  await expect(rows.first()).toContainText("load-619");
});

type ActivityTestWindow = typeof window & {
  activityTestStream: ReadableStreamDefaultController<Uint8Array>;
};

async function installControlledActivityStream(page: Page): Promise<void> {
  await installBusyActivityLogFixture(page);
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = (input, init) => {
      const url = input instanceof Request ? input.url : String(input);
      if (new URL(url, location.origin).pathname.endsWith("/agents/stream")) {
        return Promise.resolve(new Response(new ReadableStream<Uint8Array>({
          start(controller) {
            (window as ActivityTestWindow).activityTestStream = controller;
          },
        }), { headers: { "Content-Type": "text/event-stream" } }));
      }
      return originalFetch(input, init);
    };
  });
}

test("keeps reading stable across retention eviction and resumes newest activity on request", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installControlledActivityStream(page);
  await page.goto("/agent-activity");
  const grid = page.locator(".aa-log-grid");
  const scroll = page.locator(".aa-log-scroll");
  const rows = page.locator(".aa-log-row");
  await expect(grid).toHaveAttribute("aria-rowcount", "502");
  await expect(page.locator(".aa-log-tail")).toHaveCount(0);
  await expect(rows.first()).toHaveAttribute("data-activity-id", "inventory.scan:load-499:completed");

  await scroll.evaluate((element) => { element.scrollTop = 500; });
  let readingOffset = -1;
  await expect.poll(async () => {
    const offset = await scroll.evaluate((element) => element.scrollTop);
    const settled = readingOffset === offset && offset > 24;
    readingOffset = offset;
    return settled;
  }).toBe(true);
  const anchor = await rows.evaluateAll((elements) => {
    const container = document.querySelector(".aa-log-scroll")!.getBoundingClientRect();
    const element = elements.find((candidate) => candidate.getBoundingClientRect().top >= container.top + 32)!;
    return { id: element.getAttribute("data-log-id"), top: element.getBoundingClientRect().top };
  });
  await page.evaluate((events) => {
    const controller = (window as ActivityTestWindow).activityTestStream;
    controller.enqueue(new TextEncoder().encode(events.map((event) =>
      `data: ${JSON.stringify(event)}\n\n`
    ).join("")));
  }, Array.from({ length: 150 }, (_, index) => operationalActivity(index + 500)));

  const newEvents = page.getByRole("button", { name: "150 new events" });
  await expect(newEvents).toBeVisible();
  await expect(grid).toHaveAttribute("aria-rowcount", "502");
  expect(await scroll.evaluate((element) => element.scrollTop)).toBe(readingOffset);
  expect(await page.locator(`[data-log-id="${anchor.id}"]`).evaluate((element) =>
    element.getBoundingClientRect().top
  )).toBe(anchor.top);

  await newEvents.focus();
  await page.keyboard.press("Enter");
  await expect(newEvents).toHaveCount(0);
  await expect(scroll).toBeFocused();
  await expect(grid).toHaveAttribute("aria-rowcount", "602");
  await expect(rows.first()).toHaveAttribute("data-activity-id", "inventory.scan:load-649:completed");
  expect(await scroll.evaluate((element) => element.scrollTop)).toBe(0);
  expect(await rows.count()).toBeLessThan(40);

  await page.evaluate((event) => {
    (window as ActivityTestWindow).activityTestStream.enqueue(
      new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`),
    );
  }, { ...operationalActivity(650), observed_at: "2026-09-17T00:10:50.127Z" });
  await expect(rows.first()).toHaveAttribute("data-activity-id", "inventory.scan:load-650:completed");
  await expect(rows.first().locator("time")).toContainText(/\d{2}:\d{2}:\d{2}\.127/);
  await expect(page.locator(".aa-log-new-events")).toHaveCount(0);

  await scroll.press("End");
  const auditLink = page.locator('.aa-log-row a[href*="corr-1"]');
  await expect(auditLink).toBeVisible();
  await auditLink.focus();
  await page.evaluate((event) => {
    (window as ActivityTestWindow).activityTestStream.enqueue(
      new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`),
    );
  }, operationalActivity(651));
  await expect(page.getByRole("button", { name: "1 new events" })).toBeVisible();
  await expect(auditLink).toBeFocused();

  await page.getByRole("searchbox", { name: "Find" }).fill("load-651");
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("load-651");
  await expect(page.locator(".aa-log-new-events")).toHaveCount(0);
  expect(await scroll.evaluate((element) => element.scrollTop)).toBe(0);
});

for (const locale of ["en", "ko"] as const) {
  test(`keeps the virtual activity window readable and operable in ${locale}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installControlledActivityStream(page);
    await page.goto(`/agent-activity?locale=${locale}`);
    const grid = page.locator(".aa-log-grid");
    const scroll = page.locator(".aa-log-scroll");
    await expect(grid).toHaveAttribute("aria-rowcount", "502");
    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 993, height: 641 },
      { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      const time = page.locator(".aa-log-row time").first();
      await expect(time).toContainText(/\d{2}:\d{2}:\d{2}\.\d{3}/);
      expect(await page.locator(".aa-log-row").count()).toBeLessThan(40);
      const geometry = await page.locator(".aa-agent-log").evaluate((panel) => ({
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        panelOverflow: panel.scrollWidth - panel.clientWidth,
        timeOverflow: [...panel.querySelectorAll("time")].some((element) => element.scrollWidth > element.clientWidth),
      }));
      expect(geometry).toEqual({ documentOverflow: 0, panelOverflow: 0, timeOverflow: false });
      await page.screenshot({ path: testInfo.outputPath(`activity-${locale}-${viewport.width}.png`) });
    }

    await scroll.evaluate((element) => { element.scrollTop = 500; });
    await expect.poll(() => scroll.evaluate((element) => element.scrollTop)).toBeGreaterThan(24);
    await page.evaluate((event) => {
      (window as ActivityTestWindow).activityTestStream.enqueue(
        new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`),
      );
    }, operationalActivity(500));
    const pending = page.getByRole("button", { name: locale === "ko" ? "새 이벤트 1건" : "1 new events" });
    await expect(pending).toBeVisible();
    const target = await pending.boundingBox();
    expect(target!.height).toBeGreaterThanOrEqual(44);
    expect(target!.width).toBeGreaterThanOrEqual(44);
    await pending.click();
    await expect(page.locator(".aa-log-row").first()).toHaveAttribute("data-activity-id", "inventory.scan:load-500:completed");

    const fullscreen = page.locator(".aa-log-actions button[aria-pressed]");
    await fullscreen.click();
    await expect(fullscreen).toHaveAttribute("aria-pressed", "true");
    await fullscreen.click();
    await expect(fullscreen).toHaveAttribute("aria-pressed", "false");
    await expect(fullscreen).toBeFocused();
    await expect(page.locator(".aa-log-tail")).toHaveCount(0);
  });
}
