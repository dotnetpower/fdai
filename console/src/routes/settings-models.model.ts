export interface ModelCapabilityView {
  readonly name: string;
  readonly tier: "T1" | "T2";
  readonly publisher: string | null;
  readonly family: string | null;
  readonly status: string;
  readonly capacityTpm: number;
  readonly capacityUnit: "tpm" | "ptu";
  readonly capacityValue: number;
  readonly invocation: string;
  readonly reasons: readonly string[];
}

export interface ModelEndpointInventoryView {
  readonly bindingId: string;
  readonly capability: string;
  readonly providerKind: "azure-openai" | "self-hosted";
  readonly routeKind: "direct" | "apim-gateway";
  readonly apiStyle: "azure-openai" | "openai-v1";
  readonly deployment: string;
  readonly apiVersion: string | null;
  readonly authKind: "entra" | "api-key-ref" | "none";
  readonly publisher: string;
  readonly family: string;
  readonly version: string | null;
  readonly capacityUnit: "tpm" | "ptu" | "gpu";
  readonly capacityValue: number;
  readonly features: {
    readonly streaming: boolean;
    readonly embeddings: boolean;
    readonly structuredOutput: boolean;
    readonly toolCalling: boolean;
  };
  readonly discoverySource: string;
  readonly verifiedAt: string;
  readonly managedBy: "catalog-and-resolver";
  readonly userSelectable: false;
}

export interface NarratorCandidateView {
  readonly deployment: string;
  readonly family: string | null;
  readonly status: string;
  readonly totalP50Ms: number | null;
  readonly totalP95Ms: number | null;
  readonly totalSamples: number;
  readonly ttftP50Ms: number | null;
  readonly ttftP95Ms: number | null;
  readonly ttftSamples: number;
}

export interface WebSearchSettingsView {
  readonly available: boolean;
  readonly enabled: boolean;
  readonly allowedDomains: readonly string[];
  readonly revision: number;
  readonly canManage: boolean;
  readonly provider: string;
  readonly currentAutoPick: string | null;
  readonly candidates: readonly unknown[];
}

export interface ModelRoutingCandidateView {
  readonly deployment: string;
  readonly status: "unhealthy" | "recovered";
  readonly failureKind: string | null;
  readonly cooldownSeconds: number;
  readonly updatedAt: string;
}

export interface ModelRoutingRoleView {
  readonly role: string;
  readonly selectedDeployment: string | null;
  readonly selectionReason: string | null;
  readonly selectedAt: string | null;
  readonly candidates: readonly ModelRoutingCandidateView[];
}

export interface T2ModelChoiceView {
  readonly publisher: string;
  readonly family: string;
  readonly version: string | null;
  readonly catalogStatus: "registry-only" | "deployed" | "provisionable" | "quota-unavailable";
  readonly deployments: readonly string[];
  readonly availableTpm: number;
}

export interface GptModelSkuView {
  readonly name: string;
  readonly availableTpm: number;
}

export interface GptModelCatalogEntryView {
  readonly publisher: "OpenAI";
  readonly family: string;
  readonly version: string;
  readonly lifecycle: string;
  readonly skus: readonly GptModelSkuView[];
  readonly availableTpm: number;
  readonly deployments: readonly string[];
  readonly deployed: boolean;
  readonly provisionable: boolean;
  readonly selectable: boolean;
  readonly status: "deployed" | "provisionable" | "quota-unavailable";
}

export interface GptModelCatalogView {
  readonly available: boolean;
  readonly source: string;
  readonly region: string | null;
  readonly models: readonly GptModelCatalogEntryView[];
}

export interface T2ModelPolicyView {
  readonly selectionScope: "governance-draft";
  readonly invariant: "distinct-publisher";
  readonly primaryCandidates: readonly T2ModelChoiceView[];
  readonly secondaryCandidates: readonly T2ModelChoiceView[];
  readonly activePrimary: T2ModelChoiceView | null;
  readonly activeSecondary: T2ModelChoiceView | null;
  readonly quorumReady: boolean;
}

export const DEFAULT_WEB_SEARCH_DOMAINS = [
  "learn.microsoft.com",
  "azure.microsoft.com",
  "nvd.nist.gov",
  "cve.org",
  "datatracker.ietf.org",
  "kubernetes.io",
  "docs.python.org",
  "postgresql.org",
] as const;

