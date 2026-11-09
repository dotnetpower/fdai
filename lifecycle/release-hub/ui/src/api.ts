import { authenticatedFetch } from "../../../hub/ui/src/auth";
import { compareSemVer } from "./release-lineage.model";

export type Release = {
  id: string; label: string; manifest: string; digest: string; signed_payload_sha256: string; signature: string | null;
  signature_status: string; state: "draft" | "published" | "recalled";
  channels: string[]; published_at: string | null; recalled_at: string | null;
};
export type Event = {
  revision: number; release_id: string; action: string; reason: string;
  channel: string | null; occurred_at: string;
  actor?: string;
};
export type Catalog = {
  revision: number; updated_at: string; expires_at: string; expired: boolean;
  key_id: string; mode: string; releases: Release[];
  channels: Record<string, string[]>; events: Event[]; export_sha256?: string;
};

export function isInitialCatalog(catalog: Catalog): boolean {
  return catalog.revision === 0 && catalog.releases.length === 0 &&
    catalog.events.length === 0 && Object.values(catalog.channels).every(ids => ids.length === 0);
}

export type Action = "register" | "publish" | "contribute" | "promote" | "recall" | "renew";
export type CanaryObservationInput = {
  installation_id: string; release_id: string; healthy: boolean; soak_seconds: number;
};
export type Change = {
  revision: number; confirmation: string; reason: string; channel?: string; channel_confirmation?: string;
  label?: string; manifest?: string;
  lifting_release_id?: string;
  source_channel?: string; target_channel?: string;
  required_labels?: string[]; labels?: string[];
  min_soak_seconds?: number; min_healthy_canaries?: number;
  max_stage_timeout_seconds?: number; elapsed_stage_seconds?: number;
  canary_observations?: CanaryObservationInput[];
};

export class CatalogRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "CatalogRequestError";
  }
}

export function catalogRecovery(failure: unknown): string {
  if (failure instanceof CatalogRequestError) {
    if (failure.status === 401) return "Session expired. Sign in again, then refresh the catalog before another action.";
    if (failure.status === 403) return "Operator access denied. Ask the Hub owner to review your existing access; do not expand permissions.";
    if (failure.status === 409) {
      const code = /^Promotion stage blocked \((promotion_[a-z_]+)\)\.$/.exec(failure.message)?.[1];
      const cause: Record<string, string> = {
        promotion_labels_missing: "Required promotion labels are missing.",
        promotion_canary_unhealthy: "Healthy canary observations are insufficient.",
        promotion_soak_incomplete: "The required observation window is incomplete.",
        promotion_stage_timed_out: "The promotion stage timed out.",
      };
      return code && cause[code]
        ? `${cause[code]} Refresh and review the release activity before another action.`
        : "Catalog state changed or a server guard blocked the request. Refresh and review the release activity.";
    }
    if (failure.status === 429) return "Too many requests in flight. Wait briefly and refresh the catalog before retrying.";
    if (failure.status === 503) return "Hub configuration or service readiness is unavailable. Ask the Hub owner to inspect readiness.";
    return `The Hub rejected the request (${failure.status}). Review the input and current catalog before another action.`;
  }

  if (failure instanceof DOMException && ["AbortError", "TimeoutError"].includes(failure.name)) {
    return "The request timed out. Read the catalog before another action.";
  }
  if (failure instanceof Error && failure.name === "InteractionRequiredAuthError") {
    return "Session renewal requires sign-in. Sign in again, then refresh the catalog before another action.";
  }
  return "The Hub response is unavailable or invalid. Refresh the catalog and inspect the current state before another action.";
}

export function catalogChangeObserved(
  catalog: Catalog, action: Action | "recall_capability" | "lift_capability", id: string, change: Change,
): boolean {
  const expectedAction = action === "promote" ? "contribute" : action;
  const expectedChannel = action === "contribute"
    ? change.channel
    : action === "promote"
    ? (change.target_channel ?? change.channel ?? null)
    : null;
  return catalog.revision > change.revision && catalog.events.some((event) =>
    event.revision === change.revision + 1
    && event.action === expectedAction
    && event.release_id === (action === "renew" ? "catalog" : id)
    && event.reason === change.reason.trim()
    && event.channel === expectedChannel);
}

export type DeploymentRequest = {
  request_id: string; subscription_id: string; release_id: string; channel: string;
  region: string; source_commit: string; catalog_digest: string; recorded_at: string;
  status: "requested"; trust: "self-reported";
};
export type DeploymentRequestPage = {
  requests: DeploymentRequest[]; limit: number; offset: number; has_more: boolean;
};

