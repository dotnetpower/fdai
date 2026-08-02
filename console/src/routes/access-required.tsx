import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { NebulaBackground } from "../components/nebula-background";
import { StatusPill } from "../components/ui";
import { t } from "../i18n";
import {
  identityForMutationIntent,
  type MutationIntentIdentity,
} from "../mutation-intent";
import { submitSelfAccessRequest } from "./settings-iam.command";
import type { IamSelfStatus } from "./settings-iam.model";

interface Props {
  readonly auth: AuthContext;
  readonly client: OperatorApiClient;
  readonly initialStatus: IamSelfStatus;
}

interface AccessCheckGeneration { current: number }

export function beginAccessCheck(generation: AccessCheckGeneration): number {
  generation.current += 1;
  return generation.current;
}

export function isCurrentAccessCheck(
  generation: AccessCheckGeneration,
  candidate: number,
): boolean {
  return generation.current === candidate;
}

export function AccessRequiredRoute({ auth, client, initialStatus }: Props) {
  const statusGeneration = useRef(0);
  const accessRequestIntent = useRef<MutationIntentIdentity | null>(null);
  const [request, setRequest] = useState(initialStatus.request);
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [checking, setChecking] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const checkStatus = async () => {
    const generation = beginAccessCheck(statusGeneration);
    setChecking(true);
    setError(null);
    try {
      const status = await client.iamSelf();
      if (!isCurrentAccessCheck(statusGeneration, generation)) return;
      setRequest(status.request);
      if (status.canAccessConsole) window.location.reload();
    } catch (reason) {
      if (!isCurrentAccessCheck(statusGeneration, generation)) return;
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (isCurrentAccessCheck(statusGeneration, generation)) setChecking(false);
    }
  };

  useEffect(() => () => {
    statusGeneration.current += 1;
  }, []);

  useEffect(() => {
    if (request?.status !== "pending") return;
    const timer = window.setInterval(() => { void checkStatus(); }, 15_000);
    return () => window.clearInterval(timer);
  }, [request?.status]);

  const submit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const normalizedMessage = message.trim();
      const identity = identityForMutationIntent(
        accessRequestIntent.current,
        normalizedMessage,
      );
      accessRequestIntent.current = identity;
      const created = await submitSelfAccessRequest(auth, client.operatorApiBaseUrl, {
        idempotencyKey: identity.idempotencyKey,
        ...(normalizedMessage ? { message: normalizedMessage } : {}),
      });
      accessRequestIntent.current = null;
      setRequest(created);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div class="login-cosmos access-required-page">
      <NebulaBackground intensity={0.72} speed={0.7} class="login-nebula" />
      <main class="access-required-panel" role="main">
        <div class="access-required-heading">
          <span class="login-eyebrow">{t("accessRequired.eyebrow")}</span>
          <h1>{t("accessRequired.title")}</h1>
          <p>{t("accessRequired.description")}</p>
        </div>

        <dl class="access-required-identity">
          <div>
            <dt>{t("accessRequired.account")}</dt>
            <dd>{initialStatus.principal.username ?? initialStatus.principal.subjectId}</dd>
          </div>
          <div>
            <dt>{t("accessRequired.requestedRole")}</dt>
            <dd><StatusPill kind="neutral" label="Reader" /></dd>
          </div>
        </dl>

        {request ? (
          <div class="access-required-status" role="status">
            <StatusPill
              kind={request.status === "rejected" ? "danger" : request.status === "approved" ? "success" : "warning"}
              label={t(`settings.iam.statusValue.${request.status}`)}
            />
            <div>
              <strong>{t(`accessRequired.statusTitle.${request.status}`)}</strong>
              <p>{t(`accessRequired.statusDescription.${request.status}`)}</p>
              <code>{request.requestId}</code>
            </div>
          </div>
        ) : null}
        {!request || request.status === "rejected" ? (
          <div class="access-required-request">
            <label for="access-request-message">{t("accessRequired.message")}</label>
            <textarea
              id="access-request-message"
              maxLength={2000}
              value={message}
              placeholder={t("accessRequired.messagePlaceholder")}
              onInput={(event) => setMessage(event.currentTarget.value)}
            />
            <button
              type="button"
              class="primary"
              disabled={submitting}
              onClick={() => { void submit(); }}
            >
              {submitting ? t("accessRequired.submitting") : t("accessRequired.request")}
            </button>
          </div>
        ) : null}

        {error ? <div class="error" role="alert">{error}</div> : null}
        <div class="access-required-actions">
          <button type="button" disabled={checking} onClick={() => { void checkStatus(); }}>
            {checking ? t("accessRequired.checking") : t("accessRequired.checkAgain")}
          </button>
          <button
            type="button"
            disabled={signingOut}
            onClick={() => {
              setSigningOut(true);
              setError(null);
              void auth.signOut().catch((reason: unknown) => {
                setError(reason instanceof Error ? reason.message : String(reason));
                setSigningOut(false);
              });
            }}
          >
            {signingOut ? t("accessRequired.signingOut") : t("accessRequired.signOut")}
          </button>
        </div>
      </main>
    </div>
  );
}