export function draftRevisionIsCurrent(current: number, submitted: number): boolean {
  return current === submitted;
}

export function projectionGenerationIsCurrent(current: number, candidate: number): boolean {
  return current === candidate;
}

export type DomainValidationError = "required" | "too-many" | "invalid";

export interface DomainValidationResult {
  readonly domains: readonly string[];
  readonly error: DomainValidationError | null;
  readonly invalidDomains: readonly string[];
}

export interface ModelSettingsView {
  readonly region: string | null;
  readonly mixedModelMode: string | null;
  readonly resolvedMetadata: {
    readonly kind: string;
    readonly source: string;
    readonly asOf: string;
  };
  readonly discovery: {
    readonly automatic: boolean;
    readonly source: string;
    readonly status: string;
  };
  readonly provisioning: {
    readonly automatic: boolean;
    readonly status: string;
    readonly resolvedCount: number;
    readonly hilOnlyCount: number;
  };
  readonly capabilities: readonly ModelCapabilityView[];
  readonly endpointInventory: readonly ModelEndpointInventoryView[];
  readonly narrator: {
    readonly revision: number;
    readonly requested: string;
    readonly effective: string;
    readonly fallbackReason: string | null;
    readonly currentAutoPick: string | null;
    readonly candidates: readonly NarratorCandidateView[];
  };
  readonly webSearch: WebSearchSettingsView;
  readonly modelRouting: readonly ModelRoutingRoleView[];
  readonly t2SelectionScope: "system-governed";
  readonly t2ModelPolicy: T2ModelPolicyView;
  readonly modelCatalog: GptModelCatalogView;
}

