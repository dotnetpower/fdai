import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { ExecutionSettings, ExecutionSettingsRequest, InstallationDetail } from "../../src/api";

const identifier = "installation-alpha";
const digest = "a".repeat(64);

async function openSchedule(page: Page, options: {
  save?: "success" | "conflict" | "network";
  blocked?: boolean;
  unavailable?: boolean;
  windowCount?: number;
} = {}) {
  let settings: ExecutionSettings = {
    settings_digest: digest, plan_duration_minutes: 30,
    windows: Array.from({ length: options.windowCount ?? 0 }, (_, index) => ({
      start: `${String(index % 24).padStart(2, "0")}:00:00`,
      duration_minutes: 30, timezone: "UTC", allows_downtime: false,
    })),
  };
  const installation: InstallationDetail = {
    installation_id: identifier, enrollment: "enrolled",
    settings: { channel: "DEV", version_range: "*", region: "region-a", allowed_regions: ["region-a"], windows: [] },
    configuration_digest: "b".repeat(64), reported_at: "2026-10-01T00:00:00Z",
    schema_revision: 0, current_release: null, health: "unknown", entities: [], suppressions: [],
    open_plan: options.blocked ? {
      plan_id: "pending-plan", sequence: 1, target_release_id: "1.0.0", expires_at: "2026-10-02T00:00:00Z",
    } : null,
    last_evaluation: null, reports: [],
  };
  let reads = 0;
  const writes: { path: string; body: ExecutionSettingsRequest }[] = [];
  const pageErrors: string[] = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("https://hub.test/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/auth/config") return route.fulfill({ json: { profile: "local-development" } });
    if (path === `/v1/installations/${identifier}/execution-settings`) {
      if (request.method() === "GET") {
        reads += 1;
        return route.fulfill(options.unavailable
          ? { status: 503, json: { error: "schedule_unavailable" } }
          : { json: settings });
      }
      const body: ExecutionSettingsRequest = request.postDataJSON();
      writes.push({ path, body });
      if (options.save === "network") return route.abort("connectionfailed");
      if (options.save === "conflict") return route.fulfill({
        status: 409, json: { error: "execution_settings_revision_conflict" },
      });
      settings = {
        settings_digest: "c".repeat(64), windows: body.windows,
        plan_duration_minutes: body.plan_duration_minutes,
      };
      return route.fulfill({ json: { changed: true, settings_digest: settings.settings_digest } });
    }
    if (!["GET", "HEAD"].includes(request.method())) {
      throw new Error(`Unexpected mutation: ${path}`);
    }
    if (path === `/v1/installations/${identifier}`) return route.fulfill({
      json: { ...installation, settings: { ...installation.settings, windows: settings.windows } },
    });
    if (path.startsWith("/v1/")) return route.fulfill({ status: 404, json: { error: "not_found" } });
    const file = path.startsWith("/assets/") || path.startsWith("/brand/") ? path : "/index.html";
    return route.fulfill({
      body: await readFile(resolve("dist", `.${file}`)),
      contentType: file.endsWith(".js") ? "text/javascript" :
        file.endsWith(".css") ? "text/css" : file.endsWith(".png") ? "image/png" : "text/html",
    });
  });
  await page.goto(`https://hub.test/installations/${identifier}`);
  await expect(page.getByRole("heading", { name: identifier, exact: true })).toBeVisible();
  await expect(page.locator("img.brand-logo")).not.toHaveJSProperty("naturalWidth", 0);
  expect(reads).toBe(0);
  const tab = page.getByRole("button", { name: "Execution schedule", exact: true });
  await tab.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Execution schedule", exact: true })).toBeVisible();
  await expect.poll(() => reads).toBe(1);
  return { writes, pageErrors, reads: () => reads };
}

