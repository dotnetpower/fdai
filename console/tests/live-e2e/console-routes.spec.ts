import { writeFile } from "node:fs/promises";

import { expect, test, type Locator, type Page, type Response } from "@playwright/test";

import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";
import { buildBrowserEvidenceProvenance } from "./browser-evidence-provenance";
import { judgeSemanticTurn } from "./ontology-query-assurance";

const AUTHENTICATED_EXTERNAL_STACK = Boolean(
  process.env.FDAI_E2E_BASE_URL && process.env.FDAI_E2E_STORAGE_STATE,
);

const ROUTES = [
  "/overview",
  "/live",
  "/incidents",
  "/agents",
  "/approvals",
  "/provisioning",
  "/onboarding",
  "/detection-readiness",
  "/configuration-baselines",
  "/processes",
  "/workflow-apps",
  "/scheduler-runs",
  "/automation-blueprints",
  "/scheduled-continuations",
  "/conversation-delivery",
  "/conversation-assurance",
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
  "/agent-oversight",
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
  "/settings/runtime-policies",
  "/settings/memory",
  "/settings/iam",
  "/settings/integrations",
  "/settings/diagnostics",
  "/labs",
] as const;

const OPTIONAL_UNAVAILABLE_RESPONSES = new Map<string, ReadonlySet<number>>([
  ["/capabilities", new Set([404])],
  ["/finops", new Set([404])],
  ["/hil-queue", new Set([503])],
  ["/kpi/autonomy", new Set([404, 501])],
  ["/kpi/promotion-gates", new Set([404, 501, 503])],
  ["/me/context", new Set([503])],
  ["/onboarding", new Set([404])],
  ["/skills", new Set([404])],
]);

function isOperatorApiResponse(response: Response): boolean {
  const configured = process.env.FDAI_E2E_OPERATOR_API_URL;
  if (configured) return response.url().startsWith(configured.replace(/\/$/, ""));
  return new URL(response.url()).port === (process.env.FDAI_E2E_OPERATOR_API_PORT ?? "8020");
}

function isExpectedUnavailableResponse(response: Response): boolean {
  const url = new URL(response.url());
  return OPTIONAL_UNAVAILABLE_RESPONSES.get(url.pathname)?.has(response.status()) === true;
}

function parseDoneFrame(body: string): Record<string, unknown> {
  for (const frame of body.split(/\r?\n\r?\n/)) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (event !== "done" || dataLines.length === 0) continue;
    const parsed = JSON.parse(dataLines.join("\n")) as unknown;
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
  }
  throw new Error("chat stream did not contain a valid done frame");
}

async function waitForPanel(page: Page): Promise<void> {
  await expect(page.locator("main")).toBeVisible();
  await expect(page.locator("main [aria-busy='true']")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.locator("main h1, main h2").first()).toBeVisible();
  await page.waitForTimeout(250);
}