export function decodeModelSettings(value: unknown): ModelSettingsView {
  const root = object(value, "model settings");
  const discovery = object(root["discovery"], "model settings.discovery");
  const provisioning = object(root["provisioning"], "model settings.provisioning");
  const resolvedMetadata = object(root["resolved_metadata"], "model settings.resolved_metadata");
  const narrator = object(root["narrator"], "model settings.narrator");
  const webSearch = object(root["web_search"], "model settings.web_search");
  const t2ModelPolicy = object(
    root["t2_model_policy"] ?? {
      selection_scope: "governance-draft",
      invariant: "distinct-publisher",
      primary_candidates: [],
      secondary_candidates: [],
      active_primary: null,
      active_secondary: null,
      quorum_ready: false,
    },
    "model settings.t2_model_policy",
  );
  const modelCatalog = object(
    root["model_catalog"] ?? {
      available: false,
      source: "unavailable",
      region: null,
      models: [],
    },
    "model settings.model_catalog",
  );
  const modelRouting = array(root["model_routing"], "model settings.model_routing").map(
    (entry) => decodeModelRouting(entry),
  );
  const capabilities = array(root["capabilities"], "model settings.capabilities").map(
    (entry) => decodeCapability(entry),
  );
  const endpointInventory = array(
    root["endpoint_inventory"] ?? [],
    "model settings.endpoint_inventory",
  ).map((entry) => decodeEndpointInventory(entry));
  const candidates = array(narrator["candidates"], "model settings.narrator.candidates").map(
    (entry) => decodeCandidate(entry),
  );
  requireUnique(capabilities.map((item) => item.name), "model capability.name");
  requireUnique(endpointInventory.map((item) => item.bindingId), "endpoint binding.binding_id");
  requireUnique(candidates.map((item) => item.deployment), "narrator candidate.deployment");
  const primaryCandidates = array(
    t2ModelPolicy["primary_candidates"],
    "t2_model_policy.primary_candidates",
  ).map((entry) => decodeT2ModelChoice(entry, "T2 primary candidate"));
  const secondaryCandidates = array(
    t2ModelPolicy["secondary_candidates"],
    "t2_model_policy.secondary_candidates",
  ).map((entry) => decodeT2ModelChoice(entry, "T2 secondary candidate"));
  requireUnique(primaryCandidates.map(modelChoiceKey), "T2 primary candidate");
  requireUnique(secondaryCandidates.map(modelChoiceKey), "T2 secondary candidate");
  const scope = string(narrator["selection_scope"], "narrator.selection_scope");
  if (scope !== "per-user") throw new Error("narrator.selection_scope MUST be per-user");
  const t2Scope = string(root["t2_selection_scope"], "t2_selection_scope");
  if (t2Scope !== "system-governed") {
    throw new Error("t2_selection_scope MUST be system-governed");
  }
  return {
    region: nullableString(root["region"], "model settings.region"),
    mixedModelMode: nullableString(root["mixed_model_mode"], "mixed_model_mode"),
    resolvedMetadata: {
      kind: string(resolvedMetadata["kind"], "resolved_metadata.kind"),
      source: string(resolvedMetadata["source"], "resolved_metadata.source"),
      asOf: string(resolvedMetadata["as_of"], "resolved_metadata.as_of"),
    },
    discovery: {
      automatic: boolean(discovery["automatic"], "discovery.automatic"),
      source: string(discovery["source"], "discovery.source"),
      status: knownString(discovery["status"], "discovery.status", ["enabled", "disabled"]),
    },
    provisioning: {
      automatic: boolean(provisioning["automatic"], "provisioning.automatic"),
      status: knownString(provisioning["status"], "provisioning.status", ["ready", "degraded"]),
      resolvedCount: nonNegativeInteger(provisioning["resolved_count"], "provisioning.resolved_count"),
      hilOnlyCount: nonNegativeInteger(provisioning["hil_only_count"], "provisioning.hil_only_count"),
    },
    capabilities,
    endpointInventory,
    narrator: {
      revision: nonNegativeInteger(narrator["revision"], "narrator.revision"),
      requested: string(narrator["requested"], "narrator.requested"),
      effective: string(narrator["effective"], "narrator.effective"),
      fallbackReason: nullableString(narrator["fallback_reason"], "narrator.fallback_reason"),
      currentAutoPick: nullableString(narrator["current_auto_pick"], "narrator.current_auto_pick"),
      candidates,
    },
    webSearch: {
      available: boolean(webSearch["available"], "web_search.available"),
      enabled: boolean(webSearch["enabled"], "web_search.enabled"),
      allowedDomains: array(webSearch["allowed_domains"], "web_search.allowed_domains").map(
        (domain) => {
          const parsed = string(domain, "web_search.allowed_domains[]");
          if (!isValidHost(parsed)) throw new Error("web_search.allowed_domains[] is invalid");
          return parsed;
        },
      ),
      revision: nonNegativeInteger(webSearch["revision"], "web_search.revision"),
      canManage: boolean(webSearch["can_manage"], "web_search.can_manage"),
      provider: string(webSearch["provider"], "web_search.provider"),
      currentAutoPick: nullableString(
        webSearch["current_auto_pick"],
        "web_search.current_auto_pick",
      ),
      candidates: array(webSearch["candidates"], "web_search.candidates"),
    },
    modelRouting,
    t2SelectionScope: "system-governed",
    t2ModelPolicy: {
      selectionScope: knownString(
        t2ModelPolicy["selection_scope"],
        "t2_model_policy.selection_scope",
        ["governance-draft"],
      ) as "governance-draft",
      invariant: knownString(
        t2ModelPolicy["invariant"],
        "t2_model_policy.invariant",
        ["distinct-publisher"],
      ) as "distinct-publisher",
      primaryCandidates,
      secondaryCandidates,
      activePrimary: decodeNullableT2ModelChoice(
        t2ModelPolicy["active_primary"],
        "t2_model_policy.active_primary",
      ),
      activeSecondary: decodeNullableT2ModelChoice(
        t2ModelPolicy["active_secondary"],
        "t2_model_policy.active_secondary",
      ),
      quorumReady: boolean(t2ModelPolicy["quorum_ready"], "t2_model_policy.quorum_ready"),
    },
    modelCatalog: {
      available: boolean(modelCatalog["available"], "model_catalog.available"),
      source: string(modelCatalog["source"], "model_catalog.source"),
      region: nullableString(modelCatalog["region"], "model_catalog.region"),
      models: array(modelCatalog["models"], "model_catalog.models").map(decodeCatalogModel),
    },
  };
}

export function modelChoiceKey(choice: T2ModelChoiceView): string {
  return `${encodeURIComponent(choice.publisher)}|${encodeURIComponent(choice.family)}`;
}

