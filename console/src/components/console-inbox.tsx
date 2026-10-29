import { useEffect } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import { markInboxSeen, unseenInboxItems } from "../console-inbox";
import { useConsoleInbox } from "../hooks/use-console-inbox";
import { getLocale } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { Tooltip } from "./tooltip";
import { LoadingState } from "./ui";

const copy = {
  en: {
    title: "Alerts", unavailable: "Alert inbox unavailable", loading: "Loading alerts...",
    empty: "No retained operational alerts", retained: "retained",
    note: "Operational alerts are recorded here even when no external channel is bound.",
    severity: { info: "Info", warn: "Warning", error: "Error", critical: "Critical" },
  },
  ko: {
    title: "알림", unavailable: "알림함을 가져올 수 없습니다", loading: "알림을 가져오는 중...",
    empty: "보존된 운영 알림이 없습니다", retained: "보존됨",
    note: "외부 채널이 연결되지 않아도 운영 알림은 이곳에 기록됩니다.",
    severity: { info: "정보", warn: "경고", error: "오류", critical: "긴급" },
  },
};

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
  const words = text();
  useEffect(() => {
    if (!loading && !error) markInboxSeen(items);
  }, [items, loading, error]);
  if (!enabled) return null;
  return (
    <section class="stack console-inbox" id="console-inbox" aria-label={words.title}>
      <h2>{words.title}</h2>
      {error ? <p role="alert">{words.unavailable}</p> : null}
      {loading ? <LoadingState label={words.loading} /> : null}
      {!loading && !error && items.length === 0 ? <p>{words.empty}</p> : null}
      {!loading && !error ? <p>{items.length} {words.retained}. {words.note}</p> : null}
      <ul class="finding-list">
        {items.map((item) => (
          <li key={item.inbox_id}>
            <strong>{words.severity[item.severity]} - {item.title}</strong>
            {item.body ? <p>{item.body}</p> : null}
            <p>{formatConsoleTimestamp(item.recorded_at)}</p>
          </li>
        ))}
      </ul>
    </section>
  );
}
