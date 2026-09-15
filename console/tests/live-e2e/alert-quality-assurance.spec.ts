import { writeFile } from "node:fs/promises";

import { expect, test, type Page, type Response } from "@playwright/test";

import en from "../../src/routes/i18n/alert-quality.en.json" with { type: "json" };
import ko from "../../src/routes/i18n/alert-quality.ko.json" with { type: "json" };
import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";
import {
  buildBrowserEvidenceProvenance,
  canonicalJsonDigest,
} from "./browser-evidence-provenance";

const AUTHENTICATED_EXTERNAL_STACK = Boolean(
  process.env.FDAI_E2E_BASE_URL &&
    process.env.FDAI_E2E_OPERATOR_API_URL &&
    process.env.FDAI_E2E_STORAGE_STATE,
);
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 993, height: 641 },
  { width: 390, height: 844 },
] as const;

test.use({ trace: "off", screenshot: "off", video: "off" });

interface CapturedResponse {
  readonly path: string;
  readonly status: number;
  readonly payload: unknown;
}

function isAlertResponse(response: Response): boolean {
  const api = process.env.FDAI_E2E_OPERATOR_API_URL;
  if (!api || !response.url().startsWith(api.replace(/\/$/, ""))) return false;
  return new URL(response.url()).pathname.startsWith("/alert-quality");
}

async function captureAlertResponses(page: Page): Promise<CapturedResponse[]> {
  const responses: CapturedResponse[] = [];
  page.on("response", async (response) => {
    if (!isAlertResponse(response)) return;
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    responses.push({
      path: new URL(response.url()).pathname,
      status: response.status(),
      payload,
    });
  });
  return responses;
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

async function latestResponse(
  responses: CapturedResponse[],
  path: string,
): Promise<CapturedResponse> {
  await expect.poll(() => responses.filter((item) => item.path === path).length).toBeGreaterThan(0);
  return responses.filter((item) => item.path === path).at(-1)!;
}

async function openSelectedScope(page: Page, responses: CapturedResponse[]): Promise<void> {
  await restoreBrowserEntraSessionStorage(page);
  await page.goto("/alert-quality?locale=en", { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: en.title, exact: true })).toBeVisible();
  await expect(page.getByText(en.signInRequired, { exact: true })).toHaveCount(0);
  const scopesResponse = await latestResponse(responses, "/alert-quality/scopes");
  expect(scopesResponse.status).toBe(200);
  const scopesPayload = object(scopesResponse.payload, "alert-quality scopes response");
  expect(scopesPayload.execution_authority).toBe(false);
  const scopes = scopesPayload.scope_refs;
  if (!Array.isArray(scopes) || scopes.length === 0 || scopes.some((scope) => typeof scope !== "string")) {
    throw new Error("standard Browser Entra principal has no configured alert-quality scope");
  }
  await page.getByRole("combobox", { name: en.scope, exact: true }).selectOption(scopes[0] as string);
  await expect.poll(() => new URL(page.url()).searchParams.has("scope_ref")).toBe(true);
  await latestResponse(responses, "/alert-quality");
  await expect(page.locator("main [aria-busy='true']")).toHaveCount(0, { timeout: 15_000 });
}

