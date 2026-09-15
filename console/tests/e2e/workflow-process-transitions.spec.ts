import { expect, test, type Page, type Route } from "@playwright/test";
import { measureHandoverPanel } from "./handover-ui-measurements";

const processRecord = {
  id: "process-1",
  workflow_ref: "review-workflow",
  workflow_version: "1.0.0",
  status: "waiting",
  current_step: "wait_for_evidence",
  target_resource_id: "resource-1",
  started_at: "2026-08-31T00:00:00Z",
  updated_at: "2026-08-31T00:01:00Z",
  correlation_id: "correlation-1",
  revision: 3,
  has_view: false,
};

function control(available: boolean, record = processRecord) {
  if (!available) {
    return {
      schema_version: "1.0.0",
      authoritative: true,
      principal_scoped: true,
      available: false,
      process_revision: 3,
      reason: "Authoritative Workflow catalog projection is unavailable",
      step: null,
      permitted_transitions: [],
      acceptance_is_success: false,
    };
  }
  return {
    schema_version: "1.0.0",
    authoritative: true,
    principal_scoped: true,
    available: true,
    process_revision: 3,
    catalog_revision: "catalog-7",
    mode: "shadow",
    step: {
      id: record.current_step,
      kind: "wait",
      state: "waiting",
      attempt: 1,
      reason: "waiting_for:evidence.updated",
      requirements: {
        wait_for: "evidence.updated",
        timeout_seconds: 300,
        deadline_at: "2026-08-31T00:05:00Z",
      },
    },
    permitted_transitions: [
      {
        id: "resume",
        method: "POST",
        path: `/workflows/${record.id}/resume`,
        expected_revision: 3,
        requires_confirmation: false,
        runtime_recheck: true,
      },
      {
        id: "cancel",
        method: "POST",
        path: `/workflows/${record.id}/cancel`,
        expected_revision: 3,
        requires_confirmation: true,
        runtime_recheck: true,
      },
    ],
    acceptance_is_success: false,
  };
}