export async function requestDeploymentRequests(
  subscriptionId = "", offset = 0, limit = 25,
): Promise<DeploymentRequestPage> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (subscriptionId) query.set("subscription_id", subscriptionId);
  const response = await authenticatedFetch(`/v1/deployment-requests?${query}`, {
    signal: AbortSignal.timeout(10_000),
  });
  let result: unknown;
  try { result = await response.json(); }
  catch { throw new Error(`Deployment requests unavailable (${response.status}).`); }
  if (!response.ok) {
    throw new Error("Deployment requests unavailable. Check operator access and refresh.");
  }
  if (typeof result !== "object" || result === null) throw new Error("Invalid deployment request page.");
  const page = result as DeploymentRequestPage;
  if (!Array.isArray(page.requests) || page.requests.length > limit
    || page.limit !== limit || page.offset !== offset || typeof page.has_more !== "boolean"
    || !page.requests.every((record) => typeof record === "object" && record !== null
      && record.status === "requested" && record.trust === "self-reported"
      && ["request_id", "subscription_id", "release_id", "channel", "region", "source_commit", "catalog_digest", "recorded_at"]
        .every((key) => typeof record[key as keyof DeploymentRequest] === "string")
      && Number.isFinite(Date.parse(record.recorded_at)))) {
    throw new Error("Invalid deployment request page.");
  }
  return page;
}

export type StencilFeatureFlagsRecord = {
  schema_version: "fdai.stencil-feature-flags.v1";
  stencil_id: string;
  stencil_digest: string;
  feature_flags_digest?: string;
  enforcement_mode: "fail-closed";
  enabled_panel_ids: string[];
  disabled_panel_ids: string[];
  enabled_loops: string[];
  disabled_loops: string[];
  enabled_workloads: string[];
  disabled_workloads: string[];
  enabled_scheduled_jobs: string[];
  disabled_scheduled_jobs: string[];
  enabled_addons: string[];
  disabled_addons: string[];
  panel_flags: Record<string, boolean>;
  loop_flags: Record<string, boolean>;
  workload_flags: Record<string, boolean>;
  scheduled_job_flags: Record<string, boolean>;
  addon_flags: Record<string, boolean>;
  runtime_env: Record<string, string>;
};

export type ReleaseStencilMetadata = {
  stencil_id: string;
  stencil_digest: string;
  topology_profile: "lite-observe-alert" | "standard-sre" | "full-enterprise";
  title?: string;
  title_ko?: string;
  azure_rbac_posture: string;
  required_azure_roles?: string[];
  enabled_workloads: string[];
  omitted_workloads?: string[];
  enabled_loops?: string[];
  disabled_loops?: string[];
  enabled_scheduled_jobs?: string[];
  enabled_panel_ids: string[];
  disabled_panel_ids?: string[];
  release_labels?: string[];
  feature_flags?: StencilFeatureFlagsRecord;
};

export type ReleaseManifest = Record<string, unknown> & {
  product?: string;
  source_commit?: string;
  platform_tag?: string;
  capability_maximums?: Record<string, unknown>;
  schema?: { target: number; tolerates: { minimum: number; maximum: number } };
  stencil?: ReleaseStencilMetadata;
};

export function extractReleaseStencil(
  source: Release | ReleaseManifest | null | undefined,
): ReleaseStencilMetadata | null {
  if (!source) return null;
  try {
    const manifest: ReleaseManifest =
      typeof (source as Release).manifest === "string"
        ? parseReleaseManifest((source as Release).manifest)
        : (source as ReleaseManifest);
    const raw = manifest.stencil;
    if (
      typeof raw === "object" &&
      raw !== null &&
      typeof raw.stencil_id === "string" &&
      typeof raw.stencil_digest === "string" &&
      Array.isArray(raw.enabled_workloads) &&
      Array.isArray(raw.enabled_panel_ids)
    ) {
      return raw;
    }
  } catch {
    return null;
  }
  return null;
}

export function nextPromotionTransition(
  release: Release,
): { sourceChannel: "DEV" | "RELEASE_CANDIDATE"; targetChannel: "RELEASE_CANDIDATE" | "RELEASE" } | null {
  if (release.state !== "published") return null;
  if (release.channels.includes("RELEASE")) return null;
  if (release.channels.includes("RELEASE_CANDIDATE")) {
    return { sourceChannel: "RELEASE_CANDIDATE", targetChannel: "RELEASE" };
  }
  if (release.channels.includes("DEV")) {
    return { sourceChannel: "DEV", targetChannel: "RELEASE_CANDIDATE" };
  }
  return null;
}

export function activeCapabilityRecalls(events: readonly Event[]): string[] {
  const ordered = [...events].sort((a, b) => a.revision - b.revision);
  const active = new Set<string>();
  for (const event of ordered) {
    if (event.action === "recall_capability") active.add(event.release_id);
    else if (event.action === "lift_capability") active.delete(event.release_id);
  }
  return [...active].sort();
}

