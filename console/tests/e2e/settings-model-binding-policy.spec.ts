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

async function installFixture(page: Page): Promise<void> {
  const handle = async (route: Route): Promise<void> => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api(?=\/)/, "");
    if (path === "/models/settings") {
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
  await page.route("**/models/settings", handle);
}

test("keeps environment model binding bounded and authority-free", async ({ page }) => {
  await installFixture(page);
  await page.goto("/settings/models");

  const editor = page.getByRole("region", { name: "Environment model bindings" });
  await expect(editor.getByText("Draft saved", { exact: true })).toBeVisible();
  await expect(editor.getByText("No direct activation.", { exact: true })).toBeVisible();
  await expect(editor.getByRole("button", { name: "Save draft" })).toBeEnabled();
  await expect(page.getByRole("button", { name: /activate/i })).toHaveCount(0);

  await editor.getByRole("combobox").selectOption("t2.reasoner.primary");
  await editor.getByRole("button", { name: "Pinned" }).click();
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