async function installFixture(
  page: Page,
  available = true,
  records = [processRecord],
): Promise<{
  denyNext: () => void;
  requestHeaders: () => Record<string, string> | null;
  readCount: () => number;
}> {
  let deny = false;
  let headers: Record<string, string> | null = null;
  let reads = 0;
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/views/process") {
      reads += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          source: "postgresql:process_runtime",
          synthetic: false,
          durable: true,
          principal_scoped: true,
          items: records,
        }),
      });
      return;
    }
    const selected = records.find((record) => path === `/views/process/${record.id}/events`);
    if (selected) {
      reads += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          process: selected,
          events: [{
            event_id: "event-1",
            kind: "step.waiting",
            recorded_at: "2026-08-31T00:01:00Z",
            correlation_id: "correlation-1",
            causation_id: null,
            step_id: "wait_for_evidence",
            attempt: 1,
            payload: {
              step_kind: "wait",
              reason: "waiting_for:evidence.updated",
            },
          }],
          count: 1,
          planning: null,
          investigation: null,
          control: control(available && selected.status === "waiting", selected),
        }),
      });
      return;
    }
    if (path === "/workflows/process-1/resume") {
      headers = route.request().headers();
      await route.fulfill({
        status: deny ? 409 : 202,
        contentType: "application/json",
        body: JSON.stringify(deny
          ? { detail: "Process revision is stale; refresh before retrying" }
          : {
              accepted: true,
              proposal_id: "proposal-1",
              operation: "workflow.resume-request",
              duplicate: false,
            }),
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", body: "{}" });
  };
  await page.route("**/api/**", handle);
  await page.route("**/views/process**", handle);
  await page.route("**/workflows/**", handle);
  return {
    denyNext: () => { deny = true; },
    requestHeaders: () => headers,
    readCount: () => reads,
  };
}

test("renders authoritative Process state and never reports acceptance as success", async ({
  page,
}, testInfo) => {
  const viewport = process.env["FDAI_PROCESS_VIEWPORT"] === "constrained"
    ? { width: 993, height: 641 }
    : testInfo.project.name === "mobile-chromium"
      ? { width: 390, height: 844 }
      : { width: 1440, height: 900 };
  await page.setViewportSize(viewport);
  const fixture = await installFixture(page);
  await page.goto("/processes/process-1");

  await page.locator(".process-detail-section > summary").filter({ hasText: "Permitted next transitions" }).click();
  await expect(page.getByRole("heading", { name: "Permitted next transitions" })).toBeVisible();
  await expect(page.getByText("evidence.updated", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Request resume" }).click();
  await expect(page.locator(".process-control-panel").getByRole("status")).toContainText("Acceptance is not operational success");
  expect(fixture.requestHeaders()?.["if-match"]).toBe("3");
  expect(fixture.requestHeaders()?.["idempotency-key"]).toBe(
    "process:process-1:resume:revision:3",
  );

  fixture.denyNext();
  await page.getByRole("button", { name: "Request resume" }).click();
  await expect(page.getByRole("alert")).toContainText("Process revision is stale");

  for (const selector of ["html", ".process-route", ".process-control-panel"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }
});

test("denies every transition when authoritative control evidence is unavailable", async ({
  page,
}) => {
  await installFixture(page, false);
  await page.goto("/processes/process-1");

  await page.locator(".process-detail-section > summary").filter({ hasText: "Permitted next transitions" }).click();
  await expect(page.getByText(
    "Authoritative Workflow catalog projection is unavailable",
  )).toBeVisible();
  await expect(page.getByRole("button", { name: /Request (resume|cancellation|retry)/ })).toHaveCount(0);
});

test("matches the process workspace hierarchy and preserves selection through provenance", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const records = [
    processRecord,
    { ...processRecord, id: "process-2", target_resource_id: "example-worker", status: "succeeded" },
    { ...processRecord, id: "process-3", target_resource_id: "example-api", status: "failed" },
  ];
  const fixture = await installFixture(page, true, records);
  await page.goto("/processes/process-1");
  await expect(page.locator(".process-status-summary dd strong")).toHaveText(["3", "1", "1", "1"]);
  await expect(page.getByRole("heading", { name: "Process workspace", exact: true })).toBeVisible();
  await expect(page.locator(".process-list-entry[aria-current=page]")).toContainText("resource-1");
  await expect(page.locator(".process-detail")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("process-workspace-desktop.png") });
  const reads = fixture.readCount();
  const provenance = page.getByRole("button", { name: "Provenance", exact: true });
  await provenance.focus();
  await page.keyboard.press("Enter");
  await expect(provenance).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#process-workspace-panel")).toBeHidden();
  await expect(page.locator("#process-provenance-panel")).toContainText("postgresql:process_runtime");
  await expect(page.locator("#process-provenance-panel")).toContainText("Scoped to the signed-in operator");
  await page.keyboard.press("Shift+Tab");
  await expect(page.getByRole("button", { name: "Workspace", exact: true })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator(".process-detail")).toBeVisible();
  expect(fixture.readCount()).toBe(reads);
  await page.locator(".process-list-entry").filter({ hasText: "example-worker" }).click();
  await expect(page).toHaveURL(/\/processes\/process-2$/);
  await expect(page.locator(".process-runtime-meta")).toContainText("example-worker");
  await page.goBack();
  await expect(page.locator(".process-runtime-meta")).toContainText("resource-1");
  await page.locator(".process-detail-section > summary").filter({ hasText: "Execution journal" }).click();
  await page.getByText("Recorded event", { exact: true }).click();
  await expect(page.locator(".process-event-detail pre")).toContainText("evidence.updated");
  await page.screenshot({ path: testInfo.outputPath("process-event-expanded.png") });
});

for (const locale of ["en", "ko"]) {
  test(`keeps empty process structure and provenance in ${locale}`, async ({ page }) => {
    await installFixture(page, false, []);
    await page.goto(`/processes?locale=${locale}`);
    await expect(page.locator(".process-status-summary dd strong")).toHaveText(["0", "0", "0", "0"]);
    await expect(page.locator("#process-workspace-panel")).toContainText(
      locale === "ko" ? "워크플로우 프로세스 없음" : "No workflow processes",
    );
    await page.getByRole("button", { name: locale === "ko" ? "출처" : "Provenance", exact: true }).click();
    await expect(page.locator("#process-provenance-panel")).toContainText("postgresql:process_runtime");
    await expect(page.locator(".process-list-entry")).toHaveCount(0);
  });
}

for (const theme of ["light", "dark"]) {
  test(`keeps Process state text and keyboard focus legible in ${theme} theme`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await installFixture(page, true, [
      processRecord,
      { ...processRecord, id: "process-2", status: "succeeded" },
      { ...processRecord, id: "process-3", status: "failed" },
    ]);
    await page.goto("/processes/process-1");
    await page.locator(".process-detail").waitFor();
    await page.locator("html").evaluate((element, value) => element.setAttribute("data-theme", value), theme);
    for (const id of ["process-1", "process-2", "process-3"]) {
      await page.locator(`.process-list-entry[href="/processes/${id}"]`).click();
      await expect(page.locator(".process-runtime-meta")).toContainText(id);
      await page.locator(".process-detail-section > summary").filter({ hasText: "Permitted next transitions" }).click();
      await page.locator(".process-detail-section > summary").filter({ hasText: "Execution journal" }).click();
      await page.getByText("Recorded event", { exact: true }).click();
      const region = await measureHandoverPanel(page.locator(".process-route"), testInfo, `process-${theme}-${id}`);
      expect(region.rows.filter(row => row.text && !row.disabled && row.textContrast < row.threshold)).toEqual([]);
    }
    const provenance = page.getByRole("button", { name: "Provenance", exact: true });
    await provenance.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#process-provenance-panel")).toBeVisible();
    const provenanceEvidence = await measureHandoverPanel(page.locator(".process-route"), testInfo, `process-${theme}-provenance`);
    expect(provenanceEvidence.rows.filter(row => row.text && !row.disabled && row.textContrast < row.threshold)).toEqual([]);
    const focus = provenanceEvidence.rows.find(row => row.focused);
    expect(focus?.outlineWidth).toBeGreaterThanOrEqual(2);
    expect(focus?.focusContrast).toBeGreaterThanOrEqual(3);
  });
}

test("keeps loading, unavailable, and failed projections distinct from empty", async ({ page }) => {
  await installFixture(page);
  let release: (() => void) | undefined;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  let status = 503;
  await page.route("**/views/process", async (route) => {
    await pending;
    await route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Process projection failed" }),
    });
  });
  await page.goto("/processes");
  await expect(page.locator(".process-route [aria-busy=true]")).toBeVisible();
  await expect(page.locator(".process-status-summary")).toHaveCount(0);
  release?.();
  await expect(page.locator(".process-route [role=alert]")).toContainText("HTTP 503");
  await expect(page.locator(".process-status-summary")).toHaveCount(0);
  status = 404;
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.locator(".process-route")).toContainText("Process projections are not wired");
  await expect(page.locator(".process-route [role=alert]")).toHaveCount(0);
});

