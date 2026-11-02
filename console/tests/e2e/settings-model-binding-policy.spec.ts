import { expect, test, type Page, type Route } from "@playwright/test";

const digest = `sha256:${"a".repeat(64)}`;
const capabilities = [
  capability("t1.embedding", "T1", "OpenAI", "text-embedding-3-small"),
  capability("t2.reasoner.primary", "T2", "OpenAI", "gpt-4o"),
  capability("t2.reasoner.secondary", "T2", "Anthropic", "claude-opus-4"),
];

const projection = {
  environment: "staging",
  region: "example-region",
  mixed_model_mode: "cross-check",
  resolved_metadata: {
    kind: "resolved-models",
    source: "protected-plan",
    as_of: "2026-08-24T00:00:00Z",
    digest,
  },
  discovery: { automatic: true, source: "llm-registry", status: "enabled" },
  provisioning: { automatic: false, status: "ready", resolved_count: 3, hil_only_count: 0 },
  capabilities,
  endpoint_inventory: [],
  narrator: {
    selection_scope: "per-user",
    revision: 0,
    requested: "auto",
    effective: "auto",
    fallback_reason: null,
    current_auto_pick: null,
    candidates: [],
  },
  web_search: {
    available: false,
    enabled: false,
    unavailable_reason: "not_configured",
    allowed_domains: [],
    revision: 0,
    can_manage: false,
    provider: "foundry-agent",
    project_configured: false,
    agent_name: null,
    model_deployment: null,
    provisioning_status: "not-configured",
    readiness_status: "unavailable",
    current_auto_pick: null,
    candidates: [],
  },
  model_routing: [],
  t2_selection_scope: "system-governed",
  t2_model_policy: {
    selection_scope: "governance-draft",
    invariant: "distinct-publisher",
    primary_candidates: [],
    secondary_candidates: [],
    active_primary: null,
    active_secondary: null,
    quorum_ready: true,
  },
  model_catalog: { available: false, source: "unavailable", region: null, models: [] },
  binding_policy: {
    environment: "staging",
    revision: 3,
    state: "draft",
    policy: {
      schema_version: "1.0.0",
      environment: "staging",
      revision: 3,
      expected_active_digest: digest,
      capabilities: Object.fromEntries(
        capabilities.map((item) => [item.name, { selection_mode: "auto" }]),
      ),
    },
    policy_digest: digest,
    can_manage: true,
    execution_authority: false,
    activation_boundary: "protected-plan-only",
  },
};

function capability(
  name: string,
  tier: "T1" | "T2",
  publisher: string,
  family: string,
): Record<string, unknown> {
  return {
    name,
    tier,
    publisher,
    family,
    version: "2025-04-14",
    sku: "Standard",
    selection_mode: "auto",
    status: "resolved",
    capacity_tpm: 10_000,
    capacity_unit: "tpm",
    capacity_value: 10_000,
    invocation: "always",
    reasons: [],
  };
}

async function installFixture(page: Page, onRead?: () => void): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/models/settings") {
      onRead?.();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(projection),
      });
      return;
    }
    await route.continue();
  };
  await page.route("**/api/**", handle);
  await page.route((url) => url.pathname.endsWith("/models/settings"), handle);
}

