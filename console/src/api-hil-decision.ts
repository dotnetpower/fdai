import { postGovernedJson } from "./governed-command";

export interface HilDecisionReceipt {
  readonly approval_id: string;
  readonly idempotency_key: string;
  readonly correlation_id: string;
  readonly decision: "approve" | "reject";
  readonly already_recorded: boolean;
  readonly receipt_ref: string;
  readonly decided_at: string;
  readonly delivered: boolean;
}

export function decodeHilDecisionReceipt(raw: unknown): HilDecisionReceipt {
  const receipt = raw as Partial<HilDecisionReceipt>;
  if (
    typeof receipt.approval_id !== "string"
    || typeof receipt.idempotency_key !== "string"
    || typeof receipt.correlation_id !== "string"
    || (receipt.decision !== "approve" && receipt.decision !== "reject")
    || typeof receipt.already_recorded !== "boolean"
    || typeof receipt.receipt_ref !== "string"
    || typeof receipt.decided_at !== "string"
    || typeof receipt.delivered !== "boolean"
  ) {
    throw new Error("HIL decision receipt is malformed");
  }
  return receipt as HilDecisionReceipt;
}

export async function decideHilApproval(
  authorizationHeader: () => Promise<string | null>,
  operatorApiBaseUrl: string,
  approvalId: string,
  decision: "approve" | "reject",
  justification: string,
  idempotencyKey: string,
): Promise<HilDecisionReceipt> {
  const raw = await postGovernedJson(
    authorizationHeader,
    operatorApiBaseUrl,
    `/hil/${encodeURIComponent(approvalId)}/operator-decision`,
    { decision, justification },
    idempotencyKey,
  );
  return decodeHilDecisionReceipt(raw);
}
