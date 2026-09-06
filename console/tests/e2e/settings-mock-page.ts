import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type FrameLocator, type Page } from "@playwright/test";

const root = path.resolve(fileURLToPath(new URL("../../../", import.meta.url)));
const origin = "http://127.0.0.1:5373";

/** Serve local mock assets from the working checkout without backend requests. */
export async function routeMocks(page: Page) {
  await page.route(`${origin}/**`, async (route) => {
    const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
    const entry = pathname.endsWith("/") ? `${pathname}index.html` : pathname;
    const file = path.resolve(root, `.${entry}`);
    if (!file.startsWith(`${root}${path.sep}`) || !/\.(html|css|js|json|svg|png)$/.test(file)) {
      await route.fulfill({ status: 404, body: "Not a UI fixture." });
      return;
    }
    await route.fulfill({ path: file });
  });
}

/** Open the kit or master shell and wait for its actual embedded Settings or gallery surface. */
export async function openSurface(page: Page, file: string, master = false) {
  await page.goto("about:blank");
  await page.goto(`${origin}/${master ? `#mocks/ui/${file}` : `mocks/ui/#${file}`}`);
  const frame = page.frameLocator(master ? "#preview-frame" : "iframe");
  await expect(frame.locator("body")).toHaveClass(/cs-embedded/);
  if (file.startsWith("components.html")) {
    await expect(frame.locator("body")).toHaveClass(/is-gallery-ready/);
  } else {
    await expect(frame.locator("body")).toHaveAttribute("data-chat-theme", "clear-neutral");
  }
  if (file.startsWith("settings-iam.html") || file.startsWith("components.html")) {
    await expect(frame.locator("[data-iam-mock]")).toHaveAttribute("data-iam-ready", "true");
  }
  if (["settings.html", "settings-models.html", "settings-runtime.html", "settings-memory.html", "settings-diagnostics.html"].includes(file.split("::")[0]!)) {
    await expect(frame.locator("[data-settings-profile]")).toHaveAttribute("data-settings-ready", "true");
  }
  if (file.startsWith("settings-integrations.html")) {
    await expect(frame.locator("[data-integrations-workspace]")).toHaveAttribute("data-settings-tabs-ready", "true");
  }
  return frame;
}

/** Reveal an authored element through its containing tab and native ancestor disclosures. */
export async function revealSettingsSection(frame: FrameLocator, selector: string) {
  const target = frame.locator(selector).first();
  const tabName = await target.evaluate((element) => {
    const labelledBy = element.closest('[role="tabpanel"]')?.getAttribute("aria-labelledby");
    return labelledBy ? document.getElementById(labelledBy)?.textContent?.trim() : null;
  });
  if (tabName) await frame.getByRole("tab", { name: tabName, exact: true }).click();
  for (const details of await frame.locator("details").filter({ has: target }).all()) {
    if (await details.getAttribute("open") === null) await details.locator(":scope > summary").click();
  }
  return target;
}
