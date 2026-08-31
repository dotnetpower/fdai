import { loadConfig } from "../config";
import { workflowAuthorizationHeader } from "../workflow/validate";
import type { ProcessTransition } from "./processes.model";

export interface ProcessTransitionReceipt {
  readonly proposalId: string;
  readonly operation: string;
  readonly duplicate: boolean;
}

export async function requestProcessTransition(
  processId: string,
  transition: ProcessTransition,
): Promise<ProcessTransitionReceipt> {
  if (transition.method !== "POST") {
    throw new Error("Only runtime-rechecked POST transitions can be requested.");
  }
  const expectedPath = `/workflows/${processId}/${transition.id}`;
  if (transition.path !== expectedPath) {
    throw new Error("Process transition path does not match the selected Process.");
  }
  const cfg = loadConfig();
  const base = cfg.operatorApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
  const headers: Record<string, string> = {
    accept: "application/json",
    "if-match": String(transition.expected_revision),
    "idempotency-key": `process:${processId}:${transition.id}:revision:${transition.expected_revision}`,
  };
  const authorization = await workflowAuthorizationHeader();
  if (authorization !== null) headers.authorization = authorization;
  const response = await fetch(`${base.replace(/\/$/, "")}${transition.path}`, {
    method: "POST",
    headers,
    credentials: "omit",
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`Process transition returned invalid JSON (HTTP ${response.status}).`);
  }
  if (!response.ok) {
    const detail = isRecord(payload) && typeof payload["detail"] === "string"
      ? payload["detail"]
      : `HTTP ${response.status}`;
    throw new Error(detail);
  }
  if (
    response.status !== 202
    || !isRecord(payload)
    || payload["accepted"] !== true
    || typeof payload["proposal_id"] !== "string"
    || typeof payload["operation"] !== "string"
    || typeof payload["duplicate"] !== "boolean"
  ) {
    throw new Error("Process transition request returned an invalid acceptance receipt.");
  }
  const expectedOperation = `workflow.${transition.id}-request`;
  if (payload["operation"] !== expectedOperation) {
    throw new Error("Process transition acceptance receipt does not match the request.");
  }
  return {
    proposalId: payload["proposal_id"],
    operation: payload["operation"],
    duplicate: payload["duplicate"],
  };
}

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
