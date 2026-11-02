import { useEffect, useMemo, useState } from "preact/hooks";
import {
  requestStencilCatalog,
  requestStencilCompose,
  type RuntimeAxisDescriptorRecord,
  type StencilCatalogResponse,
  type StencilComposeResult,
  type StencilDefinitionRecord,
  type StencilPanelDescriptor,
} from "./api";

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
  return (
    STENCIL_ID_RE.test(input.stencilId.trim()) &&
    input.releaseVersion.trim().length <= 64 &&
    SEMVER_RE.test(input.releaseVersion.trim()) &&
    COMMIT_SHA_RE.test(input.sourceCommit.trim())
  );
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
  readonly effectiveWorkloads: string[];
  readonly omittedWorkloads: string[];
  readonly effectiveLoops: string[];
  readonly omittedLoops: string[];
  readonly effectiveJobs: string[];
  readonly omittedJobs: string[];
  readonly effectivePanels: string[];
  readonly omittedPanelCount: number;
  readonly includesClamav: boolean;
  readonly includesExecutor: boolean;
  readonly rbacPosture: "read-only-observation" | "governed-execution";
  readonly requiredAzureRoles: string[];
  readonly releaseLabels: string[];
  readonly workloadReasons: Readonly<Record<string, string[]>>;
  readonly loopReasons: Readonly<Record<string, string[]>>;
  readonly consoleBuildCommand: string;
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
    autoResolve: boolean;
  },
): LiveApolloBlueprint {
  const panelSet = new Set([...options.selectedPanels, ...catalog.locked_panels]);
  const workloadSet = new Set([...options.selectedWorkloads, ...catalog.locked_workloads]);
  const loopSet = new Set([...options.selectedLoops, ...catalog.locked_loops]);
  const jobSet = new Set([...options.selectedJobs, ...catalog.locked_scheduled_jobs]);

  const workloadReasons: Record<string, string[]> = {};
  const loopReasons: Record<string, string[]> = {};
  for (const w of catalog.locked_workloads) workloadReasons[w] = ["locked-core"];
  for (const l of catalog.locked_loops) loopReasons[l] = ["locked-core"];

  const panelById = new Map(catalog.panels.map((p) => [p.id, p]));
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
  }

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
      workloadSet.add("isolated-executor");
      loopSet.add("remediation-execution");
    }
    if (jobSet.has("cost-collector") || loopSet.has("cost-governance")) {
      loopSet.add("cost-governance");
      jobSet.add("cost-collector");
    }
  }

  const effectiveWorkloads = [...workloadSet].sort();
  const omittedWorkloads = catalog.workloads.filter((w) => !workloadSet.has(w)).sort();
  const effectiveLoops = [...loopSet].sort();
  const omittedLoops = catalog.loops.filter((l) => !loopSet.has(l)).sort();
  const effectiveJobs = [...jobSet].sort();
  const omittedJobs = catalog.scheduled_jobs.filter((j) => !jobSet.has(j)).sort();
  const effectivePanels = [...panelSet].sort();
  const omittedPanelCount = Math.max(0, catalog.panels.length - effectivePanels.length);

  const includesClamav = workloadSet.has("document-ingestion-api");
  const includesExecutor = workloadSet.has("isolated-executor");
  const rbacPosture = includesExecutor ? "governed-execution" : "read-only-observation";
  const requiredAzureRoles = ["Reader", "Monitoring Reader", "Log Analytics Reader"];
  if (loopSet.has("cost-governance")) requiredAzureRoles.push("Cost Management Reader");
  if (includesExecutor) requiredAzureRoles.push("Scoped Executor Action Role");

  const cleanId = options.stencilId.trim() || "custom-stencil";
  const releaseLabels = [
    `stencil:${cleanId}`,
    `profile:${options.topologyProfile}`,
    `rbac:${rbacPosture}`,
    `clamav:${includesClamav ? "included" : "omitted"}`,
    `executor:${includesExecutor ? "included" : "omitted"}`,
    `workloads:${effectiveWorkloads.length}`,
    `menus:${effectivePanels.length}`,
  ];

  return {
    effectiveWorkloads,
    omittedWorkloads,
    effectiveLoops,
    omittedLoops,
    effectiveJobs,
    omittedJobs,
    effectivePanels,
    omittedPanelCount,
    includesClamav,
    includesExecutor,
    rbacPosture,
    requiredAzureRoles,
    releaseLabels,
    workloadReasons,
    loopReasons,
    consoleBuildCommand: `FDAI_STENCIL_ENABLED_PANELS='${effectivePanels.join(",")}' npm --prefix console run build`,
  };
}

