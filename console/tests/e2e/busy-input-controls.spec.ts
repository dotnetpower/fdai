import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

const sessionId = "synthetic-session";

function projection(mode = "queue", pending: object[] = [], active = true, revision = 1) {
  return { session_id: sessionId, mode, active, revision, pending };
}

async function openDeck(page: Page, locale: "en" | "ko" = "en") {
  await page.goto(`/overview?locale=${locale}`);
  await page.locator(".deck-invoke").click();
  await expect(page.locator(".deck-input")).toBeVisible();
  return page.locator(".deck-busy");
}

test("desktop follow-up uses exact observed session and keeps local Stop separate", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  let observed = projection();
  let exactSession = "";
  const requests: { method: string; body: Record<string, unknown> }[] = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith("/chat/busy-input") && request.method() === "GET") {
      exactSession = url.searchParams.get("session_id") ?? "";
      observed = { ...observed, session_id: exactSession };
      return route.fulfill({ json: observed });
    }
    if (url.pathname.includes("/chat/busy-input") && request.method() !== "GET") {
      const body = request.postDataJSON() as Record<string, unknown>;
      requests.push({ method: request.method(), body });
      if (url.pathname.endsWith("/chat/busy-input")) {
        observed = projection("queue", [{
          input: { input_id: body.input_id, expires_at: "2026-09-26T12:00:00Z" },
          sequence: 0, disposition: "queued", status: "pending",
        }], true, 2);
      } else if (url.pathname.endsWith("/mode")) {
        observed = projection("steer", observed.pending, true, 3);
      } else {
        observed = projection("steer", observed.pending, false, 4);
      }
      return route.fulfill({ status: 202, json: { accepted: true } });
    }
    return route.fulfill({ status: 404, json: { detail: "fixture unavailable" } });
  });
  const busy = await openDeck(page);
  // The fixture confirms only the exact session requested by the existing Deck.
  await expect(busy.getByText("Active turn - Queue mode - 0 pending")).toBeVisible();
  const input = page.locator(".deck-input");
  await input.fill("What changed?");
  await busy.getByRole("button", { name: "Submit follow-up" }).click();
  await expect(busy.getByText("Server shows follow-up queued.")).toBeVisible();
  await expect(input).toHaveValue("");
  await busy.getByText("Inspect 1 pending follow-up(s)").click();
  await expect(busy.getByText("Sequence 0: queued; expires 2026-09-26T12:00:00Z")).toBeVisible();
  expect(requests[0]?.body.session_id).toBe(exactSession);
  expect(requests[0]?.body).not.toHaveProperty("principal_id");
  await busy.getByLabel("Follow-up mode").selectOption("steer");
  await expect(busy.getByText("Active turn - Steer prose mode - 1 pending")).toBeVisible();
  await busy.getByRole("button", { name: "Request conversational cancel" }).click();
  await expect(busy.getByText(/Request pending confirmation/)).toBeVisible();
  expect(requests.map((item) => item.method)).toEqual(["POST", "PUT", "POST"]);
  expect(requests[1]?.body).toMatchObject({ session_id: exactSession, revision: 2, mode: "steer" });
  expect(requests[2]?.body).toMatchObject({ session_id: exactSession, revision: 3 });
  await expect(page.getByRole("button", { name: "Stop", exact: true })).toHaveCount(0);
  await expect(busy.getByRole("button", { name: "Refresh conversation state" })).toBeEnabled();
  await busy.getByRole("button", { name: "Refresh conversation state" }).focus();
  await expect(busy.getByRole("button", { name: "Refresh conversation state" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(busy.getByText("No active turn - Steer prose mode - 1 pending")).toBeVisible();
  const overflow = await page.evaluate(() => ({
    page: document.documentElement.scrollWidth > document.documentElement.clientWidth,
    deck: document.querySelector(".deck-overlay")!.scrollWidth >
      document.querySelector(".deck-overlay")!.clientWidth,
  }));
  expect(overflow).toEqual({ page: false, deck: false });
});

test("unavailable, malformed, mismatched, conflict and unconfirmed responses retain draft", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let getStatus = 404;
  let body: object = projection();
  let writeStatus = 202;
  let exactSession = "";
  let submittedId = "";
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    if (new URL(request.url()).pathname.endsWith("/chat/busy-input") && request.method() === "GET") {
      exactSession = new URL(request.url()).searchParams.get("session_id") ?? "";
      return route.fulfill({ status: getStatus, json: body });
    }
    if (new URL(request.url()).pathname.endsWith("/chat/busy-input") && request.method() === "POST") {
      submittedId = (request.postDataJSON() as { input_id: string }).input_id;
      return route.fulfill({ status: writeStatus, json: { disposition: "queued" } });
    }
    return route.fulfill({ status: 404, json: {} });
  });
  const busy = await openDeck(page);
  await page.locator(".deck-input").fill("Keep this draft");
  await expect(busy.getByText(/controls unavailable/)).toBeVisible();
  await expect(busy.getByRole("button", { name: "Submit follow-up" })).toHaveCount(0);
  for (const [status, payload] of [
    [503, projection()],
    [200, { ...projection(), session_id: "wrong" }],
    [200, { ...projection(), pending: [{ sequence: 0 }] }],
    [202, projection()],
  ] as const) {
    getStatus = status;
    body = payload;
    await busy.getByRole("button", { name: "Refresh conversation state" }).click();
    await expect(busy.getByText(/controls unavailable/)).toBeVisible();
    await expect(page.locator(".deck-input")).toHaveValue("Keep this draft");
  }
  getStatus = 200;
  body = { ...projection(), session_id: exactSession };
  await busy.getByRole("button", { name: "Refresh conversation state" }).click();
  await expect(busy.getByText("Active turn - Queue mode - 0 pending")).toBeVisible();
  writeStatus = 409;
  await busy.getByRole("button", { name: "Submit follow-up" }).click();
  await expect(busy.getByText(/Conversation changed/)).toBeVisible();
  await expect(page.locator(".deck-input")).toHaveValue("Keep this draft");
  writeStatus = 202;
  await busy.getByRole("button", { name: "Refresh conversation state" }).click();
  await busy.getByRole("button", { name: "Submit follow-up" }).click();
  await expect(busy.getByText(/Request pending confirmation/)).toBeVisible();
  await expect(page.locator(".deck-input")).toHaveValue("Keep this draft");
  await expect(busy.getByText(/Server shows follow-up/)).toHaveCount(0);
  await busy.getByRole("button", { name: "Refresh conversation state" }).click();
  await expect(busy.getByText(/Request pending confirmation/)).toBeVisible();
  await expect(busy.getByRole("button", { name: "Submit follow-up" })).toHaveCount(0);
  body = {
    ...projection("queue", [{
      input: { input_id: submittedId, expires_at: "2026-09-26T12:00:00Z" },
      sequence: 0, disposition: "queued", status: "pending",
    }], true, 2),
    session_id: exactSession,
  };
  await busy.getByRole("button", { name: "Refresh conversation state" }).click();
  await expect(busy.getByText("Server shows follow-up queued.")).toBeVisible();
  await expect(page.locator(".deck-input")).toHaveValue("");
});

