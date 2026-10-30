import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const assets = resolve("lifecycle/hub/src/fdai_lifecycle_hub/setup_ui");
const origin = "https://setup.test";
const account = { id: "00000000-0000-0000-0000-000000000001", name: "Test subscription", tenant_id: "test-tenant" };
const idle = () => ({
  phase: "idle", request_id: null, action: null, message: "Local setup is ready for a request.",
  error_code: null, accounts: [account], review: null, deployment_ready: false,
  console_url: null, csrf_token: "fixture-csrf",
});
const exactReview = () => ({
  id: "review-foundation", digest: "sha256:0123456789abcdef", title: "Apply exact Foundation plan",
  details: ["Create only the resources in the retained plan.", "<img src=x onerror=alert(1)>"],
  confirmation_required: "APPLY exact plan", expires_at: "2099-01-01T00:00:00Z",
});

async function fixture(page: Page, initial: Record<string, unknown> = idle()) {
  let state = initial;
  let statusFails = false;
  let actionFails = false;
  let rejection = "";
  const posts: { path: string; body: Record<string, unknown>; headers: Record<string, string>; pageUrl: string }[] = [];
  const requests: string[] = [];
  await page.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push(url.pathname);
    expect(url.origin).toBe(origin);
    if (request.method() === "POST") {
      posts.push({ path: url.pathname, body: request.postDataJSON(), headers: request.headers(), pageUrl: page.url() });
      if (actionFails) return route.abort("connectionfailed");
      if (rejection) return route.fulfill({ status: 409, json: { error: rejection } });
      return route.fulfill({ json: { authenticated: true } });
    }
    if (url.pathname === "/setup/api/status") {
      if (statusFails) return route.abort("connectionfailed");
      return route.fulfill({ json: state });
    }
    const file = url.pathname === "/setup" || url.pathname === "/setup/" ? "index.html" : url.pathname.split("/").pop();
    expect(["index.html", "setup.css", "setup.js"]).toContain(file);
    return route.fulfill({
      body: await readFile(resolve(assets, file!)),
      contentType: file!.endsWith(".js") ? "text/javascript" : file!.endsWith(".css") ? "text/css" : "text/html",
      headers: { "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'" },
    });
  });
  return {
    posts, requests, set: (value: Record<string, unknown>) => { state = value; },
    failStatus: () => { statusFails = true; }, failAction: () => { actionFails = true; },
    reject: (message: string) => { rejection = message; },
    open: async (fragment = "") => {
      await page.goto(`${origin}/setup${fragment}`);
      await expect(page.locator("#phase")).not.toHaveText("Connecting");
    },
    refresh: async () => {
      await page.locator("#refresh").click();
      await expect(page.locator("#refresh")).toBeEnabled();
    },
  };
}

test("fragment session is exchanged once, removed before exchange, and never persisted", async ({ page }) => {
  const app = await fixture(page);
  await app.open("#session=fixture-session-token");
  expect(app.posts).toHaveLength(1);
  expect(app.posts[0].body).toEqual({ token: "fixture-session-token" });
  expect(app.posts[0].headers["x-fdai-csrf"]).toBeUndefined();
  expect(app.posts[0].headers.origin).toBe(origin);
  expect(app.posts[0].pageUrl).toBe(`${origin}/setup`);
  expect(await page.evaluate(() => [location.hash, localStorage.length, sessionStorage.length])).toEqual(["", 0, 0]);
  await page.getByRole("button", { name: "List subscriptions" }).click();
  await expect.poll(() => app.posts.length).toBe(2);
  expect(app.posts[1].body).toEqual({ action: "accounts", payload: {} });
  expect(app.posts[1].headers["x-fdai-csrf"]).toBe("fixture-csrf");
  expect(app.posts[1].headers["content-type"]).toBe("application/json");
  await app.refresh();
  expect(app.posts).toHaveLength(2);
});

