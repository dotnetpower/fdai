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
      if (path === "/v1/enrollments/bindable") {
        return route.fulfill({ status: 404, json: { error: "not_found" } });
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

const bindableInstallations = [
  { installation_id: "alpha-enrolled", status: "enrolled" },
  { installation_id: "beta-pending", status: "pending" },
  { installation_id: "gamma-new", status: "unrequested" },
  { installation_id: "delta-new", status: "unrequested" },
];

async function stubHub(page: import("@playwright/test").Page, bindable: () => { status: number; json: unknown }) {
  const writes: { path: string; body: unknown }[] = [];
  let bindableReads = 0;
  await page.route("https://hub.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/auth/config") return route.fulfill({ json: { profile: "local-development" } });
    if (path === "/v1/enrollments/bindable") {
      bindableReads += 1;
      return route.fulfill(bindable());
    }
    if (path === "/v1/enrollments/pending") return route.fulfill({ json: { enrollments: [] } });
    if (route.request().method() === "POST") {
      writes.push({ path, body: route.request().postDataJSON() });
      return route.fulfill({ status: 202, json: { enrollment: "pending", installation_key_id: "installation-test" } });
    }
    const file = path.startsWith("/assets/") ? path : "/index.html";
    return route.fulfill({
      body: await readFile(resolve("dist", `.${file}`)),
      contentType: file.endsWith(".js") ? "text/javascript" :
        file.endsWith(".css") ? "text/css" : "text/html",
    });
  });
  return { writes, bindableReads: () => bindableReads };
}

const signedFile = {
  name: "request.json", mimeType: "application/json",
  buffer: Buffer.from(JSON.stringify({ signed_payload: "e30=", proof: "cHJvb2Y=" })),
};

test("bound installations are chosen from a dropdown with status and no typed ID", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let installations = bindableInstallations;
  const api = await stubHub(page, () => ({ status: 200, json: { installations } }));
  await page.goto("https://hub.test/enrollments");
  const select = page.getByLabel("Installation", { exact: true });
  await expect(select).toHaveValue("gamma-new");
  await expect(page.getByLabel("Installation ID", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Create the file with `fdai-lifecycle-hub sign-enrollment` inside the installation boundary; it prints the key id to compare at approval."))
    .toBeVisible();
  const options = select.locator("option");
  await expect(options).toHaveText([
    "alpha-enrolled (enrolled)", "beta-pending (request pending)",
    "gamma-new (not requested yet)", "delta-new (not requested yet)",
  ]);
  await expect(options.nth(0)).toHaveJSProperty("disabled", true);
  await expect(options.nth(1)).toHaveJSProperty("disabled", true);
  await expect(options.nth(3)).toHaveJSProperty("disabled", false);

  await select.selectOption("delta-new");
  await page.getByLabel("Signed request JSON", { exact: true }).setInputFiles(signedFile);
  installations = bindableInstallations.map(item =>
    item.installation_id === "delta-new" ? { ...item, status: "pending" } : item);
  await page.getByRole("button", { name: "Submit request", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Request submitted as pending");
  expect(api.writes).toEqual([{
    path: "/v1/enrollments/delta-new/requests", body: { signed_payload: "e30=", proof: "cHJvb2Y=" },
  }]);
  await expect.poll(api.bindableReads).toBe(2);
  await expect(select).toHaveValue("gamma-new");
  await expect(options.nth(3)).toHaveText("delta-new (request pending)");
  await expect(options.nth(3)).toHaveJSProperty("disabled", true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("a bound list with nothing left to request disables submission", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const api = await stubHub(page, () => ({
    status: 200, json: { installations: bindableInstallations.slice(0, 2) },
  }));
  await page.goto("https://hub.test/enrollments");
  await page.getByLabel("Signed request JSON", { exact: true }).setInputFiles(signedFile);
  await expect(page.getByText("Every bound installation already has a pending request or is enrolled."))
    .toBeVisible();
  await expect(page.getByRole("button", { name: "Submit request", exact: true })).toBeDisabled();
  expect(api.writes).toEqual([]);
});

for (const [label, response] of [
  ["404", { status: 404, json: { error: "not_found" } }],
  ["an empty list", { status: 200, json: { installations: [] } }],
] as const) {
  test(`falls back to the typed Installation ID on ${label}`, async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const api = await stubHub(page, () => response);
    await page.goto("https://hub.test/enrollments");
    const input = page.getByLabel("Installation ID", { exact: true });
    await expect(input).toBeVisible();
    await expect(page.locator("select")).toHaveCount(0);
    await input.fill("nginx-dev");
    await page.getByLabel("Signed request JSON", { exact: true }).setInputFiles(signedFile);
    await page.getByRole("button", { name: "Submit request", exact: true }).click();
    await expect(page.getByRole("status")).toContainText("Request submitted as pending");
    expect(api.writes.map(write => write.path)).toEqual(["/v1/enrollments/nginx-dev/requests"]);
  });
}