export function releaseCapabilityIds(manifest: ReleaseManifest): Set<string> {
  const declared = new Set<string>(
    manifest.capability_maximums && typeof manifest.capability_maximums === "object"
      ? Object.keys(manifest.capability_maximums)
      : [],
  );
  if (manifest.stencil) {
    declared.add(`stencil:${manifest.stencil.stencil_id}`);
    for (const w of manifest.stencil.enabled_workloads ?? []) declared.add(w);
    for (const l of manifest.stencil.enabled_loops ?? []) declared.add(l);
    for (const p of manifest.stencil.enabled_panel_ids ?? []) declared.add(`panel:${p}`);
    for (const j of manifest.stencil.enabled_scheduled_jobs ?? []) declared.add(`job:${j}`);
    for (const a of manifest.stencil.feature_flags?.enabled_addons ?? []) {
      declared.add(`addon:${a}`);
    }
  }
  return declared;
}

export function blockedReleaseCapabilities(
  manifest: ReleaseManifest,
  events: readonly Event[],
): string[] {
  const declared = releaseCapabilityIds(manifest);
  if (declared.size === 0) return [];
  const recalled = new Set(activeCapabilityRecalls(events));
  return [...declared].filter((cap) => recalled.has(cap)).sort();
}

export type ApolloGateCheck = {
  id: string;
  label: string;
  label_ko: string;
  passed: boolean;
  detail: string;
  detail_ko: string;
};

export function evaluateApolloPromotionReadiness(input: {
  release: Release;
  manifest: ReleaseManifest;
  events: readonly Event[];
  sourceChannel: string;
  targetChannel: string;
  requiredLabels?: readonly string[];
  providedLabels?: readonly string[];
  minSoakSeconds?: number;
  elapsedStageSeconds?: number;
}): { allowed: boolean; gates: ApolloGateCheck[] } {
  const inSource = input.release.channels.includes(input.sourceChannel);
  const blockedCaps = blockedReleaseCapabilities(input.manifest, input.events);
  const notRecalled = input.release.state !== "recalled" && blockedCaps.length === 0;
  const reqLabels = new Set((input.requiredLabels ?? []).map((l) => l.trim()).filter(Boolean));
  const provLabels = new Set(
    (input.providedLabels ?? input.manifest.stencil?.release_labels ?? [])
      .map((l) => l.trim())
      .filter(Boolean),
  );
  const missingLabels = [...reqLabels].filter((l) => !provLabels.has(l));
  const labelsOk = missingLabels.length === 0;
  const minSoak = input.minSoakSeconds ?? 0;
  const elapsed = input.elapsedStageSeconds ?? minSoak;
  const soakOk = elapsed >= minSoak;

  const gates: ApolloGateCheck[] = [
    {
      id: "source-channel",
      label: `Source channel membership (${input.sourceChannel})`,
      label_ko: `원본 채널 소속 (${input.sourceChannel})`,
      passed: inSource,
      detail: inSource ? `Member of ${input.sourceChannel}` : `Missing from ${input.sourceChannel}`,
      detail_ko: inSource ? `${input.sourceChannel} 채널 소속 확인됨` : `${input.sourceChannel} 채널 소속 아님`,
    },
    {
      id: "recall-safety",
      label: "Release & capability recall gate",
      label_ko: "릴리스 및 기능(Capability) 리콜 무결성",
      passed: notRecalled,
      detail: notRecalled
        ? "Zero active release or capability recalls"
        : input.release.state === "recalled"
          ? "Release is recalled"
          : `Blocked by recalled capability: ${blockedCaps.join(", ")}`,
      detail_ko: notRecalled
        ? "활성 릴리스/기능 리콜 없음"
        : input.release.state === "recalled"
          ? "회수된 릴리스"
          : `회수된 기능 포함됨: ${blockedCaps.join(", ")}`,
    },
    {
      id: "stencil-labels",
      label: "Apollo Release & Stencil labels",
      label_ko: "Apollo 릴리스 및 Stencil 검증 레이블",
      passed: labelsOk,
      detail: labelsOk
        ? `${provLabels.size} label(s) satisfied`
        : `Missing required label(s): ${missingLabels.join(", ")}`,
      detail_ko: labelsOk
        ? `검증 레이블 ${provLabels.size}개 충족`
        : `누락된 필수 레이블: ${missingLabels.join(", ")}`,
    },
    {
      id: "soak-window",
      label: "Stage soak & observation window",
      label_ko: "단계 관찰 시간 (Soak Window)",
      passed: soakOk,
      detail: `Observed ${elapsed}s / required ${minSoak}s`,
      detail_ko: `관찰 ${elapsed}초 / 최소 요구 ${minSoak}초`,
    },
  ];
  if (input.manifest.stencil) {
    const st = input.manifest.stencil;
    const ff = st.feature_flags;
    const lockedPanelsOk =
      st.enabled_panel_ids.includes("audit") &&
      st.enabled_panel_ids.includes("dashboard") &&
      st.enabled_panel_ids.includes("settings-general") &&
      (!ff ||
        (ff.enforcement_mode === "fail-closed" &&
          ff.panel_flags.audit === true &&
          ff.panel_flags.dashboard === true &&
          ff.panel_flags["settings-general"] === true));
    gates.push({
      id: "stencil-feature-flags",
      label: "Stencil fail-closed feature-flag gate",
      label_ko: "Stencil 비활성 메뉴 Feature Flag 게이트",
      passed: lockedPanelsOk,
      detail: lockedPanelsOk
        ? `fail-closed verified (${st.enabled_panel_ids.length} active menus)`
        : "Stencil feature flags missing locked safety-core panels or fail-closed mode",
      detail_ko: lockedPanelsOk
        ? `fail-closed 검증됨 (활성 메뉴 ${st.enabled_panel_ids.length}개)`
        : "필수 안전 코어 메뉴 또는 fail-closed 정책 누락",
    });
  }
  return {
    allowed: gates.every((g) => g.passed),
    gates,
  };
}

