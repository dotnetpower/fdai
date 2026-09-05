import { afterEach, describe, expect, it, vi } from "vitest";
import type { AuthContext } from "../auth";
import {
  decodeDocumentOcrProposalReceipt,
  decodeModelBindingProposalReceipt,
  requestDocumentOcrPlan,
  requestModelBindingOperation,
  saveDocumentOcrPolicy,
  saveNarratorPreference,
  saveModelBindingPolicy,
  saveWebSearchSettings,
} from "./settings-models.command";
import {
  DEFAULT_WEB_SEARCH_DOMAINS,
  appendAllowedDomain,
  decodeModelSettings,
  draftRevisionIsCurrent,
  modelChoiceKey,
  normalizeAndValidateDomains,
  projectionGenerationIsCurrent,
  renderT2GovernanceDraft,
  removeAllowedDomain,
  t2PairIsValid,
  webSearchControlsDisabled,
  webSearchSettingsAreDirty,
  webSearchUnavailableMessageKey,
} from "./settings-models.model";
  it("maps web-search readiness codes to operator messages", () => {
    expect(webSearchUnavailableMessageKey("tool_blocked")).toBe(
      "settings.models.webSearchToolBlocked",
    );
    expect(webSearchUnavailableMessageKey("provider_timeout")).toBe(
      "settings.models.webSearchProviderUnavailable",
    );
  });


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
    version: "2026-03-05",
    sku: "Standard",
    selection_mode: "auto",
    status: "resolved",
    capacity_tpm: 1000,
    capacity_unit: "tpm",
    capacity_value: 1000,
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
    unavailable_reason: null,
    allowed_domains: [...DEFAULT_WEB_SEARCH_DOMAINS],
    revision: 1,
    can_manage: true,
    provider: "foundry-agent",
    project_configured: true,
    agent_name: "fdai-web-search",
    model_deployment: "t1.web_search",
    provisioning_status: "configured",
    readiness_status: "ready",
    current_auto_pick: "foundry-agent:fdai-web-search",
    candidates: [],
  },
  document_ocr: {
    available: true,
    revision: 2,
    desired_provider: "local_python",
    effective_provider: "local_python",
    local_python_available: true,
    azure_available: true,
    azure_resource_desired: true,
    azure_resource_state: "ready",
    request_state: "ready",
    korean_enabled: true,
    deprovision_requested: false,
    policy_digest: "sha256:" + "b".repeat(64),
    can_manage: true,
    execution_authority: false,
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
        capacity_unit: "ptu",
        capacity_value: 30,
      },
      {
        publisher: "OpenAI",
        family: "gpt-4.1",
        capacity_unit: "tpm",
        capacity_value: 0,
      },
    ],
    secondary_candidates: [
      { publisher: "Anthropic", family: "claude-opus-4", capacity_unit: "tpm", capacity_value: 0 },
      { publisher: "MistralAI", family: "mistral-large-2", capacity_unit: "tpm", capacity_value: 0 },
    ],
    active_primary: { publisher: "OpenAI", family: "gpt-4o", capacity_unit: "ptu", capacity_value: 30 },
    active_secondary: null,
    quorum_ready: false,
  },
  binding_policy: {
    environment: "staging",
    revision: 1,
    state: "draft",
    policy_digest: "sha256:" + "a".repeat(64),
    can_manage: true,
    execution_authority: false,
    policy: {
      capabilities: {
        "t1.judge": {
          selection_mode: "pinned",
          publisher: "OpenAI",
          family: "gpt-mini",
          version_policy: "latest-compatible",
          sku: "Standard",
          capacity: { unit: "tpm", value: 1000 },
        },
      },
    },
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
    expect(decoded.webSearch.unavailableReason).toBeNull();
    expect(decoded.webSearch.allowedDomains).toEqual(DEFAULT_WEB_SEARCH_DOMAINS);
    expect(decoded.webSearch.revision).toBe(1);
    expect(decoded.webSearch).toMatchObject({
      provider: "foundry-agent",
      projectConfigured: true,
      agentName: "fdai-web-search",
      modelDeployment: "t1.web_search",
      provisioningStatus: "configured",
      readinessStatus: "ready",
    });
    expect(decoded.documentOcr).toMatchObject({
      revision: 2,
      desiredProvider: "local_python",
      effectiveProvider: "local_python",
      azureResourceDesired: true,
      azureResourceState: "ready",
      canManage: true,
    });
    expect(decoded.modelRouting[0]?.selectedDeployment).toBe("primary-b");
    expect(decoded.modelRouting[0]?.candidates[0]?.status).toBe("recovered");
    expect(decoded.endpointInventory[0]).toMatchObject({
      routeKind: "apim-gateway",
      providerKind: "azure-openai",
      capacityUnit: "ptu",
      capacityValue: 30,
      userSelectable: false,
    });
    expect(decoded.resolvedMetadata.digest).toBeNull();
    expect(decoded.capabilities[0]).toMatchObject({
      version: "2026-03-05",
      sku: "Standard",
      selectionMode: "auto",
      capacityUnit: "tpm",
      capacityValue: 1000,
    });
    expect(decoded.t2ModelPolicy.primaryCandidates[0]).toMatchObject({
      capacityUnit: "ptu",
      capacityValue: 30,
    });
    expect(decoded.bindingPolicy).toMatchObject({
      environment: "staging",
      revision: 1,
      state: "draft",
      canManage: true,
      executionAuthority: false,
      policyDigest: "sha256:" + "a".repeat(64),
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

  it("submits model binding draft, assessment, and plan without activation authority", async () => {
    const calls: Array<{ readonly url: string; readonly method: string; readonly body: unknown }> = [];
    const states = ["draft", "assessment-requested", "plan-requested"] as const;
    let index = 0;
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL, init?: RequestInit) => {
      calls.push({
        url: String(url),
        method: String(init?.method),
        body: JSON.parse(String(init?.body)),
      });
      const state = states[index++];
      return new Response(JSON.stringify({
        proposal_id: `proposal-${index}`,
        accepted_at: "2026-08-24T00:00:00Z",
        duplicate: false,
        state,
        policy_digest: "sha256:" + "a".repeat(64),
        policy_revision: 1,
        execution_authority: false,
        activation_boundary: "protected-plan-only",
      }), { status: state === "draft" ? 200 : 202 });
    }));
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "Bearer token",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };
    const policy = {
      schema_version: "1.0.0",
      environment: "staging",
      revision: 1,
      capabilities: {
        "t1.judge": { selection_mode: "auto" },
      },
    };

    const draft = await saveModelBindingPolicy(auth, "http://127.0.0.1:8030", {
      policy,
      expectedRevision: 0,
      idempotencyKey: "draft-1",
    });
    const assessment = await requestModelBindingOperation(
      auth,
      "http://127.0.0.1:8030",
      "assess",
      {
        environment: "staging",
        policyRevision: 1,
        policyDigest: "sha256:" + "a".repeat(64),
        idempotencyKey: "assess-1",
      },
    );
    const plan = await requestModelBindingOperation(
      auth,
      "http://127.0.0.1:8030",
      "plan",
      {
        environment: "staging",
        policyRevision: 1,
        policyDigest: "sha256:" + "a".repeat(64),
        idempotencyKey: "plan-1",
      },
    );

    expect(draft.state).toBe("draft");
    expect(assessment.state).toBe("assessment-requested");
    expect(plan.state).toBe("plan-requested");
    expect(plan.executionAuthority).toBe(false);
    expect(calls).toEqual([
      {
        url: "http://127.0.0.1:8030/models/binding-policy",
        method: "PUT",
        body: {
          policy,
          expected_revision: 0,
          idempotency_key: "draft-1",
        },
      },
      {
        url: "http://127.0.0.1:8030/models/binding-policy/assess",
        method: "POST",
        body: {
          environment: "staging",
          policy_revision: 1,
          policy_digest: "sha256:" + "a".repeat(64),
          idempotency_key: "assess-1",
        },
      },
      {
        url: "http://127.0.0.1:8030/models/binding-policy/plan",
        method: "POST",
        body: {
          environment: "staging",
          policy_revision: 1,
          policy_digest: "sha256:" + "a".repeat(64),
          idempotency_key: "plan-1",
        },
      },
    ]);
  });

  it("rejects a model binding receipt that claims execution authority", () => {
    expect(() => decodeModelBindingProposalReceipt({
      proposal_id: "proposal-1",
      accepted_at: "2026-08-24T00:00:00Z",
      duplicate: false,
      state: "draft",
      policy_digest: "sha256:" + "a".repeat(64),
      policy_revision: 1,
      execution_authority: true,
      activation_boundary: "protected-plan-only",
    })).toThrow("execution_authority MUST be false");
  });

  it("saves an OCR policy and requests its protected plan without apply authority", async () => {
    const calls: Array<{ readonly url: string; readonly body: unknown }> = [];
    const digest = "sha256:" + "c".repeat(64);
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL, init?: RequestInit) => {
      calls.push({ url: String(url), body: JSON.parse(String(init?.body)) });
      return new Response(JSON.stringify({
        proposal_id: "ocr-proposal",
        accepted_at: "2026-08-24T00:00:00Z",
        duplicate: false,
        state: calls.length === 1 ? "plan-required" : "plan-requested",
        policy_digest: digest,
        policy_revision: 3,
        execution_authority: false,
        activation_boundary: "protected-plan-only",
      }), { status: 202 });
    }));
    const auth: AuthContext = {
      devMode: false,
      account: null,
      getAuthorizationHeader: async () => "******",
      signIn: async () => undefined,
      signOut: async () => undefined,
    };

    const saved = await saveDocumentOcrPolicy(auth, "http://127.0.0.1:8030", {
      environment: "dev",
      expectedRevision: 2,
      provider: "local_python",
      azureResourceDesired: true,
      deprovisionRequested: false,
      idempotencyKey: "ocr-policy-3",
    });
    const planned = await requestDocumentOcrPlan(auth, "http://127.0.0.1:8030", {
      environment: "dev",
      policyRevision: saved.policyRevision,
      policyDigest: saved.policyDigest,
      idempotencyKey: "ocr-plan-3",
    });

    expect(planned.executionAuthority).toBe(false);
    expect(calls).toEqual([
      {
        url: "http://127.0.0.1:8030/models/document-ocr-policy",
        body: {
          policy: {
            schema_version: "1.0.0",
            environment: "dev",
            revision: 3,
            desired_provider: "local_python",
            azure_resource_desired: true,
            deprovision_requested: false,
          },
          expected_revision: 2,
          idempotency_key: "ocr-policy-3",
        },
      },
      {
        url: "http://127.0.0.1:8030/models/document-ocr-policy/plan",
        body: {
          environment: "dev",
          policy_revision: 3,
          policy_digest: digest,
          idempotency_key: "ocr-plan-3",
        },
      },
    ]);
  });

  it("rejects OCR receipts that claim a binding-only state", () => {
    expect(() => decodeDocumentOcrProposalReceipt({
      proposal_id: "ocr-proposal",
      accepted_at: "2026-08-24T00:00:00Z",
      duplicate: false,
      state: "draft",
      policy_digest: "sha256:" + "d".repeat(64),
      policy_revision: 1,
      execution_authority: false,
      activation_boundary: "protected-plan-only",
    })).toThrow("document OCR receipt state is invalid");
  });

  it("rejects a model binding receipt with an unknown activation boundary", () => {
    expect(() => decodeModelBindingProposalReceipt({
      proposal_id: "proposal-1",
      accepted_at: "2026-08-24T00:00:00Z",
      duplicate: false,
      state: "draft",
      policy_digest: "sha256:" + "a".repeat(64),
      policy_revision: 1,
      execution_authority: false,
      activation_boundary: "direct-apply",
    })).toThrow("activation_boundary");
  });

  it("rejects a model binding receipt with a malformed accepted timestamp", () => {
    expect(() => decodeModelBindingProposalReceipt({
      proposal_id: "proposal-1",
      accepted_at: "not-a-timestamp",
      duplicate: false,
      state: "draft",
      policy_digest: "sha256:" + "a".repeat(64),
      policy_revision: 1,
      execution_authority: false,
      activation_boundary: "protected-plan-only",
    })).toThrow("accepted_at is invalid");
  });

  it("rejects an unknown model binding version policy", () => {
    expect(() => decodeModelSettings({
      ...payload,
      binding_policy: {
        environment: "staging",
        revision: 1,
        state: "draft",
        policy_digest: "sha256:" + "a".repeat(64),
        can_manage: true,
        execution_authority: false,
        policy: {
          capabilities: {
            "t1.judge": {
              selection_mode: "pinned",
              publisher: "OpenAI",
              family: "gpt-mini",
              version_policy: "floating",
              sku: "Standard",
              capacity: { unit: "tpm", value: 1000 },
            },
          },
        },
      },
    })).toThrow("version_policy is invalid");
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

  it("adds and removes normalized allowlist hosts", () => {
    expect(appendAllowedDomain(
      "learn.microsoft.com",
      " NVD.NIST.GOV ",
      true,
    )).toEqual({
      domains: ["learn.microsoft.com", "nvd.nist.gov"],
      error: null,
      invalidDomains: [],
    });
    expect(removeAllowedDomain(
      "learn.microsoft.com\nnvd.nist.gov",
      "learn.microsoft.com",
    )).toBe("nvd.nist.gov");
  });

  it("detects deployment-wide web-search draft changes", () => {
    expect(webSearchSettingsAreDirty({
      enabled: true,
      domains: ["learn.microsoft.com"],
      savedEnabled: true,
      savedDomains: ["learn.microsoft.com"],
    })).toBe(false);
    expect(webSearchSettingsAreDirty({
      enabled: true,
      domains: ["learn.microsoft.com", "nvd.nist.gov"],
      savedEnabled: true,
      savedDomains: ["learn.microsoft.com"],
    })).toBe(true);
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
    capacityUnit: "tpm" as const,
    capacityValue: 0,
  };
}
