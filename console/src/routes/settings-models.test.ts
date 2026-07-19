import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthContext } from "../auth";
import {
  saveNarratorPreference,
  saveWebSearchSettings,
} from "./settings-models.command";
import {
  DEFAULT_WEB_SEARCH_DOMAINS,
  decodeModelSettings,
  draftRevisionIsCurrent,
  modelChoiceKey,
  normalizeAndValidateDomains,
  projectionGenerationIsCurrent,
  renderT2GovernanceDraft,
  t2PairIsValid,
  webSearchControlsDisabled,
} from "./settings-models.model";

const payload = {
  region: "example-region",
  mixed_model_mode: "hil-only",
  resolved_metadata: {
    kind: "generated-file",
    source: "resolved-models.json",
    as_of: "2026-07-17T08:00:00+00:00",
  },
  discovery: { automatic: true, source: "rule-catalog/llm-registry.yaml", status: "enabled" },
  provisioning: { automatic: true, status: "degraded", resolved_count: 1, hil_only_count: 1 },
  capabilities: [{
    name: "t1.judge",
    tier: "T1",
    publisher: "OpenAI",
    family: "gpt-mini",
    status: "resolved",
    capacity_tpm: 1000,
    invocation: "always",
    reasons: [],
    user_selectable: false,
  }],
  endpoint_inventory: [{
    binding_id: "t2-primary-prod",
    capability: "t2.reasoner.primary",
    provider_kind: "azure-openai",
    route_kind: "apim-gateway",
    api_style: "azure-openai",
    deployment: "t2-primary",
    api_version: "2024-10-21",
    auth_kind: "entra",
    publisher: "OpenAI",
    family: "gpt-4o",
    version: "2024-08-06",
    capacity_unit: "ptu",
    capacity_value: 30,
    features: {
      streaming: true,
      embeddings: false,
      structured_output: true,
      tool_calling: true,
    },
    discovery_source: "apim-management",
    verified_at: "2026-07-17T00:00:00+00:00",
    managed_by: "catalog-and-resolver",
    user_selectable: false,
  }],
  narrator: {
    selection_scope: "per-user",
    revision: 1,
    requested: "auto",
    effective: "auto",
    fallback_reason: null,
    current_auto_pick: "narrator-fast",
    candidates: [{
      deployment: "narrator-fast",
      family: "gpt-fast",
      status: "available",
      total_p50_ms: 800,
      total_p95_ms: 1200,
      total_samples: 8,
      ttft_p50_ms: 220,
      ttft_p95_ms: 410,
      ttft_samples: 5,
    }],
  },
  web_search: {
    available: true,
    enabled: true,
    allowed_domains: [...DEFAULT_WEB_SEARCH_DOMAINS],
    revision: 1,
    can_manage: true,
    provider: "azure-responses",
    current_auto_pick: "narrator-fast",
    candidates: [],
  },
  model_routing: [{
    role: "t2.reasoner.primary",
    selected_deployment: "primary-b",
    selection_reason: "failover_after_1_candidate_failure",
    selected_at: "2026-07-17T10:00:00+00:00",
    candidates: [{
      deployment: "primary-a",
      status: "recovered",
      failure_kind: null,
      cooldown_seconds: 0,
      updated_at: "2026-07-17T10:00:00+00:00",
    }],
  }],
  t2_selection_scope: "system-governed",
  t2_model_policy: {
    selection_scope: "governance-draft",
    invariant: "distinct-publisher",
    primary_candidates: [
      {
        publisher: "OpenAI",
        family: "gpt-4o",
        version: "2024-11-20",
        catalog_status: "deployed",
        deployments: ["gpt-4o"],
        available_tpm: 100000,
      },
      { publisher: "OpenAI", family: "gpt-4.1" },
    ],
    secondary_candidates: [
      { publisher: "Anthropic", family: "claude-opus-4" },
      { publisher: "MistralAI", family: "mistral-large-2" },
    ],
    active_primary: { publisher: "OpenAI", family: "gpt-4o" },
    active_secondary: null,
    quorum_ready: false,
  },
  model_catalog: {
    available: true,
    source: "azure-control-plane",
    region: "example-region",
    models: [{
      publisher: "OpenAI",
      family: "gpt-5.4",
      version: "2026-03-05",
      lifecycle: "GenerallyAvailable",
      skus: [{ name: "GlobalStandard", available_tpm: 125000 }],
      available_tpm: 125000,
      deployments: ["gpt-5.4"],
      deployed: true,
      provisionable: true,
      selectable: true,
      status: "deployed",
    }],
  },
};

