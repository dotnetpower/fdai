import type { ComponentChildren } from "preact";
import { useMemo, useRef, useState } from "preact/hooks";
import {
  actionsFor, activeCapabilityRecalls, artifacts, blockedReleaseCapabilities,
  evaluateApolloPromotionReadiness, extractReleaseStencil, nextPromotionTransition, releaseTitle, safeParseReleaseManifest, schemaCompatibility,
  type Action, type Catalog, type Release,
} from "./api";
import { ReleaseStageLineage } from "./release-lineage";
import type { LineageNode } from "./release-lineage.model";

const stages = ["DEV", "RELEASE_CANDIDATE", "RELEASE"] as const;

export function recordedStage(release: Release): string | null {
  return stages.slice().reverse().find((stage) => release.channels.includes(stage)) ?? null;
}

export function nextReleaseStep(release: Release, catalog: Catalog): "recall" | "renew" | "publish" | "review" {
  if (release.state === "recalled") return "recall";
  if (release.state === "draft") return "publish";
  if (catalog.expired) return "renew";
  return "review";
}

export function ReleaseWorkspace({ release, catalog, locale: externalLocale, onLocaleChange, act, onQuickPromote, disabled, activity, edition = false, backHref }: {
  release: Release; catalog: Catalog; locale?: "en" | "ko"; onLocaleChange?: (next: "en" | "ko") => void;
  act: (action: Action, release: Release) => void;
  onQuickPromote?: ((release: Release) => Promise<void> | void) | undefined;
  disabled: boolean; activity: ComponentChildren; edition?: boolean; backHref?: string | undefined;
}) {
  const [internalLocale, setInternalLocale] = useState<"en" | "ko">(navigator.language.startsWith("ko") ? "ko" : "en");
  const locale = externalLocale ?? internalLocale;
  const setLocale = (next: "en" | "ko") => {
    setInternalLocale(next);
    onLocaleChange?.(next);
  };
  const t = (en: string, ko: string) => locale === "ko" ? ko : en;
  const evidence = useRef<HTMLDetailsElement>(null);
  const stencilDetails = useRef<HTMLDetailsElement>(null);
  const technicalDetails = useRef<HTMLDetailsElement>(null);
  const history = useRef<HTMLDetailsElement>(null);
  const [copiedDigest, setCopiedDigest] = useState(false);
  const [copyError, setCopyError] = useState("");
  const manifest = useMemo(() => safeParseReleaseManifest(release.manifest), [release.manifest]);
  const stencil = useMemo(() => extractReleaseStencil(manifest), [manifest]);
  const declaredArtifacts = useMemo(() => artifacts(manifest), [manifest]);
  const step = nextReleaseStep(release, catalog);
  const stage = recordedStage(release);
  const transition = nextPromotionTransition(release);
  const activeCapRecalls = useMemo(() => activeCapabilityRecalls(catalog.events), [catalog.events]);
  const blockedCaps = useMemo(
    () => blockedReleaseCapabilities(manifest, catalog.events),
    [manifest, catalog.events],
  );
  const apolloReadiness = useMemo(
    () =>
      transition
        ? evaluateApolloPromotionReadiness({
            release,
            manifest,
            events: catalog.events,
            sourceChannel: transition.sourceChannel,
            targetChannel: transition.targetChannel,
          })
        : null,
    [release, manifest, catalog.events, transition],
  );
  const status = release.state === "recalled" ? t("Recalled", "회수됨")
    : release.state === "draft" ? t("Draft / unsigned", "초안 / 서명 없음")
    : release.channels.includes("RELEASE") ? t("In RELEASE channel", "RELEASE 채널 소속")
    : release.channels.includes("RELEASE_CANDIDATE") ? t("Staged in RC", "RC 카나리 승격 완료")
    : t("Development published", "개발용 발행 완료");
  function reveal(target: HTMLDetailsElement | null) {
    if (!target) return;
    target.open = true;
    target.querySelector("summary")?.focus();
    target.scrollIntoView({ block: "start" });
  }
  function inspectStage(node: LineageNode) {
    if (node.id === "initialize-stencil" && !stencil) {
      location.hash = "/edition/new";
    } else if (node.id === "initialize-stencil") {
      reveal(stencilDetails.current);
    } else if (node.id === "clone-codebase" || node.id.startsWith("workload-")) {
      reveal(technicalDetails.current);
    } else {
      reveal(evidence.current);
    }
  }
  return <div class={`release-workspace${edition ? " rh-edition-workspace" : ""}`} lang={locale}>
    <div class="rh-argo-app-header">
      <div class="rh-argo-app-title">
        <a href={edition ? backHref ?? "#/edition" : "#/releases"} class="back">{edition ? t("<- Edition", "← Edition") : t("<- Releases", "← 목록")}</a>
        <h1>{releaseTitle(release, manifest)}</h1>
        <span class={`status ${release.state}`}>{status}</span>
        <span class="stencil-chip">{stage ?? "DRAFT"}</span>
        <span class="stencil-chip">{t(`Rev ${catalog.revision}`, `리비전 ${catalog.revision}`)}</span>
        {stencil && (
          <span class="stencil-pill locked">
            {stencil.stencil_id} · {stencil.enabled_workloads.length}W/{stencil.enabled_panel_ids.length}M
          </span>
        )}
        <span class="stencil-chip">
          {release.signature_status === "development-key-verified"
            ? t("ed25519 verified", "ed25519 검증됨")
            : release.signature_status === "unsigned"
              ? t("Unsigned", "미서명")
              : t(`Signature: ${release.signature_status}`, `서명 상태: ${release.signature_status}`)}
        </span>
      </div>
      <div class="actions" style="margin-top: 0;">
        {!externalLocale && (
          <label style="margin: 0; display: inline-flex; align-items: center; gap: 6px;">
            <span>{t("Workspace language", "작업 영역 언어")}</span>
            <select value={locale} onChange={(event) => setLocale(event.currentTarget.value as "en" | "ko")}>
              <option value="en">English</option><option value="ko">한국어</option>
            </select>
          </label>
        )}
        {step === "renew" ? (
          <a class="next-link" href="#/trust">{t("Review catalog freshness", "카탈로그 유효 기간 검토")}</a>
        ) : (
          <>
            <button class="chip-btn" disabled={disabled && step === "publish"} onClick={() => {
              if (step === "publish") act("publish", release);
              else if (step === "review") reveal(evidence.current);
              else reveal(history.current);
            }}>{step === "publish" ? t("Review DEV publication", "DEV 발행 검토")
              : step === "review" ? t("Review promotion evidence", "승격 근거 검토")
              : t("Review recall activity", "회수 활동 검토")}</button>
            {step === "review" && transition && blockedCaps.length === 0 && !catalog.expired && (
              <button type="button" class="chip-btn" disabled={disabled} onClick={() => act("promote", release)}>
                {t(`Quick advance to ${transition.targetChannel}`, `${transition.sourceChannel} -> ${transition.targetChannel} 옵션`)}
              </button>
            )}
          </>
        )}
      </div>
    </div>
    <section class="rh-workspace-pipeline-section" aria-labelledby="release-stage-title">
      <div class="rh-workspace-pipeline-head">
        <h2 id="release-stage-title">{t("Release & Workload Topology", "릴리스 승격 및 워크로드 토폴로지")}</h2>
        <div class="stage-pills">
          {stages.map((name) => (
            <span key={name} class={`stage-pill ${release.channels.includes(name) ? (release.state === "recalled" ? "recalled" : "done") : ""}`}>
              {release.channels.includes(name) ? `✓ ${name}` : name}
            </span>
          ))}
        </div>
      </div>
      <ReleaseStageLineage release={release} catalog={catalog} locale={locale} disabled={disabled} preserveNodeSize={edition} edition={edition} onInspectNode={edition ? inspectStage : undefined} onAct={act} onQuickPromote={onQuickPromote} />
    </section>
    {stencil && (
      <details ref={stencilDetails} class="release-disclosure">
        <summary>
          {t(
            `Stencil Blueprint & Console Menus (${stencil.stencil_id} · ${stencil.enabled_workloads.length} workloads · ${stencil.enabled_panel_ids.length} menus)`,
            `Stencil 블루프린트 및 활성 메뉴 (${stencil.stencil_id} · 워크로드 ${stencil.enabled_workloads.length}개 · 메뉴 ${stencil.enabled_panel_ids.length}개)`,
          )}
        </summary>
        <div class="preset-metrics" style="margin: 8px 0 12px;">
          <span class="stencil-pill locked">{stencil.stencil_id}</span>
          <span class="stencil-chip">{t("Profile:", "프로파일:")} {stencil.topology_profile}</span>
          <span class="stencil-chip">{t("RBAC:", "권한:")} {stencil.azure_rbac_posture}</span>
          <span class="stencil-chip">
            {manifest.schema_expand
              ? t("Upgrade: Schema expand migration", "업그레이드: 스키마 확장 마이그레이션")
              : t("Upgrade: Zero-downtime rolling", "업그레이드: 무중단 롤링")}
          </span>
        </div>
        <dl>
          <dt>{t("Stencil digest", "Stencil 다이제스트")}</dt>
          <dd>
            <code class="digest">{stencil.stencil_digest}</code>
            <button
              type="button"
              class="chip-btn"
              onClick={async () => {
                setCopyError("");
                try {
                  if (!navigator.clipboard) throw new Error(t("Clipboard is unavailable.", "클립보드를 사용할 수 없습니다."));
                  await navigator.clipboard.writeText(stencil.stencil_digest);
                  setCopiedDigest(true);
                  setTimeout(() => setCopiedDigest(false), 2000);
                } catch (failure) {
                  setCopiedDigest(false);
                  setCopyError(failure instanceof Error ? failure.message : t("Could not copy digest.", "다이제스트를 복사하지 못했습니다."));
                }
              }}
            >
              {copiedDigest ? t("Copied!", "복사됨!") : t("Copy digest", "다이제스트 복사")}
            </button>
            {copyError && <span role="alert" class="error">{copyError}</span>}
          </dd>
          <dt>{t("Included workloads (+)", "포함된 컨테이너 (+)")}</dt>
          <dd>{stencil.enabled_workloads.join(", ")}</dd>
          {stencil.omitted_workloads && stencil.omitted_workloads.length > 0 && (
            <>
              <dt>{t("Omitted workloads (-)", "제외된 컨테이너 (-)")}</dt>
              <dd>{stencil.omitted_workloads.join(", ")}</dd>
            </>
          )}
          {stencil.required_azure_roles && stencil.required_azure_roles.length > 0 && (
            <>
              <dt>{t("Required Azure roles", "필요한 Azure 역할")}</dt>
              <dd>{stencil.required_azure_roles.join(" · ")}</dd>
            </>
          )}
          {stencil.release_labels && stencil.release_labels.length > 0 && (
            <>
              <dt>{t("Apollo Release labels", "Apollo 릴리스 레이블")}</dt>
              <dd>
                <div class="preset-metrics">
                  {stencil.release_labels.map((lbl) => (
                    <code key={lbl} class="stencil-chip">{lbl}</code>
                  ))}
                </div>
              </dd>
            </>
          )}
          <dt>{t("Inactive menu feature-flag gate", "비활성 메뉴 Feature Flag 게이트")}</dt>
          <dd>
            <code class="digest">
              {stencil.feature_flags
                ? `${stencil.feature_flags.enforcement_mode}${stencil.feature_flags.feature_flags_digest ? ` · ${stencil.feature_flags.feature_flags_digest}` : ""}`
                : "fail-closed"}
            </code>
          </dd>
        </dl>
        <p><strong>{t(`Enabled Console menus (${stencil.enabled_panel_ids.length})`, `포함된 Console 메뉴 목록 (${stencil.enabled_panel_ids.length}개)`)}</strong></p>
        <div class="preset-metrics">
          {stencil.enabled_panel_ids.map((panelId) => (
            <code key={panelId} class="stencil-chip">{panelId}</code>
          ))}
        </div>
      </details>
    )}
    <details ref={evidence} class="release-disclosure">
      <summary>{t("Promotion evidence and blockers", "승격 근거 및 차단 이유")}</summary>
      <p>{t("The existing server-side promotion evaluator owns source membership, labels, canary health, soak, timeout and recall checks. This catalog API does not expose its run results. No passed gate is inferred here.", "기존 서버 측 승격 검증기가 원본 채널 소속, 레이블, 카나리 상태, 관찰 시간, 제한 시간 및 회수를 검사합니다. 현재 카탈로그 API에는 실행 결과가 없습니다. 이 화면은 검사 통과를 추정하지 않습니다.")}</p>
      <dl>
        <dt>{t("Next gated stage", "다음 승격 단계")}</dt><dd>{transition
          ? `${transition.sourceChannel} -> ${transition.targetChannel}`
          : release.channels.includes("RELEASE")
          ? t("Already in RELEASE", "이미 RELEASE 채널에 소속됨")
          : t("Not eligible for stage promotion", "단계 승격 대상이 아님")}</dd>
        <dt>{t("Gate run results", "검사 실행 결과")}</dt><dd>{t("Unavailable in this workspace", "이 작업 영역에서 제공되지 않음")}</dd>
        <dt>{t("Build / publish job", "빌드 / 발행 작업")}</dt><dd>{t("No durable job status is provided by this API", "이 API는 영속적인 작업 상태를 제공하지 않음")}</dd>
        <dt>{t("Release recall", "릴리스 회수")}</dt><dd>{release.recalled_at ?? t("No release recall recorded; capability recalls are checked by the server", "릴리스 회수 기록 없음. 기능 회수는 서버에서 검사함")}</dd>
        <dt>{t("Active capability recalls", "활성 기능 회수")}</dt><dd>{blockedCaps.length > 0
          ? t(`Blocked by recalled capabilities: ${blockedCaps.join(", ")}`, `회수된 기능으로 인해 차단됨: ${blockedCaps.join(", ")}`)
          : activeCapRecalls.length > 0
          ? t(`Catalog has ${activeCapRecalls.length} active capability recall(s) (${activeCapRecalls.join(", ")}); none declared by this release`, `카탈로그에 활성 기능 회수 ${activeCapRecalls.length}건(${activeCapRecalls.join(", ")})이 있으나 이 릴리스에는 해당하지 않음`)
          : t("No active capability recalls in catalog", "카탈로그에 활성 기능 회수 없음")}</dd>
      </dl>
      {apolloReadiness && (
        <div style="margin: 16px 0;">
          <h3>{t("Apollo Promotion Gate Pre-check", "Apollo 승격 게이트 사전 검증")}</h3>
          <ul class="apollo-diff-list">
            {apolloReadiness.gates.map((g) => (
              <li key={g.id} class={g.id === "stencil-labels" || g.id === "soak-window"
                ? "" : g.passed ? "diff-keep" : "diff-drop"}>
                <span class="diff-sign">{g.id === "stencil-labels" || g.id === "soak-window"
                  ? "-" : g.passed ? "✓" : "✕"}</span>
                <strong>{locale === "ko" ? g.label_ko : g.label}</strong>
                <small>{g.id === "stencil-labels" || g.id === "soak-window"
                  ? t("Independent gate observations unavailable", "독립적인 게이트 관찰 근거가 제공되지 않음")
                  : locale === "ko" ? g.detail_ko : g.detail}</small>
              </li>
            ))}
          </ul>
        </div>
      )}
      {transition && blockedCaps.length === 0 && !catalog.expired && (
        <div class="actions">
          <button type="button" class="primary" disabled={disabled} onClick={() => act("promote", release)}>
            {t(`Promote ${transition.sourceChannel} -> ${transition.targetChannel}`, `${transition.sourceChannel} -> ${transition.targetChannel} 승격`)}
          </button>
        </div>
      )}
      <p>{t("Use the supported promotion pipeline for gated advancement. Advanced channel curation below is a separate manual operation, not verified promotion.", "검사가 적용되는 승격에는 지원되는 승격 파이프라인을 사용하세요. 아래 고급 채널 편집은 별도의 수동 작업이며 검증된 승격이 아닙니다.")}</p>
    </details>
    <details ref={technicalDetails} class="release-disclosure">
      <summary>{t("Technical details and advanced operations", "기술 세부 정보 및 고급 작업")}</summary>
      <div class="actions">{actionsFor(release).filter((action) => action !== "publish").map((action) =>
        <button key={action} disabled={disabled} class={action === "recall" ? "danger" : ""} onClick={() => act(action, release)}>
          {action === "recall" ? t("Recall release", "릴리스 회수") : t("Manual channel curation", "수동 채널 편집")}
        </button>)}</div>
      <p>{t("Existing revision, reason and exact-target confirmations still apply. No automatic write is performed on reload or recovery.", "기존 개정 번호, 사유 및 정확한 대상 확인 절차가 유지됩니다. 새로 고침이나 복구 시 쓰기를 자동 실행하지 않습니다.")}</p>
      <dl>
        <dt>{t("Canonical manifest SHA-256", "정규 매니페스트 SHA-256")}</dt><dd><code class="digest">{release.digest}</code></dd>
        <dt>{t("Signed payload SHA-256", "서명된 페이로드 SHA-256")}</dt><dd><code class="digest">{release.signed_payload_sha256}</code></dd>
        <dt>{t("Source commit", "소스 커밋")}</dt><dd><code class="digest">{manifest.source_commit}</code></dd>
        <dt>{t("Platform", "플랫폼")}</dt><dd>{manifest.platform_tag}</dd>
        <dt>{t("Schema compatibility", "스키마 호환성")}</dt><dd lang={locale}>{schemaCompatibility(manifest, locale)}</dd>
        <dt>{t("Development key", "개발용 키")}</dt><dd><code class="digest">{catalog.key_id}</code></dd>
        <dt>{t("Published", "발행 시각")}</dt><dd>{release.published_at ?? t("Not published", "발행되지 않음")}</dd>
        <dt>{t("All channels", "모든 채널")}</dt><dd>{release.channels.join(" / ") || t("None", "없음")}</dd>
      </dl>
      <h2>{t("Declared artifacts & OCI v2 registry manifests", "선언된 컨테이너 아티팩트 및 OCI v2 레지스트리 매니페스트")}</h2>
      <p>{t("Bound component image digests. Click any OCI v2 manifest link below to verify its published registry manifest and Docker-Content-Digest header.", "바인딩된 컴포넌트 이미지 다이제스트입니다. 아래 OCI v2 매니페스트 링크를 클릭하면 레지스트리에 발행된 실제 매니페스트와 Docker-Content-Digest 헤더를 검증할 수 있습니다.")}</p>
      <div class="artifact-list">{declaredArtifacts.map((artifact) => <article key={artifact.component}>
        <div class="preset-card-head">
          <h3>{artifact.component}</h3>
          <a class="chip-btn" href={`/v2/fdai/${encodeURIComponent(artifact.component)}/manifests/${encodeURIComponent(artifact.digest)}`} target="_blank" rel="noreferrer">
            {t("OCI v2 manifest ->", "OCI v2 매니페스트 ->")}
          </a>
        </div>
        <code class="digest">{artifact.digest}</code>
        <details><summary>{t("SBOM digest", "SBOM 다이제스트")}</summary><code class="digest" lang="en">{artifact.sbom}</code></details>
      </article>)}</div>
      <details><summary>{t("Exact manifest and detached signature", "정확한 매니페스트 및 분리된 서명")}</summary>
        <pre>{release.manifest}</pre><code class="digest">{release.signature || t("No signature", "서명 없음")}</code>
      </details>
    </details>
    <details ref={history} class="release-disclosure" tabIndex={-1}>
      <summary>{t("Release activity", "릴리스 활동 이력")}</summary>
      <div lang="en">{activity}</div>
    </details>
  </div>;
}
