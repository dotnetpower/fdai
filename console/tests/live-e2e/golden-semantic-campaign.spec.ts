import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";
import {
  executeGoldenCampaign,
  executeGoldenSequence,
  loadGoldenCampaignCases,
  selectGoldenCampaignRange,
  type GoldenCampaignCase,
  type GoldenCampaignTurn,
} from "./golden-semantic-campaign";

const AUTHENTICATED_STANDARD_STACK = process.env.FDAI_E2E_BASE_URL !== undefined &&
  process.env.FDAI_E2E_STORAGE_STATE !== undefined &&
  new URL(process.env.FDAI_E2E_BASE_URL).port === "5273";
const DATASET_ROOT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../eval/golden-dataset",
);
const PRESSURE_URL = "http://127.0.0.1:8768/pressure";

async function probePressure(): Promise<string | null> {
  try {
    const response = await fetch(PRESSURE_URL);
    if (!response.ok) return "pressure_probe_unavailable";
    const value = await response.json() as Record<string, unknown>;
    return value["pressure"] === false && value["signals"] === 0
      ? null
      : "runtime_pressure";
  } catch {
    return "pressure_probe_unavailable";
  }
}

function campaignRange(): { readonly start: number; readonly end: number } | null {
  const rawStart = process.env.FDAI_E2E_GOLDEN_START_INDEX;
  const rawEnd = process.env.FDAI_E2E_GOLDEN_END_INDEX_EXCLUSIVE;
  if (rawStart === undefined && rawEnd === undefined) return null;
  if (rawStart === undefined || rawEnd === undefined) {
    throw new Error("golden campaign range requires both bounds");
  }
  const start = Number(rawStart);
  const end = Number(rawEnd);
  if (!Number.isInteger(start) || !Number.isInteger(end)) {
    throw new Error("golden campaign range bounds MUST be integers");
  }
  return { start, end };
}

async function submitGoldenTurn(
  page: Page,
  campaignCase: GoldenCampaignCase,
  _phase: "readiness" | "full",
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
    sessionId: randomUUID(),
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
  const variationKind = process.env.FDAI_E2E_GOLDEN_VARIATION;
  const loadedCases = await loadGoldenCampaignCases(
    DATASET_ROOT,
    variationKind === undefined
      ? {}
      : { variationKinds: [variationKind], expectedCaseCount: 70 },
  );
  const runFull = process.env.FDAI_E2E_GOLDEN_FULL === "1";
  const readinessCount = Number(process.env.FDAI_E2E_GOLDEN_READINESS_COUNT ?? "3");
  const range = campaignRange();
  if (range !== null && variationKind !== "direct") {
    throw new Error("golden campaign range requires the direct variation");
  }
  const cases = range === null
    ? loadedCases
    : selectGoldenCampaignRange(loadedCases, range.start, range.end);
  let chatRequestCount = 0;
  await page.route("**/chat/stream", async (route) => {
    const url = new URL(route.request().url());
    expect(url.port).toBe("8010");
    const body = route.request().postDataJSON() as Record<string, unknown>;
    expect(body["semantic_planning_profile"]).toBe("golden_campaign_no_t2");
    expect(typeof body["prompt"]).toBe("string");
    expect(body).not.toHaveProperty("case_id");
    expect(body).not.toHaveProperty("oracle");
    expect(body).not.toHaveProperty("runtime_context");
    expect(body).not.toHaveProperty("conversation_context");
    chatRequestCount += 1;
    await route.continue();
  });
  await restoreBrowserEntraSessionStorage(page);
  await page.goto("/architecture", { waitUntil: "domcontentloaded", timeout: 30_000 });
  await expect(page.locator(".shell")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("FDAI could not verify your access.")).toHaveCount(0, {
    timeout: 30_000,
  });
  if (range !== null) {
    const result = await executeGoldenSequence(
      cases,
      (campaignCase, phase) => submitGoldenTurn(page, campaignCase, phase),
      { perTurnTimeoutMs: 90_000, pressureProbe: probePressure },
    );
    expect(result.stoppedReason).toBeNull();
    expect(result.completed).toBe(cases.length);
    expect(chatRequestCount).toBe(cases.length);
    return;
  }
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
    expect(result.fullCompleted).toBe(cases.length);
    expect(chatRequestCount).toBe(readinessCount + cases.length);
  } else {
    expect(result.fullStarted).toBe(false);
    expect(result.fullCompleted).toBe(0);
    expect(chatRequestCount).toBe(readinessCount);
  }
});
