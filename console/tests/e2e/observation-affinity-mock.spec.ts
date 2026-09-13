import { expect, test, type FrameLocator } from "@playwright/test";
import { readFileSync } from "node:fs";
import { openSurface, routeMocks } from "./settings-mock-page";

const snapshotPath = "**/mocks/ui/assets/ontology-instance-snapshot.json";
const snapshot = JSON.parse(readFileSync(new URL("../../../mocks/ui/assets/ontology-instance-snapshot.json", import.meta.url), "utf8"));
const target = (frame: FrameLocator, identity: string) => frame.locator(`[name="target"][value="mock:ontology-2d:${identity}"]`);

async function expectLayout(frame: FrameLocator) {
  const measurements = await frame.locator(".oa-workspace").evaluate((root) => ({
    viewport: [innerWidth, innerHeight],
    documentFits: document.documentElement.scrollWidth <= innerWidth,
    contentFits: root.scrollWidth <= root.clientWidth,
    regionsFit: [...document.querySelectorAll(".oa-rule, .oa-inspector, dialog[open], .oa-filters")]
      .filter((element) => element.getBoundingClientRect().width > 0)
      .every((element) => element.scrollWidth <= element.clientWidth + 1),
  }));
  expect(measurements).toMatchObject({ documentFits: true, contentFits: true, regionsFit: true });
  return measurements;
}