afterEach(() => vi.unstubAllGlobals());

describe("Settings Models contracts", () => {
  it("rejects a projection response superseded by another load or save", () => {
    expect(projectionGenerationIsCurrent(9, 8)).toBe(false);
    expect(projectionGenerationIsCurrent(9, 9)).toBe(true);
  });

  it("preserves a draft edited after a save request began", () => {
    expect(draftRevisionIsCurrent(8, 7)).toBe(false);
    expect(draftRevisionIsCurrent(8, 8)).toBe(true);
  });

  it("decodes true TTFT separately from total latency", () => {
    const decoded = decodeModelSettings(payload);

    expect(decoded.narrator.candidates[0]?.ttftP50Ms).toBe(220);
    expect(decoded.narrator.candidates[0]?.totalP50Ms).toBe(800);
    expect(decoded.t2SelectionScope).toBe("system-governed");
    expect(decoded.t2ModelPolicy.primaryCandidates).toHaveLength(2);
    expect(decoded.t2ModelPolicy.activePrimary?.family).toBe("gpt-4o");
    expect(decoded.t2ModelPolicy.quorumReady).toBe(false);
    expect(decoded.t2ModelPolicy.primaryCandidates[0]?.catalogStatus).toBe("deployed");
    expect(decoded.modelCatalog.models[0]).toMatchObject({
      family: "gpt-5.4",
      deployed: true,
      availableTpm: 125000,
    });
    expect(decoded.resolvedMetadata.source).toBe("resolved-models.json");
    expect(decoded.resolvedMetadata.asOf).toBe("2026-07-17T08:00:00+00:00");
    expect(decoded.webSearch.enabled).toBe(true);
    expect(decoded.webSearch.available).toBe(true);
    expect(decoded.webSearch.allowedDomains).toEqual(DEFAULT_WEB_SEARCH_DOMAINS);
    expect(decoded.webSearch.revision).toBe(1);
    expect(decoded.modelRouting[0]?.selectedDeployment).toBe("primary-b");
    expect(decoded.modelRouting[0]?.candidates[0]?.status).toBe("recovered");
    expect(decoded.endpointInventory[0]).toMatchObject({
      routeKind: "apim-gateway",
      providerKind: "azure-openai",
      capacityUnit: "ptu",
      capacityValue: 30,
      userSelectable: false,
    });
  });

  it("validates and renders a distinct-publisher T2 governance draft", () => {
    const primary = modelChoice("OpenAI", "gpt-4o");
    const secondary = modelChoice("Anthropic", "claude-opus-4");

    expect(modelChoiceKey(primary)).toBe("OpenAI|gpt-4o");
    expect(t2PairIsValid(primary, secondary)).toBe(true);
    expect(renderT2GovernanceDraft(primary, secondary)).toContain(
      '- {publisher: "Anthropic", family: "claude-opus-4"}',
    );
    expect(renderT2GovernanceDraft(primary, secondary)).toContain("preserve SKU and capacity");
    expect(renderT2GovernanceDraft(primary, secondary)).toContain(
      "re-check catalog and quota",
    );
  });

  it("rejects a same-publisher T2 governance draft", () => {
    const primary = modelChoice("OpenAI", "gpt-4o");
    const secondary = modelChoice("OpenAI", "gpt-4.1");

    expect(t2PairIsValid(primary, secondary)).toBe(false);
    expect(() => renderT2GovernanceDraft(primary, secondary)).toThrow("distinct publishers");
  });

  it("marks a quota-backed undeployed primary for resolver and Terraform provisioning", () => {
    const primary = {
      ...modelChoice("OpenAI", "gpt-5.4"),
      catalogStatus: "provisionable" as const,
      version: "2026-03-05",
      availableTpm: 125000,
    };
    const secondary = modelChoice("Anthropic", "claude-opus-4");

    expect(renderT2GovernanceDraft(primary, secondary)).toContain(
      "Bootstrap resolver and Terraform will provision the primary",
    );
  });

  it("degrades an older projection without T2 policy to an unavailable draft builder", () => {
    const { t2_model_policy: _omitted, ...olderPayload } = payload;

    const decoded = decodeModelSettings(olderPayload);

    expect(decoded.t2ModelPolicy.primaryCandidates).toEqual([]);
    expect(decoded.t2ModelPolicy.secondaryCandidates).toEqual([]);
    expect(decoded.t2ModelPolicy.quorumReady).toBe(false);
  });

  it.each([
    ["available", { ...payload.web_search, available: "yes" }],
    ["enabled", { ...payload.web_search, enabled: "yes" }],
    ["domains", { ...payload.web_search, allowed_domains: "learn.microsoft.com" }],
    ["revision", { ...payload.web_search, revision: 1.5 }],
  ])("rejects malformed web-search %s", (_label, webSearch) => {
    expect(() => decodeModelSettings({ ...payload, web_search: webSearch })).toThrow();
  });

  it("saves the authenticated user's narrator preference", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        preferred_narrator_model: "narrator-fast",
        expected_revision: 1,
      });
      expect((init?.headers as Record<string, string>).authorization).toBe("Bearer token");
      return new Response(JSON.stringify({
        ...payload,
        narrator: { ...payload.narrator, requested: "narrator-fast", effective: "narrator-fast" },
      }), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    const saved = await saveNarratorPreference(
      auth,
      "http://127.0.0.1:8030",
      "narrator-fast",
      1,
    );

    expect(saved.narrator.effective).toBe("narrator-fast");
  });

  it("saves deployment-global web-search settings with revision", async () => {
    const fetchMock = vi.fn(async (url: string | URL, init?: RequestInit) => {
      expect(String(url)).toBe("http://127.0.0.1:8030/models/web-search-settings");
      expect(JSON.parse(String(init?.body))).toEqual({
        enabled: true,
        allowed_domains: ["learn.microsoft.com"],
        expected_revision: 1,
      });
      expect((init?.headers as Record<string, string>).authorization).toBe("Bearer token");
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    await saveWebSearchSettings(auth, "http://127.0.0.1:8030", {
      enabled: true,
      allowedDomains: ["learn.microsoft.com"],
      expectedRevision: 1,
    });

    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("normalizes domains and removes duplicates and blank lines", () => {
    const result = normalizeAndValidateDomains(
      " Learn.Microsoft.com \n\nlearn.microsoft.com\n NVD.NIST.GOV ",
      true,
    );

    expect(result).toEqual({
      domains: ["learn.microsoft.com", "nvd.nist.gov"],
      error: null,
      invalidDomains: [],
    });
  });

  it.each([
    "https://learn.microsoft.com/path",
    "learn.microsoft.com/path",
    "learn.microsoft.com:443",
    "*.microsoft.com",
  ])("rejects non-host domain input %s", (domain) => {
    const result = normalizeAndValidateDomains(domain, true);
    expect(result.error).toBe("invalid");
    expect(result.invalidDomains).toEqual([domain]);
  });

  it("requires at least one domain only while enabled", () => {
    expect(normalizeAndValidateDomains("", true).error).toBe("required");
    expect(normalizeAndValidateDomains("", false).error).toBeNull();
  });

  it("rejects more than 100 unique hosts", () => {
    const domains = Array.from({ length: 101 }, (_, index) => `host-${index}.example.com`);
    expect(normalizeAndValidateDomains(domains.join("\n"), true).error).toBe("too-many");
  });

  it("preserves the 409 status for conflict reload handling", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: "revision conflict" }),
      { status: 409, headers: { "content-type": "application/json" } },
    )));
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    await expect(saveWebSearchSettings(auth, "http://127.0.0.1:8030", {
      enabled: true,
      allowedDomains: ["learn.microsoft.com"],
      expectedRevision: 1,
    })).rejects.toMatchObject({
      status: 409,
      message: "revision conflict",
    });
  });

  it("disables controls for non-owners and while saving", () => {
    expect(webSearchControlsDisabled(false, false)).toBe(true);
    expect(webSearchControlsDisabled(true, true)).toBe(true);
    expect(webSearchControlsDisabled(true, false)).toBe(false);
  });

  it.each([
    { ...payload, provisioning: { ...payload.provisioning, resolved_count: -1 } },
    {
      ...payload,
      narrator: {
        ...payload.narrator,
        candidates: [{ ...payload.narrator.candidates[0], ttft_p50_ms: -1 }],
      },
    },
    { ...payload, discovery: { ...payload.discovery, status: "unknown" } },
  ])("rejects invalid model metrics or statuses %#", (value) => {
    expect(() => decodeModelSettings(value)).toThrow();
  });
});

function modelChoice(publisher: string, family: string) {
  return {
    publisher,
    family,
    version: null,
    catalogStatus: "registry-only" as const,
    deployments: [],
    availableTpm: 0,
  };
}