for (const routePath of ROUTES) {
  test(`${routePath} renders through the live Operator API without panel failures`, async ({ page }) => {
    const failedResponses: string[] = [];
    const pageErrors: string[] = [];
    page.on("response", (response) => {
      if (
        isOperatorApiResponse(response)
        && response.status() >= 400
        && !isExpectedUnavailableResponse(response)
      ) {
        failedResponses.push(`${response.status()} ${new URL(response.url()).pathname}`);
      }
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await page.goto(routePath, { waitUntil: "domcontentloaded" });
    await waitForPanel(page);

    await expect(page.locator(
      "main .empty.error, main .panel-error-boundary, main .state-block.state-error",
    )).toHaveCount(0);
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
  const deck = page.getByRole("complementary", { name: "Command deck" });
  if (!(await deck.isVisible())) {
    await page.getByRole("button", { name: "Open command deck" }).click();
  }
  await expect(deck).toBeVisible();
  return deck;
}

async function revealSemanticReceipt(
  deck: Locator,
  requestId: string,
  projectionId: string,
): Promise<Locator> {
  const receipt = deck.getByTestId("semantic-projection-receipt")
    .filter({ hasText: requestId })
    .filter({ hasText: projectionId })
    .last();
  await expect(receipt).toBeAttached();
  await receipt.evaluate((element) => {
    for (let ancestor = element.parentElement; ancestor; ancestor = ancestor.parentElement) {
      if (ancestor instanceof HTMLDetailsElement) ancestor.open = true;
    }
  });
  await expect(receipt).toBeVisible();
  return receipt;
}

test("Command Deck returns a verified server-time answer", async ({ page }) => {
  test.setTimeout(120_000);
  const deck = await openCommandDeck(page);
  await deck.getByPlaceholder(/Ask anything/i).fill("What is the current time?");
  await deck.getByRole("button", { name: "Send" }).click();

  await expect(deck.getByRole("status").first()).toHaveText("Answer ready.", {
    timeout: 90_000,
  });
  await expect(deck.getByText(/The current time is .*\(UTC\)\./)).toBeVisible();
  await expect(deck.getByText("Verified", { exact: true })).toBeVisible();
});

test("Command Deck renders the exact governed ontology projection receipt", async ({ page }, testInfo) => {
  test.skip(
    !AUTHENTICATED_EXTERNAL_STACK,
    "requires an external Console and Browser Entra storage state",
  );
  const operatorApiUrl = process.env.FDAI_E2E_OPERATOR_API_URL;
  if (!operatorApiUrl) {
    throw new Error("FDAI_E2E_OPERATOR_API_URL is required for external four-stage evidence");
  }
  const runConfiguration = {
    schema_version: "1.0.0",
    authentication: "browser_entra",
    console_origin: new URL(process.env.FDAI_E2E_BASE_URL!).origin,
    operator_api_origin: new URL(operatorApiUrl).origin,
    question_contract: "all_queryable_ontology_types_in_current_scope",
  };
  const provenance = buildBrowserEvidenceProvenance(
    process.env.FDAI_E2E_SOURCE_REVISION,
    process.env.FDAI_E2E_WORKSPACE_PATCH_SHA256,
    runConfiguration,
  );
  test.setTimeout(150_000);
  await restoreBrowserEntraSessionStorage(page);
  const deck = await openCommandDeck(page);
  await deck.getByRole("button", { name: "New conversation" }).click();
  await page.evaluate(() => {
    const testWindow = window as Window & { __fdaiChatStreamBody?: Promise<string> };
    const originalFetch = window.fetch;
    window.fetch = async (...args) => {
      const response = await originalFetch.apply(window, args);
      const input = args[0];
      const requestUrl = typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
      const method = args[1]?.method ?? (input instanceof Request ? input.method : "GET");
      if (
        method.toUpperCase() === "POST" &&
        new URL(requestUrl, window.location.href).pathname === "/chat/stream"
      ) {
        testWindow.__fdaiChatStreamBody = (async () => {
          const reader = response.clone().body?.getReader();
          if (!reader) throw new Error("chat stream clone did not expose a response body");
          const decoder = new TextDecoder();
          let body = "";
          for (;;) {
            const chunk = await reader.read();
            if (chunk.done) return body + decoder.decode();
            body += decoder.decode(chunk.value, { stream: true });
            const completeFrames = body.split(/\r?\n\r?\n/).slice(0, -1);
            if (completeFrames.some((frame) => /^event:\s*done\s*$/m.test(frame))) {
              void reader.cancel().catch(() => undefined);
              return body;
            }
          }
        })();
        window.fetch = originalFetch;
      }
      return response;
    };
  });
  const responsePromise = page.waitForResponse((response) => (
    isOperatorApiResponse(response) &&
    new URL(response.url()).pathname === "/chat/stream" &&
    response.request().method() === "POST"
  ));
  await deck.getByPlaceholder(/Ask anything/i).fill(
    "List all queryable ontology object types visible to this operator in the current scope.",
  );
  await deck.getByRole("button", { name: "Send" }).click();

  await expect(deck.getByRole("status").first()).toHaveText("Answer ready.", {
    timeout: 120_000,
  });
  const response = await responsePromise;
  const requestPayload = response.request().postDataJSON() as Record<string, unknown>;
  const streamBody = await page.evaluate(async () => {
    const captured = (window as Window & { __fdaiChatStreamBody?: Promise<string> })
      .__fdaiChatStreamBody;
    if (!captured) throw new Error("chat stream body capture was not initialized");
    return captured;
  });
  const done = parseDoneFrame(streamBody);
  const judgment = judgeSemanticTurn(done.semantic_receipt, done.verification);
  expect(judgment.passed, judgment.failure_reason).toBe(true);
  const semanticReceipt = judgment.receipt!;
  if (semanticReceipt.disposition !== "answered") {
    throw new Error(`governed ontology turn did not answer: ${JSON.stringify({
      disposition: semanticReceipt.disposition,
      unavailable_reason: semanticReceipt.unavailable_reason,
      request_id: semanticReceipt.request_id,
      projection_id: semanticReceipt.projection_id,
      semantic_route: semanticReceipt.semantic_route,
    })}`);
  }
  expect(requestPayload.request_id).toBe(semanticReceipt.request_id);

  await deck.getByText("Run record", { exact: true }).last().click();
  const receipt = await revealSemanticReceipt(
    deck,
    semanticReceipt.request_id,
    semanticReceipt.projection_id,
  );
  await expect(receipt.getByTestId("semantic-projection-id")).toHaveText(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
  );
  await expect(receipt.getByTestId("semantic-request-id")).toHaveText(
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
  );
  await expect(receipt.getByTestId("semantic-route")).toHaveText("verified_query_plan");
  await expect(receipt.getByTestId("semantic-unavailable-reason")).toHaveText("None");
  for (const testId of [
    "semantic-ontology-release-digest",
    "semantic-principal-manifest-digest",
    "semantic-plan-digest",
    "semantic-execution-receipt-digest",
  ]) {
    await expect(receipt.getByTestId(testId)).toHaveText(/^sha256:[0-9a-f]{64}$/);
  }
  await expect(receipt.getByTestId("semantic-execution-authority")).toHaveText("false");

  const rendered = {
    projection_id: await receipt.getByTestId("semantic-projection-id").innerText(),
    request_id: await receipt.getByTestId("semantic-request-id").innerText(),
    semantic_route: await receipt.getByTestId("semantic-route").innerText(),
    unavailable_reason: await receipt.getByTestId("semantic-unavailable-reason").innerText(),
    ontology_release_digest: await receipt.getByTestId("semantic-ontology-release-digest").innerText(),
    principal_manifest_digest: await receipt.getByTestId("semantic-principal-manifest-digest").innerText(),
    plan_digest: await receipt.getByTestId("semantic-plan-digest").innerText(),
    execution_receipt_digest: await receipt.getByTestId("semantic-execution-receipt-digest").innerText(),
    execution_authority: await receipt.getByTestId("semantic-execution-authority").innerText(),
  };
  expect(rendered).toEqual({
    projection_id: semanticReceipt.projection_id,
    request_id: semanticReceipt.request_id,
    semantic_route: semanticReceipt.semantic_route,
    unavailable_reason: "None",
    ontology_release_digest: semanticReceipt.ontology_release_digest,
    principal_manifest_digest: semanticReceipt.principal_manifest_digest,
    plan_digest: semanticReceipt.plan_digest,
    execution_receipt_digest: semanticReceipt.execution_receipt_digest,
    execution_authority: "false",
  });

  const evidence = {
    schema_version: "1.0.0",
    evidence_type: "governed_request_to_authenticated_console",
    captured_at: new Date().toISOString(),
    passed: true,
    ...provenance,
    run_configuration: runConfiguration,
    authentication: "browser_entra",
    stages: {
      operator_publication: {
        request_id: semanticReceipt.request_id,
        request_matches_projection: true,
      },
      core_processing: {
        disposition: semanticReceipt.disposition,
        semantic_route: semanticReceipt.semantic_route,
        ontology_release_digest: semanticReceipt.ontology_release_digest,
        principal_manifest_digest: semanticReceipt.principal_manifest_digest,
        plan_digest: semanticReceipt.plan_digest,
        execution_receipt_digest: semanticReceipt.execution_receipt_digest,
        execution_authority: false,
        checks_completed: judgment.verification?.checks_completed,
        checks_total: judgment.verification?.checks_total,
        evidence_ref_count: judgment.verification?.evidence_refs.length,
      },
      exact_operator_projection_read: {
        projection_id: semanticReceipt.projection_id,
        request_id: semanticReceipt.request_id,
        semantic_receipt_matches_typed_contract: true,
      },
      authenticated_console_rendering: {
        rendered,
        exact_match: true,
      },
    },
  };
  const artifactPath = testInfo.outputPath("governed-request-console-receipt.json");
  await writeFile(artifactPath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
  await testInfo.attach("governed-request-console-receipt", {
    path: artifactPath,
    contentType: "application/json",
  });
});

test("Command Deck grounds public web search in Microsoft Learn", async ({ page }) => {
  test.setTimeout(150_000);
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
