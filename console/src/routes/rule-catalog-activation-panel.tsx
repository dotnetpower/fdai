import { useState } from "preact/hooks";
import { ErrorState, LoadingState, StatusPill } from "../components/ui";
import { t } from "./i18n/governance";
import type { RuleActivationProposalReceipt } from "./rule-catalog-activation";
import { DetailRow, DetailSection } from "./rule-catalog-components";
import type {
  ActivationHistoryState,
  ActivationState,
  PendingRuleActivationRequest,
} from "./rule-catalog-types";

interface Props {
  readonly ruleId: string;
  readonly activation: ActivationState;
  readonly history: ActivationHistoryState;
  readonly onRequest: (enabled: boolean, reason: string) => Promise<RuleActivationProposalReceipt>;
  readonly onApprove: (request: PendingRuleActivationRequest) => Promise<RuleActivationProposalReceipt>;
}

export function RuleActivationPanel({ ruleId, activation, history, onRequest, onApprove }: Props) {
  if (activation.status === "loading") {
    return <LoadingState label={t("governance.rules.activation.loading")} />;
  }
  if (activation.status === "unavailable") {
    return <p class="muted footnote">{activation.message}</p>;
  }
  if (activation.status === "error") {
    return <ErrorState message={activation.message} />;
  }
  const enabled = activation.data.active_rule_ids.includes(ruleId);
  const pending = activation.data.pending_requests.filter((request) =>
    request.changes.some((change) => change.rule_id === ruleId)
  );
  return (
    <div class="rule-activation-stack">
      <DetailSection title={t("governance.rules.activation.currentTitle")}>
        <div class="pill-row">
          <StatusPill
            kind={enabled ? "success" : "neutral"}
            label={enabled
              ? t("governance.rules.activation.enabled")
              : t("governance.rules.activation.disabled")}
          />
          <StatusPill kind="neutral" label={activation.data.profile_id} />
        </div>
        <dl class="detail-grid rule-activation-facts">
          <DetailRow label={t("governance.rules.activation.generation")} value={activation.data.generation_id} mono />
          <DetailRow label={t("governance.rules.activation.source")} value={activation.data.source} />
          <DetailRow label={t("governance.rules.activation.requestedBy")} value={activation.data.requested_by} mono />
          <DetailRow label={t("governance.rules.activation.approvers")} value={activation.data.approver_ids.join(", ") || "-"} mono />
          <DetailRow label={t("governance.rules.activation.activatedAt")} value={formatTimestamp(activation.data.activated_at)} />
        </dl>
      </DetailSection>
      <ActivationRequestForm enabled={enabled} onRequest={onRequest} />
      <PendingApprovals pending={pending} onApprove={onApprove} />
      <ActivationHistory history={history} />
    </div>
  );
}

function ActivationRequestForm({
  enabled,
  onRequest,
}: {
  readonly enabled: boolean;
  readonly onRequest: Props["onRequest"];
}) {
  const [reason, setReason] = useState("");
  const [state, setState] = useState<"idle" | "submitting" | "accepted" | "error">("idle");
  const [message, setMessage] = useState("");
  const targetEnabled = !enabled;
  async function submit(event: Event): Promise<void> {
    event.preventDefault();
    setState("submitting");
    try {
      const receipt = await onRequest(targetEnabled, reason.trim());
      setMessage(t("governance.rules.activation.requestAccepted", {
        id: receipt.proposal_id,
      }));
      setReason("");
      setState("accepted");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
      setState("error");
    }
  }
  return (
    <DetailSection title={t("governance.rules.activation.requestTitle")}>
      <form class="rule-activation-form" onSubmit={(event) => void submit(event)}>
        <label>
          <span>{t("governance.rules.activation.reason")}</span>
          <textarea
            required
            minLength={20}
            maxLength={1000}
            value={reason}
            onInput={(event) => setReason((event.target as HTMLTextAreaElement).value)}
          />
        </label>
        <button class="btn primary" type="submit" disabled={state === "submitting" || reason.trim().length < 20}>
          {targetEnabled
            ? t("governance.rules.activation.requestEnable")
            : t("governance.rules.activation.requestDisable")}
        </button>
        {state === "accepted" ? <p class="state-inline success" role="status">{message}</p> : null}
        {state === "error" ? <p class="state-inline error" role="alert">{message}</p> : null}
      </form>
    </DetailSection>
  );
}

function PendingApprovals({ pending, onApprove }: {
  readonly pending: readonly PendingRuleActivationRequest[];
  readonly onApprove: Props["onApprove"];
}) {
  const [active, setActive] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  if (pending.length === 0) return null;
  async function approve(request: PendingRuleActivationRequest): Promise<void> {
    setActive(request.request_id);
    setMessage("");
    try {
      await onApprove(request);
      setMessage(t("governance.rules.activation.approvalAccepted"));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setActive(null);
    }
  }
  return (
    <DetailSection title={t("governance.rules.activation.pendingTitle")}>
      <ul class="rule-activation-history" aria-label={t("governance.rules.activation.pendingTitle")}>
        {pending.map((request) => (
          <li key={request.request_id}>
            <div>
              <strong>{request.changes.find((change) => change.rule_id)?.enabled
                ? t("governance.rules.activation.enable")
                : t("governance.rules.activation.disable")}</strong>
              <small>{formatTimestamp(request.requested_at)} - <span class="mono">{request.requested_by}</span></small>
              <p>{request.reason}</p>
            </div>
            <button
              class="btn"
              type="button"
              disabled={active !== null}
              aria-label={`${t("governance.rules.activation.approve")}: ${request.request_id}`}
              onClick={() => void approve(request)}
            >
              {t("governance.rules.activation.approve")}
            </button>
          </li>
        ))}
      </ul>
      {message ? <p class="state-inline" role="status" aria-live="polite">{message}</p> : null}
    </DetailSection>
  );
}

function ActivationHistory({ history }: { readonly history: ActivationHistoryState }) {
  if (history.status === "loading") {
    return <DetailSection title={t("governance.rules.activation.historyTitle")}><LoadingState label={t("governance.rules.activation.historyLoading")} /></DetailSection>;
  }
  if (history.status === "unavailable") {
    return <DetailSection title={t("governance.rules.activation.historyTitle")}><p class="muted footnote">{history.message}</p></DetailSection>;
  }
  if (history.status === "error") {
    return <DetailSection title={t("governance.rules.activation.historyTitle")}><ErrorState message={history.message} /></DetailSection>;
  }
  return (
    <DetailSection title={t("governance.rules.activation.historyTitle")}>
      {history.data.history.length === 0 ? <p class="muted footnote">{t("governance.rules.activation.historyEmpty")}</p> : (
        <ol class="rule-activation-history">
          {history.data.history.map((item) => (
            <li key={item.request_id}>
              <div>
                <div class="pill-row">
                  <StatusPill kind={item.readback_verified ? "success" : "warning"} label={item.status} />
                  <StatusPill kind={item.enabled ? "success" : "neutral"} label={item.enabled ? t("governance.rules.activation.enabled") : t("governance.rules.activation.disabled")} />
                </div>
                <small>{formatTimestamp(item.completed_at)} - <span class="mono">{item.requested_by}</span></small>
                <p>{item.reason}</p>
                <small>{t("governance.rules.activation.approvers")}: {item.approver_ids.join(", ") || "-"}</small>
              </div>
            </li>
          ))}
        </ol>
      )}
    </DetailSection>
  );
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
