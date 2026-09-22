import type { OperatorApiClient } from "../api";
import { postGovernedJson } from "../governed-command";

export interface RuleActivationProposalReceipt {
  readonly accepted: true;
  readonly proposal_id: string;
  readonly operation: "rule.activation-request" | "rule.activation-approve";
  readonly mode: "shadow";
  readonly idempotency_key: string;
  readonly revision: string;
  readonly duplicate: boolean;
}

export async function requestRuleActivation(
  client: OperatorApiClient,
  input: {
    readonly ruleId: string;
    readonly enabled: boolean;
    readonly reason: string;
    readonly generationDigest: string;
  },
): Promise<RuleActivationProposalReceipt> {
  return postRuleActivation(
    client,
    "/rules/activation-changes",
    {
      mode: "shadow",
      reason: input.reason,
      changes: [{ rule_id: input.ruleId, enabled: input.enabled }],
    },
    input.generationDigest,
  );
}

export async function approveRuleActivation(
  client: OperatorApiClient,
  input: {
    readonly requestId: string;
    readonly proposalDigest: string;
  },
): Promise<RuleActivationProposalReceipt> {
  return postRuleActivation(
    client,
    `/rules/activation-changes/${encodeURIComponent(input.requestId)}/approve`,
    { mode: "shadow", decision: "approve" },
    input.proposalDigest,
  );
}

async function postRuleActivation(
  client: OperatorApiClient,
  path: string,
  body: Record<string, unknown>,
  expectedRevision: string,
): Promise<RuleActivationProposalReceipt> {
  const payload = await postGovernedJson(
    client.authorizationHeader,
    client.operatorApiBaseUrl,
    path,
    body,
    crypto.randomUUID(),
    expectedRevision,
  );
  if (!isReceipt(payload)) throw new Error("Invalid Rule activation proposal receipt");
  return payload;
}

function isReceipt(value: unknown): value is RuleActivationProposalReceipt {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return record.accepted === true
    && typeof record.proposal_id === "string"
    && typeof record.revision === "string"
    && typeof record.idempotency_key === "string"
    && (record.operation === "rule.activation-request" || record.operation === "rule.activation-approve")
    && record.mode === "shadow"
    && typeof record.duplicate === "boolean";
}