test("same-document launcher navigation exchanges a new fragment and strips denied tokens", async ({ page }) => {
  const app = await fixture(page);
  await app.open();
  await page.goto(`${origin}/setup#session=fixture-session-token`);
  await expect(page).toHaveURL(`${origin}/setup`);
  await expect.poll(() => app.posts.length).toBe(1);
  expect(app.posts[0].body).toEqual({ token: "fixture-session-token" });
  expect(app.posts[0].pageUrl).toBe(`${origin}/setup`);
  await expect(page.locator("#login")).toBeEnabled();
  app.reject("Invalid launch token.");
  await page.goto(`${origin}/setup#session=invalid-synthetic-launch-token`);
  await expect(page).toHaveURL(`${origin}/setup`);
  await expect(page.getByRole("alert")).toContainText("Setup authentication failed");
  await expect(page.locator("#login")).toBeDisabled();
  expect(app.posts.map(item => item.path)).toEqual(["/setup/api/session", "/setup/api/session"]);
});

test("source installation uses the exact payload and preserves form input on failure", async ({ page }) => {
  const app = await fixture(page);
  await app.open();
  await page.locator("#subscription").selectOption(account.id);
  await page.locator("#region").fill("exampleregion");
  await page.locator("#cost").fill("1200");
  await page.getByRole("radio", { name: /Build from a clean/ }).check();
  await page.locator("#source-root").fill("/approved/source-checkout");
  app.failAction();
  await page.getByRole("button", { name: "Authorize preparation" }).click();
  await expect(page.getByRole("alert")).toContainText("outcome is unknown");
  expect(app.posts).toHaveLength(1);
  expect(app.posts[0].body).toEqual({ action: "install", payload: {
    subscription_id: account.id, region: "exampleregion", monthly_cost_ceiling: 1200,
    artifact_source: "source", source_root: "/approved/source-checkout",
  } });
  await app.refresh();
  expect(app.posts).toHaveLength(1);
  await expect(page.locator("#source-root")).toHaveValue("/approved/source-checkout");
});

test("signed images are default and private or oversized key files never reach an action", async ({ page }) => {
  const app = await fixture(page);
  await app.open();
  await expect(page.getByRole("radio", { name: /Signed prebuilt/ })).toBeChecked();
  await page.locator("#subscription").selectOption(account.id);
  await page.locator("#region").fill("exampleregion");
  await page.locator("#cost").fill("1200");
  const privateKeyLabel = "PRIVATE KEY";
  const privateFixture = [
    `-----BEGIN ${privateKeyLabel}-----`, "not-a-key", `-----END ${privateKeyLabel}-----`,
  ].join("\n");
  await page.locator("#key-file").setInputFiles({
    name: "private.pem", mimeType: "text/plain", buffer: Buffer.from(privateFixture),
  });
  await expect(page.getByRole("alert")).toContainText("Private keys");
  await expect(page.locator("#public-key")).toHaveValue("");
  await page.locator("#key-file").setInputFiles({ name: "large.pem", mimeType: "text/plain", buffer: Buffer.alloc(4097, "A") });
  await expect(page.getByRole("alert")).toContainText("4 KiB");
  expect(app.posts).toHaveLength(0);
  const key = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n-----END PUBLIC KEY-----";
  await page.locator("#public-key").fill(key);
  await page.getByRole("button", { name: "Authorize preparation" }).click();
  await expect.poll(() => app.posts.length).toBe(1);
  expect(app.posts[0].body).toEqual({ action: "install", payload: {
    subscription_id: account.id, region: "exampleregion", monthly_cost_ceiling: 1200,
    artifact_source: "hub", hub_public_key: key,
  } });
});

test("exact plan remains inert text and requires its exact confirmation", async ({ page }) => {
  const review = exactReview();
  const app = await fixture(page, { ...idle(), phase: "review", request_id: "request-1", action: "install", review });
  await app.open();
  await expect(page.locator("#review-heading")).toBeFocused();
  await expect(page.locator("#review-details")).toContainText("<img src=x onerror=alert(1)>");
  await expect(page.locator("#review-details img")).toHaveCount(0);
  await expect(page.locator("#approve")).toBeDisabled();
  await page.locator("#confirmation").fill("apply exact plan");
  await expect(page.locator("#approve")).toBeDisabled();
  await page.locator("#confirmation").fill(review.confirmation_required);
  await expect(page.locator("#approve")).toBeEnabled();
  const firstDetail = await page.locator("#review-details li").first().elementHandle();
  await app.refresh();
  await expect(page.locator("#confirmation")).toHaveValue(review.confirmation_required);
  expect(await firstDetail!.evaluate(node => node === document.querySelector("#review-details li"))).toBe(true);
  await page.locator("#approve").click();
  await expect.poll(() => app.posts.length).toBe(1);
  expect(app.posts[0].body).toEqual({
    request_id: "request-1", review_id: review.id, digest: review.digest,
    approved: true, confirmation: review.confirmation_required,
  });
});

