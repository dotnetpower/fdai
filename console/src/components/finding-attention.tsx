import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  findingHref, findingNeedsAttention, rememberFinding, type CurrentFinding,
} from "../findings";
import { useCurrentFindings } from "../hooks/use-current-findings";
import { getLocale } from "../i18n";
import { formatConsoleTimestamp } from "../time-format";
import { currentRoute, routeHref, ROUTE_STATE_EVENT } from "../router";
import { Tooltip } from "./tooltip";
import { LoadingState } from "./ui";
import "./finding-attention.css";

const copy = {
  en: {
    title: "Findings", unavailable: "Finding feed unavailable", loading: "Loading Findings...",
    empty: "No retained Findings", active: "Active", resolved: "Recovery verified",
    incomplete: "Evidence incomplete", new: "New or updated Findings", all: "Review all Findings",
    previous: "Previous", next: "Next", retained: "retained", close: "Dismiss",
    detail: "Finding details", missing: "This Finding is not in the current projection.",
    delivery: "Additional notifications remain in this inbox when browser delivery is limited.",
    complete: "Evidence complete",
    severity: { critical: "Critical", high: "High", medium: "Medium", low: "Low" },
  },
  ko: {
    title: "Findings", unavailable: "Finding 알림을 가져올 수 없습니다", loading: "Finding을 가져오는 중...",
    empty: "보존된 Finding이 없습니다", active: "미해결", resolved: "복구 검증됨",
    incomplete: "근거 불완전", new: "새로 생성되거나 갱신된 Finding", all: "모든 Finding 검토",
    previous: "이전", next: "다음", retained: "보존됨", close: "닫기",
    detail: "Finding 상세", missing: "현재 프로젝션에 해당 Finding이 없습니다.",
    delivery: "브라우저 알림 전송이 제한되어도 나머지 알림은 이 알림함에 남습니다.",
    complete: "근거 완전",
    severity: { critical: "긴급", high: "높음", medium: "보통", low: "낮음" },
  },
};

function text() { return copy[getLocale() === "ko" ? "ko" : "en"]; }
const allFindingsHref = () => routeHref("detection-readiness", { params: { data: "live" } });

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
  return (
    <div class="finding-attention">
      <Tooltip content={error || storageError ? words.unavailable : words.all}>
      <a class="topbar-control" href={allFindingsHref()}
        aria-label={`${words.title}: ${error || storageError ? words.unavailable : findings.filter((row) => row.status === "active").length}`}>
        <span class="topbar-control-label">{words.title}</span>
        <span>{error || storageError ? "!" : loading ? "..." : findings.filter((row) => row.status === "active").length}</span>
      </a>
      </Tooltip>
      {error || storageError ? <span class="sr-only" role="status">{words.unavailable}</span> : null}
      {notice ? (
        <div class="finding-toast" role="status" aria-live="polite">
          <a href={noticeCount > 1 ? allFindingsHref() : findingHref(notice)}
            onClick={() => setNotice(null)}>
            {words.new} ({noticeCount}): {words.severity[notice.severity]}
          </a>
          <button type="button" onClick={() => setNotice(null)} aria-label={words.close}>X</button>
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
  return (
    <section class="stack current-findings" aria-label={words.title}>
      <h2>{selected ? words.detail : words.title}</h2>
      {error ? <p role="alert">{words.unavailable}</p> : null}
      {loading ? <LoadingState label={words.loading} /> : null}
      {!loading && !error && rows.length === 0 ? <p>{selected ? words.missing : words.empty}</p> : null}
      {!loading && !error ? <p>{rows.length} {words.retained}. {words.delivery}</p> : null}
      <ul class="finding-list">
        {rows.slice(offset, offset + 20).map((finding) => (
          <li key={finding.finding_id}>
            <a href={findingHref(finding)}>{finding.resource_ref} / {finding.signal}</a>
            <strong>{finding.status === "resolved" ? words.resolved : words.active} - {words.severity[finding.severity]}</strong>
            <p>{finding.observation}</p>
            <p>{formatConsoleTimestamp(finding.occurred_at)} - {finding.evidence_complete ? words.complete : words.incomplete}</p>
            {finding.evidence_gaps.length ? <p>{finding.evidence_gaps.join(", ")}</p> : null}
            <details><summary>{words.detail}</summary>
              <ul>{finding.evidence_refs.map((reference) => <li key={reference}>{reference}</li>)}</ul>
            </details>
          </li>
        ))}
      </ul>
      {rows.length > 20 ? <nav aria-label={words.title}>
        <button type="button" disabled={offset === 0} onClick={() => setPage(Math.max(page - 1, 0))}>{words.previous}</button>
        <span> {offset + 1}-{Math.min(offset + 20, rows.length)} / {rows.length} </span>
        <button type="button" disabled={offset + 20 >= rows.length} onClick={() => setPage(page + 1)}>{words.next}</button>
      </nav> : null}
      {selected ? <a href={allFindingsHref()}>{words.all}</a> : null}
    </section>
  );
}
