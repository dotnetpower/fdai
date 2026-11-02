import { useEffect, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import type { ConsoleDataMode } from "../console-data-mode";
import { t } from "./i18n/approvals";
import {
  clearSlackHandoffLink,
  handoffRequest,
  hasSlackReauthentication,
  markSlackReauthentication,
  readSlackHandoffLink,
  type SlackHandoffPreview,
} from "./slack-handoff-client";

export function SlackApprovalHandoff({
  client, auth, dataMode,
}: {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
  readonly dataMode: ConsoleDataMode;
}) {
  const [token, setToken] = useState(readSlackHandoffLink);
  const [reauthRequested, setReauthRequested] = useState(
    () => token !== null && hasSlackReauthentication(token),
  );
  const [preview, setPreview] = useState<SlackHandoffPreview | null>(null);
  const [justification, setJustification] = useState("");
  const [status, setStatus] = useState<"loading" | "ready" | "recording" | "done" | "unavailable">("loading");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (token === null || dataMode !== "live" || auth.devMode) {
      setStatus("unavailable");
      return;
    }
    let active = true;
    void handoffRequest(client, token).then((value) => {
      if (active) {
        setPreview(value as SlackHandoffPreview);
        setStatus("ready");
      }
    }, (reason: unknown) => {
      if (active) {
        setError(reason instanceof Error ? reason.message : String(reason));
        setStatus("unavailable");
      }
    });
    return () => { active = false; };
  }, [client, token, dataMode, auth.devMode]);

  if (token === null) return null;
  const clear = () => {
    clearSlackHandoffLink();
    setToken(null);
  };
  const record = async () => {
    if (!preview || !reauthRequested || status !== "ready") return;
    setStatus("recording");
    setError(null);
    try {
      await handoffRequest(client, token, justification.trim());
      setStatus("done");
      clearSlackHandoffLink();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      setStatus("unavailable");
    }
  };

  return (
    <section class="settings-iam-panel slack-approval-handoff" aria-labelledby="slack-handoff-title">
      <div class="slack-handoff-head">
        <h2 id="slack-handoff-title">{t("approvals.slackTitle")}</h2>
        <button type="button" class="btn secondary btn-sm" onClick={clear}>
          {t("approvals.slackDismiss")}
        </button>
      </div>
      {status === "loading" ? (
        <div role="status" aria-busy="true" aria-label={t("approvals.slackLoading")} class="loading-skeleton">
          <span aria-hidden="true" class="skeleton-shimmer loading-skeleton-line" />
        </div>
      ) : null}
      {status === "unavailable" ? (
        <div class="state-block state-unavailable" role="alert">
          {t("approvals.slackUnavailable")} {error}
        </div>
      ) : null}
      {status === "done" ? <div class="state-block state-success" role="status">{t("approvals.slackRecorded")}</div> : null}
      {preview && (status === "ready" || status === "recording") ? (
        <div class="approval-decision-form">
          <p><strong>{t("approvals.slackContext", {
            approval: preview.approval_id,
            decision: preview.decision === "approve" ? t("approvals.approve") : t("approvals.reject"),
          })}</strong></p>
          <p class="muted">{t("approvals.slackFreshness")}</p>
          <label class="form-label" for="slack-handoff-justification">
            <span class="approval-justification-head">
              <span>{t("approvals.justification")}</span>
              <small class="muted mono">{justification.trim().length}/2000</small>
            </span>
          </label>
          <textarea
            id="slack-handoff-justification"
            class="form-input"
            value={justification}
            placeholder={t("approvals.justificationPlaceholder")}
            onInput={(event) => setJustification(event.currentTarget.value)}
            maxLength={2000}
          />
          <div class="approval-decision-actions">
            <button
              type="button"
              class="btn"
              disabled={!auth.interactiveSignIn || status === "recording"}
              onClick={() => {
                markSlackReauthentication(token);
                setReauthRequested(true);
                void auth.signIn({ reauthenticate: true });
              }}
            >
              {t("approvals.slackReauthenticate")}
            </button>
            <button
              type="button"
              class="btn btn-primary"
              disabled={status === "recording" || !reauthRequested}
              onClick={() => void record()}
            >
              {status === "recording" ? t("approvals.recordingDecision") : t("approvals.slackRecord")}
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