test("Browser Entra alert quality keeps live scope and authority boundaries", async ({ page }, testInfo) => {
  test.skip(!AUTHENTICATED_EXTERNAL_STACK, "requires the standard Browser Entra Console stack");
  test.setTimeout(90_000);
  expect(new URL(process.env.FDAI_E2E_BASE_URL!).origin).toBe("http://localhost:5273");
  expect(new URL(process.env.FDAI_E2E_OPERATOR_API_URL!).origin).toBe("http://127.0.0.1:8010");

  const responses = await captureAlertResponses(page);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await openSelectedScope(page, responses);

  const reportResponse = await latestResponse(responses, "/alert-quality");
  expect(reportResponse.status).toBe(200);
  const report = object(reportResponse.payload, "alert-quality response");
  expect(report.source).toBe("alert-noise-governance");
  expect(report.authority).toBe("shadow");
  expect("execution_authority" in report).toBe(false);
  await expect(page.getByText(en.shadow, { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("form", { name: en.proposal, exact: true })).toBeVisible();

  const treatment = page.locator("select[name=treatment_kind]");
  expect(await treatment.locator("option").evaluateAll((options) =>
    options.map((option) => (option as HTMLOptionElement).value),
  )).toEqual(["routing", "suppression", "evaluation"]);
  for (const kind of ["routing", "suppression", "evaluation"] as const) {
    await treatment.selectOption(kind);
    await expect(treatment).toHaveValue(kind);
  }
  expect(await page.locator("main").evaluate((main) => main.scrollWidth <= main.clientWidth)).toBe(true);
  expect(pageErrors).toEqual([]);

  const runConfiguration = {
    schema_version: "1.0.0",
    authentication: "browser_entra",
    console_origin: "http://localhost:5273",
    operator_api_origin: "http://127.0.0.1:8010",
    route: "/alert-quality",
    mode: "read_only_form_inspection",
  };
  const artifact = {
    schema_version: "1.0.0",
    captured_at: new Date().toISOString(),
    passed: true,
    ...buildBrowserEvidenceProvenance(
      process.env.FDAI_E2E_SOURCE_REVISION,
      process.env.FDAI_E2E_WORKSPACE_PATCH_SHA256,
      runConfiguration,
    ),
    run_configuration: runConfiguration,
    observations: {
      authenticated: true,
      scope_count: (object(
        (await latestResponse(responses, "/alert-quality/scopes")).payload,
        "scope response",
      ).scope_refs as unknown[]).length,
      report_payload_digest: canonicalJsonDigest(report),
      authority: "shadow",
      execution_authority: false,
      treatment_axes: ["routing", "suppression", "evaluation"],
      horizontal_overflow: false,
    },
    human_assistive_technology: {
      status: "needs-human",
      claim: "not-observed",
    },
  };
  await writeFile(
    testInfo.outputPath("alert-quality-browser-entra.json"),
    JSON.stringify(artifact, null, 2) + "\n",
    "utf8",
  );
  await testInfo.attach("alert-quality-browser-entra", {
    path: testInfo.outputPath("alert-quality-browser-entra.json"),
    contentType: "application/json",
  });
});

test("Browser Entra alert quality preserves localized responsive keyboard presentation", async ({ page }) => {
  test.skip(!AUTHENTICATED_EXTERNAL_STACK, "requires the standard Browser Entra Console stack");
  test.setTimeout(120_000);
  const responses = await captureAlertResponses(page);
  await openSelectedScope(page, responses);

  for (const [locale, labels] of [["en", en], ["ko", ko]] as const) {
    const target = new URL(page.url());
    target.searchParams.set("locale", locale);
    await page.goto(`${target.pathname}${target.search}`);
    await expect(page.getByRole("heading", { name: labels.title, exact: true })).toBeVisible();
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize(viewport);
      await expect(page.locator("main")).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      expect(await page.locator("main").evaluate((main) => main.scrollWidth <= main.clientWidth)).toBe(true);
    }
  }

  await page.addStyleTag({ content: ":root { font-size: 200% !important; }" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const controls = page.locator("main a[href], main button:not([disabled]), main input:not([disabled]), main select:not([disabled]), main summary");
  const controlCount = await controls.count();
  const visited = new Set<string>();
  for (let index = 0; index < controlCount + 10; index += 1) {
    await page.keyboard.press("Tab");
    const active = await page.evaluate(() => {
      const element = document.activeElement as HTMLElement | null;
      if (!element?.closest("main")) return null;
      const candidates = [...document.querySelectorAll<HTMLElement>(
        "main a[href], main button:not([disabled]), main input:not([disabled]), " +
        "main select:not([disabled]), main summary",
      )];
      const style = getComputedStyle(element);
      const visible = element.matches(":focus-visible") &&
        (style.outlineStyle !== "none" || style.boxShadow !== "none");
      return { index: candidates.indexOf(element), visible };
    });
    if (active !== null) {
      expect(active.index).toBeGreaterThanOrEqual(0);
      expect(active.visible).toBe(true);
      visited.add(String(active.index));
    }
  }
  expect(visited.size).toBe(controlCount);
});
