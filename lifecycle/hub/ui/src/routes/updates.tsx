import { useState } from "preact/hooks";
import {
  hubApi, type IntegrityState, type UpdateCandidate, type UpdateCheckRecord, type UpdateStatus,
} from "../api";
import { AsyncBoundary } from "../components/async-boundary";
import { Badge } from "../components/badge";
import { CatalogSourceBoundary } from "../components/catalog-source-boundary";
import { Link } from "../components/link";
import { formatRelative, formatTimestamp } from "../format";
import { useAsync } from "../hooks/use-async";
import { tr, useHubLocale } from "../locale";
import {
  canApply, describeActionError, describeDetail, describeIntegrity, describePlanOutcome,
  describeSchedule, describeVersions, hasUrgentRecall, isTimestampExpired, outcomeBadge, shortDigest,
  summarizeChange,
} from "../update-status";

type Notice = { kind: "error" | "info"; message: string };

function Digest({ sha256 }: { sha256: string }) {
  return <span class="mono" title={sha256}>{shortDigest(sha256)}</span>;
}

function Expiry({ iso }: { iso: string }) {
  const [locale] = useHubLocale();
  return <>{formatRelative(iso, new Date(), locale)} ({formatTimestamp(iso, undefined, locale)})</>;
}

function Integrity({ state }: { state: IntegrityState }) {
  const [locale] = useHubLocale();
  const last = state.last;
  const view = last ? describeIntegrity(last, locale) : null;
  // A persisted expiry is judged now, so an old check cannot make stale metadata look fresh.
  const staleNow = isTimestampExpired(state) && view?.badge.variant === "ok";
  const badge = staleNow
    ? { label: tr(locale, "Timestamp expired", "타임스탬프 만료됨"), variant: "warn" as const }
    : view?.badge ?? { label: tr(locale, "Not checked yet", "아직 확인되지 않음"), variant: "mute" as const };
  const lines = staleNow
    ? [tr(
        locale,
        "The signed timestamp has expired. Only recall roll-off Plans are issued until fresh metadata arrives.",
        "서명된 타임스탬프가 만료되었습니다. 새 메타데이터가 도착할 때까지 회수 롤오프 계획만 발급됩니다.",
      )]
    : view && view.badge.variant !== "ok" ? view.lines : [];
  return <>
    <Badge variant={badge.variant}>{badge.label}</Badge>
    <p class="note">{describeVersions(state, locale)}.
      {state.timestamp_expires_at
        ? <> {tr(locale, "Timestamp expires", "타임스탬프 만료:")} <Expiry iso={state.timestamp_expires_at} />.</> : null}</p>
    {lines.map(line => <p class="note" key={line}>{line}</p>)}
  </>;
}

function CheckSummary({ record }: { record: UpdateCheckRecord }) {
  const [locale] = useHubLocale();
  const badge = outcomeBadge(record.outcome, locale);
  // The candidate panel below lists the reasons, so the summary does not repeat them.
  const lines = record.outcome === "review_required" && record.candidate
    ? [tr(locale, "A new catalog is waiting for your review.", "새 카탈로그가 운영자 검토를 기다리고 있습니다.")]
    : describeDetail(record.outcome, record.detail, locale);
  const integrity = record.outcome === "failed" && record.integrity && !record.integrity.verified
    ? describeIntegrity(record.integrity, locale).lines : [];
  return <>
    <span>{formatTimestamp(record.checked_at, undefined, locale)} <Badge variant={badge.variant}>{badge.label}</Badge></span>
    {lines.length === 1
      ? <p class="note">{lines[0]}</p>
      : <ul class="update-list">{lines.map(line => <li key={line}>{line}</li>)}</ul>}
    {integrity.map(line => <p class="note" key={line}>{line}</p>)}
  </>;
}

