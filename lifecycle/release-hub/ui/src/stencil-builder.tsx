import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  extractReleaseStencil,
  parseReleaseManifest,
  requestStencilCatalog,
  requestStencilCompose,
  type Release,
  type ReleaseStencilMetadata,
  type RuntimeAxisDescriptorRecord,
  type StencilCatalogResponse,
  type StencilComposeResult,
  type StencilDefinitionRecord,
  type StencilPanelDescriptor,
} from "./api";
import { nextSuggestedSemVer } from "./release-lineage.model";

const GROUP_ORDER = [
  "overview",
  "operations",
  "agents",
  "governance",
  "knowledge",
  "evidence",
  "labs",
  "settings",
] as const;

const GROUP_LABELS: Record<string, { en: string; ko: string }> = {
  overview: { en: "Overview", ko: "개요 (Overview)" },
  operations: { en: "Operations (Live, Drift, Incidents, Alerts)", ko: "운영 (실시간·드리프트·장애·알림)" },
  agents: { en: "Agents (15-Agent Pantheon & Activity)", ko: "에이전트 (15-에이전트 판테온 및 활동)" },
  governance: { en: "Governance (Rules, Topology, Scope)", ko: "거버넌스 (규칙·토폴로지·범위)" },
  knowledge: { en: "Knowledge (Documents & Git Connectors)", ko: "지식 (문서 수집 및 Git 연동)" },
  evidence: { en: "Evidence (Audit, Trace, RCA, Reports)", ko: "증적 (감사·추적·RCA·리포트)" },
  labs: { en: "Labs", ko: "실험실 (Labs)" },
  settings: { en: "Settings", ko: "설정 (Settings)" },
};

const STENCIL_ID_RE = /^[a-z][a-z0-9-]{0,62}$/;
const SEMVER_RE = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$/;
const COMMIT_SHA_RE = /^[0-9a-f]{40}$/;

export function isValidStencilBuilderInput(input: {
  stencilId: string;
  releaseVersion: string;
  sourceCommit: string;
}): boolean {
  const commitToken = input.sourceCommit.trim().toLowerCase();
  return (
    STENCIL_ID_RE.test(input.stencilId.trim()) &&
    input.releaseVersion.trim().length <= 64 &&
    SEMVER_RE.test(input.releaseVersion.trim()) &&
    (commitToken === "auto" || commitToken === "derived" || COMMIT_SHA_RE.test(commitToken))
  );
}

export function resolvedDerivedSourceCommit(
  composed: Pick<StencilComposeResult, "release_manifest"> | null,
): string | null {
  const source = composed?.release_manifest.source_commit;
  return typeof source === "string" && COMMIT_SHA_RE.test(source) ? source : null;
}

type ReleaseDraft = Pick<Release, "id" | "label" | "manifest">;

export async function dispatchBuilderRelease(
  draft: ReleaseDraft,
  mutationsDisabled: () => boolean,
  onPrepareRelease: (draft: ReleaseDraft) => void,
  onQuickCreateRelease?: (draft: ReleaseDraft) => Promise<void> | void,
): Promise<boolean> {
  if (mutationsDisabled()) return false;
  if (onQuickCreateRelease) await onQuickCreateRelease(draft);
  else onPrepareRelease(draft);
  return true;
}

export function canQuickCreatePresetVersion(
  version: string,
  existingReleases: readonly Pick<Release, "id">[],
): boolean {
  const candidate = version.trim();
  return candidate.length <= 64 &&
    SEMVER_RE.test(candidate) &&
    !existingReleases.some((release) => release.id === candidate);
}

export function toggleRequestedItem(
  selected: readonly string[],
  value: string,
  locked: readonly string[],
): string[] {
  if (locked.includes(value)) return [...selected];
  return selected.includes(value)
    ? selected.filter((item) => item !== value)
    : [...selected, value].sort();
}

export function restoreRegisteredStencil(
  release: Release,
  catalog: StencilCatalogResponse,
): {
  stencil: ReleaseStencilMetadata;
  panels: string[];
  workloads: string[];
  loops: string[];
  jobs: string[];
  addons: string[];
  sourceMode: string;
  sourceCommit: string;
  customCommitInput: string;
} | null {
  const stencil = extractReleaseStencil(release);
  if (!stencil) return null;
  const manifest = parseReleaseManifest(release.manifest);
  const source = typeof manifest.source_commit === "string"
    ? manifest.source_commit.trim().toLowerCase()
    : "";
  const inherited = COMMIT_SHA_RE.test(source);
  return {
    stencil,
    panels: [...stencil.enabled_panel_ids],
    workloads: [...stencil.enabled_workloads],
    loops: [...(stencil.enabled_loops ?? catalog.locked_loops)],
    jobs: [...(stencil.enabled_scheduled_jobs ?? catalog.locked_scheduled_jobs)],
    addons: [...(stencil.feature_flags?.enabled_addons ?? catalog.locked_addons)],
    sourceMode: inherited ? `release:${release.id}` : catalog.detected_source_commit ? "auto" : "derived",
    sourceCommit: inherited ? source : catalog.detected_source_commit ? "auto" : "derived",
    customCommitInput: inherited ? source : catalog.detected_source_commit ?? "",
  };
}

export function groupPanelsByDomain(
  panels: readonly StencilPanelDescriptor[],
): ReadonlyMap<string, StencilPanelDescriptor[]> {
  const grouped = new Map<string, StencilPanelDescriptor[]>();
  for (const group of GROUP_ORDER) {
    grouped.set(group, []);
  }
  for (const panel of panels) {
    const bucket = grouped.get(panel.group) ?? [];
    bucket.push(panel);
    grouped.set(panel.group, bucket);
  }
  return grouped;
}

export interface LiveApolloBlueprint {
  readonly effectiveTopologyProfile: string;
  readonly effectiveWorkloads: string[];
  readonly omittedWorkloads: string[];
  readonly effectiveLoops: string[];
  readonly omittedLoops: string[];
  readonly effectiveJobs: string[];
  readonly omittedJobs: string[];
  readonly effectiveAddons: string[];
  readonly omittedAddons: string[];
  readonly effectivePanels: string[];
  readonly disabledPanels: string[];
  readonly omittedPanelCount: number;
  readonly includesClamav: boolean;
  readonly includesExecutor: boolean;
  readonly rbacPosture: "read-only-observation" | "governed-execution";
  readonly requiredAzureRoles: string[];
  readonly releaseLabels: string[];
  readonly workloadReasons: Readonly<Record<string, string[]>>;
  readonly loopReasons: Readonly<Record<string, string[]>>;
  readonly addonReasons: Readonly<Record<string, string[]>>;
  readonly panelFeatureFlags: Readonly<Record<string, boolean>>;
  readonly loopFeatureFlags: Readonly<Record<string, boolean>>;
  readonly workloadFeatureFlags: Readonly<Record<string, boolean>>;
  readonly jobFeatureFlags: Readonly<Record<string, boolean>>;
  readonly addonFeatureFlags: Readonly<Record<string, boolean>>;
  readonly runtimeEnvFlags: Readonly<Record<string, string>>;
  readonly consoleBuildCommand: string;
}

export function isAddonSelectionLocked(
  addon: string,
  catalog: Pick<StencilCatalogResponse, "locked_addons">,
  blueprint: Pick<LiveApolloBlueprint, "effectiveAddons" | "addonReasons">,
  autoResolve: boolean,
): boolean {
  return catalog.locked_addons.includes(addon) ||
    (autoResolve && blueprint.effectiveAddons.includes(addon) &&
      (blueprint.addonReasons[addon] ?? []).some((reason) => reason !== "locked-core"));
}