export function t2PairIsValid(
  primary: T2ModelChoiceView | null,
  secondary: T2ModelChoiceView | null,
): boolean {
  return primary !== null && secondary !== null && primary.publisher !== secondary.publisher;
}

export function renderT2GovernanceDraft(
  primary: T2ModelChoiceView,
  secondary: T2ModelChoiceView,
): string {
  if (!t2PairIsValid(primary, secondary)) {
    throw new Error("T2 model pair MUST use distinct publishers");
  }
  const provisioningNote = primary.catalogStatus === "deployed"
    ? `# Primary deployment already exists: ${primary.deployments.join(", ") || primary.family}.`
    : primary.catalogStatus === "provisionable"
      ? "# Bootstrap resolver and Terraform will provision the primary after this PR is approved."
      : "# Bootstrap resolver must re-check catalog and quota before provisioning the primary.";
  return [
    "# FDAI T2 model policy governance draft.",
    "# Review in a PR; this artifact does not change the running control plane.",
    "# Merge these preferences into the existing roles; preserve SKU and capacity fields.",
    provisioningNote,
    "models:",
    "  t2.reasoner.primary:",
    "    preferences:",
    `      - {publisher: ${JSON.stringify(primary.publisher)}, family: ${JSON.stringify(primary.family)}}`,
    "  t2.reasoner.secondary:",
    "    preferences:",
    `      - {publisher: ${JSON.stringify(secondary.publisher)}, family: ${JSON.stringify(secondary.family)}}`,
    "",
  ].join("\n");
}

function decodeT2ModelChoice(value: unknown, label: string): T2ModelChoiceView {
  const item = object(value, label);
  return {
    publisher: string(item["publisher"], `${label}.publisher`),
    family: string(item["family"], `${label}.family`),
    version: nullableString(item["version"], `${label}.version`),
    catalogStatus: knownString(
      item["catalog_status"] ?? "registry-only",
      `${label}.catalog_status`,
      ["registry-only", "deployed", "provisionable", "quota-unavailable"],
    ) as T2ModelChoiceView["catalogStatus"],
    deployments: array(item["deployments"] ?? [], `${label}.deployments`).map((deployment) =>
      string(deployment, `${label}.deployments[]`)
    ),
    availableTpm: nonNegativeNumber(item["available_tpm"] ?? 0, `${label}.available_tpm`),
  };
}

function decodeNullableT2ModelChoice(value: unknown, label: string): T2ModelChoiceView | null {
  return value === null ? null : decodeT2ModelChoice(value, label);
}

function decodeCatalogModel(value: unknown): GptModelCatalogEntryView {
  const item = object(value, "model catalog entry");
  const publisher = string(item["publisher"], "model catalog entry.publisher");
  if (publisher !== "OpenAI") throw new Error("model catalog entry.publisher is invalid");
  return {
    publisher,
    family: string(item["family"], "model catalog entry.family"),
    version: string(item["version"], "model catalog entry.version"),
    lifecycle: string(item["lifecycle"], "model catalog entry.lifecycle"),
    skus: array(item["skus"], "model catalog entry.skus").map((raw) => {
      const sku = object(raw, "model catalog SKU");
      return {
        name: string(sku["name"], "model catalog SKU.name"),
        availableTpm: nonNegativeNumber(
          sku["available_tpm"],
          "model catalog SKU.available_tpm",
        ),
      };
    }),
    availableTpm: nonNegativeNumber(
      item["available_tpm"],
      "model catalog entry.available_tpm",
    ),
    deployments: array(item["deployments"], "model catalog entry.deployments").map(
      (deployment) => string(deployment, "model catalog entry.deployments[]"),
    ),
    deployed: boolean(item["deployed"], "model catalog entry.deployed"),
    provisionable: boolean(item["provisionable"], "model catalog entry.provisionable"),
    selectable: boolean(item["selectable"], "model catalog entry.selectable"),
    status: knownString(item["status"], "model catalog entry.status", [
      "deployed", "provisionable", "quota-unavailable",
    ]) as GptModelCatalogEntryView["status"],
  };
}