function Summary({ status }: { status: UpdateStatus }) {
  const [locale] = useHubLocale();
  const { accepted, last_check: check, authorization } = status;
  return <section class="kv update-kv" aria-label={tr(locale, "Update status", "업데이트 상태")}>
    <div>
      <div class="k">{tr(locale, "Accepted catalog", "수락된 카탈로그")}</div>
      <div class="v small">{accepted
        ? <>{tr(locale, "Revision", "개정 번호")} {accepted.revision}, <Digest sha256={accepted.sha256} />, {accepted.release_count}{" "}
          {locale === "ko" ? "개 릴리스" : accepted.release_count === 1 ? "release" : "releases"}<br />
          {tr(locale, "Expires", "만료:")} <Expiry iso={accepted.expires_at} /></>
        : tr(locale, "No catalog accepted yet", "아직 수락된 카탈로그가 없습니다")}</div>
    </div>
    <div>
      <div class="k">{tr(locale, "Last check", "최근 확인")}</div>
      <div class="v small">{check ? <CheckSummary record={check} /> : tr(locale, "No check has run yet", "아직 확인을 실행하지 않았습니다")}</div>
    </div>
    {status.integrity && <div>
      <div class="k">{tr(locale, "Catalog integrity", "카탈로그 무결성")}</div>
      <div class="v small"><Integrity state={status.integrity} /></div>
    </div>}
    {status.mode === "auto" && <div>
      <div class="k">{tr(locale, "Standing authorization", "사전 승인")}</div>
      <div class="v small">{authorization
        ? <>{authorization.authorized_by}, {tr(locale, "expires", "만료:")} <Expiry iso={authorization.expires_at} />{" "}
          <Badge variant={authorization.valid ? "ok" : "fail"}>
            {authorization.valid ? tr(locale, "Valid", "유효") : tr(locale, "Expired", "만료됨")}
          </Badge></>
        : <Badge variant="warn">{tr(locale, "Missing", "없음")}</Badge>}</div>
    </div>}
  </section>;
}

function ChangeSummary({ candidate }: { candidate: UpdateCandidate }) {
  const [locale] = useHubLocale();
  const sections = summarizeChange(candidate.change, locale);
  if (sections.length === 0) {
    return <p class="note">{tr(
      locale,
      "No release or channel differences from the accepted catalog.",
      "수락된 카탈로그와 비교해 릴리스 또는 채널 차이가 없습니다.",
    )}</p>;
  }
  return <dl class="update-change">
    {sections.map(section => <div key={section.label}>
      <dt>{section.label}</dt>
      <dd><ul class="update-list">{section.items.map(item => <li key={item}>{item}</li>)}</ul></dd>
    </div>)}
  </dl>;
}

function CandidatePanel({ record, busy, onApply }: {
  record: UpdateCheckRecord; busy: boolean; onApply: (candidate: UpdateCandidate) => void;
}) {
  const [locale] = useHubLocale();
  const candidate = record.candidate!;
  const reasons = describeDetail(record.outcome, record.detail, locale);
  return <section class="catalog-panel" aria-label={tr(locale, "Candidate catalog", "후보 카탈로그")}>
    <h2 class="panel-title">{tr(locale, "Candidate catalog", "후보 카탈로그")}
      <Badge variant={candidate.signature_verified ? "ok" : "fail"}>
        {candidate.signature_verified
          ? tr(locale, "Signature verified", "서명 검증됨")
          : tr(locale, "Signature not verified", "서명 미검증")}
      </Badge></h2>
    {hasUrgentRecall(candidate.change) && <div class="banner fail" role="alert">
      <strong>{tr(locale, "Urgent: this catalog adds recalls", "긴급: 이 카탈로그에 회수 공지가 추가되었습니다")}</strong>
      <span>{locale === "ko"
        ? `회수 공지 ${candidate.change.new_recalls.length}건이 추가되었습니다. 아래 내용을 확인하세요.`
        : `${candidate.change.new_recalls.length === 1
          ? "A release or capability has been recalled."
          : `${candidate.change.new_recalls.length} recalls have been added.`} Review them below.`}</span>
    </div>}
    <dl class="catalog-trust">
      <dt>{tr(locale, "Revision", "개정 번호")}</dt><dd>{candidate.revision}</dd>
      <dt>{tr(locale, "Digest", "다이제스트")}</dt><dd><Digest sha256={candidate.sha256} /></dd>
      <dt>{tr(locale, "Expires", "만료 시각")}</dt><dd><Expiry iso={candidate.expires_at} /></dd>
      <dt>{tr(locale, "Signature verified", "서명 검증 여부")}</dt><dd>{candidate.signature_verified
        ? `${tr(locale, "Yes", "예")}${candidate.key_id ? ` (${tr(locale, "key", "키")} ${candidate.key_id})` : ""}`
        : tr(locale, "No", "아니오")}</dd>
    </dl>
    {candidate.integrity && <CandidateIntegrity candidate={candidate} />}
    <h3 class="update-subtitle">{tr(locale, "Why a review is needed", "검토가 필요한 이유")}</h3>
    <ul class="update-list">{reasons.map(line => <li key={line}>{line}</li>)}</ul>
    <h3 class="update-subtitle">{tr(locale, "What changes", "변경 사항")}</h3>
    <ChangeSummary candidate={candidate} />
    {canApply(record)
      ? <div class="acts">
        <button type="button" class="btn primary" disabled={busy} onClick={() => onApply(candidate)}>
          {tr(locale, "Review and apply", "검토 및 적용")}
        </button>
      </div>
      : candidate.signature_verified
        ? <p class="note" role="note">{tr(
            locale,
            "This candidate cannot be applied now because the vendor's signed timestamp has expired. Only recall changes are accepted until fresh metadata arrives.",
            "공급자의 서명된 타임스탬프가 만료되어 지금 이 후보를 적용할 수 없습니다. 새 메타데이터가 도착할 때까지 회수 변경만 허용됩니다.",
          )}</p>
        : <p class="note" role="note">{locale === "ko"
            ? <>서명을 검증할 수 없어 이 화면에서 후보를 적용할 수 없습니다. 미서명 또는 오프라인 내보내기는 <Link href="/catalog">카탈로그 가져오기</Link> 화면을 사용하세요.</>
            : <>This candidate cannot be applied here because its signature could not be verified. For an unsigned or offline export, use the <Link href="/catalog">Catalog import</Link> page.</>}</p>}
  </section>;
}

