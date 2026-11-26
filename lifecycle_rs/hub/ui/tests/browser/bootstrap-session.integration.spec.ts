import { expect, test } from "@playwright/test";

test("real Python session exchange recovers from same-document launch and strips denied fragments", async ({ page, context }) => {
  const base = process.env.FDAI_BOOTSTRAP_TEST_URL;
  test.skip(!base, "Needs a fresh local create_setup_app server and an unused synthetic launch token.");
  const url = new URL(base!);
  expect(["127.0.0.1", "localhost", "[::1]"]).toContain(url.hostname);
  const origin = url.origin;
  const token = process.env.FDAI_BOOTSTRAP_TEST_TOKEN || "fixture-session-token";
  const actions: string[] = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname === "/setup/api/actions" || url.pathname === "/setup/api/decisions") actions.push(url.pathname);
  });
  await page.goto(`${origin}/setup`);
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(page.locator("#login")).toBeDisabled();
  const exchange = page.waitForResponse(response => response.url() === `${origin}/setup/api/session` && response.request().method() === "POST");
  await page.goto(`${origin}/setup#session=${encodeURIComponent(token)}`);
  await expect(page).toHaveURL(`${origin}/setup`);
  const response = await exchange;
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ authenticated: true });
  const headers = await response.request().allHeaders();
  expect(headers["content-type"]).toBe("application/json");
  expect(headers.origin).toBe(origin);
  expect(Object.keys(response.request().postDataJSON())).toEqual(["token"]);
  expect(response.request().postDataJSON().token === token).toBe(true);
  await expect(page.locator("#login")).toBeEnabled();
  await expect(page.getByRole("alert")).toBeHidden();
  const cookies = await context.cookies(`${origin}/setup`);
  expect(cookies.some(cookie => cookie.httpOnly && cookie.sameSite === "Strict" && cookie.path === "/setup")).toBe(true);
  expect(await page.evaluate(() => [location.hash, localStorage.length, sessionStorage.length])).toEqual(["", 0, 0]);
  const status = await page.evaluate(async () => {
    const response = await fetch("/setup/api/status", { credentials: "same-origin", cache: "no-store" });
    const data = await response.json();
    return { status: response.status, hasCsrf: typeof data.csrf_token === "string" && Boolean(data.csrf_token) };
  });
  expect(status).toEqual({ status: 200, hasCsrf: true });
  const denial = page.waitForResponse(response => response.url() === `${origin}/setup/api/session` && response.request().method() === "POST");
  await page.goto(`${origin}/setup#session=invalid-synthetic-launch-token`);
  await expect(page).toHaveURL(`${origin}/setup`);
  expect((await denial).status()).toBeGreaterThanOrEqual(400);
  await expect(page.getByRole("alert")).toContainText("Setup authentication failed");
  await expect(page.locator("#login")).toBeDisabled();
  expect(actions).toHaveLength(0);
});
