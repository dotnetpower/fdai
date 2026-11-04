import { PublicClientApplication } from "@azure/msal-browser";
import { useEffect, useRef, useState } from "preact/hooks";
import {
  activeCapabilityRecalls, catalogChangeObserved, catalogRecovery, computeApolloReleaseDiff,
  extractReleaseStencil, isCustomChannel, nextPromotionTransition,
  releaseStateIndex, releaseTitle, requestCatalog, requestEntraLogin, requestEntraLogout,
  requestEntraSession, requestStencilCatalog, requestStencilCompose, syncManifestReleaseVersion,
  type Action, type Catalog, type Change, type EntraSessionStatus, type Release,
} from "./api";
import { DeploymentRequests } from "./deployment-requests";
import { nextSuggestedSemVer, ReleaseLineageSection } from "./release-lineage";
import { ReleaseWorkspace } from "./release-workspace";
import { StencilBuilder } from "./stencil-builder";

const TITLES: Record<Action, string> = {
  register: "Register release",
  publish: "Publish to DEV",
  contribute: "Add to channel",
  promote: "Promote stage",
  recall: "Recall release",
  renew: "Renew catalog freshness",
};
const TITLES_KO: Record<Action, string> = {
  register: "새 릴리스 등록 (Register release)",
  publish: "DEV 채널 서명 및 발행 (Publish to DEV)",
  contribute: "수동 채널 추가 (Add to channel)",
  promote: "다음 단계로 채널 승격 (Promote stage)",
  recall: "릴리스 긴급 회수 (Recall release)",
  renew: "카탈로그 유효기간 24시간 연장 (Renew catalog freshness)",
};
const DEFAULT_REASONS: Record<Action, { en: string; ko: string }> = {
  register: {
    en: "Register reviewed Stencil release manifest",
    ko: "검토 완료된 Stencil 릴리스 매니페스트 등록",
  },
  publish: {
    en: "Sign manifest with development key and publish to DEV ring",
    ko: "개발용 키 서명 및 DEV 검증 채널 발행 승인",
  },
  promote: {
    en: "QA, Stencil labels, and canary soak verified for stage promotion",
    ko: "Stencil 레이블 검증 및 카나리 안정화 기준 충족으로 단계 승격 승인",
  },
  contribute: {
    en: "Curated manual channel eligibility addition",
    ko: "운영자 검토를 거친 수동 채널 소속 추가",
  },
  recall: {
    en: "Emergency release withdrawal due to operational defect",
    ko: "운영 결함 발견으로 인한 릴리스 긴급 회수",
  },
  renew: {
    en: "Reviewed catalog releases, channels, and recalls for 24h freshness renewal",
    ko: "릴리스·채널·회수 상태 검토 완료 후 카탈로그 유효기간 24시간 연장",
  },
};
const ACTION_LABELS_KO: Record<string, string> = {
  register: "릴리스 초안 등록 (register)",
  publish: "DEV 서명 및 발행 (publish)",
  contribute: "채널 승격/추가 (contribute)",
  recall: "릴리스 회수 (recall)",
  recall_capability: "특정 기능 긴급 리콜 (recall_capability)",
  lift_capability: "기능 리콜 해제 (lift_capability)",
  renew: "카탈로그 유효기간 연장 (renew)",
};
type Pending = { action: Action; release: Release | null };
type RegistrationDraft = Pick<Release, "id" | "label" | "manifest">;
type ConfirmationState = {
  action: Action;
  busy: boolean;
  channel: string;
  channelConfirmation: string;
  confirmation: string;
  customChannel: boolean;
  reason: string;
  target: string;
};
const time = (value: string) => new Date(value).toISOString().replace("T", " ").replace(".000Z", " UTC");
const locationRoute = () => decodeURI(location.hash.slice(1) || "/releases");

export function isConfirmationDisabled(state: ConfirmationState): boolean {
  return state.busy
    || state.confirmation !== state.target
    || !state.target
    || state.reason.trim().length < 3
    || (state.action === "contribute"
      && state.customChannel
      && state.channelConfirmation !== state.channel);
}