function CandidateIntegrity({ candidate }: { candidate: UpdateCandidate }) {
  const [locale] = useHubLocale();
  const integrity = candidate.integrity!;
  const view = describeIntegrity(integrity, locale);
  return <>
    {(integrity.expired || integrity.root_rotation) && <div class="banner" role="alert">
      <strong>{view.badge.label}</strong>
      <span>{view.lines[0]}</span>
    </div>}
    <dl class="catalog-trust" aria-label={tr(locale, "Catalog roles", "카탈로그 역할")}>
      <dt>{tr(locale, "Catalog roles", "카탈로그 역할")}</dt><dd><Badge variant={view.badge.variant}>{view.badge.label}</Badge></dd>
      <dt>{tr(locale, "Root", "루트")}</dt><dd>{integrity.root ? `v${integrity.root.version}` : tr(locale, "None", "없음")}
        {integrity.root_rotation ? ` (${tr(locale, "was", "이전")} v${integrity.previous_root_version})` : ""}</dd>
      <dt>{tr(locale, "Snapshot", "스냅샷")}</dt><dd>{integrity.snapshot ? `v${integrity.snapshot.version}` : tr(locale, "None", "없음")}</dd>
      <dt>{tr(locale, "Timestamp", "타임스탬프")}</dt><dd>{integrity.timestamp
        ? <>v{integrity.timestamp.version}, {tr(locale, "expires", "만료:")} <Expiry iso={integrity.timestamp.expires_at} /></>
        : tr(locale, "None", "없음")}</dd>
    </dl>
  </>;
}

function PlanResults({ record }: { record: UpdateCheckRecord }) {
  const [locale] = useHubLocale();
  return <section class="catalog-panel" aria-label={tr(locale, "Plan results", "계획 평가 결과")}>
    <h2 class="panel-title">{tr(locale, "Plans after adoption", "채택 후 계획 평가 결과")}</h2>
    {record.plans.length === 0
      ? <p class="note">{tr(locale, "No installation produced a Plan result.", "계획 결과를 생성한 설치 환경이 없습니다.")}</p>
      : <div class="table-scroll"><table class="t">
        <caption>{tr(locale, "Plan result per installation", "설치 환경별 계획 평가 결과")}</caption>
        <thead><tr><th>{tr(locale, "Installation", "설치 환경")}</th><th>{tr(locale, "Outcome", "결과")}</th></tr></thead>
        <tbody>{record.plans.map(plan => <tr key={plan.installation_id}>
          <td>{plan.installation_id}</td>
          <td>{describePlanOutcome(plan.outcome, locale)}{plan.reason ? ` (${plan.reason})` : ""}</td>
        </tr>)}</tbody>
      </table></div>}
    <p class="note">{tr(
      locale,
      "Issuing a Plan never applies it. Each installation applies a Plan only inside its own maintenance window and constraints.",
      "계획 발급만으로 즉시 적용되지는 않습니다. 각 설치 환경은 자체 유지보수 구간과 제약 조건 내에서만 계획을 적용합니다.",
    )}</p>
  </section>;
}

