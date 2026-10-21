import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

for (const outcome of ["pending", "stale", "network"] as const) {
  test(`signed enrollment submission ${outcome}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const writes: { path: string; body: unknown }[] = [];
    await page.route("https://hub.test/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/auth/config") {
        return route.fulfill({ json: { profile: "local-development" } });
      }
      if (path === "/v1/enrollments/pending") {
        return route.fulfill({ json: { enrollments: [] } });
      }
      if (route.request().method() === "POST") {
        writes.push({ path, body: route.request().postDataJSON() });
        if (outcome === "network") return route.abort("connectionfailed");
        return route.fulfill(outcome === "pending" ? {
          status: 202, json: { enrollment: "pending", installation_key_id: "installation-test" },
        } : { status: 403, json: { error: "enrollment_proof_stale" } });
      }
      const file = path.startsWith("/assets/") ? path : "/index.html";
      return route.fulfill({
        body: await readFile(resolve("dist", `.${file}`)),
        contentType: file.endsWith(".js") ? "text/javascript" :
          file.endsWith(".css") ? "text/css" : "text/html",
      });
    });

    await page.goto("https://hub.test/enrollments");
    const submit = page.getByRole("button", { name: "Submit request", exact: true });
    await expect(submit).toBeDisabled();
    await page.getByLabel("Installation ID", { exact: true }).fill("nginx-dev");
    const signed = { signed_payload: "e30=", proof: "cHJvb2Y=" };
    await page.getByLabel("Signed request JSON", { exact: true }).setInputFiles({
      name: "request.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(signed)),
    });
    await submit.click();
    if (outcome === "pending") {
      await expect(page.getByRole("status")).toContainText("Request submitted as pending");
      await expect(submit).toBeDisabled();
    } else {
      await expect(page.getByRole("alert")).toContainText(
        outcome === "stale" ? "enrollment_proof_stale" : "Refresh before retrying",
      );
    }
    expect(writes).toEqual([{ path: "/v1/enrollments/nginx-dev/requests", body: signed }]);
    await expect(page.getByRole("button", { name: "Accept enrollment" })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    for (const width of [993, 390]) {
      await page.setViewportSize({ width, height: 844 });
      await expect(page.getByRole("heading", { name: "Submit a signed enrollment request" })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  });
}
