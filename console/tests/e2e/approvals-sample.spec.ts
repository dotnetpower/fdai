import { expect, test, type Page } from "@playwright/test";

async function openSampleApproval(page: Page) {
  await page.goto("/approvals?data=sample");
  const card = page.locator(".approval-card").first();
  await expect(card).toBeVisible();
  return card;
}

test("sample approval drill-downs stay within coherent synthetic evidence", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let card = await openSampleApproval(page);

  await expect(card.getByRole("link", { name: "ops.start-vm", exact: true })).toHaveCount(0);
  await expect(
    card.getByRole("link", { name: "sample-checkout-standby-vm-01", exact: true }),
  ).toHaveCount(0);
  await expect(
    card.getByRole("link", {
      name: "sample.compute.checkout-capacity.conflicting-evidence",
      exact: true,
    }),
  ).toHaveCount(0);

  await card.getByRole("link", { name: "Open incident" }).click();
  await expect(page).toHaveURL(
    /\/incidents\?status=all&correlation=sample-correlation-002&data=sample$/,
  );
  await expect(
    page.getByRole("heading", {
      name: "Checkout capacity recovery is waiting for approval",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);

  card = await openSampleApproval(page);
  await card.getByRole("link", { name: "Open trace" }).click();
  await expect(page).toHaveURL(
    /\/trace\?correlation=sample-correlation-002&data=sample$/,
  );
  await expect(page.locator(".trace-ready-workspace")).toBeVisible();
  await expect(page.locator(".trace-stage-select")).toHaveCount(3);

  card = await openSampleApproval(page);
  await card.getByRole("link", { name: "Open audit" }).click();
  await expect(page).toHaveURL(
    /\/audit\?correlation=sample-correlation-002&data=sample$/,
  );
  await expect(page.locator(".audit-record")).toHaveCount(3);

  card = await openSampleApproval(page);
  await card.getByRole("link", { name: "Open RCA" }).click();
  await expect(page).toHaveURL(
    /\/root-cause-analysis\?correlation=sample-correlation-002&data=sample$/,
  );
  await expect(page.locator(".rca-unavailable-state")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);

  for (const viewport of [
    { width: 993, height: 641 },
    { width: 390, height: 844 },
  ]) {
    await page.setViewportSize(viewport);
    await openSampleApproval(page);
    const geometry = await page.evaluate(() => ({
      client: document.documentElement.clientWidth,
      scroll: document.documentElement.scrollWidth,
    }));
    expect(geometry.scroll).toBeLessThanOrEqual(geometry.client);
  }
});

test("Slack handoff stays unavailable in sample mode on the actual approvals route", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const token = "x".repeat(43);
  await page.goto(`/approvals?data=sample&handoff=${token}`);
  const region = page.getByRole("region", { name: "Continue Slack approval" });
  await expect(region.getByRole("alert")).toContainText("cannot be used");
  await expect(page).not.toHaveURL(/handoff=/);
  await expect(region.getByRole("button", { name: "Dismiss handoff" })).toBeVisible();
  const geometry = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  expect(geometry.scroll).toBeLessThanOrEqual(geometry.width);
  await region.getByRole("button", { name: "Dismiss handoff" }).focus();
  await expect(region.getByRole("button", { name: "Dismiss handoff" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(region).toHaveCount(0);

  await page.goto(`/approvals?data=sample&locale=ko&handoff=${token}`);
  const korean = page.getByRole("region", { name: "Slack 승인 계속하기" });
  await expect(korean.getByRole("alert")).toContainText("Slack 인계를 사용할 수 없습니다");
  expect(await page.evaluate(() => document.documentElement.scrollWidth))
    .toBeLessThanOrEqual(await page.evaluate(() => document.documentElement.clientWidth));
  await korean.getByRole("button", { name: "인계 닫기" }).click();
  await expect(korean).toHaveCount(0);
});
