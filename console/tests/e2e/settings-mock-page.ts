import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type Page } from "@playwright/test";

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
  return frame;
}
