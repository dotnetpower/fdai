import path from "node:path";
import { randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";
import {
  executeGoldenCampaign,
  loadGoldenCampaignCases,
  type GoldenCampaignCase,
  type GoldenCampaignTurn,
} from "./golden-semantic-campaign";

const AUTHENTICATED_STANDARD_STACK = process.env.FDAI_E2E_BASE_URL !== undefined &&
  process.env.FDAI_E2E_STORAGE_STATE !== undefined &&
  new URL(process.env.FDAI_E2E_BASE_URL).port === "5273";

async function submitGoldenTurn(
  page: Page,
  campaignCase: GoldenCampaignCase,
  phase: "readiness" | "full",
): Promise<GoldenCampaignTurn> {
  return page.evaluate(async ({ prompt, sessionId }) => {
    const { askBackendStream } = await import("/src/deck/backend-stream.ts");
    const reply = await askBackendStream(prompt, null, [], {
      onToken: () => undefined,
      sessionId,
      semanticPlanningProfile: "golden_campaign_no_t2",
    });
    return {
      source: reply.source,
      semanticReceipt: reply.semanticReceipt ?? null,
    };
  }, {
    prompt: campaignCase.prompt,
    sessionId: `golden-semantic:${phase}:${randomUUID()}`,
  });
}

test("authenticated standard Console gates the golden semantic campaign on readiness", async ({
  page,
}) => {
  test.skip(
    !AUTHENTICATED_STANDARD_STACK || process.env.FDAI_E2E_GOLDEN_CAMPAIGN !== "1",
    "requires authenticated standard ports and explicit golden campaign opt-in",
  );
  test.setTimeout(7_200_000);
  const cases = await loadGoldenCampaignCases(
    path.resolve(process.cwd(), "../eval/golden-dataset"),
  );
  const runFull = process.env.FDAI_E2E_GOLDEN_FULL === "1";
  const readinessCount = Number(process.env.FDAI_E2E_GOLDEN_READINESS_COUNT ?? "3");
  let chatRequestCount = 0;
  await page.route("**/chat/stream", async (route) => {
    const url = new URL(route.request().url());
    expect(url.port).toBe("8010");
    const body = route.request().postDataJSON() as Record<string, unknown>;
    expect(body["semantic_planning_profile"]).toBe("golden_campaign_no_t2");
    chatRequestCount += 1;
    await route.continue();
  });
  await restoreBrowserEntraSessionStorage(page);
  await page.goto("/architecture", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.locator(".shell")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("FDAI could not verify your access.")).toHaveCount(0, {
    timeout: 30_000,
  });

  const result = await executeGoldenCampaign(
    cases,
    (campaignCase, phase) => submitGoldenTurn(page, campaignCase, phase),
    {
      readinessCount,
      runFull,
      perTurnTimeoutMs: 90_000,
    },
  );

  expect(result.readinessCompleted).toBe(readinessCount);
  expect(result.stoppedReason).toBeNull();
  if (runFull) {
    expect(result.fullStarted).toBe(true);
    expect(result.fullCompleted).toBe(560);
    expect(chatRequestCount).toBe(readinessCount + 560);
  } else {
    expect(result.fullStarted).toBe(false);
    expect(result.fullCompleted).toBe(0);
    expect(chatRequestCount).toBe(readinessCount);
  }
});
