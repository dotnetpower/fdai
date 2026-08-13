import type { Page } from "@playwright/test";

export const BROWSER_ENTRA_SESSION_BOOTSTRAP_KEY = "fdai:e2e:browser-entra-session";

export async function restoreBrowserEntraSessionStorage(page: Page): Promise<void> {
  await page.addInitScript((bootstrapKey) => {
    const serialized = localStorage.getItem(bootstrapKey);
    if (serialized === null) return;
    localStorage.removeItem(bootstrapKey);

    const entries = JSON.parse(serialized) as unknown;
    if (!Array.isArray(entries)) return;
    for (const entry of entries) {
      if (
        Array.isArray(entry) &&
        entry.length === 2 &&
        typeof entry[0] === "string" &&
        typeof entry[1] === "string"
      ) {
        sessionStorage.setItem(entry[0], entry[1]);
      }
    }
  }, BROWSER_ENTRA_SESSION_BOOTSTRAP_KEY);
}