export function StencilBuilder({
  onPrepareRelease,
}: {
  onPrepareRelease: (draft: { id: string; label: string; manifest: string }) => void;
}) {
  const [locale, setLocale] = useState(navigator.language.startsWith("ko") ? "ko" : "en");
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
  const [releaseVersion, setReleaseVersion] = useState("1.7.0");
  const [sourceCommit, setSourceCommit] = useState("a".repeat(40));
  const [composed, setComposed] = useState<StencilComposeResult | null>(null);
  const [menuQuery, setMenuQuery] = useState("");
  const [showSelectedOnly, setShowSelectedOnly] = useState(false);

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
  ) {
    const linkedMenus = reasons.filter((r) => r.startsWith("menu:")).map((r) => r.slice(5));
    return (
      <label key={id} class={`stencil-axis-card ${checked ? "is-on" : ""}`}>
        <input type="checkbox" checked={checked} disabled={locked} onChange={onToggle} />
        <div class="stencil-axis-body">
          <div class="stencil-axis-head">
            <strong>{meta ? (locale === "ko" ? meta.label_ko : meta.label) : id}</strong>
            <span class="stencil-badges">
              {locked && (
                <span class="stencil-pill locked">{t("Locked core", "필수 코어")}</span>
              )}
              {!locked && linkedMenus.length > 0 && (
                <span
                  class="stencil-pill linked"
                  title={`Required by: ${linkedMenus.join(", ")}`}
                >
                  {t(`Linked: ${linkedMenus.slice(0, 2).join(", ")}`, `연동됨: ${linkedMenus.slice(0, 2).join(", ")}`)}
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
    if (list.includes(value)) {
      setter(list.filter((item) => item !== value));
    } else {
      setter([...list, value].sort());
    }
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

  async function runCompose(event?: SubmitEvent) {
    event?.preventDefault();
    if (composing || !validInputs) return;
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
      applyPreset(result.stencil);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Stencil composition failed.");
    } finally {
      setComposing(false);
    }
  }

  return (
    <div class="stencil-builder" lang={locale}>
      <div class="workspace-bar">
        <span>{t("Custom Stencil & Menu Builder", "맞춤형 Stencil 및 메뉴 빌더")}</span>
        <label>
          {t("Builder language", "빌더 언어")}{" "}
          <select value={locale} onChange={(e) => setLocale(e.currentTarget.value)}>
            <option value="en">English</option>
            <option value="ko">한국어</option>
          </select>
        </label>
      </div>

      <div class="page-head">
        <div>
          <p class="eyebrow">{t("Build-time feature & menu composition", "빌드 타임 기능 및 메뉴 구성")}</p>
          <h1>{t("Stencils & Custom Build", "Stencil 및 커스텀 메뉴 빌드")}</h1>
          <p>
            {t(
              "Select a lightweight resource preset or choose the exact Console menus, agent loops, and service workloads to include in your build.",
              "최소 리소스 경량 프리셋을 선택하거나, 빌드에 포함할 Console 메뉴·에이전트 루프·워크로드를 직접 지정하세요.",
            )}
          </p>
        </div>
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
                    <button
                      type="button"
                      class={isSelected ? "primary" : ""}
                      onClick={() => {
                        applyPreset(preset);
                        setComposed(null);
                      }}
                    >
                      {t(`Load ${preset.stencil_id}`, `${preset.stencil_id} 불러오기`)}
                    </button>
                  </article>
                );
              })}
            </div>
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
                    {t("Target Release version (SemVer)", "대상 릴리스 버전 (SemVer)")}
                    <input
                      required
                      value={releaseVersion}
                      onInput={(e) => {
                        setReleaseVersion(e.currentTarget.value);
                        setComposed(null);
                      }}
                    />
                  </label>
                  <label>
                    {t("Source commit SHA (40 hex)", "소스 커밋 SHA (40자 16진수)")}
                    <input
                      required
                      minLength={40}
                      maxLength={40}
                      value={sourceCommit}
                      onInput={(e) => {
                        setSourceCommit(e.currentTarget.value);
                        setComposed(null);
                      }}
                    />
                  </label>
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
              </section>

              <section aria-labelledby="stencil-loops-title">
                <h2 id="stencil-loops-title">
                  {t("3. Agent-driven loops & service workloads", "3. 에이전트 주도 루프 및 서비스 워크로드")}
                </h2>
                <p>
                  {t(
                    "The 15-agent pantheon runs in-process inside core-control-plane. Resource change detection, anomaly detection, notifications, and Saga audit remain locked on.",
                    "15-에이전트 판테온은 core-control-plane 단일 컨테이너 내부에서 동작합니다. 리소스 변경 감지, 장애 감지, 알림 발송, 해시 체인 감사는 안전 코어로 항상 활성화됩니다.",
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
                </div>
              </section>

              <section aria-labelledby="stencil-menus-title">
                <h2 id="stencil-menus-title">
                  {t(
                    `4. Custom Console menus (${liveBlueprint.effectivePanels.length} / ${catalog.panels.length} enabled)`,
                    `4. 커스텀 Console 메뉴 선택 (${liveBlueprint.effectivePanels.length} / ${catalog.panels.length}개 활성화됨)`,
                  )}
                </h2>
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
                      <details key={group} class="stencil-domain-group" open>
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
              </section>

              <div class="actions">
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

                <div class="actions">
                  <button
                    type="button"
                    class="primary"
                    disabled={composing || !validInputs}
                    onClick={() => void runCompose()}
                  >
                    {composing
                      ? t("Validating...", "검증 중...")
                      : t("Validate & generate manifest", "구성 검증 및 매니페스트 생성")}
                  </button>
                </div>
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
              </dl>
              <div class="actions">
                <button
                  type="button"
                  class="primary"
                  onClick={() =>
                    onPrepareRelease({
                      id: releaseVersion.trim(),
                      label: `${composed.stencil.stencil_id} (${composed.footprint.enabled_panel_count} menus, ${composed.footprint.workload_count} workloads)`,
                      manifest: JSON.stringify(composed.release_manifest, null, 2),
                    })
                  }
                >
                  {t(
                    `Prepare Release ${releaseVersion.trim()} registration with this Stencil`,
                    `이 Stencil로 릴리스 ${releaseVersion.trim()} 등록 준비`,
                  )}
                </button>
              </div>
              <details class="release-disclosure">
                <summary>{t("Inspect generated Stencil definition & Release v2 manifest", "생성된 Stencil 정의서 및 Release v2 매니페스트 보기")}</summary>
                <pre>{JSON.stringify(composed, null, 2)}</pre>
              </details>
            </section>
          )}
        </>
      )}
    </div>
  );
}
