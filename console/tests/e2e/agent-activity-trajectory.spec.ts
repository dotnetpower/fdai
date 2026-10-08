import { expect, test, type Page, type Route } from "@playwright/test";

const change = "corr-change-0412";
const read = "corr-read-0221";

function json(route: Route, payload: unknown): Promise<void> {
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
}

function auditItem(
  seq: number,
  actor: string,
  actionKind: string,
  recordedAt: string,
  correlationId: string | null,
  entry: Record<string, unknown>,
) {
  return {
    seq,
    event_id: `event-${seq}`,
    correlation_id: correlationId,
    actor,
    action_kind: actionKind,
    mode: "shadow",
    entry,
    entry_hash: `${String(seq).padStart(4, "0")}aa11bb22cc33dd44ee55ff66`,
    previous_hash: `${String(seq - 1).padStart(4, "0")}aa11bb22cc33dd44ee55ff66`,
    recorded_at: recordedAt,
  };
}

async function installTrajectoryFixture(page: Page): Promise<void> {
  await page.route("**/system/data-sources*", (route) => json(route, {
    surface: "read-data-sources",
    sources: [{
      key: "agent-activity-trajectory-test",
      source: "deterministic browser fixture",
      routes: ["/audit", "/agents/activity", "/agents/stream"],
      availability: "available",
      configured: true,
      reachable: true,
      authoritative: true,
      durable: true,
      synthetic: true,
      reason: null,
      last_observed_at: "2026-09-17T00:30:00Z",
    }],
  }));
  await page.route("**/audit*", (route) => json(route, {
    items: [
      auditItem(9, "Heimdall", "observation.recorded", "2026-09-17T00:31:00Z", null, { summary: "Uncorrelated observation" }),
      auditItem(6, "Var", "hil.requested", "2026-09-17T00:24:03Z", change, {
        summary: "Approval request recorded as pending.",
        outcome: "hil_pending",
      }),
      auditItem(5, "Forseti", "risk_gate.evaluated", "2026-09-17T00:20:28Z", change, {
        summary: "Risk class high; human approval required.",
        outcome: "hil",
        tier: "t1",
        reason: "Blast radius exceeds one resource.",
        conversation: [{ from: "Forseti", to: "Var", text: "Current human approval is required." }],
      }),
      auditItem(4, "Heimdall", "inventory.current_state.read", "2026-09-17T00:20:21Z", change, {
        summary: "Three of four sources returned fresh records.",
        started_at: "2026-09-17T00:20:19.600Z",
        outputs: { records: "3", stale: "metrics" },
        resource_ref: "example-workload",
      }),
      auditItem(3, "Huginn", "event.normalized", "2026-09-17T00:20:19Z", change, {
        summary: "Change request normalized with its original event time.",
        duration_ms: 18,
        inputs: { event_type: "change.requested", resource: "example-workload" },
      }),
      auditItem(2, "Bragi", "read.answer-recorded", "2026-09-17T00:10:08Z", read, {
        summary: "Read-only answer recorded.",
        outcome: "completed",
      }),
      auditItem(1, "Heimdall", "read.graph-queried", "2026-09-17T00:10:03Z", read, {
        summary: "Six direct relationships returned.",
        duration_ms: 4200,
      }),
    ],
    next_cursor: null,
  }));
  await page.route("**/agents/activity*", (route) => json(route, {
    items: [],
    snapshot_at: "2026-09-17T00:31:00Z",
    source: "durable-operational-projection",
  }));
  await page.route("**/agents/stream*", (route) => route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: "",
  }));
}