function Confirm({ pending, catalog, locale, registration, setRegistration, close, done, failed }: {
  pending: Pending; catalog: Catalog; locale: "en" | "ko"; close: () => void; done: (id: string, change: Change) => Promise<void>;
  registration: RegistrationDraft; setRegistration: (draft: RegistrationDraft) => void;
  failed: (failure: unknown) => Promise<void>;
}) {
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [templateBusy, setTemplateBusy] = useState(false);
  const id = pending.action === "register" ? registration.id : pending.release?.id ?? "";
  const [confirmation, setConfirmation] = useState("");
  const [reason, setReason] = useState("");
  const { manifest, label } = registration;
  const transition = pending.release ? nextPromotionTransition(pending.release) : null;
  const pendingStencil = pending.release ? extractReleaseStencil(pending.release) : null;
  const [channel, setChannel] = useState(
    pending.action === "promote" && transition
      ? transition.targetChannel
      : Object.keys(catalog.channels).find((name) => !pending.release?.channels.includes(name)) ?? "",
  );
  const [channelConfirmation, setChannelConfirmation] = useState("");
  const [labelsInput, setLabelsInput] = useState(
    pendingStencil?.release_labels?.length
      ? [...pendingStencil.release_labels, "security-reviewed", "qa-passed"].join(", ")
      : "security-reviewed, qa-passed",
  );
  const [soakSeconds, setSoakSeconds] = useState("0");
  const customChannel = isCustomChannel(channel);
  const action = pending.action;
  const target = action === "renew" ? `renew ${catalog.revision}` : id;
  useEffect(() => {
    const previous = document.activeElement;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);
  async function fillPresetTemplate(presetId: "lite-observe-alert" | "standard-sre" | "full-enterprise") {
    if (templateBusy) return;
    setTemplateBusy(true);
    try {
      const nextVer = id.trim() || nextSuggestedSemVer(catalog.releases);
      const stCat = await requestStencilCatalog();
      const found = stCat.presets.find((p) => p.stencil.stencil_id === presetId)?.stencil;
      const composed = await requestStencilCompose({
        stencil_id: presetId,
        title: found?.title ?? presetId,
        title_ko: found?.title_ko ?? presetId,
        description: found?.description ?? presetId,
        description_ko: found?.description_ko ?? presetId,
        topology_profile: presetId,
        requested_panel_ids: found?.enabled_panel_ids ?? ["audit", "dashboard", "live", "settings-general"],
        requested_workloads: found?.enabled_workloads ?? ["core-control-plane", "operator-service"],
        requested_scheduled_jobs: found?.enabled_scheduled_jobs ?? ["analyzer", "inventory"],
        requested_loops: found?.enabled_loops ?? ["anomaly-analyzer", "inventory-reconciliation", "notification-dispatch", "saga-audit"],
        requested_addons: found?.enabled_addons ?? ["notifications", "read-only-console"],
        auto_resolve_dependencies: true,
        release_version: nextVer,
        source_commit: "auto",
      });
      setRegistration({
        id: nextVer,
        label: `${composed.stencil.stencil_id} (${composed.footprint.enabled_panel_count} menus, ${composed.footprint.workload_count} workloads)`,
        manifest: JSON.stringify(composed.release_manifest, null, 2),
      });
      setConfirmation(nextVer);
      if (!reason.trim()) {
        setReason(locale === "ko" ? DEFAULT_REASONS.register.ko : DEFAULT_REASONS.register.en);
      }
    } finally {
      setTemplateBusy(false);
    }
  }
  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const parsedLabels = labelsInput.split(",").map((item) => item.trim()).filter(Boolean);
      const soak = Math.max(0, Number.parseInt(soakSeconds, 10) || 0);
      const change: Change = {
        revision: catalog.revision, confirmation, reason,
        ...(action === "register" ? { label, manifest } : {}),
        ...(action === "contribute" ? { channel, ...(customChannel ? { channel_confirmation: channelConfirmation } : {}) } : {}),
        ...(action === "promote" && transition ? {
          source_channel: transition.sourceChannel,
          target_channel: transition.targetChannel,
          required_labels: parsedLabels,
          labels: parsedLabels,
          min_soak_seconds: soak,
          elapsed_stage_seconds: soak,
          max_stage_timeout_seconds: Math.max(3600, soak + 3600),
          min_healthy_canaries: 0,
          canary_observations: [],
        } : {}),
      };
      await requestCatalog(action === "renew" ? "/v1/catalog/renew" : `/v1/releases/${encodeURIComponent(id)}/${action}`, change);
      await done(id, change);
    } catch (failure) {
      await failed(failure);
    } finally { setBusy(false); }
  }
  return <dialog ref={dialog} aria-labelledby="confirm-title" onCancel={(event) => {
    event.preventDefault(); if (!busy) close();
  }}>
    <form onSubmit={submit}>
      <header>
        <h2 id="confirm-title">{locale === "ko" ? TITLES_KO[action] : TITLES[action]}</h2>
        <p>{t("Development validation only. No registry publication or installation changes.", "로컬/개발용 검증 작업입니다. 외부 레지스트리 배포나 실제 클러스터 변경은 수행되지 않습니다.")}</p>
      </header>
      {action === "register" && <>
        <div class="stencil-provenance-preview">
          <strong>{t("1-Click Stencil Manifest Generator:", "원클릭 에디션 매니페스트 자동 생성 (JSON 수동 작성 불필요):")}</strong>
          <div class="quick-chips">
            <button type="button" class="chip-btn" disabled={templateBusy} onClick={() => void fillPresetTemplate("lite-observe-alert")}>
              {t("Fill Lite (2 containers · 14 menus)", "경량 에디션 채우기 (컨테이너 2 · 메뉴 14)")}
            </button>
            <button type="button" class="chip-btn" disabled={templateBusy} onClick={() => void fillPresetTemplate("standard-sre")}>
              {t("Fill Standard SRE (3 containers · 32 menus)", "표준 SRE 채우기 (컨테이너 3 · 메뉴 32)")}
            </button>
            <button type="button" class="chip-btn" disabled={templateBusy} onClick={() => void fillPresetTemplate("full-enterprise")}>
              {t("Fill Full Enterprise (5 containers · 60 menus)", "전체 엔터프라이즈 채우기 (컨테이너 5 · 메뉴 60)")}
            </button>
          </div>
        </div>
        <label>
          {t("Release id (SemVer - defaults to next patch 0.5.x)", "릴리스 버전 ID (SemVer - 기본값: 다음 하위 패치 버전)")}
          <input
            required
            aria-label="Release id (SemVer)"
            value={id}
            onInput={(e) => {
              const nextId = e.currentTarget.value;
              setRegistration({
                ...registration,
                id: nextId,
                manifest: syncManifestReleaseVersion(registration.manifest, nextId),
              });
            }}
            placeholder={nextSuggestedSemVer(catalog.releases, "patch")}
          />
        </label>
        <div class="quick-chips">
          <button
            type="button"
            class="chip-btn"
            onClick={() => {
              const v = nextSuggestedSemVer(catalog.releases, "patch");
              setRegistration({
                ...registration,
                id: v,
                manifest: syncManifestReleaseVersion(registration.manifest, v),
              });
              setConfirmation(v);
            }}
          >
            {t(`Patch update (${nextSuggestedSemVer(catalog.releases, "patch")})`, `하위 패치 업데이트 (${nextSuggestedSemVer(catalog.releases, "patch")})`)}
          </button>
          <button
            type="button"
            class="chip-btn"
            onClick={() => {
              const v = nextSuggestedSemVer(catalog.releases, "minor");
              setRegistration({
                ...registration,
                id: v,
                manifest: syncManifestReleaseVersion(registration.manifest, v),
              });
              setConfirmation(v);
            }}
          >
            {t(`Minor upgrade (${nextSuggestedSemVer(catalog.releases, "minor")})`, `마이너 버전 업그레이드 (${nextSuggestedSemVer(catalog.releases, "minor")})`)}
          </button>
          <button
            type="button"
            class="chip-btn"
            onClick={() => {
              const v = nextSuggestedSemVer(catalog.releases, "major");
              setRegistration({
                ...registration,
                id: v,
                manifest: syncManifestReleaseVersion(registration.manifest, v),
              });
              setConfirmation(v);
            }}
          >
            {t(`Major upgrade (${nextSuggestedSemVer(catalog.releases, "major")})`, `메이저 버전 업그레이드 (${nextSuggestedSemVer(catalog.releases, "major")})`)}
          </button>
        </div>
        <label>{t("Release label (optional)", "릴리스 설명 라벨 (선택)")}<input maxLength={160} value={label} onInput={(e) => setRegistration({ ...registration, label: e.currentTarget.value })} /></label>
        <label>{t("Lifecycle release manifest", "릴리스 매니페스트 (JSON)")}<textarea required rows={6} spellcheck={false} value={manifest} onInput={(e) => setRegistration({ ...registration, manifest: e.currentTarget.value })} /></label>
      </>}
      {pending.release && <p><strong>{releaseTitle(pending.release)}</strong><code class="digest">{pending.release.digest}</code></p>}
      {pendingStencil && (
        <div class="preset-metrics">
          <span class="stencil-pill locked">stencil:{pendingStencil.stencil_id}</span>
          <span class="stencil-chip">{pendingStencil.topology_profile}</span>
          <span class="stencil-chip">{pendingStencil.azure_rbac_posture}</span>
        </div>
      )}
      {action === "publish" && <p>{t("Sign the exact manifest with the development key and add it to DEV. This does not establish production trust.", "매니페스트를 개발용 서명 키로 전자서명하고 DEV 채널에 발행합니다.")}</p>}
      {action === "promote" && transition && <>
        <p>{t(`Run the server-side promotion pipeline from ${transition.sourceChannel} to ${transition.targetChannel}. Source membership, active recalls, labels, soak time, and timeouts are verified atomically.`, `서버 측 승격 파이프라인을 통해 ${transition.sourceChannel}에서 ${transition.targetChannel} 채널로 승격합니다. 원본 소속, 기능 리콜 여부, Stencil 레이블, 안정화 시간을 원자적으로 검증합니다.`)}</p>
        <label>{t("Verified gate labels (comma-separated)", "검증된 게이트 레이블 (쉼표 구분)")}<input value={labelsInput} onInput={(e) => setLabelsInput(e.currentTarget.value)} /></label>
        <label>{t("Observed stage soak (seconds)", "관찰된 단계 안정화 시간 (초)")}<input type="number" min="0" step="1" value={soakSeconds} onInput={(e) => setSoakSeconds(e.currentTarget.value)} /></label>
      </>}
      {action === "contribute" && <>
        <label>{t("Destination channel", "대상 채널")}<input required list="contribution-channels" maxLength={64} pattern="DEV|RELEASE_CANDIDATE|RELEASE|custom-[a-z0-9]+(-[a-z0-9]+)*" aria-describedby="channel-help" value={channel} onInput={(e) => setChannel(e.currentTarget.value)} /></label>
        <datalist id="contribution-channels">
          {Object.keys(catalog.channels).filter((c) => !pending.release?.channels.includes(c)).map((c) => <option key={c} value={c} />)}
        </datalist>
        <p id="channel-help">{t("Choose an existing channel or enter custom-name, using lowercase letters, numbers and single hyphens (64 characters maximum).", "기존 채널(DEV, RELEASE_CANDIDATE, RELEASE)을 선택하거나 custom-이름 형식으로 새 커스텀 채널을 입력하세요.")}</p>
        {customChannel && <label class="channel-confirmation">{t(`Type ${channel} to confirm destination`, `대상 채널 확인을 위해 ${channel} 입력`)}<input required maxLength={64} autoComplete="off" value={channelConfirmation} onInput={(e) => setChannelConfirmation(e.currentTarget.value)} /></label>}
      </>}
      {action === "recall" && <p class="warning">{t("Withdraw eligibility in every channel. Recall is irreversible here. Running installations and issued Plans do not change automatically.", "모든 채널에서 이 릴리스의 배포 자격을 즉시 철회합니다. 회수된 릴리스는 다시 발행할 수 없습니다.")}</p>}
      {action === "renew" && <p class="warning">{t("Review the current releases, channels and recalls before confirming. Publish a new revision with 24-hour freshness.", "현재 릴리스·채널·회수 내역을 검토한 후 카탈로그 Export 서명의 유효기간을 24시간 연장합니다.")}</p>}
      <label>{t("Reason", "작업 사유 (Reason)")}<textarea required aria-label="Reason" minLength={3} maxLength={500} rows={2} value={reason} onInput={(e) => setReason(e.currentTarget.value)} /></label>
      <label>{t(`Type ${target || "the Release id"} to confirm`, `확인 코드 입력 (${target || "릴리스 ID"})`)}<input required autoComplete="off" value={confirmation} onInput={(e) => setConfirmation(e.currentTarget.value)} /></label>
      {target && (
        <button type="button" disabled={busy || confirmation === target} onClick={() => {
          setConfirmation(target);
          if (!reason.trim()) {
            setReason(locale === "ko" ? DEFAULT_REASONS[action].ko : DEFAULT_REASONS[action].en);
          }
          if (action === "contribute" && customChannel) setChannelConfirmation(channel);
        }}>
          {locale === "ko"
            ? `원클릭 자동 입력: 사유 + 확인 코드 (${target})`
            : `Fill reviewed confirmation (${target})`}
        </button>
      )}
      <p>{t(`Catalog revision ${catalog.revision}. A concurrent change requires refresh and review.`, `현재 카탈로그 리비전: ${catalog.revision}`)}</p>
      <footer><button type="button" disabled={busy} onClick={close}>{t("Cancel", "취소")}</button>
        <button class={action === "recall" ? "danger" : "primary"} disabled={isConfirmationDisabled({
          action, busy, channel, channelConfirmation, confirmation, customChannel, reason, target,
        })}>
          {busy ? t("Saving...", "저장 중...") : locale === "ko" ? `${TITLES_KO[action]} 실행` : `Confirm ${TITLES[action].toLowerCase()}`}
        </button></footer>
    </form>
  </dialog>;
}

