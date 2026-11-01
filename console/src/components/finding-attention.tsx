import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { architectureHref } from "./architecture-map.model";
import {
  findingHref, findingNeedsAttention, rememberFinding, type CurrentFinding,
} from "../findings";
import { useCurrentFindings } from "../hooks/use-current-findings";
import { getLocale } from "../i18n";
import { parseResourceRefDisplay } from "../routes/detection-coverage-view";
import { formatConsoleTimestamp } from "../time-format";
import { currentRoute, routeHref, ROUTE_STATE_EVENT } from "../router";
import { Tooltip } from "./tooltip";
import { CopyButton, LoadingState, StatusPill, type PillKind } from "./ui";
import "./finding-attention.css";

const copy = {
  en: {
    title: "Findings",
    unavailable: "Finding feed unavailable",
    loading: "Loading Findings...",
    empty: "No retained Findings",
    active: "Active",
    resolved: "Recovery verified",
    incomplete: "Evidence incomplete",
    new: "New or updated Findings",
    all: "Review all Findings",
    previous: "Previous",
    next: "Next",
    retained: "retained",
    close: "Dismiss",
    detail: "Finding details",
    missing: "This Finding is not in the current projection.",
    delivery: "Additional notifications remain in this inbox when browser delivery is limited.",
    complete: "Evidence complete",
    eyebrow: "Operational finding feed",
    readonlyBoundary: "Read-only detector evidence - No cause claim - No execution authority",
    selectedNotice: "Showing single Finding notification record",
    inspectFinding: "Inspect finding",
    observationLabel: "Observed condition",
    occurredAtLabel: "Observed at",
    updatedAtLabel: "Notification updated",
    firstSeenLabel: "First observed",
    evidenceStatusLabel: "Evidence posture",
    resourceKindLabel: "Resource kind",
    currentStateLabel: "Recorded state",
    assessedByLabel: "Assessed by",
    publicationLabel: "Delivery state",
    findingIdLabel: "Finding ID",
    observationKeyLabel: "Observation key",
    observationDigestLabel: "Observation digest",
    evidenceRefsLabel: "Attached evidence references",
    gapsLabel: "Evidence gaps",
    copyFindingId: "Copy Finding ID",
    copyResourceRef: "Copy resource ID",
    openResourcesTab: "Inspect in Resources tab",
    openFindingsTab: "Open Retained Findings tab",
    openArchitecture: "Open in Architecture map",
    severity: { critical: "Critical", high: "High", medium: "Medium", low: "Low" },
    reason: { opened: "Opened", escalated: "Escalated", recovered: "Recovered" },
    signals: {
      container_restart: "Container restart",
      pod_replacement: "Pod replacement",
      rollout_replacement: "Rollout replacement",
      host_cpu: "Host CPU threshold",
      host_memory: "Host memory pressure",
      disk_pressure: "Disk pressure",
      network_drop: "Network packet drop",
      latency_spike: "Latency spike",
      error_rate: "Error rate threshold",
      resource_availability: "Resource availability",
      insufficient_evidence: "Insufficient evidence",
      conflicting_evidence: "Conflicting evidence",
    } as Readonly<Record<string, string>>,
    kinds: {
      subscription: "Subscription",
      virtual_machine: "Virtual machine",
      virtual_machine_scale_set: "Virtual machine scale set (VMSS)",
      aks_cluster: "AKS cluster",
      kubernetes_pod: "Kubernetes Pod",
      api_management: "API Management service",
      mysql_flexible_server: "MySQL Flexible Server",
      llm_endpoint: "LLM endpoint",
      application_gateway: "Application Gateway",
    } as Readonly<Record<string, string>>,
    states: {
      degraded: "Degraded",
      running: "Running",
      failed: "Failed",
      recovered: "Recovered",
      metrics_missing: "Metrics missing",
      unknown: "Unknown",
      healthy: "Healthy",
      unhealthy: "Unhealthy",
    } as Readonly<Record<string, string>>,
    publications: {
      published: "Published",
      published_receipt_unrecorded: "Broker receipt unrecorded",
      duplicate_suppressed: "Duplicate suppressed",
      reconciled_duplicate: "Reconciled duplicate",
      publish_uncertain: "Publication uncertain",
      awaiting_reconciliation: "Awaiting reconciliation",
      failed: "Publication failed",
    } as Readonly<Record<string, string>>,
  },
  ko: {
    title: "Findings",
    unavailable: "Finding 알림을 가져올 수 없습니다",
    loading: "Finding을 가져오는 중...",
    empty: "보존된 Finding이 없습니다",
    active: "미해결",
    resolved: "복구 검증됨",
    incomplete: "근거 불완전",
    new: "새로 생성되거나 갱신된 Finding",
    all: "모든 Finding 검토",
    previous: "이전",
    next: "다음",
    retained: "보존됨",
    close: "닫기",
    detail: "Finding 상세",
    missing: "현재 프로젝션에 해당 Finding이 없습니다.",
    delivery: "브라우저 알림 전송이 제한되어도 나머지 알림은 이 알림함에 남습니다.",
    complete: "근거 완전",
    eyebrow: "운영 이상 징후 피드",
    readonlyBoundary: "읽기 전용 탐지 근거 - 원인 단정 없음 - 실행 권한 없음",
    selectedNotice: "단일 Finding 알림 상세 레코드 표시 중",
    inspectFinding: "Finding 상세 보기",
    observationLabel: "관찰된 이상 징후 요약",
    occurredAtLabel: "관찰 발생 시각",
    updatedAtLabel: "알림 갱신 시각",
    firstSeenLabel: "최초 관찰 시각",
    evidenceStatusLabel: "근거 완전성",
    resourceKindLabel: "리소스 종류",
    currentStateLabel: "기록된 상태",
    assessedByLabel: "판정 에이전트",
    publicationLabel: "전달 상태",
    findingIdLabel: "Finding 식별자",
    observationKeyLabel: "관측 키",
    observationDigestLabel: "관측 다이제스트",
    evidenceRefsLabel: "첨부된 근거 참조",
    gapsLabel: "근거 공백",
    copyFindingId: "Finding ID 복사",
    copyResourceRef: "리소스 ID 복사",
    openResourcesTab: "리소스 탭에서 확인",
    openFindingsTab: "보존된 발견 사항 탭 열기",
    openArchitecture: "아키텍처 맵에서 열기",
    severity: { critical: "긴급", high: "높음", medium: "보통", low: "낮음" },
    reason: { opened: "신규 감지", escalated: "심각도 격상", recovered: "복구 감지" },
    signals: {
      container_restart: "컨테이너 재시작",
      pod_replacement: "Pod 교체",
      rollout_replacement: "롤아웃 교체",
      host_cpu: "호스트 CPU 임계값",
      host_memory: "호스트 메모리 부족",
      disk_pressure: "디스크 압박",
      network_drop: "네트워크 패킷 손실",
      latency_spike: "지연 시간 급증",
      error_rate: "오류율 임계값",
      resource_availability: "리소스 가용성",
      insufficient_evidence: "근거 부족",
      conflicting_evidence: "근거 충돌",
    } as Readonly<Record<string, string>>,
    kinds: {
      subscription: "구독 (Subscription)",
      virtual_machine: "가상 머신 (VM)",
      virtual_machine_scale_set: "가상 머신 확장 집합 (VMSS)",
      aks_cluster: "AKS 클러스터",
      kubernetes_pod: "Kubernetes Pod",
      api_management: "API Management 서비스",
      mysql_flexible_server: "MySQL 유연한 서버",
      llm_endpoint: "LLM 엔드포인트",
      application_gateway: "Application Gateway",
    } as Readonly<Record<string, string>>,
    states: {
      degraded: "성능 저하",
      running: "실행 중",
      failed: "실패",
      recovered: "복구됨",
      metrics_missing: "메트릭 누락",
      unknown: "알 수 없음",
      healthy: "정상",
      unhealthy: "비정상",
    } as Readonly<Record<string, string>>,
    publications: {
      published: "게시됨",
      published_receipt_unrecorded: "브로커 증적 미기록",
      duplicate_suppressed: "중복 억제됨",
      reconciled_duplicate: "조정된 중복",
      publish_uncertain: "게시 불확실",
      awaiting_reconciliation: "조정 대기 중",
      failed: "게시 실패",
    } as Readonly<Record<string, string>>,
  },
};

