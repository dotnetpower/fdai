import { expect, test } from "@playwright/test";
import { openSurface, routeMocks } from "./settings-mock-page";

const menus = [
  { name: "General", file: "settings.html", tabs: ["Appearance", "Account", "Briefings", "Memory"], sections: ["settings-appearance", "settings-context", "settings-briefings", "settings-memory", "settings-recent-briefings", "settings-reset"] },
  { name: "Models", file: "settings-models.html", tabs: ["Overview", "Catalog", "Routing", "Web search"], sections: ["models-automation", "models-binding-policy", "models-catalog", "models-t2-policy", "models-operator-preferences", "models-web-search", "mock-allowed-domains", "models-inventory"] },
  { name: "Runtime policies", file: "settings-runtime.html", tabs: ["Effective settings", "Override editor"], sections: ["runtime-policy-settings", "runtime-override-editor"] },
  { name: "Operator memory", file: "settings-memory.html", tabs: ["Memory entries", "Compaction review"], sections: ["memory-filter", "memory-compactions", "memory-entries"] },
  { name: "Identity and access", file: "settings-iam.html", tabs: ["My access", "Users", "Role definitions", "Access requests"], sections: ["iam-current-access", "iam-boundaries", "iam-people", "iam-role-definitions", "iam-access-requests"] },
  { name: "Integrations", file: "settings-integrations.html", tabs: ["Overview", "Teams Workflows", "Diagnostics", "Email template"], sections: ["integrations-overview", "integrations-teams", "integrations-diagnostics", "integrations-email"] },
  { name: "Diagnostics", file: "settings-diagnostics.html", tabs: ["Runtime", "Policy", "Data sources"], sections: ["diagnostics-runtime", "diagnostics-policy", "diagnostics-sources"] },
];