export type ApolloReleaseDiff = {
  baseId: string;
  targetId: string;
  baseProfile: string;
  targetProfile: string;
  addedWorkloads: string[];
  removedWorkloads: string[];
  changedComponents: string[];
  addedPanels: string[];
  removedPanels: string[];
  addedLoops: string[];
  removedLoops: string[];
  addedPanelCount: number;
  removedPanelCount: number;
  rbacChanged: boolean;
  featureFlagEnforcementChanged: boolean;
  baseRbac: string;
  targetRbac: string;
};

export function computeApolloReleaseDiff(base: Release, target: Release): ApolloReleaseDiff {
  const baseManifest = parseReleaseManifest(base.manifest);
  const targetManifest = parseReleaseManifest(target.manifest);
  const baseSt = extractReleaseStencil(baseManifest);
  const targetSt = extractReleaseStencil(targetManifest);

  const baseArts = new Map(artifacts(baseManifest).map((a) => [a.component, a.digest]));
  const targetArts = new Map(artifacts(targetManifest).map((a) => [a.component, a.digest]));

  const baseWorkloads = new Set(baseSt?.enabled_workloads ?? [...baseArts.keys()]);
  const targetWorkloads = new Set(targetSt?.enabled_workloads ?? [...targetArts.keys()]);
  const addedWorkloads = [...targetWorkloads].filter((w) => !baseWorkloads.has(w)).sort();
  const removedWorkloads = [...baseWorkloads].filter((w) => !targetWorkloads.has(w)).sort();

  const changedComponents: string[] = [];
  for (const [comp, digest] of targetArts.entries()) {
    if (baseArts.has(comp) && baseArts.get(comp) !== digest) {
      changedComponents.push(comp);
    }
  }

  const basePanels = new Set(baseSt?.enabled_panel_ids ?? []);
  const targetPanels = new Set(targetSt?.enabled_panel_ids ?? []);
  const addedPanels = [...targetPanels].filter((p) => !basePanels.has(p)).sort();
  const removedPanels = [...basePanels].filter((p) => !targetPanels.has(p)).sort();
  const addedPanelCount = addedPanels.length;
  const removedPanelCount = removedPanels.length;

  const baseLoops = new Set(baseSt?.enabled_loops ?? []);
  const targetLoops = new Set(targetSt?.enabled_loops ?? []);
  const addedLoops = [...targetLoops].filter((l) => !baseLoops.has(l)).sort();
  const removedLoops = [...baseLoops].filter((l) => !targetLoops.has(l)).sort();

  const baseRbac = baseSt?.azure_rbac_posture ?? "standard";
  const targetRbac = targetSt?.azure_rbac_posture ?? "standard";
  const baseEnforcement = baseSt?.feature_flags?.enforcement_mode ?? (baseSt ? "fail-closed" : "unscoped");
  const targetEnforcement = targetSt?.feature_flags?.enforcement_mode ?? (targetSt ? "fail-closed" : "unscoped");

  return {
    baseId: base.id,
    targetId: target.id,
    baseProfile: baseSt?.stencil_id ?? "standard",
    targetProfile: targetSt?.stencil_id ?? "standard",
    addedWorkloads,
    removedWorkloads,
    changedComponents: changedComponents.sort(),
    addedPanels,
    removedPanels,
    addedLoops,
    removedLoops,
    addedPanelCount,
    removedPanelCount,
    rbacChanged: baseRbac !== targetRbac,
    featureFlagEnforcementChanged: baseEnforcement !== targetEnforcement,
    baseRbac,
    targetRbac,
  };
}

export type StencilPanelDescriptor = {
  id: string;
  path: string;
  group: string;
  label: string;
  label_ko: string;
  locked: boolean;
  required_workloads: string[];
  required_loops: string[];
  required_addons: string[];
  feature_ids: string[];
};