async function review(page: Page) {
  await page.getByRole("button", { name: "Add window", exact: true }).click();
  await page.getByLabel("Local start time", { exact: true }).fill("09:30");
  await page.getByLabel("Time zone", { exact: true }).fill("Asia/Seoul");
  await page.getByLabel("Duration (minutes)", { exact: true }).fill("90.5");
  await page.getByLabel("Plan duration (minutes)", { exact: true }).fill("20");
  await page.getByRole("combobox", { name: "Reason", exact: true }).selectOption("operator_schedule_change");
  const confirmation = page.getByLabel("Exact confirmation", { exact: true });
  await expect(page.getByRole("button", { name: "Save execution settings", exact: true })).toBeDisabled();
  await confirmation.fill(`update execution settings ${identifier} ${digest}`);
}

async function geometry(page: Page) {
  const result = await page.evaluate(() => {
    const main = document.querySelector("main");
    const form = document.querySelector(".execution-settings");
    if (!main || !form) throw new Error("Missing schedule surface");
    const colors = (selector: string) => {
      const element = form.querySelector(selector);
      if (!element) throw new Error(`Missing measured control: ${selector}`);
      const style = getComputedStyle(element);
      return { color: style.color, background: style.backgroundColor, border: style.borderTopColor };
    };
    return {
      viewport: { width: innerWidth, height: innerHeight },
      documentWidth: document.documentElement.scrollWidth,
      mainWidth: main.clientWidth, mainScrollWidth: main.scrollWidth,
      formWidth: form.clientWidth, formScrollWidth: form.scrollWidth,
      input: colors(".input"),
      save: colors(".btn.primary"),
      controls: Array.from(form.querySelectorAll<HTMLInputElement | HTMLButtonElement>("input, button, select"))
        .map(control => {
          const bounds = control.getBoundingClientRect();
          return { width: bounds.width, height: bounds.height, right: bounds.right };
        }),
    };
  });
  expect(result.documentWidth).toBeLessThanOrEqual(result.viewport.width);
  expect(result.mainScrollWidth).toBeLessThanOrEqual(result.mainWidth);
  expect(result.formScrollWidth).toBeLessThanOrEqual(result.formWidth);
  for (const control of result.controls) expect(control.right).toBeLessThanOrEqual(result.viewport.width);
  expect(contrast(result.input.color, result.input.background)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(result.input.border, result.input.background)).toBeGreaterThanOrEqual(3);
  expect(contrast(result.save.color, result.save.background)).toBeGreaterThanOrEqual(4.5);
  return result;
}

