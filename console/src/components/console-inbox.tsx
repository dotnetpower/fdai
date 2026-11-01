import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { markInboxSeen, unseenInboxItems } from "../console-inbox";
import { useConsoleInbox } from "../hooks/use-console-inbox";
import { getLocale } from "../i18n";
import { ROUTE_STATE_EVENT, routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { Tooltip } from "./tooltip";
import { LoadingState, StatusPill, type PillKind } from "./ui";

const INBOX_PAGE_SIZE = 5;

const copy = {
  en: {
    title: "Alerts", unavailable: "Alert inbox unavailable", loading: "Loading alerts...",
    empty: "No retained operational alerts", retained: "retained",
    note: "Operational alerts are recorded here even when no external channel is bound.",
    showAlerts: "Show retained operational alerts",
    previous: "Previous", next: "Next",
    severity: { info: "Info", warn: "Warning", error: "Error", critical: "Critical" },
  },
  ko: {
    title: "알림", unavailable: "알림함을 가져올 수 없습니다", loading: "알림을 가져오는 중...",
    empty: "보존된 운영 알림이 없습니다", retained: "보존됨",
    note: "외부 채널이 연결되지 않아도 운영 알림은 이곳에 기록됩니다.",
    showAlerts: "보존된 운영 알림 펼치기",
    previous: "이전", next: "다음",
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

function text() { return copy[getLocale() === "ko" ? "ko" : "en"]; }
const inboxHref = () => `${routeHref("detection-readiness", { params: { data: "live" } })}#console-inbox`;

export function ConsoleInboxAttention({ client }: { readonly client: OperatorApiClient }) {
  const { items, error, loading } = useConsoleInbox(client);
  const words = text();
  const unseen = error ? 0 : unseenInboxItems(items).length;
  return (
    <Tooltip content={error ? words.unavailable : words.title}>
      <a class="topbar-control" href={inboxHref()}
        aria-label={`${words.title}: ${error ? words.unavailable : unseen}`}>
        <span class="topbar-control-label">{words.title}</span>
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
  const [targeted, setTargeted] = useState(
    () => typeof window !== "undefined" && window.location.hash === "#console-inbox",
  );
  const words = text();
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
  const maxPage = Math.max(Math.ceil(items.length / INBOX_PAGE_SIZE) - 1, 0);
  const safePage = Math.min(page, maxPage);
  const offset = safePage * INBOX_PAGE_SIZE;
  const visibleItems = items.slice(offset, offset + INBOX_PAGE_SIZE);
  const listContent = (
    <>
      <ul class="finding-list console-inbox-list">
        {visibleItems.map((item) => (
          <li key={item.inbox_id} class="console-inbox-item">
            <div class="console-inbox-item-head">
              <div class="console-inbox-item-title">
                <StatusPill kind={SEVERITY_PILL[item.severity]} label={words.severity[item.severity]} />
                <strong>{words.severity[item.severity]} - {item.title}</strong>
              </div>
              <span class="muted small">{formatConsoleTimestamp(item.recorded_at)}</span>
            </div>
            {item.body ? <p class="console-inbox-item-body">{formatAlertBody(item.body)}</p> : null}
          </li>
        ))}
      </ul>
      {items.length > INBOX_PAGE_SIZE ? (
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
            {offset + 1}-{Math.min(offset + INBOX_PAGE_SIZE, items.length)} / {items.length}
          </span>
          <button
            type="button"
            class="btn secondary"
            disabled={offset + INBOX_PAGE_SIZE >= items.length}
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
        <h2>{words.title}</h2>
        {!loading && !error ? (
          <p class="muted small">{items.length} {words.retained}. {words.note}</p>
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