function Status({ release, locale = "en" }: { release: Release; locale?: "en" | "ko" }) {
  const label = release.state === "draft"
    ? (locale === "ko" ? "초안 (미서명)" : "Draft / unsigned")
    : release.state === "recalled"
      ? (locale === "ko" ? "회수됨 (사용 중지)" : "Recalled")
      : (locale === "ko" ? "서명·발행 완료" : "Development published");
  return <span class={`status ${release.state}`}>{label}</span>;
}

function Activity({ catalog, releaseId, locale = "en" }: { catalog: Catalog; releaseId?: string; locale?: "en" | "ko" }) {
  const events = catalog.events.filter((event) => !releaseId || event.release_id === releaseId);
  const stencilByRelease = new Map(
    catalog.releases.map((r) => [r.id, extractReleaseStencil(r)] as const),
  );
  return events.length ? <ol class="activity">{events.map((event) => {
    const st = stencilByRelease.get(event.release_id);
    const actionText = locale === "ko" ? (ACTION_LABELS_KO[event.action] ?? event.action) : event.action;
    return <li key={event.revision}>
      <div><strong>{actionText}{event.channel ? ` -> ${event.channel}` : ""}</strong>{event.action === "renew"
        ? <a href="#/trust">{locale === "ko" ? "카탈로그 유효기간" : "Catalog freshness"}</a>
        : <a href={`#/releases/${event.release_id}`}>Release {event.release_id}</a>}
        {st && <span class="stencil-chip">stencil:{st.stencil_id} ({st.azure_rbac_posture})</span>}
      </div>
      <p>{event.reason}</p><small>{locale === "ko" ? `리비전 ${event.revision}` : `Revision ${event.revision}`} / {time(event.occurred_at)} / {event.actor === "local-operator" ? (locale === "ko" ? "로컬 운영자" : "local operator (unauthenticated)") : event.actor ? `operator: ${event.actor}` : (locale === "ko" ? "운영자 신원 미기재" : "Operator attribution unavailable")}</small>
    </li>;
  })}</ol> : <p class="empty">{locale === "ko" ? "기록된 활동 이력이 없습니다." : "No recorded activity."}</p>;
}

const CHANNEL_GUARDRAILS: Record<string, { tier: string; tier_ko: string; policy: string; policy_ko: string }> = {
  DEV: {
    tier: "Development ring",
    tier_ko: "1단계: 개발 검증 링",
    policy: "Immediate signed publication · 0s soak · sandbox/dev fleet eligibility",
    policy_ko: "서명 즉시 발행 · 대기 시간 0초 · 개발/샌드박스 환경 배포 가능",
  },
  RELEASE_CANDIDATE: {
    tier: "Canary / Staging ring",
    tier_ko: "2단계: 카나리·스테이징 링",
    policy: "Requires DEV membership, zero active capability recalls, and verified Stencil labels",
    policy_ko: "DEV 소속 · 활성 기능 리콜 0건 · Stencil 검증 레이블 충족 시 승격",
  },
  RELEASE: {
    tier: "Production ring",
    tier_ko: "3단계: 운영(Production) 링",
    policy: "Requires RELEASE_CANDIDATE soak, healthy canary quorum, and full recall clearance",
    policy_ko: "RC 안정화 통과 · 카나리 정상 확인 · 모든 리콜 무결성 검증 완료 후 승격",
  },
};

function Channels({ catalog, locale = "en" }: { catalog: Catalog; locale?: "en" | "ko" }) {
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);
  const states = releaseStateIndex(catalog.releases);
  const stencilByRelease = new Map(
    catalog.releases.map((r) => [r.id, extractReleaseStencil(r)] as const),
  );
  return <>
    <div class="page-head"><div><p class="eyebrow">{t("Eligibility curation", "단계별 배포 링 관리")}</p><h1>{t("Channels", "배포 채널 (Channels)")}</h1><p>{t("Manual contributions and Apollo stage-promoted channel rings.", "DEV → RELEASE_CANDIDATE → RELEASE 3단계 배포 링의 자격 기준과 현재 소속 릴리스를 확인합니다.")}</p></div></div>
    <div class="channel-grid">{Object.entries(catalog.channels).map(([channel, members]) => {
      const guardrail = CHANNEL_GUARDRAILS[channel] ?? {
        tier: "Custom channel ring",
        tier_ko: "커스텀 배포 링",
        policy: "Explicit operator-curated channel membership and recall verification",
        policy_ko: "운영자가 직접 지정한 커스텀 채널 소속 및 리콜 검증 적용",
      };
      const eligibleMembers = members.filter((id) => states.get(id) !== "recalled");
      const headRelease = eligibleMembers[0] ?? null;
      return <section class="channel" key={channel}>
        <div class="preset-card-head">
          <h2>{channel}</h2>
          <span class="stencil-pill count-pill">{locale === "ko" ? guardrail.tier_ko : guardrail.tier}</span>
        </div>
        <p><small>{locale === "ko" ? guardrail.policy_ko : guardrail.policy}</small></p>
        <p><strong>{t(`${eligibleMembers.length} active`, `활성 ${eligibleMembers.length}개`)}</strong> / {t(`${members.length} total`, `전체 ${members.length}개`)} {headRelease ? t(`(Channel head: Release ${headRelease})`, `(최신 버전: Release ${headRelease})`) : ""}</p>
        {members.map((id) => {
          const st = stencilByRelease.get(id);
          return <p key={id}><a href={`#/releases/${id}`}>Release {id}</a> {states.get(id) === "recalled" ? t(" / Recalled", " / 회수됨") : ""} {st ? <span class="stencil-chip">{st.stencil_id} · {st.enabled_workloads.length}w/{st.enabled_panel_ids.length}m</span> : null}</p>;
        })}
        {!members.length && <p>{t("No releases added.", "아직 이 채널에 승격·추가된 릴리스가 없습니다.")}</p>}
      </section>;
    })}</div><p>{t("Channel membership is eligibility, not permission to deploy. Installation constraints remain authoritative.", "채널 소속은 배포 자격(Eligibility)을 의미하며, 실제 클러스터 적용 시점과 제약 조건은 각 설치본(Installation) 정책이 결정합니다.")}</p>
  </>;
}