function contrast(foreground: string, background: string): number {
  function luminance(color: string) {
    const match = /^rgb\((\d+),\s*(\d+),\s*(\d+)\)$/.exec(color);
    if (!match) throw new Error(`Expected an opaque RGB color, got ${color}`);
    const channels = match.slice(1).map(value => {
      const linear = Number(value) / 255;
      return linear <= 0.04045 ? linear / 12.92 : ((linear + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * channels[0]! + 0.7152 * channels[1]! + 0.0722 * channels[2]!;
  }
  const first = luminance(foreground), second = luminance(background);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

test("schedule is lazy, keyboard-accessible, bounded, and saves only the reviewed schedule", async ({ page }, info) => {
  const harness = await openSchedule(page);
  await expect(page.getByText("No windows configured.", { exact: false })).toBeVisible();
  await review(page);
  const desktop = await geometry(page);
  const measurements = info.outputPath("desktop-geometry.json");
  await writeFile(measurements, JSON.stringify(desktop));
  await info.attach("desktop-geometry", { path: measurements, contentType: "application/json" });
  const screenshot = info.outputPath("schedule-desktop.png");
  await page.screenshot({ path: screenshot, fullPage: true });
  await info.attach("schedule-desktop", { path: screenshot, contentType: "image/png" });
  await page.getByRole("button", { name: "Save execution settings", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Execution settings saved." }))
    .toContainText("No Plan was computed or applied.");
  expect(harness.writes).toHaveLength(1);
  const write = harness.writes[0]!;
  expect(write.path).toBe(`/v1/installations/${identifier}/execution-settings`);
  expect(write.body).toEqual({
    request_id: expect.stringMatching(/^[0-9a-f-]{36}$/),
    expected_settings_digest: digest,
    windows: [{ start: "09:30", duration_minutes: 90.5, timezone: "Asia/Seoul", allows_downtime: false }],
    plan_duration_minutes: 20, reason_code: "operator_schedule_change",
    confirmation: `update execution settings ${identifier} ${digest}`,
  });
  await expect.poll(harness.reads).toBe(2);
  await expect(page.getByLabel("Time zone", { exact: true })).toHaveValue("Asia/Seoul");
  expect(harness.pageErrors).toEqual([]);
});

test("expanded schedule reflows after the desktop gate", async ({ page }, info) => {
  const harness = await openSchedule(page, { windowCount: 1 });
  await page.getByLabel("Time zone", { exact: true }).fill("Asia/Seoul");
  await page.getByLabel("Exact confirmation", { exact: true }).fill("검토 중인 일정");
  await geometry(page);
  for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    await expect(page.getByLabel("Time zone", { exact: true })).toHaveValue("Asia/Seoul");
    const measured = await geometry(page);
    if (viewport.width === 390) {
      for (const control of measured.controls) {
        if (control.width > 24) expect(control.height).toBeGreaterThanOrEqual(44);
      }
    }
    const path = info.outputPath(`geometry-${viewport.width}.json`);
    await writeFile(path, JSON.stringify(measured));
    await info.attach(`geometry-${viewport.width}`, { path, contentType: "application/json" });
  }
  expect(harness.writes).toEqual([]);
  expect(harness.pageErrors).toEqual([]);
});

for (const failure of ["conflict", "network"] as const) {
  test(`${failure} is explicit and requires refresh instead of automatic resubmission`, async ({ page }) => {
    const harness = await openSchedule(page, { save: failure });
    await review(page);
    await page.getByRole("button", { name: "Save execution settings", exact: true }).click();
    await expect(page.getByRole("alert")).toContainText(failure === "conflict"
      ? "execution_settings_revision_conflict" : "save outcome could not be confirmed");
    await expect(page.getByRole("button", { name: "Save execution settings", exact: true })).toBeDisabled();
    expect(harness.writes).toHaveLength(1);
    await page.getByRole("button", { name: "Refresh settings", exact: true }).click();
    await expect.poll(harness.reads).toBe(2);
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.getByLabel("Exact confirmation", { exact: true })).toHaveValue("");
    expect(harness.writes).toHaveLength(1);
  });
}

test("an open Plan prevents editing without hiding its status", async ({ page }) => {
  const harness = await openSchedule(page, { blocked: true });
  await expect(page.getByRole("status")).toContainText("An open Plan blocks schedule changes.");
  await expect(page.getByRole("button", { name: "Add window", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save execution settings", exact: true })).toBeDisabled();
  expect(harness.writes).toEqual([]);
});

test("unavailable settings remain unavailable rather than an empty editable schedule", async ({ page }) => {
  const harness = await openSchedule(page, { unavailable: true });
  await expect(page.getByRole("alert")).toContainText("schedule_unavailable");
  await expect(page.getByRole("button", { name: "Save execution settings", exact: true })).toHaveCount(0);
  expect(harness.writes).toEqual([]);
});

test("32 windows remain editable without allowing a thirty-third", async ({ page }) => {
  const harness = await openSchedule(page, { windowCount: 32 });
  await expect(page.getByRole("button", { name: "Add window", exact: true })).toBeDisabled();
  await expect(page.getByLabel("Time zone", { exact: true })).toHaveCount(32);
  await page.getByRole("button", { name: "Remove window 1", exact: true }).click();
  await expect(page.getByLabel("Time zone", { exact: true })).toHaveCount(31);
  await expect(page.getByLabel("Local start time", { exact: true }).first()).toHaveValue("01:00:00");
  await expect(page.getByRole("button", { name: "Add window", exact: true })).toBeEnabled();
  expect(harness.writes).toEqual([]);
});
