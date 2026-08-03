import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  DECK_OPEN_READY_EVENT,
  isDeckOpenListenerReady,
  openDeckWithContext,
  type DeckOpenDetail,
} from "../deck/open-deck";
import {
  useAccessGrantStream,
  type AccessGrantRequestProjection,
} from "../hooks/use-access-grant-stream";
import { t } from "../i18n";

interface Props {
  readonly client: OperatorApiClient;
  readonly principalId?: string | null;
}

export function accessGrantDeckDetail(request: AccessGrantRequestProjection): DeckOpenDetail {
  return {
    sessionKey: `access-grant:${request.request_id}`,
    sessionLabel: t("accessGrants.sessionLabel"),
    contextNote: t("accessGrants.context", {
      capability: request.capability_id,
      scope: request.scope_ref,
      expires: request.expires_at,
    }),
    openingBriefing: t("accessGrants.briefing", {
      capability: request.capability_id,
      scope: request.scope_ref,
    }),
    onlyWhenIdle: true,
  };
}

export function AccessGrantAttention({ client, principalId }: Props) {
  const requests = useAccessGrantStream({
    url: `${client.operatorApiBaseUrl.replace(/\/$/, "")}/access-grants/stream`,
    enabled: Boolean(principalId),
    getAuthorizationHeader: client.authorizationHeader,
  });
  const [deckReady, setDeckReady] = useState(isDeckOpenListenerReady);
  const opened = useRef(new Set<string>());
  const first = requests[0];

  useEffect(() => {
    const markReady = () => setDeckReady(true);
    window.addEventListener(DECK_OPEN_READY_EVENT, markReady);
    return () => window.removeEventListener(DECK_OPEN_READY_EVENT, markReady);
  }, []);

  useEffect(() => {
    if (!deckReady || !first || opened.current.has(first.request_id) || document.hidden) return;
    if (openDeckWithContext(accessGrantDeckDetail(first))) {
      opened.current.add(first.request_id);
    }
  }, [deckReady, first]);

  if (!first) return null;
  return (
    <button
      type="button"
      class="access-grant-attention"
      aria-label={t("accessGrants.open", { count: requests.length })}
      onClick={() => {
        if (openDeckWithContext(accessGrantDeckDetail(first))) {
          opened.current.add(first.request_id);
        }
      }}
    >
      {t("accessGrants.badge", { count: requests.length })}
    </button>
  );
}
