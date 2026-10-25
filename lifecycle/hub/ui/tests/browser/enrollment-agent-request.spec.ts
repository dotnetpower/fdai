import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const entities = [{
  entity_id: "core", kind: "workload", managed: false, ownership_gap: "ownership_unproven",
  release_id: "1.4.0", health: "healthy",
}];
const base = {
  installation_id: "nginx-dev", installation_key_id: "installation-0123456789abcdef",
  requested_at: "2026-10-25T09:00:00+00:00", channel: "stable", version_range: ">=1.4.0 <2.0.0",
  region: "korea-central", entities, reported_at: "2026-10-25T08:59:00+00:00", schema_revision: 15,
};

for (const requester of [
  { name: "installation Agent", via: "agent", by: "00000000-0000-0000-0000-000000000000",
    label: "Requested by installation Agent 00000000" },
  { name: "operator", via: "operator", by: "approved-human", label: "Requested by operator" },
] as const) {
  test(`pending enrollment shows it was requested by the ${requester.name}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const writes: string[] = [];
    const pending = { ...base, requested_by: requester.by, requested_via: requester.via };
    await page.route("https://hub.test/**", async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === "/auth/config") return route.fulfill({ json: { profile: "local-development" } });
      if (path === "/v1/enrollments/bindable") return route.fulfill({ status: 404, json: { error: "not_found" } });
      if (path === "/v1/enrollments/pending") return route.fulfill({ json: { enrollments: [pending] } });
      if (path === "/v1/enrollments/pending/nginx-dev") return route.fulfill({ json: pending });
      if (route.request().method() !== "GET") {
        writes.push(path);
        return route.fulfill({ status: 500, json: { error: "unexpected_write" } });
      }
      const file = path.startsWith("/assets/") ? path : "/index.html";
      return route.fulfill({
        body: await readFile(resolve("dist", `.${file}`)),
        contentType: file.endsWith(".js") ? "text/javascript" :
          file.endsWith(".css") ? "text/css" : "text/html",
      });
    });

    await page.goto("https://hub.test/enrollments");
    await expect(page.getByRole("cell", {
      name: requester.via === "agent" ? "Installation Agent" : "Operator or file", exact: true,
    })).toBeVisible();
    await page.getByRole("link", { name: "nginx-dev" }).click();
    await expect(page.getByText(requester.label)).toBeVisible();
    const accept = page.getByRole("button", { name: "Accept enrollment" });
    await expect(page.getByLabel("Verified key id")).toHaveValue("");
    await expect(accept).toBeDisabled();
    await page.getByLabel("Approver").fill("operator@example.com");
    await expect(accept).toBeDisabled();
    await page.getByLabel("Verified key id").fill("installation-0123456789abcdef");
    await expect(accept).toBeEnabled();
    expect(await page.getByText("cannot accept or reject it").count()).toBe(
      requester.via === "agent" ? 1 : 0,
    );
    expect(writes).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    for (const width of [993, 390]) {
      await page.setViewportSize({ width, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    }
  });
}