export type StencilDefinitionRecord = {
  schema_version: string;
  stencil_id: string;
  title: string;
  title_ko: string;
  description: string;
  description_ko: string;
  topology_profile: "lite-observe-alert" | "standard-sre" | "full-enterprise";
  enabled_workloads: string[];
  enabled_scheduled_jobs: string[];
  enabled_loops: string[];
  enabled_addons: string[];
  enabled_panel_ids: string[];
  authority_granted: false;
};

export type RuntimeAxisDescriptorRecord = {
  id: string;
  label: string;
  label_ko: string;
  summary: string;
  summary_ko: string;
  agents: string[];
  locked: boolean;
};

export type StencilFootprint = {
  stencil_id: string;
  stencil_digest: string;
  topology_profile: string;
  workload_count: number;
  total_workloads: number;
  omitted_workloads: string[];
  scheduled_job_count: number;
  omitted_scheduled_jobs: string[];
  omitted_loops?: string[];
  includes_clamav_sidecar: boolean;
  includes_privileged_executor: boolean;
  enabled_panel_count: number;
  total_panel_count: number;
  omitted_panel_count: number;
  disabled_panel_ids?: string[];
  disabled_loops?: string[];
  active_navigation_groups: string[];
  enabled_feature_ids: string[];
  azure_rbac_posture: string;
  required_azure_roles: string[];
  release_labels?: string[];
  feature_flags?: StencilFeatureFlagsRecord;
  dependency_reasons?: {
    workloads: Record<string, string[]>;
    loops: Record<string, string[]>;
  };
  apollo_diff_vs_full?: {
    retained_workloads: string[];
    removed_workloads: string[];
    removed_sidecars: string[];
    retained_scheduled_jobs: string[];
    removed_scheduled_jobs: string[];
    retained_loops: string[];
    removed_loops: string[];
    retained_panel_count: number;
    removed_panel_count: number;
  };
  terraform_flags: {
    enable_document_ingestion_workloads: boolean;
    enable_isolated_executor: boolean;
    product_profile_mode: string;
  };
  console_build_command: string;
};

export type StencilCatalogResponse = {
  detected_source_commit?: string | null;
  detected_source_ref?: string | null;
  presets: { stencil: StencilDefinitionRecord; footprint: StencilFootprint }[];
  panels: StencilPanelDescriptor[];
  workloads: string[];
  locked_workloads: string[];
  workloads_catalog?: RuntimeAxisDescriptorRecord[];
  scheduled_jobs: string[];
  locked_scheduled_jobs: string[];
  scheduled_jobs_catalog?: RuntimeAxisDescriptorRecord[];
  loops: string[];
  locked_loops: string[];
  loops_catalog?: RuntimeAxisDescriptorRecord[];
  addons: string[];
  locked_addons: string[];
  locked_panels: string[];
};

export type StencilComposePayload = {
  stencil_id: string;
  title: string;
  title_ko: string;
  description: string;
  description_ko: string;
  topology_profile: "lite-observe-alert" | "standard-sre" | "full-enterprise";
  requested_panel_ids: string[];
  requested_workloads: string[];
  requested_scheduled_jobs: string[];
  requested_loops: string[];
  requested_addons: string[];
  auto_resolve_dependencies: boolean;
  release_version: string;
  source_commit: string;
};

export type StencilComposeResult = {
  stencil: StencilDefinitionRecord;
  footprint: StencilFootprint;
  release_manifest: Record<string, unknown>;
};

const STENCIL_PANEL_GROUPS = new Set([
  "overview",
  "operations",
  "agents",
  "governance",
  "knowledge",
  "evidence",
  "labs",
  "settings",
]);
const STENCIL_PANEL_ID_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const STENCIL_PANEL_PATH_PATTERN = /^\/[a-z0-9]+(?:[/-][a-z0-9]+)*$/;

function boundedDisplayText(value: unknown): value is string {
  return typeof value === "string"
    && value.length <= 160
    && value.trim().length > 0
    && !/[\u0000-\u001f\u007f]/u.test(value);
}

function validStencilPanelDescriptor(value: unknown): value is StencilPanelDescriptor {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const panel = value as Record<string, unknown>;
  return typeof panel.id === "string"
    && panel.id.length <= 63
    && STENCIL_PANEL_ID_PATTERN.test(panel.id)
    && typeof panel.group === "string"
    && STENCIL_PANEL_GROUPS.has(panel.group)
    && typeof panel.path === "string"
    && panel.path.length <= 256
    && STENCIL_PANEL_PATH_PATTERN.test(panel.path)
    && boundedDisplayText(panel.label)
    && boundedDisplayText(panel.label_ko)
    && typeof panel.locked === "boolean"
    && ["required_workloads", "required_loops", "required_addons", "feature_ids"]
      .every((field) => Array.isArray(panel[field])
        && (panel[field] as unknown[]).every((item) => typeof item === "string"));
}