test.describe("Observation affinity static preview", () => {
  test.describe.configure({ mode: "serial" });
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium", "Responsive checks follow the desktop gate in this file.");
    await page.setViewportSize({ width: 1440, height: 900 });
    await routeMocks(page);
  });

  test("desktop rule inspection, preview creation, validation and keyboard recovery", async ({ page }, testInfo) => {
    const errors: string[] = [];
    const unsafeRequests: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (request.method() !== "GET" || !request.url().startsWith("http://127.0.0.1:5373/")) unsafeRequests.push(request.url());
    });
    const frame = await openSurface(page, "observation-affinity.html", true);
    await expect(frame.locator(".oa-workspace")).toHaveAttribute("data-affinity-ready", "true");
    await expect(page.locator('[data-page="mocks/ui/observation-affinity.html"]')).toHaveClass(/is-active/);
    await expect(frame.locator(".oa-rule")).toHaveCount(4);
    await expect(frame.locator("#detail-title")).toHaveText("Post-change observation");
    await expect(frame.locator("#detail-status")).toHaveText("Applied");
    await expect(frame.locator("#detail-evidence")).toContainText("Not live telemetry");
    await expect(frame.getByText("Always maintained", { exact: true })).toBeVisible();
    const desktop = await expectLayout(frame);
    await page.screenshot({ path: testInfo.outputPath("affinity-desktop.png") });

    await frame.getByRole("button", { name: "Inspect Data continuity", exact: true }).click();
    await expect(frame.locator("#detail-status")).toHaveText("Budget limited");
    await expect(frame.locator("#detail-application")).toContainText("no additional collection is confirmed");
    await expect(frame.locator("#detail-title")).toBeFocused();
    await frame.getByRole("button", { name: "Inspect Runtime behavior", exact: true }).click();
    await expect(frame.locator("#detail-status")).toHaveText("Evidence unavailable");
    await expect(frame.locator("#detail-application")).toContainText("health cannot be confirmed");
    await frame.getByRole("button", { name: "Pause in preview", exact: true }).click();
    await expect(frame.locator("#detail-status")).toHaveText("Paused");
    await frame.getByRole("button", { name: "Resume in preview", exact: true }).click();
    await expect(frame.locator("#detail-status")).toHaveText("Not evaluated");

    await frame.getByRole("searchbox", { name: "Find a rule or target" }).fill("no-matching-example");
    await expect(frame.getByRole("heading", { name: "No matching rules" })).toBeVisible();
    await expect(frame.locator("#rule-detail")).toBeHidden();
    await frame.getByRole("button", { name: "Clear filters" }).click();
    await expect(frame.getByRole("searchbox", { name: "Find a rule or target" })).toBeFocused();
    await frame.getByLabel("Rule state", { exact: true }).selectOption("paused");
    await expect(frame.locator(".oa-rule")).toHaveCount(1);
    await frame.getByRole("button", { name: "Resume in preview", exact: true }).click();
    await expect(frame.getByLabel("Rule state", { exact: true })).toBeFocused();
    await expect(frame.locator(".oa-rule")).toHaveCount(0);
    await frame.getByLabel("Rule state", { exact: true }).selectOption("all");

    const add = frame.getByRole("button", { name: "Add affinity rule" });
    await add.focus();
    await page.keyboard.press("Enter");
    const editor = frame.getByRole("dialog", { name: "Add observation affinity" });
    await expect(editor).toBeVisible();
    await expect(frame.locator("#ontology-picker")).toHaveAttribute("data-source-state", "ready");
    await expect(frame.getByLabel("Rule name", { exact: true })).toBeFocused();
    await expectLayout(frame);
    await page.screenshot({ path: testInfo.outputPath("affinity-editor-desktop.png") });
    await page.keyboard.press("Shift+Tab");
    await expect(frame.getByRole("button", { name: "Create preview rule" })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(frame.getByLabel("Rule name", { exact: true })).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(editor).toBeHidden();
    await expect(add).toBeFocused();
    await add.click();
    const save = frame.getByRole("button", { name: "Create preview rule" });
    await save.click();
    await expect(frame.getByRole("alert")).toHaveText("Enter a name for this affinity rule.");
    await frame.getByLabel("Rule name", { exact: true }).fill("Post-change observation");
    await save.click();
    await expect(frame.getByRole("alert")).toContainText("already exists");
    await frame.getByLabel("Rule name", { exact: true }).fill("Example multi-resource observation");
    await save.click();
    await expect(frame.getByRole("alert")).toHaveText("Select at least one observation target.");
    await target(frame, "group:example-runtime").check();
    await frame.getByLabel("Resources", { exact: true }).check();
    await expect(editor.locator('[name="target"]:checked')).toHaveCount(0);
    await expect(frame.locator("#selected-count")).toHaveText("1 selected");
    await frame.getByRole("button", { name: "Remove example-runtime / mock:ontology-2d:group:example-runtime", exact: true }).click();
    await target(frame, "example-runtime:runtime-environment").check();
    await target(frame, "example-runtime:checkout-api").check();
    await frame.getByLabel("Availability", { exact: true }).uncheck();
    await save.click();
    await expect(frame.getByRole("alert")).toHaveText("Select at least one observation signal.");
    await frame.getByLabel("Performance", { exact: true }).check();
    await save.click();
    await expect(frame.getByRole("alert")).toHaveText("Enter a reason for the additional observation.");
    await frame.getByLabel("Reason", { exact: true }).fill("Watch the example services after a deployment.");
    await frame.getByLabel("Preference strength", { exact: true }).selectOption("strong");
    await save.click();
    await expect(editor).toBeHidden();
    await expect(add).toBeFocused();
    await expect(frame.locator(".oa-rule")).toHaveCount(5);
    await expect(frame.locator("#detail-title")).toHaveText("Example multi-resource observation");
    await expect(frame.locator("#detail-targets li")).toHaveCount(2);
    await expect(frame.locator("#detail-strength")).toHaveText("Strong preference");
    await expect(frame.locator("#detail-status")).toHaveText("Not evaluated");
    await expect(frame.locator("#preview-feedback")).toContainText("in this preview only");
    await frame.locator(".oa-explainer > summary").focus();
    await page.keyboard.press("Enter");
    await expect(frame.getByRole("heading", { name: "Respect existing limits" })).toBeVisible();
    await expectLayout(frame);
    await add.click();
    await frame.getByLabel("Rule name", { exact: true }).fill("Unsaved");
    await frame.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(frame.locator(".oa-rule")).toHaveCount(5);
    await page.reload();
    await expect(frame.locator(".oa-rule")).toHaveCount(4);
    expect(errors).toEqual([]);
    expect(unsafeRequests).toEqual([]);
    await testInfo.attach("desktop-measurements", { body: JSON.stringify(desktop), contentType: "application/json" });
  });

  test("ontology snapshot identity, membership filters and cross-type selection review", async ({ page }) => {
    const fixture = structuredClone(snapshot);
    fixture.generation = "mock-duplicate-names-v2";
    fixture.instances.find((item: { id: string }) => item.id.endsWith(":ingestion-api")).name = "checkout-api";
    await page.route(snapshotPath, (route) => route.fulfill({ json: fixture }));
    const frame = await openSurface(page, "observation-affinity.html", true);
    await frame.getByRole("button", { name: "Add affinity rule" }).click();
    await expect(frame.locator("#ontology-picker")).toHaveAttribute("data-source-state", "ready");
    await expect(frame.locator("#target-source-summary")).toContainText("mock-duplicate-names-v2");
    await expect(frame.locator("#target-source-summary")).toContainText("2026-08-22T08:00:00Z");
    await expect(frame.locator("#target-help")).toContainText("not catalog type definitions");
    await frame.locator(".oa-source-details > summary").click();
    await expect(frame.locator("#target-source")).toContainText("ontology-instances-2d-mock");
    await expect(frame.locator("#target-derivation")).toContainText("mocks/ui/ontology-instances-2d.html");
    await expect(frame.locator("#target-count")).toHaveText("4 of 4 recorded resource groups");
    await target(frame, "group:example-runtime").check();
    await frame.getByLabel("Resources", { exact: true }).check();
    await expect(frame.locator("#target-count")).toHaveText("12 of 12 recorded resources");
    const search = frame.getByRole("searchbox", { name: "Search ontology instances" });
    await search.fill("checkout-api");
    await expect(frame.locator("#target-count")).toHaveText("2 of 12 recorded resources");
    await expect(frame.locator("#target-options")).toContainText("compute.container-app");
    await expect(frame.getByRole("checkbox", { name: "checkout-api / mock:ontology-2d:example-runtime:ingestion-api", exact: true })).toBeVisible();
    await target(frame, "example-runtime:checkout-api").check();
    await target(frame, "example-runtime:ingestion-api").check();
    await expect(frame.locator("#selected-count")).toHaveText("3 selected");
    await frame.getByLabel("Resource group membership").selectOption("mock:ontology-2d:group:example-data");
    await expect(frame.locator("#target-no-match")).toContainText("No matching recorded instances");
    await expect(frame.locator("#selected-count")).toHaveText("3 selected");
    await search.fill("");
    await expect(frame.locator("#target-count")).toHaveText("5 of 12 recorded resources");
    await expect(target(frame, "example-data:state-db")).toBeVisible();
    await expect(target(frame, "example-runtime:checkout-api")).toHaveCount(0);
    await search.fill("data.postgresql");
    await expect(frame.locator("#target-count")).toHaveText("1 of 12 recorded resources");
    await target(frame, "example-data:state-db").focus();
    await page.keyboard.press("Space");
    await expect(frame.locator("#selected-count")).toHaveText("4 selected");
    await frame.getByRole("button", { name: "Clear target filters" }).click();
    await expect(search).toBeFocused();
    await search.fill("mock:ontology-2d:example-runtime:ingestion-api");
    await expect(frame.locator("#target-count")).toHaveText("1 of 12 recorded resources");
    await expect(target(frame, "example-runtime:ingestion-api")).toBeChecked();
    await frame.getByRole("button", { name: "Remove checkout-api / mock:ontology-2d:example-runtime:checkout-api", exact: true }).click();
    await expect(frame.locator("#selected-targets button").first()).toBeFocused();
    await expect(frame.locator("#selected-count")).toHaveText("3 selected");
    await frame.getByLabel("Rule name", { exact: true }).fill("Exact instance review");
    await frame.getByLabel("Reason", { exact: true }).fill("Observe only the reviewed snapshot identities.");
    await frame.getByRole("button", { name: "Create preview rule" }).click();
    await expect(frame.locator("#detail-targets li")).toHaveCount(3);
    await expect(frame.locator('#detail-targets [data-instance-id="mock:ontology-2d:example-runtime:ingestion-api"]')).toContainText("mock-duplicate-names-v2");
    await expect(frame.locator('#detail-targets [data-instance-id="mock:ontology-2d:example-runtime:checkout-api"]')).toHaveCount(0);
    await expect(frame.locator("#detail-status")).toHaveText("Not evaluated");
    await frame.getByRole("button", { name: "Pause in preview", exact: true }).click();
    await frame.getByRole("button", { name: "Resume in preview", exact: true }).click();
    await expect(frame.locator("#detail-status")).toHaveText("Not evaluated");
    await expectLayout(frame);
  });

  test("bounded source scenarios fail closed and clear old selections", async ({ page }) => {
    const frame = await openSurface(page, "observation-affinity.html", true);
    const add = frame.getByRole("button", { name: "Add affinity rule" });
    await add.click();
    await target(frame, "group:example-runtime").check();
    await frame.locator(".oa-source-details > summary").click();
    const scenario = frame.getByLabel("Mock source scenario");
    const save = frame.getByRole("button", { name: "Create preview rule" });
    for (const state of ["unavailable", "error", "empty", "partial"]) {
      await scenario.selectOption(state);
      await expect(frame.locator("#ontology-picker")).toHaveAttribute("data-source-state", state);
      await expect(save).toBeDisabled();
      await expect(frame.locator("#selected-count")).toHaveText("0 selected");
      if (state === "unavailable" || state === "error") {
        await expect(frame.locator("#target-source-error")).toContainText("No fallback targets");
        await expect(frame.locator('[name="target"]')).toHaveCount(0);
      } else if (state === "empty") {
        await expect(frame.locator("#target-no-match")).toContainText("No recorded ontology instances");
      } else {
        await expect(frame.locator("#target-source-summary")).toContainText("coverage is incomplete");
        await expect(frame.locator('[name="target"]:enabled')).toHaveCount(0);
        await expect(frame.locator('[name="target"]')).toHaveCount(4);
      }
    }
    await scenario.selectOption("loading");
    await expect(frame.locator("#target-loading")).toBeVisible();
    await expect(frame.locator("#target-loading .oa-skeleton")).toHaveCount(3);
    await expect(frame.locator("#ontology-picker")).toHaveAttribute("aria-busy", "true");
    await expect(save).toBeDisabled();
    await expect(frame.locator("#ontology-picker")).toHaveAttribute("data-source-state", "unavailable");
    await expect(frame.locator("#target-source-error")).toContainText("deadline reached");
    await scenario.selectOption("ready");
    await expect(save).toBeEnabled();
    await expect(frame.locator("#selected-count")).toHaveText("0 selected");
    await target(frame, "group:example-data").check();
    await frame.getByRole("button", { name: "Reload mock snapshot" }).click();
    await expect(frame.locator("#selected-count")).toHaveText("0 selected");
    await expect(frame.locator("#target-change")).toContainText("Previous selections were cleared");
    await expect(save).toBeEnabled();
    await page.keyboard.press("Escape");
    await expect(frame.getByRole("dialog")).toBeHidden();
    await expect(add).toBeFocused();
    await add.click();
    await expect(frame.locator("#selected-count")).toHaveText("0 selected");
    await frame.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(add).toBeFocused();
    await expect(frame.locator(".oa-rule")).toHaveCount(4);
  });

  test("real asset failures, invalid identities and generation changes cannot reuse a selection", async ({ page }) => {
    const frame = await openSurface(page, "observation-affinity.html", true);
    await expect(frame.locator(".oa-workspace")).toHaveAttribute("data-affinity-ready", "true");
    let payload = structuredClone(snapshot);
    let status = 503;
    await page.route(snapshotPath, (route) => route.fulfill({ status, json: payload }));
    await frame.getByRole("button", { name: "Add affinity rule" }).click();
    const picker = frame.locator("#ontology-picker");
    const save = frame.getByRole("button", { name: "Create preview rule" });
    await expect(picker).toHaveAttribute("data-source-state", "error");
    await expect(frame.locator("#target-source-error")).toContainText("HTTP 503");
    await expect(save).toBeDisabled();
    await frame.locator(".oa-source-details > summary").click();
    const reload = frame.getByRole("button", { name: "Reload mock snapshot" });
    status = 200;
    await reload.click();
    await target(frame, "group:example-runtime").check();
    payload.generation = "mock-next-generation";
    await reload.click();
    await expect(frame.locator("#target-generation")).toHaveText("mock-next-generation");
    await expect(frame.locator("#selected-count")).toHaveText("0 selected");
    await expect(target(frame, "group:example-runtime")).not.toBeChecked();
    const invalid = [
      { ...snapshot, source: { ...snapshot.source, id: "different-source" } },
      { ...snapshot, instances: [...snapshot.instances, snapshot.instances[0]] },
      { ...snapshot, generation: "" },
      { ...snapshot, relations: [...snapshot.relations, { from: "missing", to: "missing", type: "member_of" }] },
      { ...snapshot, instances: [{ ...snapshot.instances[0], objectType: "CatalogType" }] },
    ];
    for (const malformed of invalid) {
      payload = malformed;
      await reload.click();
      await expect(picker).toHaveAttribute("data-source-state", "error");
      await expect(frame.locator("#target-source-error")).toContainText("Invalid synthetic ontology snapshot");
      await expect(save).toBeDisabled();
      await expect(frame.locator('[name="target"]')).toHaveCount(0);
      await expect(frame.locator("#selected-count")).toHaveText("0 selected");
    }
    await frame.locator("#rule-form").evaluate((form: HTMLFormElement) => form.requestSubmit());
    await expect(frame.locator("#form-error")).toContainText("complete, validated ontology snapshot is required");
    await expect(frame.locator(".oa-rule")).toHaveCount(4);
    await expect(frame.getByRole("dialog")).toBeVisible();
  });

  test("cancel and source changes discard late snapshot responses", async ({ page }) => {
    const frame = await openSurface(page, "observation-affinity.html", true);
    await expect(frame.locator(".oa-workspace")).toHaveAttribute("data-affinity-ready", "true");
    let release!: () => void;
    let delivered!: () => void;
    const held = new Promise<void>((resolve) => { release = resolve; });
    const completed = new Promise<void>((resolve) => { delivered = resolve; });
    await page.route(snapshotPath, async (route) => {
      await held;
      await route.fulfill({ json: snapshot });
      delivered();
    });
    const requested = page.waitForRequest(snapshotPath);
    await frame.getByRole("button", { name: "Add affinity rule" }).click();
    await requested;
    await expect(frame.locator("#target-loading")).toBeVisible();
    await frame.locator(".oa-source-details > summary").click();
    await frame.getByLabel("Mock source scenario").selectOption("error");
    await expect(frame.locator("#ontology-picker")).toHaveAttribute("data-source-state", "error");
    release();
    await completed;
    await expect(frame.locator('[name="target"]')).toHaveCount(0);
    await expect(frame.getByRole("button", { name: "Create preview rule" })).toBeDisabled();
    await frame.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(frame.getByRole("dialog")).toBeHidden();
    await expect(frame.getByRole("button", { name: "Add affinity rule" })).toBeFocused();
    await expect(frame.locator(".oa-rule")).toHaveCount(4);
    await page.unroute(snapshotPath);
    let finish!: () => void;
    let didFinish!: () => void;
    const cancelledRead = new Promise<void>((resolve) => { finish = resolve; });
    const cancelledDelivery = new Promise<void>((resolve) => { didFinish = resolve; });
    await page.route(snapshotPath, async (route) => {
      await cancelledRead;
      await route.fulfill({ json: snapshot });
      didFinish();
    });
    const nextRequest = page.waitForRequest(snapshotPath);
    await frame.getByRole("button", { name: "Add affinity rule" }).click();
    await nextRequest;
    await frame.getByRole("button", { name: "Cancel", exact: true }).click();
    finish();
    await cancelledDelivery;
    await expect(frame.getByRole("dialog")).toBeHidden();
    await expect(frame.locator('[name="target"]')).toHaveCount(0);
    await expect(frame.getByRole("button", { name: "Add affinity rule" })).toBeFocused();
  });

  test("responsive master, kit navigation, text extremes and user preferences", async ({ page }, testInfo) => {
    const frame = await openSurface(page, "observation-affinity.html", true);
    const layouts = [];
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
      await page.setViewportSize(viewport);
      await expect(frame.locator("#detail-title")).toHaveText("Post-change observation");
      layouts.push({ outer: viewport, inner: await expectLayout(frame) });
      await frame.getByRole("button", { name: "Add affinity rule" }).click();
      await expectLayout(frame);
      await frame.getByLabel("Rule name", { exact: true }).fill("관찰선호도검토".repeat(10));
      await target(frame, "group:example-runtime").check();
      await frame.getByLabel("Reason", { exact: true }).fill("변경 후 서비스 안정성과 가용성을 확인합니다. ".repeat(5));
      await frame.getByRole("button", { name: "Create preview rule" }).click();
      await expect(frame.locator("#detail-status")).toHaveText("Not evaluated");
      await expectLayout(frame);
      await frame.locator("#detail-title").scrollIntoViewIfNeeded();
      await page.screenshot({ path: testInfo.outputPath(`affinity-${viewport.width}.png`) });
      await page.reload();
    }
    await page.setViewportSize({ width: 993, height: 641 });
    await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
    await frame.getByRole("button", { name: "Inspect Data continuity", exact: true }).click();
    await expect(frame.locator("#detail-title")).toBeFocused();
    await expect(frame.locator("#detail-status")).toHaveText("Budget limited");
    await expectLayout(frame);
    await page.emulateMedia({ forcedColors: "none" });
    await frame.locator(".oa-workspace").evaluate(() => {
      const style = document.createElement("style");
      style.textContent = ".oa-page { --cs-type-body-size:28px; --cs-type-compact-size:26px; --cs-type-label-size:24px; --cs-type-panel-title-size:30px; --cs-type-section-title-size:36px; --cs-type-page-title-size:48px; } .oa-page * { line-height:1.5!important; letter-spacing:.12em!important; word-spacing:.16em!important; } .oa-page p { margin-bottom:2em!important; }";
      document.head.append(style);
    });
    await expectLayout(frame);
    await frame.getByRole("button", { name: "Add affinity rule" }).click();
    await expectLayout(frame);
    await frame.getByRole("button", { name: "Cancel", exact: true }).click();
    await page.setViewportSize({ width: 1440, height: 900 });
    const kit = await openSurface(page, "observation-affinity.html");
    await expect(kit.locator("#detail-title")).toHaveText("Post-change observation");
    await expect(page.locator('[data-page="observation-affinity.html"]')).toHaveClass(/is-active/);
    await expectLayout(kit);
    await page.locator('[data-page="scope.html"]').click();
    await expect(kit.getByRole("heading", { name: "Effective boundaries", exact: true })).toBeVisible();
    await page.goBack();
    await expect(kit.locator("#detail-title")).toHaveText("Post-change observation");
    await testInfo.attach("responsive-measurements", { body: JSON.stringify(layouts), contentType: "application/json" });
  });
});