export function computeLiveApolloBlueprint(
  catalog: StencilCatalogResponse,
  options: {
    stencilId: string;
    topologyProfile: string;
    selectedPanels: readonly string[];
    selectedWorkloads: readonly string[];
    selectedLoops: readonly string[];
    selectedJobs: readonly string[];
    selectedAddons?: readonly string[];
    autoResolve: boolean;
  },
): LiveApolloBlueprint {
  const panelSet = new Set([...options.selectedPanels, ...catalog.locked_panels]);
  const workloadSet = new Set([...options.selectedWorkloads, ...catalog.locked_workloads]);
  const loopSet = new Set([...options.selectedLoops, ...catalog.locked_loops]);
  const jobSet = new Set([...options.selectedJobs, ...catalog.locked_scheduled_jobs]);
  const addonSet = new Set([...(options.selectedAddons ?? []), ...catalog.locked_addons]);

  const workloadReasons: Record<string, string[]> = {};
  const loopReasons: Record<string, string[]> = {};
  const addonReasons: Record<string, string[]> = {};
  const addAddonReason = (id: string, reason: string) => {
    addonReasons[id] = [...new Set([...(addonReasons[id] ?? []), reason])];
  };
  for (const w of catalog.locked_workloads) workloadReasons[w] = ["locked-core"];
  for (const l of catalog.locked_loops) loopReasons[l] = ["locked-core"];
  for (const a of catalog.locked_addons) addAddonReason(a, "locked-core");

  const panelById = new Map(catalog.panels.map((p) => [p.id, p]));
  if (
    options.autoResolve &&
    (panelSet.has("settings-environment") ||
      panelSet.has("provision") ||
      panelSet.has("onboarding"))
  ) {
    for (const envPanel of ["settings-environment", "provision", "onboarding"]) {
      if (panelById.has(envPanel)) panelSet.add(envPanel);
    }
  }
  for (const panelId of [...panelSet].sort()) {
    const desc = panelById.get(panelId);
    if (!desc) continue;
    for (const reqW of desc.required_workloads) {
      if (options.autoResolve) workloadSet.add(reqW);
      workloadReasons[reqW] = [...new Set([...(workloadReasons[reqW] ?? []), `menu:${panelId}`])];
    }
    for (const reqL of desc.required_loops) {
      if (options.autoResolve) loopSet.add(reqL);
      loopReasons[reqL] = [...new Set([...(loopReasons[reqL] ?? []), `menu:${panelId}`])];
    }
    for (const reqA of desc.required_addons) {
      if (options.autoResolve) addonSet.add(reqA);
      addAddonReason(reqA, `menu:${panelId}`);
    }
  }

  let effectiveTopologyProfile = options.topologyProfile;
  if (options.autoResolve) {
    if (
      loopSet.has("document-ingestion") ||
      workloadSet.has("document-ingestion-api") ||
      workloadSet.has("document-processing-worker")
    ) {
      workloadSet.add("document-ingestion-api");
      workloadSet.add("document-processing-worker");
      loopSet.add("document-ingestion");
    }
    if (loopSet.has("remediation-execution") || workloadSet.has("isolated-executor")) {
      for (const addon of ["enterprise-identity-governance", "governed-execution"]) {
        if (loopSet.has("remediation-execution")) addAddonReason(addon, "loop:remediation-execution");
        if (workloadSet.has("isolated-executor")) addAddonReason(addon, "workload:isolated-executor");
      }
      workloadSet.add("isolated-executor");
      loopSet.add("remediation-execution");
      addonSet.add("enterprise-identity-governance");
      addonSet.add("governed-execution");
    }
    if (jobSet.has("cost-collector") || loopSet.has("cost-governance")) {
      loopSet.add("cost-governance");
      jobSet.add("cost-collector");
    }
    if (loopSet.has("document-ingestion")) {
      effectiveTopologyProfile = "full-enterprise";
    } else if (
      effectiveTopologyProfile === "lite-observe-alert" &&
      (workloadSet.size > catalog.locked_workloads.length ||
        addonSet.has("governed-execution") ||
        loopSet.has("remediation-execution"))
    ) {
      effectiveTopologyProfile = "standard-sre";
    }
  }
  for (const addon of ["governed-execution", "policy-administration"]) {
    if (addonSet.has(addon)) {
      addAddonReason("enterprise-identity-governance", `addon:${addon}`);
      if (options.autoResolve) addonSet.add("enterprise-identity-governance");
    }
  }

  const effectiveWorkloads = [...workloadSet].sort();
  const omittedWorkloads = catalog.workloads.filter((w) => !workloadSet.has(w)).sort();
  const effectiveLoops = [...loopSet].sort();
  const omittedLoops = catalog.loops.filter((l) => !loopSet.has(l)).sort();
  const effectiveJobs = [...jobSet].sort();
  const omittedJobs = catalog.scheduled_jobs.filter((j) => !jobSet.has(j)).sort();
  const effectiveAddons = [...addonSet].sort();
  const omittedAddons = catalog.addons.filter((a) => !addonSet.has(a)).sort();
  const effectivePanels = [...panelSet].sort();
  const disabledPanels = catalog.panels
    .map((p) => p.id)
    .filter((id) => !panelSet.has(id))
    .sort();
  const omittedPanelCount = Math.max(0, catalog.panels.length - effectivePanels.length);

  const panelFeatureFlags: Record<string, boolean> = {};
  for (const p of [...catalog.panels.map((item) => item.id)].sort()) {
    panelFeatureFlags[p] = panelSet.has(p);
  }
  const loopFeatureFlags: Record<string, boolean> = {};
  for (const l of [...catalog.loops].sort()) {
    loopFeatureFlags[l] = loopSet.has(l);
  }
  const workloadFeatureFlags: Record<string, boolean> = {};
  for (const w of [...catalog.workloads].sort()) {
    workloadFeatureFlags[w] = workloadSet.has(w);
  }
  const jobFeatureFlags: Record<string, boolean> = {};
  for (const j of [...catalog.scheduled_jobs].sort()) {
    jobFeatureFlags[j] = jobSet.has(j);
  }
  const addonFeatureFlags: Record<string, boolean> = {};
  for (const a of [...catalog.addons].sort()) {
    addonFeatureFlags[a] = addonSet.has(a);
  }

  const includesClamav = workloadSet.has("document-ingestion-api");
  const includesExecutor = workloadSet.has("isolated-executor");
  const rbacPosture = includesExecutor ? "governed-execution" : "read-only-observation";
  const requiredAzureRoles = ["Reader", "Monitoring Reader", "Log Analytics Reader"];
  if (loopSet.has("cost-governance")) requiredAzureRoles.push("Cost Management Reader");
  if (includesExecutor && addonSet.has("governed-execution")) {
    requiredAzureRoles.push("Scoped Executor Action Role (privileged mutation)");
  }

  const cleanId = options.stencilId.trim() || "custom-stencil";
  const releaseLabels = [
    `stencil:${cleanId}`,
    `profile:${effectiveTopologyProfile}`,
    `rbac:${rbacPosture}`,
    `clamav:${includesClamav ? "included" : "omitted"}`,
    `executor:${includesExecutor ? "included" : "omitted"}`,
    `workloads:${effectiveWorkloads.length}`,
    `menus:${effectivePanels.length}`,
  ];

  const runtimeEnvFlags: Record<string, string> = {
    FDAI_STENCIL_ID: cleanId,
    FDAI_STENCIL_ENABLED_PANELS: effectivePanels.join(","),
    FDAI_STENCIL_DISABLED_PANELS: disabledPanels.join(","),
    FDAI_STENCIL_ENABLED_LOOPS: effectiveLoops.join(","),
    FDAI_STENCIL_DISABLED_LOOPS: omittedLoops.join(","),
    FDAI_STENCIL_ENABLED_WORKLOADS: effectiveWorkloads.join(","),
    FDAI_STENCIL_DISABLED_WORKLOADS: omittedWorkloads.join(","),
    FDAI_STENCIL_ENABLED_JOBS: effectiveJobs.join(","),
    FDAI_STENCIL_DISABLED_JOBS: omittedJobs.join(","),
    FDAI_STENCIL_ENABLED_ADDONS: effectiveAddons.join(","),
    FDAI_STENCIL_DISABLED_ADDONS: omittedAddons.join(","),
    FDAI_STENCIL_ENFORCE_INACTIVE_MENUS: "1",
  };

  return {
    effectiveTopologyProfile,
    effectiveWorkloads,
    omittedWorkloads,
    effectiveLoops,
    omittedLoops,
    effectiveJobs,
    omittedJobs,
    effectiveAddons,
    omittedAddons,
    effectivePanels,
    disabledPanels,
    omittedPanelCount,
    includesClamav,
    includesExecutor,
    rbacPosture,
    requiredAzureRoles,
    releaseLabels,
    workloadReasons,
    loopReasons,
    addonReasons,
    panelFeatureFlags,
    loopFeatureFlags,
    workloadFeatureFlags,
    jobFeatureFlags,
    addonFeatureFlags,
    runtimeEnvFlags,
    consoleBuildCommand: `FDAI_STENCIL_ENABLED_PANELS='${effectivePanels.join(",")}' npm --prefix console run build`,
  };
}