function ReleaseDiffInspector({
  releases,
  locale = "en",
  externalPair,
}: {
  releases: readonly Release[];
  locale?: "en" | "ko";
  externalPair?: { baseId: string; targetId: string } | null;
}) {
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);
  const [baseId, setBaseId] = useState(releases[releases.length - 1]?.id ?? "");
  const [targetId, setTargetId] = useState(releases[0]?.id ?? "");
  useEffect(() => {
    if (externalPair) {
      setBaseId(externalPair.baseId);
      setTargetId(externalPair.targetId);
    }
  }, [externalPair]);
  if (releases.length < 2) return null;
  const base = releases.find((r) => r.id === baseId) ?? releases[releases.length - 1];
  const target = releases.find((r) => r.id === targetId) ?? releases[0];
  if (!base || !target) return null;
  const diff = computeApolloReleaseDiff(base, target);
  return (
    <section id="release-diff-section" aria-labelledby="release-diff-title">
      <h2 id="release-diff-title">{t("Apollo Release-to-Release Diff Inspector", "릴리스 간 구성을 한눈에 비교 (Apollo Release Diff)")}</h2>
      <p>{t("Compare topology, workload containers, Console menu count, and RBAC posture between two registered Releases.", "등록된 두 릴리스 사이의 에디션 변화, 추가·제외된 컨테이너, 메뉴 증감, Azure 권한 차이를 즉시 비교합니다.")}</p>
      <div class="stencil-grid">
        <label>
          {t("Base Release (Before)", "기준 릴리스 (이전 버전)")}
          <select value={base.id} onChange={(e) => setBaseId(e.currentTarget.value)}>
            {releases.map((r) => <option key={r.id} value={r.id}>Release {r.id} ({r.label || "No label"})</option>)}
          </select>
        </label>
        <label>
          {t("Target Release (After)", "비교 대상 릴리스 (새 버전)")}
          <select value={target.id} onChange={(e) => setTargetId(e.currentTarget.value)}>
            {releases.map((r) => <option key={r.id} value={r.id}>Release {r.id} ({r.label || "No label"})</option>)}
          </select>
        </label>
      </div>
      <div class="facts">
        <div><span>{t("Stencil transition", "에디션 프로파일 변화")}</span><strong>{diff.baseProfile} {"->"} {diff.targetProfile}</strong></div>
        <div><span>{t("RBAC transition", "Azure 권한 변화")}</span><strong>{diff.rbacChanged ? `${diff.baseRbac} -> ${diff.targetRbac}` : `${diff.targetRbac} (${t("unchanged", "동일")})`}</strong></div>
        <div><span>{t("Menu delta", "Console 메뉴 수 변화")}</span><strong>+{diff.addedPanelCount} / -{diff.removedPanelCount} {t("menus", "개 메뉴")}</strong></div>
        <div><span>{t("Changed image digests", "변경된 컨테이너 이미지")}</span><strong>{diff.changedComponents.length} {t("component(s)", "개 컴포넌트")}</strong></div>
      </div>
      {(diff.addedWorkloads.length > 0 || diff.removedWorkloads.length > 0) && (
        <ul class="apollo-diff-list">
          {diff.addedWorkloads.map((w) => (
            <li key={`add-${w}`} class="diff-keep"><span class="diff-sign">+</span><code>{w}</code><small>{t(`added in ${target.id}`, `${target.id}에서 추가됨`)}</small></li>
          ))}
          {diff.removedWorkloads.map((w) => (
            <li key={`rem-${w}`} class="diff-drop"><span class="diff-sign">-</span><code>{w}</code><small>{t(`omitted in ${target.id}`, `${target.id}에서 제외됨`)}</small></li>
          ))}
        </ul>
      )}
    </section>
  );
}

const CAPABILITY_PRESET_CHIPS: { id: string; en: string; ko: string }[] = [
  { id: "isolated-executor", en: "Isolated Executor (isolated-executor)", ko: "격리 조치 실행기 (isolated-executor)" },
  { id: "remediation-execution", en: "Remediation Loop (remediation-execution)", ko: "자동 복구 루프 (remediation-execution)" },
  { id: "document-ingestion", en: "Document Ingestion (document-ingestion)", ko: "문서 지식 수집 (document-ingestion)" },
  { id: "cost-governance", en: "Cost Governance (cost-governance)", ko: "비용 거버넌스 (cost-governance)" },
  { id: "code-security", en: "Code Security (code-security)", ko: "코드 보안 스캔 (code-security)" },
];