test("Korean copy and keyboard controls fit a constrained deck", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    if (new URL(request.url()).pathname.endsWith("/chat/busy-input") && request.method() === "GET") {
      const session = new URL(request.url()).searchParams.get("session_id") ?? "";
      return route.fulfill({ json: {
        ...projection("steer", [{
          input: { input_id: "input-one", expires_at: "2026-09-26T12:00:00Z" },
          sequence: 0, disposition: "steered", status: "pending",
        }]), session_id: session,
      } });
    }
    return route.fulfill({ status: 404, json: {} });
  });
  const busy = await openDeck(page, "ko");
  await expect(busy.getByText("대화 후속 입력")).toBeVisible();
  await expect(busy.getByLabel("후속 입력 모드")).toBeVisible();
  await busy.getByText("대기 중인 후속 입력 1건 보기").click();
  await expect(busy.getByText("순서 0: 방향 조정 대기 중; 만료 2026-09-26T12:00:00Z")).toBeVisible();
  await busy.getByRole("button", { name: "대화 상태 새로고침" }).focus();
  await expect(busy.getByRole("button", { name: "대화 상태 새로고침" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(busy.getByLabel("후속 입력 모드")).toBeFocused();
  const fits = () => page.evaluate(() => {
    const deck = document.querySelector(".deck-overlay")!;
    const controls = document.querySelector(".deck-busy")!;
    const deckBounds = deck.getBoundingClientRect();
    const controlBounds = controls.getBoundingClientRect();
    return document.documentElement.scrollWidth <= document.documentElement.clientWidth &&
      deck.scrollWidth <= deck.clientWidth &&
      controlBounds.left >= deckBounds.left &&
      controlBounds.right <= deckBounds.right;
  });
  expect(await fits()).toBe(true);
  await page.setViewportSize({ width: 993, height: 641 });
  await expect(busy.getByText(/로컬 중지와 별개/)).toBeVisible();
  expect(await fits()).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await fits()).toBe(true);
});
