import type { OperatorApiClient } from "../api";
import { decodeHilDecisionReceipt, type HilDecisionReceipt } from "../api-hil-decision";

const SLACK_HANDOFF_KEY = "fdai:slack-approval-handoff";
const SLACK_REAUTH_KEY = "fdai:slack-approval-reauth";

export interface SlackHandoffPreview {
  readonly approval_id: string;
  readonly decision: "approve" | "reject";
}

export function readSlackHandoffLink(): string | null {
  const url = new URL(window.location.href);
  const token = url.searchParams.get("handoff");
  if (token !== null) {
    url.searchParams.delete("handoff");
    window.history.replaceState(window.history.state, "", url);
    if (/^[A-Za-z0-9_-]{43}$/.test(token)) {
      window.sessionStorage.setItem(SLACK_HANDOFF_KEY, token);
    }
  }
  const stored = window.sessionStorage.getItem(SLACK_HANDOFF_KEY);
  if (stored !== null && !/^[A-Za-z0-9_-]{43}$/.test(stored)) {
    clearSlackHandoffLink();
    return null;
  }
  return stored;
}

export function clearSlackHandoffLink(): void {
  window.sessionStorage.removeItem(SLACK_HANDOFF_KEY);
  window.sessionStorage.removeItem(SLACK_REAUTH_KEY);
}

export function markSlackReauthentication(token: string): void {
  window.sessionStorage.setItem(SLACK_REAUTH_KEY, token);
}

export function hasSlackReauthentication(token: string): boolean {
  return window.sessionStorage.getItem(SLACK_REAUTH_KEY) === token;
}

export async function handoffRequest(
  client: OperatorApiClient,
  token: string,
  justification?: string,
): Promise<SlackHandoffPreview | HilDecisionReceipt> {
  const authorization = await client.authorizationHeader();
  const response = await fetch(
    new URL(`/hil/slack/handoff/${encodeURIComponent(token)}`, client.operatorApiBaseUrl),
    {
      method: justification === undefined ? "GET" : "POST",
      headers: {
        accept: "application/json",
        ...(authorization ? { authorization } : {}),
        ...(justification === undefined ? {} : { "content-type": "application/json" }),
      },
      credentials: "omit",
      cache: "no-store",
      ...(justification === undefined ? {} : { body: JSON.stringify({ justification }) }),
    },
  );
  if (!response.ok) {
    throw new Error(`Approval handoff is unavailable (${response.status}).`);
  }
  const value: unknown = await response.json();
  if (justification !== undefined) return decodeHilDecisionReceipt(value);
  if (
    typeof value !== "object" || value === null
    || !("approval_id" in value) || typeof value.approval_id !== "string"
    || !("decision" in value) || (value.decision !== "approve" && value.decision !== "reject")
  ) {
    throw new Error("Approval handoff preview is malformed.");
  }
  return value as SlackHandoffPreview;
}