test("a revised digest clears confirmation and expired reviews fail closed", async ({ page }) => {
  const review = exactReview();
  const app = await fixture(page, { ...idle(), phase: "review", request_id: "request-1", review });
  await app.open();
  await page.locator("#confirmation").fill(review.confirmation_required);
  app.set({ ...idle(), phase: "review", request_id: "request-1", review: { ...review, digest: "sha256:changed" } });
  await app.refresh();
  await expect(page.locator("#confirmation")).toHaveValue("");
  app.set({ ...idle(), phase: "review", request_id: "request-1", review: { ...review, expires_at: "2000-01-01T00:00:00Z" } });
  await app.refresh();
  await expect(page.locator("#expired")).toBeVisible();
  await expect(page.locator("#approve")).toBeDisabled();
  expect(app.posts).toHaveLength(0);
});

test("decline has no confirmation requirement and is bound to the exact review", async ({ page }) => {
  const review = exactReview();
  const app = await fixture(page, { ...idle(), phase: "review", request_id: "request-1", review });
  await app.open();
  await page.locator("#decline").click();
  await expect.poll(() => app.posts.length).toBe(1);
  expect(app.posts[0].body).toEqual({
    request_id: "request-1", review_id: review.id, digest: review.digest, approved: false, confirmation: "",
  });
});

for (const phase of ["blocked", "failed", "interrupted"]) {
  test(`${phase} exposes explicit inspect and resume without replaying the job`, async ({ page }) => {
    const app = await fixture(page, { ...idle(), phase, request_id: "request-1", error_code: "example_failure" });
    await app.open();
    await expect(page.locator("#recovery-section")).toBeVisible();
    await expect(page.locator("#install")).toBeDisabled();
    await expect(page.locator("#login")).toBeEnabled();
    await expect(page.locator("#accounts")).toBeDisabled();
    await expect(page.locator("#console-link")).not.toHaveAttribute("href");
    await page.locator("#inspect").click();
    await expect.poll(() => app.posts.length).toBe(1);
    await expect(page.locator("#resume")).toBeEnabled();
    await page.locator("#resume").click();
    await expect.poll(() => app.posts.length).toBe(2);
    expect(app.posts.map(item => item.body)).toEqual([
      { action: "inspect", payload: {} }, { action: "resume", payload: {} },
    ]);
  });
}

test("Console requires both verified readiness and an absolute safe HTTPS URL", async ({ page }) => {
  const app = await fixture(page, { ...idle(), phase: "working", console_url: "https://console.example.invalid/" });
  await app.open();
  await expect(page.locator("#console-link")).not.toHaveAttribute("href");
  app.set({ ...idle(), phase: "ready", deployment_ready: false, console_url: "https://console.example.invalid/" });
  await app.refresh();
  await expect(page.locator("#phase")).toHaveText("Readiness not verified");
  await expect(page.locator("#console-link")).not.toHaveAttribute("href");
  for (const url of ["javascript:alert(1)", "http://console.example.invalid/", "//console.example.invalid/", "https://user:password@console.example.invalid/"]) {
    app.set({ ...idle(), phase: "ready", deployment_ready: true, console_url: url });
    await app.refresh();
    await expect(page.locator("#console-link")).not.toHaveAttribute("href");
    await expect(page.locator("#console-unavailable")).toBeVisible();
  }
  app.set({ ...idle(), phase: "ready", deployment_ready: true, console_url: "https://console.example.invalid/" });
  await app.refresh();
  await expect(page.locator("#console-link")).toBeVisible();
  await expect(page.locator("#console-link")).toHaveAttribute("href", "https://console.example.invalid/");
  await expect(page.locator("#recovery-section")).toBeHidden();
});