function decodeModelRouting(value: unknown): ModelRoutingRoleView {
  const item = object(value, "model routing role");
  return {
    role: string(item["role"], "model routing role.role"),
    selectedDeployment: nullableString(
      item["selected_deployment"],
      "model routing role.selected_deployment",
    ),
    selectionReason: nullableString(
      item["selection_reason"],
      "model routing role.selection_reason",
    ),
    selectedAt: nullableString(item["selected_at"], "model routing role.selected_at"),
    candidates: array(item["candidates"], "model routing role.candidates").map(
      (candidate) => {
        const parsed = object(candidate, "model routing candidate");
        const status = knownString(parsed["status"], "model routing candidate.status", [
          "unhealthy",
          "recovered",
        ]);
        return {
          deployment: string(parsed["deployment"], "model routing candidate.deployment"),
          status: status as ModelRoutingCandidateView["status"],
          failureKind: nullableString(
            parsed["failure_kind"],
            "model routing candidate.failure_kind",
          ),
          cooldownSeconds: nonNegativeInteger(
            parsed["cooldown_seconds"],
            "model routing candidate.cooldown_seconds",
          ),
          updatedAt: string(parsed["updated_at"], "model routing candidate.updated_at"),
        };
      },
    ),
  };
}

export function normalizeAndValidateDomains(
  input: string,
  enabled: boolean,
): DomainValidationResult {
  const domains = [...new Set(
    input
      .split(/\r?\n/)
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean),
  )];
  if (domains.length > 100) {
    return { domains, error: "too-many", invalidDomains: [] };
  }
  const invalidDomains = domains.filter((domain) => !isValidHost(domain));
  if (invalidDomains.length > 0) {
    return { domains, error: "invalid", invalidDomains };
  }
  if (enabled && domains.length === 0) {
    return { domains, error: "required", invalidDomains: [] };
  }
  return { domains, error: null, invalidDomains: [] };
}

export function webSearchControlsDisabled(canManage: boolean, saving: boolean): boolean {
  return !canManage || saving;
}

