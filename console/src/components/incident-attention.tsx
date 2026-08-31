import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import {
  DECK_OPEN_READY_EVENT,
  isDeckOpenListenerReady,
  openDeckWithContext,
  type DeckOpenDetail,
} from "../deck/open-deck";
import {
  useIncidentAttentionStream,
  type IncidentAttentionProjection,
} from "../hooks/use-incident-attention-stream";
import { t } from "../i18n";

interface Props {
  readonly client: OperatorApiClient;
  readonly principalId?: string | null;
}

const AUTO_INVESTIGATION_PREFIX = "fdai:incident:auto-investigated:";

export function incidentDeckDetail(incident: IncidentAttentionProjection): DeckOpenDetail {
  return {
    sessionKey: `incident:${incident.correlation_id}`,
    sessionLabel: t("incidentAttention.sessionLabel", { ticket: incident.incident_id }),
    contextNote: t("incidentAttention.context", {
      ticket: incident.incident_id,
      correlation: incident.correlation_id,
    }),
    openingBriefing: t("incidentAttention.briefing", {
      severity: incident.severity,
      title: incident.title,
    }),
    prompt: t("incidentAttention.investigationPrompt"),
    submitPrompt: true,
    binding: {
      kind: "incident",
      incidentId: incident.incident_id,
      correlationId: incident.correlation_id,
    },
    onlyWhenIdle: true,
  };
}

export function IncidentAttention({ client, principalId }: Props) {
  const incidents = useIncidentAttentionStream({
    url: `${client.operatorApiBaseUrl.replace(/\/$/, "")}/incidents/stream`,
    principalId: principalId ?? null,
    getAuthorizationHeader: client.authorizationHeader,
  });
  const [deckReady, setDeckReady] = useState(isDeckOpenListenerReady);
  const opened = useRef(new Set<string>());
  const first = incidents[0];

  useEffect(() => {
    const markReady = () => setDeckReady(true);
    window.addEventListener(DECK_OPEN_READY_EVENT, markReady);
    return () => window.removeEventListener(DECK_OPEN_READY_EVENT, markReady);
  }, []);

  useEffect(() => {
    if (
      !deckReady || !first || opened.current.has(first.incident_id) || document.hidden ||
      wasAutoInvestigated(first.incident_id)
    ) return;
    if (openDeckWithContext(incidentDeckDetail(first))) {
      opened.current.add(first.incident_id);
      markAutoInvestigated(first.incident_id);
    }
  }, [deckReady, first]);

  if (!first) return null;
  return (
    <button
      type="button"
      class="topbar-control incident-attention"
      aria-label={t("incidentAttention.open", { count: incidents.length })}
      title={t("incidentAttention.open", { count: incidents.length })}
      onClick={() => {
        if (openDeckWithContext(incidentDeckDetail(first))) {
          opened.current.add(first.incident_id);
        }
      }}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 9v4" />
        <path d="M12 17h.01" />
        <path d="M10.3 3.6 2.5 17.1A2 2 0 0 0 4.2 20h15.6a2 2 0 0 0 1.7-2.9L13.7 3.6a2 2 0 0 0-3.4 0Z" />
      </svg>
      <span class="topbar-control-label">{t("incidentAttention.label")}</span>
      <span class="incident-attention-count">{incidents.length}</span>
    </button>
  );
}

export function wasAutoInvestigated(incidentId: string): boolean {
  try {
    return window.localStorage.getItem(`${AUTO_INVESTIGATION_PREFIX}${incidentId}`) === "1";
  } catch {
    return false;
  }
}

export function markAutoInvestigated(incidentId: string): void {
  try {
    window.localStorage.setItem(`${AUTO_INVESTIGATION_PREFIX}${incidentId}`, "1");
  } catch {
    // Browser storage is best-effort; the in-memory opened set still suppresses this mount.
  }
}