test("lost status disables approval and invalid status cannot become readiness", async ({ page }) => {
  const review = exactReview();
  const app = await fixture(page, { ...idle(), phase: "review", request_id: "request-1", review });
  await app.open();
  await page.locator("#confirmation").fill(review.confirmation_required);
  await expect(page.locator("#approve")).toBeEnabled();
  app.set({ phase: "ready", deployment_ready: true, console_url: "https://console.example.invalid/" });
  await app.refresh();
  await expect(page.getByRole("alert")).toContainText("invalid status");
  await expect(page.locator("#approve")).toBeDisabled();
  await expect(page.locator("#console-link")).not.toHaveAttribute("href");
  app.set({ ...idle(), phase: "review", request_id: "request-1", review });
  await app.refresh();
  app.failStatus();
  await app.refresh();
  await expect(page.locator("#approve")).toBeDisabled();
  await expect(page.locator("#phase")).toHaveText("Status unavailable");
  expect(app.posts).toHaveLength(0);
});

test("safe API errors are explicit inert text and never retried", async ({ page }) => {
  const app = await fixture(page);
  await app.open();
  app.reject("Exact approval required. <strong>Not applied.</strong>");
  await page.locator("#login").click();
  await expect(page.getByRole("alert")).toHaveText("Exact approval required. <strong>Not applied.</strong>");
  await expect(page.locator("#notice strong")).toHaveCount(0);
  await page.locator("#locale").selectOption("ko");
  await expect(page.getByRole("alert")).toContainText("Exact approval required.");
  expect(app.posts).toHaveLength(1);
});

test("visible status polling pauses while hidden and never submits a job", async ({ page }) => {
  const app = await fixture(page, { ...idle(), phase: "working", request_id: "request-1", action: "install" });
  await app.open();
  await expect(page.locator("#skeleton")).toBeVisible();
  await expect(page.locator("#status-live")).toHaveAttribute("aria-busy", "true");
  const count = app.requests.filter(path => path === "/setup/api/status").length;
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(2200);
  expect(app.requests.filter(path => path === "/setup/api/status")).toHaveLength(count);
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect.poll(() => app.requests.filter(path => path === "/setup/api/status").length).toBeGreaterThan(count);
  expect(app.posts).toHaveLength(0);
});

test("English fallback, Korean selector, long content, keyboard and desktop geometry", async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(navigator, "language", { get: () => "fr-FR" }); });
  const app = await fixture(page);
  await app.open();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.getByRole("heading", { name: "Set up FDAI in Azure" })).toBeVisible();
  await page.locator("#locale").selectOption("ko");
  await expect(page.locator("html")).toHaveAttribute("lang", "ko");
  await expect(page.getByRole("heading", { name: "Azure에 FDAI 설치" })).toBeVisible();
  await page.getByRole("button", { name: "Azure 로그인", exact: true }).focus();
  await expect(page.locator("#login")).toBeFocused();
  expect(await page.locator("#login").evaluate(node => getComputedStyle(node).outlineStyle)).not.toBe("none");
  await page.keyboard.press("Enter");
  await expect.poll(() => app.posts.length).toBe(1);
  app.set({ ...idle(), phase: "review", request_id: "opaque".repeat(40), review: {
    ...exactReview(), title: "실제 계획 검토 ".repeat(20), details: ["긴 식별자와 한국어 설명 ".repeat(50), "a".repeat(400)],
  } });
  await app.refresh();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  for (const selector of ["#review-details", "#review-digest", "#message"]) {
    expect(await page.locator(selector).evaluate(node => node.scrollWidth <= node.clientWidth)).toBe(true);
  }
});

test("constrained and mobile viewports retain controls, Korean scope and no overflow", async ({ page }) => {
  const app = await fixture(page, { ...idle(), phase: "review", request_id: "x".repeat(180), review: exactReview() });
  await app.open();
  await page.locator("#locale").selectOption("ko");
  for (const size of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(size);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await expect(page.locator("#review-section")).toBeVisible();
    await expect(page.locator(".scope-notes")).toBeVisible();
    await page.locator("#confirmation").fill("APPLY exact plan");
    await expect(page.locator("#approve")).toBeEnabled();
    for (const selector of ["#approve", "#decline", "#refresh", "#locale", "#confirmation"]) {
      const box = await page.locator(selector).boundingBox();
      expect(box!.height).toBeGreaterThanOrEqual(44);
    }
  }
});