export function StencilBuilder({
  locale: externalLocale,
  onLocaleChange,
  existingReleases = [],
  onPrepareRelease,
  onQuickCreateRelease,
  mutationsDisabled = false,
}: {
  locale?: "en" | "ko";
  onLocaleChange?: (next: "en" | "ko") => void;
  existingReleases?: readonly Release[];
  onPrepareRelease: (draft: { id: string; label: string; manifest: string }) => void;
  onQuickCreateRelease?: (draft: { id: string; label: string; manifest: string }) => Promise<void> | void;
  mutationsDisabled?: boolean;
}) {
  const [internalLocale, setInternalLocale] = useState<"en" | "ko">(
    navigator.language.startsWith("ko") ? "ko" : "en",
  );
  const locale = externalLocale ?? internalLocale;
  const setLocale = (next: "en" | "ko") => {
    setInternalLocale(next);
    onLocaleChange?.(next);
  };
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);

  const [catalog, setCatalog] = useState<StencilCatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [composing, setComposing] = useState(false);

  const [stencilId, setStencilId] = useState("lite-observe-alert");
  const [title, setTitle] = useState("Lite: Agent-Driven Observe, Drift & Alert");
  const [titleKo, setTitleKo] = useState("경량 에디션: 에이전트 주도 변경·장애 감지 및 알림");
  const [description, setDescription] = useState(
    "Minimal Azure resource footprint. Runs Core 15-agent pantheon and Operator API only for continuous resource change/drift detection, deterministic anomaly detection, and notifications.",
  );
  const [descriptionKo, setDescriptionKo] = useState(
    "최소한의 Azure 리소스만 생성하는 경량 버전입니다. Core 15-에이전트 판테온과 Operator API만으로 리소스 변경/드리프트 감지, 장애 감지, 알림 발송만 수행합니다.",
  );
  const [topologyProfile, setTopologyProfile] = useState<
    "lite-observe-alert" | "standard-sre" | "full-enterprise"
  >("lite-observe-alert");
  const [selectedPanels, setSelectedPanels] = useState<string[]>([]);
  const [selectedWorkloads, setSelectedWorkloads] = useState<string[]>([]);
  const [selectedJobs, setSelectedJobs] = useState<string[]>([]);
  const [selectedLoops, setSelectedLoops] = useState<string[]>([]);
  const [selectedAddons, setSelectedAddons] = useState<string[]>([]);
  const [autoResolve, setAutoResolve] = useState(true);
  const [releaseVersion, setReleaseVersion] = useState(() =>
    nextSuggestedSemVer(existingReleases, "patch"),
  );
  const [versionEdited, setVersionEdited] = useState(false);
  const [sourceMode, setSourceMode] = useState<string>("auto");
  const [sourceCommit, setSourceCommit] = useState("auto");
  const [customCommitInput, setCustomCommitInput] = useState("");
  const [composed, setComposed] = useState<StencilComposeResult | null>(null);
  const [menuQuery, setMenuQuery] = useState("");
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);
  const mutationsDisabledRef = useRef(mutationsDisabled);
  mutationsDisabledRef.current = mutationsDisabled;
  const releaseMutationsDisabled = () => mutationsDisabledRef.current;

  useEffect(() => {
    if (!versionEdited) {
      setReleaseVersion(nextSuggestedSemVer(existingReleases, "patch"));
    }
  }, [existingReleases, versionEdited]);

  const releaseProvenanceList = useMemo(() => {
    const items: { id: string; label: string; commit: string }[] = [];
    for (const rel of existingReleases) {
      try {
        const parsed = parseReleaseManifest(rel.manifest);
        const sha = typeof parsed.source_commit === "string" ? parsed.source_commit.trim().toLowerCase() : "";
        if (COMMIT_SHA_RE.test(sha)) {
          items.push({ id: rel.id, label: rel.label || `Release ${rel.id}`, commit: sha });
        }
      } catch {
        // Ignore unparseable legacy manifests
      }
    }
    return items;
  }, [existingReleases]);

  function applyPreset(preset: StencilDefinitionRecord) {
    setStencilId(preset.stencil_id);
    setTitle(preset.title);
    setTitleKo(preset.title_ko);
    setDescription(preset.description);
    setDescriptionKo(preset.description_ko);
    setTopologyProfile(preset.topology_profile);
    setSelectedPanels([...preset.enabled_panel_ids]);
    setSelectedWorkloads([...preset.enabled_workloads]);
    setSelectedJobs([...preset.enabled_scheduled_jobs]);
    setSelectedLoops([...preset.enabled_loops]);
    setSelectedAddons([...preset.enabled_addons]);
  }

  useEffect(() => {
    let active = true;
    setLoading(true);
    void requestStencilCatalog()
      .then((data) => {
        if (!active) return;
        setCatalog(data);
        if (data.detected_source_commit) {
          setSourceMode("auto");
          setSourceCommit("auto");
          setCustomCommitInput(data.detected_source_commit);
        } else {
          setSourceMode("derived");
          setSourceCommit("derived");
        }
        const lite = data.presets.find((p) => p.stencil.stencil_id === "lite-observe-alert")
          ?? data.presets[0];
        if (lite) {
          applyPreset(lite.stencil);
        }
        setError("");
      })
      .catch((err) => {
        if (active) setError(err instanceof Error ? err.message : "Failed to load Stencil catalog.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const groupedPanels = useMemo(
    () => (catalog ? groupPanelsByDomain(catalog.panels) : new Map<string, StencilPanelDescriptor[]>()),
    [catalog],
  );

  const liveBlueprint = useMemo(
    () =>
      catalog
        ? computeLiveApolloBlueprint(catalog, {
            stencilId,
            topologyProfile,
            selectedPanels,
            selectedWorkloads,
            selectedLoops,
            selectedJobs,
            selectedAddons,
            autoResolve,
          })
        : null,
    [
      catalog,
      stencilId,
      topologyProfile,
      selectedPanels,
      selectedWorkloads,
      selectedLoops,
      selectedJobs,
      selectedAddons,
      autoResolve,
    ],
  );

  const workloadMetaMap = useMemo(
    () => new Map((catalog?.workloads_catalog ?? []).map((w) => [w.id, w])),
    [catalog],
  );
  const loopMetaMap = useMemo(
    () => new Map((catalog?.loops_catalog ?? []).map((l) => [l.id, l])),
    [catalog],
  );
  const jobMetaMap = useMemo(
    () => new Map((catalog?.scheduled_jobs_catalog ?? []).map((j) => [j.id, j])),
    [catalog],
  );

  function renderAxisCard(
    id: string,
    meta: RuntimeAxisDescriptorRecord | undefined,
    checked: boolean,
    locked: boolean,
    reasons: readonly string[],
    onToggle: () => void,
    dependencyLocked = false,
  ) {
    const linkedReasons = reasons.filter((r) => r !== "locked-core")
      .map((r) => r.startsWith("menu:") ? r.slice(5) : r);
    return (
      <label key={id} class={`stencil-axis-card ${checked ? "is-on" : ""}`}>
        <input type="checkbox" checked={checked} disabled={locked || dependencyLocked} onChange={onToggle} />
        <div class="stencil-axis-body">
          <div class="stencil-axis-head">
            <strong>{meta ? (locale === "ko" ? meta.label_ko : meta.label) : id}</strong>
            <span class="stencil-badges">
              {locked && (
                <span class="stencil-pill locked">{t("Locked core", "필수 코어")}</span>
              )}
              {!locked && linkedReasons.length > 0 && (
                <span
                  class="stencil-pill linked"
                  title={`Required by: ${linkedReasons.join(", ")}`}
                >
                  {t(`Required: ${linkedReasons.slice(0, 2).join(", ")}`, `필수 의존: ${linkedReasons.slice(0, 2).join(", ")}`)}
                </span>
              )}
            </span>
          </div>
          {meta && (
            <p class="stencil-axis-desc">
              {locale === "ko" ? meta.summary_ko : meta.summary}
            </p>
          )}
          <div class="stencil-axis-meta">
            <code>{id}</code>
            {meta && meta.agents.length > 0 && (
              <span class="stencil-agents">
                {t("Agents:", "담당 에이전트:")} {meta.agents.join(" · ")}
              </span>
            )}
          </div>
        </div>
      </label>
    );
  }

  function toggleItem(list: string[], value: string, locked: string[], setter: (next: string[]) => void) {
    if (locked.includes(value)) return;
    setComposed(null);
    setter(toggleRequestedItem(list, value, locked));
  }

  function toggleGroupPanels(groupPanels: StencilPanelDescriptor[], enableAll: boolean) {
    if (!catalog) return;
    setComposed(null);
    const locked = new Set(catalog.locked_panels);
    const groupIds = new Set(groupPanels.map((p) => p.id));
    if (enableAll) {
      const merged = new Set([...selectedPanels, ...groupIds]);
      setSelectedPanels([...merged].sort());
    } else {
      const filtered = selectedPanels.filter((id) => !groupIds.has(id) || locked.has(id));
      setSelectedPanels(filtered.sort());
    }
  }

  const validInputs = isValidStencilBuilderInput({
    stencilId,
    releaseVersion,
    sourceCommit,
  });
  const quickPresetVersionValid = canQuickCreatePresetVersion(releaseVersion, existingReleases);

  async function runCompose(event?: SubmitEvent, openRegisterAfter = false, quickCreate = false) {
    event?.preventDefault();
    if (composing || !validInputs || (openRegisterAfter && releaseMutationsDisabled())) return;
    setComposing(true);
    setError("");
    try {
      const result = await requestStencilCompose({
        stencil_id: stencilId.trim(),
        title: title.trim(),
        title_ko: titleKo.trim(),
        description: description.trim(),
        description_ko: descriptionKo.trim(),
        topology_profile: topologyProfile,
        requested_panel_ids: selectedPanels,
        requested_workloads: selectedWorkloads,
        requested_scheduled_jobs: selectedJobs,
        requested_loops: selectedLoops,
        requested_addons: selectedAddons,
        auto_resolve_dependencies: autoResolve,
        release_version: releaseVersion.trim(),
        source_commit: sourceCommit.trim(),
      });
      setComposed(result);
      // The response contains dependency-closed selections. Keep the operator's
      // explicit choices so removing a menu can remove its implicit dependencies.
      const effectiveVersion =
        typeof result.release_manifest?.release_version === "string" &&
        result.release_manifest.release_version.trim()
          ? result.release_manifest.release_version.trim()
          : releaseVersion.trim();
      setReleaseVersion(effectiveVersion);
      const draft = {
        id: effectiveVersion,
        label: `${result.stencil.stencil_id} (${result.footprint.enabled_panel_count} menus, ${result.footprint.workload_count} workloads)`,
        manifest: JSON.stringify(result.release_manifest, null, 2),
      };
      if (openRegisterAfter) await dispatchBuilderRelease(
        draft, releaseMutationsDisabled, onPrepareRelease,
        quickCreate ? onQuickCreateRelease : undefined,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stencil composition failed.");
    } finally {
      setComposing(false);
    }
  }

  async function runQuickPresetRelease(preset: StencilDefinitionRecord) {
    if (composing || !quickPresetVersionValid || releaseMutationsDisabled()) return;
    setComposing(true);
    setError("");
    try {
      const targetVer = releaseVersion.trim();
      const result = await requestStencilCompose({
        stencil_id: preset.stencil_id,
        title: preset.title,
        title_ko: preset.title_ko,
        description: preset.description,
        description_ko: preset.description_ko,
        topology_profile: preset.topology_profile,
        requested_panel_ids: [...preset.enabled_panel_ids],
        requested_workloads: [...preset.enabled_workloads],
        requested_scheduled_jobs: [...preset.enabled_scheduled_jobs],
        requested_loops: [...preset.enabled_loops],
        requested_addons: [...preset.enabled_addons],
        auto_resolve_dependencies: true,
        release_version: targetVer,
        source_commit: sourceCommit.trim() || "auto",
      });
      setComposed(result);
      applyPreset(preset);
      const draft = {
        id: targetVer,
        label: `${result.stencil.stencil_id} (${result.footprint.enabled_panel_count} menus, ${result.footprint.workload_count} workloads)`,
        manifest: JSON.stringify(result.release_manifest, null, 2),
      };
      await dispatchBuilderRelease(draft, releaseMutationsDisabled, onPrepareRelease, onQuickCreateRelease);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stencil composition failed.");
    } finally {
      setComposing(false);
    }
  }

  return (
    <div class="stencil-builder" lang={locale}>
      <div class="page-head">
        <div>
          <p class="eyebrow">{t("Build-time feature & menu composition", "빌드 타임 기능 및 메뉴 구성")}</p>
          <h1>{t("Stencils & Custom Build", "Stencil 및 커스텀 메뉴 빌드")}</h1>
        </div>
        {!externalLocale && <label style="display: inline-flex; align-items: center; gap: 8px; font-size: var(--cs-type-compact-size); color: var(--cs-text-soft);">
          {t("Builder language", "빌더 언어")}{" "}
          <select value={locale} onChange={(e) => setLocale(e.currentTarget.value as "en" | "ko")}>
            <option value="en">English</option>
            <option value="ko">한국어</option>
          </select>
        </label>}
      </div>

      {loading && <p role="status" class="empty">{t("Loading Stencil catalog...", "Stencil 카탈로그 불러오는 중...")}</p>}
      {error && <p role="alert" class="error">{error}</p>}

      {catalog && liveBlueprint && (
        <>
          <section aria-labelledby="stencil-presets-title">
            <h2 id="stencil-presets-title">{t("1. Edition presets", "1. 에디션 프리셋 선택")}</h2>
            <div class="channel-grid">
              {catalog.presets.map(({ stencil: preset, footprint }) => {
                const isSelected = stencilId === preset.stencil_id;
                return (
                  <article
                    key={preset.stencil_id}
                    class={`preset-card ${isSelected ? "active" : ""}`}
                  >
                    <div class="preset-card-head">
                      <h3>{locale === "ko" ? preset.title_ko : preset.title}</h3>
                      {isSelected && (
                        <span class="stencil-pill active-pill">
                          {t("Active base", "현재 기준")}
                        </span>
                      )}
                    </div>
                    <p>{locale === "ko" ? preset.description_ko : preset.description}</p>
                    <div class="preset-metrics">
                      <span class="stencil-chip">
                        {t("Workloads", "워크로드")} {footprint.workload_count}/{footprint.total_workloads}
                      </span>
                      <span class="stencil-chip">
                        {t("Menus", "메뉴")} {footprint.enabled_panel_count}/{footprint.total_panel_count}
                      </span>
                      <span class="stencil-chip">
                        {footprint.azure_rbac_posture}
                      </span>
                    </div>
                    <div class="actions" style="margin-top: 8px;">
                      <button
                        type="button"
                        class="primary"
                        disabled={composing || mutationsDisabled || !quickPresetVersionValid}
                        onClick={() => void runQuickPresetRelease(preset)}
                      >
                        {t(
                          `1-Click Create (${releaseVersion.trim()})`,
                          `원클릭 즉시 생성 (${releaseVersion.trim()})`,
                        )}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          applyPreset(preset);
                          setComposed(null);
                        }}
                      >
                        {t(`Load ${preset.stencil_id}`, `${preset.stencil_id} 불러오기`)}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
            {existingReleases.some((r) => extractReleaseStencil(r) !== null) && (
              <div class="stencil-provenance-preview" style="margin-top: 16px;">
                <strong>
                  {t(
                    "Registered Stencil releases in catalog:",
                    "카탈로그에 등록된 Stencil 릴리스 불러오기:",
                  )}
                </strong>
                {existingReleases.map((r) => {
                  const st = extractReleaseStencil(r);
                  if (!st) return null;
                  return (
                    <button
                      key={r.id}
                      type="button"
                      onClick={() => {
                        const restored = restoreRegisteredStencil(r, catalog);
                        if (!restored) return;
                        setStencilId(restored.stencil.stencil_id);
                        if (restored.stencil.title) setTitle(restored.stencil.title);
                        if (restored.stencil.title_ko) setTitleKo(restored.stencil.title_ko);
                        setTopologyProfile(restored.stencil.topology_profile);
                        setSelectedWorkloads(restored.workloads);
                        setSelectedPanels(restored.panels);
                        setSelectedLoops(restored.loops);
                        setSelectedJobs(restored.jobs);
                        setSelectedAddons(restored.addons);
                        setSourceMode(restored.sourceMode);
                        setSourceCommit(restored.sourceCommit);
                        setCustomCommitInput(restored.customCommitInput);
                        setComposed(null);
                      }}
                    >
                      {t(
                        `Load ${st.stencil_id} (Release ${r.id})`,
                        `${st.stencil_id} 불러오기 (릴리스 ${r.id})`,
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </section>

          <div class="stencil-workspace">
            <form class="stencil-main-column" onSubmit={runCompose}>
              <section aria-labelledby="stencil-identity-title">
                <h2 id="stencil-identity-title">
                  {t("2. Stencil identity & target release", "2. Stencil 식별자 및 대상 릴리스")}
                </h2>
                <div class="stencil-grid">
                  <label>
                    {t("Stencil ID", "Stencil ID")}
                    <input
                      required
                      pattern="[a-z][a-z0-9\-]{0,62}"
                      value={stencilId}
                      onInput={(e) => {
                        setStencilId(e.currentTarget.value);
                        setComposed(null);
                      }}
                    />
                  </label>
                  <label>
                    {t("Topology profile", "토폴로지 프로파일")}
                    <select
                      value={topologyProfile}
                      onChange={(e) => {
                        setTopologyProfile(
                          e.currentTarget.value as
                            | "lite-observe-alert"
                            | "standard-sre"
                            | "full-enterprise",
                        );
                        setComposed(null);
                      }}
                    >
                      <option value="lite-observe-alert">
                        {t("lite-observe-alert (Minimal resources, read-only)", "lite-observe-alert (최소 리소스·감지/알림 전용)")}
                      </option>
                      <option value="standard-sre">
                        {t("standard-sre (SRE + HIL execution)", "standard-sre (표준 SRE + 승인 실행)")}
                      </option>
                      <option value="full-enterprise">
                        {t("full-enterprise (Full stack + Knowledge + FinOps)", "full-enterprise (전체 기능 + 지식 + 비용)")}
                      </option>
                    </select>
                  </label>
                  <label>
                    {t("Target Release version (SemVer - defaults to patch)", "대상 릴리스 버전 (SemVer - 기본 하위 패치 증가)")}
                    <input
                      required
                      value={releaseVersion}
                      onInput={(e) => {
                        setVersionEdited(true);
                        setReleaseVersion(e.currentTarget.value);
                        setComposed(null);
                      }}
                    />
                    {existingReleases.some((r) => r.id === releaseVersion.trim()) && (
                      <small class="warning" role="status">
                        {t(
                          `Release ${releaseVersion.trim()} is already registered. Choose the next patch (${nextSuggestedSemVer(existingReleases, "patch")}).`,
                          `릴리스 ${releaseVersion.trim()} 버전은 이미 등록되어 있습니다. 다음 패치 버전(${nextSuggestedSemVer(existingReleases, "patch")})을 선택하세요.`,
                        )}
                      </small>
                    )}
                    <div class="quick-chips">
                      <button
                        type="button"
                        class="chip-btn"
                        onClick={() => {
                          setVersionEdited(false);
                          setReleaseVersion(nextSuggestedSemVer(existingReleases, "patch"));
                          setComposed(null);
                        }}
                      >
                        {t(
                          `Patch (${nextSuggestedSemVer(existingReleases, "patch")})`,
                          `하위 패치 (${nextSuggestedSemVer(existingReleases, "patch")})`,
                        )}
                      </button>
                      <button
                        type="button"
                        class="chip-btn"
                        onClick={() => {
                          setVersionEdited(true);
                          setReleaseVersion(nextSuggestedSemVer(existingReleases, "minor"));
                          setComposed(null);
                        }}
                      >
                        {t(
                          `Minor upgrade (${nextSuggestedSemVer(existingReleases, "minor")})`,
                          `마이너 업그레이드 (${nextSuggestedSemVer(existingReleases, "minor")})`,
                        )}
                      </button>
                      <button
                        type="button"
                        class="chip-btn"
                        onClick={() => {
                          setVersionEdited(true);
                          setReleaseVersion(nextSuggestedSemVer(existingReleases, "major"));
                          setComposed(null);
                        }}
                      >
                        {t(
                          `Major upgrade (${nextSuggestedSemVer(existingReleases, "major")})`,
                          `메이저 업그레이드 (${nextSuggestedSemVer(existingReleases, "major")})`,
                        )}
                      </button>
                    </div>
                  </label>
                </div>
                <details class="stencil-collapsible" open={sourceMode === "custom"}>
                  <summary>
                    <span>{t("Source commit provenance & dependency options", "소스 커밋 출처 및 의존성 자동 해결 옵션")}</span>
                    <span class="summary-meta">
                      <span class="stencil-chip">{sourceMode === "auto" ? "Git HEAD" : sourceMode}</span>
                    </span>
                  </summary>
                  <div class="stencil-grid" style="margin-top: 8px;">
                  <label class="stencil-provenance-span">
                    {t("Source commit provenance", "소스 커밋 출처 (자동 바인딩)")}
                    <select
                      value={sourceMode}
                      onChange={(e) => {
                        const mode = e.currentTarget.value;
                        setSourceMode(mode);
                        setComposed(null);
                        if (mode === "auto") {
                          setSourceCommit("auto");
                        } else if (mode === "derived") {
                          setSourceCommit("derived");
                        } else if (mode.startsWith("release:")) {
                          const relId = mode.slice(8);
                          const found = releaseProvenanceList.find((r) => r.id === relId);
                          if (found) {
                            setSourceCommit(found.commit);
                            setCustomCommitInput(found.commit);
                          }
                        } else if (mode === "custom") {
                          const initial = catalog.detected_source_commit ?? "";
                          const nextCustom = COMMIT_SHA_RE.test(customCommitInput)
                            ? customCommitInput
                            : initial;
                          setCustomCommitInput(nextCustom);
                          setSourceCommit(nextCustom);
                        }
                      }}
                    >
                      {catalog.detected_source_commit && (
                        <option value="auto">
                          {t(
                            `Workspace Git HEAD (${catalog.detected_source_ref ?? "HEAD"} · ${catalog.detected_source_commit.slice(0, 10)})`,
                            `워크스페이스 Git HEAD 자동 감지 (${catalog.detected_source_ref ?? "HEAD"} · ${catalog.detected_source_commit.slice(0, 10)})`,
                          )}
                        </option>
                      )}
                      <option value="derived">
                        {t(
                          "Auto-derive deterministic SHA from Stencil + SemVer",
                          "Stencil 구성 + 버전 기반 결정론적 SHA 자동 생성",
                        )}
                      </option>
                      {releaseProvenanceList.map((item) => (
                        <option key={item.id} value={`release:${item.id}`}>
                          {t(
                            `Inherit from Release ${item.id} (${item.commit.slice(0, 10)})`,
                            `기존 릴리스 ${item.id}에서 상속 (${item.commit.slice(0, 10)})`,
                          )}
                        </option>
                      ))}
                      <option value="custom">
                        {t(
                          "Custom full 40-hex commit SHA...",
                          "직접 입력 (전체 40자 커밋 SHA)...",
                        )}
                      </option>
                    </select>
                  </label>
                  <div class="stencil-provenance-span">
                    {sourceMode !== "custom" ? (
                      <div class="stencil-provenance-preview">
                        <span class="stencil-pill locked">
                          {sourceMode === "auto"
                            ? t("Git HEAD bound", "Git HEAD 자동 바인딩")
                            : sourceMode === "derived"
                              ? t("Deterministic SHA", "결정론적 자동 파생")
                              : t("Release inherited", "릴리스 상속됨")}
                        </span>
                        {sourceMode === "auto" && catalog.detected_source_ref && (
                          <span class="stencil-chip">{catalog.detected_source_ref}</span>
                        )}
                        <code>
                          {sourceMode === "auto" && catalog.detected_source_commit
                            ? catalog.detected_source_commit
                            : sourceMode === "derived"
                              ? resolvedDerivedSourceCommit(composed) ?? t("Resolved by server at compose time", "구성 시 서버에서 확정")
                              : sourceCommit}
                        </code>
                      </div>
                    ) : (
                      <div class="stencil-custom-sha-box">
                        <input
                          required
                          placeholder={t(
                            "Paste the real full 40-hex commit SHA",
                            "실제 전체 40자 커밋 SHA를 입력하세요",
                          )}
                          value={customCommitInput}
                          onInput={(e) => {
                            const val = e.currentTarget.value.trim().toLowerCase();
                            setCustomCommitInput(val);
                            setSourceCommit(val);
                            setComposed(null);
                          }}
                        />
                        {customCommitInput && !COMMIT_SHA_RE.test(customCommitInput) && (
                          <small class="warning" role="status">
                            {t("A real full 40-hex commit SHA is required; short SHAs and tags cannot be expanded here.", "실제 전체 40자 커밋 SHA가 필요합니다. 짧은 SHA와 태그는 여기서 확장할 수 없습니다.")}
                          </small>
                        )}
                        <div class="stencil-sha-actions">
                          {catalog.detected_source_commit && (
                            <button
                              type="button"
                              onClick={() => {
                                const head = catalog.detected_source_commit!;
                                setCustomCommitInput(head);
                                setSourceCommit(head);
                                setComposed(null);
                              }}
                            >
                              {t("Use Git HEAD", "현재 Git HEAD 채우기")}
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
                <label class="stencil-check">
                  <input
                    type="checkbox"
                    checked={autoResolve}
                    onChange={(e) => {
                      setAutoResolve(e.currentTarget.checked);
                      setComposed(null);
                    }}
                  />
                  <span>
                    {t(
                      "Automatically enable required backing workloads and agent loops for selected menus (Apollo dependency graph closure)",
                      "선택한 메뉴에 필요한 백엔드 워크로드 및 에이전트 루프 의존성을 자동으로 활성화 (Apollo 의존성 그래프 클로저)",
                    )}
                  </span>
                </label>
                </details>
              </section>

              <details class="stencil-collapsible" aria-labelledby="stencil-loops-title">
                <summary>
                  <span id="stencil-loops-title">
                    {t("3. Agent-driven loops & service workloads", "3. 에이전트 주도 루프 및 서비스 워크로드")}
                  </span>
                  <span class="summary-meta">
                    <span class="stencil-chip">
                      {t(
                        `${liveBlueprint.effectiveWorkloads.length}/${catalog.workloads.length} containers · ${liveBlueprint.effectiveLoops.length}/${catalog.loops.length} loops`,
                        `컨테이너 ${liveBlueprint.effectiveWorkloads.length}/${catalog.workloads.length} · 루프 ${liveBlueprint.effectiveLoops.length}/${catalog.loops.length}`,
                      )}
                    </span>
                  </span>
                </summary>
                <p>
                  {t(
                    "The 15-agent pantheon runs in-process inside core-control-plane. Resource change detection, anomaly detection, notifications, and Saga audit remain locked on. Optional add-ons can be chosen below; required add-ons stay linked until their dependency is removed.",
                    "15-에이전트 판테온은 core-control-plane 단일 컨테이너 내부에서 동작합니다. 리소스 변경 감지, 장애 감지, 알림 발송, 해시 체인 감사는 안전 코어로 항상 활성화됩니다. 선택적 부가 기능은 아래에서 고를 수 있으며 필수 의존 기능은 원인을 제거할 때까지 연동됩니다.",
                  )}
                </p>
                <div class="stencil-axis-sections">
                  <div class="stencil-axis-section">
                    <h3>{t("Service workloads (Containers)", "서비스 워크로드 (컨테이너)")}</h3>
                    <div class="stencil-axis-grid">
                      {catalog.workloads.map((workload) =>
                        renderAxisCard(
                          workload,
                          workloadMetaMap.get(workload),
                          liveBlueprint.effectiveWorkloads.includes(workload),
                          catalog.locked_workloads.includes(workload),
                          liveBlueprint.workloadReasons[workload] ?? [],
                          () =>
                            toggleItem(
                              selectedWorkloads,
                              workload,
                              catalog.locked_workloads,
                              setSelectedWorkloads,
                            ),
                        ),
                      )}
                    </div>
                  </div>
                  <div class="stencil-axis-section">
                    <h3>{t("Agent loops", "에이전트 루프")}</h3>
                    <div class="stencil-axis-grid">
                      {catalog.loops.map((loop) =>
                        renderAxisCard(
                          loop,
                          loopMetaMap.get(loop),
                          liveBlueprint.effectiveLoops.includes(loop),
                          catalog.locked_loops.includes(loop),
                          liveBlueprint.loopReasons[loop] ?? [],
                          () =>
                            toggleItem(
                              selectedLoops,
                              loop,
                              catalog.locked_loops,
                              setSelectedLoops,
                            ),
                        ),
                      )}
                    </div>
                  </div>
                  <div class="stencil-axis-section">
                    <h3>{t("Scheduled jobs (CronJobs)", "스케줄 잡 (CronJob)")}</h3>
                    <div class="stencil-axis-grid">
                      {catalog.scheduled_jobs.map((job) =>
                        renderAxisCard(
                          job,
                          jobMetaMap.get(job),
                          liveBlueprint.effectiveJobs.includes(job),
                          catalog.locked_scheduled_jobs.includes(job),
                          catalog.locked_scheduled_jobs.includes(job) ? ["locked-core"] : [],
                          () =>
                            toggleItem(
                              selectedJobs,
                              job,
                              catalog.locked_scheduled_jobs,
                              setSelectedJobs,
                            ),
                        ),
                      )}
                    </div>
                  </div>
                  <div class="stencil-axis-section">
                    <h3>{t(`Add-ons (${liveBlueprint.effectiveAddons.length}/${catalog.addons.length})`, `부가 기능 (${liveBlueprint.effectiveAddons.length}/${catalog.addons.length})`)}</h3>
                    <div class="stencil-axis-grid">
                      {catalog.addons.map((addon) =>
                        renderAxisCard(
                          addon,
                          undefined,
                          liveBlueprint.effectiveAddons.includes(addon),
                          catalog.locked_addons.includes(addon),
                          liveBlueprint.addonReasons[addon] ?? [],
                          () => toggleItem(selectedAddons, addon, catalog.locked_addons, setSelectedAddons),
                          isAddonSelectionLocked(addon, catalog, liveBlueprint, autoResolve),
                        ),
                      )}
                    </div>
                  </div>
                </div>
              </details>

              <details class="stencil-collapsible" aria-labelledby="stencil-menus-title">
                <summary>
                  <span id="stencil-menus-title">
                    {t(
                      `4. Custom Console menus (${liveBlueprint.effectivePanels.length} / ${catalog.panels.length} enabled)`,
                      `4. 커스텀 Console 메뉴 선택 (${liveBlueprint.effectivePanels.length} / ${catalog.panels.length}개 활성화됨)`,
                    )}
                  </span>
                  <span class="summary-meta">
                    <span class="stencil-chip">
                      {t(`${liveBlueprint.disabledPanels.length} omitted`, `${liveBlueprint.disabledPanels.length}개 제외됨`)}
                    </span>
                  </span>
                </summary>
                <p>
                  {t(
                    "Unchecked menus are physically excluded from the built Console bundle chunks when built with FDAI_STENCIL_ENABLED_PANELS.",
                    "선택 해제한 메뉴는 FDAI_STENCIL_ENABLED_PANELS로 빌드할 때 최종 Console JS/CSS 번들 청크에서 물리적으로 제외됩니다.",
                  )}
                </p>
                <div class="stencil-menu-toolbar">
                  <input
                    type="search"
                    placeholder={t("Filter menus by name or ID...", "메뉴 이름 또는 ID 검색...")}
                    value={menuQuery}
                    onInput={(e) => setMenuQuery(e.currentTarget.value)}
                  />
                  <label class="stencil-check">
                    <input
                      type="checkbox"
                      checked={showSelectedOnly}
                      onChange={(e) => setShowSelectedOnly(e.currentTarget.checked)}
                    />
                    <span>{t("Show enabled menus only", "활성화된 메뉴만 보기")}</span>
                  </label>
                </div>

                <div class="stencil-domain-list">
                  {[...groupedPanels.entries()].map(([group, panels]) => {
                    const needle = menuQuery.trim().toLowerCase();
                    const visibleGroupPanels = panels.filter((p) => {
                      if (showSelectedOnly && !liveBlueprint.effectivePanels.includes(p.id)) {
                        return false;
                      }
                      if (!needle) return true;
                      return (
                        p.id.toLowerCase().includes(needle) ||
                        p.label.toLowerCase().includes(needle) ||
                        p.label_ko.toLowerCase().includes(needle)
                      );
                    });
                    if (visibleGroupPanels.length === 0) return null;
                    const enabledInGroup = panels.filter((p) =>
                      liveBlueprint.effectivePanels.includes(p.id),
                    ).length;

                    return (
                      <details key={group} class="stencil-domain-group" open={Boolean(needle)}>
                        <summary class="stencil-domain-summary">
                          <span>
                            <strong>
                              {locale === "ko"
                                ? (GROUP_LABELS[group]?.ko ?? group)
                                : (GROUP_LABELS[group]?.en ?? group)}
                            </strong>
                            <span class="stencil-pill count-pill">
                              {enabledInGroup} / {panels.length} {t("enabled", "활성")}
                            </span>
                          </span>
                          <span class="actions" onClick={(e) => e.stopPropagation()}>
                            <button
                              type="button"
                              onClick={() => toggleGroupPanels(panels, true)}
                            >
                              {t("All", "전체 선택")}
                            </button>
                            <button
                              type="button"
                              onClick={() => toggleGroupPanels(panels, false)}
                            >
                              {t("Min", "최소화")}
                            </button>
                          </span>
                        </summary>
                        <div class="stencil-panel-grid">
                          {visibleGroupPanels.map((panel) => {
                            const checked = liveBlueprint.effectivePanels.includes(panel.id);
                            return (
                              <label
                                key={panel.id}
                                class={`stencil-axis-card compact ${checked ? "is-on" : ""}`}
                              >
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  disabled={panel.locked}
                                  onChange={() =>
                                    toggleItem(
                                      selectedPanels,
                                      panel.id,
                                      catalog.locked_panels,
                                      setSelectedPanels,
                                    )
                                  }
                                />
                                <div class="stencil-axis-body">
                                  <div class="stencil-axis-head">
                                    <strong>
                                      {locale === "ko" ? panel.label_ko : panel.label}
                                    </strong>
                                    {panel.locked && (
                                      <span class="stencil-pill locked">
                                        {t("Locked", "필수")}
                                      </span>
                                    )}
                                  </div>
                                  <div class="stencil-axis-meta">
                                    <code>{panel.id}</code>
                                    <code>{panel.path}</code>
                                    {panel.required_workloads.length > 0 && (
                                      <span class="stencil-agents">
                                        + {panel.required_workloads.join(", ")}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </label>
                            );
                          })}
                        </div>
                      </details>
                    );
                  })}
                </div>
              </details>

              <div class="actions" style="margin-top: 20px;">
                <button type="submit" class="primary" disabled={composing || !validInputs}>
                  {composing
                    ? t("Validating & composing Stencil...", "Stencil 검증 및 구성 중...")
                    : t("Validate & compose custom build", "커스텀 빌드 구성 검증 및 생성")}
                </button>
              </div>
            </form>

            <aside class="stencil-inspector" aria-label={t("Live Apollo Blueprint", "실시간 Apollo 블루프린트")}>
              <div class="inspector-card">
                <p class="eyebrow">{t("Live Apollo Blueprint & Diff", "실시간 Apollo 블루프린트 및 비교")}</p>
                <h3>{locale === "ko" ? titleKo : title}</h3>
                <div class="inspector-metrics">
                  <div>
                    <span>{t("Containers", "컨테이너")}</span>
                    <strong>
                      {liveBlueprint.effectiveWorkloads.length} / {catalog.workloads.length}
                    </strong>
                  </div>
                  <div>
                    <span>{t("Console Menus", "Console 메뉴")}</span>
                    <strong>
                      {liveBlueprint.effectivePanels.length} / {catalog.panels.length}
                    </strong>
                  </div>
                  <div>
                    <span>{t("ClamAV Sidecar", "ClamAV 사이드카")}</span>
                    <strong>
                      {liveBlueprint.includesClamav
                        ? t("Included", "포함됨")
                        : t("Omitted (-2Gi)", "제외됨 (-2Gi)")}
                    </strong>
                  </div>
                  <div>
                    <span>{t("Azure RBAC", "Azure 권한")}</span>
                    <strong>
                      {liveBlueprint.includesExecutor
                        ? t("Governed Exec", "승인 기반 실행")
                        : t("100% Read-Only", "100% 읽기 전용")}
                    </strong>
                  </div>
                </div>

                <div class="actions">
                  <button
                    type="button"
                    class="primary"
                    disabled={composing || mutationsDisabled || !validInputs}
                    onClick={() => void runCompose(undefined, true, true)}
                  >
                    {composing
                      ? t("Creating...", "생성 중...")
                      : t(
                          `1-Click Compose & Register Release ${releaseVersion.trim()}`,
                          `원클릭으로 릴리스 ${releaseVersion.trim()} 즉시 생성·등록`,
                        )}
                  </button>
                  <button
                    type="button"
                    disabled={composing || !validInputs}
                    onClick={() => void runCompose(undefined, false, false)}
                  >
                    {t("Preview manifest only", "매니페스트만 미리보기")}
                  </button>
                </div>

                <details class="release-disclosure" style="margin-top: 8px;">
                  <summary>
                    {t("Inspect topology diff, labels & RBAC", "토폴로지 비교·레이블·권한 상세 보기")}
                  </summary>
                  <h4>{t("Apollo Topology Diff (vs Full)", "Full 에디션 대비 토폴로지 비교 (Diff)")}</h4>
                  <ul class="apollo-diff-list">
                    {liveBlueprint.effectiveWorkloads.map((w) => (
                      <li key={w} class="diff-keep">
                        <span class="diff-sign">+</span>
                        <code>{w}</code>
                        <small>{t("active", "포함")}</small>
                      </li>
                    ))}
                    {liveBlueprint.omittedWorkloads.map((w) => (
                      <li key={w} class="diff-drop">
                        <span class="diff-sign">-</span>
                        <code>{w}</code>
                        <small>{t("omitted", "제외됨")}</small>
                      </li>
                    ))}
                    {!liveBlueprint.includesClamav && (
                      <li class="diff-drop">
                        <span class="diff-sign">-</span>
                        <code>clamav (sidecar)</code>
                        <small>{t("omitted", "제외됨")}</small>
                      </li>
                    )}
                  </ul>

                  <h4>{t("Apollo Release Labels", "Apollo 릴리스 레이블 (자동 부여)")}</h4>
                  <div class="preset-metrics">
                    {liveBlueprint.releaseLabels.map((lbl) => (
                      <code key={lbl} class="stencil-chip">{lbl}</code>
                    ))}
                  </div>

                  <h4>{t("Required Azure Roles", "필요한 Azure RBAC 역할")}</h4>
                  <p class="inspector-roles">{liveBlueprint.requiredAzureRoles.join(" · ")}</p>

                  <h4>{t("Inactive Menu Feature Flag Gate", "비활성 메뉴 Feature Flag 차단 정책")}</h4>
                  <div class="preset-metrics">
                    <code class="stencil-chip">
                      {t(
                        `fail-closed · ${liveBlueprint.disabledPanels.length} menus blocked`,
                        `fail-closed · 비활성 메뉴 ${liveBlueprint.disabledPanels.length}개 차단`,
                      )}
                    </code>
                    <code class="stencil-chip">
                      {t(
                        `${liveBlueprint.omittedLoops.length} backend loops disabled`,
                        `백엔드 루프 ${liveBlueprint.omittedLoops.length}개 비활성화`,
                      )}
                    </code>
                  </div>
                </details>
              </div>
            </aside>
          </div>

          {composed && (
            <section aria-labelledby="stencil-result-title" class="release-next">
              <h2 id="stencil-result-title">
                {t("Composed Stencil & Resource Footprint", "생성된 Stencil 및 리소스 절감 요약")}
              </h2>
              <div class="facts">
                <div>
                  <span>{t("Active workloads", "활성 워크로드")}</span>
                  <strong>
                    {composed.footprint.workload_count} / {composed.footprint.total_workloads}
                  </strong>
                </div>
                <div>
                  <span>{t("ClamAV & Doc workers", "ClamAV 및 문서 워커")}</span>
                  <strong>
                    {composed.footprint.includes_clamav_sidecar
                      ? t("Included", "포함됨")
                      : t("Omitted (Lightweight)", "제외됨 (경량화)")}
                  </strong>
                </div>
                <div>
                  <span>{t("Enabled Console menus", "활성 Console 메뉴")}</span>
                  <strong>
                    {composed.footprint.enabled_panel_count} / {composed.footprint.total_panel_count}
                  </strong>
                </div>
                <div>
                  <span>{t("Azure RBAC posture", "Azure RBAC 권한 수준")}</span>
                  <strong>{composed.footprint.azure_rbac_posture}</strong>
                </div>
              </div>
              <div class="actions" style="margin-top: 16px;">
                {onQuickCreateRelease && (
                  <button
                    type="button"
                    class="primary"
                    disabled={composing || mutationsDisabled}
                    onClick={() =>
                      void dispatchBuilderRelease({
                        id: releaseVersion.trim(),
                        label: `${composed.stencil.stencil_id} (${composed.footprint.enabled_panel_count} menus, ${composed.footprint.workload_count} workloads)`,
                        manifest: JSON.stringify(composed.release_manifest, null, 2),
                      }, releaseMutationsDisabled, onPrepareRelease, onQuickCreateRelease)
                    }
                  >
                    {t(
                      `1-Click Create Release ${releaseVersion.trim()} Now`,
                      `원클릭으로 릴리스 ${releaseVersion.trim()} 즉시 생성`,
                    )}
                  </button>
                )}
                <button
                  type="button"
                  class={onQuickCreateRelease ? "" : "primary"}
                  disabled={composing || mutationsDisabled}
                  onClick={() =>
                    void dispatchBuilderRelease({
                      id: releaseVersion.trim(),
                      label: `${composed.stencil.stencil_id} (${composed.footprint.enabled_panel_count} menus, ${composed.footprint.workload_count} workloads)`,
                      manifest: JSON.stringify(composed.release_manifest, null, 2),
                    }, releaseMutationsDisabled, onPrepareRelease)
                  }
                >
                  {t(
                    `Prepare Release ${releaseVersion.trim()} registration with this Stencil`,
                    `이 Stencil로 릴리스 ${releaseVersion.trim()} 등록 준비`,
                  )}
                </button>
              </div>
              <details class="release-disclosure">
                <summary>{t("Inspect generated Stencil definition & Release v2 manifest", "생성된 Stencil 상세 메타데이터 및 Release v2 매니페스트 보기")}</summary>
                <dl>
                  <dt>{t("Stencil digest", "Stencil 다이제스트")}</dt>
                  <dd><code class="digest">{composed.footprint.stencil_digest}</code></dd>
                  <dt>{t("Apollo Release labels", "Apollo 릴리스 레이블")}</dt>
                  <dd>{(composed.footprint.release_labels ?? []).join(", ")}</dd>
                  <dt>{t("Omitted workloads", "제외된 워크로드")}</dt>
                  <dd>{composed.footprint.omitted_workloads.join(", ") || t("None", "없음")}</dd>
                  <dt>{t("Required Azure roles", "필요한 Azure 역할")}</dt>
                  <dd>{composed.footprint.required_azure_roles.join(", ")}</dd>
                  <dt>{t("Console custom build command", "Console 커스텀 빌드 명령")}</dt>
                  <dd><code class="digest">{composed.footprint.console_build_command}</code></dd>
                  <dt>{t("Inactive menu feature flag gate", "비활성 메뉴 Feature Flag 게이트")}</dt>
                  <dd>
                    <code class="digest">
                      {composed.footprint.feature_flags
                        ? `${composed.footprint.feature_flags.enforcement_mode} (FDAI_STENCIL_ENFORCE_INACTIVE_MENUS=1 · ${composed.footprint.feature_flags.disabled_panel_ids.length} menus & ${composed.footprint.feature_flags.disabled_loops.length} loops blocked)`
                        : "fail-closed"}
                    </code>
                  </dd>
                </dl>
                <pre>{JSON.stringify(composed, null, 2)}</pre>
              </details>
            </section>
          )}
        </>
      )}
    </div>
  );
}