test("bounds long process content and enlarged text in the selected viewport", async ({ page }, testInfo) => {
  const width = Number(process.env["FDAI_PROCESS_LAYOUT_WIDTH"] ?? 1440);
  await page.setViewportSize({ width, height: width >= 1200 ? 900 : 844 });
  await installFixture(page, true, [{
    ...processRecord,
    workflow_ref: `example-workflow-${"long-identifier-".repeat(8)}`,
    target_resource_id: `example-resource-${"긴이름".repeat(20)}`,
    current_step: `example-step-${"evidence-".repeat(10)}`,
  }]);
  await page.goto("/processes/process-1?locale=ko");
  await expect(page.locator(".process-detail")).toBeVisible();
  await page.locator(".process-detail-section > summary").filter({ hasText: "허용된 다음 전환" }).click();
  await page.locator(".process-detail-section > summary").filter({ hasText: "실행 저널" }).click();
  await page.getByText("기록된 이벤트", { exact: true }).click();
  const assertBounds = async () => {
    for (const selector of ["html", "main", ".process-route", ".process-list", ".process-view-stage", ".process-control-panel"]) {
      const bounds = await page.locator(selector).evaluate((element) => ({
        client: element.clientWidth, scroll: element.scrollWidth,
        overflowing: Array.from(element.querySelectorAll("*"))
          .filter((child) => child.clientWidth > 0 && child.scrollWidth > child.clientWidth + 1)
          .map((child) => `${child.tagName}.${child.className}: ${child.scrollWidth}/${child.clientWidth}`)
          .slice(0, 12),
      }));
      expect(bounds.scroll, `${selector}: ${bounds.overflowing.join(", ")}`).toBeLessThanOrEqual(bounds.client);
    }
  };
  await assertBounds();
  const columns = await page.locator(".process-workspace").evaluate((element) =>
    getComputedStyle(element).gridTemplateColumns.split(" ").length);
  expect(columns).toBe(width >= 993 ? 2 : 1);
  await page.locator("main").evaluate((element) => { element.scrollTop = 0; });
  await page.screenshot({ path: testInfo.outputPath(`process-${width}-ko.png`) });
  await page.locator(".process-route *").evaluateAll((elements) => {
    const sizes = elements.map((element) => parseFloat(getComputedStyle(element).fontSize) * 2);
    elements.forEach((element, index) => {
      if (element instanceof HTMLElement) element.style.fontSize = `${sizes[index]}px`;
    });
  });
  await page.addStyleTag({ content: `
    .process-route * { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; }
    .process-route p { margin-bottom: 2em !important; }
  ` });
  await assertBounds();
  if (width <= 390) {
    for (const button of await page.locator(".process-route button").all()) {
      const box = await button.boundingBox();
      if (box) expect(box.height).toBeGreaterThanOrEqual(44);
    }
  }
});