function validStencilDefinition(value: unknown): value is StencilDefinitionRecord {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const stencil = value as Record<string, unknown>;
  return typeof stencil.schema_version === "string"
    && typeof stencil.stencil_id === "string"
    && typeof stencil.title === "string"
    && typeof stencil.title_ko === "string"
    && typeof stencil.description === "string"
    && typeof stencil.description_ko === "string"
    && typeof stencil.topology_profile === "string"
    && stencil.authority_granted === false
    && ["enabled_workloads", "enabled_panel_ids", "enabled_scheduled_jobs", "enabled_loops", "enabled_addons"]
      .every((field) => Array.isArray(stencil[field]) && (stencil[field] as unknown[]).every((item) => typeof item === "string"));
}

function validStencilFootprint(value: unknown): value is StencilFootprint {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const footprint = value as Record<string, unknown>;
  const featureFlags = footprint.feature_flags;
  return typeof footprint.stencil_digest === "string"
    && typeof footprint.azure_rbac_posture === "string"
    && typeof footprint.console_build_command === "string"
    && typeof footprint.includes_clamav_sidecar === "boolean"
    && ["workload_count", "total_workloads", "enabled_panel_count", "total_panel_count"]
      .every((field) => typeof footprint[field] === "number" && Number.isFinite(footprint[field]))
    && ["omitted_workloads", "required_azure_roles"]
      .every((field) => Array.isArray(footprint[field]) && (footprint[field] as unknown[]).every((item) => typeof item === "string"))
    && (footprint.release_labels === undefined
      || (Array.isArray(footprint.release_labels) && footprint.release_labels.every((item) => typeof item === "string")))
    && (featureFlags === undefined || (typeof featureFlags === "object" && featureFlags !== null
      && "enforcement_mode" in featureFlags && typeof featureFlags.enforcement_mode === "string"
      && "disabled_panel_ids" in featureFlags && Array.isArray(featureFlags.disabled_panel_ids)
      && "disabled_loops" in featureFlags && Array.isArray(featureFlags.disabled_loops)));
}

export async function requestStencilCatalog(): Promise<StencilCatalogResponse> {
  const response = await authenticatedFetch("/v1/stencils", {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) {
    throw new Error(`Stencil catalog unavailable (${response.status}).`);
  }
  const raw: unknown = await response.json();
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error("Invalid Stencil catalog payload.");
  }
  const data = raw as Record<string, unknown>;
  if (!Array.isArray(data.presets)
    || !data.presets.every((item: unknown) =>
      typeof item === "object" && item !== null && "stencil" in item
      && validStencilDefinition(item.stencil) && "footprint" in item && validStencilFootprint(item.footprint))
    || !Array.isArray(data.panels)
    || !data.panels.every(validStencilPanelDescriptor)
    || new Set(
      (data.panels as StencilPanelDescriptor[]).map((panel) => panel.id),
    ).size !== data.panels.length
    || new Set(
      (data.panels as StencilPanelDescriptor[]).map((panel) => panel.path),
    ).size !== data.panels.length
    || !["workloads", "locked_workloads", "scheduled_jobs", "locked_scheduled_jobs", "loops", "locked_loops",
      "addons", "locked_addons", "locked_panels"]
      .every((field) => Array.isArray(data[field]) && (data[field] as unknown[]).every((item) => typeof item === "string"))
    || !["workloads_catalog", "scheduled_jobs_catalog", "loops_catalog"].every((field) =>
      data[field] === undefined || (Array.isArray(data[field]) && data[field].every((item: unknown) =>
        typeof item === "object" && item !== null
        && "id" in item && typeof item.id === "string"
        && "label" in item && typeof item.label === "string"
        && "label_ko" in item && typeof item.label_ko === "string"
        && "summary" in item && typeof item.summary === "string"
        && "summary_ko" in item && typeof item.summary_ko === "string"
        && "agents" in item && Array.isArray(item.agents)
        && "locked" in item && typeof item.locked === "boolean")))
  ) {
    throw new Error("Invalid Stencil catalog payload.");
  }
  return raw as StencilCatalogResponse;
}

export async function requestStencilCompose(
  payload: StencilComposePayload,
): Promise<StencilComposeResult> {
  const response = await authenticatedFetch("/v1/stencils/compose", {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(10_000),
  });
  const raw: unknown = await response.json().catch(() => ({}));
  const body = typeof raw === "object" && raw !== null && !Array.isArray(raw)
    ? raw as Record<string, unknown> : {};
  if (!response.ok) {
    const message = typeof body.error === "string" && body.error.trim()
      ? body.error
      : `Stencil composition failed (${response.status}).`;
    throw new Error(message);
  }
  if (!validStencilDefinition(body.stencil) || !validStencilFootprint(body.footprint)
    || typeof body.release_manifest !== "object" || body.release_manifest === null
    || Array.isArray(body.release_manifest)) {
    throw new Error("Invalid Stencil composition payload.");
  }
  return body as StencilComposeResult;
}

