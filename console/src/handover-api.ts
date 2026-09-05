import type { OperatorApiClient } from "./api";
import {
  decodeHandoverGoal,
  decodeHandoverInvitation,
  type HandoverGoal,
  type HandoverInvitation,
} from "./handover-model";

export async function fetchHandoverInvitation(
  client: OperatorApiClient,
  sessionId: string,
): Promise<HandoverInvitation | null> {
  const params = new URLSearchParams({ session_id: sessionId });
  return decodeHandoverInvitation(
    await request(client, `/handover/goals/invitation?${params.toString()}`),
  );
}

export async function fetchHandoverGoal(
  client: OperatorApiClient,
  goalId: string,
): Promise<HandoverGoal> {
  return decodeHandoverGoal(
    await request(client, `/handover/goals/${encodeURIComponent(goalId)}`),
  );
}

export async function addHandoverEvidence(
  client: OperatorApiClient,
  goalId: string,
  expectedRevision: number,
  evidenceRef: string,
  digest: string,
): Promise<HandoverGoal> {
  return decodeHandoverGoal(await request(
    client,
    `/handover/goals/${encodeURIComponent(goalId)}/evidence`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "idempotency-key": `handover-evidence:${goalId}:${evidenceRef}`,
      },
      body: JSON.stringify({
        expected_revision: expectedRevision,
        evidence_ref: evidenceRef,
        digest,
        kind: "document",
      }),
    },
  ));
}

export async function updateHandoverGoal(
  client: OperatorApiClient,
  goalId: string,
  operation: "snooze" | "decline",
  expectedRevision: number,
): Promise<HandoverGoal> {
  return decodeHandoverGoal(await request(
    client,
    `/handover/goals/${encodeURIComponent(goalId)}/${operation}`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "idempotency-key": `handover:${goalId}:${operation}:${expectedRevision}`,
      },
      body: JSON.stringify({ expected_revision: expectedRevision }),
    },
  ));
}

async function request(
  client: OperatorApiClient,
  path: string,
  init: RequestInit = {},
): Promise<unknown> {
  const headers = new Headers(init.headers);
  headers.set("accept", "application/json");
  const authorization = await client.authorizationHeader();
  if (authorization) headers.set("authorization", authorization);
  const response = await fetch(new URL(path, client.operatorApiBaseUrl), {
    ...init,
    headers,
    credentials: "omit",
  });
  if (!response.ok) {
    throw new Error(`Handover API request failed with HTTP ${response.status}.`);
  }
  return response.json();
}
