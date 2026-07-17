export interface ActionSubmitResult {
  readonly submitted: boolean;
  readonly status: number;
  readonly actionType?: string;
  readonly correlationId?: string;
  readonly reason?: string;
  readonly requiredCapability?: string;
  readonly message?: string;
  readonly incidentId?: string;
  readonly incidentState?: string;
  readonly created?: boolean;
}

function newIdempotencyKey(): string {
  const cryptoLike = (globalThis as { crypto?: { randomUUID?: () => string } }).crypto;
  if (cryptoLike?.randomUUID) return `act-${cryptoLike.randomUUID()}`;
  return `act-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function createActionSubmitter(
  chatUrl: () => string,
  requestHeaders: () => Promise<Record<string, string>>,
): (
  prompt: string,
  sessionId: string | null,
  signal?: AbortSignal,
) => Promise<ActionSubmitResult> {
  return async (prompt, sessionId, signal) => {
    let response: Response;
    try {
      response = await fetch(`${chatUrl()}/action`, {
        method: "POST",
        headers: await requestHeaders(),
        body: JSON.stringify({
          prompt,
          session_id: sessionId ?? undefined,
          idempotency_key: newIdempotencyKey(),
        }),
        signal: signal ?? null,
        credentials: "omit",
      });
    } catch {
      return { submitted: false, status: 0, reason: "error" };
    }
    if (response.status === 404 || response.status === 501) {
      return { submitted: false, status: response.status, reason: "not_wired" };
    }
    let payload: Record<string, unknown> = {};
    try {
      const parsed = await response.json();
      if (typeof parsed === "object" && parsed !== null) {
        payload = parsed as Record<string, unknown>;
      }
    } catch {
      /* fall through - use the status only */
    }
    return {
      submitted: payload.submitted === true,
      status: response.status,
      ...(typeof payload.action_type === "string" ? { actionType: payload.action_type } : {}),
      ...(typeof payload.correlation_id === "string"
        ? { correlationId: payload.correlation_id }
        : {}),
      ...(typeof payload.reason === "string" ? { reason: payload.reason } : {}),
      ...(typeof payload.required_capability === "string"
        ? { requiredCapability: payload.required_capability }
        : {}),
      ...(typeof payload.message === "string" ? { message: payload.message } : {}),
      ...(typeof payload.incident_id === "string" ? { incidentId: payload.incident_id } : {}),
      ...(typeof payload.incident_state === "string"
        ? { incidentState: payload.incident_state }
        : {}),
      ...(typeof payload.created === "boolean" ? { created: payload.created } : {}),
    };
  };
}

export function renderActionResult(result: ActionSubmitResult): string {
  if (result.actionType?.startsWith("incident.") && result.message) return result.message;
  if (result.submitted) {
    return (
      `Submitted "${result.actionType ?? "action"}" to the pipeline for judgment. ` +
      `Nothing runs until Forseti judges it and (if high-risk) an approver signs off - ` +
      `execution is shadow-first. Track it by correlation ${result.correlationId ?? "-"} in the Trace panel.`
    );
  }
  switch (result.reason) {
    case "rbac_capability":
      return (
        "Your role can't submit actions - that needs the Contributor capability " +
        `(${result.requiredCapability ?? "author-draft-pr"}). This console stays read-only for you.`
      );
    case "deny_override_forbidden":
      return (
        "That exact action was already denied, and re-asking can't override a deny. " +
        "If the situation changed, raise it with an approver instead of re-submitting."
      );
    case "invalid_principal":
      return "I couldn't identify your account, so I did not submit that action. Try signing in again.";
    case "incident_confirmation_required":
    case "incident_details_required":
    case "incident_creation_cancelled":
    case "incident_confirmation_expired":
    case "incident_confirmation_invalid":
    case "incident_session_required":
      return result.message ?? "The incident request needs more information before it can continue.";
    case "unmapped_action_intent":
      return "I recognised that as a command, but it maps to no known action yet, so I did not submit it.";
    case "not_wired":
      return "Action submission is not enabled on this deployment (read-only console).";
    default:
      return "I could not submit that action (the action endpoint did not respond).";
  }
}