test("loads configuration without catalog discovery and pages a lazily loaded catalog", async ({ page }) => {
  await installFixture(page);
  let release!: () => void;
  const provider = new Promise<void>((resolve) => { release = resolve; });
  const reads: string[] = [];
  await page.route((url) => url.pathname.endsWith("/models/settings"), async (route) => {
    const summary = new URL(route.request().url()).searchParams.get("view") === "summary";
    reads.push(summary ? "summary" : "full");
    if (!summary) await provider;
    await route.fulfill({ json: {
      ...projection,
      model_catalog: summary ? {
        available: false, source: "azure-management-catalog", region: null,
        models: [], load_state: "deferred", as_of: null,
      } : {
        available: true, source: "azure-management-catalog", region: "example-region",
        as_of: "2026-11-02T00:00:00Z",
        models: Array.from({ length: 25 }, (_, index) => ({
          publisher: "OpenAI", family: `gpt-example-${index}`, version: "1",
          lifecycle: "GenerallyAvailable", skus: [], available_tpm: 10_000,
          deployments: [], deployed: false, provisionable: true, selectable: true,
          status: "provisionable",
        })),
      },
    } });
  });
  await page.goto("/settings/models?locale=en");
  await expect(page.getByRole("heading", { name: "Current model state" })).toBeVisible();
  expect(reads).toEqual(["summary"]);
  const navigation = page.getByRole("navigation", { name: "Model settings views" });
  await page.getByRole("button", { name: "Open catalog", exact: true }).click();
  await expect(page.getByText("Loading account model catalog...", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live GPT model catalog", exact: true })).toBeFocused();
  await expect(page.getByRole("region", { name: "Environment model bindings" })).toBeVisible();
  await navigation.getByRole("button", { name: "Overview", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Current model state" })).toBeVisible();
  release();
  await navigation.getByRole("button", { name: "Catalog and policy" }).click();
  await expect(page.locator(".settings-model-catalog-entry")).toHaveCount(12);
  await expect(page).toHaveURL(/model-view=catalog/);
  const pager = page.getByRole("navigation", { name: "Model catalog pages" });
  await expect(pager).toContainText("Models 1-12 of 25");
  await pager.getByRole("button", { name: "Next", exact: true }).click();
  await expect(pager).toContainText("Models 13-24 of 25");
  await page.getByRole("searchbox", { name: "Search models" }).fill("gpt-example-24");
  await expect(page.locator(".settings-model-catalog-entry")).toHaveCount(1);
  await expect(pager).toContainText("Models 1-1 of 1");
  await page.getByRole("button", { name: "Clear model search" }).click();
  await expect(page.locator(".settings-model-catalog-entry")).toHaveCount(12);
  expect(reads).toEqual(["summary", "full"]);
});

test("protects a domain draft that has not yet been added to the allowlist", async ({ page }) => {
  await installFixture(page);
  await page.route((url) => url.pathname.endsWith("/models/settings"), (route) =>
    route.fulfill({ json: {
      ...projection,
      web_search: {
        ...projection.web_search, available: true, enabled: true, can_manage: true,
        allowed_domains: ["example.com"], unavailable_reason: null, project_configured: true,
        agent_name: "example-search", model_deployment: "example-search-model",
        readiness_status: "ready", provisioning_status: "configured",
      },
    } })
  );
  await page.goto("/settings/models?locale=en&model-view=web-search");
  const draft = page.locator("#web-search-domain-draft");
  await draft.fill("docs.example.com");
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.locator("#settings-overlay nav").getByRole("link", { name: /^General/ }).click();
  await expect(page).toHaveURL(/\/settings\/models/);
  await expect(draft).toHaveValue("docs.example.com");
});

test("reports unsupported clipboard access instead of silently ignoring governance copy", async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: undefined });
  });
  await installFixture(page);
  const choice = (publisher: string, family: string) => ({
    publisher, family, version: null, catalog_status: "registry-only",
    deployments: [], available_tpm: 0, capacity_unit: "tpm", capacity_value: 0,
  });
  await page.route((url) => url.pathname.endsWith("/models/settings"), (route) =>
    route.fulfill({ json: {
      ...projection,
      t2_model_policy: {
        ...projection.t2_model_policy,
        primary_candidates: [choice("OpenAI", "example-primary")],
        secondary_candidates: [choice("Anthropic", "example-secondary")],
      },
    } })
  );
  await page.goto("/settings/models?locale=en&model-view=catalog");
  await page.getByRole("button", { name: "Copy governance draft", exact: true }).click();
  await expect(page.getByText("Clipboard access failed. Select the draft text and copy it manually.", {
    exact: true,
  })).toBeVisible();
});

test("keeps environment model binding bounded and authority-free", async ({ page }) => {
  await installFixture(page);
  await page.goto("/settings/models");
  await page.getByRole("navigation", { name: "Model settings views" })
    .getByRole("button", { name: "Catalog and policy" }).click();

  const editor = page.getByRole("region", { name: "Environment model bindings" });
  await expect(editor.getByText("Draft saved", { exact: true })).toBeVisible();
  await expect(editor.getByText("No direct activation.", { exact: true })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Save draft" })).toBeDisabled();
  await expect(page.getByRole("button", { name: /activate/i })).toHaveCount(0);

  await editor.getByRole("combobox").selectOption("t2.reasoner.primary");
  await editor.getByRole("button", { name: "Pinned" }).click();
  await expect(editor.getByRole("button", { name: "Save draft" })).toBeEnabled();
  await editor.getByRole("combobox").nth(1).selectOption("GlobalProvisionedManaged");
  const capacity = editor.getByRole("spinbutton");
  await expect(capacity).toHaveAttribute("min", "1");
  await expect(capacity).toHaveAttribute("max", "10000000");

  for (const selector of ["html", ".settings-models-route", ".settings-binding-editor"]) {
    const dimensions = await page.locator(selector).evaluate((element) => ({
      clientWidth: element.clientWidth,
      scrollWidth: element.scrollWidth,
    }));
    expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth);
  }
});

