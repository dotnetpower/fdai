import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { markInboxSeen, unseenInboxItems } from "../console-inbox";
import { useConsoleInbox } from "../hooks/use-console-inbox";
import { getLocale } from "../i18n";
import { ROUTE_STATE_EVENT, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { Tooltip } from "./tooltip";
import { CopyButton, LoadingState, StatusPill, type PillKind } from "./ui";

const INBOX_PAGE_SIZE = 5;

const copy = {
  en: {
    title: "Alerts", unavailable: "Alert inbox unavailable", loading: "Loading alerts...",
    empty: "No retained operational alerts", retained: "retained",
    note: "Operational alerts are recorded here even when no external channel is bound.",
    showAlerts: "Show retained operational alerts",
    previous: "Previous", next: "Next",
    filterAll: "All",
    searchPlaceholder: "Filter alerts by title, body, or correlation ID",
    clearFilter: "Clear filter",
    correlationLabel: "Correlation",
    openTrace: "Open trace",
    openAudit: "Open audit",
    categories: {
      operational_alert: "Operational alert",
      security_alert: "Security alert",
      governance_alert: "Governance alert",
    } as Readonly<Record<string, string>>,
    severity: { info: "Info", warn: "Warning", error: "Error", critical: "Critical" },
  },
  ko: {
    title: "알림", unavailable: "알림함을 가져올 수 없습니다", loading: "알림을 가져오는 중...",
    empty: "보존된 운영 알림이 없습니다", retained: "보존됨",
    note: "외부 채널이 연결되지 않아도 운영 알림은 이곳에 기록됩니다.",
    showAlerts: "보존된 운영 알림 펼치기",
    previous: "이전", next: "다음",
    filterAll: "전체",
    searchPlaceholder: "제목, 본문 또는 상관 ID로 알림 필터",
    clearFilter: "필터 지우기",
    correlationLabel: "상관 ID",
    openTrace: "추적 열기",
    openAudit: "감사 열기",
    categories: {
      operational_alert: "운영 알림",
      security_alert: "보안 알림",
      governance_alert: "거버넌스 알림",
    } as Readonly<Record<string, string>>,
    severity: { info: "정보", warn: "경고", error: "오류", critical: "긴급" },
  },
};

const SEVERITY_PILL: Readonly<Record<"info" | "warn" | "error" | "critical", PillKind>> = {
  info: "info",
  warn: "warning",
  error: "danger",
  critical: "danger",
};

function formatAlertBody(body: string): ComponentChildren {
  const parts = body.split(/(`[^`]+`)/g);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      const token = part.slice(1, -1);
      const compact = /^sha256:[0-9a-f]{24,}$/i.test(token)
        ? `${token.slice(0, 15)}...${token.slice(-8)}`
        : token;
      const codeEl = (
        <code key={index} class="mono inbox-code-chip">
          {compact}
        </code>
      );
      return token !== compact ? (
        <Tooltip key={index} content={token}>
          {codeEl}
        </Tooltip>
      ) : codeEl;
    }
    return part;
  });
}

const inboxHref = () => `${routeHref("detection-readiness", { params: { data: "live" } })}#console-inbox`;

export function ConsoleInboxAttention({ client }: { readonly client: OperatorApiClient }) {
  const { items, error, loading } = useConsoleInbox(client);
  const { title, unavailable } = copy[getLocale() === "ko" ? "ko" : "en"];
  const unseen = error ? 0 : unseenInboxItems(items).length;
  return (
    <Tooltip content={error ? unavailable : title}>
      <a class="topbar-control" href={inboxHref()}
        aria-label={`${title}: ${error ? unavailable : unseen}`}>
        <span class="topbar-control-label">{title}</span>
        <span>{error ? "!" : loading ? "..." : unseen}</span>
      </a>
    </Tooltip>
  );
}

export function ConsoleInbox({ client, enabled = true }: {
  readonly client: OperatorApiClient;
  readonly enabled?: boolean;
}) {
  const { items, error, loading } = useConsoleInbox(client, enabled);
  const [page, setPage] = useState(0);
  const [severityFilter, setSeverityFilter] = useState<"all" | "error" | "warn" | "info">("all");
  const [query, setQuery] = useState("");
  const [targeted, setTargeted] = useState(
    () => typeof window !== "undefined" && window.location.hash === "#console-inbox",
  );
  const words = copy[getLocale() === "ko" ? "ko" : "en"];
  useEffect(() => {
    if (!loading && !error) markInboxSeen(items);
  }, [items, loading, error]);
  useEffect(() => {
    const syncHash = () => {
      setTargeted(window.location.hash === "#console-inbox");
    };
    window.addEventListener("hashchange", syncHash);
    window.addEventListener("popstate", syncHash);
    window.addEventListener("fdai:route-changed", syncHash);
    window.addEventListener(ROUTE_STATE_EVENT, syncHash);
    return () => {
      window.removeEventListener("hashchange", syncHash);
      window.removeEventListener("popstate", syncHash);
      window.removeEventListener("fdai:route-changed", syncHash);
      window.removeEventListener(ROUTE_STATE_EVENT, syncHash);
    };
  }, []);
  if (!enabled) return null;
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filteredItems = items.filter((item) => {
    if (severityFilter === "error" && item.severity !== "error" && item.severity !== "critical") {
      return false;
    }
    if (severityFilter === "warn" && item.severity !== "warn") return false;
    if (severityFilter === "info" && item.severity !== "info") return false;
    if (!normalizedQuery) return true;
    return [item.title, item.body, item.correlation_id, item.category]
      .some((value) => value.toLocaleLowerCase().includes(normalizedQuery));
  });
  const errorOrCriticalCount = items.filter(
    (item) => item.severity === "error" || item.severity === "critical",
  ).length;
  const warnCount = items.filter((item) => item.severity === "warn").length;
  const infoCount = items.filter((item) => item.severity === "info").length;
  const maxPage = Math.max(Math.ceil(filteredItems.length / INBOX_PAGE_SIZE) - 1, 0);
  const safePage = Math.min(page, maxPage);
  const offset = safePage * INBOX_PAGE_SIZE;
  const visibleItems = filteredItems.slice(offset, offset + INBOX_PAGE_SIZE);
  const listContent = (
    <>
      {items.length > INBOX_PAGE_SIZE ? (
        <div class="current-findings-filterbar" role="group" aria-label={words.title}>
          <div class="governance-chipset">
            <button
              type="button"
              class={severityFilter === "all" ? "is-active" : undefined}
              onClick={() => { setSeverityFilter("all"); setPage(0); }}
            >
              {words.filterAll} ({items.length})
            </button>
            {errorOrCriticalCount > 0 ? (
              <button
                type="button"
                class={severityFilter === "error" ? "is-active" : undefined}
                onClick={() => { setSeverityFilter("error"); setPage(0); }}
              >
                {words.severity.error}+ ({errorOrCriticalCount})
              </button>
            ) : null}
            {warnCount > 0 ? (
              <button
                type="button"
                class={severityFilter === "warn" ? "is-active" : undefined}
                onClick={() => { setSeverityFilter("warn"); setPage(0); }}
              >
                {words.severity.warn} ({warnCount})
              </button>
            ) : null}
            {infoCount > 0 ? (
              <button
                type="button"
                class={severityFilter === "info" ? "is-active" : undefined}
                onClick={() => { setSeverityFilter("info"); setPage(0); }}
              >
                {words.severity.info} ({infoCount})
              </button>
            ) : null}
          </div>
          <input
            type="search"
            class="form-input current-findings-search"
            value={query}
            placeholder={words.searchPlaceholder}
            aria-label={words.searchPlaceholder}
            onInput={(event) => {
              setQuery(event.currentTarget.value);
              setPage(0);
            }}
          />
          {severityFilter !== "all" || query ? (
            <button
              type="button"
              class="btn secondary btn-sm"
              onClick={() => {
                setSeverityFilter("all");
                setQuery("");
                setPage(0);
              }}
            >
              {words.clearFilter}
            </button>
          ) : null}
        </div>
      ) : null}
      <ul class="finding-list console-inbox-list">
        {visibleItems.map((item) => (
          <li key={item.inbox_id} class="console-inbox-item">
            <div class="console-inbox-item-head">
              <div class="console-inbox-item-title">
                <StatusPill kind={SEVERITY_PILL[item.severity]} label={words.severity[item.severity]} />
                <strong>{item.title}</strong>
                <span class="finding-kind-chip">
                  {words.categories[item.category] ?? item.category}
                </span>
              </div>
              <span class="muted small">{formatConsoleTimestamp(item.recorded_at)}</span>
            </div>
            {item.body ? <p class="console-inbox-item-body">{formatAlertBody(item.body)}</p> : null}
            {item.correlation_id ? (
              <div class="console-inbox-item-foot">
                <span class="muted small">
                  {words.correlationLabel}: <code class="mono">{item.correlation_id}</code>
                </span>
                <div class="console-inbox-item-links">
                  <CopyButton text={item.correlation_id} />
                  <a
                    class="btn secondary btn-sm"
                    href={routeHref("trace", { params: { correlation: item.correlation_id, data: "live" } })}
                  >
                    {words.openTrace}
                  </a>
                  <a
                    class="btn secondary btn-sm"
                    href={routeHref("audit", { params: { correlation: item.correlation_id, data: "live" } })}
                  >
                    {words.openAudit}
                  </a>
                </div>
              </div>
            ) : null}
          </li>
        ))}
      </ul>
      {filteredItems.length > INBOX_PAGE_SIZE ? (
        <nav class="console-inbox-pager" aria-label={words.title}>
          <button
            type="button"
            class="btn secondary"
            disabled={offset === 0}
            onClick={() => setPage(Math.max(safePage - 1, 0))}
          >
            {words.previous}
          </button>
          <span class="muted small">
            {offset + 1}-{Math.min(offset + INBOX_PAGE_SIZE, filteredItems.length)} / {filteredItems.length}
          </span>
          <button
            type="button"
            class="btn secondary"
            disabled={offset + INBOX_PAGE_SIZE >= filteredItems.length}
            onClick={() => setPage(safePage + 1)}
          >
            {words.next}
          </button>
        </nav>
      ) : null}
    </>
  );
  return (
    <section class="stack console-inbox" id="console-inbox" aria-label={words.title}>
      <div class="section-heading-row">
        <div>
          <h2>{words.title}</h2>
          {!loading && !error ? (
            <p class="muted small">{items.length} {words.retained}. {words.note}</p>
          ) : null}
        </div>
        {!loading && !error && items.length > 0 ? (
          <div class="current-findings-summary-pills" aria-hidden="true">
            {errorOrCriticalCount > 0 ? (
              <StatusPill kind="danger" label={`${words.severity.error}+ ${errorOrCriticalCount}`} />
            ) : null}
            {warnCount > 0 ? (
              <StatusPill kind="warning" label={`${words.severity.warn} ${warnCount}`} />
            ) : null}
            {infoCount > 0 ? (
              <StatusPill kind="info" label={`${words.severity.info} ${infoCount}`} />
            ) : null}
          </div>
        ) : null}
      </div>
      {error ? <p role="alert">{words.unavailable}</p> : null}
      {loading ? <LoadingState label={words.loading} /> : null}
      {!loading && !error && items.length === 0 ? <p>{words.empty}</p> : null}
      {!loading && !error && items.length > 0 ? (
        items.length > 3 && !targeted ? (
          <details class="console-inbox-details">
            <summary>{words.showAlerts} ({items.length})</summary>
            {listContent}
          </details>
        ) : listContent
      ) : null}
    </section>
  );
}