test.describe("Complete Settings workspace coverage", () => {
  test.beforeEach(async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== "desktop-chromium");
    await page.emulateMedia({ reducedMotion: "reduce" });
    await routeMocks(page);
  });

  for (const viewport of [
    { label: "wide", width: 1440, height: 900, master: false },
    { label: "desktop", width: 1070, height: 918, master: false },
    { label: "constrained", width: 993, height: 641, master: true },
    { label: "mobile", width: 390, height: 844, master: true },
  ]) {
    test(`${viewport.label} covers all seven menus and all 23 internal views`, async ({ page }, testInfo) => {
      await page.setViewportSize(viewport);
      const errors: string[] = [];
      page.on("pageerror", (error) => errors.push(error.message));
      const visited: string[] = [];
      let titleLeft: number | undefined;
      for (const menu of menus) {
        const frame = await openSurface(page, menu.file, viewport.master);
        if (menu.name === "General") {
          const listed = await page.locator("a[data-page]").evaluateAll((links) =>
            links.map((link) => (link.getAttribute("data-page") || "").split("/").pop() || "")
              .filter((file) => /^settings(?:-|\.html)/.test(file)),
          );
          expect([...new Set(listed)].sort()).toEqual(menus.map((item) => item.file).sort());
        }
        await expect(frame.getByRole("tab")).toHaveText(menu.tabs);
        for (const id of menu.sections) await expect(frame.locator("#" + id)).toHaveCount(1);
        const left = await frame.locator("h1").evaluate((element) => element.getBoundingClientRect().left);
        titleLeft ??= left;
        expect(left, menu.name).toBeCloseTo(titleLeft, 0);
        const positions = await frame.getByRole("tab").evaluateAll((elements) =>
          elements.map((element) => ({ x: element.getBoundingClientRect().x, width: element.getBoundingClientRect().width })),
        );
        for (const [index, name] of menu.tabs.entries()) {
          await frame.getByRole("tab", { name, exact: true }).click();
          const panel = frame.getByRole("tabpanel");
          await expect(panel).toHaveCount(1);
          await expect(panel).toHaveAccessibleName(name);
          expect(await frame.locator("body").evaluate(() => scrollY)).toBe(0);
          expect(await frame.getByRole("tab").evaluateAll((elements) =>
            elements.map((element) => ({ x: element.getBoundingClientRect().x, width: element.getBoundingClientRect().width })),
          )).toEqual(positions);
          expect(await panel.evaluate((element) =>
            element.scrollWidth <= element.clientWidth && document.documentElement.scrollWidth <= innerWidth,
          )).toBe(true);
          if (menu.file === "settings-integrations.html" && name === "Teams Workflows") {
            await expect(frame.locator("[data-teams-workflow-preview]")).toHaveAttribute("data-teams-workflow-ready", "true");
          }
          if (menu.file === "settings-iam.html" && viewport.label !== "mobile") {
            if (name === "Role definitions") await expect(frame.locator(".iam-role-table")).toHaveCSS("display", "table");
            if (name === "Access requests") await expect(frame.locator(".iam-requests-table")).toHaveCSS("display", "table");
            if (name === "My access" && viewport.label !== "constrained") {
              expect(await frame.locator(".iam-boundary-grid").evaluate((element) => element.getBoundingClientRect().bottom <= innerHeight - 16)).toBe(true);
            }
          }
          await page.screenshot({ path: testInfo.outputPath(`${menu.file}-${index}.png`) });
          for (const detail of await panel.locator("details:visible").all()) {
            const summary = detail.locator(":scope > summary");
            if (await detail.getAttribute("open") === null) {
              await summary.click();
              await expect(detail).toHaveAttribute("open", "");
            }
            expect(await detail.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
            await summary.click();
          }
          const heights = await frame.locator(".cp-tab:visible, .cs-control-button:visible, .cs-control-input:visible, .cs-control-select:visible").evaluateAll((elements) =>
            elements.map((element) => ({ label: element.textContent?.trim() || element.getAttribute("aria-label"), height: element.getBoundingClientRect().height, clipped: element.scrollWidth > element.clientWidth + 1 })),
          );
          expect(heights.filter((item) => item.height !== (viewport.label === "mobile" ? 44 : 34) || item.clipped)).toEqual([]);
          visited.push(`${menu.name}/${name}`);
        }
      }
      expect(visited).toHaveLength(23);
      expect(errors).toEqual([]);
      await testInfo.attach("visited-settings-views.json", { body: JSON.stringify(visited, null, 2), contentType: "application/json" });
    });
  }

  test("desktop preserves native preferences, shared filters and editor values across tabs", async ({ page }) => {
    await page.setViewportSize({ width: 1070, height: 918 });
    const unexpected: string[] = [];
    page.on("request", (request) => {
      if (request.method() !== "GET") unexpected.push(request.method());
    });
    let frame = await openSurface(page, "settings.html");
    await frame.getByRole("group", { name: "Language", exact: true }).getByRole("button", { name: "Korean" }).click();
    await frame.getByRole("tab", { name: "Account", exact: true }).click();
    await frame.getByRole("textbox", { name: "Timezone", exact: true }).fill("Etc/UTC");
    await frame.getByRole("tab", { name: "Appearance", exact: true }).click();
    await expect(frame.getByRole("group", { name: "Language", exact: true }).getByRole("button", { name: "Korean" })).toHaveAttribute("aria-pressed", "true");
    await frame.getByRole("tab", { name: "Account", exact: true }).click();
    await expect(frame.getByRole("textbox", { name: "Timezone", exact: true })).toHaveValue("Etc/UTC");
    await expect(frame.getByRole("button", { name: "Save user context" })).toBeDisabled();

    frame = await openSurface(page, "settings-memory.html");
    await frame.locator(".cs-settings-workspace-filters > summary").click();
    await frame.getByRole("textbox", { name: "Scope reference" }).fill("example-scope");
    await frame.getByRole("tab", { name: "Compaction review" }).click();
    await expect(frame.getByRole("textbox", { name: "Scope reference" })).toHaveValue("example-scope");
    await expect(frame.getByText("Reviewer unassigned", { exact: true })).toBeVisible();

    frame = await openSurface(page, "settings-runtime.html::override-editor");
    await frame.getByRole("textbox", { name: "Override value" }).fill("12 min");
    await frame.getByRole("button", { name: "Save revisioned override" }).click();
    await frame.getByRole("tab", { name: "Effective settings" }).click();
    await frame.getByRole("tab", { name: "Override editor" }).click();
    await expect(frame.getByRole("textbox", { name: "Override value" })).toHaveValue("12 min");
    expect(unexpected).toEqual([]);
  });

  test("desktop supports old section links, keyboard navigation, history and invalid-view recovery", async ({ page }) => {
    await page.setViewportSize({ width: 1070, height: 918 });
    const frame = await openSurface(page, "settings.html::settings-context");
    await expect(frame.getByRole("tab", { name: "Account", exact: true })).toHaveAttribute("aria-selected", "true");
    const account = frame.getByRole("tab", { name: "Account", exact: true });
    await account.focus();
    await account.press("ArrowRight");
    await expect(frame.getByRole("tab", { name: "Briefings" })).toBeFocused();
    await page.goBack();
    await expect(account).toHaveAttribute("aria-selected", "true");
    await page.goForward();
    await frame.getByRole("tab", { name: "Briefings" }).focus();
    await page.keyboard.press("End");
    await expect(frame.getByRole("tab", { name: "Memory", exact: true })).toBeFocused();
    await page.keyboard.press("Home");
    await expect(frame.getByRole("tab", { name: "Appearance" })).toBeFocused();
    const invalid = await openSurface(page, "settings-models.html::not-a-view");
    await expect(invalid.getByRole("alert")).toContainText("Settings view unavailable");
    await expect(invalid.getByRole("tabpanel")).toHaveCount(0);
    await invalid.getByRole("button", { name: "Return to Overview" }).click();
    await expect(invalid.getByRole("tabpanel", { name: "Overview" })).toBeVisible();
  });

  test("missing authored content fails visibly rather than reporting a complete workspace", async ({ page }) => {
    await page.addInitScript(() => {
      document.addEventListener("DOMContentLoaded", () => {
        document.getElementById("models-inventory")?.closest("section")?.remove();
      }, { once: true });
    });
    await page.goto("http://127.0.0.1:5373/mocks/ui/#settings-models.html");
    const frame = page.frameLocator("iframe");
    await expect(frame.locator("[data-settings-profile]")).toHaveAttribute("data-settings-ready", "error");
    await expect(frame.getByRole("alert")).toContainText("Settings workspace could not load");
    await expect(frame.getByRole("tab")).toHaveCount(0);
  });
});
