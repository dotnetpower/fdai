import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, type FrameLocator, type Page } from "@playwright/test";

// Opens the one Command deck mock (mocks/ui/deck.html) inside the design mock index. Repository UI
// fixtures are served in-process, so no design server, Console backend, or external endpoint runs.
export const root = fileURLToPath(new URL("../../../", import.meta.url));
export const origin = "http://127.0.0.1:5373";
export const promptPath = path.join(root, "mocks/ui/assets/prompts/system-prompt.example.md");

export interface DeckPage {
  readonly frame: FrameLocator;
  readonly requests: string[];
  readonly errors: string[];
}

export async function serveMockFiles(page: Page, requests: string[] = []) {
  await page.route(`${origin}/**`, async (route) => {
    requests.push(route.request().url());
    const pathname = decodeURIComponent(new URL(route.request().url()).pathname);
    const relative = pathname === "/" ? "/index.html" : pathname;
    const file = path.resolve(root, "." + relative);
    const allowed = file.startsWith(path.resolve(root) + path.sep)
      && (/\.(html|css|js|svg|png|woff2?)$/.test(file) || file === promptPath
        || /\/mocks\/ui\/fixtures\/adaptive\/[a-z-]+\.json$/.test(file.split(path.sep).join("/")));
    if (!allowed) {
      await route.fulfill({ status: 404, body: "Not a public UI fixture." });
      return;
    }
    await route.fulfill({ path: file });
  });
}

export async function openDeck(page: Page, query: Record<string, string>): Promise<DeckPage> {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await serveMockFiles(page, requests);
  await page.goto("about:blank");
  await page.goto(`${origin}/?deck=${Date.now()}#mocks/ui/deck.html?${new URLSearchParams(query)}`);
  const frame = page.frameLocator("#preview-frame");
  await expect(frame.locator("body")).toHaveAttribute("data-deck-state", "settled", { timeout: 15_000 });
  await expect(frame.locator("body")).toHaveClass(/cs-embedded/);
  return { frame, requests, errors };
}

export async function pressPreview(frame: FrameLocator, selector: string) {
  const preview = frame.locator("#ds-preview");
  if (!await preview.evaluate((element: HTMLDetailsElement) => element.open)) {
    await preview.locator(":scope > summary").click();
  }
  await frame.locator(selector).click();
}
