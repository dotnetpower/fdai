import type { ComponentChildren } from "preact";
import { useMemo, useRef, useState } from "preact/hooks";
import {
  actionsFor, activeCapabilityRecalls, artifacts, blockedReleaseCapabilities,
  nextPromotionTransition, parseReleaseManifest, releaseTitle, schemaCompatibility,
  type Action, type Catalog, type Release,
} from "./api";

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

export function ReleaseWorkspace({ release, catalog, act, disabled, activity }: {
  release: Release; catalog: Catalog; act: (action: Action, release: Release) => void;
  disabled: boolean; activity: ComponentChildren;
}) {
  const [locale, setLocale] = useState(navigator.language.startsWith("ko") ? "ko" : "en");
  const t = (en: string, ko: string) => locale === "ko" ? ko : en;
  const evidence = useRef<HTMLDetailsElement>(null);
  const history = useRef<HTMLElement>(null);
  const manifest = useMemo(() => parseReleaseManifest(release.manifest), [release.manifest]);
  const declaredArtifacts = useMemo(() => artifacts(manifest), [manifest]);
  const step = nextReleaseStep(release, catalog);
  const stage = recordedStage(release);
  const transition = nextPromotionTransition(release);
  const activeCapRecalls = useMemo(() => activeCapabilityRecalls(catalog.events), [catalog.events]);
  const blockedCaps = useMemo(
    () => blockedReleaseCapabilities(manifest, catalog.events),
    [manifest, catalog.events],
  );
  const status = release.state === "recalled" ? t("Recalled", "회수됨")
    : release.state === "draft" ? t("Draft / unsigned", "초안 / 서명 없음")
    : t("Development published", "개발용 발행 완료");
  function reviewEvidence() {
    if (evidence.current) {
      evidence.current.open = true;
      evidence.current.querySelector("summary")?.focus();
      evidence.current.scrollIntoView({ block: "start" });
    }
  }
  return <div class="release-workspace" lang={locale}>
    <div class="workspace-bar">
      <a href="#/releases" class="back">{t("All releases", "모든 릴리스")}</a>
      <label>{t("Workspace language", "작업 영역 언어")} <select value={locale} onChange={(event) => setLocale(event.currentTarget.value)}>
        <option value="en">English</option><option value="ko">한국어</option>
      </select></label>
    </div>
    <div class="page-head"><div><p class="eyebrow">{t("Release workspace", "릴리스 작업 영역")}</p>
      <h1>{releaseTitle(release, manifest)}</h1><p>{release.label || t("No release label", "릴리스 설명 없음")}</p>
    </div><span class={`status ${release.state}`}>{status}</span></div>
    <div class="facts">
      <div><span>{t("Recorded stage", "기록된 단계")}</span><strong>{stage ?? t("No built-in channel", "기본 채널 소속 없음")}</strong></div>
      <div><span>{t("Manifest signature", "매니페스트 서명")}</span><strong>{release.signature ? t("Development key verified", "개발용 키 검증됨") : t("Unsigned", "서명 없음")}</strong></div>
      <div><span>{t("Catalog revision", "카탈로그 개정 번호")}</span><strong>{catalog.revision}</strong></div>
      <div><span>{t("Artifact availability", "아티팩트 가용성")}</span><strong>{t("Unverified", "검증되지 않음")}</strong></div>
    </div>
    <section class="release-next" aria-labelledby="release-next-title">
      <h2 id="release-next-title">{t("Next step", "다음 단계")}</h2>
      <p>{step === "recall"
        ? t("Recall blocks further publication and channel changes. Review the recorded activity; running installations are not changed here.", "회수된 릴리스는 다시 발행하거나 채널을 변경할 수 없습니다. 기록된 활동을 확인하세요. 실행 중인 설치에는 여기서 변경을 적용하지 않습니다.")
        : step === "renew"
        ? t("The catalog export has expired. Review releases, membership and recalls before explicitly renewing freshness.", "카탈로그 내보내기의 유효 기간이 지났습니다. 릴리스, 채널 소속 및 회수 내역을 검토한 후 명시적으로 갱신하세요.")
        : step === "publish"
        ? t("Review the exact manifest, then confirm development signing and DEV membership. This does not build images or publish them to a registry.", "정확한 매니페스트를 검토한 후 개발용 서명과 DEV 채널 추가를 확인하세요. 이미지를 빌드하거나 레지스트리에 발행하는 작업은 아닙니다.")
        : t("Review promotion evidence before advancing. Channel membership alone does not prove that promotion gates passed.", "다음 단계로 이동하기 전에 승격 근거를 검토하세요. 채널 소속만으로 승격 검사를 통과했다고 판단할 수 없습니다.")}</p>
      {step === "renew" ? <a class="next-link" href="#/trust">{t("Review catalog freshness", "카탈로그 유효 기간 검토")}</a>
        : <button class="primary" disabled={disabled} onClick={() => {
          if (step === "publish") act("publish", release);
          else if (step === "review") reviewEvidence();
          else { history.current?.focus(); history.current?.scrollIntoView({ block: "start" }); }
        }}>{step === "publish" ? t("Review DEV publication", "DEV 발행 검토")
          : step === "review" ? t("Review promotion evidence", "승격 근거 검토")
          : t("Review recall activity", "회수 활동 검토")}</button>}
    </section>
    <section aria-labelledby="release-stage-title"><h2 id="release-stage-title">{t("Channel membership", "채널 소속")}</h2>
      <p>{t("Recorded membership, not a verified promotion history. Custom channels remain in technical details.", "기록된 소속이며 검증된 승격 이력은 아닙니다. 사용자 지정 채널은 기술 세부 정보에서 확인할 수 있습니다.")}</p>
      <ol class="release-stages">{stages.map((name) => <li key={name}><strong>{name}</strong><span>{
        release.channels.includes(name)
          ? release.state === "recalled" ? t("Withdrawn by recall", "회수로 사용 중지됨") : t("Member", "소속됨")
          : t("Not added", "추가되지 않음")
      }</span></li>)}</ol>
    </section>
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
      {transition && blockedCaps.length === 0 && !catalog.expired && (
        <div class="actions">
          <button type="button" class="primary" disabled={disabled} onClick={() => act("promote", release)}>
            {t(`Promote ${transition.sourceChannel} -> ${transition.targetChannel}`, `${transition.sourceChannel} -> ${transition.targetChannel} 승격`)}
          </button>
        </div>
      )}
      <p>{t("Use the supported promotion pipeline for gated advancement. Advanced channel curation below is a separate manual operation, not verified promotion.", "검사가 적용되는 승격에는 지원되는 승격 파이프라인을 사용하세요. 아래 고급 채널 편집은 별도의 수동 작업이며 검증된 승격이 아닙니다.")}</p>
    </details>
    <details class="release-disclosure">
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
        <dt>{t("Schema compatibility", "스키마 호환성")}</dt><dd lang="en">{schemaCompatibility(manifest)}</dd>
        <dt>{t("Development key", "개발용 키")}</dt><dd><code class="digest">{catalog.key_id}</code></dd>
        <dt>{t("Published", "발행 시각")}</dt><dd>{release.published_at ?? t("Not published", "발행되지 않음")}</dd>
        <dt>{t("All channels", "모든 채널")}</dt><dd>{release.channels.join(" / ") || t("None", "없음")}</dd>
      </dl>
      <h2>{t("Declared artifacts", "선언된 아티팩트")}</h2>
      <p>{t("Declared digests only. No registry, SBOM or provenance verification is established by this view.", "선언된 다이제스트만 표시합니다. 이 화면은 레지스트리, SBOM 또는 출처 검증을 입증하지 않습니다.")}</p>
      <div class="artifact-list">{declaredArtifacts.map((artifact) => <article key={artifact.component}>
        <h3>{artifact.component}</h3><code class="digest">{artifact.digest}</code>
        <details><summary>{t("SBOM digest", "SBOM 다이제스트")}</summary><code class="digest" lang="en">{artifact.sbom}</code></details>
      </article>)}</div>
      <details><summary>{t("Exact manifest and detached signature", "정확한 매니페스트 및 분리된 서명")}</summary>
        <pre>{release.manifest}</pre><code class="digest">{release.signature || t("No signature", "서명 없음")}</code>
      </details>
    </details>
    <section ref={history} tabIndex={-1}><h2>{t("Release activity", "릴리스 활동")}</h2><div lang="en">{activity}</div></section>
  </div>;
}
