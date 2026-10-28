import { expect, test, type Page, type Route } from "@playwright/test";

const NOW = new Date().toISOString();

function frame(event: string | null, id: string, data: unknown): string {
  return `${event ? `event: ${event}\n` : ""}id: ${id}\ndata: ${JSON.stringify(data)}\n\n`;
}

function stage(
  eventId: string,
  name: string,
  phase: string,
  detail: Record<string, unknown>,
  error?: string,
) {
  return {
    event_id: eventId, correlation_id: `corr-${eventId}`, stage: name, phase,
    source: "runtime-observed", ts: NOW, detail, ...(error ? { error } : {}),
  };
}

const activity = {
  type: "agent.operational-activity",
  schema_version: "1.1.0",
  idempotency_key: "observation:metrics:unavailable",
  activity_id: "observation:metrics:campaign-1:degraded",
  kind: "observation",
  status: "degraded",
  owner_agent: "Heimdall",
  producer: "observation-campaign-job",
  observation_domain: "metrics",
  source: "metrics",
  freshness: "stale",
  evidence_count: 0,
  duration_ms: 30_000,
  correlation_id: "campaign-1",
  observed_at: NOW,
  reason_codes: ["source_timeout", "source_stale"],
  execution_authority: false,
};

const stream = [
  frame("hello", "0", {}),
  frame("source", "1", { status: "ready", source: "runtime-observed", ts: NOW }),
  frame(null, "2", stage("evt-approved", "ingest", "done", { mode: "shadow" })),
  frame(null, "3", stage("evt-approved", "gate", "done", { gate_decision: "auto", mode: "shadow", resource_type: "compute.vm" })),
  frame(null, "4", stage("evt-approved", "audit", "done", { outcome: "approved", decision: "auto", mode: "shadow" })),
  frame(null, "5", stage("evt-reported", "gate", "done", {
    gate_decision: "hil", reason: "Blast radius exceeds one resource.", scope: "subscription", resource_type: "compute.vm",
  })),
  frame("activity", "6", activity),
].join("");

async function install(page: Page): Promise<void> {
  const json = (route: Route, body: unknown) =>
    route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  await page.route("**/system/data-sources*", (route) => json(route, {
    surface: "read-data-sources",
    sources: [{
      key: "live-absence-test", source: "deterministic browser fixture", routes: ["/live/stream"],
      availability: "available", configured: true, reachable: true, authoritative: true,
      durable: true, synthetic: true, reason: null, last_observed_at: NOW,
    }],
  }));
  await page.route("**/live/stream*", (route) => route.fulfill({
    status: 200, contentType: "text/event-stream", body: stream,
  }));
}

for (const locale of ["en", "ko"] as const) {
  test(`Live cards explain absent values by cause (${locale})`, async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Desktop is validated before narrow layouts.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await install(page);
    await page.goto(`/live?locale=${locale}&data=live`);
    const words = locale === "ko"
      ? { noReason: "이 결정과 함께 보고된 사유 없음", noScope: "이 이벤트가 범위를 보고하지 않음", timeout: "소스 읽기 시간 초과", reported: "Blast radius exceeds one resource." }
      : { noReason: "No reason was reported with this decision", noScope: "Scope not reported by this event", timeout: "Source read timed out", reported: "Blast radius exceeds one resource." };

    const approved = page.locator(".live-tile").filter({ hasText: "compute.vm" }).filter({ hasText: words.noReason });
    await expect(approved).toHaveCount(1);
    await expect(approved).toContainText(words.noScope);
    await expect(page.locator(".live-tile").filter({ hasText: words.reported })).toContainText("subscription");
    await expect(page.locator(".live-tile").filter({ hasText: locale === "ko" ? "관찰되지 않음" : "Not observed" })).toHaveCount(0);

    const observation = page.locator(".live-observation-item");
    await expect(observation).toContainText(words.timeout);
    await expect(observation).toContainText(locale === "ko" ? "외 1건" : "+1 more");

    for (const viewport of [
      { width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 },
    ]) {
      await page.setViewportSize(viewport);
      expect(await page.evaluate(() =>
        document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
      await page.locator(".live-tile").first().scrollIntoViewIfNeeded();
      expect(await page.locator(".live-work-card").evaluateAll((cards) =>
        cards.every((card) => card.scrollWidth <= card.clientWidth))).toBe(true);
      await page.locator(".live-work-card").first().locator("xpath=ancestor::section[1]")
        .screenshot({ path: testInfo.outputPath(`live-absence-${locale}-${viewport.width}.png`) });
    }

    await observation.click();
    const detail = page.locator("#live-observation-detail-panel");
    await expect(detail).toContainText(words.timeout);
    await expect(detail.locator("code", { hasText: "source_stale" })).toBeVisible();
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: testInfo.outputPath(`live-absence-detail-${locale}.png`), animations: "disabled" });
  });
}