function Events({ status }: { status: UpdateStatus }) {
  const [locale] = useHubLocale();
  return <section aria-label={tr(locale, "Recent update events", "최근 업데이트 이벤트")}>
    <h2 class="panel-title">{tr(locale, "Recent events", "최근 이벤트")}</h2>
    {status.events.length === 0
      ? <p class="empty">{tr(locale, "No update events recorded yet.", "아직 기록된 업데이트 이벤트가 없습니다.")}</p>
      : <div class="table-scroll"><table class="t">
        <caption>{tr(locale, "Recent update events, newest first", "최근 업데이트 이벤트 (최신순)")}</caption>
        <thead><tr>
          <th>{tr(locale, "Time", "시각")}</th>
          <th>{tr(locale, "Action", "작업")}</th>
          <th>{tr(locale, "Actor", "수행 주체")}</th>
          <th>{tr(locale, "Revision", "개정 번호")}</th>
          <th>{tr(locale, "Digest", "다이제스트")}</th>
        </tr></thead>
        <tbody>{status.events.map(event => <tr key={`${event.recorded_at}/${event.action}/${event.sha256}`}>
          <td>{formatTimestamp(event.recorded_at, undefined, locale)}</td><td>{event.action}</td><td>{event.actor}</td>
          <td>{event.revision}</td><td><Digest sha256={event.sha256} /></td>
        </tr>)}</tbody>
      </table></div>}
  </section>;
}

export function UpdatesPage() {
  const [locale] = useHubLocale();
  return <CatalogSourceBoundary title={tr(locale, "Updates", "업데이트")}><TrustedUpdatesPage /></CatalogSourceBoundary>;
}

function TrustedUpdatesPage() {
  const [locale] = useHubLocale();
  const status = useAsync(() => hubApi.getUpdateStatus(), []);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [adopted, setAdopted] = useState<UpdateCheckRecord | null>(null);

  async function run(action: () => Promise<UpdateCheckRecord>) {
    if (busy) return;
    setBusy(true);
    setNotice(null);
    setAdopted(null);
    try {
      const record = await action();
      if (record.outcome === "adopted") setAdopted(record);
    } catch (error) {
      setNotice({ kind: "error", message: describeActionError(error, locale).message });
    } finally {
      setBusy(false);
      status.reload();
    }
  }

  const loading = status.status === "loading";
  const sentence = status.status === "ready" ? describeSchedule(status.data, locale) : "";
  return <div class="catalog-page updates-page">
    <div class="m-head">
      <div>
        <h1>{tr(locale, "Updates", "업데이트")}</h1>
        <p class="sub">{sentence || tr(locale, "Keeps the Hub on the latest vendor Release.", "Hub를 최신 공급자 릴리스 상태로 유지합니다.")}</p>
      </div>
      <div class="acts">
        <button type="button" class="btn primary" disabled={loading || busy}
          aria-busy={busy}
          onClick={() => void run(() => hubApi.checkForUpdates())}>
          {tr(locale, "Check now", "지금 확인")}
        </button>
      </div>
    </div>
    {notice && <p class={`banner ${notice.kind === "error" ? "fail" : ""}`}
      role={notice.kind === "error" ? "alert" : "status"}>{notice.message}</p>}
    {adopted && <div class="banner" role="status">
      <strong>{tr(locale, "The new catalog was adopted.", "새 카탈로그가 채택되었습니다.")}</strong>
      <span>{adopted.candidate
        ? tr(
            locale,
            `Revision ${adopted.candidate.revision} is now the accepted catalog.`,
            `개정 번호 ${adopted.candidate.revision}이(가) 수락된 카탈로그로 설정되었습니다.`,
          )
        : tr(locale, "It is now the accepted catalog.", "수락된 카탈로그로 설정되었습니다.")}</span>
    </div>}
    <AsyncBoundary state={status}>
      {(data) => {
        const record = data.last_check;
        const plansRecord = adopted ?? (record?.outcome === "adopted" ? record : null);
        return <>
          <Summary status={data} />
          {record?.outcome === "review_required" && record.candidate &&
            <CandidatePanel record={record} busy={busy}
              onApply={candidate => void run(() => hubApi.applyUpdate(candidate.revision, candidate.sha256))} />}
          {plansRecord && <PlanResults record={plansRecord} />}
          <Events status={data} />
        </>;
      }}
    </AsyncBoundary>
  </div>;
}