for (const locale of ["en", "ko"] as const) {
  test(`renders audit trajectories step by step and keeps legacy Waterfall links in ${locale}`, async ({
    page,
  }, testInfo) => {
    const mobile = testInfo.project.name === "mobile-chromium";
    if (!mobile) {
      await page.setViewportSize(locale === "en" ? { width: 1440, height: 900 } : { width: 993, height: 641 });
    }
    await installTrajectoryFixture(page);
    await page.goto(`/agent-activity?view=waterfall&step=5&window=1h&locale=${locale}`);

    const view = page.locator(".aa-trajectories");
    await expect(view).toBeVisible();
    await expect(page.getByRole("button", { name: locale === "ko" ? "Trajectories" : "Trajectories", exact: true }))
      .toHaveAttribute("aria-pressed", "true");
    await expect(page.getByRole("button", { name: /^Waterfall$|^워터폴$/ })).toHaveCount(0);
    await expect(view.locator(".tj-item")).toHaveCount(2);
    await expect(view.locator(".tj-source")).toContainText(locale === "ko" ? "1건" : "1 uncorrelated");

    const detail = view.locator("#aa-trajectory-detail");
    await expect(detail.locator(".tj-eyebrow code")).toHaveText(change);
    await expect(detail.locator("h2")).toHaveText("Change request normalized with its original event time.");
    await expect(detail.locator(".tj-route li")).toHaveCount(4);
    await expect(detail.locator('.tj-phases [data-phase="authorization"]')).toHaveAttribute("data-state", "attention");
    await expect(detail.locator('.tj-phases [data-phase="execution"]')).toHaveAttribute("data-state", "unrecorded");
    await expect(detail.locator(".tj-step")).toHaveCount(4);
    await expect(detail.locator('details[data-step-seq="5"]')).toHaveAttribute("open", "");
    await expect(detail.locator('details[data-step-seq="5"] .tj-step-body')).toContainText("Blast radius exceeds one resource.");
    await expect(detail.locator(".tj-handoff").filter({ hasText: "Current human approval is required." }))
      .toHaveCount(1);
    await expect(detail.locator(".tj-handoff.is-transition")).toHaveCount(2);

    const markers = detail.locator(".tj-mark");
    await expect(markers).toHaveCount(4);
    await markers.nth(1).click();
    await expect(detail.locator('details[data-step-seq="4"]')).toHaveAttribute("open", "");
    await expect(detail.locator('details[data-step-seq="4"] .tj-step-body')).toContainText("example-workload");

    if (!mobile) {
      await view.locator(".tj-lane-label").nth(2).hover();
      await expect(page.getByRole("tooltip")).toContainText("Forseti");
      await page.mouse.move(0, 0);
      const lastMarker = markers.last();
      await lastMarker.hover();
      const tooltip = page.getByRole("tooltip");
      await expect(tooltip).toContainText("Var");
      await expect(tooltip).toContainText("hil_pending");
      const markerBox = (await lastMarker.boundingBox())!;
      const tipBox = (await tooltip.boundingBox())!;
      expect(Math.abs(tipBox.y + tipBox.height - markerBox.y)).toBeLessThanOrEqual(24);
      expect(tipBox.x).toBeLessThanOrEqual(markerBox.x + markerBox.width);
      expect(tipBox.x + tipBox.width).toBeGreaterThanOrEqual(markerBox.x);
      const clipped = await view.locator(".tj-lane-label > span:last-child").evaluateAll((labels) =>
        labels.filter((label) => label.scrollWidth > label.clientWidth + 1 || label.scrollHeight > label.clientHeight + 1).length);
      expect(clipped).toBe(0);
    }

    const geometry = await page.evaluate(() => {
      const main = document.querySelector("main")!;
      const panel = document.querySelector<HTMLElement>("#aa-trajectory-detail")!.getBoundingClientRect();
      const short = [...document.querySelectorAll<HTMLElement>(".aa-trajectories button")]
        .filter((element) => element.checkVisibility())
        .filter((element) => element.getBoundingClientRect().height < 43)
        .map((element) => element.className || element.textContent || "");
      const mainRight = main.getBoundingClientRect().right;
      const offenders = [...main.querySelectorAll<HTMLElement>("*")]
        .filter((element) => element.checkVisibility() && element.getBoundingClientRect().right > mainRight + 1)
        .slice(0, 6)
        .map((element) => `${element.tagName}.${element.getAttribute("class") ?? ""}`);
      return {
        document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        main: main.scrollWidth - main.clientWidth,
        offenders,
        panelRight: panel.right,
        viewport: innerWidth,
        short,
      };
    });
    expect(geometry.document).toBeLessThanOrEqual(0);
    expect(geometry.offenders).toEqual([]);
    expect(geometry.main).toBeLessThanOrEqual(1);
    expect(geometry.panelRight).toBeLessThanOrEqual(geometry.viewport);
    if (mobile) expect(geometry.short).toEqual([]);
    await detail.scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`trajectory-${locale}.png`), fullPage: false });

    await view.locator(".tj-item").filter({ hasText: read }).click();
    await expect(detail.locator(".tj-eyebrow code")).toHaveText(read);
    await expect(page).toHaveURL(new RegExp(`trajectory=${read}`));
    await expect(page).not.toHaveURL(/view=waterfall|step=/);
    await expect(detail.locator(".tj-status-lg")).toHaveAttribute("data-tone", "good");
    await expect(detail.getByRole("link", { name: locale === "ko" ? "Trace 열기" : "Open trace" }))
      .toHaveAttribute("href", `/trace?correlation=${read}`);

    await detail.getByRole("button", { name: locale === "ko" ? "활동 로그에서 보기" : "Show in activity log" }).click();
    await expect(page).toHaveURL(new RegExp(`view=activity.*q=${read}`));
    await expect(page.locator(".aa-agent-log")).toBeVisible();
  });
}