const SEVERITY_PILL: Readonly<Record<CurrentFinding["severity"], PillKind>> = {
  critical: "danger",
  high: "warning",
  medium: "info",
  low: "neutral",
};

function text() { return copy[getLocale() === "ko" ? "ko" : "en"]; }
const allFindingsHref = () => `${routeHref("detection-readiness", { params: { data: "live" } })}#current-findings`;

export function FindingAttention({
  findings, error, loading, principalId,
}: {
  readonly findings: readonly CurrentFinding[];
  readonly error: boolean;
  readonly loading: boolean;
  readonly principalId?: string | null;
}) {
  const [notice, setNotice] = useState<CurrentFinding | null>(null);
  const [noticeCount, setNoticeCount] = useState(0);
  const [storageError, setStorageError] = useState(false);
  useEffect(() => { setNotice(null); setStorageError(false); }, [principalId]);
  useEffect(() => {
    const show = () => {
      if (document.hidden || error) return;
      try {
        const unseen = findings.filter((finding) => findingNeedsAttention(finding, principalId));
        if (unseen[0]) { setNotice(unseen[0]); setNoticeCount(unseen.length); }
        for (const finding of findings) rememberFinding(finding, principalId);
        setStorageError(false);
      } catch { setStorageError(true); }
    };
    show();
    document.addEventListener("visibilitychange", show);
    return () => document.removeEventListener("visibilitychange", show);
  }, [findings, error, principalId]);
  const words = text();
  const activeCount = findings.filter((row) => row.status === "active").length;
  return (
    <div class="finding-attention">
      <Tooltip content={error || storageError ? words.unavailable : words.all}>
        <a
          class="topbar-control"
          href={allFindingsHref()}
          aria-label={`${words.title}: ${error || storageError ? words.unavailable : activeCount}`}
        >
          <span class="topbar-control-label">{words.title}</span>
          <span>{error || storageError ? "!" : loading ? "..." : activeCount}</span>
        </a>
      </Tooltip>
      {error || storageError ? <span class="sr-only" role="status">{words.unavailable}</span> : null}
      {notice ? (
        <div class="finding-toast" role="status" aria-live="polite">
          <StatusPill kind={SEVERITY_PILL[notice.severity]} label={words.severity[notice.severity]} />
          <a
            class="finding-toast-link"
            href={noticeCount > 1 ? allFindingsHref() : findingHref(notice)}
            onClick={() => setNotice(null)}
          >
            <strong>{words.new} ({noticeCount}): {words.severity[notice.severity]}</strong>
            <span class="finding-toast-meta mono">
              {parseResourceRefDisplay(notice.resource_ref).shortName} · {words.signals[notice.signal] ?? notice.signal}
            </span>
          </a>
          <button
            type="button"
            class="finding-toast-close"
            onClick={() => setNotice(null)}
            aria-label={words.close}
          >
            X
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function CurrentFindings({ client, enabled = true }: {
  readonly client: OperatorApiClient;
  readonly enabled?: boolean;
}) {
  const { findings, error, loading } = useCurrentFindings(client, enabled);
  const [page, setPage] = useState(0);
  const words = text();
  const [selected, setSelected] = useState(() => currentRoute().search.get("finding"));
  useEffect(() => {
    const sync = () => {
      setSelected(currentRoute().search.get("finding"));
      setPage(0);
    };
    window.addEventListener("fdai:route-changed", sync);
    window.addEventListener(ROUTE_STATE_EVENT, sync);
    window.addEventListener("popstate", sync);
    return () => {
      window.removeEventListener("fdai:route-changed", sync);
      window.removeEventListener(ROUTE_STATE_EVENT, sync);
      window.removeEventListener("popstate", sync);
    };
  }, []);
  const rows = selected ? findings.filter((row) => row.finding_id === selected) : findings;
  const offset = Math.min(page * 20, Math.max(Math.ceil(rows.length / 20) - 1, 0) * 20);
  if (!enabled) return null;
  const activeCount = rows.filter((row) => row.status === "active").length;
  const resolvedCount = rows.filter((row) => row.status === "resolved").length;
  const highOrCriticalCount = rows.filter(
    (row) => row.severity === "critical" || row.severity === "high",
  ).length;
  return (
    <section id="current-findings" class="stack current-findings" aria-label={words.title}>
      <div class="current-findings-head">
        <div class="current-findings-title-group">
          <div class="current-findings-eyebrow-row">
            <span class="current-findings-eyebrow">{words.eyebrow}</span>
            <span class="current-findings-boundary">{words.readonlyBoundary}</span>
          </div>
          <h2>{selected ? words.detail : words.title}</h2>
          {!loading && !error ? (
            <p class="current-findings-subtitle">
              {rows.length} {words.retained}. {words.delivery}
            </p>
          ) : null}
        </div>
        {!loading && !error && rows.length > 0 ? (
          <div class="current-findings-summary-pills" aria-hidden="true">
            <StatusPill
              kind={activeCount > 0 ? "warning" : "success"}
              label={`${words.active} ${activeCount}`}
            />
            {resolvedCount > 0 ? (
              <StatusPill kind="success" label={`${words.resolved} ${resolvedCount}`} />
            ) : null}
            {highOrCriticalCount > 0 ? (
              <StatusPill kind="danger" label={`${words.severity.high}+ ${highOrCriticalCount}`} />
            ) : null}
          </div>
        ) : null}
      </div>
      {selected ? (
        <div class="current-findings-selected-banner">
          <span class="muted small">{words.selectedNotice}</span>
          <code class="mono small">{selected.slice(0, 16)}...</code>
        </div>
      ) : null}
      {error ? <p role="alert" class="state-block state-error">{words.unavailable}</p> : null}
      {loading ? <LoadingState label={words.loading} /> : null}
      {!loading && !error && rows.length === 0 ? (
        <p class="state-block state-unavailable">{selected ? words.missing : words.empty}</p>
      ) : null}
      <ul class="finding-list current-findings-list">
        {rows.slice(offset, offset + 20).map((finding) => {
          const parsedRef = parseResourceRefDisplay(finding.resource_ref);
          const signalName = words.signals[finding.signal] ?? finding.signal;
          const kindName = words.kinds[finding.resource_kind] ?? finding.resource_kind;
          const stateName = finding.current_state
            ? (words.states[finding.current_state] ?? finding.current_state)
            : (finding.status === "resolved" ? words.resolved : words.active);
          const publicationName = finding.publication
            ? (words.publications[finding.publication] ?? finding.publication)
            : null;
          return (
            <li
              key={finding.finding_id}
              class={`finding-card-item is-severity-${finding.severity} is-status-${finding.status}`}
            >
              <a class="finding-card-link" href={findingHref(finding)}>
                <span class="finding-card-link-main">
                  <span class="finding-card-short-title">
                    {parsedRef.shortName} · {signalName}
                  </span>
                  <span class="finding-card-raw-id mono">
                    {finding.resource_ref} / {finding.signal}
                  </span>
                </span>
                <span class="finding-card-cta">{words.inspectFinding}</span>
              </a>
              <div class="finding-card-badges">
                <StatusPill
                  kind={finding.status === "resolved" ? "success" : "warning"}
                  label={finding.status === "resolved" ? words.resolved : words.active}
                />
                <StatusPill
                  kind={SEVERITY_PILL[finding.severity]}
                  label={words.severity[finding.severity]}
                />
                <StatusPill
                  kind={finding.evidence_complete ? "success" : "warning"}
                  label={finding.evidence_complete ? words.complete : words.incomplete}
                />
                <StatusPill
                  kind="neutral"
                  label={`${words.reason[finding.notification_reason]} (v${finding.notification_version})`}
                />
                <span class="finding-kind-chip">{kindName}</span>
                <strong class="sr-only">
                  {finding.status === "resolved" ? words.resolved : words.active} - {words.severity[finding.severity]}
                </strong>
              </div>
              <div class="finding-observation-box">
                <span class="finding-observation-label">{words.observationLabel}</span>
                <p class="finding-observation-text">{finding.observation}</p>
              </div>
              <div class="finding-facts-grid">
                <div class="finding-fact-cell">
                  <span class="finding-fact-label">{words.occurredAtLabel}</span>
                  <p class="finding-fact-value">
                    {formatConsoleTimestamp(finding.occurred_at)} - {finding.evidence_complete ? words.complete : words.incomplete}
                  </p>
                </div>
                <div class="finding-fact-cell">
                  <span class="finding-fact-label">{words.updatedAtLabel}</span>
                  <span class="finding-fact-value">
                    {formatConsoleTimestamp(finding.notification_changed_at)}
                  </span>
                </div>
                <div class="finding-fact-cell">
                  <span class="finding-fact-label">{words.currentStateLabel}</span>
                  <span class="finding-fact-value">
                    {stateName}
                    {finding.current_state && stateName !== finding.current_state ? (
                      <code class="mono finding-inline-code">{finding.current_state}</code>
                    ) : null}
                  </span>
                </div>
                <div class="finding-fact-cell">
                  <span class="finding-fact-label">{words.assessedByLabel}</span>
                  <span class="finding-fact-value">
                    {finding.assessed_by ?? "Heimdall"}
                    {publicationName ? ` · ${publicationName}` : ""}
                  </span>
                </div>
              </div>
              {finding.evidence_gaps.length ? (
                <div class="finding-gaps-box">
                  <span class="finding-fact-label">{words.gapsLabel}</span>
                  <p>{finding.evidence_gaps.join(", ")}</p>
                </div>
              ) : null}
              <details class="finding-details-disclosure">
                <summary>{words.detail}</summary>
                <div class="finding-details-body">
                  <div class="finding-details-meta-grid">
                    <div>
                      <span class="finding-fact-label">{words.findingIdLabel}</span>
                      <span class="finding-fact-value mono">{finding.finding_id}</span>
                    </div>
                    <div>
                      <span class="finding-fact-label">{words.resourceKindLabel}</span>
                      <span class="finding-fact-value">
                        {kindName} <code class="mono finding-inline-code">{finding.resource_kind}</code>
                      </span>
                    </div>
                    {finding.first_seen_at ? (
                      <div>
                        <span class="finding-fact-label">{words.firstSeenLabel}</span>
                        <span class="finding-fact-value">{formatConsoleTimestamp(finding.first_seen_at)}</span>
                      </div>
                    ) : null}
                    {finding.observation_key ? (
                      <div>
                        <span class="finding-fact-label">{words.observationKeyLabel}</span>
                        <span class="finding-fact-value mono">{finding.observation_key}</span>
                      </div>
                    ) : null}
                    {finding.observation_digest ? (
                      <div>
                        <span class="finding-fact-label">{words.observationDigestLabel}</span>
                        <span class="finding-fact-value mono">{finding.observation_digest}</span>
                      </div>
                    ) : null}
                  </div>
                  <div class="finding-evidence-section">
                    <span class="finding-fact-label">{words.evidenceRefsLabel}</span>
                    <ul class="finding-evidence-list">
                      {finding.evidence_refs.map((reference) => (
                        <li key={reference} class="mono finding-evidence-chip">{reference}</li>
                      ))}
                    </ul>
                  </div>
                  <div class="finding-detail-actions">
                    <CopyButton text={finding.finding_id} label={words.copyFindingId} />
                    <CopyButton text={finding.resource_ref} label={words.copyResourceRef} />
                    <a
                      class="btn secondary btn-sm"
                      href={`${routeHref("detection-readiness", { params: { data: "live", resource: finding.resource_ref } })}#detection-resources`}
                    >
                      {words.openResourcesTab}
                    </a>
                    <a
                      class="btn secondary btn-sm"
                      href={architectureHref(finding.resource_ref)}
                    >
                      {words.openArchitecture}
                    </a>
                  </div>
                </div>
              </details>
            </li>
          );
        })}
      </ul>
      {rows.length > 20 ? (
        <nav class="current-findings-pager" aria-label={words.title}>
          <button
            type="button"
            class="btn secondary"
            disabled={offset === 0}
            onClick={() => setPage(Math.max(page - 1, 0))}
          >
            {words.previous}
          </button>
          <span class="muted small">
            {offset + 1}-{Math.min(offset + 20, rows.length)} / {rows.length}
          </span>
          <button
            type="button"
            class="btn secondary"
            disabled={offset + 20 >= rows.length}
            onClick={() => setPage(page + 1)}
          >
            {words.next}
          </button>
        </nav>
      ) : null}
      {selected ? (
        <div class="current-findings-footer">
          <a class="btn secondary btn-sm" href={allFindingsHref()}>{words.all}</a>
          <a
            class="btn secondary btn-sm"
            href={`${routeHref("detection-readiness", { params: { data: "live" } })}#detection-findings`}
          >
            {words.openFindingsTab}
          </a>
        </div>
      ) : null}
    </section>
  );
}
