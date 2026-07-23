import { expect, test, type Page, type Response } from "@playwright/test";

const ROUTES = [
  "/overview",
  "/live",
  "/incidents",
  "/agents",
  "/approvals",
  "/provisioning",
  "/onboarding",
  "/processes",
  "/workflow-apps",
  "/scheduler-runs",
  "/automation-blueprints",
  "/scheduled-continuations",
  "/conversation-delivery",
  "/audit",
  "/browser-evidence",
  "/forecast-learning",
  "/conversation-search",
  "/reports",
  "/trace",
  "/root-cause-analysis",
  "/architecture",
  "/ontology",
  "/pantheon",
  "/agent-activity",
  "/handover",
  "/rules",
  "/workflow-builder",
  "/capabilities",
  "/skills",
  "/documents",
  "/blast-radius",
  "/promotion-gates",
  "/context-selection-comparisons",
  "/scope",
  "/operating-outcomes",
  "/control-assurance",
  "/verticals",
  "/trust-routing",
  "/llm-cost",
  "/settings/general",
  "/settings/models",
  "/settings/memory",
  "/settings/iam",
  "/settings/integrations",
  "/settings/diagnostics",
  "/labs",
] as const;

function isReadApiResponse(response: Response): boolean {
  const configured = process.env.FDAI_E2E_READ_API_URL;
  if (configured) return response.url().startsWith(configured.replace(/\/$/, ""));
  return new URL(response.url()).port === (process.env.FDAI_E2E_READ_API_PORT ?? "8012");
}

async function waitForPanel(page: Page): Promise<void> {
  await expect(page.locator("main")).toBeVisible();
  await expect(page.locator("main [aria-busy='true']")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator("main h1, main h2").first()).toBeVisible();
  await page.waitForTimeout(250);
}

for (const routePath of ROUTES) {
  test(`${routePath} renders through the live read API without panel failures`, async ({ page }) => {
    const failedResponses: string[] = [];
    const pageErrors: string[] = [];
    page.on("response", (response) => {
      if (isReadApiResponse(response) && response.status() >= 400) {
        failedResponses.push(`${response.status()} ${new URL(response.url()).pathname}`);
      }
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto(routePath, { waitUntil: "domcontentloaded" });
    await waitForPanel(page);

    await expect(page.locator("main .empty.error, main .panel-error-boundary")).toHaveCount(0);
    expect(pageErrors).toEqual([]);
    expect(failedResponses).toEqual([]);
  });
}

test("the live route inventory stays synchronized with the production registry", async ({ page }) => {
  await page.goto("/overview", { waitUntil: "domcontentloaded" });
  const registeredPaths = await page.evaluate(async () => {
    const module = await import("/src/router.ts");
    return module.registeredPanelRoutes().map((route: { path: string }) => route.path).sort();
  });

  expect([...ROUTES].sort()).toEqual(registeredPaths);
});

async function openCommandDeck(page: Page) {
  await page.goto("/settings/diagnostics", { waitUntil: "domcontentloaded" });
  await waitForPanel(page);
  await page.getByRole("button", { name: "Open command deck" }).click();
  return page.getByRole("complementary", { name: "Command deck" });
}

test("Command Deck returns a verified server-time answer", async ({ page }) => {
  const deck = await openCommandDeck(page);
  await deck.getByPlaceholder(/Ask anything/i).fill("What is the current time?");
  await deck.getByRole("button", { name: "Send" }).click();

  await expect(deck.getByRole("status").first()).toHaveText("Answer ready.", {
    timeout: 90_000,
  });
  await expect(deck.getByText(/The current time is .*\(UTC\)\./)).toBeVisible();
  await expect(deck.getByText("Verified", { exact: true })).toBeVisible();
});

test("Command Deck grounds public web search in Microsoft Learn", async ({ page }) => {
  const deck = await openCommandDeck(page);
  await deck.getByPlaceholder(/Ask anything/i).fill(
    "Search Microsoft Learn for Azure OpenAI Responses API web search guidance and cite the source.",
  );
  await deck.getByRole("button", { name: "Send" }).click();

  await expect(deck.getByRole("status").first()).toHaveText("Answer ready.", {
    timeout: 120_000,
  });
  await expect(deck).toContainText(
    "https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search",
  );
  await expect(deck).not.toContainText("public-web evidence could not be retrieved");
  await expect(deck.getByText("Consistent", { exact: true })).toBeVisible();
});