function CapabilityRecallControl({
  catalog,
  disabled,
  locale = "en",
  onUpdated,
}: {
  catalog: Catalog;
  disabled: boolean;
  locale?: "en" | "ko";
  onUpdated: (next: Catalog, message: string) => void;
}) {
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);
  const recalled = activeCapabilityRecalls(catalog.events);
  const [capTarget, setCapTarget] = useState("isolated-executor");
  const [capAction, setCapAction] = useState<"recall" | "lift">("recall");
  const [liftingReleaseId, setLiftingReleaseId] = useState(
    catalog.releases.find((r) => r.state === "published")?.id ?? "",
  );
  const [reason, setReason] = useState("Surgical Apollo capability recall / lift verification");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submitCap(event: SubmitEvent) {
    event.preventDefault();
    if (busy || disabled || !capTarget.trim() || reason.trim().length < 3) return;
    setBusy(true);
    setErr("");
    try {
      const next = await requestCatalog(
        `/v1/capabilities/${encodeURIComponent(capTarget.trim())}/${capAction}`,
        {
          revision: catalog.revision,
          confirmation: capTarget.trim(),
          reason: reason.trim(),
          ...(capAction === "lift" ? { lifting_release_id: liftingReleaseId.trim() } : {}),
        },
      );
      onUpdated(
        next,
        capAction === "recall"
          ? t(
              `Capability '${capTarget}' recalled. Releases declaring '${capTarget}' are now blocked from promotion.`,
              `기능 '${capTarget}'에 긴급 리콜이 발령되었습니다. 이 기능을 포함한 릴리스만 승격이 정밀 차단되며 경량 에디션은 정상 통과합니다.`,
            )
          : t(
              `Capability '${capTarget}' recall lifted by Release ${liftingReleaseId}.`,
              `릴리스 ${liftingReleaseId}를 통해 기능 '${capTarget}' 리콜이 해제되었습니다.`,
            ),
      );
    } catch (e) {
      setErr(catalogRecovery(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-labelledby="cap-recall-title">
      <h2 id="cap-recall-title">{t("Apollo Surgical Capability Recall & Lift Control", "기능 단위 정밀 리콜 및 복구 제어 (Apollo Surgical Recall)")}</h2>
      <p>
        {t(
          "Recall a specific workload or agent loop (for example isolated-executor, remediation-execution, or document-ingestion) without recalling unaffected lightweight Releases such as lite-observe-alert.",
          "전체 릴리스를 폐기하지 않고 문제가 생긴 특정 기능·컨테이너만 정밀 차단합니다. 해당 기능을 쓰지 않는 경량 에디션(lite-observe-alert)은 중단 없이 정상 승격됩니다.",
        )}
      </p>
      <div class="preset-metrics" style="margin-bottom: 12px;">
        <strong>{t("Active capability recalls:", "현재 차단(리콜)된 기능:")}</strong>
        {recalled.length === 0 ? (
          <span class="stencil-chip">{t("None (All capabilities healthy)", "없음 (모든 기능 정상)")}</span>
        ) : (
          recalled.map((c) => <span key={c} class="stencil-pill locked">RECALLED: {c}</span>)
        )}
      </div>
      <div class="quick-chips" style="margin-bottom: 16px;">
        {CAPABILITY_PRESET_CHIPS.map((chip) => (
          <button
            key={chip.id}
            type="button"
            class="chip-btn"
            onClick={() => {
              setCapTarget(chip.id);
              setCapAction(recalled.includes(chip.id) ? "lift" : "recall");
            }}
          >
            {locale === "ko" ? chip.ko : chip.en}
          </button>
        ))}
      </div>
      {err && <p class="error" role="alert">{err}</p>}
      <form onSubmit={submitCap} class="stencil-grid">
        <label>
          {t("Target capability / workload / loop ID", "대상 기능 / 워크로드 / 에이전트 루프 ID")}
          <input
            required
            list="apollo-capabilities-list"
            value={capTarget}
            onInput={(e) => setCapTarget(e.currentTarget.value)}
          />
          <datalist id="apollo-capabilities-list">
            {CAPABILITY_PRESET_CHIPS.map((c) => <option key={c.id} value={c.id} />)}
          </datalist>
        </label>
        <label>
          {t("Operation", "실행할 작업")}
          <select
            value={capAction}
            onChange={(e) => setCapAction(e.currentTarget.value as "recall" | "lift")}
          >
            <option value="recall">{t("Recall capability (Block promotion of dependent Releases)", "기능 리콜 발령 (이 기능을 포함한 릴리스의 승격 차단)")}</option>
            <option value="lift">{t("Lift capability recall (Requires published lifting Release)", "기능 리콜 해제 (수정된 발행 릴리스 지정)")}</option>
          </select>
        </label>
        {capAction === "lift" && (
          <label>
            {t("Lifting Release ID (Published SemVer)", "결함이 수정된 릴리스 버전 ID (SemVer)")}
            <input
              required
              value={liftingReleaseId}
              onInput={(e) => setLiftingReleaseId(e.currentTarget.value)}
              placeholder="0.5.0"
            />
          </label>
        )}
        <label>
          {t("Audit reason", "감사 기록 사유")}
          <input
            required
            minLength={3}
            value={reason}
            onInput={(e) => setReason(e.currentTarget.value)}
          />
        </label>
        <div class="stencil-provenance-span">
          <button type="submit" class={capAction === "recall" ? "danger" : "primary"} disabled={busy || disabled}>
            {busy
              ? t("Applying...", "처리 중...")
              : capAction === "recall"
                ? t(`Recall capability '${capTarget}'`, `'${capTarget}' 기능 리콜 발령`)
                : t(`Lift capability '${capTarget}'`, `'${capTarget}' 기능 리콜 해제`)}
          </button>
        </div>
      </form>
    </section>
  );
}

function EntraSignInDialog({
  entraStatus,
  locale,
  close,
  onSignedIn,
}: {
  entraStatus: EntraSessionStatus | null;
  locale: "en" | "ko";
  close: () => void;
  onSignedIn: (next: EntraSessionStatus, message: string) => void;
}) {
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);
  const dialog = useRef<HTMLDialogElement>(null);
  const detected = entraStatus?.detected_accounts ?? [];
  const defaultAccount = detected[0];
  const [tenantId, setTenantId] = useState(
    defaultAccount?.tenant_id ?? "00000000-0000-0000-0000-000000000000",
  );
  const [clientId, setClientId] = useState("00000000-0000-0000-0000-000000000000");
  const [principalInput, setPrincipalInput] = useState(
    defaultAccount?.principal ?? "operator@microsoft.com",
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    const previous = document.activeElement;
    dialog.current?.showModal();
    return () => {
      dialog.current?.close();
      if (previous instanceof HTMLElement) previous.focus();
    };
  }, []);

  async function signInWorkstation(principal?: string, tenant?: string, label?: string) {
    if (busy) return;
    setBusy(true);
    setErr("");
    try {
      const next = await requestEntraLogin({
        mode: "workstation",
        principal: (principal ?? principalInput).trim(),
        tenant_id: (tenant ?? tenantId).trim(),
        display_name: label ?? "",
      });
      onSignedIn(
        next,
        t(
          `Signed in with Microsoft Entra ID as ${next.session?.principal ?? next.actor}.`,
          `Microsoft Entra ID 계정(${next.session?.principal ?? next.actor})으로 로그인되었습니다. 이후 모든 릴리스 작업에 이 계정이 기록됩니다.`,
        ),
      );
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Microsoft Entra ID sign-in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function signInMsalPopup() {
    if (busy) return;
    setBusy(true);
    setErr("");
    try {
      const cleanTenant = tenantId.trim().toLowerCase();
      const cleanClient = clientId.trim();
      const msal = new PublicClientApplication({
        auth: {
          clientId: cleanClient,
          authority: `https://login.microsoftonline.com/${cleanTenant}`,
          redirectUri: window.location.origin,
        },
        cache: { cacheLocation: "sessionStorage" },
      });
      await msal.initialize();
      const authResult = await msal.loginPopup({
        scopes: ["openid", "profile", "email"],
        prompt: "select_account",
      });
      const acct = authResult.account;
      if (!acct) throw new Error("No Microsoft Entra ID account returned from popup.");
      const next = await requestEntraLogin({
        mode: "msal_account",
        principal: acct.username || acct.localAccountId,
        display_name: acct.name || acct.username,
        tenant_id: acct.tenantId || cleanTenant,
        client_id: cleanClient,
      });
      onSignedIn(
        next,
        t(
          `Signed in via MSAL OAuth2 PKCE as ${next.session?.principal}.`,
          `MSAL OAuth2 PKCE를 통해 Microsoft Entra ID(${next.session?.principal})로 로그인되었습니다.`,
        ),
      );
    } catch (e) {
      setErr(
        e instanceof Error
          ? e.message
          : t("MSAL popup sign-in was cancelled or failed.", "MSAL 팝업 로그인이 취소되었거나 실패했습니다."),
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      aria-labelledby="entra-dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) close();
      }}
    >
      <header>
        <h2 id="entra-dialog-title">
          {t("Sign in with Microsoft Entra ID", "Microsoft Entra ID 운영자 로그인")}
        </h2>
        <p>
          {t(
            "Bind your Microsoft Entra ID identity so every Release registration, DEV publication, stage promotion, and capability recall is attributed to your account.",
            "Microsoft Entra ID 계정으로 로그인하면 릴리스 등록, DEV 전자서명 발행, 단계 승격, 긴급 기능 리콜 등 모든 감사 이력(Activity)에 귀하의 Entra ID 신원이 기록됩니다.",
          )}
        </p>
      </header>

      {err && <p class="error" role="alert">{err}</p>}

      {detected.length > 0 && (
        <section style="margin-top: 16px;">
          <h3>
            {t(
              "1. Detected Workstation Microsoft Entra ID Account (1-Click)",
              "1. 현재 워크스테이션에 연결된 Microsoft Entra ID 계정 (원클릭 로그인)",
            )}
          </h3>
          <div class="apollo-diff-list">
            {detected.map((acct) => (
              <div
                key={`${acct.principal}-${acct.tenant_id}`}
                class="stencil-provenance-preview"
                style="justify-content: space-between;"
              >
                <div>
                  <strong>{acct.principal}</strong>
                  <div class="preset-metrics" style="margin-top: 4px;">
                    <span class="stencil-chip">Tenant: {acct.tenant_id}</span>
                    <span class="stencil-chip">{acct.tenant_label}</span>
                  </div>
                </div>
                <button
                  type="button"
                  class="primary"
                  disabled={busy}
                  onClick={() =>
                    void signInWorkstation(acct.principal, acct.tenant_id, `${acct.principal} (${acct.tenant_label})`)
                  }
                >
                  {t(`Continue as ${acct.principal}`, `${acct.principal} 계정으로 즉시 로그인`)}
                </button>
              </div>
            ))}
          </div>
        </section>
      )}

      <section style="margin-top: 24px;">
        <h3>
          {t(
            "2. Interactive MSAL OAuth2 PKCE Sign-In or Custom Entra Principal",
            "2. 브라우저 MSAL OAuth2 팝업 로그인 또는 Entra 계정 직접 지정",
          )}
        </h3>
        <div class="stencil-grid">
          <label>
            {t("Microsoft Entra Tenant ID (UUID)", "Microsoft Entra 테넌트 ID (UUID)")}
            <input
              value={tenantId}
              onInput={(e) => setTenantId(e.currentTarget.value)}
              placeholder="00000000-0000-0000-0000-000000000000"
            />
          </label>
          <label>
            {t("Entra SPA Application (Client) ID", "Entra SPA 애플리케이션 (Client) ID")}
            <input
              value={clientId}
              onInput={(e) => setClientId(e.currentTarget.value)}
              placeholder="00000000-0000-0000-0000-000000000000"
            />
          </label>
          <label class="stencil-provenance-span">
            {t("Operator UPN / Email", "운영자 Entra ID 이메일 (UPN)")}
            <input
              value={principalInput}
              onInput={(e) => setPrincipalInput(e.currentTarget.value)}
              placeholder="operator@microsoft.com"
            />
          </label>
        </div>
        <div class="actions">
          <button type="button" class="primary" disabled={busy} onClick={() => void signInWorkstation()}>
            {t("Sign in with UPN & Tenant ID", "입력한 Entra ID 계정으로 로그인")}
          </button>
          <button type="button" disabled={busy} onClick={() => void signInMsalPopup()}>
            {t("Open Microsoft login popup (MSAL PKCE)", "Microsoft 공식 로그인 팝업 열기 (MSAL PKCE)")}
          </button>
        </div>
      </section>

      <footer>
        <button type="button" disabled={busy} onClick={close}>
          {t("Close", "닫기")}
        </button>
      </footer>
    </dialog>
  );
}

export function App() {
  const [locale, setLocaleState] = useState<"en" | "ko">(() => {
    try {
      const saved = localStorage.getItem("fdai-release-hub-locale");
      if (saved === "ko" || saved === "en") return saved;
    } catch {
      // Ignore storage access errors
    }
    return navigator.language.startsWith("ko") ? "ko" : "en";
  });
  function setLocale(next: "en" | "ko") {
    setLocaleState(next);
    try {
      localStorage.setItem("fdai-release-hub-locale", next);
    } catch {
      // Ignore storage access errors
    }
  }
  const t = (en: string, ko: string) => (locale === "ko" ? ko : en);

  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [entraStatus, setEntraStatus] = useState<EntraSessionStatus | null>(null);
  const [entraDialogOpen, setEntraDialogOpen] = useState(false);
  const [route, setRoute] = useState(locationRoute);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState<Pending | null>(null);
  const [registration, setRegistration] = useState<RegistrationDraft>({ id: "", label: "", manifest: "" });
  const [diffPair, setDiffPair] = useState<{ baseId: string; targetId: string } | null>(null);
  const [notice, setNotice] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const heading = useRef<HTMLElement>(null);
  async function refresh() {
    setLoading(true);
    try {
      const [current, session] = await Promise.all([
        requestCatalog(),
        requestEntraSession(),
      ]);
      setCatalog(current);
      if (session) setEntraStatus(session);
      setError("");
      return current;
    }
    catch (failure) { setError(catalogRecovery(failure)); return null; }
    finally { setLoading(false); }
  }
  useEffect(() => {
    void refresh();
    const changed = () => { setRoute(locationRoute()); setNotice(""); heading.current?.focus(); };
    addEventListener("hashchange", changed);
    return () => removeEventListener("hashchange", changed);
  }, []);
  const releaseId = route.startsWith("/releases/") ? route.slice(10) : null;
  const release = catalog?.releases.find((r) => r.id === releaseId);
  const active = route.startsWith("/releases") ? "/releases" : route;
  const disabled = loading || !!error;
  const navItems: [string, string, string][] = [
    ["/stencils", "Stencils", "1. 스텐실·메뉴 빌더"],
    ["/releases", "Releases", "2. 릴리스 목록·발행"],
    ["/channels", "Channels", "3. 배포 채널 (DEV·RC·운영)"],
    ["/deployment-requests", "Deployment requests", "4. 구독 배포 요청"],
    ["/activity", "Activity", "5. 변경·감사 이력"],
    ["/trust", "Catalog trust", "6. 서명 신뢰 및 기능 리콜"],
  ];
  return <div class="app" lang={locale}>
    <a class="skip" href="#main" onClick={(event) => { event.preventDefault(); heading.current?.focus(); }}>Skip to content</a>
    <nav class="side" aria-label="Release Hub">
      <div class="brand"><img src="/brand/fdai-logo.png" alt="FDAI" /><span>Release Hub<small>{t("Vendor workspace", "릴리스 컨트롤 플레인")}</small></span></div>
      {navItems.map(([path, titleEn, titleKo]) =>
        <a key={path} class={active === path ? "nav-link current" : "nav-link"} href={`#${path}`} aria-current={active === path ? "page" : undefined}>{locale === "ko" ? titleKo : titleEn}</a>)}
      <div class="side-note">
        <strong>
          {entraStatus?.authenticated
            ? t("Microsoft Entra ID verified", "Microsoft Entra ID 로그인됨")
            : t("Development validation", "로컬 검증 모드 (미로그인)")}
        </strong>
        <p>
          {entraStatus?.authenticated && entraStatus.session
            ? `${entraStatus.session.principal} (Tenant ${entraStatus.session.tenant_id.slice(0, 8)}...)`
            : t("No production trust root or deployment authority.", "상단 'Microsoft Entra ID 로그인' 버튼으로 운영자 계정을 연결하세요.")}
        </p>
      </div>
    </nav>
    <main id="main" class="main" ref={heading} tabIndex={-1}>
      <div class="workspace-bar">
        <span>{t("Vendor / FDAI", "FDAI 릴리스 허브 (권장 순서: 1. 스텐실 구성 -> 2. 릴리스 등록/발행 -> 3. 채널 승격)")}</span>
        <div class="actions" style="margin-top: 0;">
          {entraStatus?.authenticated && entraStatus.session ? (
            <span class="stencil-provenance-preview" style="padding: 4px 10px;">
              <span class="stage-pill done">Entra ID</span>
              <strong>{entraStatus.session.principal}</strong>
              <button
                type="button"
                class="chip-btn"
                onClick={() => setEntraDialogOpen(true)}
              >
                {t("Switch account", "계정 전환")}
              </button>
              <button
                type="button"
                class="chip-btn"
                onClick={() => {
                  void requestEntraLogout().then((next) => {
                    setEntraStatus(next);
                    setNotice(
                      t(
                        "Signed out of Microsoft Entra ID.",
                        "Microsoft Entra ID에서 로그아웃되었습니다.",
                      ),
                    );
                  });
                }}
              >
                {t("Sign out", "로그아웃")}
              </button>
            </span>
          ) : (
            <button
              type="button"
              class="primary"
              onClick={() => setEntraDialogOpen(true)}
            >
              {t("Sign in with Microsoft Entra ID", "Microsoft Entra ID 로그인")}
            </button>
          )}
          <label style="display: inline-flex; align-items: center; gap: 8px; margin: 0;">
            <span>{t("Language", "화면 언어")}</span>
            <select value={locale} onChange={(e) => setLocale(e.currentTarget.value as "en" | "ko")}>
              <option value="en">English</option>
              <option value="ko">한국어</option>
            </select>
          </label>
          <button disabled={loading} onClick={() => { setNotice(""); void refresh(); }}>{loading ? t("Loading...", "불러오는 중...") : t("Refresh catalog", "카탈로그 새로고침")}</button>
        </div>
      </div>
      <nav class="workflow-guide" aria-label={t("Release workflow steps", "릴리스 진행 4단계 가이드")}>
        <a href="#/stencils" class={`workflow-step ${active === "/stencils" ? "active" : ""}`}>
          <strong>{t("Step 1 · Stencil Builder", "1단계 · 에디션 및 메뉴 맞춤 구성")}</strong>
          <small>{t("Choose Lite/Standard/Full or custom Console menus", "경량·표준·전체 프리셋 또는 원하는 메뉴만 선택")}</small>
        </a>
        <a href="#/releases" class={`workflow-step ${active === "/releases" ? "active" : ""}`}>
          <strong>{t("Step 2 · Register & Publish", "2단계 · 릴리스 등록 및 DEV 발행")}</strong>
          <small>{t("Register manifest and sign into DEV ring", "생성된 매니페스트 등록 및 개발용 전자서명 발행")}</small>
        </a>
        <a href="#/channels" class={`workflow-step ${active === "/channels" ? "active" : ""}`}>
          <strong>{t("Step 3 · Stage Promotion", "3단계 · 단계별 채널 승격 (RC · 운영)")}</strong>
          <small>{t("Promote DEV -> RELEASE_CANDIDATE -> RELEASE", "승격 게이트 검증 후 스테이징·운영 채널로 승격")}</small>
        </a>
        <a href="#/trust" class={`workflow-step ${active === "/trust" || active === "/deployment-requests" ? "active" : ""}`}>
          <strong>{t("Step 4 · Trust & Surgical Recall", "4단계 · 서명 핀 확인 및 기능 리콜")}</strong>
          <small>{t("Verify export pin or recall specific capabilities", "Export 핀 검증 및 결함 기능 단위 정밀 리콜 제어")}</small>
        </a>
      </nav>
      <p class="boundary">{t("Development signatures only. Images remain external; nothing is deployed.", "모든 매니페스트와 Stencil 블루프린트는 전자서명으로 무결성이 검증되며, 클러스터 배포는 별도 승인 후 수행됩니다.")}</p>
      {error && <p class="error" role="alert">Catalog unavailable: {error} {catalog ? "Previously loaded data is shown; mutations are disabled." : "Use Refresh catalog to retry."}</p>}
      {notice && <p role={uncertain ? "alert" : "status"} class={error || uncertain ? "warning" : "success"}>{notice}</p>}
      {route === "/deployment-requests" && <DeploymentRequests catalog={catalog} locale={locale} />}
      {!catalog && !error && <p role="status" class="empty">{t("Loading release catalog...", "릴리스 카탈로그 불러오는 중...")}</p>}
      {catalog && <>
        {catalog.expired && <p class="warning">{t(`Catalog export expired at ${time(catalog.expires_at)}. Consumers will reject it. Review the releases, channels and recalls, then use `, `카탈로그 Export 유효기간(${time(catalog.expires_at)})이 만료되었습니다. 하위 설치본이 이를 거부하므로 검토 후 `)}<a href="#/trust">{t("Catalog trust", "서명 신뢰 및 기능 리콜")}</a>{t(" to explicitly renew freshness. Refresh catalog is read-only.", " 메뉴에서 유효기간을 24시간 연장하세요.")}</p>}
        {release ? <ReleaseWorkspace release={release} catalog={catalog} locale={locale} onLocaleChange={setLocale} disabled={disabled} act={(action, r) => setPending({ action, release: r })} activity={<Activity catalog={catalog} releaseId={release.id} locale={locale} />} />
          : releaseId ? <><h1>{t("Release unavailable", "릴리스를 찾을 수 없음")}</h1><p>{t(`No release matches ${releaseId}.`, `${releaseId} 버전의 릴리스가 존재하지 않습니다.`)}</p><a href="#/releases">{t("Back to releases", "릴리스 목록으로 돌아가기")}</a></>
          : route === "/releases" ? <>
            <div class="page-head">
              <div>
                <p class="eyebrow">{t("Release catalog", "릴리스 카탈로그 및 단계 승격")}</p>
                <h1>{t("Releases", "릴리스 목록 (Releases)")}</h1>
                <p>{t("Publish once. Curate eligibility. Keep the evidence in view.", "한 번 서명·발행한 불변 아티팩트를 DEV → RELEASE_CANDIDATE → RELEASE 단계별로 안전하게 승격합니다.")}</p>
              </div>
              <div class="actions" style="margin-top: 0;">
                <a class="next-link" href="#/stencils" style="padding: 8px 14px; border: 1px solid var(--rh-border); border-radius: var(--cs-radius-sm); text-decoration: none;">
                  {t("Build custom Stencil first", "맞춤 Stencil 먼저 구성하기")}
                </a>
                <button
                  class="primary"
                  disabled={disabled}
                  aria-label="Register release"
                  onClick={() => {
                    if (!registration.id.trim()) {
                      setRegistration((prev) => ({
                        ...prev,
                        id: nextSuggestedSemVer(catalog.releases, "patch"),
                      }));
                    }
                    setPending({ action: "register", release: null });
                  }}
                >
                  {t("Register release", "새 릴리스 바로 등록")}
                </button>
              </div>
            </div>
            <div class="summary"><strong>{t(`${catalog.releases.length} releases`, `총 ${catalog.releases.length}개 릴리스`)}</strong><span>{t(`Revision ${catalog.revision}`, `카탈로그 리비전 ${catalog.revision}`)}</span><span>{t(`Updated ${time(catalog.updated_at)}`, `최근 갱신 ${time(catalog.updated_at)}`)}</span></div>
            {catalog.releases.length === 0 ? <section class="empty"><h2>{t("No releases yet", "아직 등록된 릴리스가 없습니다")}</h2><p>{t("Use 1. Stencil Builder to compose a custom edition or click Register release to auto-fill a template.", "상단의 '새 릴리스 바로 등록' 버튼을 눌러 원클릭 템플릿으로 생성하거나, '1. 스텐실·메뉴 빌더'에서 원하는 메뉴만 골라 시작하세요.")}</p></section>
              : <>
                <ReleaseLineageSection
                  catalog={catalog}
                  locale={locale}
                  activeReleaseId={pending?.release?.id ?? null}
                  buildingDraft={
                    pending?.action === "register" && registration.id.trim()
                      ? {
                          id: registration.id.trim(),
                          stencilId: registration.label.split(" ")[0] || "custom-stencil",
                          label: registration.label,
                        }
                      : null
                  }
                  disabled={disabled}
                  onAct={(action, r) => setPending({ action, release: r })}
                  onComparePair={(bId, tId) => {
                    setDiffPair({ baseId: bId, targetId: tId });
                    document.getElementById("release-diff-section")?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }}
                />
                <div class="release-list">{catalog.releases.map((r) => {
                  const st = extractReleaseStencil(r);
                  const inDev = r.channels.includes("DEV");
                  const inRc = r.channels.includes("RELEASE_CANDIDATE");
                  const inProd = r.channels.includes("RELEASE");
                  return <a key={r.id} href={`#/releases/${r.id}`} class="release-row">
                    <div>
                      <strong>{releaseTitle(r)}</strong>
                      <p>{r.label || t("No label", "설명 없음")}</p>
                      {st && (
                        <div class="preset-metrics" style="margin-top: 6px;">
                          <span class="stencil-pill locked">{st.stencil_id}</span>
                          <span class="stencil-chip">{t(`${st.enabled_workloads.length} workloads · ${st.enabled_panel_ids.length} menus`, `컨테이너 ${st.enabled_workloads.length}개 · 메뉴 ${st.enabled_panel_ids.length}개`)}</span>
                          <span class="stencil-chip">{st.azure_rbac_posture === "read-only-observation" ? t("read-only-observation", "100% 읽기 전용") : t("governed-execution", "승인 기반 실행")}</span>
                        </div>
                      )}
                    </div>
                    <Status release={r} locale={locale} />
                    <div class="stage-pills" aria-label={r.channels.join(" / ") || "No channel"}>
                      <span class={`stage-pill ${inDev ? "done" : ""}`}>DEV</span>
                      <span>→</span>
                      <span class={`stage-pill ${inRc ? "done" : ""}`}>RC</span>
                      <span>→</span>
                      <span class={`stage-pill ${inProd ? "done" : ""}`}>RELEASE</span>
                    </div>
                    <span class="row-next" aria-hidden="true">{t("View details & promote ->", "상세 보기 및 승격 ->")}</span>
                  </a>;
                })}</div>
                <ReleaseDiffInspector releases={catalog.releases} locale={locale} externalPair={diffPair} />
              </>}
          </>           : route === "/deployment-requests" ? null
          : route === "/stencils" ? <StencilBuilder
            locale={locale}
            onLocaleChange={setLocale}
            existingReleases={catalog.releases}
            onPrepareRelease={(draft) => {
              setRegistration(draft);
              setPending({ action: "register", release: null });
            }}
          />
          : route === "/channels" ? <Channels catalog={catalog} locale={locale} />
          : route === "/activity" ? <><h1>{t("Activity", "변경 및 감사 이력 (Activity)")}</h1><p>{t("Transactional publication changes, newest first. Development attribution is not a production audit guarantee.", "릴리스 등록, 서명 발행, 단계 승격, 기능 리콜 등 모든 카탈로그 트랜잭션 이력을 최신순으로 표시합니다.")}</p><Activity catalog={catalog} locale={locale} /></>
          : route === "/trust" ? <>
            <h1>{t("Catalog trust", "서명 신뢰 및 긴급 기능 리콜 (Catalog Trust)")}</h1><p>{t("Verify exact export bytes and every published manifest before Lifecycle planning.", "카탈로그 Export 서명 핀 검증, 유효기간 갱신, 그리고 특정 결함 기능만 정밀 차단하는 Apollo Surgical Recall을 관리합니다.")}</p>
            <section><h2>{t("Development verification boundary", "카탈로그 전자서명 및 Export 핀 정보")}</h2><p>{t("Release signatures are verified against the active development key on every read. Channels and recalls are development metadata, not signed production catalog roles.", "모든 릴리스 매니페스트와 내장된 Stencil 블루프린트는 읽을 때마다 공개키로 서명을 검증합니다.")}</p>
              <dl><dt>{t("Key id", "서명 키 ID")}</dt><dd><code>{catalog.key_id}</code></dd><dt>{t("Revision", "카탈로그 리비전")}</dt><dd>{catalog.revision}</dd><dt>{t("Export expiry", "Export 만료 시각")}</dt><dd>{time(catalog.expires_at)}</dd><dt>{t("Export SHA-256 pin", "Export SHA-256 고정 핀")}</dt><dd><code class="digest">{catalog.export_sha256 || "Refresh to obtain the current pin."}</code></dd></dl>
              <a href="/v1/catalog/export" target="_blank" rel="noreferrer">{t("Open local JSON export (new tab)", "서명된 카탈로그 JSON 원본 열기 (새 탭)")}</a>
            </section>
            {catalog.releases.some((r) => extractReleaseStencil(r) !== null) && (
              <section>
                <h2>{t("Signed Stencil blueprints in catalog", "카탈로그 내 전자서명된 Stencil 블루프린트 목록")}</h2>
                <p>{t("Each Stencil blueprint below is embedded inside its canonical Release manifest and covered by the Release signature.", "아래 Stencil 블루프린트는 각 릴리스 매니페스트 내부에 내장되어 전자서명으로 위변조가 방지됩니다.")}</p>
                <dl>
                  {catalog.releases.map((r) => {
                    const st = extractReleaseStencil(r);
                    if (!st) return null;
                    return <>
                      <dt key={`dt-${r.id}`}><a href={`#/releases/${r.id}`}>Release {r.id}</a> ({st.stencil_id})</dt>
                      <dd key={`dd-${r.id}`}><code class="digest">{st.stencil_digest}</code> · {st.azure_rbac_posture} · {t(`${st.enabled_workloads.length} workloads / ${st.enabled_panel_ids.length} menus`, `컨테이너 ${st.enabled_workloads.length}개 / 메뉴 ${st.enabled_panel_ids.length}개`)}</dd>
                    </>;
                  })}
                </dl>
              </section>
            )}
            <CapabilityRecallControl
              catalog={catalog}
              disabled={disabled}
              locale={locale}
              onUpdated={(next, msg) => {
                setCatalog(next);
                setUncertain(false);
                setNotice(msg);
              }}
            />
            <section><h2>{t("Renew development freshness", "카탈로그 서명 유효기간 24시간 연장")}</h2>
              <p>{t("After reviewing the releases, channels and recalls, extend freshness by 24 hours from publication without changing their content.", "릴리스·채널·리콜 내역을 변경하지 않고 카탈로그 Export 서명의 유효기간만 현재 시각 기준 24시간 연장합니다.")}</p>
              <button disabled={disabled} onClick={() => setPending({ action: "renew", release: null })}>{t("Renew catalog freshness", "카탈로그 유효기간 24시간 연장 실행")}</button>
            </section>
          </> : <><h1>Page not found</h1><a href="#/releases">Back to releases</a></>}
      </>}
      {entraDialogOpen && (
        <EntraSignInDialog
          entraStatus={entraStatus}
          locale={locale}
          close={() => setEntraDialogOpen(false)}
          onSignedIn={(next, msg) => {
            setEntraStatus(next);
            setEntraDialogOpen(false);
            setUncertain(false);
            setNotice(msg);
          }}
        />
      )}
      {pending && catalog && <Confirm pending={pending} catalog={catalog} locale={locale} registration={registration} setRegistration={setRegistration} close={() => setPending(null)} done={async (id, change) => {
        const renewed = pending.action === "renew";
        setUncertain(false);
        setPending(null); location.hash = renewed ? "/trust" : `/releases/${id}`; const readBack = await refresh();
        const observed = readBack && catalogChangeObserved(readBack, pending.action, id, change);
        if (observed && pending.action === "register") setRegistration({ id: "", label: "", manifest: "" });
        setUncertain(!observed);
        setNotice(observed
          ? renewed
            ? "Freshness renewal recorded and read back. Customers still need separate pin approval and import; no deployment was performed."
            : "Catalog change recorded and read back; no deployment was performed."
          : "The API accepted the request, but the exact attributed change is not confirmed by catalog readback. Review activity and refresh before another action.");
        heading.current?.focus();
      }} failed={async (failure) => {
        setPending(null);
        setUncertain(true);
        setNotice(`Write outcome unconfirmed. ${catalogRecovery(failure)} Reading authoritative catalog state; no write will be replayed.`);
        const readBack = await refresh();
        setNotice(`Write outcome unconfirmed. ${catalogRecovery(failure)} ${readBack
          ? "Current catalog read back. Review membership and activity before opening a new confirmation."
          : "Catalog readback failed. Mutations remain disabled until a successful refresh."}`);
        heading.current?.focus();
      }} />}
    </main>
  </div>;
}
