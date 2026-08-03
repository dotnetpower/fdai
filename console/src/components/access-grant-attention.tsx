import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
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
import {
  reviewAccessGrant,
  type AccessGrantDecisionReceipt,
} from "./access-grant-decision";

interface Props {
  readonly auth: AuthContext;
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

export function AccessGrantAttention({ auth, client, principalId }: Props) {
  const requests = useAccessGrantStream({
    url: `${client.operatorApiBaseUrl.replace(/\/$/, "")}/access-grants/stream`,
    enabled: Boolean(principalId),
    getAuthorizationHeader: client.authorizationHeader,
  });
  const [deckReady, setDeckReady] = useState(isDeckOpenListenerReady);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<AccessGrantDecisionReceipt | null>(null);
  const opened = useRef(new Set<string>());
  const first = requests[0];
  const selected = requests.find((request) => request.request_id === selectedId) ?? first;

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

  useEffect(() => {
    if (selectedId === null && first) setSelectedId(first.request_id);
    if (selectedId !== null && requests.length > 0 && !selected) {
      setSelectedId(first?.request_id ?? null);
    }
  }, [first, requests, selected, selectedId]);

  if (!first) return null;
  return (
    <div class="access-grant-attention-wrap">
      <button
        type="button"
        class="access-grant-attention"
        aria-label={t("accessGrants.open", { count: requests.length })}
        aria-expanded={reviewOpen}
        onClick={() => {
          setReviewOpen(!reviewOpen);
          setReceipt(null);
          setError(null);
        }}
      >
        {t("accessGrants.badge", { count: requests.length })}
      </button>
      {reviewOpen && selected ? (
        <section class="access-grant-review" role="dialog" aria-label={t("accessGrants.reviewTitle")}>
          <header>
            <div>
              <strong>{t("accessGrants.reviewTitle")}</strong>
              <span>{t("accessGrants.reviewBoundary")}</span>
            </div>
            <button type="button" class="icon-button" aria-label={t("accessGrants.close")} onClick={() => setReviewOpen(false)}>×</button>
          </header>
          {requests.length > 1 ? (
            <label>
              {t("accessGrants.request")}
              <select value={selected.request_id} onChange={(event) => {
                setSelectedId(event.currentTarget.value);
                setReason("");
                setReceipt(null);
                setError(null);
              }}>
                {requests.map((request) => (
                  <option key={request.request_id} value={request.request_id}>
                    {request.capability_id} - {request.request_id}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <dl>
            <div><dt>{t("accessGrants.capability")}</dt><dd>{selected.capability_id}</dd></div>
            <div><dt>{t("accessGrants.scope")}</dt><dd>{selected.scope_ref}</dd></div>
            <div><dt>{t("accessGrants.expires")}</dt><dd>{selected.expires_at}</dd></div>
            <div><dt>{t("accessGrants.quorum")}</dt><dd>{selected.quorum}</dd></div>
          </dl>
          <label>
            {t("accessGrants.reason")}
            <textarea
              required
              maxLength={2000}
              value={reason}
              onInput={(event) => setReason(event.currentTarget.value)}
            />
          </label>
          {error ? <div class="error" role="alert">{error}</div> : null}
          {receipt ? (
            <div class="access-grant-review-receipt" role="status">
              {receipt.status === "rejected"
                ? t("accessGrants.rejected")
                : receipt.status === "approved"
                ? t("accessGrants.approved")
                : t("accessGrants.quorumPending", {
                    count: receipt.approved_count,
                    quorum: receipt.quorum,
                  })}
              <span>{t("accessGrants.notApplied")}</span>
            </div>
          ) : null}
          <div class="access-grant-review-actions">
            <button type="button" class="secondary" onClick={() => {
              if (openDeckWithContext(accessGrantDeckDetail(selected))) {
                opened.current.add(selected.request_id);
              }
            }}>{t("accessGrants.openInvestigation")}</button>
            <button type="button" class="secondary" disabled={busy || !reason.trim()} onClick={() => { void decide("reject"); }}>{t("accessGrants.reject")}</button>
            <button type="button" disabled={busy || !reason.trim()} onClick={() => { void decide("approve"); }}>{t("accessGrants.approve")}</button>
          </div>
        </section>
      ) : null}
    </div>
  );

  async function decide(decision: "approve" | "reject"): Promise<void> {
    if (!selected || !reason.trim()) return;
    setBusy(true);
    setError(null);
    setReceipt(null);
    try {
      const next = await reviewAccessGrant(
        auth,
        client.operatorApiBaseUrl,
        selected,
        decision,
        reason,
      );
      setReceipt(next);
      setReason("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }
}