test("does not promise T1 narration when the narrator and secondary are unavailable", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page);
  await page.route("**/models/settings**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...projection,
        narrator: {
          ...projection.narrator,
          current_auto_pick: null,
          candidates: [],
        },
        t2_model_policy: {
          ...projection.t2_model_policy,
          active_secondary: null,
          quorum_ready: false,
        },
      }),
    });
  });
  await page.goto("/settings/models");

  await expect(page.locator(".settings-model-readiness-facts dd").first())
    .toHaveText("Unavailable");
  await expect(page.getByText("Independent secondary model is not configured", { exact: true }))
    .toBeVisible();
  await expect(page.getByText(
    "T2 judgments stay unavailable until a secondary model from another publisher is reviewed and activated.",
    { exact: true },
  )).toBeVisible();
  await expect(page.getByText("T1 narration remains available.", { exact: false })).toHaveCount(0);
});

test("separates Models into task-focused production views", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await installFixture(page);
  await page.goto("/settings/models");

  const navigation = page.getByRole("navigation", { name: "Model settings views" });
  await expect(navigation.getByRole("button")).toHaveText([
    "Overview",
    "Catalog and policy",
    "Routing and inventory",
    "Web search",
  ]);
  await expect(page.getByRole("heading", { name: "Current model state" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Environment model bindings" })).toBeHidden();

  await page.getByRole("button", { name: "Open catalog" }).click();
  await expect(page.getByRole("button", { name: "Refresh catalog" })).toBeFocused();
  await navigation.getByRole("button", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Review T2 policy" }).click();
  await expect(page.getByRole("heading", { name: "T2 model policy" })).toBeFocused();

  await expect(page.getByRole("heading", { name: "Environment model bindings" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Live GPT model catalog" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "T2 model policy" })).toBeVisible();

  await navigation.getByRole("button", { name: "Routing and inventory" }).click();
  await expect(page.getByRole("heading", { name: "Find routing and inventory evidence" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Model endpoint inventory" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Capability assignments" })).toBeVisible();

  await navigation.getByRole("button", { name: "Web search" }).click();
  await expect(page.getByRole("heading", { name: "Web search" })).toBeVisible();
  expect(await page.locator(".settings-models-route").evaluate((element) => (
    element.scrollWidth <= element.clientWidth
  ))).toBe(true);
});

test("preserves an unsaved binding draft across catalog refresh and view changes", async ({ page }) => {
  await installFixture(page);
  await page.goto("/settings/models");

  const navigation = page.getByRole("navigation", { name: "Model settings views" });
  await navigation.getByRole("button", { name: "Catalog and policy" }).click();
  const editor = page.getByRole("region", { name: "Environment model bindings" });
  await editor.getByRole("button", { name: "Pinned" }).click();
  await editor.getByRole("textbox").nth(0).fill("ExamplePublisher");
  await editor.getByRole("textbox").nth(1).fill("example-model");

  await page.getByRole("button", { name: "Refresh catalog" }).click();
  await expect(editor.getByRole("button", { name: "Pinned" })).toHaveAttribute("aria-pressed", "true");
  await expect(editor.getByRole("textbox").nth(0)).toHaveValue("ExamplePublisher");
  await expect(editor.getByRole("button", { name: "Save draft" })).toBeEnabled();

  await navigation.getByRole("button", { name: "Overview" }).click();
  await navigation.getByRole("button", { name: "Catalog and policy" }).click();
  await expect(editor.getByRole("textbox").nth(1)).toHaveValue("example-model");
});

test("preserves the binding draft and blocks resave after a revision conflict", async ({ page }) => {
  await installFixture(page);
  let conflictSeen = false;
  await page.route("**/models/settings**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ...projection,
        binding_policy: {
          ...projection.binding_policy,
          revision: conflictSeen ? 4 : 3,
          policy: {
            ...projection.binding_policy.policy,
            revision: conflictSeen ? 4 : 3,
          },
        },
      }),
    });
  });
  await page.route("**/models/binding-policy", async (route) => {
    conflictSeen = true;
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: "binding revision conflict" }),
    });
  });
  await page.goto("/settings/models");
  await page.getByRole("navigation", { name: "Model settings views" })
    .getByRole("button", { name: "Catalog and policy" }).click();

  const editor = page.getByRole("region", { name: "Environment model bindings" });
  await editor.getByRole("button", { name: "Pinned" }).click();
  await editor.getByRole("textbox").nth(0).fill("ExamplePublisher");
  await editor.getByRole("textbox").nth(1).fill("example-model");
  await editor.getByRole("button", { name: "Save draft" }).click();

  await expect(editor.getByRole("alert")).toContainText("The saved binding changed elsewhere");
  await expect(editor.getByRole("textbox").nth(0)).toHaveValue("ExamplePublisher");
  await expect(editor.getByRole("textbox").nth(1)).toHaveValue("example-model");
  await expect(editor.getByRole("button", { name: "Save draft" })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Request assessment" })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Request plan" })).toBeDisabled();
  await expect(editor.getByRole("button", { name: "Discard changes" })).toBeEnabled();
});

