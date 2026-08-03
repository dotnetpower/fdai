import type { AuthContext } from "../auth";
import { putGovernedJson } from "../governed-command";
import type { AccessGrantRequestProjection } from "../hooks/use-access-grant-stream";

const SAFE_ID = /^[A-Za-z0-9._:-]{1,256}$/;

export interface AccessGrantDecisionReceipt {
  readonly request_id: string;
  readonly status: "pending" | "approved" | "rejected";
  readonly revision: number;
  readonly approved_count: number;
  readonly quorum: number;
  readonly reviewed_at: string;
  readonly permission_applied: false;
  readonly fresh_probe_required: true;
}

export async function reviewAccessGrant(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  request: AccessGrantRequestProjection,
  decision: "approve" | "reject",
  reason: string,
): Promise<AccessGrantDecisionReceipt> {
  const normalizedReason = reason.trim();
  if (!normalizedReason) throw new Error("Access grant review reason is required");
  return decodeAccessGrantDecisionReceipt(await putGovernedJson(
    auth,
    operatorApiBaseUrl,
    `/access-grants/${encodeURIComponent(request.request_id)}/decision`,
    {
      decision,
      reason: normalizedReason,
      expected_revision: request.revision,
    },
    "POST",
  ));
}

export function decodeAccessGrantDecisionReceipt(value: unknown): AccessGrantDecisionReceipt {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Access grant decision response was malformed");
  }
  const receipt = value as Record<string, unknown>;
  if (
    !SAFE_ID.test(String(receipt.request_id ?? ""))
    || !["pending", "approved", "rejected"].includes(String(receipt.status))
    || !nonnegativeInteger(receipt.revision)
    || !nonnegativeInteger(receipt.approved_count)
    || !positiveInteger(receipt.quorum)
    || Number(receipt.approved_count) > Number(receipt.quorum)
    || !validTimestamp(receipt.reviewed_at)
    || receipt.permission_applied !== false
    || receipt.fresh_probe_required !== true
  ) throw new Error("Access grant decision response was malformed");
  return receipt as unknown as AccessGrantDecisionReceipt;
}

function nonnegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0;
}

function positiveInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 1;
}

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 64 && Number.isFinite(Date.parse(value));
}