export type EntraDetectedAccount = {
  principal: string;
  tenant_id: string;
  tenant_label: string;
  is_default: boolean;
};

export type EntraActiveSession = {
  principal: string;
  display_name: string;
  tenant_id: string;
  auth_method: "entra-workstation" | "entra-msal-pkce" | "entra-remote-jwt";
  signed_in_at: string;
};

export type EntraSessionStatus = {
  authenticated: boolean;
  actor: string;
  session: EntraActiveSession | null;
  detected_accounts: EntraDetectedAccount[];
};

export async function requestEntraSession(): Promise<EntraSessionStatus | null> {
  try {
    const response = await authenticatedFetch("/v1/auth/session", {
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
    if (!response.ok) return null;
    const raw: unknown = await response.json();
    if (
      typeof raw !== "object" ||
      raw === null ||
      typeof (raw as EntraSessionStatus).authenticated !== "boolean" ||
      !Array.isArray((raw as EntraSessionStatus).detected_accounts)
    ) {
      return null;
    }
    return raw as EntraSessionStatus;
  } catch {
    return null;
  }
}

export async function requestEntraLogin(payload: {
  mode: "workstation" | "msal_account";
  principal?: string;
  display_name?: string;
  tenant_id?: string;
  client_id?: string;
}): Promise<EntraSessionStatus> {
  const response = await authenticatedFetch("/v1/auth/entra/login", {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(10_000),
  });
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    const message = typeof body.error === "string" && body.error.trim()
      ? body.error
      : `Entra ID sign-in failed (${response.status}).`;
    throw new Error(message);
  }
  return body as EntraSessionStatus;
}

export async function requestEntraLogout(): Promise<EntraSessionStatus> {
  const response = await authenticatedFetch("/v1/auth/entra/logout", {
    method: "POST",
    cache: "no-store",
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) throw new CatalogRequestError("Entra ID sign-out was rejected.", response.status);
  const result: unknown = await response.json();
  if (typeof result !== "object" || result === null || !("authenticated" in result)
    || result.authenticated !== false || !("session" in result) || result.session !== null) {
    throw new Error("Entra ID sign-out was not confirmed.");
  }
  return result as EntraSessionStatus;
}

export function parseReleaseManifest(manifest: string): ReleaseManifest {
  const parsed: unknown = JSON.parse(manifest);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Invalid manifest.");
  }
  return parsed as ReleaseManifest;
}

export function safeParseReleaseManifest(manifest: string): ReleaseManifest {
  try {
    return parseReleaseManifest(manifest);
  } catch {
    return {};
  }
}

export function syncManifestReleaseVersion(manifestJson: string, nextVersion: string): string {
  const trimmedVer = nextVersion.trim();
  if (!trimmedVer || !manifestJson.trim()) return manifestJson;
  try {
    const parsed = JSON.parse(manifestJson) as Record<string, unknown>;
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return manifestJson;
    }
    let changed = false;
    if (typeof parsed.release_version === "string" && parsed.release_version !== trimmedVer) {
      parsed.release_version = trimmedVer;
      changed = true;
    }
    if (
      typeof parsed.configuration_schema === "object" &&
      parsed.configuration_schema !== null &&
      !Array.isArray(parsed.configuration_schema)
    ) {
      const schemaObj = parsed.configuration_schema as Record<string, unknown>;
      if (typeof schemaObj.release_version === "string" && schemaObj.release_version !== trimmedVer) {
        schemaObj.release_version = trimmedVer;
        changed = true;
      }
    }
    return changed ? JSON.stringify(parsed, null, 2) : manifestJson;
  } catch {
    return manifestJson;
  }
}

export function releaseTitle(release: Release, manifest = safeParseReleaseManifest(release.manifest)): string {
  return `${manifest.product ?? "Release"} ${release.id}`;
}

export function schemaCompatibility(manifest: ReleaseManifest, locale: "en" | "ko" = "en"): string {
  if (!manifest.schema) {
    return locale === "ko" ? "선언되지 않음 (무상태 패키지)" : "Not declared (stateless package)";
  }
  return `${manifest.schema.tolerates.minimum} - ${manifest.schema.tolerates.maximum} (target ${manifest.schema.target})`;
}