test("keeps production Models usable at the mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installFixture(page);
  await page.goto("/settings/models");

  const navigation = page.getByRole("navigation", { name: "Model settings views" });
  for (const button of await navigation.getByRole("button").all()) {
    expect(await button.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
    await button.click();
    expect(await page.locator(".settings-models-route").evaluate((element) => (
      element.scrollWidth <= element.clientWidth
    ))).toBe(true);
    const shortTargets = await page.locator(
      ".settings-models-route button:visible, .settings-models-route input:not([type='checkbox']):visible, .settings-models-route select:visible, .settings-models-route summary:visible, .settings-models-route .settings-toggle-control:visible",
    ).evaluateAll((elements) => elements.filter((element) => (
      element.getBoundingClientRect().height < 44
    )).map((element) => element.textContent?.trim() || element.getAttribute("aria-label")));
    expect(shortTargets, (await button.textContent()) ?? "Models workspace view").toEqual([]);
  }
});

test("guards unsaved Models changes when Settings closes", async ({ page }) => {
  await installFixture(page);
  await page.goto("/settings/models");
  await page.getByRole("navigation", { name: "Model settings views" })
    .getByRole("button", { name: "Catalog and policy" }).click();
  await page.getByRole("region", { name: "Environment model bindings" })
    .getByRole("button", { name: "Pinned" }).click();

  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toBe("Discard unsaved Settings changes?");
    await dialog.dismiss();
  });
  await page.getByRole("button", { name: "Close settings" }).click();
  await expect(page.getByRole("dialog", { name: "Settings" })).toBeVisible();

  page.once("dialog", async (dialog) => {
    await dialog.accept();
  });
  await page.getByRole("button", { name: "Close settings" }).click();
  await expect(page.getByRole("dialog", { name: "Settings" })).toHaveCount(0);
});

test("retries the same catalog refresh after a transient failure", async ({ page }) => {
  await installFixture(page);
  let refreshAttempts = 0;
  await page.route("**/models/settings**", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("refresh_catalog") !== "1") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(projection),
      });
      return;
    }
    refreshAttempts += 1;
    await route.fulfill(refreshAttempts === 1 ? {
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "catalog refresh unavailable" }),
    } : {
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(projection),
    });
  });
  await page.goto("/settings/models");
  await page.getByRole("navigation", { name: "Model settings views" })
    .getByRole("button", { name: "Catalog and policy" }).click();

  await page.getByRole("button", { name: "Refresh catalog" }).click();
  await expect(page.getByText("HTTP 503", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).click();

  await expect(page.getByText("HTTP 503", { exact: true })).toHaveCount(0);
  await expect.poll(() => refreshAttempts).toBe(2);
});

test("prefetches and reuses Models settings within the authenticated client", async ({ page }) => {
  let modelReads = 0;
  await installFixture(page, () => { modelReads += 1; });
  await page.goto("/settings/general");

  const dialog = page.getByRole("dialog", { name: "Settings" });
  const modelsLink = dialog.getByRole("link", { name: /Models/ });
  await modelsLink.hover();
  await expect.poll(() => modelReads).toBe(1);
  await modelsLink.click();
  await expect(page.getByRole("heading", { name: "Model lifecycle" })).toBeVisible();

  await dialog.getByRole("link", { name: /General/ }).click();
  await dialog.getByRole("link", { name: /Models/ }).click();
  await expect(page.getByRole("heading", { name: "Model lifecycle" })).toBeVisible();
  expect(modelReads).toBe(1);
});