function isValidHost(value: string): boolean {
  if (
    value.includes("://")
    || value.includes("/")
    || value.includes(":")
    || value.includes("*")
    || /[\s?#@]/.test(value)
  ) {
    return false;
  }
  if (value.length > 253 || !value.includes(".")) return false;
  return value.split(".").every(
    (label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label),
  );
}

function decodeCapability(value: unknown): ModelCapabilityView {
  const item = object(value, "model capability");
  const tier = string(item["tier"], "model capability.tier");
  if (tier !== "T1" && tier !== "T2") throw new Error("model capability.tier is invalid");
  return {
    name: string(item["name"], "model capability.name"),
    tier,
    publisher: nullableString(item["publisher"], "model capability.publisher"),
    family: nullableString(item["family"], "model capability.family"),
    status: knownString(item["status"], "model capability.status", [
      "resolved", "capacity-reduced", "hil-only",
    ]),
    capacityTpm: nonNegativeNumber(item["capacity_tpm"], "model capability.capacity_tpm"),
    capacityUnit: knownString(
      item["capacity_unit"] ?? "tpm",
      "model capability.capacity_unit",
      ["tpm", "ptu"],
    ) as ModelCapabilityView["capacityUnit"],
    capacityValue: nonNegativeNumber(
      item["capacity_value"] ?? item["capacity_tpm"],
      "model capability.capacity_value",
    ),
    invocation: string(item["invocation"], "model capability.invocation"),
    reasons: array(item["reasons"], "model capability.reasons").map((reason) =>
      string(reason, "model capability.reason")
    ),
  };
}

function decodeEndpointInventory(value: unknown): ModelEndpointInventoryView {
  const item = object(value, "endpoint binding");
  const features = object(item["features"], "endpoint binding.features");
  const managedBy = string(item["managed_by"], "endpoint binding.managed_by");
  if (managedBy !== "catalog-and-resolver") {
    throw new Error("endpoint binding.managed_by MUST be catalog-and-resolver");
  }
  if (item["user_selectable"] !== false) {
    throw new Error("endpoint binding.user_selectable MUST be false");
  }
  return {
    bindingId: string(item["binding_id"], "endpoint binding.binding_id"),
    capability: string(item["capability"], "endpoint binding.capability"),
    providerKind: knownString(item["provider_kind"], "endpoint binding.provider_kind", [
      "azure-openai", "self-hosted",
    ]) as ModelEndpointInventoryView["providerKind"],
    routeKind: knownString(item["route_kind"], "endpoint binding.route_kind", [
      "direct", "apim-gateway",
    ]) as ModelEndpointInventoryView["routeKind"],
    apiStyle: knownString(item["api_style"], "endpoint binding.api_style", [
      "azure-openai", "openai-v1",
    ]) as ModelEndpointInventoryView["apiStyle"],
    deployment: string(item["deployment"], "endpoint binding.deployment"),
    apiVersion: nullableString(item["api_version"], "endpoint binding.api_version"),
    authKind: knownString(item["auth_kind"], "endpoint binding.auth_kind", [
      "entra", "api-key-ref", "none",
    ]) as ModelEndpointInventoryView["authKind"],
    publisher: string(item["publisher"], "endpoint binding.publisher"),
    family: string(item["family"], "endpoint binding.family"),
    version: nullableString(item["version"], "endpoint binding.version"),
    capacityUnit: knownString(item["capacity_unit"], "endpoint binding.capacity_unit", [
      "tpm", "ptu", "gpu",
    ]) as ModelEndpointInventoryView["capacityUnit"],
    capacityValue: nonNegativeNumber(item["capacity_value"], "endpoint binding.capacity_value"),
    features: {
      streaming: boolean(features["streaming"], "endpoint binding.features.streaming"),
      embeddings: boolean(features["embeddings"], "endpoint binding.features.embeddings"),
      structuredOutput: boolean(
        features["structured_output"],
        "endpoint binding.features.structured_output",
      ),
      toolCalling: boolean(features["tool_calling"], "endpoint binding.features.tool_calling"),
    },
    discoverySource: string(item["discovery_source"], "endpoint binding.discovery_source"),
    verifiedAt: string(item["verified_at"], "endpoint binding.verified_at"),
    managedBy: "catalog-and-resolver",
    userSelectable: false,
  };
}

function decodeCandidate(value: unknown): NarratorCandidateView {
  const item = object(value, "narrator candidate");
  return {
    deployment: string(item["deployment"], "narrator candidate.deployment"),
    family: nullableString(item["family"], "narrator candidate.family"),
    status: knownString(item["status"], "narrator candidate.status", ["available"]),
    totalP50Ms: nullableNonNegativeNumber(item["total_p50_ms"], "candidate.total_p50_ms"),
    totalP95Ms: nullableNonNegativeNumber(item["total_p95_ms"], "candidate.total_p95_ms"),
    totalSamples: nonNegativeInteger(item["total_samples"], "candidate.total_samples"),
    ttftP50Ms: nullableNonNegativeNumber(item["ttft_p50_ms"], "candidate.ttft_p50_ms"),
    ttftP95Ms: nullableNonNegativeNumber(item["ttft_p95_ms"], "candidate.ttft_p95_ms"),
    ttftSamples: nonNegativeInteger(item["ttft_samples"], "candidate.ttft_samples"),
  };
}

function object(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function array(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} MUST be an array`);
  return value;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string") throw new Error(`${label} MUST be a string`);
  return value;
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null || value === undefined) return null;
  return string(value, label);
}

function number(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} MUST be a finite number`);
  }
  return value;
}

function nonNegativeNumber(value: unknown, label: string): number {
  const parsed = number(value, label);
  if (parsed < 0) throw new Error(`${label} MUST be non-negative`);
  return parsed;
}

function nullableNonNegativeNumber(value: unknown, label: string): number | null {
  if (value === null || value === undefined) return null;
  return nonNegativeNumber(value, label);
}

function knownString(value: unknown, label: string, allowed: readonly string[]): string {
  const parsed = string(value, label);
  if (!allowed.includes(parsed)) throw new Error(`${label} is invalid`);
  return parsed;
}

function requireUnique(values: readonly string[], label: string): void {
  if (new Set(values).size !== values.length) throw new Error(`${label} MUST be unique`);
}

function nonNegativeInteger(value: unknown, label: string): number {
  const parsed = number(value, label);
  if (!Number.isInteger(parsed) || parsed < 0) {
    throw new Error(`${label} MUST be a non-negative integer`);
  }
  return parsed;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} MUST be a boolean`);
  return value;
}