function parseCatalog(value: unknown): Catalog {
  const record = (item: unknown): item is Record<string, unknown> =>
    typeof item === "object" && item !== null && !Array.isArray(item);
  const date = (item: unknown): item is string =>
    typeof item === "string" && item.trim().length > 0 && Number.isFinite(Date.parse(item));
  const strings = (item: unknown): item is string[] =>
    Array.isArray(item) && item.every((entry) => typeof entry === "string");
  if (!record(value)) throw new Error("Release Hub returned an invalid catalog.");
  const candidate = value;
  if (
    typeof candidate.revision !== "number"
    || !Number.isSafeInteger(candidate.revision)
    || candidate.revision < 0
    || !date(candidate.updated_at)
    || !date(candidate.expires_at)
    || typeof candidate.expired !== "boolean"
    || typeof candidate.key_id !== "string"
    || typeof candidate.mode !== "string"
    || (candidate.export_sha256 !== undefined && typeof candidate.export_sha256 !== "string")
    || !Array.isArray(candidate.releases)
    || !candidate.releases.every((release: unknown) =>
      record(release)
      && typeof release.id === "string"
      && typeof release.label === "string"
      && typeof release.manifest === "string"
      && typeof release.digest === "string"
      && typeof release.signed_payload_sha256 === "string"
      && (release.signature === null || typeof release.signature === "string")
      && typeof release.signature_status === "string"
      && (release.state === "draft" || release.state === "published" || release.state === "recalled")
      && strings(release.channels)
      && (release.published_at === null || date(release.published_at))
      && (release.recalled_at === null || date(release.recalled_at)))
    || !Array.isArray(candidate.events)
    || !candidate.events.every((event: unknown) =>
      record(event)
      && Number.isSafeInteger(event.revision)
      && typeof event.release_id === "string"
      && typeof event.action === "string"
      && typeof event.reason === "string"
      && (event.channel === null || typeof event.channel === "string")
      && date(event.occurred_at)
      && (event.actor === undefined || typeof event.actor === "string"))
    || !record(candidate.channels)
    || !Object.values(candidate.channels).every(strings)
  ) {
    throw new Error("Release Hub returned an invalid catalog.");
  }
  return candidate as Catalog;
}

export async function requestCatalog(path = "/v1/catalog", body?: Change): Promise<Catalog> {
  const response = await authenticatedFetch(path, {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
    ...(body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : {}),
  });
  let result: unknown;
  try {
    result = await response.json();
  } catch {
    if (!response.ok) throw new CatalogRequestError(`Request failed (${response.status}).`, response.status);
    throw new Error("Release Hub returned invalid JSON.");
  }
  if (!response.ok) {
    const message = typeof result === "object" && result !== null && "error" in result
      && typeof result.error === "string" && result.error.trim()
      ? result.error : `Request failed (${response.status}).`;
    throw new CatalogRequestError(message, response.status);
  }
  return parseCatalog(result);
}

export async function requestCatalogExport(): Promise<Blob> {
  const response = await authenticatedFetch("/v1/catalog/export", {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!response.ok) throw new CatalogRequestError("Catalog export unavailable.", response.status);
  if (!response.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    throw new Error("Catalog export returned an unexpected content type.");
  }
  return response.blob();
}

export function actionsFor(release: Release): Action[] {
  if (release.state === "recalled") return [];
  return release.state === "draft" ? ["publish"] : ["contribute", "recall"];
}

export function releaseStateIndex(releases: Release[]): ReadonlyMap<string, Release["state"]> {
  return new Map(releases.map((release) => [release.id, release.state]));
}

export function latestEligibleChannelHead(
  members: readonly string[],
  states: ReadonlyMap<string, Release["state"]>,
): string | null {
  let head: string | null = null;
  for (const id of members) {
    if (states.get(id) !== "published") continue;
    if (head === null || compareSemVer(id, head) > 0 ||
      (compareSemVer(id, head) === 0 && id.localeCompare(head) > 0)) {
      head = id;
    }
  }
  return head;
}

export function isCustomChannel(value: string): boolean {
  return value.length <= 64 && value === value.trim() && /^custom-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
}

export function artifacts(root: ReleaseManifest): { component: string; digest: string; sbom: string }[] {
  const result: { component: string; digest: string; sbom: string }[] = [];
  for (const section of ["services", "sidecars", "installation_agents", "workloads", "components", "console", "deployment_support"]) {
    const group = root[section];
    if (typeof group !== "object" || group === null) continue;
    const entries = section === "console" || section === "deployment_support"
      ? [[section, group] as const] : Object.entries(group);
    for (const [component, value] of entries) {
      if (typeof value !== "object" || value === null) continue;
      const record = value as Record<string, unknown>;
      const digest = typeof record.image_digest === "string"
        ? record.image_digest
        : typeof record.archive_sha256 === "string" ? record.archive_sha256 : null;
      if (!digest) throw new Error(`Artifact ${component} has no digest.`);
      result.push({
        component,
        digest,
        sbom: typeof record.sbom_sha256 === "string" ? record.sbom_sha256 : "Not declared",
      });
    }
  }
  return result;
}
