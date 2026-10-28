import type { OperatorApiClient } from "../api";
import { useCurrentFindings } from "../hooks/use-current-findings";
import { BrowserNotificationControl } from "./browser-notification-control";
import { FindingAttention } from "./finding-attention";

export function FindingNotifications({
  client, principalId,
}: {
  readonly client: OperatorApiClient;
  readonly principalId?: string | null;
}) {
  const feed = useCurrentFindings(client, true, principalId);
  return (
    <>
      <FindingAttention {...feed} principalId={principalId ?? null} />
      <BrowserNotificationControl client={client} principalId={principalId ?? null}
        findings={feed.error ? [] : feed.findings} />
    </>
  );
}
